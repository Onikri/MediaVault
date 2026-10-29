"""Single-process ARM64 FastAPI service. No public model/Drive credentials."""
from __future__ import annotations
import asyncio, base64, json, os, secrets, time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from .cache import JsonCache
from .source import ReadOnlySettings, SourceSessions
from .detector import DetectorService
from .provider import GemmaBatchTranslator
from .quota import QuotaPacer
from .orchestrator import RealtimeChapterOrchestrator, POLICY
from .contracts import MODEL_IDS

DATA=Path(os.getenv('MANGA_BATCH_DATA','/data'));KEY=DATA/'google-api-key'
settings=ReadOnlySettings(os.getenv('IMPORTER_READONLY_DATA','/importer'))
source=SourceSessions(settings)

@asynccontextmanager
async def lifespan(app):
    import redis.asyncio as redis
    connection=redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'),socket_connect_timeout=1,socket_timeout=1)
    cache=JsonCache(DATA,connection);detector=DetectorService(os.getenv('MANGA_DETECTOR','/models/rtdetr.onnx'))
    # A failed/missing model makes readiness false, not a silently different detector.
    try:await asyncio.to_thread(detector.warm);app.state.detector_ready=True
    except Exception:app.state.detector_ready=False
    pacer=QuotaPacer(tpm=int(os.getenv('GEMMA_TPM_BUDGET','13000')),rpm=int(os.getenv('GEMMA_RPM_BUDGET','14')),independent=os.getenv('GEMMA_INDEPENDENT_POOLS')=='1')
    from .pool import GooglePool
    provider=GooglePool(pacer,KEY,settings);app.state.engine=RealtimeChapterOrchestrator(source,detector,provider,cache)
    async def sweep():
        while True:
            await asyncio.sleep(60);await asyncio.to_thread(source.sweep)
    sweeper=asyncio.create_task(sweep())
    yield
    sweeper.cancel();await asyncio.gather(sweeper,return_exceptions=True)
    await app.state.engine.close();await cache.close();await connection.aclose()
    for id,s in list(source.sessions.items()):source.close(id,s['subject'])

app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
app.add_middleware(CORSMiddleware,allow_origins=[os.getenv('ALLOWED_ORIGIN','https://onikri.github.io')],allow_methods=['GET','POST','DELETE'],allow_headers=['Authorization','Content-Type'],allow_credentials=False)
@app.middleware('http')
async def bounds(request,call_next):
    if request.method in ('POST','PUT'):
        try:length=int(request.headers.get('content-length','0'))
        except ValueError:return JSONResponse({'detail':'Некорректный Content-Length.'},status_code=400)
        if length>512*1024:return JSONResponse({'detail':'Запрос превышает 512 КиБ.'},status_code=413)
    response=await call_next(request);response.headers['Cache-Control']='no-store, no-transform' if response.headers.get('content-type','').startswith('text/event-stream') else 'no-store';return response

def owner(authorization:str=Header(default='')):
    if not authorization.startswith('Bearer '):raise HTTPException(401,'Войди в профиль владельца ВМ.')
    try:return settings.owner(authorization[7:])
    except (PermissionError,OSError):raise HTTPException(401,'Сеанс ВМ истёк. Войди снова.')

class OpenChapter(BaseModel):
    model_config=ConfigDict(extra='forbid')
    library_id:str=Field(min_length=1,max_length=200)
    item_id:str=Field(min_length=1,max_length=200)
    vault_key:SecretStr
    names:list[str]=Field(min_length=1,max_length=1500)
    model:Literal[tuple(MODEL_IDS)]='gemini-3.5-flash-lite'
    direction:Literal['ltr','rtl']='rtl'
    currentPage:int=Field(default=1,ge=1,le=1500)
class Touch(BaseModel):currentPage:int=Field(ge=1,le=1500)
class GoogleKey(BaseModel):key:SecretStr

async def session(id,subject):
    try:return await asyncio.to_thread(source.get,id,subject)
    except KeyError:raise HTTPException(404,'Сеанс главы истёк. Открой главу заново.')
@app.get('/api/v1/manga-translation/status')
async def status(request:Request):
    engine=request.app.state.engine
    return {'ready':request.app.state.detector_ready and engine.translator.configured(),'configured':engine.translator.configured(),'detectorReady':request.app.state.detector_ready,'models':list(MODEL_IDS),'policy':POLICY,'maxPages':3,'maxBoxes':65,'prefetchPages':9,'serverInpaint':False,'progressVersion':1,'foregroundPages':3,'parallelBatches':3,'quota':engine.translator.pacer.snapshot(),'message':'Пакетный перевод Google · JSON → устройство' if engine.translator.configured() else 'Установи ключ Google AI Studio в настройках ВМ.'}
@app.post('/api/v1/manga-translation/key')
async def configure(body:GoogleKey,request:Request,subject=Depends(owner)):
    key=body.key.get_secret_value().strip()
    if not 20<=len(key)<=256 or any(c.isspace() for c in key):raise HTTPException(422,'Некорректный ключ Google AI Studio.')
    from google import genai
    from google.genai import types
    candidate=genai.Client(api_key=key,vertexai=False,http_options=types.HttpOptions(timeout=10000,retry_options=types.HttpRetryOptions(attempts=1)))
    async def available(model):
        try:await candidate.aio.models.get(model=model);return model
        except Exception:return None
    verified=[m for m in await asyncio.gather(*(available(m) for m in MODEL_IDS)) if m]
    if not verified:
        await candidate.aio.aclose()
        raise HTTPException(422,'Ключ не подтвердил доступ к бесплатным Gemma 4. Проверь проект Google AI Studio и ограничения ключа.')
    DATA.mkdir(exist_ok=True,parents=True,mode=0o700);tmp=DATA/('.key-'+secrets.token_hex(8))
    fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as out:out.write(key)
    os.replace(tmp,KEY);request.app.state.engine.translator.client=candidate;request.app.state.engine.translator.disabled=set(MODEL_IDS)-set(verified)
    return {'configured':True,'availableModels':verified}
@app.post('/api/v1/chapters')
async def open_chapter(body:OpenChapter,request:Request,subject=Depends(owner)):
    if not request.app.state.engine.translator.configured():raise HTTPException(409,'Сначала установи ключ Google AI Studio в настройках ВМ.')
    if not request.app.state.detector_ready:raise HTTPException(503,'Вес RT-DETR не установлен или не прошёл проверку SHA-256.')
    try:
        key=base64.b64decode(body.vault_key.get_secret_value(),validate=True)
        if len(key)!=32:raise ValueError('Некорректный ключ библиотеки.')
        id,s=await asyncio.to_thread(source.open,subject,body.library_id,body.item_id,key,body.names)
        s['direction']=body.direction;s['model']=body.model
        return {'id':id,'manifest':s['manifest'],'policy':POLICY,'pageCount':len(s['names'])}
    except ValueError as e:raise HTTPException(422,str(e))
@app.post('/api/v1/chapters/{id}/touch')
async def touch(id:str,body:Touch,request:Request,subject=Depends(owner)):
    s=await session(id,subject)
    if body.currentPage>len(s['names']):raise HTTPException(422,'Страницы нет в главе.')
    hits,jobs=await request.app.state.engine.window(s,body.currentPage)
    return {'cached':len(hits),'pending':len(jobs)}
@app.delete('/api/v1/chapters/{id}')
async def close(id:str,subject=Depends(owner)):
    # Jobs already shared with other readers can finish. Keys are removed when
    # the session expires; close is explicit when the reader is locked.
    await asyncio.to_thread(source.close,id,subject);return {'closed':True}

def event(kind,value):return 'event: '+kind+'\ndata: '+json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n\n'
@app.get('/api/v1/chapters/{id}/stream')
async def stream(id:str,request:Request,currentPage:int=1,subject=Depends(owner)):
    s=await session(id,subject)
    if not 1<=currentPage<=len(s['names']):raise HTTPException(422,'Страницы нет в главе.')
    async def events():
        yield event('ready',{'policy':POLICY,'currentPage':currentPage})
        engine=request.app.state.engine
        try:hits,jobs=await engine.window(s,currentPage)
        except Exception as error:
            yield event('page_error',{'page':currentPage,'message':str(error)[:500]})
            yield event('complete',{'currentPage':currentPage});return
        for hit in hits:yield event('page_translated',hit)
        pending={j['future']:j for j in jobs};versions={};last_heartbeat=time.monotonic()
        while pending:
            if await request.is_disconnected():return
            for job in pending.values():
                value=engine.snapshot(job)
                if versions.get(job['page'])!=value['revision']:
                    versions[job['page']]=value['revision'];yield event('progress',value)
            done,_=await asyncio.wait(pending,timeout=.75,return_when=asyncio.FIRST_COMPLETED)
            for f in done:
                job=pending.pop(f)
                try:yield event('page_translated',f.result())
                except Exception as error:yield event('page_error',{'page':job['page'],'message':str(error)[:500]})
            if time.monotonic()-last_heartbeat>=10:
                yield event('heartbeat',{'serverTimeMs':int(time.time()*1000)})
                last_heartbeat=time.monotonic()
        yield event('complete',{'currentPage':currentPage})
    return StreamingResponse(events(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no','Content-Encoding':'identity','Cache-Control':'no-store, no-transform','Connection':'keep-alive'})
