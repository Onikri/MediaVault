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
from pathlib import Path
from urllib.parse import urlsplit

from manga_source_tags import unique, clean_label
from manga_tag_policy import current, normalize, project_row

FORMAT = {'manga', 'manhwa', 'manhua', 'webtoon'}

def tag_key(value):
    return current().key(value)


def _text(value, limit=500):
    return ' '.join(str(value or '').split())[:limit]

def _aliases(row):
    values = [row.get('title'), *list((row.get('titles') or {}).values()), *(row.get('aliases') if isinstance(row.get('aliases'), list) else [])]
    return list(dict.fromkeys(_text(v,500) for v in values if isinstance(v,str) and v.strip()))[:60]

def _url(row):
    # Source URL outranks a Suwayomi local bridge reference.
    value = row.get('sourceUrl') or row.get('sourceURL') or row.get('url') or ''
    if not isinstance(value, str):
        return ''
    try:
        p = urlsplit(value)
    except ValueError:
        return ''
    if p.scheme != 'https' or not p.hostname or p.username or p.password or len(value) > 2048:
        return ''
    if p.hostname in {'localhost', '127.0.0.1'} or p.hostname.endswith('.local'):
        return ''
    return value

def initialize(conn):
    conn.create_function('catalog_normalize',1,normalize,deterministic=True)
    conn.create_function('catalog_tag_label',1,lambda key:current().label(key))
    conn.create_function('catalog_tag_visible',2,lambda label,url:bool(current().key(label,__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(url or '').hostname or '')))
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
        PRIMARY KEY(title_id,category,tag_key,original));
      CREATE INDEX IF NOT EXISTS catalog_tags_key ON catalog_tags(tag_key,title_id);
      CREATE TABLE IF NOT EXISTS catalog_tag_facts(
        title_id TEXT NOT NULL,category TEXT NOT NULL,original TEXT NOT NULL,
        PRIMARY KEY(title_id,category,original));
      CREATE TABLE IF NOT EXISTS catalog_policy_state(name TEXT PRIMARY KEY,value TEXT NOT NULL);
    ''')
    from content_vocabulary import initialize as initialize_vocabulary
    initialize_vocabulary(conn)
    revision=conn.execute("SELECT value FROM catalog_policy_state WHERE name='revision'").fetchone()
    if not revision or revision[0]!=current().revision:
        with conn:reindex(conn)

def upsert(conn, rows, source_id='', timestamp=None):
    """Idempotent; weak search results never erase enriched source tags."""
    now = float(time.time() if timestamp is None else timestamp)
    count = 0
    from content_vocabulary import add,bump,host
    vocabulary_added=0
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
        inspected = isinstance(row.get('episodes'), list) or row.get('metadataInspected') is True
        fields = ('id','ids','titles','title', 'provider', 'providerName', 'sourceId', 'sourceUrl', 'url',
                  'language', 'format', 'cover', 'year', 'description', 'readingMode',
                  'adult', 'age', 'aliases', 'tags', 'genres', 'identityTitles',
                  'authors', 'artists', 'status', 'truncated','sourceMetadataVersion')
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
        data['aliases'] = list(dict.fromkeys([*_aliases(row), *_aliases(previous)]))[:60]
        raw = {}
        for category in ('tags', 'genres'):
            input_values = row.get(category)
            fresh = unique(input_values) if isinstance(input_values, list) else []
            prior = unique(previous.get(category) or [])
            data[category] = list(dict.fromkeys([*prior, *fresh]))[:120]
            raw[category] = fresh
        chapters = row.get('episodes') if isinstance(row.get('episodes'),list) else None
        chapter_count = len({(v.get('season'), str(v.get('number')))
                             for v in chapters if isinstance(v, dict)}) if chapters is not None else None
        chapter_count = chapter_count if chapter_count is not None else (old[4] if old else None)
        data['chapterCount'] = chapter_count
        data['tagStatus'] = ('present' if data['tags'] or data['genres'] else
                             'not_provided_in_detail' if inspected else
                             old[3] if old else 'not_requested')
        data['indexedAt'] = now
        data['metadataChecked']=inspected or previous.get('metadataChecked',False)
        search = normalize(' '.join([title, *_aliases(data)]))[:5000]
        lang = _text(data.get('language') or 'und', 8)
        kind = _text(data.get('format') or '', 20)
        if kind not in FORMAT:
            kind = ''
        adult = 1 if data.get('adult') is True else 0 if data.get('adult') is False else None
        year = data.get('year')
        year = int(year) if isinstance(year, int) and not isinstance(year, bool) and 1800 <= year <= 2200 else None
        sid = _text(row.get('sourceId') or source_id or (previous.get('sourceId') or provider), 100)
        data['sourceId']=sid
        data['url']=data.get('url') or url
        data['kind']='manga'
        facts={category:raw[category] for category in ('tags','genres')}
        if not current().include_discovered:data=project_row(data)
        data['tagStatus']='present' if data['tags'] or data['genres'] else 'not_provided_in_detail' if data['metadataChecked'] else 'not_requested'
        clean_metadata = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        if len(clean_metadata.encode('utf-8')) > 32000:
            # Never let an abnormally large upstream payload poison the index.
            continue
        for category in ('tags','genres'):
            for label in facts[category]:
                conn.execute('INSERT OR IGNORE INTO catalog_tag_facts VALUES(?,?,?)',(identity,category,label))
                vocabulary_added+=add(conn,label,host(url),category,'manga')
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
        conn.execute('DELETE FROM catalog_tags WHERE title_id=?',(identity,))
        policy=current();source=urlsplit(url).hostname or ''
        for category in ('tags','genres'):
            for (label,) in conn.execute('SELECT original FROM catalog_tag_facts WHERE title_id=? AND category=?',(identity,category)).fetchall():
                key = policy.identity(label,source) if policy.include_discovered else policy.key(label,source)
                if not key:
                    continue
                # Keep each original provider name; aliases for the same key can
                # be recovered from the JSON metadata.
                conn.execute('''INSERT OR IGNORE INTO catalog_tags(
                   title_id,category,tag_key,original) VALUES(?,?,?,?)''',
                   (identity,{'tag':'tags','genre':'genres'}.get(policy.rules.get(key,{}).get('category'),category),key,label))
        count += 1
    if vocabulary_added:bump(conn)
    return count

def _conditions(q='', tag='', provider='', format='', source_id='', *, genre='', language='all', year='', age='', source_ids=()):
    sql = []
    args = []
    if q:
        for word in normalize(q)[:160].split()[:12]:
            sql.append("t.search_text LIKE ? ESCAPE '\\'")
            args.append('%'+word.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
    for category,values in ((None,tag),('genres',genre)):
        for value in (values if isinstance(values,(list,tuple)) else str(values or '').split(','))[:12]:
            if not str(value).strip():continue
            sql.append('EXISTS(SELECT 1 FROM catalog_tags x WHERE x.title_id=t.id AND x.tag_key=?'+(' AND x.category=?' if category else '')+')')
            args.append(tag_key(value) if clean_label(value) else '')
            if category:args.append(category)
    if provider:
        sql.append('t.provider=?')
        args.append(provider)
    if source_id:
        sql.append('t.source_id=?')
        args.append(source_id)
    if source_ids:
        sql.append('t.source_id IN ('+','.join('?' for _ in source_ids)+')')
        args.extend(source_ids)
    if format:
        sql.append('t.format=?')
        args.append({'манга':'manga','манхва':'manhwa','маньхуа':'manhua','вебтун':'webtoon'}.get(normalize(format),format))
    if language and language!='all':
        sql.append('t.language=?');args.append(language)
    if year:
        sql.append('t.year=?');args.append(str(year))
    if age=='adult':sql.append('(t.adult=1 OR CAST(json_extract(t.metadata,\'$.age\') AS INTEGER)>=18)')
    elif age=='under18':sql.append('(t.adult=0 OR CAST(json_extract(t.metadata,\'$.age\') AS INTEGER)<18)')
    return (' WHERE '+' AND '.join(sql) if sql else ''), args

# Whole-catalogue orders for paging. Every order ends in the id, so a title
# keeps one place across page requests while the crawler rewrites rows.
SORTS = {
    'new': 't.year IS NULL,t.year DESC,t.id',
    'old': 't.year IS NULL,t.year,t.id',
    'title': 't.title COLLATE NOCASE,t.id',
    'length': 't.chapter_count IS NULL,t.chapter_count DESC,t.id',
    'added': 't.first_seen DESC,t.id',
}

def browse(conn, *, q='', tag='', provider='', format='', source_id='', limit=30, offset=0, sort='', **filters):
    limit = min(100,max(1,int(limit)))
    offset = min(100000,max(0,int(offset)))
    where,args = _conditions(q,tag,provider,format,source_id,**filters)
    total = conn.execute('SELECT COUNT(*) FROM catalog_titles t'+where,args).fetchone()[0]
    rank=''
    ranking=[]
    if normalize(q):
        rank="CASE WHEN catalog_normalize(t.title)=? THEN 0 WHEN EXISTS(SELECT 1 FROM json_each(t.metadata,'$.aliases') a WHERE catalog_normalize(a.value)=?) THEN 1 WHEN catalog_normalize(t.title) LIKE ? ESCAPE '\\' THEN 2 ELSE 3 END,"
        term=normalize(q);ranking=[term,term,term+'%']
    values = conn.execute('SELECT id,metadata,chapter_count,tag_state,updated FROM catalog_titles t'+where+
                          ' ORDER BY '+rank+(SORTS.get(sort) or ('t.updated DESC,t.id' if rank else SORTS['new']))+' LIMIT ? OFFSET ?', [*args,*ranking,limit,offset]).fetchall()
    result=[]
    for identity,metadata,chapters,status,updated in values:
        row=_public_metadata(json.loads(metadata))
        row.update({'catalogId':identity,'chapterCount':chapters,'tagStatus':status,'indexedAt':updated})
        result.append(row)
    return {'total':total,'limit':limit,'offset':offset,'items':result}

def title(conn, identity):
    row = conn.execute('SELECT metadata,chapter_count,tag_state FROM catalog_titles WHERE id=?',(identity,)).fetchone()
    if not row:
        return None
    result = _public_metadata(json.loads(row[0]))
    result['catalogId'] = identity
    result['chapterCount'] = row[1]
    result['tagStatus'] = row[2]
    return result

def _public_metadata(row):
    # Older index entries may predate the reader URL and taxonomy normalization.
    row={**row,'kind':'manga','url':row.get('url') or row.get('sourceUrl','')}
    for category in ('tags','genres'):row[category]=unique(row.get(category) or [])
    return project_row(row)


def reindex(conn,policy=None):
    """Rebuild the projection from retained source facts, including removals."""
    policy=policy or current()
    from content_vocabulary import add,bump
    rows=conn.execute('SELECT id,metadata FROM catalog_titles ORDER BY id')
    count=0;added=0
    conn.execute('DELETE FROM catalog_tags')
    for identity,raw in rows:
        count+=1
        row=json.loads(raw)
        for category in ('tags','genres'):
            if not conn.execute('SELECT 1 FROM catalog_tag_facts WHERE title_id=? AND category=? LIMIT 1',(identity,category)).fetchone():
                for label in unique(row.get(category) or []):
                    conn.execute('INSERT OR IGNORE INTO catalog_tag_facts VALUES(?,?,?)',(identity,category,label))
        source=urlsplit(row.get('sourceUrl') or row.get('url') or '').hostname or ''
        raw_facts={}
        for category in ('tags','genres'):
            facts=[v[0] for v in conn.execute('SELECT original FROM catalog_tag_facts WHERE title_id=? AND category=?',(identity,category))]
            raw_facts[category]=facts
            for label in facts:
                added+=add(conn,label,source,category,'manga')
                key=policy.identity(label,source) if policy.include_discovered else policy.key(label,source)
                if key:conn.execute('INSERT OR IGNORE INTO catalog_tags VALUES(?,?,?,?)',(identity,{'tag':'tags','genre':'genres'}.get(policy.rules.get(key,{}).get('category'),category),key,label))
        row.update(raw_facts if policy.include_discovered else policy.facts(raw_facts,source))
        state='present' if row['tags'] or row['genres'] else 'not_provided_in_detail' if row.get('metadataChecked') else 'not_requested'
        row['tagStatus']=state
        conn.execute('UPDATE catalog_titles SET metadata=?,tag_state=? WHERE id=?',(json.dumps(row,ensure_ascii=False),state,identity))
    conn.execute("INSERT OR REPLACE INTO catalog_policy_state VALUES('revision',?)",(policy.revision,))
    if added:bump(conn)
    return count


def tags(conn, *, provider='', source_id='', limit=100, q='', **filters):
    where,params = _conditions(provider=provider,source_id=source_id,**filters)
    where+=(' AND ' if where else ' WHERE ')+'catalog_tag_visible(g.original,t.source_url)=1'
    if q:
        needle='%'+normalize(q).replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        where+=(' AND ' if where else ' WHERE ')+"(g.tag_key LIKE ? ESCAPE '\\' OR catalog_normalize(g.original) LIKE ? ESCAPE '\\' OR catalog_normalize(catalog_tag_label(g.tag_key)) LIKE ? ESCAPE '\\')"
        params.extend([needle,needle,needle])
    rows=conn.execute('''SELECT g.category,g.tag_key,MIN(g.original),COUNT(DISTINCT g.title_id),json_group_array(DISTINCT g.original)
                         FROM catalog_tags g JOIN catalog_titles t ON t.id=g.title_id'''+where+
                      ''' GROUP BY g.category,g.tag_key ORDER BY COUNT(DISTINCT g.title_id) DESC,g.tag_key LIMIT ?''',
                      [*params,min(500,max(1,int(limit)))]).fetchall()
    return {'tags':[{'type':kind,'key':key,'original':original,'originalLabels':json.loads(originals) if originals else [],'works':count}
                    for kind,key,original,count,originals in rows if clean_label(original)]}

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
        "SELECT id,source_url FROM catalog_titles WHERE inspected=0 "
        "ORDER BY updated DESC LIMIT ?",(limit,))]
