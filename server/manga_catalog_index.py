"""Persistent, metadata-only manga catalogue built from verified public source data.

The existing manga discovery queue supplies initial titles. Title inspection
enriches them with provider tags/genres. No chapter images, cookies, or login
information are stored, and no full-site crawling is triggered implicitly.
"""
import hashlib
import json
import os
import re
import threading
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

from manga_source_tags import unique, clean_label
from catalog_labels import readable_label
from manga_tag_policy import current, normalize, project_row
from release_status import condition as status_condition, initialize_index as initialize_status_index, work_status

FORMAT = {'manga', 'manhwa', 'manhua', 'webtoon','comic','rumanga'}
LABEL_INDEX_REVISION='readable-labels-v1'
WORK_TAG_INDEX_REVISION='work-tags-v1'

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

def _work_tag_triggers(conn):
    conn.execute('''CREATE TRIGGER IF NOT EXISTS catalog_work_tags_add AFTER INSERT ON catalog_work_tags BEGIN
        INSERT INTO catalog_tag_stats(category,tag_key,works) VALUES(NEW.category,NEW.tag_key,1)
        ON CONFLICT(category,tag_key) DO UPDATE SET works=works+1;
      END''')
    conn.execute('''CREATE TRIGGER IF NOT EXISTS catalog_work_tags_remove AFTER DELETE ON catalog_work_tags BEGIN
        UPDATE catalog_tag_stats SET works=works-1 WHERE category=OLD.category AND tag_key=OLD.tag_key;
        DELETE FROM catalog_tag_stats WHERE category=OLD.category AND tag_key=OLD.tag_key AND works<=0;
      END''')

def initialize_work_tags(conn):
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS catalog_work_tags(
        work_key TEXT NOT NULL,category TEXT NOT NULL,tag_key TEXT NOT NULL,
        PRIMARY KEY(work_key,category,tag_key)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS catalog_work_tags_lookup ON catalog_work_tags(category,tag_key,work_key);
      CREATE TABLE IF NOT EXISTS catalog_tag_stats(
        category TEXT NOT NULL,tag_key TEXT NOT NULL,works INTEGER NOT NULL,
        PRIMARY KEY(category,tag_key)) WITHOUT ROWID;
    ''')
    _work_tag_triggers(conn)

def rebuild_work_tags(conn):
    """Compile source-level tag facts into one indexed row per work and tag."""
    conn.execute('DROP TRIGGER IF EXISTS catalog_work_tags_add')
    conn.execute('DROP TRIGGER IF EXISTS catalog_work_tags_remove')
    conn.execute('DELETE FROM catalog_work_tags');conn.execute('DELETE FROM catalog_tag_stats')
    conn.execute('''INSERT OR IGNORE INTO catalog_work_tags(work_key,category,tag_key)
                    SELECT t.work_key,g.category,g.tag_key FROM catalog_tags g
                    JOIN catalog_titles t ON t.id=g.title_id WHERE length(t.work_key)>0''')
    conn.execute('''INSERT INTO catalog_tag_stats(category,tag_key,works)
                    SELECT category,tag_key,COUNT(*) FROM catalog_work_tags GROUP BY category,tag_key''')
    _work_tag_triggers(conn)
    conn.execute("INSERT OR REPLACE INTO catalog_policy_state VALUES('work-tag-index',?)",(WORK_TAG_INDEX_REVISION,))

def refresh_work_tags(conn,work_keys):
    keys=sorted({key for key in work_keys if key})
    if not keys:return
    # initialize() owns schema setup. executescript() commits implicitly in
    # sqlite3, so calling it here would publish a crawler batch halfway
    # through its transaction to concurrent catalogue readers.
    marks=','.join('?' for _ in keys)
    conn.execute('DELETE FROM catalog_work_tags WHERE work_key IN ('+marks+')',keys)
    conn.execute('''INSERT OR IGNORE INTO catalog_work_tags(work_key,category,tag_key)
                    SELECT t.work_key,g.category,g.tag_key FROM catalog_tags g
                    JOIN catalog_titles t ON t.id=g.title_id WHERE t.work_key IN ('''+marks+')',keys)

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
    from catalog_taxonomy import initialize_origins
    initialize_origins(conn,manga=True)
    # One work is listed by many source sites under the same title; browse
    # pages over these work keys so the work cannot reappear on another page.
    if 'work_key' not in {r[1] for r in conn.execute('PRAGMA table_info(catalog_titles)')}:
        conn.execute("ALTER TABLE catalog_titles ADD COLUMN work_key TEXT NOT NULL DEFAULT ''")
    with conn:conn.execute("UPDATE catalog_titles SET work_key=catalog_normalize(title) WHERE work_key=''")
    # Covers the per-work aggregates, so a page reads the index, not the rows.
    conn.execute('CREATE INDEX IF NOT EXISTS catalog_titles_works ON catalog_titles(work_key,year,chapter_count,first_seen)')
    conn.execute('CREATE INDEX IF NOT EXISTS catalog_titles_newest ON catalog_titles((year IS NULL),year DESC,work_key,chapter_count)')
    initialize_work_tags(conn)
    initialize_status_index(conn,table='catalog_titles',document='metadata',work='work_key')
    from content_vocabulary import initialize as initialize_vocabulary
    initialize_vocabulary(conn)
    revision=conn.execute("SELECT value FROM catalog_policy_state WHERE name='revision'").fetchone()
    labels=conn.execute("SELECT value FROM catalog_policy_state WHERE name='label-index'").fetchone()
    compiled=conn.execute("SELECT value FROM catalog_policy_state WHERE name='work-tag-index'").fetchone()
    if not revision or revision[0]!=current().revision or not labels or labels[0]!=LABEL_INDEX_REVISION:
        with conn:reindex(conn)
    elif not compiled or compiled[0]!=WORK_TAG_INDEX_REVISION:
        with conn:rebuild_work_tags(conn)

def _without_index_time(metadata):
    return {key:value for key,value in metadata.items() if key!='indexedAt'}

def upsert(conn, rows, source_id='', timestamp=None):
    """Idempotent; weak search results never erase enriched source tags."""
    now = float(time.time() if timestamp is None else timestamp)
    count = 0
    from content_vocabulary import add,bump,host
    vocabulary_added=0;affected=set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = _text(row.get('title'), 500)
        provider = _text(row.get('provider'), 120)
        url = _url(row)
        if not title or not provider or not url or row.get('kind', 'manga') != 'manga':
            continue
        identity = hashlib.sha256((provider + '\x00' + url).encode('utf-8')).hexdigest()[:32]
        old = conn.execute('SELECT metadata,first_seen,inspected,tag_state,chapter_count,work_key,'
                           'title,source_id,search_text,language,format,adult,year FROM catalog_titles WHERE id=?',
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
            fresh = unique(readable_label(value) for value in input_values) if isinstance(input_values, list) else []
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
        changes=conn.total_changes
        for category in ('tags','genres'):
            for label in facts[category]:
                conn.execute('INSERT OR IGNORE INTO catalog_tag_facts VALUES(?,?,?)',(identity,category,label))
                vocabulary_added+=add(conn,label,host(url),category,'manga')
        work_key=normalize(title) or identity
        # A crawler revisits most rows unchanged. Keep updated/inspected as
        # "last seen" and skip the tag and work-tag rewrite when the stored
        # columns, metadata (apart from indexedAt) and tag facts are the same.
        if (old and conn.total_changes==changes and tuple(old[6:13])==(title,sid,search,lang,kind,adult,year)
                and old[3]==data['tagStatus'] and old[4]==chapter_count and old[5]==work_key
                and _without_index_time(previous)==_without_index_time(json.loads(clean_metadata))):
            conn.execute('UPDATE catalog_titles SET updated=?,inspected=CASE WHEN ? THEN ? ELSE inspected END WHERE id=?',
                         (now,inspected,now,identity))
            count += 1
            continue
        if old:affected.add(old[5])
        conn.execute('''INSERT INTO catalog_titles(
             id,provider,source_id,source_url,title,search_text,language,format,
             adult,year,chapter_count,tag_state,metadata,first_seen,updated,inspected,work_key)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
             ON CONFLICT(id) DO UPDATE SET
             source_id=excluded.source_id,title=excluded.title,
             search_text=excluded.search_text,language=excluded.language,
             format=excluded.format,adult=excluded.adult,year=excluded.year,
             chapter_count=excluded.chapter_count,tag_state=excluded.tag_state,
             metadata=excluded.metadata,updated=excluded.updated,
             inspected=excluded.inspected,work_key=excluded.work_key''',
             (identity,provider,sid,url,title,search,lang,kind,adult,year,chapter_count,
              data['tagStatus'],clean_metadata,old[1] if old else now,now,
              now if inspected else old[2] if old else 0,work_key))
        affected.add(work_key)
        conn.execute('DELETE FROM catalog_tags WHERE title_id=?',(identity,))
        policy=current();source=urlsplit(url).hostname or ''
        from catalog_taxonomy import classify
        for category in ('tags','genres'):
            for (raw_label,) in conn.execute('SELECT original FROM catalog_tag_facts WHERE title_id=? AND category=?',(identity,category)).fetchall():
                label=readable_label(raw_label)
                key = policy.identity(label,source) if policy.include_discovered else policy.key(label,source)
                if not key:
                    continue
                classified=classify(label,category,'manga',policy,source)
                if not classified:continue
                # Keep each original provider name; aliases for the same key can
                # be recovered from the JSON metadata.
                conn.execute('''INSERT OR IGNORE INTO catalog_tags(
                   title_id,category,tag_key,original) VALUES(?,?,?,?)''',
                   (identity,classified[0],key,label))
        count += 1
    refresh_work_tags(conn,affected)
    if vocabulary_added:bump(conn)
    return count

def _conditions(provider='', format='', source_id='', *, readingMode='', language='all', year='', age='', source_ids=()):
    sql = []
    args = []
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
        args.append({'манга':'manga','манхва':'manhwa','маньхуа':'manhua','комикс':'comic','руманга':'rumanga','вебтун':'webtoon'}.get(normalize(format),format))
    if readingMode=='webtoon':sql.append("(t.format='webtoon' OR json_extract(t.metadata,'$.readingMode') IN ('webtoon','vertical','scroll'))")
    if readingMode=='paged':sql.append("(t.format!='webtoon' AND COALESCE(json_extract(t.metadata,'$.readingMode'),'') NOT IN ('webtoon','vertical','scroll'))")
    if language and language!='all':
        sql.append("(t.language=? COLLATE NOCASE OR t.language LIKE ?)")
        args.extend((language, language+'-%'))
    if year:
        sql.append('t.year=?');args.append(str(year))
    if age=='adult':sql.append('(t.adult=1 OR CAST(json_extract(t.metadata,\'$.age\') AS INTEGER)>=18)')
    elif age=='under18':sql.append('(t.adult=0 OR CAST(json_extract(t.metadata,\'$.age\') AS INTEGER)<18)')
    return (' WHERE '+' AND '.join(sql) if sql else ''), args

# Whole-catalogue orders for paging. Every order ends in the id, so a title
# keeps one place across page requests while the crawler rewrites rows.
# The same orders over whole works (all source rows sharing a work key).
WORK_SORTS = {
    'new': 'MAX(t.year) IS NULL,MAX(t.year) DESC,t.work_key',
    'old': 'MAX(t.year) IS NULL,MAX(t.year),t.work_key',
    'title': 't.work_key',
    'length': 'MAX(t.chapter_count) IS NULL,MAX(t.chapter_count) DESC,t.work_key',
    'added': 'MIN(t.first_seen) DESC,t.work_key',
}
WORK_SOURCES = 12
SORTS = {
    'new': 't.year IS NULL,t.year DESC,t.id',
    'old': 't.year IS NULL,t.year,t.id',
    'title': 't.title COLLATE NOCASE,t.id',
    'length': 't.chapter_count IS NULL,t.chapter_count DESC,t.id',
    'added': 't.first_seen DESC,t.id',
}

def browse(conn, *, q='', tag='', provider='', format='', source_id='', limit=30, offset=0, sort='', status='', **filters):
    limit = min(100,max(1,int(limit)))
    offset = min(10_000_000,max(0,int(offset)))
    facet={k:filters.pop(k,'') for k in ['genre','excludeGenre','excludeTag']}
    where,args = _conditions(provider,format,source_id,**filters)
    from catalog_taxonomy import clauses
    extra,values=clauses(conn,kind='manga',tag=tag,manga=True,**facet)
    newest_first_page = not where and not extra and status in ('','available') and sort in ('','new') and offset == 0
    restriction,states=status_condition(status,table='catalog_titles',document='metadata',work='t.work_key',peer_work='peer.work_key')
    if restriction:extra.append(restriction);values.extend(states)
    if extra:where+=(' AND ' if where else ' WHERE ')+' AND '.join(extra);args.extend(values)
    return _browse_works(conn,where,args,sort,limit,offset,q=q,newest_first_page=newest_first_page)

def _search_where(where, words, *, use_index):
    if not words:return where
    prefix='s' if use_index else 't'
    terms=' AND '.join(f"{prefix}.search_text LIKE ? ESCAPE '\\'" for _ in words)
    if use_index:
        # Scan the compact search index first. The work-order index otherwise
        # needs a metadata-table lookup for every source row before testing LIKE.
        terms=f't.rowid IN (SELECT s.rowid FROM catalog_titles s INDEXED BY catalog_titles_search WHERE {terms})'
    return where+(' AND ' if where else ' WHERE ')+terms

def _browse_works(conn,where,args,sort,limit,offset,q='',newest_first_page=False):
    # Page over works, then return every matching source row of those works
    # (a few per work) in page order; the client folds them into one card.
    # total stays the number of source rows; workTotal counts works for paging.
    query=normalize(q)
    words=query[:160].split()[:12]
    args=[*args,*('%'+word.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%' for word in words)]
    search_where=_search_where(where,words,use_index=True)
    grouped=' FROM catalog_titles t'+search_where+' GROUP BY t.work_key'
    order=WORK_SORTS.get(sort) or WORK_SORTS['new'];ranking=[]
    if words:
        order="MIN(CASE WHEN catalog_normalize(t.title)=? OR EXISTS(SELECT 1 FROM json_each(t.metadata,'$.aliases') a WHERE catalog_normalize(a.value)=?) THEN 0 ELSE 1 END),"+order
        ranking=[query,query]
        page=conn.execute('SELECT t.work_key,SUM(COUNT(*)) OVER (),COUNT(*) OVER ()'+grouped+' ORDER BY '+order+' LIMIT ? OFFSET ?',[*args,*ranking,limit,offset]).fetchall()
        keys=[row[0] for row in page]
    elif newest_first_page:
        # The first edition of each work in this order has its maximum eligible
        # year. Stop as soon as the page has enough distinct works.
        page=[]
        keys=[]
        seen=set()
        cursor=conn.execute('SELECT t.work_key FROM catalog_titles t INDEXED BY catalog_titles_newest'+where+' ORDER BY (t.year IS NULL),t.year DESC,t.work_key',args)
        try:
            for (key,) in cursor:
                if key in seen:
                    continue
                seen.add(key)
                keys.append(key)
                if len(keys)==limit:
                    break
        finally:
            cursor.close()
    else:
        page=[]
        keys=[k for (k,) in conn.execute('SELECT t.work_key'+grouped+' ORDER BY '+order+' LIMIT ? OFFSET ?',[*args,limit,offset])]
    if page:
        total,works_total=page[0][1:]
    else:
        total,works_total=conn.execute('SELECT COALESCE(SUM(sources),0),COUNT(*) FROM (SELECT COUNT(*) AS sources'+grouped+')',args).fetchone()

    result=[]
    if keys:
        # The work-key index narrows hydration to just these works.
        where=_search_where(where,words,use_index=False)
        place={k:i for i,k in enumerate(keys)}
        clause=(' AND ' if where else ' WHERE ')+'t.work_key IN ('+','.join('?'*len(keys))+')'
        rows=conn.execute('SELECT t.id,t.metadata,t.chapter_count,t.tag_state,t.updated,t.work_key FROM catalog_titles t'+where+clause+' ORDER BY t.chapter_count IS NULL,t.chapter_count DESC,t.id',[*args,*keys]).fetchall()
        facts=_work_facts(conn,keys)
        counts={}
        for identity,metadata,chapters,status,updated,key in sorted(rows,key=lambda r:place[r[5]]):
            counts[key]=counts.get(key,0)+1
            if counts[key]>WORK_SOURCES:continue
            row=_public_metadata({**json.loads(metadata),'hentaiExcluded':facts[key]['hentaiExcluded']})
            from catalog_taxonomy import is_hentai
            row['genres']=list(dict.fromkeys([*row['genres'],*[v for v in facts[key]['genres'] if is_hentai(v,current())]]))
            row['hentaiExcluded']=facts[key]['hentaiExcluded']
            row.update({'catalogId':identity,'chapterCount':chapters,'tagStatus':status,'indexedAt':updated,'workKey':key,'workFacts':facts[key]})
            if facts[key].get('releaseStatus'):row['releaseStatus']=facts[key]['releaseStatus']
            result.append(row)
    return {'total':total,'workTotal':works_total,'limit':limit,'offset':offset,'works':len(keys),'items':result}

def title(conn, identity):
    row = conn.execute('SELECT metadata,chapter_count,tag_state,work_key FROM catalog_titles WHERE id=?',(identity,)).fetchone()
    if not row:
        return None
    facts=_work_facts(conn,[row[3]])[row[3]]
    result = {**_public_metadata({**json.loads(row[0]),'hentaiExcluded':facts['hentaiExcluded']}),**facts,'workFacts':facts}
    result['catalogId'] = identity
    result['chapterCount'] = row[1]
    result['tagStatus'] = row[2]
    return result

def _work_facts(conn,keys):
    from catalog_taxonomy import hentai_excluded
    marks=','.join('?' for _ in keys)
    blocked={key for (key,) in conn.execute('SELECT DISTINCT t.work_key FROM catalog_titles t JOIN catalog_tag_facts f ON f.title_id=t.id WHERE t.work_key IN ('+marks+') AND catalog_not_hentai(f.original)=1',keys)}
    records=[(key,json.loads(raw)) for key,raw in conn.execute('SELECT work_key,metadata FROM catalog_titles WHERE work_key IN ('+marks+')',keys)]
    blocked.update(key for key,row in records if hentai_excluded(row))
    facts={key:{'genres':[],'tags':[],'hentaiExcluded':key in blocked} for key in keys}
    states={key:[] for key in keys}
    for key,row in records:
        states[key].append(row)
        public=_public_metadata({**row,'hentaiExcluded':key in blocked})
        for field in ['genres','tags']:facts[key][field]=list(dict.fromkeys([*facts[key][field],*public.get(field,[])]))[:120]
    for key,rows in states.items():
        if status:=work_status(rows):facts[key]['releaseStatus']=status
    return facts

def _public_metadata(row):
    # Older index entries may predate the reader URL and taxonomy normalization.
    row={**row,'kind':'manga','url':row.get('url') or row.get('sourceUrl','')}
    for category in ('tags','genres'):row[category]=unique(row.get(category) or [])
    return project_row(row)


def reindex(conn,policy=None):
    """Rebuild the projection from retained source facts, including removals."""
    policy=policy or current()
    from content_vocabulary import bump
    rows=conn.execute('SELECT id,metadata FROM catalog_titles ORDER BY id')
    count=0;added=0
    conn.execute('DELETE FROM catalog_tags')
    for identity,raw in rows:
        count+=1
        added+=reproject_title(conn,identity,raw,policy)
    conn.execute("INSERT OR REPLACE INTO catalog_policy_state VALUES('revision',?)",(policy.revision,))
    conn.execute("INSERT OR REPLACE INTO catalog_policy_state VALUES('label-index',?)",(LABEL_INDEX_REVISION,))
    rebuild_work_tags(conn)
    if added:bump(conn)
    return count

def reproject_title(conn,identity,raw,policy,*,single=False):
    """Project one title's retained facts. single=True replaces only its rows
    and rewrites the stored document only when the projection changed."""
    from content_vocabulary import add
    from catalog_taxonomy import classify
    row=json.loads(raw);added=0
    if single:
        before=json.loads(raw)
        conn.execute('DELETE FROM catalog_tags WHERE title_id=?',(identity,))
    for category in ('tags','genres'):
        if not conn.execute('SELECT 1 FROM catalog_tag_facts WHERE title_id=? AND category=? LIMIT 1',(identity,category)).fetchone():
            for label in unique(row.get(category) or []):
                conn.execute('INSERT OR IGNORE INTO catalog_tag_facts VALUES(?,?,?)',(identity,category,label))
    source=urlsplit(row.get('sourceUrl') or row.get('url') or '').hostname or ''
    raw_facts={}
    for category in ('tags','genres'):
        facts=list(dict.fromkeys(readable_label(v[0]) for v in conn.execute('SELECT original FROM catalog_tag_facts WHERE title_id=? AND category=?',(identity,category)) if readable_label(v[0])))
        raw_facts[category]=facts
        for label in facts:
            added+=add(conn,label,source,category,'manga')
            key=policy.identity(label,source) if policy.include_discovered else policy.key(label,source)
            classified=classify(label,category,'manga',policy,source)
            if key and classified:conn.execute('INSERT OR IGNORE INTO catalog_tags VALUES(?,?,?,?)',(identity,classified[0],key,label))
    row.update(raw_facts if policy.include_discovered else policy.facts(raw_facts,source))
    state='present' if row['tags'] or row['genres'] else 'not_provided_in_detail' if row.get('metadataChecked') else 'not_requested'
    row['tagStatus']=state
    if not single or row!=before:conn.execute('UPDATE catalog_titles SET metadata=?,tag_state=? WHERE id=?',(json.dumps(row,ensure_ascii=False),state,identity))
    return added


def _visibility(policy):
    # One policy snapshot per query: current() stats the policy file, and the
    # facet query asks about every tag row of the index (millions of calls).
    hosts={}
    def visible(label,url):
        host=hosts.get(url)
        if host is None:
            host=urlsplit(url or '').hostname or ''
            if len(hosts)<500000:hosts[url]=host
        return 1 if policy.key(label,host) else 0
    return visible

def tags(conn, *, provider='', source_id='', limit=100, q='', **filters):
    policy=current()
    limit=min(500,max(1,int(limit)))
    global_scope=(not provider and not source_id and
                  filters.get('language','all') in ('','all') and
                  not filters.get('source_ids') and not filters.get('year') and
                  not filters.get('age') and not filters.get('format') and
                  not filters.get('readingMode'))
    if global_scope:
        needle=normalize(q);items=[]
        for kind,key,count in conn.execute('SELECT category,tag_key,works FROM catalog_tag_stats ORDER BY works DESC,tag_key'):
            if not policy.key(key):continue
            label=policy.label(key,key)
            aliases=policy.rules.get(key,{}).get('aliases',[])
            if needle and needle not in normalize(' '.join([key,label,*aliases])):continue
            items.append({'type':kind,'key':key,'original':label,'originalLabels':[label],'works':count})
            if len(items)>=limit:break
        return {'tags':items,'compiled':True}
    conn.create_function('catalog_tag_visible',2,_visibility(policy))
    conn.create_function('catalog_tag_label',1,policy.label)
    where,params = _conditions(provider=provider,source_id=source_id,**filters)
    where+=(' AND ' if where else ' WHERE ')+'catalog_tag_visible(g.original,t.source_url)=1'
    if q:
        needle='%'+normalize(q).replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        where+=(' AND ' if where else ' WHERE ')+"(g.tag_key LIKE ? ESCAPE '\\' OR catalog_normalize(g.original) LIKE ? ESCAPE '\\' OR catalog_normalize(catalog_tag_label(g.tag_key)) LIKE ? ESCAPE '\\')"
        params.extend([needle,needle,needle])
    rows=conn.execute('''SELECT g.category,g.tag_key,MIN(g.original),COUNT(DISTINCT g.title_id),json_group_array(DISTINCT g.original)
                         FROM catalog_tags g JOIN catalog_titles t ON t.id=g.title_id'''+where+
                      ''' GROUP BY g.category,g.tag_key ORDER BY COUNT(DISTINCT g.title_id) DESC,g.tag_key LIMIT ?''',
                      [*params,limit]).fetchall()
    return {'tags':[{'type':kind,'key':key,'original':policy.label(key,original),
                     'originalLabels':[policy.label(key,original)],'works':count}
                    for kind,key,original,count,_ in rows if clean_label(policy.label(key,original))]}

# Facets read every tag row of the whole index and change slowly.
# Each answer (about 80 KB per
# filter set and tag policy) is kept in memory and in DATA_DIR, so a restart
# answers at once. An answer older than TAGS_TTL is still served immediately
# while one background refresh replaces it; only a never-seen key waits.
TAGS_TTL=6*3600
TAGS_FILE=Path(os.getenv('DATA_DIR','/data'))/'manga-tag-facets.json'
_tag_cache={}
_tag_guard=threading.Lock()
_tag_refreshing=set()
_tag_loaded=[False]

def _load_tag_cache(path):
    if _tag_loaded[0]:return
    _tag_loaded[0]=True
    try:
        saved=json.loads(Path(path).read_text(encoding='utf-8'))
        for row in saved if isinstance(saved,list) else []:
            if isinstance(row,dict) and isinstance(row.get('value'),dict):
                _tag_cache[(row['revision'],row['filters'])]=(float(row['at']),row['value'])
    except (OSError,ValueError,KeyError,TypeError):pass

def _save_tag_cache(path):
    rows=[{'revision':key[0],'filters':key[1],'at':at,'value':value} for key,(at,value) in _tag_cache.items()]
    path=Path(path);temporary=path.with_name(path.name+'.tmp')
    try:
        temporary.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8');os.replace(temporary,path)
    except OSError:pass

def cached_tags(conn, lock, *, ttl=None, clock=time.time, background=True, path=None, reader=None, **kwargs):
    ttl=TAGS_TTL if ttl is None else ttl;path=path or TAGS_FILE
    key=(current().revision,json.dumps(kwargs,sort_keys=True,default=str))
    def compute():
        if reader is None:
            with lock:value=tags(conn,**kwargs)
        else:
            with reader() as db:value=tags(db,**kwargs)
        with _tag_guard:
            _tag_cache.pop(key,None);_tag_cache[key]=(clock(),value)
            while len(_tag_cache)>64:_tag_cache.pop(next(iter(_tag_cache)))
            _tag_refreshing.discard(key)
            _save_tag_cache(path)
        return value
    with _tag_guard:
        _load_tag_cache(path)
        hit=_tag_cache.get(key)
        if hit and clock()-hit[0]<ttl:return hit[1]
        refresh=hit is not None and key not in _tag_refreshing
        if refresh:_tag_refreshing.add(key)
    if hit is not None:
        if refresh:
            def run():
                try:compute()
                except Exception:
                    with _tag_guard:_tag_refreshing.discard(key)
            if background:threading.Thread(target=run,name='manga-tag-facets',daemon=True).start()
            else:run()
        return hit[1]
    return compute()

def stats(conn):
    rows = conn.execute('''SELECT provider,COUNT(*),
                  SUM(CASE WHEN tag_state='present' THEN 1 ELSE 0 END)
                  FROM catalog_titles GROUP BY provider ORDER BY COUNT(*) DESC''').fetchall()
    return {'totalTitles':sum(row[1] for row in rows),'titlesWithTags':sum(row[2] or 0 for row in rows),
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
