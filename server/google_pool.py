"""Owner-controlled Google credentials and a fixed, quota-paced Oracle gateway."""
import asyncio,hashlib,json,time
from pathlib import Path
import httpx
from fastapi import Depends,HTTPException,Request
from pydantic import BaseModel,Field,SecretStr,ConfigDict
from typing import Literal
MODELS=('gemini-3.5-flash-lite','gemma-4-26b-a4b-it','gemma-4-31b-it','gemini-3.1-flash-lite','gemini-2.5-flash-lite')
# Models added after key slots were saved are allowed on every slot. (Owner rule: no non-Lite Flash.)
LATER_MODELS=()
SETTING='reader:google-keys';_store=lambda:None;_limits_state=None
API_ROOT='https://generativelanguage.googleapis.com/v1beta/models/'

class GoogleCallError(Exception):
    def __init__(self,status,message):
        super().__init__(message);self.status=status

async def server_generate(model,request,*,max_wait=120):
    """A server-side request (video chapters) through the same quota ledger as the gateway.

    Keys rotate by the ledger; 429 or 5xx moves the request to a key of another project, as the gateway does.
    """
    if _limits_state is None:raise GoogleCallError(503,'Хранилище сервера не готово.')
    rows=[r for r in saved() if model in r.get('models',MODELS) or model in LATER_MODELS]
    if not rows:raise GoogleCallError(422,'Нет серверного ключа Google для '+model+'.')
    from google_gateway_limits import estimate,project as key_project,GatewayLimited
    tokens=estimate(request,model);spare=list(rows)
    while True:
        try:row,call=await _limits_state().acquire(spare,model,tokens=tokens,max_wait=max_wait)
        except GatewayLimited as error:raise GoogleCallError(429,'Ключи ждут квоту Google '+str(error.seconds)+' с') from None
        response=None;status=0;usage=None
        try:
            async with httpx.AsyncClient(timeout=120,follow_redirects=False,headers={'x-goog-api-key':row['key']}) as client:
                response=await client.post(API_ROOT+model+':generateContent',json=request)
            status=response.status_code
            if status==200:
                try:data=response.json()
                except ValueError:status=502;data=None
                if data is not None:
                    usage=data.get('usageMetadata',{});return data
        except httpx.HTTPError:status=502
        finally:_limits_state().finish(row,model,call,status,usage,response)
        spare=[r for r in spare if key_project(r)!=key_project(row)]
        if (status==429 or status>=500) and spare:continue
        raise GoogleCallError(status,'Google · HTTP '+str(status))

def saved():
    store=_store()
    value=store.setting(SETTING) if store else None
    if value is not None:
        return [{**row,'subscription':row.get('subscription') or ('pro' if row['slot']<3 else 'free')}
                for row in value.get('slots',[])]
    from gemma_translate import key_path
    path=key_path()
    if path.is_file():return [{'slot':0,'key':path.read_text('utf-8-sig').strip(),'project':'','models':list(MODELS)}]
    return []
def fingerprint(key):return hashlib.sha256(key.encode()).hexdigest()[:16]
def safe_status(rows):return {'configured':bool(rows),'keyCount':len(rows),'slots':[{'slot':r['slot'],'configured':True,'project':r.get('project',''),'subscription':r.get('subscription','free'),'availableModels':r.get('models',[])} for r in rows],'maxParallel':min(6,len(rows))}
class KeySlot(BaseModel):
    model_config=ConfigDict(extra='forbid')
    slot:int=Field(ge=0,le=5)
    key:SecretStr|None=None
    project:str=Field(default='',max_length=100,pattern=r'^[A-Za-z0-9_.-]*$')
    subscription:Literal['pro','free']|None=None
class KeyPool(BaseModel):
    slots:list[KeySlot]=Field(min_length=1,max_length=6)
class Generate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    key:SecretStr|None=None
    slot:int|None=Field(default=None,ge=0,le=5)
    model:str
    request:dict
    # Personal mode: explicitly join the owner's pool. Server slots: treat the
    # requested slot as a preference and fail over inside this one gateway call.
    pool:bool=False

def install(app,owner,get_store,translator=None):
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
    global _limits_state
    _limits_state=state
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
    async def status(subject=Depends(translator or owner)):
        if str(subject).startswith('guest:'):
            raise HTTPException(403,'Настройки ключей доступны владельцу.')
        result=status_rows()
        if str(subject).startswith('share:'):
            result['slots']=[{k:v for k,v in row.items() if k in {'slot','configured','availableModels'}} for row in result['slots']]
        return result
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
                return {'slot':s.slot,'key':key,'project':s.project,'models':available,
                        'subscription':s.subscription or previous.get(s.slot,{}).get('subscription','free')}
            rows=[r for r in await asyncio.gather(*(check(s) for s in body.slots)) if r]
        if len({r['key'] for r in rows})!=len(rows):raise HTTPException(422,'Один и тот же ключ добавлен несколько раз.')
        store=_store()
        if store is None:raise HTTPException(503,'Хранилище сервера не готово.')
        store.setting(SETTING,{'slots':rows,'updated':time.time()})
        return status_rows()
    @app.post('/reader/google/generate')
    async def generate(body:Generate,connection:Request,subject=Depends(translator or owner)):
        if str(subject).startswith('guest:'):
            raise HTTPException(403,'Перевод серверными ключами доступен по ссылке владельца на тайтл.')
        if body.model not in MODELS:raise HTTPException(422,'Выбери поддерживаемую модель Google.')
        request=body.request
        if set(request)-{'systemInstruction','contents','generationConfig','safetySettings'} or not isinstance(request.get('contents'),list) or len(json.dumps(request))>18*1024*1024:raise HTTPException(422,'Некорректный запрос перевода.')
        rows=saved();personal=body.key is not None
        if personal:
            key=body.key.get_secret_value().strip()
            if not key or len(key)>512 or any(c.isspace() for c in key):raise HTTPException(422,'Проверь личный ключ Google.')
            known=next((r for r in rows if r['key']==key),{})
            mine={'slot':known.get('slot'),'key':key,'project':known.get('project') or 'personal-shared'}
            rows=[mine]+([r for r in rows if r['key']!=key and (body.model in r.get('models',MODELS) or body.model in LATER_MODELS)] if body.pool and body.slot is None else [])
        else:
            rows=[r for r in rows if body.model in r.get('models',MODELS) or body.model in LATER_MODELS]
        if not rows:raise HTTPException(422,'Добавь серверный ключ Google для выбранной модели.')
        model=body.model;activity=network.begin(subject,body.slot,model,personal=personal);lease=None;response=None;status_code=0;usage=None
        # Pool-aware manga clients delegate retries here, so another project can
        # proceed immediately while the failed project keeps its own cooldown.
        from google_gateway_limits import identity as key_identity,project as key_project
        spare=[] if (body.slot is not None and not body.pool) or (personal and not body.pool) else list(rows)
        from google_gateway_limits import estimate
        tokens=estimate(request,model)
        try:
            while True:
                lease=await state().acquire(spare or rows,model,preferred=body.slot,tokens=tokens,on_wait=lambda seconds:network.update(activity,'quota',retry_after=seconds),disconnected=connection.is_disconnected)
                row,call=lease
                network.update(activity,'translating',slot=row.get('slot'))
                if await connection.is_disconnected():raise HTTPException(499,'Запрос отменён до перевода.')
                # Exactly the same request body as personal mode. No countTokens
                # round trip: the TPM budget uses the size estimate of the body.
                async with httpx.AsyncClient(timeout=120,follow_redirects=False,headers={'x-goog-api-key':row['key']}) as client:
                    response=await client.post('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',json=request)
                status_code=response.status_code
                # 429 (quota) or 5xx (overloaded) moves to another key once.
                if (status_code==429 or status_code>=500) and spare:
                    state().finish(row,model,call,status_code,None,response);lease=None
                    spare=[r for r in spare if key_identity(r['key'])!=key_identity(row['key']) and key_project(r)!=key_project(row)]
                    if spare:
                        network.update(activity,'quota');continue
                break
            if status_code!=200:
                from google_gateway_limits import provider_limit
                delay,_=provider_limit(response,time.time())
                raise HTTPException(status_code,'Google · HTTP '+str(status_code)+((' · повтор через '+str(int(delay)+1)+' с') if delay else ''),headers={'Retry-After':str(int(delay)+1)} if delay else None)
            try:result=response.json()
            except ValueError:raise HTTPException(502,'Google вернул некорректный JSON.') from None
            usage=result.get('usageMetadata',{})
            result['mediavaultGateway']={'slot':row.get('slot'),'personal':personal,'maxParallel':min(6,len(rows))}
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
