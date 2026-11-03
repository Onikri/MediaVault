"""Exact MAL/Shikimori character facts. Never infer family/status from an image."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
import re
import threading
import time
from urllib.parse import urljoin
from metadata_catalog import metadata,get_json
from source_parser import SourceError

cache=OrderedDict();pending={};lock=threading.RLock();slots=threading.BoundedSemaphore(4)
FIELDS=[('age','Возраст',r'Age|Возраст',False),('height','Рост',r'Height|Рост',False),
 ('birthday','День рождения',r'Birthday|Birth date|Date of birth|День рождения|Дата рождения',False),
 ('gender','Пол',r'Gender|Sex|Пол',False),('weight','Вес',r'Weight|Вес',False),
 ('mother','Мать',r'Mother|Мать|Мама',True),('father','Отец',r'Father|Отец|Папа',True),
 ('status','Статус',r'Status|Статус',True),
 ('debut','Первое появление',r'First appearance|Debut|First anime appearance|First manga appearance|Первое появление|Дебют',True)]
TRANSLATE={'male':'Мужской','female':'Женский','alive':'Жив','deceased':'Погиб','dead':'Погиб','unknown':'Не указан','unknown.':'Не указан'}


def plain(value):
    text=re.sub(r'<br\s*/?>','\n',str(value or ''),flags=re.I)
    return re.sub(r'<[^>]*>|\[/?[a-z][^\]]*\]','',text,flags=re.I).strip()


def build(identity,base,details):
    if base and str(base.get('id'))!=identity:raise SourceError('Каталог вернул другого персонажа.')
    if details and str(details.get('mal_id'))!=identity:raise SourceError('Каталог вернул другого персонажа.')
    attributes=[];seen=set()
    # Prefer published Russian character data; retain source attribution per field.
    for text,source,url in [(plain(base.get('description_html') or base.get('description')),'Шикимори','https://shikimori.io/characters/'+identity),(plain(details.get('about')),'MyAnimeList / Jikan',details.get('url') or 'https://myanimelist.net/character/'+identity)]:
        for key,label,pattern,spoiler in FIELDS:
            match=re.search(r'(?im)^\s*(?:'+pattern+r')\s*[:：]\s*([^\n\r]+)',text)
            if not match or key in seen:continue
            value=match[1].strip().strip('*')[:250]
            if value.casefold() in {'unknown','unknown.','n/a','none','неизвестно','не указан'}:continue
            attributes.append({'key':key,'label':label,'value':TRANSLATE.get(value.casefold(),value),'spoiler':spoiler,'source':source,'url':url});seen.add(key)
    appearances=[]
    for kind in ('anime','manga'):
        for row in details.get(kind) or []:
            work=row.get(kind) or {}
            if not work.get('mal_id'):continue
            appearances.append({'id':str(work['mal_id']),'kind':kind,'title':str(work.get('title') or '')[:250],
                'role':'Главный герой' if row.get('role')=='Main' else 'Персонаж','image':(work.get('images',{}).get('jpg') or {}).get('image_url','')})
    return {'id':identity,'name':base.get('russian') or base.get('name') or details.get('name') or '',
        'image':urljoin('https://shikimori.io',(base.get('image') or {}).get('original') or '') if (base.get('image') or {}).get('original') else ((details.get('images') or {}).get('jpg') or {}).get('image_url',''),
        'actors':[p.get('russian') or p.get('name') for p in base.get('seyu',[]) if p.get('russian') or p.get('name')],
        'nativeName':details.get('name_kanji') or '', 'aliases':(details.get('nicknames') or [])[:12],
        'description':plain(base.get('description_html') or base.get('description')),
        'attributes':attributes,'appearances':appearances[:100],
        'sources':[{'name':'Шикимори','url':'https://shikimori.io/characters/'+identity},{'name':'MyAnimeList','url':details.get('url') or 'https://myanimelist.net/character/'+identity}]}


def profile(identity):
    if not re.fullmatch(r'[1-9]\d{0,11}',identity):raise SourceError('Некорректный персонаж.')
    with lock:
        hit=cache.get(identity)
        if hit and hit[0]>time.monotonic():return hit[1]
        waiting=pending.get(identity);leader=waiting is None
        if leader:waiting=pending[identity]=threading.Event()
    if not leader:
        waiting.wait(20)
        with lock:hit=cache.get(identity)
        if hit:return hit[1]
        raise SourceError('Сведения о персонаже пока не ответили.')
    acquired=False
    try:
        acquired=slots.acquire(timeout=2)
        if not acquired:raise SourceError('Каталог загружает других персонажей. Повтори через несколько секунд.')
        def safe(fn):
            try:return fn()
            except SourceError:return {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(safe,lambda:metadata('shikimori',identity=identity,kind='character'))
            b=pool.submit(safe,lambda:(get_json('https://api.jikan.moe/v4/characters/'+identity+'/full').get('data') or {}))
            base,details=a.result(),b.result()
        if not base and not details:raise SourceError('Каталоги пока не предоставили сведения о персонаже.')
        result=build(identity,base,details)
        with lock:
            cache[identity]=(time.monotonic()+21600,result)
            while len(cache)>256:cache.popitem(last=False)
        return result
    finally:
        if acquired:slots.release()
        with lock:pending.pop(identity,None);waiting.set()


def install(app):
    @app.get('/metadata/character-profile/{identity}')
    def get(identity:str):return profile(identity)
