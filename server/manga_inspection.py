"""Bounded, shared chapter metadata cache; never stores page images or credentials."""
import copy,threading,time
from source_parser import SourceError

_lock=threading.RLock();_cache={};_running={};_slots=threading.BoundedSemaphore(3)

def inspect(url,refresh=False):
    with _lock:
        if refresh:_cache.pop(url,None)
        hit=_cache.get(url)
        if hit and hit[0]>time.monotonic():return copy.deepcopy(hit[1])
        pending=_running.get(url)
        if pending is None:pending={'event':threading.Event()};_running[url]=pending;leader=True
        else:leader=False
    if not leader:
        if not pending['event'].wait(70):raise SourceError('Источник не успел вернуть главы. Повтори проверку.')
        if 'error' in pending:raise SourceError(pending['error'])
        return copy.deepcopy(pending['value'])
    acquired=False
    try:
        acquired=_slots.acquire(timeout=5)
        if not acquired:raise SourceError('Проверяются другие источники. Повтори через несколько секунд.')
        from manga_sources import inspect as upstream
        value=upstream(url)
        value={**value,'chapterCount':len({(e.get('season',1),e['number']) for e in value.get('episodes',[])}),'volumeCount':len(value.get('seasons',[]))}
        with _lock:
            if len(_cache)>=64:_cache.pop(next(iter(_cache)))
            _cache[url]=(time.monotonic()+120,copy.deepcopy(value));pending['value']=copy.deepcopy(value)
        return value
    except Exception as error:
        with _lock:pending['error']=str(error) if isinstance(error,SourceError) else 'Не удалось проверить главы источника.'
        raise
    finally:
        if acquired:_slots.release()
        with _lock:_running.pop(url,None);pending['event'].set()
