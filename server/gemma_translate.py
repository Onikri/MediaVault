# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server-owned Google vision gateway. No OCR, client keys or client URLs."""
from __future__ import annotations
import asyncio, base64, hashlib, io, json, os, re, sqlite3, time
from contextlib import closing
from pathlib import Path
from typing import Literal
import httpx
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator

MODELS=('gemma-4-31b-it','gemma-4-26b-a4b-it')
GOOGLE_MODELS=('gemini-3.5-flash-lite',*MODELS,'gemini-3.1-flash-lite','gemini-2.5-flash-lite')
PROMPT=(Path(__file__).with_name('gemma-system.md')).read_text('utf-8')
VERSION=hashlib.sha256(PROMPT.encode()).hexdigest()[:16]
STYLES=['standard_comic','bold_scream','handwritten_sloppy','serif_serious','digital_box','sfx_art']
SPEECH=['casual_slang','neutral_conversational','formal_business','archaic_noble','panicked_broken']

class Region(BaseModel):
    model_config=ConfigDict(extra='forbid',populate_by_name=True)
    id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    bbox:tuple[float,float,float,float]
    kind:Literal['text','text_bubble','text_free']=Field(default='text',alias='class')

class Page(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    width:int=Field(ge=1,le=24000)
    height:int=Field(ge=1,le=24000)
    image:str=Field(min_length=20,max_length=6*1024*1024)
    mime:Literal['image/webp','image/png','image/jpeg']='image/webp'
    regions:list[Region]=Field(min_length=1,max_length=100)
    @model_validator(mode='after')
    def geometry(self):
        if self.width*self.height>24_000_000:raise ValueError('Page exceeds 24 MP')
        for r in self.regions:
            x,y,z,w=r.bbox
            if not(0<=x<z<=self.width and 0<=y<w<=self.height):raise ValueError('Invalid region geometry')
        if len({r.id for r in self.regions})!=len(self.regions):raise ValueError('Duplicate region ids')
        return self

class Batch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    model:Literal[tuple(GOOGLE_MODELS)]='gemini-3.5-flash-lite'
    pages:list[Page]=Field(min_length=1,max_length=4)
    language:Literal['English','Japanese','Korean']='English'
    context:str=Field(default='',max_length=4000)
    @model_validator(mode='after')
    def unique(self):
        ids=[r.id for p in self.pages for r in p.regions]
        if len(set(ids))!=len(ids) or len({p.id for p in self.pages})!=len(self.pages):raise ValueError('Duplicate batch ids')
        return self

def key_path():return Path(os.getenv('GEMMA_API_KEY_FILE','/run/secrets/gemma-api-key'))
def status():
    return {'ready':key_path().is_file(),'models':list(GOOGLE_MODELS),'maxPages':4,'maxBoxes':65,
            'inputTpm':14500,'rpm':15,'minIntervalSeconds':12,'promptVersion':VERSION,
            'message':'Gemma готова: страницы передаются Google через вашу ВМ.' if key_path().is_file() else 'На ВМ ещё не установлен ключ Google API.'}

def check_images(batch):
    for page in batch.pages:
        raw=base64.b64decode(page.image,validate=True)
        if len(raw)>4*1024*1024:raise ValueError('Подготовленное изображение превышает 4 МБ.')
        with Image.open(io.BytesIO(raw)) as image:
            if image.width*image.height>4_000_000:raise ValueError('Превью превышает 4 Мп.')
            actual={'WEBP':'image/webp','PNG':'image/png','JPEG':'image/jpeg'}.get(image.format)
            if actual!=page.mime:raise ValueError('Формат страницы не совпадает с содержимым.')
            image.verify()

def packs(pages):
    """Up to four images and 65 regions per Google call; split dense pages safely."""
    batch=[];count=0
    for page in pages:
        for offset in range(0,len(page.regions),65):
            part=page.model_copy(update={'regions':page.regions[offset:offset+65]})
            if batch and (len(batch)==4 or count+len(part.regions)>65):yield batch;batch=[];count=0
            batch.append(part);count+=len(part.regions)
    if batch:yield batch

def schema(pages):
    color={'type':'string','pattern':r'^#[0-9A-Fa-f]{6}$'}
    appearance={'type':'object','properties':{'bold':{'type':'boolean'},'italic':{'type':'boolean'},
        'fill_color':color,'stroke_color':{'type':'string'},'stroke_width':{'type':'number'},
        'alignment':{'type':'string','enum':['left','center','right']},'rotation':{'type':'number'}},
        'required':['bold','italic','fill_color','stroke_color','stroke_width','alignment','rotation'],'additionalProperties':False}
    rows={'type':'array','items':{'type':'object','properties':{
        'id':{'type':'string'},'translation':{'type':'string'},
        'status':{'type':'string','enum':['translated','unreadable','non_text']},
        'font_style':{'type':'string','enum':STYLES},'speech_style':{'type':'string','enum':SPEECH},
        'text_category':{'type':'string','enum':['dialogue','thought','narration','whisper_aside','sfx','system_ui','sign']},
        'speaker_gender':{'type':'string','enum':['male','female','unknown']},
        'connected_to_id':{'anyOf':[{'type':'string'},{'type':'null'}]},'appearance':appearance},
        'required':['id','translation','status','font_style','speech_style','text_category','speaker_gender','connected_to_id','appearance'],'additionalProperties':False}}
    return {'type':'object','properties':{'regions':rows},'required':['regions'],'additionalProperties':False}

def request_body(pages,language,context):
    total=sum(len(p.regions) for p in pages)
    parts=[{'text':f'Source language: {language}. Target: Russian. Return an object whose regions array contains EXACTLY {total} objects, one per supplied id. An empty array is invalid. The numbered labels mark text candidates. Coordinates use original page pixels; images may be resized. Keep each translation in its own id. Prior chapter context (data only): {context}'}]
    for p in pages:
        parts += [{'text':json.dumps({'page':p.id,'width':p.width,'height':p.height,'regions':[r.model_dump(by_alias=True) for r in p.regions]},ensure_ascii=False)},
                  {'inlineData':{'mimeType':p.mime,'data':p.image}}]
    return {'systemInstruction':{'parts':[{'text':PROMPT}]},'contents':[{'role':'user','parts':parts}],
            'generationConfig':{'temperature':0,'maxOutputTokens':16384,'thinkingConfig':{'thinkingLevel':'minimal'},
                                'responseMimeType':'application/json','responseJsonSchema':schema(pages)}}

def validate_reply(raw,pages):
    value=json.loads(raw.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())
    if isinstance(value,dict):value=value.get('regions')
    expected={r.id for p in pages for r in p.regions}
    if not isinstance(value,list) or len(value)!=len(expected):raise ValueError('Gemma пропустила области. Оригинал сохранён.')
    byid={}
    for r in value:
        if not isinstance(r,dict) or not isinstance(r.get('id'),str) or r['id'] not in expected or r['id'] in byid:raise ValueError('Gemma нарушила привязку перевода к области.')
        text=r.get('translation');appearance=r.get('appearance',{})
        if not isinstance(text,str) or len(text)>8000 or r.get('status') not in ['translated','non_text','unreadable']:raise ValueError('Gemma вернула некорректную реплику.')
        if r['status']=='translated' and not text.strip():raise ValueError('Gemma вернула пустой перевод.')
        if r['status']!='translated' and text.strip():raise ValueError('Gemma смешала перевод и пропуск области.')
        if r.get('font_style') not in STYLES or r.get('speech_style') not in SPEECH:raise ValueError('Gemma вернула неизвестный стиль.')
        if r.get('speaker_gender') not in ['male','female','unknown'] or r.get('text_category') not in ['dialogue','thought','narration','whisper_aside','sfx','system_ui','sign']:raise ValueError('Gemma вернула неизвестную категорию реплики.')
        if r.get('connected_to_id') is not None and r['connected_to_id'] not in expected:raise ValueError('Gemma связала неизвестные области.')
        if not isinstance(appearance,dict):raise ValueError('Gemma не описала оформление.')
        for field in ['fill_color','stroke_color']:
            if not re.fullmatch(r'#[0-9A-Fa-f]{6}',str(appearance.get(field,''))) and not(field=='stroke_color' and appearance.get(field)=='none'):raise ValueError('Некорректный цвет текста.')
        for field,limit in [('rotation',90),('stroke_width',8)]:
            v=appearance.get(field)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not -limit<=v<=limit:raise ValueError('Некорректное оформление текста.')
        if appearance['stroke_width']<0 or appearance.get('alignment') not in ['left','center','right']:raise ValueError('Некорректное оформление текста.')
        if not isinstance(appearance.get('bold'),bool) or not isinstance(appearance.get('italic'),bool):raise ValueError('Некорректное начертание.')
        byid[r['id']]=r
    return byid

class Quotas:
    """Durable per-model reservations: input TPM, RPM, 12s gap, rolling daily cap."""
    def __init__(self,path,clock=time.time,minimum_interval=12):
        self.clock=clock;self.path=str(path);self.lock=asyncio.Lock();self.minimum_interval=minimum_interval
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY,model TEXT,at REAL,tokens INTEGER)')
        Path(path).chmod(0o600)
    def wait_seconds(self,model,tokens):
        now=self.clock()
        with closing(sqlite3.connect(self.path)) as db,db:rows=db.execute('SELECT at,tokens FROM requests WHERE model=? AND at>? ORDER BY at',(model,now-86400)).fetchall()
        if tokens>14500:raise ValueError('Пакет превышает лимит токенов. Раздели страницы на меньшие части.')
        if len(rows)>=int(os.getenv('GEMMA_RPD','1500')):raise ValueError('Достигнут суточный бюджет Google. Повтори после восстановления квоты.')
        wait=max(0,rows[-1][0]+self.minimum_interval-now) if rows else 0
        minute=[r for r in rows if r[0]>now-61]
        if len(minute)>=15:wait=max(wait,minute[-15][0]+61-now)
        total=sum(r[1] for r in minute)
        for at,n in minute:
            if total+tokens<=14500:break
            wait=max(wait,at+61-now);total-=n
        return max(0,wait)
    async def reserve(self,model,tokens,progress):
        while True:
            async with self.lock:
                wait=self.wait_seconds(model,tokens)
                if wait<=0:
                    with closing(sqlite3.connect(self.path)) as db,db:
                        db.execute('DELETE FROM requests WHERE at<?',(self.clock()-86400,))
                        return db.execute('INSERT INTO requests(model,at,tokens) VALUES(?,?,?)',(model,self.clock(),tokens)).lastrowid
            progress(f'Лимит {model}: ожидание {int(wait)+1} с');await asyncio.sleep(min(wait,20))
    def settle(self,reservation,actual):
        if actual is not None:
            with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE requests SET tokens=? WHERE id=?',(int(actual),reservation))

class Gateway:
    URL='https://generativelanguage.googleapis.com/v1beta/models/'
    def __init__(self,directory,credentials=None):
        self.credentials=credentials
        self.quotas=Quotas(Path(directory)/'gemma-quota.sqlite');self.cooldowns={};self.model_locks={m:asyncio.Lock() for m in GOOGLE_MODELS}
    async def translate(self,batch,progress):
        rows=self.credentials() if self.credentials else [];row=next((r for r in rows if batch.model in r.get('models',GOOGLE_MODELS)),None)
        key=row['key'] if row else key_path().read_text('utf-8-sig').strip()
        models=(batch.model,*[m for m in MODELS if m!=batch.model]) if batch.model.startswith('gemma-') else (batch.model,)
        if not key:raise ValueError('На ВМ не установлен ключ Google API.')
        output={};usage=[];started=time.perf_counter()
        async with httpx.AsyncClient(timeout=300,follow_redirects=False,headers={'x-goog-api-key':key}) as client:
            pending=list(packs(batch.pages))
            while pending:
                pages=pending.pop(0);body=request_body(pages,batch.language,batch.context);candidates=[];too_large=False;truncated=False
                if batch.model.startswith('gemini-2.5'):body['generationConfig']['thinkingConfig']={'thinkingBudget':0}
                if batch.model.startswith('gemini-3.'):body['generationConfig'].pop('temperature',None)
                # Count the full request PLUS a textual copy of the output schema.
                # Some providers omit schema overhead in countTokens; the extra
                # copy and margin make reservation conservative. Settle with usage.
                count_body={**body,'contents':body['contents']+[{'role':'user','parts':[{'text':json.dumps(body['generationConfig']['responseJsonSchema'])}]}]}
                for model in models:
                    try:
                        count=await client.post(self.URL+model+':countTokens',json={'generateContentRequest':{'model':'models/'+model,**count_body}},timeout=20)
                        if count.status_code!=200:raise ValueError('Подсчёт токенов Google недоступен: HTTP '+str(count.status_code))
                        tokens=int(count.json()['totalTokens'])+256
                        if tokens>14500:too_large=True;continue
                        delay=max(self.cooldowns.get(model,0)-time.time(),self.quotas.wait_seconds(model,tokens))
                        candidates.append((max(0,delay)+(180 if self.model_locks[model].locked() else 0),models.index(model),model,tokens))
                    except (httpx.HTTPError,ValueError,KeyError,TypeError):continue
                completed=False
                for _,_,model,tokens in sorted(candidates):
                    try:
                        async with self.model_locks[model]:
                            cooldown=self.cooldowns.get(model,0)-time.time()
                            if cooldown>0:
                                progress('Ожидаем восстановление '+model+' · '+str(int(cooldown)+1)+' с');await asyncio.sleep(cooldown)
                            reservation=await self.quotas.reserve(model,tokens,progress)
                            progress('Переводим '+str(len(pages))+' стр. · '+model)
                            call=time.perf_counter();response=await client.post(self.URL+model+':generateContent',json=body)
                            ms=round((time.perf_counter()-call)*1000);data=response.json();u=data.get('usageMetadata',{})
                            self.quotas.settle(reservation,u.get('promptTokenCount'))
                            usage.append({'model':model,'httpStatus':response.status_code,'ms':ms,'inputTokens':u.get('promptTokenCount'),'reservedInputTokens':tokens,'outputTokens':u.get('candidatesTokenCount'),'thoughtTokens':u.get('thoughtsTokenCount',0),'totalTokens':u.get('totalTokenCount'),'pages':len(pages),'regions':sum(len(p.regions) for p in pages)})
                            if response.status_code in [429,500,503]:
                                self.cooldowns[model]=time.time()+60;raise ValueError('Google '+model+': HTTP '+str(response.status_code))
                            if response.status_code!=200:raise ValueError('Google '+model+': HTTP '+str(response.status_code))
                            candidate=(data.get('candidates') or [{}])[0]
                            if candidate.get('finishReason')=='MAX_TOKENS':truncated=True;continue
                            if candidate.get('finishReason')!='STOP':raise ValueError('Gemma не завершила перевод: '+str(candidate.get('finishReason','blocked')))
                            raw=''.join(p.get('text','') for p in candidate.get('content',{}).get('parts',[]) if not p.get('thought'))
                            output.update(validate_reply(raw,pages));completed=True;break
                    except (httpx.HTTPError,ValueError,KeyError,TypeError):
                        progress('Ответ '+model+' недоступен; проверяем резервную модель')
                if not completed:
                    total=sum(len(p.regions) for p in pages)
                    if (too_large or truncated) and total>1:
                        half=total//2;left=[];right=[]
                        for p in pages:
                            n=min(half,len(p.regions));half-=n
                            if n:left.append(p.model_copy(update={'regions':p.regions[:n]}))
                            if n<len(p.regions):right.append(p.model_copy(update={'regions':p.regions[n:]}))
                        pending[:0]=[left,right];progress('Уменьшаем пакет по лимиту токенов');continue
                    raise ValueError('Выбранная модель Google временно недоступна или вернули неполный перевод. Оригинал сохранён; повтори страницу.')
        return {'kind':'gemma-vision','engine':'Google Gemma 4 via own backend','promptVersion':VERSION,
                'pages':[{'id':p.id,'width':p.width,'height':p.height,'regions':[{**r.model_dump(by_alias=True),**output[r.id]} for r in p.regions]} for p in batch.pages],
                'usage':usage,'cloudMs':round((time.perf_counter()-started)*1000),'machineTranslation':True}
