"""Short-lived, owner-created playback capabilities. No Drive writes or open proxy."""
from dataclasses import dataclass,field
import asyncio,contextlib,re,secrets,threading,time
import m3u8
from urllib.parse import urljoin,urlsplit
from fastapi import Depends,HTTPException,Header,Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import Response,StreamingResponse
from pydantic import BaseModel,ConfigDict,Field
from source_parser import PublicHttp,Resolver,SourceError,public_url

@dataclass
class Session:
    owner:str
    headers:dict
    expires:float
    kind:str='video'
    max_height:int|None=None
    manifests:dict=field(default_factory=dict)
    resources:dict=field(default_factory=dict)
    reverse:dict=field(default_factory=dict)
    lock:object=field(default_factory=threading.RLock)
    slots:object=field(default_factory=lambda:threading.BoundedSemaphore(8))
    def resource(self,url):
        url=public_url(url,resolve_dns=False)
        with self.lock:
            if url in self.reverse:return self.reverse[url]
            if len(self.resources)>=8000:raise SourceError('Слишком много частей в потоке.')
            token=secrets.token_urlsafe(12);self.resources[token]=url;self.reverse[url]=token;return token

sessions={};lock=threading.RLock()

async def watch_disconnect(request,event):
    # Unlike is_disconnected()'s nonblocking poll, an active receive task also
    # observes disconnects through Starlette's buffered-body middleware.
    while True:
        if (await request.receive())['type']=='http.disconnect':
            event.set();return
def expire():
    now=time.monotonic()
    for key in list(sessions):
        if sessions[key].expires<now:del sessions[key]
def create(owner,headers,kind='video'):
    with lock:
        expire()
        if len(sessions)>=24 or sum(s.owner==owner for s in sessions.values())>=4:raise HTTPException(429,'Закрой предыдущий онлайн-просмотр и повтори.')
        token=secrets.token_urlsafe(32);session=Session(owner,headers,time.monotonic()+7200,kind);sessions[token]=session;return token,session

def rewrite_manifest(text,base,link,max_height=None):
    if not text.lstrip().startswith('#EXTM3U'):raise SourceError('Источник не предоставил HLS.')
    if re.search(r'#EXT-X-(?:SESSION-KEY|KEY):[^\n]*(?:METHOD=(?!NONE)[^,\s]+|KEYFORMAT=)',text):raise SourceError('Зашифрованные и DRM-потоки в онлайн-режиме не поддерживаются.')
    if max_height is not None:
        playlist=m3u8.loads(text,uri=base)
        if playlist.playlists:
            variants=[v for v in playlist.playlists if v.stream_info.resolution and v.stream_info.resolution[1]<=max_height]
            if not variants:raise SourceError('В этом потоке нет качества в выбранных пределах.')
            playlist.playlists[:]=variants
            text=playlist.dumps()
    lines=[]
    for line in text.splitlines():
        if line.startswith('#'):
            line=re.sub(r'URI="([^"\r\n]+)"',lambda m:'URI="'+link(urljoin(base,m[1]))+'"',line)
        elif line.strip():line=link(urljoin(base,line.strip()))
        lines.append(line)
    return '\n'.join(lines)+'\n'

class Prepare(BaseModel):
    model_config=ConfigDict(extra='forbid')
    url:str=Field(max_length=8192)
    kind:str=Field(pattern='^(video|manga)$')
    quality:str=Field(default='best',pattern='^(best|[1-9][0-9]{1,3})$')

def install(app,owner):
    # Register before /online/{token}/{resource}, which otherwise captures
    # /online/exports/{id} as an ordinary playback capability.
    from local_exports import install as install_exports
    install_exports(app,owner)
    def resolve(body,subject):
        http=PublicHttp(timeout=(4,12),deadline=time.monotonic()+45)
        try:
            if body.kind=='manga':
                from manga_sources import inspect
                data=inspect(body.url,http)
                if not data['pages']:raise SourceError('Выбери конкретную опубликованную главу.')
                token,s=create(subject,{'Referer':data['url']},'manga')
                return {'id':token,'kind':'manga','language':data['language'],'pages':['/online/'+token+'/'+s.resource(url) for url in data['pages'][:1500]],'expiresIn':7200}
            started=time.monotonic()
            from media_download import pick_stream
            page=Resolver(http).resolve(body.url)
            # Keep the HLS master: playback adapts while segments arrive. Do not
            # probe every variant or download/transcode an episode before play.
            masters=[v for v in page.streams if v.get('type')=='hls' and not v.get('quality')]
            stream=masters[0] if masters else pick_stream(page.streams,body.quality)
            max_height=None if body.quality=='best' else int(body.quality)
            manifest=None
            # Check the first manifest now, before granting a playback capability.
            if stream['type']=='hls':
                text,final,_=http.document(stream['url'],headers=stream.get('headers'));rewrite_manifest(text,final,lambda v:v,max_height)
                manifest=(text,final,time.monotonic()+30)
            token,s=create(subject,stream.get('headers') or {})
            s.max_height=max_height
            resource=s.resource(stream['url'])
            if manifest:s.manifests[resource]=manifest
            return {'id':token,'kind':'video','url':'/online/'+token+'/'+resource,'type':stream['type'],'expiresIn':7200,'preparationMs':round((time.monotonic()-started)*1000)}
        finally:http.close()

    @app.post('/online/prepare')
    async def prepare(body:Prepare,request:Request,subject=Depends(owner)):
        # A hover preview can be cancelled while upstream parsing is still
        # running. Do not leave its newly created two-hour capability occupying
        # one of the owner's four slots after that browser has disconnected.
        disconnected=asyncio.Event();watcher=asyncio.create_task(watch_disconnect(request,disconnected))
        try:
            data=await run_in_threadpool(resolve,body,subject)
            if disconnected.is_set():
                with lock:
                    session=sessions.get(data['id'])
                    if session and session.owner==subject:sessions.pop(data['id'],None)
                raise HTTPException(499,'Подготовка просмотра отменена.')
            return data
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):await watcher

    @app.delete('/online/{token}')
    def close(token:str,subject=Depends(owner)):
        with lock:
            s=sessions.get(token)
            if s and s.owner==subject:del sessions[token]
        return {'closed':True}

    @app.get('/online/{token}/{resource}')
    def stream(token:str,resource:str,range_header:str=Header(default='',alias='Range')):
        with lock:
            expire();s=sessions.get(token);url=s.resources.get(resource) if s else None
        if not s or not url:raise HTTPException(410,'Онлайн-сеанс завершён. Открой серию или главу снова.')
        if range_header and not re.fullmatch(r'bytes=(?:\d+-\d*|-\d+)',range_header):raise HTTPException(416,'Некорректный диапазон.')
        if not s.slots.acquire(blocking=False):raise HTTPException(429,'Дождись загрузки предыдущих частей.')
        http=PublicHttp(timeout=(5,20));response=None;handed=False
        try:
            with s.lock:cached=s.manifests.pop(resource,None)
            if cached and cached[2]>time.monotonic():
                data=rewrite_manifest(cached[0],cached[1],lambda value:'/online/'+token+'/'+s.resource(value),s.max_height)
                return Response(data,media_type='application/vnd.apple.mpegurl',headers={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'})
            from suwayomi_bridge import parse_reference,page_image
            if s.kind=='manga' and parse_reference(url):
                raw,mime=page_image(url)
                return Response(raw,media_type=mime,headers={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'})
            if s.kind=='manga' and urlsplit(s.headers.get('Referer','')).hostname=='ru.novelcool.com':
                from source_relay import relay,image as device_image
                if relay.available():
                    raw,_,headers=device_image(url,s.headers['Referer'])
                    return Response(raw,media_type=headers['Content-Type'],headers={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'})
            response,final=http._open(url,headers=s.headers,byte_range=range_header or None)
            mime=response.headers.get('Content-Type','').split(';')[0].lower()
            common={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'}
            if s.kind=='manga':
                from manga_download import image_extension
                parts=[];size=0
                for block in response.iter_content(65536):
                    size+=len(block)
                    if size>30*1024*1024:raise SourceError('Страница слишком велика.')
                    parts.append(block)
                raw=b''.join(parts);extension=image_extension(raw[:32])
                if not extension:raise SourceError('Источник не предоставил изображение.')
                return Response(raw,media_type='image/'+('jpeg' if extension=='jpg' else extension),headers=common)
            is_hls='mpegurl' in mime or urlsplit(final).path.lower().endswith('.m3u8')
            if is_hls:
                parts=[];size=0
                for block in response.iter_content(65536):
                    size+=len(block)
                    if size>4*1024*1024:raise SourceError('Слишком большой плейлист.')
                    parts.append(block)
                data=rewrite_manifest(b''.join(parts).decode('utf-8'),final,lambda value:'/online/'+token+'/'+s.resource(value),s.max_height)
                return Response(data,media_type='application/vnd.apple.mpegurl',headers=common)
            allowed=mime.startswith(('video/','audio/','image/')) or mime in {'application/octet-stream','binary/octet-stream','text/vtt'}
            if not allowed:raise SourceError('Источник вернул неподдерживаемый файл.')
            for name in ('Content-Length','Content-Range','Accept-Ranges'):
                if name in response.headers:common[name]=response.headers[name]
            status=response.status_code;active=response;response=None;handed=True
            def blocks():
                try:
                    total=0
                    for block in active.iter_content(128*1024):
                        if token not in sessions or s.expires<time.monotonic():break
                        total+=len(block)
                        if total>12*1024**3:break
                        yield block
                finally:active.close();http.close();s.slots.release()
            return StreamingResponse(blocks(),status_code=status,media_type=mime,headers=common)
        finally:
            if not handed:
                if response is not None:response.close()
                http.close();s.slots.release()
