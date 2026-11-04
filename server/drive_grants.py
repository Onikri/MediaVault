"""Public background-Drive state, separate from browser file permissions."""
import threading,time
from fastapi import Depends,HTTPException
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
slots=threading.BoundedSemaphore(2)
def status(store,subject):
    value=store.setting('google:'+subject) or {}
    return {'configured':bool(value),'connected':bool(value) and not value.get('needs_consent',False),'needsConsent':bool(value.get('needs_consent')),
            'state':'missing' if not value else 'needs_consent' if value.get('needs_consent') else 'ready' if value.get('checked_at') else 'unverified',
            'checkedAt':value.get('checked_at')}
def rejected(store,subject,refresh_token=None):
    with store.lock:
        value=store.setting('google:'+subject)
        if value and (refresh_token is None or value.get('refresh_token')==refresh_token) and not value.get('needs_consent'):store.setting('google:'+subject,{**value,'needs_consent':True,'checked_at':time.time()})

def install(app,owner,get_store,credentials):
    @app.get('/google/connection')
    def connection(subject=Depends(owner)):return status(get_store(),subject)
    @app.post('/google/connection/check')
    def check(subject=Depends(owner)):
        store=get_store();value=store.setting('google:'+subject)
        if not value:return status(store,subject)
        if time.time()-float(value.get('checked_at') or 0)<20:return status(store,subject)
        if not slots.acquire(False):raise HTTPException(429,'Проверка Google занята. Повтори через несколько секунд.')
        session=__import__('requests').Session()
        try:
            transport=Request(session=session)
            def bounded(url,method='GET',body=None,headers=None,**kwargs):return transport(url=url,method=method,body=body,headers=headers,timeout=8)
            credential=credentials(subject);credential.refresh(bounded)
            with store.lock:
                current=store.setting('google:'+subject)
                if current and current.get('refresh_token')==value.get('refresh_token'):store.setting('google:'+subject,{**current,'needs_consent':False,'checked_at':time.time()})
            return status(store,subject)
        except RefreshError as error:
            if not getattr(error,'retryable',False):rejected(store,subject,value.get('refresh_token'));return status(store,subject)
            return {**status(store,subject),'checkError':'Google временно не ответил. Сохранённое разрешение не удалено.'}
        except Exception:return {**status(store,subject),'checkError':'Не удалось связаться с Google. Сохранённое разрешение не удалено.'}
        finally:session.close();slots.release()
