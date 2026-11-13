"""Bounded, metadata-only facts shared by all catalogue media kinds."""
import hashlib,json,re,time
from urllib.parse import urlsplit
from manga_tag_policy import current,normalize

KINDS=frozenset({'movie','tv','anime','manga','ranobe','book'})

def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS content_titles(id TEXT PRIMARY KEY,kind TEXT NOT NULL,search TEXT NOT NULL,raw TEXT NOT NULL,updated INTEGER NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS content_titles_kind ON content_titles(kind,updated)')

def safe_url(value):
    if not isinstance(value,str) or len(value)>2000:return ''
    try:
        p=urlsplit(value)
        return value if p.scheme=='https' and p.hostname and not p.username and not p.password else ''
    except ValueError:return ''

def ingest(db,rows):
    initialize(db);count=0
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
        raw=json.dumps(data,ensure_ascii=False,separators=(',',':'))
        if len(raw.encode())>24000:continue
        key=hashlib.sha256((data['kind']+'\0'+provider+'\0'+identity).encode()).hexdigest()[:32]
        search=normalize(' '.join([title,*data['aliases'],*data['titles'].values()]))[:5000]
        db.execute('INSERT OR REPLACE INTO content_titles VALUES(?,?,?,?,?)',(key,data['kind'],search,raw,int(time.time())))
        count+=1
    return count

def browse(db,*,kind,q='',tag='',genre='',limit=60):
    initialize(db)
    if kind not in KINDS:return {'items':[],'total':0}
    policy=current();wanted=[(field,policy.key(value)) for field,value in (('tags',tag),('genres',genre)) if value]
    rows=[]
    for identity,search,raw in db.execute('SELECT id,search,raw FROM content_titles WHERE kind=? ORDER BY updated DESC LIMIT 10000',(kind,)):
        if any(word not in search for word in normalize(q).split()[:12]):continue
        row=json.loads(raw);source=urlsplit(row.get('sourceUrl') or row.get('sourceURL') or '').hostname or ''
        facts=policy.facts(row,source)
        if any(not key or policy.rules[key]['label'] not in facts[field] for field,key in wanted):continue
        rows.append({**row,**facts,'contentCatalogId':identity})
    return {'items':rows[:min(100,max(1,limit))],'total':len(rows)}

def facts(db):
    initialize(db)
    for identity,kind,raw in db.execute('SELECT id,kind,raw FROM content_titles'):
        row=json.loads(raw);source=urlsplit(row.get('sourceUrl') or row.get('sourceURL') or '').hostname or ''
        for category in ('tags','genres'):
            for label in row.get(category) or []:yield identity,kind,source,category,label

def reindex(db,policy):
    initialize(db)
    # Source facts stay immutable; every read is projected through the current
    # policy. Reindexing warms/validates the new projection transactionally.
    count=0
    for (raw,) in db.execute('SELECT raw FROM content_titles'):
        row=json.loads(raw);source=urlsplit(row.get('sourceUrl') or row.get('sourceURL') or '').hostname or ''
        policy.facts(row,source);count+=1
    return count
