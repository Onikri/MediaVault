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

JUNK=__import__('re').compile(r'^(?:ST-[A-Za-z0-9_-]+|_ga.*|_gid|_gcl_.*|_gat.*|__utm.*)$')

def json_cookies(raw):
    """EditThisCookie / Cookie-Editor JSON export -> Netscape cookies.txt text."""
    import json
    try:items=json.loads(raw)
    except ValueError:raise HTTPException(422,'Не удалось прочитать JSON-экспорт cookies.') from None
    if isinstance(items,dict):items=items.get('cookies') or []
    if not isinstance(items,list):raise HTTPException(422,'Нужен список cookies из расширения браузера.')
    rows=['# Netscape HTTP Cookie File']
    for item in items[:2000]:
        if not isinstance(item,dict):continue
        domain=str(item.get('domain') or item.get('host') or '').strip()
        name,value=str(item.get('name') or ''),str(item.get('value') or '')
        if not domain or not name:continue
        host_only=bool(item.get('hostOnly')) and not domain.startswith('.')
        expires=item.get('expirationDate',item.get('expires',item.get('expiry',0)))
        try:expires=0 if item.get('session') else max(0,int(float(expires or 0)))
        except (TypeError,ValueError):expires=0
        rows.append('\t'.join([domain,'FALSE' if host_only else 'TRUE',str(item.get('path') or '/'),'TRUE' if item.get('secure') else 'FALSE',str(expires),name,value]))
    return '\n'.join(rows)+'\n'

def normalize_cookies(raw):
    if not isinstance(raw,str) or not 0<len(raw.encode())<=1024*1024:
        raise HTTPException(422,'Нужен cookies.txt размером до 1 МБ.')
    if raw.lstrip('\ufeff \r\n\t')[:1] in '[{':
        raw=json_cookies(raw.lstrip('\ufeff'))
    if not raw.lstrip('\ufeff').startswith('# Netscape HTTP Cookie File'):
        raise HTTPException(422,'Нужен экспорт cookies YouTube: файл cookies.txt (Netscape) или JSON из расширения EditThisCookie / Cookie-Editor.')
    rows=[];names=set()
    for line in raw.splitlines():
        if line.startswith('#HttpOnly_'):line=line[len('#HttpOnly_'):]
        elif line.startswith('#') or not line.strip():continue
        parts=line.split('\t')
        if len(parts)!=7:raise HTTPException(422,'Некорректный формат cookies.txt.')
        domain,include,path,secure,expires,name,value=parts
        # Only YouTube session cookies are accepted. Other Google/website
        # credentials in an overbroad export are not stored or forwarded.
        if domain.lower() not in {'youtube.com','.youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'}:continue
        # Per-page state (ST-…) and analytics cookies pile up by the hundreds in a
        # browser export and play no part in signing in; they are not stored.
        if JUNK.match(name):continue
        if include not in {'TRUE','FALSE'} or secure not in {'TRUE','FALSE'} or not expires.isdigit() or not path.startswith('/') or not name or not value or any(ord(c)<32 for c in line if c!='\t'):
            raise HTTPException(422,'Некорректная запись сессии YouTube.')
        if int(expires) and int(expires)<=time.time():continue
        rows.append('\t'.join([domain.lower(),include,path,secure,expires,name,value]));names.add(name)
        if len(rows)>400:raise HTTPException(422,'Слишком много cookies YouTube в экспорте. Экспортируй их из нового приватного окна, где открыт только YouTube.')
    if not names&{'SID','SAPISID','__Secure-1PSID','__Secure-3PSID'}:
        raise HTTPException(422,'В файле нет действующей авторизованной сессии YouTube. Войди на YouTube перед экспортом.')
    return '# Netscape HTTP Cookie File\n'+'\n'.join(rows)+'\n'

def cookie_rejected(detail):
    return 'youtube account cookies are no longer valid' in detail.lower()


def same_snapshot(current, previous):
    return bool(current and previous and current.get('updated') == previous.get('updated')
                and current.get('cookies') == previous.get('cookies'))


def playback_rejected(previous):
    store = _store()
    if not store or not previous:
        return
    with store.lock:
        current = credentials()
        if same_snapshot(current, previous):
            store.setting(SETTING, {**current, 'needsRefresh': True, 'checked': time.time()})


def playback_verified(raw, previous):
    """Persist a changed jar only after playback verifies the same session."""
    store = _store()
    if not store or not previous:
        return
    try:
        candidate = normalize_cookies(raw)
    except HTTPException:
        candidate = previous['cookies']
    def has_login_marker(jar):
        return any(line.split('\t')[-2:-1] == ['LOGIN_INFO'] for line in jar.splitlines())
    if has_login_marker(previous['cookies']) and not has_login_marker(candidate):
        candidate = previous['cookies']
    with store.lock:
        current = credentials()
        if not same_snapshot(current, previous):
            return
        changed = candidate != current['cookies']
        if changed or current.get('needsRefresh') or not current.get('checked'):
            now = time.time()
            update = {**current, 'cookies': candidate, 'needsRefresh': False, 'checked': now}
            if changed:
                update['refreshed'] = now
            store.setting(SETTING, update)

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
        return {'configured':bool(value),'updated':value.get('updated') if value else None,'refreshed':value.get('refreshed') if value else None,'checked':value.get('checked') if value else None,'needsRefresh':bool(value and value.get('needsRefresh'))}

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
