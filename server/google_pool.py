"""Owner-controlled Google credentials and a fixed, quota-paced Oracle gateway."""
import asyncio,hashlib,json,time,weakref
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
    slot:int=Field(default=0,ge=0,le=2)
    model:str
    request:dict

def install(app,owner,get_store):
    global _store
    _store=get_store
    from gemma_translate import Quotas
    quotas={}
    def quota(model):
        family='gemma' if model.startswith('gemma-') else 'gemini'
        if family not in quotas:quotas[family]=Quotas(Path(__import__('os').getenv('DATA_DIR','/data'))/'google-personal-quota.sqlite',minimum_interval=12 if family=='gemma' else 0)
        return quotas[family]
    locks=weakref.WeakValueDictionary();slots=asyncio.Semaphore(3)
    @app.get('/reader/google/keys')
    def status(subject=Depends(owner)):return safe_status(saved())
    @app.post('/reader/google/keys')
    async def configure(body:KeyPool,subject=Depends(owner)):
        if len({s.slot for s in body.slots})!=len(body.slots):raise HTTPException(422,'Повторяется номер ключа.')
        previous={r['slot']:r for r in saved()};rows=[]
        async with httpx.AsyncClient(timeout=15,follow_redirects=False) as client:
            for s in body.slots:
                key=s.key.get_secret_value().strip() if s.key is not None else previous.get(s.slot,{}).get('key','')
                if not key:continue
                if not 20<=len(key)<=512 or any(c.isspace() for c in key):raise HTTPException(422,'Проверь ключ '+str(s.slot+1)+'.')
                response=await client.get('https://generativelanguage.googleapis.com/v1beta/models',params={'pageSize':1000},headers={'x-goog-api-key':key})
                if response.status_code!=200:raise HTTPException(422,'Google не подтвердил ключ '+str(s.slot+1)+' · HTTP '+str(response.status_code))
                names={m.get('name','').removeprefix('models/') for m in response.json().get('models',[])}
                available=[m for m in MODELS if m in names]
                if not available:raise HTTPException(422,'Для ключа '+str(s.slot+1)+' нет поддерживаемых моделей.')
                rows.append({'slot':s.slot,'key':key,'project':s.project,'models':available})
        if len({r['key'] for r in rows})!=len(rows):raise HTTPException(422,'Один и тот же ключ добавлен несколько раз.')
        store=_store()
        if store is None:raise HTTPException(503,'Хранилище сервера не готово.')
        store.setting(SETTING,{'slots':rows,'updated':time.time()})
        return safe_status(rows)
    @app.post('/reader/google/generate')
    async def generate(body:Generate,connection:Request,subject=Depends(owner)):
        if body.model not in MODELS:raise HTTPException(422,'Выбери поддерживаемую модель Google.')
        row=next((r for r in saved() if r['slot']==body.slot),{})
        key=body.key.get_secret_value().strip() if body.key else row.get('key','')
        if not key:raise HTTPException(422,'Добавь ключ Google AI Studio.')
        # Unknown projects share one budget; adding keys never invents new quotas.
        group=hashlib.sha256((row.get('project') or 'shared-project').encode()).hexdigest()[:16] if not body.key else 'personal-shared'
        lock=locks.setdefault((subject,fingerprint(key)),asyncio.Lock())
        request=body.request
        if set(request)-{'systemInstruction','contents','generationConfig','safetySettings'} or not isinstance(request.get('contents'),list) or len(json.dumps(request))>18*1024*1024:raise HTTPException(422,'Некорректный запрос перевода.')
        model=body.model;url='https://generativelanguage.googleapis.com/v1beta/models/'+model
        async with slots,lock,httpx.AsyncClient(timeout=120,follow_redirects=False,headers={'x-goog-api-key':key}) as client:
            count=await client.post(url+':countTokens',json={'generateContentRequest':{'model':'models/'+model,**request}})
            if count.status_code!=200:raise HTTPException(count.status_code,'Google не смог подсчитать токены · HTTP '+str(count.status_code))
            try:tokens=int(count.json()['totalTokens'])+256;reservation=await quota(model).reserve(group+':'+model,tokens,lambda _:None)
            except (ValueError,KeyError):raise HTTPException(429,'Запрос превышает установленный бюджет Google.') from None
            if await connection.is_disconnected():raise HTTPException(499,'Запрос отменён до перевода.')
            response=await client.post(url+':generateContent',json=request)
            if response.status_code!=200:raise HTTPException(response.status_code,'Google · HTTP '+str(response.status_code)+'. Запрос не перенаправлялся на другой ключ.')
            result=response.json();quota(model).settle(reservation,result.get('usageMetadata',{}).get('promptTokenCount'))
            return result
