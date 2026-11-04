"""The selected MangaBall chapter's own public reserve image server.

This is the image-proxy used by MangaBall's reader's 'server2' button. Neither
another scanlation, another provider, arbitrary client URL nor credentials can
select a target. The site's public JSON establishes work, language and page order.
"""
import json,re,threading,time
from urllib.parse import urlsplit,parse_qs,urlencode
from source_parser import PublicHttp,SourceError,public_url

_cache={};_lock=threading.RLock()

def page(client,saved,source,manga,chapter,index):
    match=re.fullmatch(r'/title-detail/([a-f0-9]{24})',urlsplit(saved.get('realUrl','')).path)
    if urlsplit(saved.get('realUrl','')).scheme!='https' or urlsplit(saved.get('realUrl','')).hostname!='mangaball.com' or not match:raise SourceError('Manga Ball не подтвердил исходный тайтл.')
    title_id=match[1]
    rows=client.get(f'/manga/{manga}/chapters',{'onlineFetch':'false'},timeout=6)
    row=next((r for r in rows if r.get('index')==chapter),None)
    chapter_id=str((row or {}).get('url',''))
    if not re.fullmatch(r'[a-f0-9]{24}',chapter_id):raise SourceError('Manga Ball не подтвердил исходную главу.')
    endpoint='https://mangaball.com/api/v1/chapter-detail?'+urlencode({'chapter_id':chapter_id})
    def api_only(url):
        if url!=endpoint:raise SourceError('Некорректный адрес читалки Manga Ball.')
        return public_url(url,allow_api=True)
    with _lock:hit=_cache.get(chapter_id)
    if hit and hit[0]>time.monotonic():data=hit[1]
    else:
        http=PublicHttp(validate=api_only,timeout=(3,8))
        try:
            text,_,_=http.document(endpoint);data=json.loads(text).get('data',{}).get('chapter',{})
        finally:http.close()
        with _lock:
            if len(_cache)>=128:_cache.pop(next(iter(_cache)))
            _cache[chapter_id]=(time.monotonic()+180,data)
    language={'jp':'ja','kr':'ko'}.get(data.get('lang') or data.get('language'),data.get('lang') or data.get('language'))
    if str(data.get('title_id'))!=title_id or str(data.get('id'))!=chapter_id or language!=source.get('lang'):raise SourceError('Manga Ball вернул другую главу или язык; подмена не допускается.')
    pages=data.get('pages',[])
    if not isinstance(pages,list) or not 0<=index<len(pages)<=500:raise SourceError('Страница отсутствует в исходной главе Manga Ball.')
    target=public_url(pages[index])
    endpoint='https://mangaball.com/api/v1/image-proxy?'+urlencode({'url':target})
    http=PublicHttp(validate=api_only,timeout=(3,15));response=None
    try:
        response,_=http._open(endpoint,headers={'Referer':'https://mangaball.com/chapter-detail/'+chapter_id});raw=bytearray()
        for block in response.iter_content(65536):
            raw.extend(block)
            if len(raw)>30*1024*1024:raise SourceError('Страница превышает допустимый размер.')
        from manga_download import image_extension
        extension=image_extension(raw[:32])
        if not extension:raise SourceError('Резервный сервер Manga Ball вернул заглушку вместо страницы.')
        return bytes(raw),'image/'+('jpeg' if extension=='jpg' else extension)
    except SourceError:raise SourceError('Manga Ball не отдаёт страницу через основной и резервный серверы изображений. Источник временно недоступен.') from None
    finally:
        if response is not None:response.close()
        http.close()
