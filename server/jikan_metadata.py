"""Bounded, key-free MAL metadata. Jikan first; user-supplied Tenrai compatibility fallback."""
from collections import OrderedDict
from datetime import datetime, timezone
import re
import threading
import time
import requests
from source_parser import SourceError

BASES = ('https://api.jikan.moe/v4', 'https://api.tenrai.org/v1')
_cache, _pending, _failed_until, _next_request = OrderedDict(), {}, {}, {}
_lock = threading.RLock()
_PATH = re.compile(r'(?:anime|manga)(?:/[1-9]\d{0,11}(?:/(?:full|pictures|videos|characters|staff|relations|episodes))?)?|top/(?:anime|manga)|seasons/(?:now|upcoming|20\d{2}/(?:winter|spring|summer|fall))|schedules|(?:characters|people)/[1-9]\d{0,11}(?:/full)?')
_PARAMS = {'q','page','limit','sfw','order_by','sort','filter','type','status','start_date','end_date','genres'}


def _fetch(base, path, params):
    with _lock:
        start = max(time.monotonic(), _next_request.get(base, 0))
        delay = start - time.monotonic()
        if delay > 10:raise SourceError('Очередь каталога занята. Повтори немного позже.')
        _next_request[base] = start + 1.05  # <= 60/minute, shared by all consumers
    if delay > 0:
        time.sleep(delay)
    with requests.Session() as session:
        with session.get(base+'/'+path, params=params, timeout=(2,4), stream=True,
                         headers={'Accept':'application/json','User-Agent':'MediaVault/5.6 public metadata'}) as response:
            response.raise_for_status()
            raw = bytearray()
            for block in response.iter_content(65536):
                raw.extend(block)
                if len(raw) > 8*1024*1024:
                    raise SourceError('Ответ каталога слишком велик.')
            import json
            value = json.loads(raw)
            if not isinstance(value, dict) or 'data' not in value:
                raise SourceError('Каталог вернул неполные данные.')
            return value


def jikan_json(path, params=None):
    path = str(path).strip('/')
    if not _PATH.fullmatch(path):
        raise SourceError('Неизвестный раздел метаданных.')
    params = {str(k):str(v) for k,v in (params or {}).items() if k in _PARAMS and v is not None}
    if any(len(v)>160 for v in params.values()):
        raise SourceError('Слишком длинный запрос.')
    try:
        if 'limit' in params:params['limit'] = str(max(1,min(25,int(params['limit']))))
        if 'page' in params:params['page'] = str(max(1,min(100,int(params['page']))))
    except ValueError:
        raise SourceError('Неверный номер страницы или размер выдачи.') from None
    if re.fullmatch(r'(?:anime|manga)/[1-9]\d*(?:/(?:full|pictures|videos|characters|staff|relations))?',path):
        params = {}  # Resource routes have no list pagination; share their cache entries.
    key = (path, tuple(sorted(params.items())))
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.monotonic():return hit[1]
        pending = _pending.get(key)
        leader = pending is None
        if leader:pending = _pending[key] = threading.Event()
    if not leader:
        if pending.wait(16):
            with _lock:
                if key in _cache:return _cache[key][1]
        raise SourceError('Каталог пока не ответил. Повтори поиск.')
    try:
        for base in BASES:
            with _lock:
                if _failed_until.get(base,0)>time.monotonic():continue
            try:
                value = _fetch(base,path,params)
                with _lock:
                    _cache[key] = (time.monotonic()+(900 if path.startswith(('seasons/','schedules')) else 21600),value)
                    _cache.move_to_end(key)
                    while len(_cache)>512:_cache.popitem(last=False)
                return value
            except (requests.RequestException, ValueError, SourceError):
                with _lock:_failed_until[base] = time.monotonic()+30
        with _lock:
            if hit:return hit[1]  # retained public metadata during an upstream outage
        raise SourceError('Метаданные MyAnimeList сейчас недоступны.')
    finally:
        with _lock:_pending.pop(key,None)
        pending.set()


def home_feed():
    now = datetime.now(timezone.utc)
    season = ('winter','spring','summer','fall')[(now.month-1)//3]
    label = {'winter':'Зима','spring':'Весна','summer':'Лето','fall':'Осень'}[season]+' '+str(now.year)
    from concurrent.futures import ThreadPoolExecutor
    def load(path,params):
        try:return jikan_json(path,params).get('data',[])
        except SourceError:return []
    with ThreadPoolExecutor(max_workers=2) as pool:
        current = pool.submit(load,f'seasons/{now.year}/{season}',{'limit':24,'sfw':'true'})
        popular = pool.submit(load,'top/anime',{'limit':24,'filter':'bypopularity','sfw':'true'})
        current,popular = current.result(),popular.result()
    current = [r for r in current if (not r.get('season') or r['season']==season) and (not r.get('year') or r['year']==now.year)]
    from metadata_helpers import localize
    rows = {str(r.get('mal_id')):r for r in current+popular if r.get('mal_id')}
    localize('jikan',{'data':list(rows.values())},'anime')
    return {'season':{'year':now.year,'name':season,'label':label},'current':current,'popular':popular,
            'sources':['MyAnimeList / Jikan'],'updatedAt':now.isoformat()}
