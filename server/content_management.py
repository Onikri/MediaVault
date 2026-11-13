"""Private owner-managed global taxonomy. No GitHub writes or remote scripts."""
from pathlib import Path
import difflib,hashlib,json,os,threading,time
from urllib.parse import urlsplit
from fastapi import Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from manga_tag_policy import Policy,current,canonical_json,normalize
from manga_tag_deploy import atomic_write,_update_lock
import content_catalog

_worker_lock=threading.Lock()
_queue_lock=threading.Lock()
_pending=set()
_pending_all=False

def directory():return Path(os.getenv('DATA_DIR','/data'))

def public_policy(store=None):
    with _update_lock:
        if store is not None:
            from content_vocabulary import public
            return public(store)
        data=current().public()
        data.pop('includeDiscovered',None);data.pop('hiddenTags',None)
        return {'revision':hashlib.sha256(canonical_json(data)).hexdigest(),'policy':data,'scope':'all'}

def with_policy(result,revision,store):
    value=public_policy(store)
    return {**result,**({'tagPolicy':value} if value['revision']!=revision else {})}

def prioritize(store,subject,tag='',genre=''):
    if not current().include_discovered or not isinstance(subject,str) or subject.startswith(('guest:','share:')) or not (tag or genre):return
    from catalogue_indexer import ensure
    service=ensure(store)
    if service:service.prioritize([*str(tag or '').split(','),genre])

def save(store,data,expected):
    data=json.loads(json.dumps(data))
    # Deleting an explicitly configured rule in automatic mode must not let
    # its original spellings silently reappear as newly discovered tags.
    previous=current()
    if data.get('includeDiscovered'):
        remaining={row.get('key') for row in data.get('tags',[]) if isinstance(row,dict)}
        hidden=list(data.get('hiddenTags',[]))
        for key,row in previous.rules.items():
            if key not in remaining:hidden.extend([key,row['label'],*row['aliases'],*(v for values in row.get('sourceAliases',{}).values() for v in values)])
        data['hiddenTags']=list(dict.fromkeys(hidden))
    try:policy=Policy(data)
    except (ValueError,TypeError,KeyError):raise HTTPException(422,'Проверь названия, синонимы и повторяющиеся соответствия тегов.') from None
    with _update_lock,store.lock:
        if current().revision!=expected:raise HTTPException(409,'Правила уже изменены в другой вкладке. Обнови данные перед сохранением.')
        path=directory()/'manga-tag-policy.json';prior=path.read_bytes() if path.exists() else None
        previous=current()
        if previous.revision==policy.revision:return {'revision':policy.revision,'unchanged':True,'reindexedTitles':0}
        try:
            from manga_catalog_index import reindex
            with store.db:
                if previous.include_discovered and policy.include_discovered and previous.data['tags']==policy.data['tags']:
                    # Visibility changes need no corpus rewrite: source facts and
                    # canonical lookup keys remain indexed independently.
                    content_catalog.initialize(store.db)
                    count=store.db.execute('SELECT COUNT(*) FROM catalog_titles').fetchone()[0]+store.db.execute('SELECT COUNT(*) FROM content_titles').fetchone()[0]
                    store.db.execute("INSERT OR REPLACE INTO catalog_policy_state VALUES('revision',?)",(policy.revision,))
                    store.db.execute("INSERT OR REPLACE INTO content_catalog_state VALUES('policy',?)",(policy.revision,))
                    content_catalog.invalidate(store.db)
                else:count=reindex(store.db,policy)+content_catalog.reindex(store.db,policy)
                atomic_write(path,canonical_json(policy.data)+b'\n')
                store.db.execute("INSERT OR REPLACE INTO catalog_policy_state VALUES('commit','private-owner')")
        except BaseException:
            if prior is not None:atomic_write(path,prior)
            elif path.exists():path.unlink()
            raise
        changed=[key for key,rule in policy.rules.items() if previous.rules.get(key)!=rule or key in previous.hidden and key not in policy.hidden]
        return {'revision':policy.revision,'unchanged':False,'reindexedTitles':count,'changedKeys':changed}

def inventory(store,q='',limit=80):
    from content_vocabulary import initialize
    policy=current();terms={}
    with store.lock,store.db:
        content_catalog.initialize(store.db);initialize(store.db)
        for label,source,category,kind in store.db.execute('SELECT label,source,category,kind FROM catalog_vocabulary'):
            token=normalize(label)
            item=terms.setdefault(token,{'label':label,'labels':set(),'sources':set(),'kinds':set(),'category':category})
            item['labels'].add(label)
            if source:item['sources'].add(source)
            item['kinds'].add(kind)
        query=normalize(q);results=[]
        for token,row in terms.items():
            score=1 if not query or query in token else difflib.SequenceMatcher(None,query,token).ratio()
            if query and query not in token and score<.55:continue
            keys={policy.key(row['label'],source) for source in row['sources'] or ['']}-{''}
            results.append({'label':row['label'],'sources':sorted(row['sources']),'kinds':sorted(row['kinds']),
                'category':row['category'],'keys':sorted(keys),'score':round(score,3),'labels':row['labels']})
        results.sort(key=lambda row:(-row['score'],row['label']))
        total=len(results);results=results[:limit]
        for row in results:
            labels=list(row.pop('labels'));marks=','.join('?' for _ in labels)
            row['works']=store.db.execute('SELECT COUNT(DISTINCT title_id) FROM catalog_tag_facts WHERE original IN ('+marks+')',labels).fetchone()[0]+store.db.execute('SELECT COUNT(DISTINCT title_id) FROM content_tag_facts WHERE original IN ('+marks+')',labels).fetchone()[0]
    return {'items':results,'total':total}


def scan_status():
    try:
        value=json.loads((directory()/'content-index-job.json').read_text())
        if value.get('state') in {'running','queued'} and not _worker_lock.locked():value.update(state='interrupted',error='Сервер перезапускался. Нажми «Проверить источники», чтобы продолжить; сохранённые правила действуют.')
        return value
    except (OSError,ValueError):return {'state':'idle','sources':[]}

def start_scan(store,keys=None):
    global _pending_all
    if not _worker_lock.acquire(blocking=False):
        with _queue_lock:
            if keys is None:_pending_all=True
            else:_pending.update(keys)
            atomic_write(directory()/'content-pending-keys.json',canonical_json({'all':_pending_all,'keys':sorted(_pending)}))
        return {**scan_status(),'pendingChanges':True}
    with _queue_lock:
        if keys is not None:
            keys=list(dict.fromkeys(keys));_pending.update(keys[3:]);keys=keys[:3]
        atomic_write(directory()/'content-pending-keys.json',canonical_json({'all':_pending_all,'keys':sorted(_pending)}))
        remaining=len(_pending)
    status={'state':'queued','startedAt':int(time.time()),'completed':0,'total':24,'indexed':0,'sources':[],'keys':keys,'remainingKeys':remaining}
    atomic_write(directory()/'content-index-job.json',canonical_json(status))
    def run():
        global _pending_all
        try:
            from content_sources import scan
            from content_metadata import scan as metadata_scan
            import itertools
            for row in itertools.chain(metadata_scan(store,keys),scan(store,keys)):
                status['state']='running';status['sources'].append(row);status['completed']+=1;status['indexed']+=row.get('indexed',0)
                atomic_write(directory()/'content-index-job.json',canonical_json(status))
            status['state']='done'
        except Exception:
            status.update(state='failed',error='Не удалось завершить обновление источников. Сохранённые правила действуют; повтори обновление.')
        finally:
            status['finishedAt']=int(time.time());atomic_write(directory()/'content-index-job.json',canonical_json(status));_worker_lock.release()
            with _queue_lock:
                full=_pending_all;pending=list(_pending);_pending.clear();_pending_all=False
                atomic_write(directory()/'content-pending-keys.json',canonical_json({'all':False,'keys':[]}))
            if full or pending:start_scan(store,None if full else pending)
    threading.Thread(target=run,name='content-vocabulary',daemon=True).start()
    return status

def recover(manager):
    try:
        status=json.loads((directory()/'content-index-job.json').read_text())
        try:pending=json.loads((directory()/'content-pending-keys.json').read_text())
        except (OSError,ValueError):pending={}
        if status.get('state') in {'queued','running'} or pending.get('all') or pending.get('keys'):
            keys=None if status.get('keys') is None or pending.get('all') else sorted(set(status.get('keys',[])+pending.get('keys',[])))
            start_scan(manager(),keys)
    except (OSError,ValueError):pass
    if current().include_discovered:
        from catalogue_indexer import ensure
        ensure(manager())

class PolicyUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:str=Field(min_length=64,max_length=64)
    policy:dict

class CatalogueFacts(BaseModel):
    model_config=ConfigDict(extra='forbid')
    items:list[dict]=Field(max_length=100)

def install(app,owner,viewer,manager):
    @app.get('/admin/content')
    def read_content(subject=Depends(owner)):
        if current().include_discovered:
            from catalogue_indexer import ensure
            service=ensure(manager())
        else:service=None
        with _update_lock:
            policy=current()
            return {'revision':policy.revision,'policy':policy.data,'job':service.status() if service else scan_status(),'scope':'all','storage':'private-oracle'}

    @app.put('/admin/content/policy')
    def write_content(body:PolicyUpdate,subject=Depends(owner)):
        store=manager();result=save(store,body.policy,body.revision)
        keys=result.pop('changedKeys',[])
        if current().include_discovered:
            from catalogue_indexer import ensure
            service=ensure(store)
            if service:
                service.prioritize([current().label(key) for key in keys]);result['job']=service.status()
        elif keys:result['job']=start_scan(store,keys)
        return {**result,'policy':current().data,'scope':'all'}

    @app.get('/admin/content/vocabulary')
    def vocabulary(q:str='',subject=Depends(owner)):
        return inventory(manager(),q[:120])

    @app.post('/admin/content/refresh')
    def refresh_content(subject=Depends(owner)):
        if current().include_discovered:
            from catalogue_indexer import ensure
            service=ensure(manager())
            if service:
                from suwayomi_bridge import sources
                service.seed(sources())
                with service.store.lock,service.store.db:service.store.db.execute("UPDATE catalogue_jobs SET state='queued',due=0 WHERE state IN ('done','partial','retry','unsupported') AND spec NOT LIKE '%-detail%'")
                return service.status()
        prior=scan_status()
        return start_scan(manager(),prior.get('keys') if prior.get('state') in {'failed','interrupted'} else None)

    @app.get('/admin/content/job')
    def read_job(subject=Depends(owner)):
        if current().include_discovered:
            from catalogue_indexer import ensure
            service=ensure(manager())
            if service:return service.status()
        return scan_status()

    @app.get('/catalog/status')
    def public_status(subject=Depends(viewer)):
        from catalogue_indexer import ensure
        service=ensure(manager())
        return service.status() if service else {'state':'disabled','indexed':0,'sources':[]}

    @app.post('/catalog/content/facts')
    def record_facts(body:CatalogueFacts,subject=Depends(owner)):
        store=manager()
        with store.lock,store.db:return {'indexed':content_catalog.ingest(store.db,body.items)}

    @app.get('/catalog/content')
    def content(q:str='',kind:str='anime',tag:str='',genre:str='',offset:int=0,limit:int=60,tagPolicyRevision:str='',subject=Depends(viewer)):
        store=manager()
        with store.lock:result=content_catalog.browse(store.db,kind=kind,q=q[:160],tag=tag[:120],genre=genre[:120],offset=offset,limit=limit)
        prioritize(store,subject,tag,genre)
        return with_policy(result,tagPolicyRevision,store)
