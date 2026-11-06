"""Bounded public image fetcher, never an arbitrary URL or video proxy."""
from collections import OrderedDict
import threading
from urllib.parse import urlsplit
from source_parser import PublicHttp, SourceError, public_url
from manga_hitomi import DOMAIN as HITOMI_DOMAIN, ROOT as HITOMI_ROOT, THUMBNAIL_PATH

HOSTS={'img.youtube.com','i.ytimg.com','shikimori.io','desu.shikimori.io','shikimori.one','shikimori.me','shikimori.org','desu.shikimori.one','s4.anilist.co','cdn.myanimelist.net',
       'media.kitsu.io','media.kitsu.app','upload.wikimedia.org','commons.wikimedia.org','covers.openlibrary.org'}
cache,lock=OrderedDict(),threading.Lock()

def hitomi_cover(url):
    parts=urlsplit(url)
    return parts.hostname in {'atn.'+HITOMI_DOMAIN,'btn.'+HITOMI_DOMAIN} and not parts.query and bool(THUMBNAIL_PATH.fullmatch(parts.path))

def image_url(value):
    result=public_url(value)
    if urlsplit(result).hostname not in HOSTS and not hitomi_cover(result):raise SourceError('Изображения этого источника не поддерживаются.')
    return result

def fetch_image(url):
    image_url(url)
    with lock:
        if url in cache:cache.move_to_end(url);return cache[url]
    http=PublicHttp(validate=image_url,timeout=(4,7))
    response=None
    try:
        response,final=http._open(url,headers={'Referer':HITOMI_ROOT+'/'} if hitomi_cover(url) else None)
        mime=response.headers.get('Content-Type','').split(';')[0]
        if mime not in {'image/jpeg','image/png','image/webp','image/avif'}:raise SourceError('Источник не предоставил изображение.')
        parts=[];size=0
        for block in response.iter_content(65536):
            size+=len(block)
            if size>8*1024*1024:raise SourceError('Изображение слишком велико.')
            parts.append(block)
        data=b''.join(parts)
        if not data or not (data.startswith((b'\xff\xd8\xff',b'\x89PNG\r\n\x1a\n')) or data[:4]==b'RIFF' or b'ftypavif' in data[:32]):raise SourceError('Источник вернул неправильный файл изображения.')
        result=(data,mime)
        with lock:
            cache[url]=result
            while sum(len(v[0]) for v in cache.values())>64*1024*1024:cache.popitem(last=False)
        return result
    finally:
        if response is not None:response.close()
        http.close()
