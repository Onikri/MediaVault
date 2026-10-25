"""Short-lived, owner-created playback capabilities. No Drive writes or open proxy."""
from dataclasses import dataclass,field
import re,secrets,threading,time
from urllib.parse import urljoin,urlsplit
from fastapi import Depends,HTTPException,Header
from fastapi.responses import Response,StreamingResponse
from pydantic import BaseModel,ConfigDict,Field
from source_parser import PublicHttp,Resolver,SourceError,public_url

@dataclass
class Session:
    owner:str
    headers:dict
    expires:float
    kind:str='video'
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
def expire():
    now=time.monotonic()
    for key in list(sessions):
        if sessions[key].expires<now:del sessions[key]
def create(owner,headers,kind='video'):
    with lock:
        expire()
        if len(sessions)>=24 or sum(s.owner==owner for s in sessions.values())>=4:raise HTTPException(429,'Закрой предыдущий онлайн-просмотр и повтори.')
        token=secrets.token_urlsafe(32);session=Session(owner,headers,time.monotonic()+7200,kind);sessions[token]=session;return token,session

def rewrite_manifest(text,base,link):
    if not text.lstrip().startswith('#EXTM3U'):raise SourceError('Источник не предоставил HLS.')
    if re.search(r'#EXT-X-(?:SESSION-KEY|KEY):[^\n]*(?:METHOD=(?!NONE)[^,\s]+|KEYFORMAT=)',text):raise SourceError('Зашифрованные и DRM-потоки в онлайн-режиме не поддерживаются.')
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
    @app.post('/online/prepare')
    def prepare(body:Prepare,subject=Depends(owner)):
        http=PublicHttp(timeout=(4,12),deadline=time.monotonic()+45)
        try:
            if body.kind=='manga':
                from manga_sources import inspect
                data=inspect(body.url,http)
                if not data['pages']:raise SourceError('Выбери конкретную опубликованную главу.')
                token,s=create(subject,{'Referer':data['url']},'manga')
                return {'id':token,'kind':'manga','language':data['language'],'pages':['/online/'+token+'/'+s.resource(url) for url in data['pages'][:1500]],'expiresIn':7200}
            from media_download import pick_stream,expand_stream_qualities
            page=Resolver(http).resolve(body.url)
            stream=pick_stream(expand_stream_qualities(page.streams,http),body.quality)
            # Check the first manifest now, before granting a playback capability.
            if stream['type']=='hls':
                text,final,_=http.document(stream['url'],headers=stream.get('headers'));rewrite_manifest(text,final,lambda v:v)
            token,s=create(subject,stream.get('headers') or {})
            return {'id':token,'kind':'video','url':'/online/'+token+'/'+s.resource(stream['url']),'type':stream['type'],'expiresIn':7200}
        finally:http.close()

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
                data=rewrite_manifest(b''.join(parts).decode('utf-8'),final,lambda value:'/online/'+token+'/'+s.resource(value))
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
