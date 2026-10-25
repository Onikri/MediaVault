"""Exact-ID Shikimori posters. Do not cache missing/error responses as valid artwork."""
import re
import threading
import time
from metadata_catalog import get_json

_cache={};_lock=threading.Lock()


def usable(url):
    return isinstance(url,str) and url.startswith('https://') and not re.search(r'(?:/|_)(?:missing|404|no[_-]?image|original/missing)(?:[./_-]|$)',url,re.I)


def posters(ids,kind='anime'):
    ids=list(dict.fromkeys(str(i) for i in ids if re.fullmatch(r'\d{1,12}',str(i))))[:30]
    if not ids:return {}
    key=(tuple(ids),kind)
    with _lock:
        cached=_cache.get(key)
        if cached and cached[0]>time.monotonic():return cached[1]
    resource='mangas' if kind in {'manga','ranobe'} else 'animes'
    query='query { '+resource+'(ids: "'+','.join(ids)+'", limit: 30) { id russian name genres { id name russian kind } poster { originalUrl mainUrl } } }'
    data=get_json('https://shikimori.io/api/graphql',body={'query':query})
    result={}
    for item in (data.get('data') or {}).get(resource,[]) or []:
        if str(item.get('id')) not in ids:continue
        poster=item.get('poster') or {}
        image=next((poster.get(k) for k in ('originalUrl','mainUrl') if usable(poster.get(k))),None)
        if image:result[str(item['id'])]={'cover':image,'title':item.get('russian') or '', 'aliases':[item.get('name') or ''],'genres':item.get('genres') or []}
    if result:
        with _lock:
            if len(_cache)>128:_cache.clear()
            _cache[key]=(time.monotonic()+(3600 if len(result)==len(ids) else 60),result)
    return result


def missing(url):
    return not url or bool(re.search(r'(?:/|_)(?:missing|404|no[_-]?image|no_poster)(?:[./_-]|$)',str(url),re.I))

def repair(value,kind,part=''):
    import copy
    value=copy.deepcopy(value)
    if kind=='character' or part=='roles':return value
    groups=[('anime','anime'),('manga','manga')] if part=='related' else [(None,kind)]
    for key,media in groups:
        items=[r[key] for r in value if r.get(key)] if key else value if isinstance(value,list) else [value]
        needed=[r for r in items if isinstance(r,dict) and r.get('id') and (missing(r.get('image',{}).get('original')) or not part and not r.get('genres'))]
        try:assets=posters([r['id'] for r in needed],media) if needed else {}
        except Exception:assets={}
        for item in needed:
            art=assets.get(str(item['id']),{})
            if art.get('cover'):item.setdefault('image',{})['original']=art['cover']
            if not item.get('genres') and art.get('genres'):item['genres']=art['genres']
    return value
