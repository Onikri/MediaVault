"""Bounded, source-only access to NovelCool's public application API.

Public client parameters come from a checksummed upstream adapter at install
time, never from an owner's Google account, browser, or desktop worker.
"""
import hashlib,json,os,re,time
from pathlib import Path
import requests
from source_parser import SourceError,public_url,USER_AGENT,MAX_DOCUMENT

UPSTREAM='https://raw.githubusercontent.com/keiyoushi/extensions-source/dbf6c05d6a9520c60533f1626616263522bbe71a/src/all/novelcool/src/eu/kanade/tachiyomi/extension/all/novelcool/NovelCool.kt'
UPSTREAM_SHA256='ace8b20acb9401e538d2f9a85753ff18bf2da283ae0ff55794891cd41190a0fa'
OPERATIONS={'book/search':{'keyword','page'},'book/info':{'book_id'},'chapter/book_list':{'book_id'},'chapter/info':{'chapter_id'}}

def settings_path():return Path(os.getenv('DATA_DIR','/data'))/'novelcool-public-client.json'

def validate_settings(data):
    if not isinstance(data,dict) or not re.fullmatch(r'\d{1,30}',str(data.get('appId',''))) or not re.fullmatch(r'[a-f0-9]{32}',data.get('secret','')):raise ValueError('Invalid public client parameters')
    return {'appId':str(data['appId']),'secret':data['secret'],'package_name':'com.zuoyou.novel','lang':'ru'}

def settings():
    try:return validate_settings(json.loads(settings_path().read_text(encoding='utf-8')))
    except (OSError,ValueError,TypeError):return None

def install():
    if settings():return
    path=settings_path()
    if not path.parent.is_dir():raise SourceError('Create the existing backend data directory first.')
    with requests.Session() as session:
        session.trust_env=False
        with session.get(UPSTREAM,timeout=(4,15),allow_redirects=False) as response:
            response.raise_for_status();raw=response.content
    if len(raw)>128*1024 or hashlib.sha256(raw).hexdigest()!=UPSTREAM_SHA256:raise SourceError('Upstream public client checksum mismatch.')
    text=raw.decode('utf-8');data={}
    for key,name in [('appId','APP_ID'),('secret','APP_SECRET')]:
        match=re.search(r'\bconst val '+name+r'\s*=\s*"([a-zA-Z0-9]+)"',text)
        if not match:raise SourceError('Upstream public client format changed.')
        data[key]=match[1]
    data=validate_settings(data);temporary=path.with_suffix('.tmp')
    descriptor=os.open(temporary,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
    with os.fdopen(descriptor,'w',encoding='utf-8') as out:json.dump(data,out)
    temporary.replace(path);path.chmod(0o600)

def request(operation,values,http):
    if operation not in OPERATIONS or set(values)!=OPERATIONS[operation]:raise SourceError('Unsupported NovelCool API operation.')
    for key,value in values.items():
        if key in {'book_id','chapter_id'} and not re.fullmatch(r'[1-9]\d{0,12}',str(value)):raise SourceError('Invalid NovelCool identifier.')
    if operation=='book/search' and (not isinstance(values['keyword'],str) or not 0<len(values['keyword'])<=200 or type(values['page']) is not int or not 1<=values['page']<=10):raise SourceError('Invalid NovelCool search.')
    client=settings()
    if not client:raise SourceError('Серверный API NovelCool ещё не настроен.')
    target=public_url('https://api.novelcool.com/'+operation+'/',allow_api=True)
    payload={**client,**values}
    if operation=='book/search':payload.update(lc_type='manga',page_size='100')
    end=getattr(http,'deadline',None)
    end=end if isinstance(end,(int,float)) else time.monotonic()+30
    remaining=end-time.monotonic()
    if remaining<=0:raise SourceError('NovelCool не уложился во время проверки.')
    try:
        with requests.Session() as session:
            session.trust_env=False
            with session.post(target,data=payload,headers={'User-Agent':USER_AGENT},timeout=(min(3,remaining),min(12,remaining)),allow_redirects=False,stream=True) as response:
                if response.status_code!=200:raise SourceError('API NovelCool вернул HTTP '+str(response.status_code)+'.')
                raw=bytearray()
                for block in response.iter_content(65536):
                    raw.extend(block)
                    if len(raw)>MAX_DOCUMENT or time.monotonic()>end:raise SourceError('Ответ API NovelCool превысил лимит.')
                data=json.loads(raw)
    except (requests.RequestException,ValueError):raise SourceError('Сервер не получил корректный ответ API NovelCool.') from None
    if not isinstance(data,dict) or data.get('error_code') not in ('success',0,'0'):raise SourceError('NovelCool отклонил публичный запрос.')
    return data

if __name__=='__main__':
    install();print('NovelCool public API client configured; no user credentials required.')
