"""Shared presentation taxonomy; retained source facts and owner rules stay intact."""
import hashlib,json,unicodedata
from pathlib import Path

DATA=json.loads(Path(__file__).with_name('catalog-taxonomy.json').read_text(encoding='utf-8'))
REVISION=hashlib.sha256(json.dumps(DATA,sort_keys=True).encode()).hexdigest()
def norm(value):return ' '.join(unicodedata.normalize('NFKC',str(value or '')).casefold().replace('_',' ').replace('-',' ').split())
GENRES={norm(alias):row for row in DATA['genres'] for alias in [row['label'],row['key'],*row['aliases']]}
HENTAI=DATA['sourceGenres']['hentai']
HENTAI_NAMES={norm(v) for v in ['Хентай','hentai',*GENRES['hentai']['aliases']]}
HENTAI_NEGATIVE={norm(v) for v in HENTAI['excludeLabels']}

def hentai_origin(provider,url,kind):
    from urllib.parse import urlsplit
    if kind not in HENTAI['kinds']:return False
    if provider in HENTAI['providers']:return True
    try:host=(urlsplit(url or '').hostname or '').lower().rstrip('.')
    except ValueError:return False
    return any(host==domain or host.endswith('.'+domain) for domain in HENTAI['hosts'])

def hentai_excluded(row):
    if row.get('hentaiExcluded') or (row.get('workFacts') or {}).get('hentaiExcluded'):return True
    values=[*(row.get('genres') or []),*(row.get('tags') or []),*((row.get('workFacts') or {}).get('genres') or []),*((row.get('workFacts') or {}).get('tags') or [])]
    return any(norm(v) in HENTAI_NEGATIVE for v in values) or any(hentai_excluded(v) for v in row.get('sources') or [] if isinstance(v,dict))

def is_hentai(value,policy=None):
    return norm(value) in HENTAI_NAMES or bool(policy and policy.identity(value)==policy.identity('Хентай'))

def origin_row(row,source=''):
    url=row.get('sourceUrl') or row.get('sourceURL') or row.get('url') or ('https://'+source if source else '')
    return hentai_origin(row.get('provider'),url,row.get('kind','manga')) or any(origin_row({**v,'kind':row.get('kind','manga')}) for v in row.get('sources') or [] if isinstance(v,dict))

def origin_sql(alias='t',manga=False):
    if manga:return "catalog_hentai_origin("+alias+".provider,"+alias+".source_url,'manga')"
    raw=alias+'.raw'
    return "catalog_hentai_origin(json_extract("+raw+",'$.provider'),COALESCE(NULLIF(json_extract("+raw+",'$.sourceUrl'),''),NULLIF(json_extract("+raw+",'$.sourceURL'),''),json_extract("+raw+",'$.url')),"+alias+".kind)"

def register_origin_functions(db):
    db.create_function('catalog_hentai_origin',3,hentai_origin,deterministic=True)
    db.create_function('catalog_not_hentai',1,lambda value:norm(value) in HENTAI_NEGATIVE,deterministic=True)

def initialize_origins(db,manga=False):
    register_origin_functions(db)
    table='catalog_titles' if manga else 'content_titles'
    stamp=hashlib.sha256(json.dumps(HENTAI,sort_keys=True).encode()).hexdigest()[:12]
    prefix='catalog_hentai_origin_' if manga else 'content_hentai_origin_'
    name=prefix+stamp
    veto_prefix='catalog_hentai_veto_' if manga else 'content_hentai_veto_'
    for family in [prefix,veto_prefix]:
        for (old,) in db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE ?",(family+'%',)).fetchall():
            if old!=family+stamp:db.execute('DROP INDEX "'+old+'"')
    expression=origin_sql('t',manga).replace('t.','')
    db.execute('CREATE INDEX IF NOT EXISTS '+name+' ON '+table+'('+expression+')')
    facts='catalog_tag_facts' if manga else 'content_tag_facts'
    veto=veto_prefix+stamp
    db.execute('CREATE INDEX IF NOT EXISTS '+veto+' ON '+facts+'(catalog_not_hentai(original),title_id)')

def hentai_work_set(policy,manga=False):
    from content_catalog import work_sql
    table='catalog_titles' if manga else 'content_titles';tags='catalog_tags' if manga else 'content_tags';facts='catalog_tag_facts' if manga else 'content_tag_facts'
    work=lambda alias:alias+'.work_key' if manga else work_sql(alias)
    wanted=keys('Хентай',policy,allow_hidden=True)
    explicit='SELECT '+work('peer')+' AS work FROM '+tags+' x JOIN '+table+' peer ON peer.id=x.title_id WHERE x.tag_key IN ('+','.join('?' for _ in wanted)+')'
    origins='SELECT '+work('peer')+' FROM '+table+' peer WHERE '+origin_sql('peer',manga)+'=1'
    negative='SELECT '+work('peer')+' FROM '+facts+' f JOIN '+table+' peer ON peer.id=f.title_id WHERE catalog_not_hentai(f.original)=1'
    return 'SELECT eligible.work FROM ('+explicit+' UNION '+origins+') eligible WHERE eligible.work NOT IN ('+negative+')',wanted

def classify(label,field,kind,policy=None,source=''):
    if not isinstance(label,str) or not label.strip() or label.strip().isdecimal():return None
    rule=policy.rules.get(policy.identity(label,source),{}) if policy else {}
    genre=GENRES.get(norm(label)) or GENRES.get(norm(rule.get('label'))) or GENRES.get(norm(rule.get('key')))
    category={'genre':'genres','tag':'tags'}.get(rule.get('category')) or ('genres' if genre else 'tags')
    if kind=='book' and (category!='genres' or not genre and rule.get('category')!='genre'):return None
    if genre and genre.get('kinds') and kind not in genre['kinds']:return None
    return category,(rule.get('label') or (genre['label'] if genre and category=='genres' else label))

def project(policy,row,source=''):
    result={'genres':[],'tags':[]};kind=row.get('kind','manga')
    for field in result:
        for label in row.get(field) or []:
            if not policy.key(label,source):continue
            value=classify(label,field,kind,policy,source)
            if value and value[1] not in result[value[0]]:result[value[0]].append(value[1])
    if hentai_excluded(row):
        result={k:[v for v in values if not is_hentai(v,policy)] for k,values in result.items()}
    elif origin_row(row,source) and policy.key('Хентай',source) and classify('Хентай','genres',kind,policy,source)[0]=='genres':
        label=policy.label(policy.identity('Хентай',source),'Хентай')
        if label not in result['genres']:result['genres'].append(label)
    return {k:v[:120] for k,v in result.items()}

def keys(value,policy,allow_hidden=False):
    if not allow_hidden and not policy.key(value):return []
    row=GENRES.get(norm(value)) or GENRES.get(norm(policy.label(policy.identity(value))))
    labels=[value,*([row['label'],row['key'],*row['aliases']] if row else [])]
    from manga_tag_policy import normalize
    return sorted({key for v in labels for key in (policy.identity(v),normalize(v))})

def clauses(db,*,kind,genre='',tag='',excludeGenre='',excludeTag='',manga=False):
    from manga_tag_policy import current
    policy=current()
    result=[];params=[]
    for field,raw,negative in [('genres',genre,False),('tags',tag,False),('genres',excludeGenre,True),('tags',excludeTag,True)]:
        try:values=raw if isinstance(raw,(list,tuple)) else json.loads(raw) if str(raw or '').startswith('[') else str(raw or '').split(',')
        except (ValueError,TypeError):
            from fastapi import HTTPException
            raise HTTPException(422,'Неверный список фильтров.') from None
        if not isinstance(values,(list,tuple)) or len(values)>64 or any(not isinstance(v,str) or len(v)>120 for v in values):
            from fastapi import HTTPException
            raise HTTPException(422,'Не больше 64 текстовых значений в группе фильтров.')
        values=list(dict.fromkeys(v.strip() for v in values if v.strip()))
        if not values:continue
        wanted=sorted({k for v in values for k in keys(v,policy,allow_hidden=negative) if (classify(k,field,kind,policy) or ('',''))[0]==field})
        if not wanted:
            if not negative:result.append('0')
            continue
        if manga:
            work='t.work_key'
            query='SELECT peer.work_key FROM catalog_tags x JOIN catalog_titles peer ON peer.id=x.title_id WHERE '
        else:
            from content_catalog import work_sql
            work=work_sql('t')
            query='SELECT '+work_sql('peer')+' FROM content_tags x JOIN content_titles peer ON peer.id=x.title_id WHERE '
        # Resolve each signed set once from the tag index, not once per title.
        query+='x.tag_key IN ('+','.join('?' for _ in wanted)+')'
        if field=='genres' and any(is_hentai(k,policy) for k in wanted):
            ordinary=[k for k in wanted if not is_hentai(k,policy)]
            hentai_query,hentai_args=hentai_work_set(policy,manga)
            if ordinary:
                query=query[:query.index('x.tag_key IN (')]+'x.tag_key IN ('+','.join('?' for _ in ordinary)+') UNION '+hentai_query
                wanted=[*ordinary,*hentai_args]
            else:query=hentai_query;wanted=hentai_args
        result.append(work+(' NOT IN (' if negative else ' IN (')+query+')');params.extend(wanted)
    return result,params

def format_label(value,kind):
    return DATA.get('formatAliases',{}).get(kind,{}).get(str(value).casefold(),value)

def maintain_books(store):
    """Resume derived book cleanup in short transactions; retain all raw facts/jobs."""
    import time
    from manga_tag_policy import current
    from content_catalog import _index,invalidate
    marker='taxonomy-books-v1';vmarker='taxonomy-book-vocabulary-v1'
    while not getattr(store,'stopping',False):
        with store.lock,store.db:
            if not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='content_titles'").fetchone():return
            prior=store.db.execute('SELECT value FROM content_catalog_state WHERE name=?',(marker,)).fetchone()
            if not prior or prior[0]!='done':
                rows=store.db.execute("SELECT id,raw FROM content_titles WHERE kind='book' AND id>? ORDER BY id LIMIT 20",(prior[0] if prior else '',)).fetchall()
                for identity,raw in rows:_index(store.db,identity,json.loads(raw),current())
                store.db.execute('INSERT OR REPLACE INTO content_catalog_state VALUES(?,?)',(marker,rows[-1][0] if rows else 'done'))
            else:
                prior=store.db.execute('SELECT value FROM content_catalog_state WHERE name=?',(vmarker,)).fetchone()
                if prior and prior[0]=='done':return
                rows=store.db.execute("SELECT rowid,label,source,category FROM catalog_vocabulary WHERE kind='book' AND rowid>? ORDER BY rowid LIMIT 200",(int(prior[0]) if prior else 0,)).fetchall()
                for rowid,label,source,category in rows:
                    if not classify(label,category,'book',current(),source):store.db.execute('DELETE FROM catalog_vocabulary WHERE rowid=?',(rowid,))
                store.db.execute('INSERT OR REPLACE INTO content_catalog_state VALUES(?,?)',(vmarker,str(rows[-1][0]) if rows else 'done'))
                if not rows:invalidate(store.db);return
        time.sleep(.1)
