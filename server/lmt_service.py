# SPDX-License-Identifier: AGPL-3.0-or-later
"""Private native LMT worker. Public routes require the existing owner session.
No Drive secrets, vault keys, catalog files or importer queues are mounted here.
"""
from __future__ import annotations
import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import time
from typing import Literal

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from PIL import Image
from lmt_runtime import LmtRuntime

VERSION = 5
MAX_IMAGE = 10 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 24_000_000

class Options(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: Literal['English','Japanese','Korean','Chinese (Simplified)'] = 'English'
    ocr: Literal['paddle','manga-ocr','ppocrv6-manga','ppocrv5-korean','pororo'] = 'paddle'
    detector: Literal['comic-bubble','comic-text-detector','yolo26n-manga','ppocrv6-det','magi'] = 'comic-bubble'
    panelDetector: Literal['none','yolo26n-manga','yolov12-panels'] = 'none'
    inpaint: Literal['quality','fast'] = 'quality'
    font: Literal['comic-relief','pangolin','neucha','system'] = 'comic-relief'
    translator: Literal['hymt2','index'] = 'hymt2'

class Body(BaseModel):
    model_config = ConfigDict(extra='forbid')
    image: str = Field(min_length=20, max_length=14*1024*1024)
    options: Options = Field(default_factory=Options)

class EncryptedCache:
    def __init__(self, directory, limit=512*1024*1024, ttl=7*86400):
        self.directory=Path(directory); self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        key=self.directory/'cache.key'
        try:
            fd=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError: pass
        else:
            with os.fdopen(fd,'wb') as out: out.write(AESGCM.generate_key(bit_length=256))
        self.cipher=AESGCM(key.read_bytes()); self.limit=limit; self.ttl=ttl
    def identity(self,subject,data,options):
        return hashlib.sha256(subject.encode()+b'\0'+data+b'\0'+json.dumps({'version':VERSION,**options},sort_keys=True).encode()).hexdigest()
    def read(self,key):
        p=self.directory/(key+'.cache')
        try:
            if time.time()-p.stat().st_mtime>self.ttl: p.unlink();return None
            raw=p.read_bytes();value=json.loads(self.cipher.decrypt(raw[:12],raw[12:],key.encode()));os.utime(p,None);return value
        except (OSError,ValueError): return None
        except Exception: return None  # corrupt/authentication-failed entries are recomputed
    def write(self,key,value):
        if not value.get('renderedImage') or value.get('warnings') or value.get('inpaint',{}).get('unpainted'): return
        iv=secrets.token_bytes(12);raw=iv+self.cipher.encrypt(iv,json.dumps(value,ensure_ascii=False).encode(),key.encode())
        p=self.directory/(key+'.cache');tmp=p.with_suffix('.part');tmp.write_bytes(raw);tmp.chmod(0o600);tmp.replace(p)
        files=sorted(self.directory.glob('*.cache'),key=lambda f:f.stat().st_mtime);total=sum(f.stat().st_size for f in files)
        for f in files:
            if total<=self.limit and time.time()-f.stat().st_mtime<=self.ttl:break
            total-=f.stat().st_size;f.unlink(missing_ok=True)

class Processor:
    def __init__(self, directory):
        root=Path(directory)
        self.runtime=LmtRuntime(os.getenv('LMT_ASSETS_DIR','/assets'),root/'lmt-browser')
        self.cache=EncryptedCache(root/'results');self.jobs={};self.queue=asyncio.Queue(maxsize=4);self.worker=None
    def status(self):
        s=self.runtime.status()
        return {**s,'version':VERSION,'modelLabel':'Hy-MT2 1.8B Q8 · LaMa Manga',
                'translators':['hymt2']+(['index'] if os.getenv('LMT_INDEX_MODEL') else []),
                'message': 'Полный LMT готов.' if s['ready'] else 'Модели полного LMT ещё не настроены на ВМ.',
                'cache':'encrypted','cacheLifetimeDays':7,'queued':sum(j['state']=='queued' for j in self.jobs.values()),
                'defaults':Options().model_dump()}
    def cleanup(self):
        for key,j in list(self.jobs.items()):
            if j['state'] in {'done','error','cancelled'} and time.monotonic()-j['updated']>600:self.jobs.pop(key)
    async def submit(self,data,options,subject):
        self.cleanup();key=self.cache.identity(subject,data,options)
        for job_id,j in self.jobs.items():
            if j['key']==key and j['subject']==subject and j['state'] in {'queued','running','done'}:return job_id
        if self.queue.full() or len(self.jobs)>=16:raise HTTPException(429,'Очередь перевода заполнена. Подожди текущую страницу.')
        job_id=secrets.token_urlsafe(24)
        hit=await asyncio.to_thread(self.cache.read,key)
        self.jobs[job_id]={'key':key,'subject':subject,'data':b'' if hit else data,'options':options,'updated':time.monotonic(),
            'state':'done' if hit else 'queued','status':'Готово · из кэша ВМ' if hit else 'В очереди на ВМ',**({'result':{**hit,'cacheHit':True}} if hit else {})}
        if not hit:
            self.queue.put_nowait(job_id)
            if not self.worker or self.worker.done():self.worker=asyncio.create_task(self.run())
        return job_id
    def get(self,job_id,subject):
        self.cleanup();j=self.jobs.get(job_id)
        if not j or j['subject']!=subject:raise HTTPException(404,'Задание перевода не найдено.')
        return j
    def cancel(self,j):
        j['data']=b'';j.pop('result',None);j.update(state='cancelled',status='Отменено',updated=time.monotonic())
        if j.get('task'):j['task'].cancel()
    async def run(self):
        while not self.queue.empty():
            job_id=await self.queue.get();j=self.jobs[job_id]
            try:
                if j['state']=='cancelled':continue
                j.update(state='running',status='Запускаем перевод на ВМ')
                def progress(s):j.update(status=s,updated=time.monotonic())
                config={**j['options'],'mode':'api','allowDownloads':True,'contextKey':j['key']}
                task=asyncio.create_task(self.runtime.run(j['data'],config,progress));j['task']=task
                result=await asyncio.wait_for(task,900)
                if j['state']=='cancelled':continue
                if not result.get('renderedImage'):raise ValueError(result.get('message','Готовая страница не получена. Проверь язык или OCR.'))
                await asyncio.to_thread(self.cache.write,j['key'],result)
                j.update(state='done',status='Готово · фон восстановлен, русский текст набран',result=result)
            except asyncio.CancelledError:j.update(state='cancelled',status='Отменено')
            except Exception as e:
                msg=str(e) if isinstance(e,ValueError) else 'Не удалось завершить перевод. Проверь состояние моделей на ВМ.'
                j.update(state='error',status=msg[:300])
            finally:
                j.pop('task',None);j['data']=b'';j['updated']=time.monotonic();self.queue.task_done()
    async def close(self):
        for j in self.jobs.values():self.cancel(j)
        if self.worker:await self.worker
        await self.runtime.close();self.jobs.clear()

async def owner(authorization: str = Header(default='')):
    if len(authorization)>4096 or not authorization.startswith('Bearer '):raise HTTPException(401,'Войди в профиль владельца.')
    # Verify against the running importer. Its queue is read only; no catalog,
    # signing key, Google tokens or account password is exposed to this worker.
    try:
        async with httpx.AsyncClient(trust_env=False,timeout=10) as client:
            response=await client.get(os.getenv('IMPORTER_AUTH_URL','http://importer:7860/jobs'),headers={'Authorization':authorization})
        if response.status_code!=200:raise ValueError()
        token=authorization[7:].split('.')[0];payload=json.loads(base64.urlsafe_b64decode(token+'='*(-len(token)%4)))
        subject=payload['sub']
        if not isinstance(subject,str) or not subject:raise ValueError()
        return subject
    except Exception:raise HTTPException(401,'Подключи профиль владельца к серверу заново.') from None

@asynccontextmanager
async def lifespan(app):
    app.state.processor=Processor(os.getenv('LMT_DATA_DIR','/data'))
    try:yield
    finally:await app.state.processor.close()
app=FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=[os.getenv('ALLOWED_ORIGIN','https://onikri.github.io')],allow_methods=['GET','POST'],allow_headers=['Authorization','Content-Type'])
@app.exception_handler(RequestValidationError)
async def invalid_request(request,error):
    return JSONResponse(status_code=422,content={'detail':'Проверь страницу и выбранные модели. Недопустимые параметры перевода.'})
@app.get('/reader/lmt/status')
async def status():
    value=app.state.processor.status()
    if value['ready']:
        try:
            url=os.environ['LMT_LLM_URL'].rstrip('/').removesuffix('/v1')+'/health'
            async with httpx.AsyncClient(timeout=2,trust_env=False) as client:
                r=await client.get(url)
            if not r.is_success:raise ValueError()
        except Exception:value.update(ready=False,message='Hy-MT2 запускается на ВМ. Подожди и повтори перевод.')
    return value
@app.post('/reader/lmt/jobs',status_code=202)
async def submit(body:Body,subject=Depends(owner)):
    p=app.state.processor
    if not p.status()['ready']:raise HTTPException(503,'Полный LMT ещё не настроен на ВМ.')
    try:
        data=base64.b64decode(body.image,validate=True)
        if len(data)>MAX_IMAGE:raise HTTPException(413,'Страница превышает 10 МБ.')
        def check():
            with Image.open(io.BytesIO(data)) as im:
                if im.width*im.height>24_000_000:raise ValueError()
                im.verify()
        await asyncio.to_thread(check)
    except HTTPException:raise
    except Exception:raise HTTPException(422,'Некорректная страница или более 24 Мп.') from None
    return {'id':await p.submit(data,body.options.model_dump(),subject)}
@app.get('/reader/lmt/jobs/{job_id}')
async def poll(job_id:str,subject=Depends(owner)):
    j=app.state.processor.get(job_id,subject)
    return {'state':j['state'],'status':j['status'],**({'result':j['result']} if j['state']=='done' else {})}
@app.post('/reader/lmt/jobs/{job_id}/cancel')
async def cancel(job_id:str,subject=Depends(owner)):
    p=app.state.processor;p.cancel(p.get(job_id,subject));return {'state':'cancelled'}
