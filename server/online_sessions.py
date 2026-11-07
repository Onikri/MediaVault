"""Short-lived, owner-created playback capabilities. No Drive writes or open proxy."""
from dataclasses import dataclass,field
import asyncio,contextlib,os,re,secrets,threading,time
import m3u8
from urllib.parse import urljoin,urlsplit
from fastapi import Depends,HTTPException,Header,Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import Response,StreamingResponse
from pydantic import BaseModel,ConfigDict,Field
from source_parser import PublicHttp,Resolver,SourceAccessError,SourceError,is_alloha_player,public_url

@dataclass
class Session:
    owner:str
    headers:dict
    expires:float
    kind:str='video'
    client_id:str=''
    max_height:int|None=None
    audio_mime:str=''
    alloha:bool=False
    manifests:dict=field(default_factory=dict)
    resources:dict=field(default_factory=dict)
    reverse:dict=field(default_factory=dict)
    lock:object=field(default_factory=threading.RLock)
    slots:object=field(default_factory=lambda:threading.BoundedSemaphore(8))
    def resource(self,url,*,synthetic=False):
        url=public_url(url,resolve_dns=False)
        with self.lock:
            if not synthetic and url in self.reverse:return self.reverse[url]
            if len(self.resources)>=8000:raise SourceError('Слишком много частей в потоке.')
            token=secrets.token_urlsafe(12)
            self.resources[token]=url
            if not synthetic:self.reverse[url]=token
            return token

sessions={};lock=threading.RLock();preparations={}
LEASE_SECONDS=120

class AllohaPlaybackState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    time: float = Field(ge=0, le=604800, allow_inf_nan=False)
    paused: bool = Field(strict=True)
    rate: float = Field(default=1, ge=.25, le=4, allow_inf_nan=False)
    seeking: bool = Field(default=False, strict=True)
    buffering: bool = Field(default=False, strict=True)
    ended: bool = Field(default=False, strict=True)

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
    for key,value in list(preparations.items()):
        if value[1]<now:preparations.pop(key,None)
def create(owner,headers,kind='video',client_id='',reservation=None):
    with lock:
        expire()
        if client_id:
            if reservation is not None and preparations.get((owner,client_id),(None,))[0]!=reservation:raise HTTPException(409,'Открывается другая глава.')
            for key,s in list(sessions.items()):
                if s.owner==owner and s.client_id==client_id:sessions.pop(key,None)
        if kind!='preview':
            for key,value in list(sessions.items()):
                if value.owner==owner and value.kind=='preview':sessions.pop(key,None)
        if len(sessions)>=24 or sum(s.owner==owner for s in sessions.values())>=4:raise HTTPException(429,'Закрой предыдущий онлайн-просмотр и повтори.')
        token=secrets.token_urlsafe(32);session=Session(owner,headers,time.monotonic()+(LEASE_SECONDS if client_id else 7200),kind,client_id);sessions[token]=session;return token,session

def rewrite_manifest(text,base,link,max_height=None):
    if not text.lstrip().startswith('#EXTM3U'):raise SourceError('Источник не предоставил HLS.')
    for tag,attributes in re.findall(r'#EXT-X-(SESSION-KEY|KEY):([^\r\n]*)',text):
        # Plain AES-128 with a published key (HanimeTV) is ordinary HLS that the
        # player decrypts itself, as media_download already accepts. DRM systems,
        # SAMPLE-AES and session keys stay unsupported.
        method=(re.search(r'METHOD=([^,\s]+)',attributes) or [None,''])[1]
        keyformat=(re.search(r'KEYFORMAT="?([^",\s]*)',attributes) or [None,'identity'])[1]
        if method=='NONE':continue
        if tag!='KEY' or method!='AES-128' or keyformat!='identity' or 'URI="' not in attributes:
            raise SourceError('Зашифрованные и DRM-потоки в онлайн-режиме не поддерживаются.')
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
    referer:str|None=Field(default=None,max_length=8192)
    kind:str=Field(pattern='^(video|manga)$')
    quality:str=Field(default='best',pattern='^(best|[1-9][0-9]{1,3})$')
    purpose:str=Field(default='playback',pattern='^(playback|preview)$')
    refresh:bool=False
    client_id:str=Field(default='',alias='clientId',max_length=100,pattern=r'^[A-Za-z0-9:_-]*$')

_hls_option=[]
def hls_extension_option():
    if not _hls_option:
        import subprocess
        try:_hls_option.append('extension_picky' in subprocess.run(['ffmpeg','-hide_banner','-h','demuxer=hls'],capture_output=True,text=True,timeout=10).stdout)
        except (OSError,subprocess.SubprocessError):_hls_option.append(False)
    return _hls_option[0]

_ready={};_ready_lock=threading.Lock()
VIDEO_TYPES=('video/','audio/','application/octet-stream','binary/octet-stream','application/mp4')
# HanimeTV's CDN labels its AES-128 MPEG-TS segments text/html with a .html name.
DISGUISED_SEGMENT_HOSTS=('.htv-elidibus.com',)
def disguised_segment(url):
    host=urlsplit(url).hostname or ''
    return host.endswith(DISGUISED_SEGMENT_HOSTS) and urlsplit(url).path.endswith('.html')
def playable(text,base,headers,http,document,depth=0):
    """Readiness: before granting playback, follow the playlist (≤4 levels)
    to its first fragment and require real media bytes. A CDN that answers a
    segment with an HTML/empty page is a dead source, not a slow one."""
    playlist=m3u8.loads(text,uri=base)
    if playlist.playlists:
        if depth>=4:raise SourceError('Плейлист источника вложен слишком глубоко.')
        best=max(playlist.playlists,key=lambda v:((v.stream_info.resolution or (0,0))[1],v.stream_info.bandwidth or 0))
        child=urljoin(base,best.uri)
        with _ready_lock:
            if _ready.get(child,0)>time.monotonic():return
        inner,final,_=document(http,child,headers=headers)
        return playable(inner,final,headers,http,document,depth+1)
    first=next((urljoin(base,m.uri) for m in playlist.segment_map if m.uri),None) or (urljoin(base,playlist.segments[0].uri) if playlist.segments else None)
    if not first:raise SourceError('В плейлисте источника нет фрагментов видео.')
    key=base
    with _ready_lock:
        if _ready.get(key,0)>time.monotonic():return
    response,_=http._open(first,headers=headers,byte_range='bytes=0-2047')
    try:
        mime=response.headers.get('Content-Type','').split(';')[0].strip().lower()
        sample=next(response.iter_content(2048),b'')
    finally:response.close()
    if not sample or not disguised_segment(first) and (mime=='text/html' or sample.lstrip()[:1]==b'<' or mime and not mime.startswith(VIDEO_TYPES) and 'mp2t' not in mime):
        raise SourceError('Источник отдаёт страницу вместо видео. Выбери другой плеер или повтори позже.')
    with _ready_lock:
        if len(_ready)>512:_ready.clear()
        # Signed Alloha links live ~20 min; other sources are re-checked sooner.
        _ready[key]=time.monotonic()+(1200 if (urlsplit(first).hostname or '').endswith('.vkvideo.cloud') else 300)

def install(app,owner,exports_owner=None):
    from playback_resolver import PlaybackResolver
    resolver_cache=PlaybackResolver();app.state.playback_resolver=resolver_cache
    # Register before /online/{token}/{resource}, which otherwise captures
    # /online/exports/{id} as an ordinary playback capability.
    from local_exports import install as install_exports
    install_exports(app,exports_owner or owner)
    def resolve(body,subject,reservation=None):
        http=PublicHttp(timeout=(4,12),deadline=time.monotonic()+45)
        http.preview=body.purpose=='preview'
        http.refresh_playback=body.refresh
        token=None
        try:
            if body.kind=='manga':
                from manga_sources import inspect
                data=inspect(body.url,http)
                if not data['pages']:raise SourceError('Выбери конкретную опубликованную главу.')
                token,s=create(subject,{'Referer':data['url']},'manga',body.client_id,reservation)
                return {'id':token,'kind':'manga','language':data['language'],'pages':['/online/'+token+'/'+s.resource(url) for url in data['pages'][:1500]],'expiresIn':LEASE_SECONDS}
            started=time.monotonic()
            from media_download import pick_stream
            parent=public_url(body.referer,resolve_dns=False) if body.referer else None
            refresh=body.refresh
            for attempt in (0,1):
                http.refresh_playback=refresh
                page,source_cached=resolver_cache.page(subject,body.url,parent,lambda:Resolver(http).resolve(body.url,referer=parent) if parent else Resolver(http).resolve(body.url),refresh=refresh,preview=http.preview)
                resolved_at=time.monotonic()
                # Keep the HLS master: playback adapts while segments arrive. Do not
                # probe every variant or download/transcode an episode before play.
                masters=[v for v in page.streams if v.get('type')=='hls' and not v.get('quality')]
                stream=masters[0] if masters else pick_stream(page.streams,body.quality)
                max_height=None if body.quality=='best' else int(body.quality)
                manifest=None
                generated=False
                try:
                    # Check the first manifest now, before granting a playback capability.
                    if stream['type']=='hls':
                        from adaptive_playback import adaptive_master
                        text=adaptive_master(page.streams,http,max_height,document=lambda client,url,headers=None,refresh=refresh:resolver_cache.document(client,url,headers,refresh=refresh)) if not masters else None
                        generated=text is not None
                        if not generated:text,final,_=resolver_cache.document(http,stream['url'],headers=stream.get('headers'),refresh=refresh)
                        else:final=stream['url']
                        rewrite_manifest(text,final,lambda v:v,None if generated else max_height)
                        manifest=(text,final,float('inf') if generated else time.monotonic()+30)
                        playable(text,final,stream.get('headers'),http,lambda client,url,headers=None,refresh=refresh:resolver_cache.document(client,url,headers,refresh=refresh))
                    break
                except SourceAccessError:
                    # Long-cached Alloha URLs may have expired: renew them once.
                    # Freshly issued ones being refused puts the CDN on cooldown.
                    if not is_alloha_player(body.url):raise
                    from browser_player import rejected
                    if not rejected(body.url,parent) or attempt:raise
                    refresh=True
            token,s=create(subject,stream.get('headers') or {},kind='preview' if body.purpose=='preview' else 'video',client_id=body.client_id,reservation=reservation)
            s.max_height=None if generated else max_height
            # A generated master can include its base URL as a media playlist.
            # Give it a distinct resource so that variant never loops to the master.
            resource=s.resource(stream['url'],synthetic=generated)
            if manifest:s.manifests[resource]=manifest
            captions=[]
            for i,track in enumerate(getattr(page,'subtitles',[])):
                if str(track.get('url','')).split('?',1)[0].lower().endswith('.vtt'):
                    captions.append({'id':str(i),'name':str(track.get('name') or 'Субтитры')[:100],
                                     'language':str(track.get('language') or 'und')[:12],'url':'/online/'+token+'/'+s.resource(track['url'])})
            return {'id':token,'kind':'video','url':'/online/'+token+'/'+resource,'type':stream['type'],'subtitles':captions,
                    'sourceIntervals':getattr(page,'skip_segments',[]),'qualities':sorted({int(v['quality']) for v in page.streams if str(v.get('quality','')).isdigit()},reverse=True),
                    'expiresIn':LEASE_SECONDS,'preparationMs':round((time.monotonic()-started)*1000),'performance':{'resolveMs':round((resolved_at-started)*1000),'manifestMs':round((time.monotonic()-resolved_at)*1000),'sourceCached':source_cached}}
        except BaseException:
            if token:
                with lock:sessions.pop(token,None)
            raise
        finally:http.close()

    @app.post('/online/prepare')
    async def prepare(body:Prepare,request:Request,subject=Depends(owner)):
        # A hover preview can be cancelled while upstream parsing is still
        # running. Do not leave its newly created two-hour capability occupying
        # one of the owner's four slots after that browser has disconnected.
        reservation=secrets.token_urlsafe(16)
        if body.client_id:
            with lock:
                expire()
                if len(preparations)>=128 and (subject,body.client_id) not in preparations:raise HTTPException(429,'Слишком много подключений. Повтори через минуту.')
                if body.kind=='video' and body.purpose=='playback':
                    for key,value in list(preparations.items()):
                        if key[0]==subject and len(value)>2 and value[2]=='preview':preparations.pop(key,None)
                preparations[(subject,body.client_id)]=(reservation,time.monotonic()+60,body.purpose)
        disconnected=asyncio.Event();watcher=asyncio.create_task(watch_disconnect(request,disconnected))
        try:
            if body.kind == 'video' and is_alloha_player(body.url) and hasattr(app.state, 'alloha_delivery'):
                service = app.state.alloha_delivery
                data = await service.prepare_online(body, subject)
                if disconnected.is_set():
                    await service.close_session(service.session(data['id']))
                    raise HTTPException(499, 'Подготовка просмотра отменена.')
                # Keep the existing player/room/download capability shape. The
                # Alloha branch below delegates all actual I/O to its live browser.
                native = service.session(data['id'])
                with lock:
                    bridge = Session(subject, {}, native.expires, client_id=body.client_id, alloha=True)
                    bridge.resources['alloha-playback'] = body.url
                    sessions[data['id']] = bridge
                return data
            data=await run_in_threadpool(resolve,body,subject,reservation)
            if disconnected.is_set():
                with lock:
                    session=sessions.get(data['id'])
                    if session and session.owner==subject:sessions.pop(data['id'],None)
                raise HTTPException(499,'Подготовка просмотра отменена.')
            return data
        finally:
            if body.client_id:
                with lock:
                    if preparations.get((subject,body.client_id),(None,))[0]==reservation:preparations.pop((subject,body.client_id),None)
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):await watcher

    @app.delete('/online/{token}')
    async def close(token:str,subject=Depends(owner)):
        service = getattr(app.state, 'alloha_delivery', None)
        if service and token in service.sessions:
            await service.close_session(service.sessions[token])
            with lock:sessions.pop(token, None)
            return {'closed': True}
        with lock:
            s=sessions.get(token)
            if s and s.owner==subject:del sessions[token]
        return {'closed':True}

    @app.post('/online/{token}/heartbeat')
    def heartbeat(token:str,subject=Depends(owner)):
        service = getattr(app.state, 'alloha_delivery', None)
        with lock:
            expire();s=sessions.get(token)
            if not s or s.owner!=subject:raise HTTPException(410,'Онлайн-сеанс завершён. Открой главу снова.')
            if s.alloha:
                if not service or token not in service.sessions:
                    raise HTTPException(410,'Сессия Alloha завершена.')
                session=service.sessions[token]
                if session.closed or session.expires<=service.clock() or session.source.socket_closed:
                    raise HTTPException(410,'Сессия Alloha завершена.')
                return {'expiresIn': max(0, int(session.expires-service.clock()))}
            s.expires=time.monotonic()+LEASE_SECONDS
        return {'expiresIn':LEASE_SECONDS}

    @app.post('/online/{token}/playback')
    async def playback(token:str,body:AllohaPlaybackState,subject=Depends(owner)):
        with lock:
            session=sessions.get(token)
            if not session or session.owner!=subject or not session.alloha:
                raise HTTPException(404,'Сессия Alloha недоступна.')
        service=getattr(app.state,'alloha_delivery',None)
        if not service:raise HTTPException(410,'Сессия Alloha завершена.')
        return await service.report_playback(token,subject,body.model_dump())

    @app.get('/online/{token}/{resource}/download')
    def download(token:str,resource:str,height:int=0,name:str='video'):
        """Save the playing episode as one MP4: ffmpeg remuxes (-c copy, no
        re-encode) the chosen HLS quality read through this same capability
        proxy, so upstream headers and URL validation stay server-side."""
        import shutil,subprocess,urllib.parse
        with lock:
            expire();s=sessions.get(token);url=s.resources.get(resource) if s else None
        if not s or not url or s.kind!='video':raise HTTPException(410,'Онлайн-сеанс завершён. Открой серию снова.')
        if not shutil.which('ffmpeg'):raise HTTPException(503,'На сервере нет ffmpeg для сохранения видео.')
        if s.alloha:
            service = app.state.alloha_delivery
            native = service.session(token)
            quality = service.select_quality(native.translations[native.active]['qualities'], str(height)) if height else native.online_quality
            path = f'/play/{token}/{native.active}/{quality}.m3u8'
        else:
            target=url
            with s.lock:cached=s.manifests.get(resource)
            if cached:
                playlist=m3u8.loads(cached[0],uri=cached[1])
                if playlist.playlists:
                    variants=sorted(playlist.playlists,key=lambda v:(v.stream_info.resolution or (0,0))[1])
                    fitting=[v for v in variants if height and (v.stream_info.resolution or (0,0))[1]<=height]
                    target=urljoin(cached[1],(fitting or variants)[-1].uri)
            path='/online/'+token+'/'+(resource if target==url else s.resource(target))
        local='http://127.0.0.1:'+os.getenv('PORT','7860')+path
        safe=re.sub(r'[\\/:*?"<>|\x00-\x1f]+',' ',name).strip()[:120] or 'video'
        # Our proxy URLs have no file extension; patched ffmpeg builds reject
        # such HLS segments unless extension_picky is off (only our proxy is read).
        command=['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-protocol_whitelist','http,tcp,crypto,data,file',*(['-extension_picky','0'] if hls_extension_option() else []),'-i',local,
                 '-map','0:v:0','-map','0:a:0?','-c','copy','-f','mp4','-movflags','frag_keyframe+empty_moov+default_base_moof','pipe:1']
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        # Fail before the browser starts saving: never hand out an empty file.
        first=process.stdout.read(256*1024)
        if not first:
            process.wait()
            raise HTTPException(502,'Не удалось собрать видео для сохранения. Повтори позже или выбери другое качество.')
        def body():
            try:
                yield first
                while True:
                    block=process.stdout.read(256*1024)
                    if not block:break
                    yield block
            finally:
                if process.poll() is None:process.kill()
                process.wait()
        disposition="attachment; filename=video.mp4; filename*=UTF-8''"+urllib.parse.quote(safe+'.mp4')
        return StreamingResponse(body(),media_type='video/mp4',headers={'Content-Disposition':disposition,'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

    @app.get('/online/{token}/{resource}')
    def stream(token:str,resource:str,request:Request,range_header:str=Header(default='',alias='Range')):
        with lock:
            expire();s=sessions.get(token);url=s.resources.get(resource) if s else None
            if s and url and s.client_id:s.expires=time.monotonic()+LEASE_SECONDS
        if not s or not url:raise HTTPException(410,'Онлайн-сеанс завершён. Открой серию или главу снова.')
        if s.alloha:
            from anyio import from_thread
            service = app.state.alloha_delivery
            native = service.session(token)
            return from_thread.run(service.play, token, native.active, native.online_quality)
        if range_header and not re.fullmatch(r'bytes=(?:\d+-\d*|-\d+)',range_header):raise HTTPException(416,'Некорректный диапазон.')
        if not s.slots.acquire(blocking=False):raise HTTPException(429,'Дождись загрузки предыдущих частей.')
        if s.kind=='music':
            from music_audio import audio_url
            http=PublicHttp(validate=audio_url,timeout=(5,20))
        else:http=PublicHttp(timeout=(5,20))
        # The device-download remux reads this proxy from loopback: bulk pace.
        http.bulk=bool(request.client and request.client.host in {'127.0.0.1','::1'})
        response=None;handed=False
        try:
            with s.lock:cached=s.manifests.get(resource)
            if cached and cached[2]>time.monotonic():
                data=rewrite_manifest(cached[0],cached[1],lambda value:'/online/'+token+'/'+s.resource(value),s.max_height)
                return Response(data,media_type='application/vnd.apple.mpegurl',headers={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'})
            from suwayomi_bridge import parse_reference,page_image
            if s.kind=='manga' and parse_reference(url):
                raw,mime=page_image(url)
                return Response(raw,media_type=mime,headers={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'})
            from hentaichan_video import open_media, video_media
            if s.kind in {'video', 'preview'} and video_media(url):
                response,final=open_media(http,url,headers=s.headers,byte_range=range_header or None)
            else:
                response,final=http._open(url,headers=s.headers,byte_range=range_header or None)
            mime=response.headers.get('Content-Type','').split(';')[0].lower()
            common={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'}
            if s.kind=='music':
                if mime not in {'audio/mp4','audio/webm','video/mp4','video/webm','application/octet-stream'}:raise SourceError('YouTube вернул заглушку вместо аудио.')
                mime=s.audio_mime
            if s.kind=='music-file':
                if mime!=s.audio_mime:raise SourceError('Аудиоисточник сменил тип файла.')
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
            if s.kind in {'video','preview'} and disguised_segment(final) and mime=='text/html':mime='video/mp2t'
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
                        if total>(256*1024**2 if s.kind in {'music','music-file'} else 12*1024**3):break
                        yield block
                finally:active.close();http.close();s.slots.release()
            return StreamingResponse(blocks(),status_code=status,media_type=mime,headers=common)
        finally:
            if not handed:
                if response is not None:response.close()
                http.close();s.slots.release()

    app.state.online_stream=stream
