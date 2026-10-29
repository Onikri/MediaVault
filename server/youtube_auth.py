"""Owner-supplied YouTube sessions; encrypted at rest, never returned by API."""
import time
from fastapi import Depends,HTTPException
from pydantic import BaseModel,SecretStr

SETTING='music:youtube-session'
_store=lambda:None

def credentials():
    store=_store()
    return store.setting(SETTING) if store is not None else None

def cookie_text():
    value=credentials()
    return value.get('cookies','') if value else ''

def normalize_cookies(raw):
    if not isinstance(raw,str) or not 0<len(raw.encode())<=1024*1024:
        raise HTTPException(422,'Нужен cookies.txt размером до 1 МБ.')
    if not raw.lstrip('\ufeff').startswith('# Netscape HTTP Cookie File'):
        raise HTTPException(422,'Нужен экспорт YouTube в формате Netscape cookies.txt.')
    rows=[];names=set()
    for line in raw.splitlines():
        if line.startswith('#HttpOnly_'):line=line[len('#HttpOnly_'):]
        elif line.startswith('#') or not line.strip():continue
        parts=line.split('\t')
        if len(parts)!=7:raise HTTPException(422,'Некорректный формат cookies.txt.')
        domain,include,path,secure,expires,name,value=parts
        # Only YouTube session cookies are accepted. Other Google/website
        # credentials in an overbroad export are not stored or forwarded.
        if domain.lower() not in {'youtube.com','.youtube.com'}:continue
        if include not in {'TRUE','FALSE'} or secure not in {'TRUE','FALSE'} or not expires.isdigit() or not path.startswith('/') or not name or not value or any(ord(c)<32 for c in line if c!='\t'):
            raise HTTPException(422,'Некорректная запись сессии YouTube.')
        if int(expires) and int(expires)<=time.time():continue
        rows.append('\t'.join([domain.lower(),include,path,secure,expires,name,value]));names.add(name)
        if len(rows)>200:raise HTTPException(422,'Слишком много записей сессии YouTube.')
    if not names&{'SID','SAPISID','__Secure-1PSID','__Secure-3PSID'}:
        raise HTTPException(422,'В файле нет действующей авторизованной сессии YouTube. Войди на YouTube перед экспортом.')
    return '# Netscape HTTP Cookie File\n'+'\n'.join(rows)+'\n'

class CookieSession(BaseModel):
    cookies:SecretStr

def install(app,owner,get_store):
    global _store
    _store=get_store
    def invalidate(subject):
        import music_audio
        from online_sessions import sessions,lock as session_lock
        with music_audio.lock:music_audio.cache.clear();music_audio.auth_epoch+=1
        with session_lock:
            for key in list(sessions):
                if sessions[key].owner==subject and sessions[key].kind=='music':del sessions[key]

    @app.get('/music/youtube/session')
    def status(subject=Depends(owner)):
        value=credentials()
        return {'configured':bool(value),'updated':value.get('updated') if value else None}

    @app.put('/music/youtube/session')
    def connect(body:CookieSession,subject=Depends(owner)):
        canonical=normalize_cookies(body.cookies.get_secret_value());store=_store()
        if store is None:raise HTTPException(503,'Хранилище сервера ещё не готово.')
        updated=time.time();store.setting(SETTING,{'cookies':canonical,'updated':updated});invalidate(subject)
        return {'configured':True,'updated':updated}

    @app.delete('/music/youtube/session')
    def disconnect(subject=Depends(owner)):
        store=_store()
        if store is not None:store.consume(SETTING)
        invalidate(subject)
        return {'configured':False,'updated':None}
