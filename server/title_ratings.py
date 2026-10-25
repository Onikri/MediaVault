"""Public, key-free ratings linked only through an exact MAL identifier."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import math
import re
import threading
import time
from metadata_catalog import get_json,metadata
from source_parser import SourceError

_cache={};_lock=threading.RLock()
PLATFORMS={'shikimori':'Шикимори','mal':'MyAnimeList','anilist':'AniList','kitsu':'Kitsu'}

def score(provider,value,scale,url,votes=None):
    try:value=float(value)
    except (ValueError,TypeError):return None
    if not math.isfinite(value) or not 0<value<=scale:return None
    return {'provider':provider,'name':PLATFORMS[provider],'value':value,'scale':scale,'normalized':round(value/scale*10,2),'url':url,
            'votes':int(votes) if isinstance(votes,(int,float)) and math.isfinite(votes) and votes>0 else None}

def fetch_rating(provider,identity,kind):
    resource='manga' if kind in {'manga','ranobe'} else 'anime'
    if provider=='shikimori':
        value=metadata('shikimori',identity=identity,kind=resource)
        if str(value.get('id'))!=identity:return None
        votes=sum(int(row.get('value') or 0) for row in value.get('rates_scores_stats',[]))
        return score(provider,value.get('score'),10,f'https://shikimori.io/{resource}s/{identity}',votes)
    if provider=='mal':
        value=get_json(f'https://api.jikan.moe/v4/{resource}/{identity}').get('data') or {}
        if str(value.get('mal_id'))!=identity:return None
        return score(provider,value.get('score'),10,f'https://myanimelist.net/{resource}/{identity}',value.get('scored_by'))
    if provider=='anilist':
        body={'query':'query($id:Int!,$type:MediaType!){Media(idMal:$id,type:$type){id idMal averageScore siteUrl stats{scoreDistribution{amount}}}}','variables':{'id':int(identity),'type':'MANGA' if resource=='manga' else 'ANIME'}}
        value=(get_json('https://graphql.anilist.co',body=body).get('data') or {}).get('Media') or {}
        if str(value.get('idMal'))!=identity or not str(value.get('id','')).isdigit():return None
        votes=sum(int(r.get('amount') or 0) for r in (value.get('stats') or {}).get('scoreDistribution') or [])
        return score(provider,value.get('averageScore'),100,f'https://anilist.co/{resource}/{value["id"]}',votes)
    data=get_json('https://kitsu.io/api/edge/mappings',params={'filter[externalSite]':'myanimelist/'+resource,'filter[externalId]':identity,'include':'item'})
    matches=[r for r in data.get('data',[]) if str(r.get('attributes',{}).get('externalId'))==identity and r.get('attributes',{}).get('externalSite')=='myanimelist/'+resource]
    targets={(r.get('relationships',{}).get('item',{}).get('data',{}).get('type'),r.get('relationships',{}).get('item',{}).get('data',{}).get('id')) for r in matches}
    for row in data.get('included',[]):
        if (row.get('type'),row.get('id')) not in targets or row.get('type')!=resource or not str(row.get('id','')).isdigit():continue
        attributes=row.get('attributes') or {};votes=sum(int(v or 0) for v in (attributes.get('ratingFrequencies') or {}).values())
        return score(provider,attributes.get('averageRating'),100,f'https://kitsu.io/{resource}/{row["id"]}',votes)
    return None

def ratings(identity,kind='anime'):
    identity=str(identity)
    if not re.fullmatch(r'[1-9]\d{0,11}',identity) or kind not in {'anime','manga','ranobe'}:raise SourceError('Для оценок нужен точный ID аниме или манги.')
    kind='manga' if kind in {'manga','ranobe'} else 'anime'
    def work(provider):
        key=(provider,identity,kind)
        with _lock:cached=_cache.get(key)
        if cached and cached[0]>time.monotonic():return cached[1]
        try:
            item=fetch_rating(provider,identity,kind)
            if item:item['checkedAt']=datetime.now(timezone.utc).isoformat()
            result={'provider':provider,'name':PLATFORMS[provider],'status':'ok' if item else 'unrated','item':item}
        except Exception:result={'provider':provider,'name':PLATFORMS[provider],'status':'unavailable','item':None}
        with _lock:
            if len(_cache)>512:_cache.clear()
            _cache[key]=(time.monotonic()+(21600 if result['status']=='ok' else 90),result)
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:values=list(pool.map(work,PLATFORMS))
    return {'identity':identity,'kind':kind,'items':[v['item'] for v in values if v['item']],
            'providers':[{k:v[k] for k in ('provider','name','status')} for v in values],
            'checkedAt':datetime.now(timezone.utc).isoformat(),'retryAfter':int((time.time()+90)*1000)}

def known_ratings(identity,kind):
    kind='manga' if kind in {'manga','ranobe'} else 'anime';identity=str(identity)
    with _lock:values=[_cache[(p,identity,kind)][1] for p in PLATFORMS if (p,identity,kind) in _cache and _cache[(p,identity,kind)][0]>time.monotonic()]
    items=[v['item'] for v in values if v['item']]
    if not items:return None
    providers={v['provider']:{k:v[k] for k in ('provider','name','status')} for v in values}
    return {'identity':identity,'kind':kind,'items':items,'providers':[providers.get(p,{'provider':p,'name':name,'status':'unavailable'}) for p,name in PLATFORMS.items()],
            'checkedAt':min(v['checkedAt'] for v in items),'retryAfter':int((time.time()+90)*1000)}
