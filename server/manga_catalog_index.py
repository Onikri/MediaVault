"""Persistent, metadata-only manga catalogue built from verified public source data.

The existing manga discovery queue supplies initial titles. Title inspection
enriches them with provider tags/genres. No chapter images, cookies, or login
information are stored, and no full-site crawling is triggered implicitly.
"""
import hashlib
import json
import re
import time
import unicodedata
from urllib.parse import urlsplit

from manga_source_tags import unique

FORMAT = {'manga', 'manhwa', 'manhua', 'webtoon'}
SYNONYMS = {
    'fantasy': 'фэнтези',
    'romance': 'романтика', 'romantic': 'романтика',
    'comedy': 'комедия', 'drama': 'драма',
    'action': 'экшен', 'боевик': 'экшен',
    'adventure': 'приключения',
    'horror': 'ужасы', 'mystery': 'детектив',
    'slice of life': 'повседневность',
}

def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split()).strip()

def tag_key(value):
    name = normalize(value)
    return SYNONYMS.get(name, name)

def _text(value, limit=500):
    return ' '.join(str(value or '').split())[:limit]

def _aliases(row):
    values = [row.get('title'), *(row.get('aliases') if isinstance(row.get('aliases'), list) else [])]
    return unique(v for v in values if isinstance(v, str))

def _url(row):
    # Source URL outranks a Suwayomi local bridge reference.
    value = row.get('sourceUrl') or row.get('sourceURL') or row.get('url') or ''
    if not isinstance(value, str):
        return ''
    p = urlsplit(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or len(value) > 2048:
        return ''
    if p.hostname in {'localhost', '127.0.0.1'} or p.hostname.endswith('.local'):
        return ''
    return value

def initialize(conn):
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS catalog_titles(
        id TEXT PRIMARY KEY,provider TEXT NOT NULL,source_id TEXT NOT NULL,
        source_url TEXT NOT NULL,title TEXT NOT NULL,search_text TEXT NOT NULL,
        language TEXT NOT NULL,format TEXT NOT NULL,adult INTEGER,
        year INTEGER,chapter_count INTEGER,tag_state TEXT NOT NULL,
        metadata TEXT NOT NULL,first_seen REAL NOT NULL,updated REAL NOT NULL,
        inspected REAL NOT NULL DEFAULT 0,
        UNIQUE(provider,source_url));
      CREATE INDEX IF NOT EXISTS catalog_titles_search ON catalog_titles(search_text);
      CREATE INDEX IF NOT EXISTS catalog_titles_source ON catalog_titles(source_id,updated);
      CREATE INDEX IF NOT EXISTS catalog_titles_recent ON catalog_titles(updated DESC);
      CREATE TABLE IF NOT EXISTS catalog_tags(
        title_id TEXT NOT NULL,category TEXT NOT NULL,tag_key TEXT NOT NULL,
        original TEXT NOT NULL,
        PRIMARY KEY(title_id,category,tag_key));
      CREATE INDEX IF NOT EXISTS catalog_tags_key ON catalog_tags(tag_key,title_id);
    ''')

def upsert(conn, rows, source_id='', timestamp=None):
    """Idempotent; weak search results never erase enriched source tags."""
    now = float(time.time() if timestamp is None else timestamp)
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = _text(row.get('title'), 500)
        provider = _text(row.get('provider'), 120)
        url = _url(row)
        if not title or not provider or not url or row.get('kind', 'manga') != 'manga':
            continue
        identity = hashlib.sha256((provider + '\x00' + url).encode('utf-8')).hexdigest()[:32]
        old = conn.execute('SELECT metadata,first_seen,inspected,tag_state,chapter_count FROM catalog_titles WHERE id=?',
                           (identity,)).fetchone()
        # The discovery worker may supply a partial metadata-only row.
        previous = json.loads(old[0]) if old else {}
        inspected = isinstance(row.get('episodes'), list)
        fields = ('title', 'provider', 'providerName', 'sourceId', 'sourceUrl',
                  'language', 'format', 'cover', 'year', 'description', 'readingMode',
                  'adult', 'age', 'aliases', 'tags', 'genres', 'identityTitles',
                  'authors', 'artists', 'status')
        data = dict(previous)
        for key in fields:
            value = row.get(key)
            if isinstance(value, (str, list, dict)) and not value:
                continue
            if value is not None:
                data[key] = value
        data['title'] = title
        data['provider'] = provider
        data['sourceUrl'] = url
        data['aliases'] = list(dict.fromkeys([*_aliases(previous), *_aliases(row)]))[:60]
        raw = {}
        for category in ('tags', 'genres'):
            input_values = row.get(category)
            fresh = unique(input_values) if isinstance(input_values, list) else []
            prior = unique(previous.get(category) or [])
            data[category] = list(dict.fromkeys([*prior, *fresh]))[:120]
            raw[category] = fresh
        chapters = row.get('episodes') if inspected else None
        chapter_count = len({(v.get('season'), str(v.get('number')))
                             for v in chapters if isinstance(v, dict)}) if inspected else None
        chapter_count = chapter_count if chapter_count is not None else (old[4] if old else None)
        data['chapterCount'] = chapter_count
        data['tagStatus'] = ('present' if data['tags'] or data['genres'] else
                             'not_provided_in_detail' if inspected else
                             old[3] if old else 'not_requested')
        data['indexedAt'] = now
        clean_metadata = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        if len(clean_metadata.encode('utf-8')) > 32000:
            # Never let an abnormally large upstream payload poison the index.
            continue
        search = normalize(' '.join([title, *_aliases(data)]))[:5000]
        lang = _text(data.get('language') or 'ru', 8)
        kind = _text(data.get('format') or '', 20)
        if kind not in FORMAT:
            kind = ''
        adult = 1 if data.get('adult') is True else 0 if data.get('adult') is False else None
        year = data.get('year')
        year = int(year) if isinstance(year, int) and not isinstance(year, bool) and 1800 <= year <= 2200 else None
        sid = _text(row.get('sourceId') or source_id or (previous.get('sourceId') or provider), 100)
        conn.execute('''INSERT INTO catalog_titles(
             id,provider,source_id,source_url,title,search_text,language,format,
             adult,year,chapter_count,tag_state,metadata,first_seen,updated,inspected)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
             ON CONFLICT(id) DO UPDATE SET
             source_id=excluded.source_id,title=excluded.title,
             search_text=excluded.search_text,language=excluded.language,
             format=excluded.format,adult=excluded.adult,year=excluded.year,
             chapter_count=excluded.chapter_count,tag_state=excluded.tag_state,
             metadata=excluded.metadata,updated=excluded.updated,
             inspected=excluded.inspected''',
             (identity,provider,sid,url,title,search,lang,kind,adult,year,chapter_count,
              data['tagStatus'],clean_metadata,old[1] if old else now,now,
              now if inspected else old[2] if old else 0))
        for category in ('tags','genres'):
            for label in data[category]:
                key = tag_key(label)
                if not key:
                    continue
                # Keep each original provider name; aliases for the same key can
                # be recovered from the JSON metadata.
                conn.execute('''INSERT OR IGNORE INTO catalog_tags(
                   title_id,category,tag_key,original) VALUES(?,?,?,?)''',
                   (identity,category,key,label))
        count += 1
    return count

def _conditions(q='', tag='', provider='', format='', source_id=''):
    sql = []
    args = []
    if q:
        needle = normalize(q)[:160].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        sql.append("t.search_text LIKE ? ESCAPE '\\'")
        args.append('%'+needle+'%')
    if tag:
        sql.append('EXISTS(SELECT 1 FROM catalog_tags x WHERE x.title_id=t.id AND x.tag_key=?)')
        args.append(tag_key(tag))
    if provider:
        sql.append('t.provider=?')
        args.append(provider)
    if source_id:
        sql.append('t.source_id=?')
        args.append(source_id)
    if format:
        sql.append('t.format=?')
        args.append(format)
    return (' WHERE '+' AND '.join(sql) if sql else ''), args

def browse(conn, *, q='', tag='', provider='', format='', source_id='', limit=30, offset=0):
    limit = min(100,max(1,int(limit)))
    offset = min(100000,max(0,int(offset)))
    where,args = _conditions(q,tag,provider,format,source_id)
    total = conn.execute('SELECT COUNT(*) FROM catalog_titles t'+where,args).fetchone()[0]
    values = conn.execute('SELECT id,metadata,chapter_count,tag_state,updated FROM catalog_titles t'+where+
                          ' ORDER BY updated DESC,id LIMIT ? OFFSET ?', [*args,limit,offset]).fetchall()
    result=[]
    for identity,metadata,chapters,status,updated in values:
        row=json.loads(metadata)
        row.update({'catalogId':identity,'chapterCount':chapters,'tagStatus':status,'indexedAt':updated})
        result.append(row)
    return {'total':total,'limit':limit,'offset':offset,'items':result}

def title(conn, identity):
    row = conn.execute('SELECT metadata,chapter_count,tag_state FROM catalog_titles WHERE id=?',(identity,)).fetchone()
    if not row:
        return None
    result = json.loads(row[0])
    result['catalogId'] = identity
    result['chapterCount'] = row[1]
    result['tagStatus'] = row[2]
    return result

def tags(conn, *, provider='', source_id='', limit=100):
    where,params = _conditions(provider=provider,source_id=source_id)
    rows=conn.execute('''SELECT g.category,g.tag_key,MIN(g.original),COUNT(DISTINCT g.title_id)
                         FROM catalog_tags g JOIN catalog_titles t ON t.id=g.title_id'''+where+
                      ''' GROUP BY g.category,g.tag_key ORDER BY COUNT(DISTINCT g.title_id) DESC,g.tag_key LIMIT ?''',
                      [*params,min(500,max(1,int(limit)))]).fetchall()
    return {'tags':[{'type':kind,'key':key,'original':original,'works':count}
                    for kind,key,original,count in rows]}

def stats(conn):
    total = conn.execute('SELECT COUNT(*) FROM catalog_titles').fetchone()[0]
    tagged = conn.execute("SELECT COUNT(*) FROM catalog_titles WHERE tag_state='present'").fetchone()[0]
    rows = conn.execute('''SELECT provider,COUNT(*),
                  SUM(CASE WHEN tag_state='present' THEN 1 ELSE 0 END)
                  FROM catalog_titles GROUP BY provider ORDER BY COUNT(*) DESC''').fetchall()
    return {'totalTitles':total,'titlesWithTags':tagged,
            'perProvider':[{'provider':p,'titles':n,'withTags':t or 0} for p,n,t in rows],
            'note':'Only discovered titles are indexed; full upstream catalogue coverage is not implied.'}


def backfill(conn, *, offset=0, limit=250):
    """Copy bounded existing discovery cache rows into the permanent index."""
    offset = min(50000, max(0, int(offset)))
    limit = min(500, max(1, int(limit)))
    rows = conn.execute('SELECT source_id,metadata FROM titles ORDER BY updated DESC LIMIT ? OFFSET ?',
                        (limit,offset)).fetchall()
    imported = 0
    for source_id, metadata in rows:
        try:
            value = json.loads(metadata)
            imported += upsert(conn,[value],source_id=source_id)
        except (ValueError,TypeError,KeyError):
            continue
    return {'scanned':len(rows),'imported':imported,
            'nextOffset':offset+len(rows) if len(rows)==limit else None}

def missing_tags(conn, limit=3):
    """Metadata-only titles eligible for an explicit on-demand enrich request."""
    limit = min(3,max(1,int(limit)))
    return [(row[0],row[1]) for row in conn.execute(
        "SELECT id,source_url FROM catalog_titles WHERE tag_state!='present' AND inspected=0 "
        "ORDER BY updated DESC LIMIT ?",(limit,))]
