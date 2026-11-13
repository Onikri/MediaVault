"""Bounded, metadata-only facts shared by all catalogue media kinds."""
import hashlib,json,re,time
from urllib.parse import urlsplit
from manga_tag_policy import current,normalize

KINDS=frozenset({'movie','tv','anime','manga','ranobe','book'})

def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS content_titles(id TEXT PRIMARY KEY,kind TEXT NOT NULL,search TEXT NOT NULL,raw TEXT NOT NULL,updated INTEGER NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS content_titles_kind ON content_titles(kind,updated)')
    db.execute('CREATE TABLE IF NOT EXISTS content_catalog_state(name TEXT PRIMARY KEY,value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS content_tag_facts(title_id TEXT NOT NULL,kind TEXT NOT NULL,source TEXT NOT NULL,category TEXT NOT NULL,original TEXT NOT NULL,PRIMARY KEY(title_id,category,original))')
    db.execute('CREATE TABLE IF NOT EXISTS content_tags(title_id TEXT NOT NULL,category TEXT NOT NULL,tag_key TEXT NOT NULL,original TEXT NOT NULL,PRIMARY KEY(title_id,category,tag_key,original))')
    db.execute('CREATE INDEX IF NOT EXISTS content_tags_key ON content_tags(tag_key,category,title_id)')
    db.execute('CREATE INDEX IF NOT EXISTS content_fact_labels ON content_tag_facts(original,source)')
    from content_vocabulary import initialize as initialize_vocabulary
    initialize_vocabulary(db)
    state=db.execute("SELECT value FROM content_catalog_state WHERE name='policy'").fetchone()
    if not db.execute("SELECT 1 FROM content_catalog_state WHERE name='facts-v1'").fetchone() or not state or state[0]!=current().revision:
        added=0
        for identity,raw in title_rows(db):added+=_index(db,identity,json.loads(raw),current())
        if added:invalidate(db)
        db.execute("INSERT OR REPLACE INTO content_catalog_state VALUES('facts-v1','1')")
        db.execute("INSERT OR REPLACE INTO content_catalog_state VALUES('policy',?)",(current().revision,))

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
        for label in row.get(field) or []:
            db.execute('INSERT OR IGNORE INTO content_tag_facts VALUES(?,?,?,?,?)',(identity,row['kind'],source,field,label))
            added+=add(db,label,source,field,row['kind'])
            key=policy.identity(label,source) if policy.include_discovered else policy.key(label,source)
            if key:
                category={'tag':'tags','genre':'genres'}.get(policy.rules.get(key,{}).get('category'),field)
                db.execute('INSERT OR IGNORE INTO content_tags VALUES(?,?,?,?)',(identity,category,key,label))
    return added

def safe_url(value):
    if not isinstance(value,str) or len(value)>2000:return ''
    try:
        p=urlsplit(value)
        return value if p.scheme=='https' and p.hostname and not p.username and not p.password else ''
    except ValueError:return ''

def ingest(db,rows):
    initialize(db);count=0;new_facts=0
    for row in rows[:100]:
        if not isinstance(row,dict) or row.get('kind') not in KINDS:continue
        provider=row.get('provider');identity=str(row.get('id') or '')
        if not isinstance(provider,str) or not re.fullmatch(r'[a-zA-Z0-9:_-]{1,100}',provider) or not 1<=len(identity)<=200:continue
        title=row.get('title')
        if not isinstance(title,str) or not title.strip() or len(title)>500:continue
        data={k:row[k] for k in ('id','kind','provider','providerId','title','titles','format','year','language','age','status','ids','description') if k in row}
        for field in ('tags','genres','aliases'):
            values=row.get(field);data[field]=list(dict.fromkeys(v.strip() for v in values if isinstance(v,str) and 0<len(v.strip())<=120))[:120] if isinstance(values,list) else []
        for field in ('sourceUrl','sourceURL','url','cover'):data[field]=safe_url(row.get(field))
        # Never accept arbitrary client objects, account secrets or enormous text.
        data['description']=str(data.get('description') or '')[:12000]
        data['ids']={k:str(v)[:100] for k,v in (data.get('ids') or {}).items() if k in {'mal','anilist','kitsu','imdb','wikidata','fantlab','kinopoisk','openlibrary'}} if isinstance(data.get('ids'),dict) else {}
        if not isinstance(data.get('titles'),dict):data['titles']={}
        data['titles']={k:v[:500] for k,v in data['titles'].items() if k in {'ru','uk','en','native','romaji'} and isinstance(v,str)}
        key=hashlib.sha256((data['kind']+'\0'+provider+'\0'+identity).encode()).hexdigest()[:32]
        previous=db.execute('SELECT raw FROM content_titles WHERE id=?',(key,)).fetchone()
        if previous:
            old=json.loads(previous[0])
            for field in ('tags','genres','aliases'):data[field]=list(dict.fromkeys([*data[field],*old.get(field,[])]))[:120]
            for field in ('sourceUrl','sourceURL','url','cover','description'):
                if not data.get(field):data[field]=old.get(field,'')
            for field in ('ids','titles'):data[field]={**old.get(field,{}),**data[field]}
        raw=json.dumps(data,ensure_ascii=False,separators=(',',':'))
        if len(raw.encode())>24000:continue
        search=normalize(' '.join([title,*data['aliases'],*data['titles'].values()]))[:5000]
        db.execute('INSERT OR REPLACE INTO content_titles VALUES(?,?,?,?,?)',(key,data['kind'],search,raw,int(time.time())))
        new_facts+=_index(db,key,data,current())
        count+=1
    if new_facts:invalidate(db)
    return count

def browse(db,*,kind,q='',tag='',genre='',limit=60,offset=0):
    initialize(db)
    if kind not in KINDS:return {'items':[],'total':0}
    policy=current();wanted=[('genres',policy.key(genre))] if genre else []
    wanted += [(None,policy.key(value.strip())) for value in str(tag or '').split(',')[:12] if value.strip()]
    where=['kind=?'];params=[kind]
    for word in normalize(q).split()[:12]:
        where.append("search LIKE ? ESCAPE '\\'");params.append('%'+word.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
    for field,key in wanted:
        if not key:return {'items':[],'total':0,'offset':offset}
        where.append('EXISTS(SELECT 1 FROM content_tags g WHERE g.title_id=t.id AND g.tag_key=?'+(' AND g.category=?' if field else '')+')');params.append(key)
        if field:params.append(field)
    condition=' AND '.join(where);limit=min(100,max(1,limit));offset=max(0,min(10_000_000,offset))
    total=db.execute('SELECT COUNT(*) FROM content_titles t WHERE '+condition,params).fetchone()[0];rows=[]
    for identity,raw in db.execute('SELECT id,raw FROM content_titles t WHERE '+condition+' ORDER BY updated DESC,id LIMIT ? OFFSET ?',[*params,limit,offset]):
        row=json.loads(raw);source=urlsplit(row.get('sourceUrl') or row.get('sourceURL') or '').hostname or ''
        facts=policy.facts(row,source)
        rows.append({**row,**facts,'contentCatalogId':identity})
    return {'items':rows,'total':total,'offset':offset,'limit':limit}

def facts(db):
    initialize(db)
    yield from db.execute('SELECT title_id,kind,source,category,original FROM content_tag_facts')

def reindex(db,policy):
    initialize(db)
    count=0
    for identity,raw in title_rows(db):
        _index(db,identity,json.loads(raw),policy);count+=1
    db.execute("INSERT OR REPLACE INTO content_catalog_state VALUES('policy',?)",(policy.revision,))
    invalidate(db)
    return count
