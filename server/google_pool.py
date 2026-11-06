"""Owner-controlled Google credentials and a fixed, quota-paced Oracle gateway."""
import asyncio,hashlib,json,time
from pathlib import Path
import httpx
from fastapi import Depends,HTTPException,Request
from pydantic import BaseModel,Field,SecretStr,ConfigDict
MODELS=('gemini-3.5-flash-lite','gemma-4-26b-a4b-it','gemma-4-31b-it','gemini-3.1-flash-lite','gemini-2.5-flash-lite')
SETTING='reader:google-keys';_store=lambda:None

def saved():
    store=_store()
    value=store.setting(SETTING) if store else None
    if value is not None:return value.get('slots',[])
    from gemma_translate import key_path
    path=key_path()
    if path.is_file():return [{'slot':0,'key':path.read_text('utf-8-sig').strip(),'project':'','models':list(MODELS)}]
    return []
def fingerprint(key):return hashlib.sha256(key.encode()).hexdigest()[:16]
def safe_status(rows):return {'configured':bool(rows),'keyCount':len(rows),'slots':[{'slot':r['slot'],'configured':True,'project':r.get('project',''),'availableModels':r.get('models',[])} for r in rows],'maxParallel':min(3,len(rows))}
class KeySlot(BaseModel):
    model_config=ConfigDict(extra='forbid')
    slot:int=Field(ge=0,le=2)
    key:SecretStr|None=None
    project:str=Field(default='',max_length=100,pattern=r'^[A-Za-z0-9_.-]*$')
class KeyPool(BaseModel):
    slots:list[KeySlot]=Field(min_length=1,max_length=3)
class Generate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    key:SecretStr|None=None
    slot:int|None=Field(default=None,ge=0,le=2)
    model:str
    request:dict

def install(app,owner,get_store):
    global _store
    _store=get_store
    from google_gateway_limits import GoogleGatewayLimits,GatewayLimited
    from reader_network import ReaderNetwork
    from os import getenv
    limits=None;network=ReaderNetwork()
    def state():
        nonlocal limits
        if limits is None:
            directory=getattr(_store(),'directory',None) or getenv('DATA_DIR')
            if not directory:raise HTTPException(503,'Хранилище сервера не готово.')
            limits=GoogleGatewayLimits(Path(directory)/'google-gateway.sqlite')
        return limits
    def status_rows():
        rows=saved();result=safe_status(rows)
        for slot,row in zip(result['slots'],rows):slot['runtime']=state().snapshot(row)
        result['quotaNote']='Остаток RPM — оценка по запросам этой ВМ. Точная оставшаяся квота Google неизвестна; cooldown и ограничения получены из ответов API.'
        return result
    @app.get('/reader/google/diagnostics')
    async def diagnostics(subject=Depends(owner)):
        await network.observe_address()
        metadata=status_rows()
        return {**network.snapshot(subject),'keys':metadata['slots'],'quotaNote':metadata['quotaNote']}
    @app.get('/reader/google/keys')
    async def status(subject=Depends(owner)):return status_rows()
    @app.post('/reader/google/keys')
    async def configure(body:KeyPool,subject=Depends(owner)):
        if len({s.slot for s in body.slots})!=len(body.slots):raise HTTPException(422,'Повторяется номер ключа.')
        previous={r['slot']:r for r in saved()}
        async with httpx.AsyncClient(timeout=15,follow_redirects=False) as client:
            async def check(s):
                key=s.key.get_secret_value().strip() if s.key is not None else previous.get(s.slot,{}).get('key','')
                if not key:return None
                if not 20<=len(key)<=512 or any(c.isspace() for c in key):raise HTTPException(422,'Проверь ключ '+str(s.slot+1)+'.')
                response=await client.get('https://generativelanguage.googleapis.com/v1beta/models',params={'pageSize':1000},headers={'x-goog-api-key':key})
                if response.status_code!=200:raise HTTPException(422,'Google не подтвердил ключ '+str(s.slot+1)+' · HTTP '+str(response.status_code))
                names={m.get('name','').removeprefix('models/') for m in response.json().get('models',[])}
                available=[m for m in MODELS if m in names]
                if not available:raise HTTPException(422,'Для ключа '+str(s.slot+1)+' нет поддерживаемых моделей.')
                return {'slot':s.slot,'key':key,'project':s.project,'models':available}
            rows=[r for r in await asyncio.gather(*(check(s) for s in body.slots)) if r]
        if len({r['key'] for r in rows})!=len(rows):raise HTTPException(422,'Один и тот же ключ добавлен несколько раз.')
        store=_store()
        if store is None:raise HTTPException(503,'Хранилище сервера не готово.')
        store.setting(SETTING,{'slots':rows,'updated':time.time()})
        return status_rows()
    @app.post('/reader/google/generate')
    async def generate(body:Generate,connection:Request,subject=Depends(owner)):
        if body.model not in MODELS:raise HTTPException(422,'Выбери поддерживаемую модель Google.')
        request=body.request
        if set(request)-{'systemInstruction','contents','generationConfig','safetySettings'} or not isinstance(request.get('contents'),list) or len(json.dumps(request))>18*1024*1024:raise HTTPException(422,'Некорректный запрос перевода.')
        rows=saved();personal=body.key is not None
        if personal:
            key=body.key.get_secret_value().strip()
            if not key or len(key)>512 or any(c.isspace() for c in key):raise HTTPException(422,'Проверь личный ключ Google.')
            known=next((r for r in rows if r['key']==key),{})
            rows=[{'slot':None,'key':key,'project':known.get('project') or 'personal-shared'}]
        else:
            rows=[r for r in rows if body.model in r.get('models',MODELS)]
        if not rows:raise HTTPException(422,'Добавь серверный ключ Google для выбранной модели.')
        model=body.model;activity=network.begin(subject,body.slot,model,personal=personal);lease=None;response=None;status_code=0;usage=None
        try:
            lease=await state().acquire(rows,model,preferred=body.slot,on_wait=lambda seconds:network.update(activity,'quota',retry_after=seconds),disconnected=connection.is_disconnected)
            row,call=lease
            network.update(activity,'translating',slot=row.get('slot'))
            if await connection.is_disconnected():raise HTTPException(499,'Запрос отменён до перевода.')
            # Exactly the same request body as personal mode. No countTokens
            # round trip or unrelated Gemma TPM budget on Gemini vision calls.
            async with httpx.AsyncClient(timeout=120,follow_redirects=False,headers={'x-goog-api-key':row['key']}) as client:
                response=await client.post('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',json=request)
            status_code=response.status_code
            if status_code!=200:
                from google_gateway_limits import provider_limit
                delay,_=provider_limit(response,time.time())
                raise HTTPException(status_code,'Google · HTTP '+str(status_code)+((' · повтор через '+str(int(delay)+1)+' с') if delay else ''),headers={'Retry-After':str(int(delay)+1)} if delay else None)
            try:result=response.json()
            except ValueError:raise HTTPException(502,'Google вернул некорректный JSON.') from None
            usage=result.get('usageMetadata',{})
            result['mediavaultGateway']={'slot':row.get('slot'),'personal':personal,'maxParallel':3}
            network.update(activity,'done',status_code)
            return result
        except GatewayLimited as error:
            network.update(activity,'error',429,retry_after=error.seconds)
            raise HTTPException(429,'Все доступные ключи ожидают квоту Google · повтор через '+str(error.seconds)+' с',headers={'Retry-After':str(error.seconds)}) from None
        except HTTPException as error:
            status_code=error.status_code;network.update(activity,'error',status_code);raise
        except httpx.HTTPError:
            status_code=502;network.update(activity,'error',status_code)
            raise HTTPException(502,'Не удалось получить ответ Google. Готовые страницы сохранены.') from None
        except BaseException:
            status_code=499 if await connection.is_disconnected() else 500;network.update(activity,'cancelled' if status_code==499 else 'error',status_code);raise
        finally:
            if lease:state().finish(row,model,call,status_code,usage,response)
