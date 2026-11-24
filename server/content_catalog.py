"""Bounded, metadata-only facts shared by all catalogue media kinds."""
import hashlib,json,re,time
from urllib.parse import urlsplit
from catalog_labels import readable_label
from manga_tag_policy import current,normalize
from release_status import condition as status_condition, initialize_index as initialize_status_index, work_status

KINDS=frozenset({'movie','tv','anime','manga','ranobe','book'})
LABEL_INDEX_REVISION='readable-labels-v1'
WORK_TAG_INDEX_REVISION='work-tags-v1'
RELEASE_YEAR = "MAX(CASE WHEN typeof(json_extract(t.raw,'$.year')) IN ('integer','text') AND CAST(json_extract(t.raw,'$.year') AS INTEGER) BETWEEN 1 AND 9999 THEN CAST(json_extract(t.raw,'$.year') AS INTEGER) END)"
ORDERS = {
    'updated': 'MAX(t.updated) DESC',
    'new': f'{RELEASE_YEAR} IS NULL,{RELEASE_YEAR} DESC',
    'old': f'{RELEASE_YEAR} IS NULL,{RELEASE_YEAR}',
    'title': 'MIN(t.search)',
    'trending': """MAX(CASE WHEN CAST(json_extract(t.raw,'$.trendingAt') AS INTEGER)>=unixepoch()-7200
        THEN CAST(json_extract(t.raw,'$.trending') AS INTEGER) ELSE 0 END) DESC,
        MAX(CAST(json_extract(t.raw,'$.popularity') AS INTEGER)) DESC,
        MAX(CAST(json_extract(t.raw,'$.score') AS REAL)) DESC,"""+RELEASE_YEAR+' DESC',
    'score': "MAX(CAST(json_extract(t.raw,'$.score') AS REAL)) DESC,"+RELEASE_YEAR+' DESC',
}

NUMERIC_LIMITS={'score':(0.01,10),'popularity':(0,1_000_000_000),'trending':(0,1_000_000_000),
                'episodes':(1,100_000),'episodesAired':(0,100_000),'chapters':(0,100_000),'firstAiringAt':(1,4_000_000_000)}

def catalogue_number(value,minimum,maximum):
    if isinstance(value,bool) or not isinstance(value,(int,float,str)):return None
    try:number=float(value)
    except (ValueError,OverflowError):return None
    if minimum<=number<=maximum:return int(number) if number.is_integer() else number
    return None

def work_sql(alias='t'):
    p=alias+'.' if alias else ''
    expr=p+"kind||':'||CASE "
    for key in ['mal','imdb','kinopoisk','anilist','kitsu','openlibrary','fantlab']:
        value="NULLIF(json_extract("+p+"raw,'$.ids."+key+"'),'')"
        expr+='WHEN '+value+' IS NOT NULL THEN '+repr(key+':')+'||'+value+' '
    return '('+expr+"ELSE 'id:'||"+p+'id END)'

def work_key(row,identity):
    kind=str(row.get('kind') or '')
    ids=row.get('ids') if isinstance(row.get('ids'),dict) else {}
    for key in ['mal','imdb','kinopoisk','anilist','kitsu','openlibrary','fantlab']:
        if ids.get(key) not in (None,''):return kind+':'+key+':'+str(ids[key])
    return kind+':id:'+identity

def _work_tag_triggers(db):
    db.execute('''CREATE TRIGGER IF NOT EXISTS content_work_tags_add AFTER INSERT ON content_work_tags BEGIN
        INSERT INTO content_tag_stats(kind,category,tag_key,works) VALUES(NEW.kind,NEW.category,NEW.tag_key,1)
        ON CONFLICT(kind,category,tag_key) DO UPDATE SET works=works+1;
      END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS content_work_tags_remove AFTER DELETE ON content_work_tags BEGIN
        UPDATE content_tag_stats SET works=works-1 WHERE kind=OLD.kind AND category=OLD.category AND tag_key=OLD.tag_key;
        DELETE FROM content_tag_stats WHERE kind=OLD.kind AND category=OLD.category AND tag_key=OLD.tag_key AND works<=0;
      END''')

def initialize_work_tags(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS content_work_tags(
        kind TEXT NOT NULL,work_key TEXT NOT NULL,category TEXT NOT NULL,tag_key TEXT NOT NULL,
        PRIMARY KEY(kind,work_key,category,tag_key)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS content_work_tags_lookup ON content_work_tags(kind,category,tag_key,work_key);
      CREATE TABLE IF NOT EXISTS content_tag_stats(
        kind TEXT NOT NULL,category TEXT NOT NULL,tag_key TEXT NOT NULL,works INTEGER NOT NULL,
        PRIMARY KEY(kind,category,tag_key)) WITHOUT ROWID;
    ''')
    _work_tag_triggers(db)

def rebuild_work_tags(db):
    db.execute('DROP TRIGGER IF EXISTS content_work_tags_add')
    db.execute('DROP TRIGGER IF EXISTS content_work_tags_remove')
    db.execute('DELETE FROM content_work_tags');db.execute('DELETE FROM content_tag_stats')
    work=work_sql('t')
    db.execute('''INSERT OR IGNORE INTO content_work_tags(kind,work_key,category,tag_key)
                  SELECT t.kind,'''+work+''',g.category,g.tag_key FROM content_tags g
                  JOIN content_titles t ON t.id=g.title_id''')
    db.execute('''INSERT INTO content_tag_stats(kind,category,tag_key,works)
                  SELECT kind,category,tag_key,COUNT(*) FROM content_work_tags GROUP BY kind,category,tag_key''')
    _work_tag_triggers(db)
    db.execute("INSERT OR REPLACE INTO content_catalog_state VALUES('work-tag-index',?)",(WORK_TAG_INDEX_REVISION,))

def refresh_work_tags(db,keys):
    keys=sorted({key for key in keys if key})
    if not keys:return
    # Avoid executescript() here: it commits an active ingest transaction.
    # initialize() has already created the materialized index and triggers.
    marks=','.join('?' for _ in keys);work=work_sql('t')
    db.execute('DELETE FROM content_work_tags WHERE work_key IN ('+marks+')',keys)
    db.execute('''INSERT OR IGNORE INTO content_work_tags(kind,work_key,category,tag_key)
                  SELECT t.kind,'''+work+''',g.category,g.tag_key FROM content_tags g
                  JOIN content_titles t ON t.id=g.title_id WHERE '''+work+' IN ('+marks+')',keys)


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS content_titles(id TEXT PRIMARY KEY,kind TEXT NOT NULL,search TEXT NOT NULL,raw TEXT NOT NULL,updated INTEGER NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS content_titles_kind ON content_titles(kind,updated)')
    db.execute('CREATE INDEX IF NOT EXISTS content_work_identity ON content_titles('+work_sql('')+')')
    initialize_status_index(db,table='content_titles',document='raw',work=work_sql(''),kind='kind')
    db.execute('CREATE TABLE IF NOT EXISTS content_catalog_state(name TEXT PRIMARY KEY,value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS content_tag_facts(title_id TEXT NOT NULL,kind TEXT NOT NULL,source TEXT NOT NULL,category TEXT NOT NULL,original TEXT NOT NULL,PRIMARY KEY(title_id,category,original))')
    db.execute('CREATE TABLE IF NOT EXISTS content_tags(title_id TEXT NOT NULL,category TEXT NOT NULL,tag_key TEXT NOT NULL,original TEXT NOT NULL,PRIMARY KEY(title_id,category,tag_key,original))')
    db.execute('CREATE INDEX IF NOT EXISTS content_tags_key ON content_tags(tag_key,category,title_id)')
    db.execute('CREATE INDEX IF NOT EXISTS content_fact_labels ON content_tag_facts(original,source)')
    initialize_work_tags(db)
    from catalog_taxonomy import initialize_origins
    initialize_origins(db)
    from content_vocabulary import initialize as initialize_vocabulary
    initialize_vocabulary(db)
    state=db.execute("SELECT value FROM content_catalog_state WHERE name='policy'").fetchone()
    labels=db.execute("SELECT value FROM content_catalog_state WHERE name='label-index'").fetchone()
    compiled=db.execute("SELECT value FROM content_catalog_state WHERE name='work-tag-index'").fetchone()
    needs_index=not db.execute("SELECT 1 FROM content_catalog_state WHERE name='facts-v1'").fetchone() or not state or state[0]!=current().revision or not labels or labels[0]!=LABEL_INDEX_REVISION
    if needs_index:
        added=0
        for identity,raw in title_rows(db):added+=_index(db,identity,json.loads(raw),current())
        if added:invalidate(db)
        db.execute("INSERT OR REPLACE INTO content_catalog_state VALUES('facts-v1','1')")
        db.execute("INSERT OR REPLACE INTO content_catalog_state VALUES('policy',?)",(current().revision,))
        db.execute("INSERT OR REPLACE INTO content_catalog_state VALUES('label-index',?)",(LABEL_INDEX_REVISION,))
    if needs_index or not compiled or compiled[0]!=WORK_TAG_INDEX_REVISION:rebuild_work_tags(db)

def title_rows(db):
    cursor=db.execute('SELECT id,raw FROM content_titles ORDER BY id')
    while True:
        batch=cursor.fetchmany(250)
        if not batch:return
        yield from batch


def invalidate(db):
    db.execute('CREATE TABLE IF NOT EXISTS content_catalog_state(name TEXT PRIMARY KEY,value TEXT NOT NULL)')
    db.execute("INSERT INTO content_catalog_state VALUES('vocabulary','1') ON CONFLICT(name) DO UPDATE SET value=CAST(value AS INTEGER)+1")

def _index(db,identity,row,policy):
    from content_vocabulary import add
    source=urlsplit(row.get('sourceUrl') or row.get('sourceURL') or '').hostname or '';added=0
    db.execute('DELETE FROM content_tags WHERE title_id=?',(identity,))
    for field in ('genres','tags'):
        for raw_label in row.get(field) or []:
            label=readable_label(raw_label)
            if not label:continue
            db.execute('INSERT OR IGNORE INTO content_tag_facts VALUES(?,?,?,?,?)',(identity,row['kind'],source,field,label))
            added+=add(db,label,source,field,row['kind'])
            from catalog_taxonomy import classify
            classified=classify(label,field,row['kind'],policy,source)
            if not classified:continue
            key=policy.identity(label,source) if policy.include_discovered else policy.key(label,source)
            if key:
                category=classified[0]
                db.execute('INSERT OR IGNORE INTO content_tags VALUES(?,?,?,?)',(identity,category,key,label))
    return added

def safe_url(value):
    if not isinstance(value,str) or len(value)>2000:return ''
    try:
        p=urlsplit(value)
        return value if p.scheme=='https' and p.hostname and not p.username and not p.password else ''
    except ValueError:return ''

def title_key(kind,provider,identity):
    return hashlib.sha256((kind+'\0'+provider+'\0'+identity).encode()).hexdigest()[:32]

def ingest(db,rows):
    initialize(db);count=0;new_facts=0;affected=set()
    for row in rows[:100]:
        if not isinstance(row,dict) or row.get('kind') not in KINDS:continue
        provider=row.get('provider');identity=str(row.get('id') or '')
        if not isinstance(provider,str) or not re.fullmatch(r'[a-zA-Z0-9:_-]{1,100}',provider) or not 1<=len(identity)<=200:continue
        title=row.get('title')
        if not isinstance(title,str) or not title.strip() or len(title)>500:continue
        data={k:row[k] for k in ('id','kind','provider','providerId','title','titles','format','year','language','age','status','ids','description') if k in row}
        for field,(minimum,maximum) in NUMERIC_LIMITS.items():
            if (value:=catalogue_number(row.get(field),minimum,maximum)) is not None:data[field]=value
        if 'trending' in data:
            data['trendingAt']=min(int(time.time()),catalogue_number(row.get('trendingAt'),1,4_000_000_000) or int(time.time()))
        for field in ('startDate','endDate'):
            if isinstance(row.get(field),str) and re.match(r'^\d{4}(?:-\d{2}){0,2}(?:$|T)',row[field]):
                data[field]=row[field][:10]
        for field in ('tags','genres','aliases'):
            values=row.get(field);data[field]=list(dict.fromkeys(readable_label(v) if field!='aliases' else v.strip() for v in values if isinstance(v,str) and 0<len(v.strip())<=120))[:120] if isinstance(values,list) else []
        for field in ('sourceUrl','sourceURL','url','cover'):data[field]=safe_url(row.get(field))
        # Never accept arbitrary client objects, account secrets or enormous text.
        data['description']=str(data.get('description') or '')[:12000]
        data['ids']={k:str(v)[:100] for k,v in (data.get('ids') or {}).items() if k in {'mal','anilist','kitsu','imdb','wikidata','fantlab','kinopoisk','openlibrary'}} if isinstance(data.get('ids'),dict) else {}
        if not isinstance(data.get('titles'),dict):data['titles']={}
        data['titles']={k:v[:500] for k,v in data['titles'].items() if k in {'ru','uk','en','native','romaji'} and isinstance(v,str)}
        key=title_key(data['kind'],provider,identity)
        previous=db.execute('SELECT raw FROM content_titles WHERE id=?',(key,)).fetchone()
        if previous:
            old=json.loads(previous[0])
            affected.add(work_key(old,key))
            for field in ('tags','genres','aliases'):data[field]=list(dict.fromkeys([*data[field],*old.get(field,[])]))[:120]
            for field in ('sourceUrl','sourceURL','url','cover','description'):
                if not data.get(field):data[field]=old.get(field,'')
            if not data.get('status') and old.get('status'):data['status']=old['status']
            for field in (*NUMERIC_LIMITS,'trendingAt','startDate','endDate','year'):
                if data.get(field) is None and old.get(field) is not None:data[field]=old[field]
            for field in ('ids','titles'):data[field]={**old.get(field,{}),**data[field]}
        raw=json.dumps(data,ensure_ascii=False,separators=(',',':'))
        if len(raw.encode())>24000:continue
        if provider=='omdb' and previous and previous[0]==raw:
            count+=1
            continue
        search=normalize(' '.join([title,*data['aliases'],*data['titles'].values()]))[:5000]
        db.execute('INSERT OR REPLACE INTO content_titles VALUES(?,?,?,?,?)',(key,data['kind'],search,raw,int(time.time())))
        new_facts+=_index(db,key,data,current())
        affected.add(work_key(data,key))
        count+=1
    refresh_work_tags(db,affected)
    if new_facts:invalidate(db)
    return count

def browse(db,*,kind,q='',tag='',genre='',excludeGenre='',excludeTag='',format='',year='',age='',limit=60,offset=0,sort='updated',status='',prepared=False):
    if not prepared:initialize(db)
    if kind not in KINDS:return {'items':[],'total':0}
    policy=current();where=['kind=?'];params=[kind]
    for word in normalize(q).split()[:12]:
        where.append("search LIKE ? ESCAPE '\\'");params.append('%'+word.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
    from catalog_taxonomy import clauses
    extra,values=clauses(db,kind=kind,tag=tag,genre=genre,excludeGenre=excludeGenre,excludeTag=excludeTag)
    where.extend(extra);params.extend(values)
    restriction,states=status_condition(status,table='content_titles',document='raw',work=work_sql(),peer_work=work_sql('peer'),kind=kind)
    if restriction:where.append(restriction);params.extend(states)
    from catalog_taxonomy import format_label
    db.create_function('catalog_format',2,format_label,deterministic=True)
    if format:where.append("catalog_format(json_extract(t.raw,'$.format'),t.kind)=?");params.append(format_label(format,kind))
    if year:where.append("CAST(json_extract(t.raw,'$.year') AS TEXT)=?");params.append(str(year))
    if age=='adult':where.append("CAST(json_extract(t.raw,'$.age') AS INTEGER)>=18")
    elif age=='under18':where.append("CAST(json_extract(t.raw,'$.age') AS INTEGER)<18")
    condition=' AND '.join(where);limit=min(100,max(1,limit));offset=max(0,min(10_000_000,offset))
    work=work_sql();total=db.execute('SELECT COUNT(DISTINCT '+work+') FROM content_titles t WHERE '+condition,params).fetchone()[0]
    order=ORDERS.get(sort,ORDERS['updated'])
    keys=[value[0] for value in db.execute('SELECT '+work+' FROM content_titles t WHERE '+condition+' GROUP BY '+work+' ORDER BY '+order+','+work+' LIMIT ? OFFSET ?',[*params,limit,offset])]
    rows=[row for key in keys if (row:=read_work(db,key,policy)) is not None]
    return {'items':rows,'total':total,'offset':offset,'limit':limit}

def read_work(db,key,policy,preferred_id=''):
    records=[(identity,json.loads(raw)) for identity,raw in db.execute('SELECT id,raw FROM content_titles t WHERE '+work_sql()+'=? ORDER BY updated DESC,id',(key,))]
    if not records:return None
    from catalog_taxonomy import hentai_excluded
    excluded=any(hentai_excluded(record) for _,record in records) or bool(db.execute('SELECT 1 FROM content_tag_facts f JOIN content_titles peer ON peer.id=f.title_id WHERE '+work_sql('peer')+'=? AND catalog_not_hentai(f.original)=1 LIMIT 1',(key,)).fetchone())
    identity,row=next((entry for entry in records if entry[0]==preferred_id),records[0])
    for field in ('cover','description','score','popularity','episodes','episodesAired','chapters','firstAiringAt','startDate','endDate'):
        if row.get(field) in (None,''):
            value=next((record[field] for _,record in records if record.get(field) not in (None,'')),None)
            if value is not None:row[field]=value
    merged={'genres':[],'tags':[]}
    for _,record in records:
        source=urlsplit(record.get('sourceUrl') or record.get('sourceURL') or '').hostname or ''
        facts=policy.facts({**record,'hentaiExcluded':excluded},source)
        for field in merged:merged[field]=list(dict.fromkeys([*merged[field],*facts[field]]))[:120]
    aliases=list(dict.fromkeys([value for _,record in records for value in [record['title'],*record.get('aliases',[])]]))[:120]
    ids={};titles={}
    for _,record in reversed(records):ids.update(record.get('ids') or {});titles.update(record.get('titles') or {})
    providers=list(dict.fromkeys(record['provider'] for _,record in records))
    state=work_status(record for _,record in records)
    return {**row,**merged,'hentaiExcluded':excluded,'aliases':aliases,'ids':ids,'titles':titles,'contentCatalogId':identity,'workKey':key,'providerCount':len(records),'providers':providers,'releaseStatus':state}

def title(db,kind,provider,source_id,*,prepared=False):
    if not prepared:initialize(db)
    identity=title_key(kind,provider,provider+':'+source_id)
    match=db.execute('SELECT '+work_sql()+' FROM content_titles t WHERE id=?',(identity,)).fetchone()
    return read_work(db,match[0],current(),preferred_id=identity) if match else None

def facts(db):
    initialize(db)
    yield from db.execute('SELECT title_id,kind,source,category,original FROM content_tag_facts')

def reindex(db,policy):
    initialize(db)
    count=0
    for identity,raw in title_rows(db):
        _index(db,identity,json.loads(raw),policy);count+=1
    db.execute("INSERT OR REPLACE INTO content_catalog_state VALUES('policy',?)",(policy.revision,))
    rebuild_work_tags(db)
    invalidate(db)
    return count
