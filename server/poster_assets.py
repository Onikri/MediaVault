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
    query='query { '+resource+'(ids: "'+','.join(ids)+'", limit: 30) { id russian name poster { originalUrl mainUrl } } }'
    data=get_json('https://shikimori.io/api/graphql',body={'query':query})
    result={}
    for item in (data.get('data') or {}).get(resource,[]) or []:
        if str(item.get('id')) not in ids:continue
        poster=item.get('poster') or {}
        image=next((poster.get(k) for k in ('originalUrl','mainUrl') if usable(poster.get(k))),None)
        if image:result[str(item['id'])]={'cover':image,'title':item.get('russian') or '', 'aliases':[item.get('name') or '']}
    if result:
        with _lock:
            if len(_cache)>128:_cache.clear()
            _cache[key]=(time.monotonic()+3600,result)
    return result
