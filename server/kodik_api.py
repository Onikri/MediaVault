"""Owner-keyed Kodik catalogue; only fixed API hosts and published episode URLs.

No third-party tokens, CDN credentials, constructed episode links or API token
in the client response. The existing Kodik resolver still prepares actual video.
"""
import hashlib,json,os,re,threading,time,sqlite3
from urllib.parse import urlsplit
import requests
from fastapi import Depends,HTTPException
from pydantic import BaseModel,ConfigDict,SecretStr
from title_identity import aliases,match_title

API='https://kodik-api.com'
HOSTS={'kodik.info','kodik.biz','kodik.cc','kodikplayer.com','aniqit.com'}
_store=lambda:None
_cache={};_inspections={};_lock=threading.RLock()

def token():
    store=_store()
    try:saved=store.setting('configuration:kodik') if store else None
    except sqlite3.ProgrammingError:saved=None
    return (saved or {}).get('token') or os.getenv('KODIK_API_TOKEN','')

def call(method,key,parameters):
    if method not in {'search','list'}:raise ValueError('Unsupported Kodik endpoint')
    try:
        with requests.Session() as session:
            session.trust_env=False
            with session.post(API+'/'+method,data={'token':key,**parameters},headers={'Accept':'application/json','User-Agent':'MediaVault/5.6'},timeout=(3,6),allow_redirects=False,stream=True) as response:
                if response.status_code in {401,403}:raise ValueError('Kodik не принял ключ API.')
                if response.status_code==429:raise ValueError('Kodik ограничил частоту запросов. Повтори позже.')
                if response.status_code!=200:raise ValueError('Kodik временно недоступен.')
                raw=bytearray()
                for block in response.iter_content(65536):
                    raw.extend(block)
                    if len(raw)>4*1024*1024:raise ValueError('Слишком большой ответ Kodik.')
                value=json.loads(raw)
                if not isinstance(value,dict) or not isinstance(value.get('results'),list):raise ValueError('Kodik вернул неподдерживаемый ответ.')
                return value
    except (requests.RequestException,json.JSONDecodeError):raise ValueError('Не удалось подключиться к Kodik API.') from None

def player_url(value):
    if not isinstance(value,str):return ''
    if value.startswith('//'):value='https:'+value
    try:
        p=urlsplit(value)
        return value if p.scheme=='https' and p.hostname in HOSTS and not p.username and not p.password and p.port in {None,443} and len(value)<=2048 else ''
    except ValueError:return ''

def inspect_result(row,kind):
    url=player_url(row.get('link'));translation=row.get('translation') or {};name=' '.join(str(translation.get('title') or '').split())[:120]
    if not url or not name or re.match(r'^(неизвестн|unknown|серия\s*\d)',name,re.I):return None
    episodes=[];seasons=[]
    season_rows=row.get('seasons') or {}
    if not isinstance(season_rows,dict):return None
    for sn,part in season_rows.items():
        if not str(sn).isdigit() or not isinstance(part,dict):continue
        season=int(sn);season_url=player_url(part.get('link'))
        if season_url:seasons.append({'number':season,'url':season_url,'title':'Сезон '+str(season)})
        for en,value in (part.get('episodes') if isinstance(part.get('episodes'),dict) else {}).items():
            link=player_url(value.get('link') if isinstance(value,dict) else value)
            if str(en).isdigit() and link:
                episode={'number':int(en),'season':season,'url':link,'title':'Серия '+str(en)}
                if isinstance(value,dict):
                    shots=value.get('screenshots') or []
                    if shots and isinstance(shots[0],str) and shots[0].startswith('https://'):episode['thumbnail']=shots[0]
                episodes.append(episode)
    if not episodes and 'serial' not in str(row.get('type','')):episodes=[{'number':1,'season':1,'url':url,'title':row.get('title') or 'Фильм'}]
    if not episodes:return None
    episodes.sort(key=lambda e:(e['season'],e['number']))
    voice={'id':str(translation.get('id') or row.get('id','')),'name':name,'named':True,'kind':'subtitles' if translation.get('type')=='subtitles' else 'voice','language':'und','player':'Kodik','url':url,'episodes':episodes}
    material=row.get('material_data') or {}
    return {'url':url,'title':str(row.get('title') or '')[:300],'kind':kind,'provider':'kodik','providerName':'Kodik API','ids':{k:v for k,v in {'mal':str(row.get('shikimori_id') or ''),'imdb':row.get('imdb_id')}.items() if v},'year':row.get('year'),'dubs':[voice],'episodes':episodes,'seasons':seasons,'complete':True,'pending':False,'scannedPages':1,'screenshots':[u for u in material.get('screenshots',[]) if isinstance(u,str) and u.startswith('https://')][:8]}

def discover(selected):
    key=token()
    if not key:return {'provider':'kodik','name':'Kodik API','status':'not_configured','message':'Нужен личный токен Kodik в подключениях профиля.','sources':[],'complete':True}
    signature=hashlib.sha256((key+repr(selected)).encode()).hexdigest()
    with _lock:
        cached=_cache.get(signature)
        if cached and cached[0]>time.monotonic():return cached[1]
    kind=selected.get('kind','anime');ids=selected.get('ids') or {}
    params={'limit':100,'with_material_data':'true','with_seasons':'true','with_episodes':'true'}
    if ids.get('mal') and kind=='anime':params['shikimori_id']=ids['mal']
    elif ids.get('imdb'):params['imdb_id']=ids['imdb']
    else:params.update(title=(aliases(selected) or [''])[0],strict='true')
    try:
        sources=[]
        for row in call('search',key,params)['results'][:100]:
            actual_kind='anime' if str(row.get('type','')).startswith('anime') else 'tv' if 'serial' in str(row.get('type','')) else 'movie'
            candidate={'title':row.get('title'),'aliases':[row.get('title_orig'),row.get('other_title')],'kind':actual_kind,'year':row.get('year'),'ids':{'mal':str(row.get('shikimori_id') or ''),'imdb':row.get('imdb_id')}}
            if not match_title(selected,candidate)[0]:continue
            source=inspect_result(row,kind)
            if source:sources.append(source)
        value={'provider':'kodik','name':'Kodik API','status':'ok' if sources else 'no_match','message':'Данные каталога; доступность видео проверяется при запуске.','sources':sources,'complete':True}
        with _lock:
            if len(_cache)>=100:_cache.pop(next(iter(_cache)))
            _cache[signature]=(time.monotonic()+300,value)
            for source in sources:
                for url in [source['url'],*[s['url'] for s in source.get('seasons',[])]]:_inspections[url]=(time.monotonic()+600,source)
            for url,entry in list(_inspections.items()):
                if entry[0]<time.monotonic():_inspections.pop(url,None)
            while len(_inspections)>2048:_inspections.pop(next(iter(_inspections)))
        return value
    except ValueError as error:return {'provider':'kodik','name':'Kodik API','status':'unavailable','message':str(error),'sources':[],'complete':False}

def cached_inspection(url,season=None):
    with _lock:hit=_inspections.get(url)
    if not hit or hit[0]<time.monotonic():return None
    value=hit[1]
    if season is None:return value
    episodes=[e for e in value['episodes'] if e['season']==season]
    return {**value,'episodes':episodes,'dubs':[{**v,'episodes':episodes} for v in value['dubs']]} if episodes else None

def install(app,owner,store):
    global _store
    _store=store
    class Configuration(BaseModel):
        model_config=ConfigDict(extra='forbid')
        token:SecretStr
    @app.get('/integrations/kodik')
    def status(subject=Depends(owner)):
        return {'configured':bool(token()),'endpoint':API,'serverOnly':True}
    @app.put('/integrations/kodik')
    def configure(body:Configuration,subject=Depends(owner)):
        value=body.token.get_secret_value().strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,160}',value):raise HTTPException(422,'Некорректный токен Kodik.')
        try:call('list',value,{'limit':1})
        except ValueError as error:raise HTTPException(502,str(error)) from None
        store().setting('configuration:kodik',{'token':value,'verifiedAt':int(time.time())})
        with _lock:_cache.clear();_inspections.clear()
        return {'configured':True,'serverOnly':True,'verified':True}
    @app.delete('/integrations/kodik')
    def disconnect(subject=Depends(owner)):
        store().setting('configuration:kodik',{})
        with _lock:_cache.clear();_inspections.clear()
        return {'configured':bool(token())}
