"""Exact-title search and translation aggregation with bounded, isolated source requests."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import threading
import time
import re
from title_identity import aliases, match_title
from site_adapters import SITES, search_site, inspect_source
from player_catalog import group_voices
from source_parser import PublicHttp

_cache={};_lock=threading.Lock();_slots=threading.BoundedSemaphore(2)
_progress={}

def voice_suggestions(query='',limit=30):
    """Labels observed on real Russian source/player pages; never a studio list.

    An unknown language stays unknown in the response, rather than fabricating
    language verification for a Russian provider's player label.
    """
    query=' '.join(str(query).casefold().split())[:80];now=time.monotonic();groups={}
    with _lock:
        snapshots=[entry[1] for entry in _cache.values() if entry[0]>now]
    for snapshot in snapshots:
        for voice in snapshot.get('voices',[]):
            name=voice.get('name','');kind=voice.get('kind','');language=voice.get('language','und')
            if not name or kind in {'sub','subs','subtitle','subtitles'} or language not in {'ru','und'} or query not in name.casefold():continue
            variants=[v for v in voice.get('variants',[]) if v.get('named',True) and v.get('sourceUrl')]
            if not variants:continue
            key=(name.casefold(),kind,language)
            group=groups.setdefault(key,{'id':voice['id'],'name':name,'kind':kind,'language':language,'observed':True,'providers':set(),'sourceCount':0})
            group['providers'].update(v.get('providerName') or v.get('provider','') for v in variants)
            group['sourceCount']+=len(variants)
    values=[{**v,'providers':sorted(v['providers'])} for v in groups.values()]
    values.sort(key=lambda v:(not v['name'].casefold().startswith(query),v['name'].casefold()))
    return {'query':query,'voices':values[:max(1,min(int(limit),50))],'total':len(values),'observedOnly':True}


def _discover(selected,*,refresh=False,continuing=False):
    if not aliases(selected):raise ValueError('Выбери конкретный тайтл из каталога.')
    key=repr((selected.get('ids'),aliases(selected),selected.get('year'),selected.get('kind')))
    with _lock:
        hit=_cache.get(key)
        if not refresh and hit and hit[0]>time.monotonic():return hit[1]
        if refresh and not continuing:
            hit=None
            for stale in [k for k in _progress if k[0]==key]:_progress.pop(stale,None)
        known={s['url']:s for s in hit[1]['sources'] if s.get('complete',True)} if hit and hit[0]>time.monotonic() else {}
    if not _slots.acquire(blocking=False):raise ValueError('Поиск источников уже выполняется. Повтори через несколько секунд.')
    try:
        names=aliases(selected)
        # Search engines rarely match a catalogue's full localized film title.
        # Broaden the query only; all results still pass exact title/year/ID.
        stems=[v.split(':',1)[0].split('. Фильм',1)[0].strip() for v in names if re.search(r'[а-яё]',v,re.I)]
        keywords=[v.split()[-1].strip(' .:!?') for v in names if ':' in v and re.search(r'[а-яё]',v,re.I)]
        queries=list(dict.fromkeys([*names[:2],*[v for v in keywords if len(v)>=4],*[v for v in stems if len(v)>=4]]))[:4]
        def work(site):
            http=PublicHttp(timeout=(2,4),deadline=time.monotonic()+15)
            try:
                matches=[{**s,'kind':selected.get('kind','anime'),'matchEvidence':s.get('matchEvidence','exact_title')} for s in (hit[1]['sources'] if hit and hit[0]>time.monotonic() else []) if s.get('provider')==site.id]
                status='empty';message='Точное совпадение тайтла и сезона не найдено.'
                for query in queries:
                    response=search_site(site,query,http=http)
                    status=response['status'];message=response.get('message',message)
                    for candidate in response['results']:
                        accepted,evidence=match_title(selected,candidate)
                        if accepted and not any(m['url']==candidate['url'] for m in matches):
                            matches.append({**candidate,'matchEvidence':evidence})
                    if matches:break  # Leave the request budget for its players.
                inspected=[];provider_pending=False
                for candidate in matches:
                    if candidate['url'] not in known and http.deadline and time.monotonic()>=http.deadline:
                        provider_pending=True;break
                    try:
                        if candidate['url'] in known:value=known[candidate['url']]
                        else:
                            progress_key=(key,candidate['url'])
                            with _lock:
                                for stale in [k for k,v in _progress.items() if v['expires']<time.monotonic()]:_progress.pop(stale,None)
                                if progress_key not in _progress:
                                    if len(_progress)>=64:_progress.pop(next(iter(_progress)))
                                    _progress[progress_key]={'state':{},'lock':threading.Lock(),'expires':time.monotonic()+300}
                                progress=_progress[progress_key]
                            with progress['lock']:
                                value=inspect_source(candidate['url'],http=http,kind=selected.get('kind','anime'),state=progress['state'])
                                progress['expires']=time.monotonic()+300
                            if not value.get('pending'):
                                with _lock:_progress.pop(progress_key,None)
                        verified={**candidate,'ids':value.get('ids') or candidate.get('ids') or {},'year':value.get('year') or candidate.get('year')}
                        accepted,evidence=match_title(selected,verified)
                        if not accepted:continue
                        if selected.get('year') and not verified.get('year') and evidence!='external_id':
                            status='unverified';message='Название совпадает, но год или внешний ID не подтверждён страницей.';continue
                        # HTML title must not contradict the selected identity. Search snippets can be stale.
                        import re
                        page_title=re.split(r'\s+(?:смотреть|watch)\b|\s+[|–—]\s+',value.get('title',''),flags=re.I)[0]
                        if page_title and not match_title(selected,{'title':page_title,'kind':'anime'})[0]:
                            continue
                        inspected.append({**value,'title':candidate['title'],'providerName':site.name,'matchEvidence':candidate['matchEvidence']})
                    except Exception:
                        status='unavailable';message='Страница найдена, плееры временно не ответили.'
                count=sum(len(v.get('dubs',[])) for v in inspected)
                provider_status='ok' if count else 'no_players' if inspected else status if status in {'unavailable','unverified'} else 'no_match'
                if count:message='Найдено вариантов плееров: '+str(count)+'. Доступность серии проверяется перед просмотром.'
                elif inspected:message='Тайтл найден, но доступные плееры не подтверждены.'
                return {'provider':site.id,'name':site.name,'status':provider_status,'pending':provider_pending,'complete':not provider_pending and all(v.get('complete',True) for v in inspected) and status!='unavailable','message':message,'sources':inspected}
            except Exception:
                return {'provider':site.id,'name':site.name,'status':'unavailable','message':'Источник не ответил или изменил разметку.','sources':[]}
            finally:http.close()
        sites=[s for s in SITES if selected.get('kind','anime')=='anime' and s.kind=='anime' and s.id not in {'sovet','anilibriafun','animevosttv'}]
        providers=[]
        def snapshot(unfinished=False):
            sources=[s for p in providers for s in p.get('sources',[])]
            for previous in known.values():
                if not any(s['url']==previous['url'] for s in sources):sources.append(previous)
            return {'title':selected,'voices':group_voices(sources),'sources':sources,
                'providers':[{k:v for k,v in p.items() if k!='sources'} for p in providers],
                'progress':len(providers)+sum(s.get('scannedPages',1) for s in sources),
                'pending':unfinished or any(s.get('pending') for s in sources) or any(p.get('pending') for p in providers),
                'complete':not unfinished and all(p.get('complete',False) for p in providers),'checkedAt':int(time.time())}
        with ThreadPoolExecutor(max_workers=6) as pool:
            from kodik_api import discover as kodik_discover
            futures=[pool.submit(kodik_discover,selected),*[pool.submit(work,site) for site in sites]]
            if selected.get('kind','anime') in {'anime','movie'} and str((selected.get('ids') or {}).get('mal'))=='57555':
                from yummy_anime_source import discover_reze
                futures.append(pool.submit(discover_reze))
            for future in as_completed(futures):
                providers.append(future.result());result=snapshot(len(providers)<len(futures))
                with _lock:_cache[key]=(time.monotonic()+(300 if result['sources'] else 30),result)
                with _jobs_lock:job=_jobs.get(key)
                if job and result['voices']:job['changed'].set()
        result=snapshot()
        with _lock:
            if len(_cache)>=80:_cache.pop(next(iter(_cache)))
            _cache[key]=(time.monotonic()+(300 if result['sources'] else 30),result)
        from source_index import save
        save(key,result)
        return result
    finally:_slots.release()


_jobs={};_jobs_lock=threading.RLock()

def discover(selected,*,refresh=False,continuing=False):
    if not aliases(selected):raise ValueError('Выбери конкретный тайтл из каталога.')
    key=repr((selected.get('ids'),aliases(selected),selected.get('year'),selected.get('kind')))
    with _lock:hit=_cache.get(key)
    with _jobs_lock:
        job=_jobs.get(key)
        if job is None and (not refresh or continuing) and hit and hit[0]>time.monotonic() and not hit[1].get('pending'):return hit[1]
        if job is None:
            if len(_jobs)>=2:
                if hit:return {**hit[1],'pending':True,'complete':False,'refreshing':True}
                raise ValueError('Поиск других тайтлов уже выполняется. Повтори через несколько секунд.')
            if not hit and not refresh:
                from source_index import load
                old=load(key)
                if old:
                    hit=(time.monotonic()+30,{**old,'title':selected})
                    with _lock:_cache[key]=hit
            job=_jobs[key]={'changed':threading.Event(),'done':threading.Event()}
            def run():
                try:_discover(selected,refresh=True,continuing=continuing or bool(hit))
                except Exception:job['error']=True
                finally:
                    job['done'].set();job['changed'].set()
                    with _jobs_lock:_jobs.pop(key,None)
            threading.Thread(target=run,daemon=True,name='voice-discovery').start()
    if hit and hit[1].get('voices'):return {**hit[1],'pending':True,'complete':False,'refreshing':True}
    # Fast providers can unlock playback before slow providers finish. Subsequent
    # polling joins the same job; it never starts a second catalogue crawl.
    job['changed'].wait(1.5)
    with _lock:current=_cache.get(key)
    if current:return {**current[1],'refreshing':not job['done'].is_set()}
    if job.get('error'):raise ValueError('Источники пока не ответили. Повтори поиск.')
    return {'title':selected,'voices':[],'sources':[],'providers':[],'progress':0,'pending':not job['done'].is_set(),'complete':job['done'].is_set(),'checkedAt':int(time.time())}
