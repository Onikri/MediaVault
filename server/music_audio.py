"""Owner-created, short-lived audio capabilities. No open URL proxy or files."""
import asyncio,contextlib,json,os,re,shutil,subprocess,sys,tempfile,threading,time
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from fastapi import Depends,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field
from starlette.concurrency import run_in_threadpool
from source_parser import public_url,SourceError,playback_headers

slots=threading.BoundedSemaphore(2);lock=threading.RLock();cache={}
FIELDS='id,title,duration,url,http_headers,ext,acodec,vcodec,protocol,is_live,live_status,availability'

def youtube_id(value):
    if not isinstance(value,str) or len(value)>4096:raise SourceError('Нужна ссылка YouTube на одну запись.')
    try:
        parsed=urlsplit(value);host=parsed.hostname;port=parsed.port
    except ValueError:raise SourceError('Некорректная ссылка YouTube.') from None
    if parsed.scheme!='https' or parsed.username or parsed.password or port not in (None,443):raise SourceError('Нужна публичная HTTPS-ссылка YouTube.')
    if host=='youtu.be':identity=parsed.path.lstrip('/')
    elif host in {'youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'}:
        if parsed.path=='/watch':
            values=parse_qs(parsed.query).get('v',[]);identity=values[0] if len(values)==1 else ''
        else:
            match=re.fullmatch(r'/(?:shorts|embed)/([A-Za-z0-9_-]{11})/?',parsed.path);identity=match[1] if match else ''
    else:identity=''
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',identity):raise SourceError('Нужна ссылка YouTube на одну запись, а не плейлист или канал.')
    return identity

def audio_url(value):
    value=public_url(value);parsed=urlsplit(value)
    if not parsed.hostname.endswith('.googlevideo.com') or parsed.path!='/videoplayback':raise SourceError('Источник вернул неподдерживаемый аудиосервер.')
    return value

def failure(detail):
    lower=detail.lower()
    if 'not a bot' in lower or 'confirm you' in lower or 'sign in' in lower or '429' in lower:
        return 'YouTube требует проверку серверного IP Oracle. Можно открыть официальный плеер YouTube.'
    if 'private' in lower or 'members-only' in lower or 'unavailable' in lower or 'age' in lower:
        return 'Эта запись недоступна серверу без входа или имеет ограничения доступа.'
    return 'YouTube не предоставил доступную аудиодорожку. Можно повторить запрос или открыть официальный плеер.'

def extract(identity,refresh=False):
    now=time.monotonic()
    with lock:hit=cache.get(identity)
    if not refresh and hit and hit[0]>now:return hit[1],int(hit[0]-now)
    if not slots.acquire(False):raise HTTPException(429,'Подготовка музыки занята. Повтори через несколько секунд.')
    process=None
    try:
        root=Path(os.getenv('DATA_DIR','/data'))/'temporary';root.mkdir(parents=True,exist_ok=True)
        # No shell, config, cookies, credential forwarding, plugins or media
        # download. Files contain only bounded extractor metadata and disappear.
        with tempfile.TemporaryDirectory(dir=root,prefix='audio-resolve-') as directory,open(Path(directory)/'result','w+b') as output,open(Path(directory)/'error','w+b') as error:
            command=[sys.executable,'-m','yt_dlp','--ignore-config','--no-plugin-dirs','--no-cache-dir','--no-playlist','--no-warnings','--no-color','--socket-timeout','6','--retries','0','--extractor-retries','0','--js-runtimes','node','--skip-download','--print','%(.{'+FIELDS+'})j','-f','bestaudio[ext=m4a][protocol=https]/bestaudio[ext=webm][protocol=https]','--','https://www.youtube.com/watch?v='+identity]
            process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=output,stderr=error)
            end=time.monotonic()+28
            while process.poll() is None:
                if time.monotonic()>end or os.fstat(output.fileno()).st_size>4*1024**2 or os.fstat(error.fileno()).st_size>256*1024:
                    process.kill();process.wait();raise HTTPException(504,'YouTube не ответил за время подготовки. Повтори запрос.')
                time.sleep(.05)
            error.seek(0);diagnostic=error.read(256*1024).decode(errors='replace')
            if process.returncode:raise HTTPException(502,failure(diagnostic))
            output.seek(0)
            try:data=json.loads(output.read(4*1024**2))
            except ValueError:raise HTTPException(502,'Некорректный ответ обработчика аудио.') from None
        if data.get('id')!=identity or data.get('is_live') or data.get('live_status') in {'is_live','is_upcoming'} or data.get('vcodec')!='none' or data.get('ext') not in {'m4a','webm'} or data.get('protocol')!='https':raise HTTPException(422,'Нужна опубликованная запись с отдельной аудиодорожкой.')
        duration=data.get('duration')
        if not isinstance(duration,(int,float)) or not 0<duration<=7200:raise HTTPException(422,'Поддерживаются записи продолжительностью до двух часов.')
        url=audio_url(data.get('url',''));expiry=parse_qs(urlsplit(url).query).get('expire',[''])[0]
        ttl=min(600,int(expiry)-int(time.time())-60) if expiry.isdigit() else 300
        if ttl<30:raise HTTPException(502,'YouTube вернул истекающую ссылку. Повтори запрос.')
        value={'url':url,'headers':playback_headers(data.get('http_headers')),'mime':'audio/mp4' if data['ext']=='m4a' else 'audio/webm','duration':duration,'title':str(data.get('title') or 'YouTube')[:300]}
        with lock:
            if len(cache)>=64:cache.clear()
            cache[identity]=(time.monotonic()+ttl,value)
        return value,ttl
    finally:
        if process and process.poll() is None:process.kill();process.wait()
        slots.release()

class Play(BaseModel):
    model_config=ConfigDict(extra='forbid')
    url:str=Field(max_length=4096)
    refresh:bool=False

def install(app,owner):
    from online_sessions import create,sessions,lock as sessions_lock,watch_disconnect
    @app.post('/music/play')
    async def play(body:Play,request:Request,subject=Depends(owner)):
        identity=youtube_id(body.url);disconnected=asyncio.Event();watcher=asyncio.create_task(watch_disconnect(request,disconnected));token=None
        try:
            data,ttl=await run_in_threadpool(extract,identity,body.refresh)
            if disconnected.is_set():raise HTTPException(499,'Подготовка аудио отменена.')
            token,session=create(subject,data['headers'],'music');session.expires=time.monotonic()+ttl;session.audio_mime=data['mime']
            resource=session.resource(data['url'])
            return {'id':token,'streamUrl':'/online/'+token+'/'+resource,'mime':data['mime'],'duration':data['duration'],'title':data['title'],'expiresIn':ttl,'youtubeId':identity}
        except BaseException:
            if token:
                with sessions_lock:sessions.pop(token,None)
            raise
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):await watcher
