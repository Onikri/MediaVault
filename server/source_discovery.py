"""Exact-title search and translation aggregation with bounded, isolated source requests."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from title_identity import aliases, match_title
from site_adapters import SITES, search_site, inspect_source
from player_catalog import group_voices
from source_parser import PublicHttp

_cache={};_lock=threading.Lock();_slots=threading.BoundedSemaphore(2)


def discover(selected):
    if not aliases(selected):raise ValueError('Выбери конкретный тайтл из каталога.')
    key=repr((selected.get('ids'),aliases(selected),selected.get('year'),selected.get('kind')))
    with _lock:
        hit=_cache.get(key)
        if hit and hit[0]>time.monotonic():return hit[1]
    if not _slots.acquire(blocking=False):raise ValueError('Поиск источников уже выполняется. Повтори через несколько секунд.')
    try:
        queries=list(dict.fromkeys(aliases(selected)))[:2]
        def work(site):
            http=PublicHttp(timeout=(2,4),deadline=time.monotonic()+12)
            try:
                matches=[];status='empty';message='Точное совпадение тайтла и сезона не найдено.'
                for query in queries:
                    response=search_site(site,query,http=http)
                    status=response['status'];message=response.get('message',message)
                    for candidate in response['results']:
                        accepted,evidence=match_title(selected,candidate)
                        if accepted and not any(m['url']==candidate['url'] for m in matches):
                            matches.append({**candidate,'matchEvidence':evidence})
                    if matches:break
                inspected=[]
                for candidate in matches[:2]:
                    try:
                        value=inspect_source(candidate['url'],http=http,kind=selected.get('kind','anime'))
                        # HTML title must not contradict the selected identity. Search snippets can be stale.
                        page_title=value.get('title','').split(' / ')[0]
                        if page_title and not match_title(selected,{'title':page_title,'kind':'anime'})[0]:
                            # Site suffixes are allowed only after an exact catalogue title.
                            if not any(page_title.casefold().startswith(name.casefold()+' ') or page_title.casefold()==name.casefold() for name in aliases(candidate)):
                                continue
                        inspected.append({**value,'title':candidate['title'],'providerName':site.name,'matchEvidence':candidate['matchEvidence']})
                    except Exception:
                        status='unavailable';message='Страница найдена, плееры временно не ответили.'
                return {'provider':site.id,'name':site.name,'status':'ok' if inspected else 'no_match' if matches or status in {'ok','empty'} else status,'message':message,'sources':inspected}
            except Exception:
                return {'provider':site.id,'name':site.name,'status':'unavailable','message':'Источник не ответил или изменил разметку.','sources':[]}
            finally:http.close()
        sites=[s for s in SITES if s.kind=='anime' and s.id not in {'sovet','anilibriafun','animevosttv'}]
        with ThreadPoolExecutor(max_workers=6) as pool:providers=list(pool.map(work,sites))
        sources=[s for p in providers for s in p.pop('sources')]
        result={'title':selected,'voices':group_voices(sources),'sources':sources,'providers':providers,'checkedAt':int(time.time())}
        with _lock:
            if len(_cache)>=80:_cache.pop(next(iter(_cache)))
            _cache[key]=(time.monotonic()+(300 if sources else 30),result)
        return result
    finally:_slots.release()
