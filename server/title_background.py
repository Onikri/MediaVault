"""Native, muted catalogue video backgrounds, cached inside the checkout.

Only exact MAL catalogue matches may supply URLs. The browser never submits a URL.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.parse import urlsplit

import requests
from fastapi import HTTPException,Request
from fastapi.responses import FileResponse,StreamingResponse
from metadata_catalog import get_json, metadata
from title_extras import trailers_from_details
from trailer_service import slots, download as download_trailer, jobs as trailer_jobs, lock as trailer_lock

QUERY='''query($ids:[Int!]!){findAnimeByExternalSite(site:MAL,id:$ids){
 resources{nodes{site externalId}}
 animethemes{type animethemeentries{nsfw spoiler videos{nodes{link resolution size}}}}
}}'''
jobs={}
lock=threading.RLock()
MAX_BYTES=100*1024*1024
lookups=threading.BoundedSemaphore(4)
streams=threading.BoundedSemaphore(8)

def public_job(job):
    return {k:v for k,v in job.items() if k in {'status','source','message','url'}}


def candidates(identity):
    data=get_json('https://graphql.animethemes.moe/',body={'query':QUERY,'variables':{'ids':[int(identity)]}})
    videos=[]
    for anime in (data.get('data') or {}).get('findAnimeByExternalSite') or []:
        if not any(r.get('site')=='MAL' and str(r.get('externalId'))==identity for r in (anime.get('resources') or {}).get('nodes',[])):continue
        for theme in anime.get('animethemes',[]):
            for entry in theme.get('animethemeentries',[]):
                if entry.get('nsfw') or entry.get('spoiler'):continue
                for video in (entry.get('videos') or {}).get('nodes',[]):
                    url=str(video.get('link') or '')
                    if urlsplit(url).scheme!='https' or urlsplit(url).hostname!='v.animethemes.moe':continue
                    if not 0<int(video.get('size') or 0)<=MAX_BYTES:continue
                    videos.append((theme.get('type')!='OP',int(video.get('resolution') or 9999),url))
    return list(dict.fromkeys(v[2] for v in sorted(videos)))[:4]


def fetch_clip(url,target):
    with requests.get(url,stream=True,timeout=(10,15),allow_redirects=False) as response:
        response.raise_for_status()
        if int(response.headers.get('Content-Length') or 0)>MAX_BYTES:raise ValueError('Clip too large')
        size=0;deadline=time.monotonic()+50
        with target.open('wb') as output:
            for chunk in response.iter_content(256*1024):
                size+=len(chunk)
                if size>MAX_BYTES or time.monotonic()>deadline:raise ValueError('Clip limit')
                output.write(chunk)


def encode_clip(raw,partial):
    result=subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(raw),'-t','45','-an',
        '-vf','scale=w=1280:h=720:force_original_aspect_ratio=decrease:force_divisible_by=2,fps=24',
        '-c:v','libx264','-threads','2','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','-movflags','+faststart',str(partial)],capture_output=True,timeout=80)
    return result.returncode==0 and partial.is_file() and partial.stat().st_size>1000


def render(identity,directory):
    raw=directory/(identity+'.source')
    partial=directory/(identity+'.partial.mp4')
    acquired=False
    try:
        try:urls=candidates(identity)
        except Exception:urls=[]
        source='AnimeThemes'
        if urls:
            # The original WebM is playable while the optional MP4 cache builds.
            with lock:jobs[identity]={'status':'streaming','source':source,'url':'/backgrounds/'+identity+'/source','clips':urls,'clip':0,'updated':time.time()}
        acquired=slots.acquire(blocking=False)
        if not acquired:
            if urls:return
            raise ValueError('Encoding busy')
        ready=False
        for url in urls:
            try:
                fetch_clip(url,raw)
                if encode_clip(raw,partial):
                    ready=True;break
            except Exception:continue
        if not ready:
            # Some films have no OP/ED. Try their catalogue trailers, never an unrelated title.
            details=metadata('shikimori',identity=identity,kind='anime')
            for video in trailers_from_details(details)[:3]:
                token='background-'+identity
                with trailer_lock:trailer_jobs[token]={'status':'preparing','updated':time.time()}
                download_trailer(token,video['url'],directory,release_slot=False)
                with trailer_lock:job=trailer_jobs.pop(token,{})
                if job.get('status')=='ready':
                    downloaded=Path(job['path'])
                    try:ready=encode_clip(downloaded,partial)
                    finally:downloaded.unlink(missing_ok=True)
                    if ready:source='Проморолик';break
        if not ready:raise ValueError('No available same-title video')
        partial.replace(directory/(identity+'.mp4'))
        with lock:jobs[identity]={**jobs.get(identity,{}),'status':'ready','source':source,'updated':time.time()}
    except Exception:
        with lock:
            if jobs.get(identity,{}).get('status')!='streaming':jobs[identity]={'status':'unavailable','message':'Видео этого тайтла пока не удалось получить. Повтори загрузку фона.','updated':time.time()}
    finally:
        raw.unlink(missing_ok=True);partial.unlink(missing_ok=True)
        if acquired:slots.release()
        lookups.release()


def install(app,data_dir):
    directory=Path(os.environ.get('TITLE_VIDEO_CACHE_DIR',str(Path(__file__).resolve().parent/'.codex-local'/'backgrounds')))

    @app.get('/backgrounds/{identity}')
    def prepare(identity:str):
        if not re.fullmatch(r'[1-9]\d{0,8}',identity):raise HTTPException(422,'Нужен точный ID аниме.')
        with lock:
            directory.mkdir(parents=True,exist_ok=True)
            if (directory/(identity+'.mp4')).is_file():return {'status':'ready','source':jobs.get(identity,{}).get('source','Каталог'),'url':'/backgrounds/'+identity+'/video'}
            old=jobs.get(identity)
            if old and (old['status']=='preparing' or old['updated']>time.time()-300):return public_job(old)
            if not lookups.acquire(blocking=False):raise HTTPException(429,'Подготовка видео занята. Повторяем автоматически.')
            # Bound disk use; never remove clips being generated.
            paths=sorted((p for p in directory.glob('*.mp4') if p.stem.isdigit()),key=lambda p:p.stat().st_mtime)
            total=sum(p.stat().st_size for p in paths)
            for path in paths:
                if total<256*1024*1024:break
                total-=path.stat().st_size;path.unlink(missing_ok=True)
            jobs[identity]={'status':'preparing','updated':time.time()}
            threading.Thread(target=render,args=(identity,directory),daemon=True,name='title-video').start()
            return {'status':'preparing'}

    @app.get('/backgrounds/{identity}/source')
    def source(identity:str,request:Request):
        if not re.fullmatch(r'[1-9]\d{0,8}',identity):raise HTTPException(404)
        with lock:
            job=jobs.get(identity,{})
            clips=job.get('clips',[]);index=job.get('clip',0)
            url=clips[index] if index<len(clips) else ''
        if not url or urlsplit(url).scheme!='https' or urlsplit(url).hostname!='v.animethemes.moe':raise HTTPException(404,'Подготовь видеофон заново.')
        byte_range=request.headers.get('range','')
        if byte_range and not re.fullmatch(r'bytes=(?:\d+-\d*|-\d+)',byte_range):raise HTTPException(416)
        if not streams.acquire(blocking=False):raise HTTPException(429)
        response=None
        try:
            response=requests.get(url,headers={'Range':byte_range} if byte_range else {},stream=True,timeout=(4,15),allow_redirects=False)
            if response.status_code not in {200,206} or not response.headers.get('Content-Type','').split(';')[0].startswith('video/'):
                with lock:
                    if jobs.get(identity) is job:job['clip']=index+1
                raise HTTPException(502,'Источник видео временно не отвечает.')
            if int(response.headers.get('Content-Length') or 0)>MAX_BYTES:raise HTTPException(502)
            headers={k:response.headers[k] for k in ['Content-Length','Content-Range','Accept-Ranges'] if k in response.headers}
            headers['Cache-Control']='public,max-age=300'
            def chunks():
                total=0;deadline=time.monotonic()+180
                try:
                    for block in response.iter_content(64*1024):
                        total+=len(block)
                        if total>MAX_BYTES or time.monotonic()>deadline:break
                        yield block
                finally:response.close();streams.release()
            return StreamingResponse(chunks(),status_code=response.status_code,media_type=response.headers['Content-Type'],headers=headers)
        except requests.RequestException:
            if response is not None:response.close()
            streams.release();raise HTTPException(502,'Источник видео временно не отвечает.') from None
        except BaseException:
            if response is not None:response.close()
            streams.release();raise

    @app.get('/backgrounds/{identity}/video')
    def video(identity:str):
        if not re.fullmatch(r'[1-9]\d{0,8}',identity):raise HTTPException(404)
        path=directory/(identity+'.mp4')
        if not path.is_file():raise HTTPException(404,'Подготовь видеофон заново.')
        os.utime(path,None)
        return FileResponse(path,media_type='video/mp4',headers={'Cache-Control':'public,max-age=86400'})
