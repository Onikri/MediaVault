"""On-demand public catalogue trailers for the native player; no iframe embeds."""
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field,ConfigDict
from metadata_catalog import metadata
from title_extras import trailers_from_details

jobs={};lock=threading.RLock();slots=threading.BoundedSemaphore(2)
MAX_BYTES=100*1024*1024

def prune(directory):
    for key in list(jobs):
        job=jobs[key]
        if job['updated']<time.time()-(90 if job['status']=='unavailable' else 3600) and job['status']!='preparing':
            if job.get('path'):Path(job['path']).unlink(missing_ok=True)
            jobs.pop(key)
    paths=sorted(directory.glob('*'),key=lambda p:p.stat().st_mtime)
    total=sum(p.stat().st_size for p in paths if p.is_file())
    for path in paths:
        if total<=256*1024*1024:break
        if path.is_file():total-=path.stat().st_size;path.unlink(missing_ok=True)

def prepare(anime_id,video_id,directory):
    details=metadata('shikimori',identity=anime_id,kind='anime')
    video=next((v for v in trailers_from_details(details) if v['id']==video_id),None)
    if not video:raise HTTPException(404,'Каталог больше не предоставляет этот трейлер.')
    with lock:
        directory.mkdir(parents=True,exist_ok=True);prune(directory)
        old=next((v for v in jobs.values() if v['anime']==anime_id and v['video']==video_id),None)
        if old and (old['status']!='ready' or Path(old.get('path','')).is_file()):return public(old)
        if not slots.acquire(blocking=False):raise HTTPException(429,'Сервер готовит другие трейлеры. Повтори через минуту.')
        token=secrets.token_urlsafe(24);jobs[token]={'id':token,'anime':anime_id,'video':video_id,'status':'preparing','updated':time.time()}
        thread=threading.Thread(target=download,args=(token,video['url'],directory),daemon=True,name='public-trailer');thread.start()
        return public(jobs[token])

def public(job):return {k:job[k] for k in ('id','status','message') if k in job}

def download(token,url,directory):
    target=directory/(token+'.%(ext)s')
    try:
        import playwright
        node=Path(playwright.__file__).parent/'driver'/'node'
        runtime=['--js-runtimes','node:'+str(node)] if node.is_file() else []
        result=subprocess.run([sys.executable,'-m','yt_dlp','--ignore-config','--no-playlist','--no-progress','--no-part','--quiet','--no-warnings',
            '--socket-timeout','12','--retries','1','--fragment-retries','1','--max-filesize','100M','--match-filter','duration <= 600 & !is_live',
            '-f','best[height<=720][ext=mp4][vcodec!=none][acodec!=none]/best[height<=720][vcodec!=none][acodec!=none]',
            '-o',str(target),*runtime,'--',url],capture_output=True,timeout=120,check=False)
        paths=[p for p in directory.glob(token+'.*') if p.suffix in {'.mp4','.webm','.mkv','.mov'}]
        if result.returncode or not paths or not 0<paths[0].stat().st_size<=MAX_BYTES:raise ValueError()
        path=paths[0]
        probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type','-of','json',str(path)],capture_output=True,timeout=10,check=False)
        data=json.loads(probe.stdout)
        if not any(s.get('codec_type')=='video' for s in data.get('streams',[])) or float(data.get('format',{}).get('duration',0))>600:raise ValueError()
        if path.suffix!='.mp4':
            mp4=directory/(token+'.mp4')
            remux=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(path),'-c','copy','-movflags','+faststart',str(mp4)],capture_output=True,timeout=45,check=False)
            if remux.returncode==0:path.unlink();path=mp4
        with lock:jobs[token].update({'status':'ready','path':str(path),'updated':time.time()})
    except Exception:
        for path in directory.glob(token+'.*'):path.unlink(missing_ok=True)
        with lock:jobs[token].update({'status':'unavailable','message':'Источник пока не отдаёт этот ролик. Попробуй другой трейлер или повтори позже.','updated':time.time()})
    finally:slots.release()

def install(app,data_dir):
    class Request(BaseModel):
        model_config=ConfigDict(extra='forbid')
        anime_id:str=Field(pattern=r'^\d{1,12}$')
        video_id:str=Field(pattern=r'^\d{1,12}$')
    @app.post('/trailers/prepare')
    def begin(body:Request):return prepare(body.anime_id,body.video_id,Path(data_dir)/'temporary-trailers')
    @app.get('/trailers/status/{token}')
    def status(token:str):
        with lock:job=jobs.get(token)
        if not job:raise HTTPException(404,'Подготовка трейлера истекла. Запусти ролик снова.')
        return public(job)
    @app.get('/trailers/stream/{token}')
    def stream(token:str):
        with lock:job=jobs.get(token)
        if not job or job['status']!='ready' or not Path(job.get('path','')).is_file():raise HTTPException(404,'Подготовь трейлер заново.')
        path=Path(job['path']);return FileResponse(path,media_type='video/webm' if path.suffix=='.webm' else 'video/mp4',headers={'Cache-Control':'private,max-age=900'})
