"""AniSkip v2 metadata, never guessed 90-second intervals or video uploads."""
import json,math,threading,time,requests
from collections import OrderedDict
from source_parser import SourceError,USER_AGENT

def get_json(url,params=None):
    try:
        with requests.get(url,params=params,headers={'User-Agent':USER_AGENT,'Accept':'application/json'},timeout=(4,7),stream=True,allow_redirects=False) as response:
            raw=bytearray()
            for block in response.iter_content(65536):
                raw.extend(block)
                if len(raw)>1024*1024:raise SourceError('Ответ базы разметки слишком велик.')
            data=json.loads(raw)
            # AniSkip uses 404 for a successful lookup with no community marks.
            if response.status_code==404 and data.get('found') is False:return data
            if not response.ok or not isinstance(data,dict):raise SourceError('База разметки временно недоступна.')
            return data
    except (requests.RequestException,ValueError,AttributeError):raise SourceError('База разметки временно недоступна.') from None

_cache=OrderedDict();_lock=threading.Lock()
def _read(url,params=None):
    key=(url,tuple(params or []));now=time.monotonic()
    with _lock:old=_cache.get(key)
    if old and old[0]>now:return old[1]
    data=get_json(url,params=params)
    with _lock:
        _cache[key]=(now+(3600 if data.get('found') else 120),data)
        while len(_cache)>256:_cache.popitem(last=False)
    return data

def numeric(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def choose_intervals(data,duration):
    chosen={}
    for row in data.get('results',[]):
        if not isinstance(row,dict):continue
        interval=row.get('interval') or {};kind=row.get('skipType');start=interval.get('startTime');end=interval.get('endTime');length=row.get('episodeLength')
        if kind not in {'op','ed'} or not all(numeric(v) for v in [start,end]) or not 0<=start<end<=duration+2:continue
        difference=abs(length-duration) if numeric(length) and length>0 else 0
        # A substantially different cut must not skip dialogue. Smaller release
        # differences are explicit in the UI and can be adjusted by the viewer.
        if difference>30:continue
        value={'type':kind,'start':start,'end':min(end,duration),'source':'AniSkip','durationDifference':round(difference,3),'needsReview':difference>2}
        if kind not in chosen or difference<chosen[kind]['durationDifference']:chosen[kind]=value
    return list(chosen.values())

def skip_times(identity,episode,duration):
    mapped_id,mapped_episode=identity,episode
    try:
        # AniSkip rules are essential for catalogues numbering across seasons.
        rules=_read(f'https://api.aniskip.com/v2/relation-rules/{identity}')
        for rule in rules.get('rules',[]):
            origin=rule.get('from') or {};target=rule.get('to') or {};start=origin.get('start');end=origin.get('end',start)
            if all(isinstance(v,int) and not isinstance(v,bool) for v in [start,end,target.get('start'),target.get('malId')]) and 1<=start<=episode<=end<=10000 and 1<=target['malId']<=10**12:
                mapped_id=target['malId'];mapped_episode=target['start']+episode-start;break
    except (SourceError,ValueError,TypeError,AttributeError):pass
    try:
        data=_read(f'https://api.aniskip.com/v2/skip-times/{mapped_id}/{mapped_episode}',[('types[]','op'),('types[]','ed'),('episodeLength',round(duration,3))])
        parts=choose_intervals(data,duration)
        return {'intervals':parts,'source':'AniSkip','animeId':mapped_id,'episode':mapped_episode,'message':'' if parts else 'Для этой версии серии разметки пока нет.'}
    except (SourceError,ValueError,TypeError,AttributeError):
        return {'intervals':[],'source':'AniSkip','message':'База разметки временно недоступна. Можно повторить поиск или отметить опенинг вручную.','unavailable':True}
