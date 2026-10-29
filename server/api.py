"""Unattended, owner-only importer. Run with uvicorn api:app --port 7860.

Google offline consent happens once. Refresh credentials and queued encryption
keys are encrypted on the server's private volume; completed/cancelled tasks
discard their vault key. Public source clients never receive Google credentials.
"""
from __future__ import annotations

import base64
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from urllib.parse import urlencode, urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, SecretStr
import requests

from metadata_catalog import metadata
from run_import import run_job, validate_job
from site_adapters import inspect_source, search_sources, voice_availability
from source_parser import SourceError
from task_store import TaskStore
from vault_drive import ADMIN_EMAIL_SHA256, GoogleDriveAdapter, VaultDrive, VaultError


CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "262576202069-9gcrr64crhdubh2drhsspsnq9c0rtfri.apps.googleusercontent.com")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
ORIGIN = os.getenv("ALLOWED_ORIGIN", "https://onikri.github.io").rstrip("/")
REDIRECT = PUBLIC_URL + "/oauth/callback"
store = None
stopping = threading.Event()
wakeup = threading.Event()


def client_secret():
    configured = store.setting("configuration:google-oauth") if store else None
    return configured["client_secret"] if configured else CLIENT_SECRET


def b64url(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def session_token(subject):
    body = b64url(json.dumps({"sub": subject, "exp": int(time.time()) + 86400, "nonce": secrets.token_urlsafe(12)}, separators=(",", ":")).encode())
    return body + "." + b64url(hmac.digest(store.key, body.encode(), "sha256"))


def owner(authorization: str = Header(default="")):
    try:
        token = authorization.removeprefix("Bearer ")
        body, signature = token.split(".")
        if not hmac.compare_digest(signature, b64url(hmac.digest(store.key, body.encode(), "sha256"))):
            raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if payload["exp"] < time.time() or not payload.get("sub"):
            raise ValueError()
        return payload["sub"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "Войди через Google на сайте заново.") from None


def google_identity(token):
    try:
        response = requests.get("https://www.googleapis.com/oauth2/v3/userinfo", headers={"Authorization": "Bearer " + token}, timeout=(6, 15))
        response.raise_for_status()
        user = response.json()
        if user.get("email_verified") is not True or not user.get("email") or not user.get("sub"):
            raise HTTPException(403, "Google не подтвердил аккаунт.")
        return user
    except (requests.RequestException, ValueError):
        raise HTTPException(401, "Google не подтвердил вход. Подключи аккаунт на сайте заново.") from None


def google_user(token):
    user = google_identity(token)
    if hashlib.sha256(user['email'].strip().lower().encode()).hexdigest() != ADMIN_EMAIL_SHA256:
        raise HTTPException(403, 'Сервер импорта доступен только владельцу MediaVault.')
    return user


def drive_credentials(subject):
    value = store.setting("google:" + subject)
    secret = client_secret()
    if not value or not secret:
        raise VaultError("Подключи Google Drive к серверу один раз в настройках импорта.")
    from google.oauth2.credentials import Credentials
    return Credentials(token=None, refresh_token=value["refresh_token"], token_uri="https://oauth2.googleapis.com/token",
                       client_id=CLIENT_ID, client_secret=secret,
                       scopes=["openid", "email", "profile", "https://www.googleapis.com/auth/drive"])


def drive_error_message(error):
    status=getattr(getattr(error,'resp',None),'status',None)
    if status is None:return None
    try:
        body=json.loads(getattr(error,'content',b'{}'))
        reasons={entry.get('reason') for entry in body.get('error',{}).get('errors',[])}
    except (ValueError,TypeError,AttributeError):reasons=set()
    if 'storageQuotaExceeded' in reasons:return 'На Google Drive недостаточно свободного места. Готовые серии сохранены. Освободи место и продолжи задание.'
    if status==429 or reasons & {'rateLimitExceeded','userRateLimitExceeded'}:return 'Google временно ограничил запись в Drive. Готовые серии сохранены; задание можно продолжить позже.'
    if status==403:return 'Google Drive не разрешил запись. Проверь доступ владельца к папке библиотеки и разрешение на запись.'
    if status==404:return 'Файл или папка библиотеки недоступны в Google Drive. Открой свою библиотеку заново.'
    if status in {500,502,503,504}:return 'Google Drive временно недоступен. Завершённые серии сохранены; повтори продолжение позже.'
    return None


def worker():
    last_cleanup = 0
    while not stopping.is_set():
        if time.monotonic() - last_cleanup > 60:
            store.expire_keys()
            last_cleanup = time.monotonic()
        task = store.next()
        if not task:
            wakeup.wait(5)
            wakeup.clear()
            continue
        task_id, vault = task["id"], None
        if task["created"] < time.time() - 7 * 86400:
            store.update(task_id, status="cancelled", progress={"message": "Срок хранения задания истёк."}, forget_key=True)
            continue
        try:
            store.update(task_id, progress={"phase": "preparing"})
            data = task["data"]
            vault = VaultDrive(GoogleDriveAdapter.from_adc(drive_credentials(task["owner"])))
            library_id=data.get('library_id') or data['job']['library_id']
            vault.unlock_key(library_id, base64.b64decode(data["vault_key"], validate=True))
            if not task['progress'].get('recover_needed',True):vault._manifest_cache=[]
            base_counts={key:task['progress'].get(key,0) for key in ('saved','skipped','failed')}
            def progress(event):
                event={**event,**{key:base_counts[key]+event[key] for key in base_counts if key in event}}
                store.update(task_id, progress=event)
            def cancelled():
                return store.get(task_id)["status"] == "cancelling"
            if data.get('kind')=='enrich':
                from library_enrichment import enrichment_step
                result=enrichment_step(vault,cursor=task['progress'].get('cursor',0),title_id=data.get('title_id'),progress=progress)
            else:
                def saved(item):
                    group=item.get('collectionId')
                    if group and item.get('category') in {'video','manga'}:
                        identity='artwork-'+hashlib.sha256((library_id+':'+group+':v2').encode()).hexdigest()
                        try:store.add(task['owner'],{'kind':'enrich','library_id':library_id,'vault_key':data['vault_key'],'title_id':item.get('section','anime')+':'+group},identity)
                        except ValueError:pass
                result = run_job(data["job"], vault, log=lambda _: None, progress=progress, cancelled=cancelled,
                                 temporary_dir=store.directory / "temporary",start_index=task['progress'].get('cursor',0),max_files=1,on_saved=saved)
            result={**result,**{key:base_counts[key]+result[key] for key in base_counts}}
            if cancelled():
                store.update(task_id, status="cancelled", progress={"phase": "cancelled"}, forget_key=True)
            elif result.get('remaining'):
                store.update(task_id,status='queued',progress={**result,'phase':'queued','recover_needed':False,'message':'Следующая серия — после одного файла из других заданий.'})
                wakeup.set()
            elif result["failed"]:
                store.update(task_id, status="failed", progress={"phase": "failed", **result,
                    "message": "Некоторые файлы недоступны в источнике. Сохранённые уже в коллекции; задание можно продолжить."})
            else:
                store.update(task_id, status="completed", progress={"phase": "done", **result}, forget_key=True)
        except Exception as error:
            if store.get(task_id)["status"] == "cancelling":
                store.update(task_id, status="cancelled", progress={"phase": "cancelled"}, forget_key=True)
            elif error.__class__.__module__.startswith("google.auth") or isinstance(error, HTTPException):
                store.update(task_id, status="waiting_auth", progress={"message": "Серверу нужно повторное разрешение Google. Завершённые серии сохранены."})
            else:
                message = drive_error_message(error) or (str(error) if isinstance(error, (SourceError, VaultError)) else "Импорт остановился. Завершённые файлы в Drive сохранены; задание можно продолжить.")
                store.update(task_id, status="failed", progress={"phase": "failed", "message": message[:500]})
        finally:
            if vault:
                vault.close()


@asynccontextmanager
async def lifespan(application):
    global store
    store = TaskStore(os.getenv("DATA_DIR", "/data"))
    temporary = store.directory / "temporary"
    temporary.mkdir(exist_ok=True, mode=0o700)
    stopping.clear()
    thread = threading.Thread(target=worker, daemon=True, name="media-import")
    if os.getenv("MEDIA_VAULT_DISABLE_WORKER") != "1":
        thread.start()
    yield
    stopping.set()
    wakeup.set()
    from manga_discovery import shutdown as shutdown_manga_discovery
    shutdown_manga_discovery()
    from local_exports import shutdown as shutdown_local_exports
    shutdown_local_exports()
    if thread.is_alive():
        thread.join(timeout=2)
    # A live worker may still be finishing a bounded source request during shutdown.
    if not thread.is_alive():
        store.close()


app = FastAPI(title="MediaVault import service", version="8.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=[ORIGIN], allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key"], expose_headers=["Content-Disposition"])


@app.middleware("http")
async def limits(request: Request, call_next):
    if request.method == "POST":
        maximum=14*1024*1024 if request.url.path=="/reader/translate" else 512*1024
        if request.headers.get("origin") not in (None, ORIGIN):
            return JSONResponse({"detail": "Origin denied"}, status_code=403)
        try:
            if int(request.headers.get("content-length", "0")) > maximum:
                return JSONResponse({"detail": "Request too large"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Invalid content length"}, status_code=400)
        if len(await request.body()) > maximum:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(SourceError)
@app.exception_handler(VaultError)
async def source_error(request, error):
    return JSONResponse({"detail": str(error)}, status_code=422)


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # FastAPI's default response can echo input values, including a submitted key.
    return JSONResponse({"detail": "Некорректные параметры запроса."}, status_code=422)


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


@app.get("/health")
def health():
    return {"application": "MediaVault", "version": 17, "mangaGlobalDiscovery":True, "onlinePlayback":True, "mangaLanguages":["ru","en","ja","ko"], "mangaFormats":["manga","manhwa","manhua","webtoon"], "readerTranslation":True, "animeMusic":True, "mangaImport":True,"platformRatings":True,"voiceDiscovery": True, "sourceQualities": True, "rememberedDevices": True, "oauthConfigured": bool(client_secret() and PUBLIC_URL.startswith("https://")),
            "origin": ORIGIN, "worker": "server", "paidServices": False}


@app.post("/auth/session")
def authenticate(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer ") or len(authorization) > 8192:
        raise HTTPException(401, "Нужен вход через Google.")
    user = google_user(authorization[7:])
    return {"token": session_token(user["sub"]), "driveConnected": bool(store.setting("google:" + user["sub"])),
            "oauthConfigured": bool(client_secret() and PUBLIC_URL.startswith("https://"))}


class GoogleOAuthConfiguration(StrictBody):
    client_id: str = Field(max_length=200)
    client_secret: SecretStr


@app.post("/admin/google-oauth")
def configure_google(body: GoogleOAuthConfiguration, subject=Depends(owner)):
    secret = body.client_secret.get_secret_value().strip()
    if body.client_id != CLIENT_ID or not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", secret):
        raise HTTPException(422, "Нужны настройки существующего Web OAuth-клиента MediaVault.")
    if not PUBLIC_URL.startswith("https://"):
        raise HTTPException(503, "Сначала настрой HTTPS сервера.")
    store.setting("configuration:google-oauth", {"client_secret": secret})
    return {"oauthConfigured": True, "redirectUri": REDIRECT}


@app.post("/oauth/start")
def oauth_start(subject=Depends(owner)):
    return {"url": oauth_url(subject)}


def oauth_url(subject, *, device_id=None, readonly=False):
    if not client_secret() or not PUBLIC_URL.startswith("https://"):
        raise HTTPException(503, "Администратору нужно завершить одноразовую настройку Google OAuth на сервере.")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    store.setting("oauth:" + state, {"sub": subject, "expires": time.time() + 600, "verifier": verifier, "device": device_id, "readonly": readonly})
    params = {"client_id": CLIENT_ID, "redirect_uri": REDIRECT, "response_type": "code",
              "scope": "openid email profile https://www.googleapis.com/auth/" + ("drive.readonly" if readonly else "drive"), "state": state,
              "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true",
              "code_challenge_method": "S256", "code_challenge": b64url(hashlib.sha256(verifier.encode()).digest())}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


@app.get("/oauth/callback", response_class=HTMLResponse)
def oauth_callback(state: str = "", code: str = "", error: str = ""):
    pending = store.consume("oauth:" + state)
    if not pending or pending["expires"] < time.time() or error or not code:
        raise HTTPException(400, "Разрешение Google отменено или устарело. Повтори подключение на сайте.")
    try:
        response = requests.post("https://oauth2.googleapis.com/token", data={"code": code, "client_id": CLIENT_ID,
            "client_secret": client_secret(), "redirect_uri": REDIRECT, "grant_type": "authorization_code", "code_verifier": pending["verifier"]}, timeout=(6, 20))
        response.raise_for_status()
        tokens = response.json()
    except (requests.RequestException, ValueError):
        raise HTTPException(502, "Не удалось завершить разрешение Google. Повтори подключение.") from None
    user = (google_identity if pending.get('device') else google_user)(tokens.get("access_token", ""))
    if user["sub"] != pending["sub"]:
        raise HTTPException(403, "Выбран другой Google-аккаунт.")
    scopes = set(tokens.get("scope", "").split())
    required_scope = 'https://www.googleapis.com/auth/drive.readonly' if pending.get('readonly') else 'https://www.googleapis.com/auth/drive'
    if required_scope not in scopes and 'https://www.googleapis.com/auth/drive' not in scopes:
        raise HTTPException(403, "Для серверного импорта нужно разрешить запись в Google Drive.")
    destination = 'device-google:' + pending['device'] if pending.get('device') else 'google:' + user['sub']
    old = store.setting(destination) or {}
    refresh = tokens.get("refresh_token") or old.get("refresh_token")
    if not refresh:
        raise HTTPException(400, "Google не выдал фоновый доступ. Повтори подключение с подтверждением разрешений.")
    store.setting(destination, {"refresh_token": refresh, 'scope': tokens.get('scope', '')})
    if pending.get('device'):
        device = store.setting('device:' + pending['device'])
        if not device or device['sub'] != user['sub']:
            raise HTTPException(403, 'Устройство больше не зарегистрировано.')
        store.setting('device:' + pending['device'], {**device, 'ready': True, 'expires':time.time()+90*86400})
    for task in store.list(user["sub"]):
        if task["status"] == "waiting_auth":
            store.update(task["id"], status="queued")
    wakeup.set()
    # No tokens, state, code or keys are included in the returned page.
    return "<!doctype html><meta charset=utf-8><title>MediaVault</title><p>Google Drive подключён. Можно вернуться в MediaVault.</p><script>if(window.opener){window.opener.postMessage({type:'mediavault-server-connected'}," + json.dumps(ORIGIN) + ");window.close();}</script>"


from device_sessions import install as install_device_sessions
install_device_sessions(app, sys.modules[__name__])


@app.get('/metadata/posters')
def title_posters(ids: str = '', kind: str = 'anime'):
    from poster_assets import posters
    if len(ids)>400 or kind not in {'anime','manga','ranobe'}:raise HTTPException(422,'Некорректные ID постеров.')
    return posters(ids.split(','),kind)


@app.get('/metadata/watch-order')
def title_watch_order(identity: str = ''):
    if not re.fullmatch(r'\d{1,12}',identity):raise HTTPException(422,'Некорректный тайтл.')
    from watch_order import watch_order
    return watch_order(identity)


@app.get('/metadata/ratings')
def title_platform_ratings(identity:str='',kind:str='anime'):
    from title_ratings import ratings
    return ratings(identity,kind)

@app.get("/metadata/{provider}")
def catalogue(provider: str, q: str = "", kind: str = "anime", page: int = 1, identity: str | None = None, year: int | None = None, part: str = '',genre:str='',tag:str=''):
    return metadata(provider, query=q, kind=kind, page=page, identity=identity, year=year, part=part,genre=genre,tag=tag)


@app.get('/artwork')
def artwork(url: str):
    from artwork import fetch_image
    data,mime=fetch_image(url)
    return Response(data,media_type=mime,headers={'Cache-Control':'public,max-age=86400','X-Content-Type-Options':'nosniff'})


@app.get("/sources/search")
def source_search(q: str, kind: str = "anime", subject=Depends(owner)):
    if not 2 <= len(q.strip()) <= 160:
        raise HTTPException(422, "Укажи название от 2 до 160 символов.")
    if kind=='manga':
        from manga_sources import search_title
        return search_title({'kind':'manga','title':q.strip()})
    return search_sources(q.strip(), kind)


@app.get("/sources/availability")
def availability(q: str, subject=Depends(owner)):
    if not 2 <= len(q.strip()) <= 160:
        raise HTTPException(422, "Некорректное название.")
    return voice_availability(q.strip())


class Inspection(StrictBody):
    url: str = Field(max_length=8192)
    dub_url: str | None = Field(default=None, max_length=8192)
    season: int | None = Field(default=None, ge=1, le=1000)
    kind: str = "anime"
    continuation: str | None = Field(default=None,max_length=100)


_inspection_states={}
_inspection_lock=threading.Lock()


@app.post("/sources/inspect")
def source_inspect(body: Inspection, subject=Depends(owner)):
    if body.kind not in {"anime", "movie", "tv", "manga", "ranobe"}:
        raise HTTPException(422, "Неизвестный тип произведения.")
    signature=(subject,body.url,body.dub_url,body.season,body.kind)
    with _inspection_lock:
        for token in [k for k,v in _inspection_states.items() if v['expires']<time.monotonic()]:_inspection_states.pop(token,None)
        token=body.continuation or secrets.token_urlsafe(20)
        if body.continuation:
            entry=_inspection_states.get(token)
            if not entry or entry['signature']!=signature:raise HTTPException(422,'Проверка истекла. Запусти проверку ссылки заново.')
        else:
            if len(_inspection_states)>=16:_inspection_states.pop(next(iter(_inspection_states)))
            entry={'signature':signature,'state':{},'lock':threading.Lock(),'expires':time.monotonic()+300}
            _inspection_states[token]=entry
    try:
        with entry['lock']:
            value=inspect_source(body.url,dub_url=body.dub_url,season=body.season,kind=body.kind,state=entry['state'])
            entry['expires']=time.monotonic()+300
    except BaseException:
        with _inspection_lock:_inspection_states.pop(token,None)
        raise
    if value.get('pending'):value['continuation']=token
    else:
        with _inspection_lock:_inspection_states.pop(token,None)
    return value


class TitleDiscovery(StrictBody):
    title: dict
    refresh: bool = False
    continuing: bool = False

class MangaDiscovery(TitleDiscovery):
    language:str=Field(default='auto',pattern=r'^(auto|all|ru|en|ja|ko)$')
    format:str=Field(default='all',pattern=r'^(all|manga|manhwa|manhua|webtoon)$')
    bridgeOffset:int=Field(default=0,ge=0,le=10000)
    bridgeLimit:int=Field(default=8,ge=1,le=16)

class MangaGlobalSearch(StrictBody):
    query:str=Field(min_length=2,max_length=160)
    language:str=Field(default='all',pattern=r'^(all|ru|en|ja|ko)$')
    sourceIds:list[str]|None=Field(default=None,max_length=1000)
    refresh:bool=False

def manga_discovery_call(action,*args):
    from manga_discovery import SearchLimit,SearchMissing
    try:return action(*args)
    except SearchLimit as error:raise HTTPException(429,str(error)) from None
    except SearchMissing as error:raise HTTPException(404,str(error)) from None
    except ValueError as error:raise HTTPException(422,str(error)) from None

@app.get('/discovery/manga/sources')
def discovery_manga_sources(language:str='all',q:str='',subject=Depends(owner)):
    from manga_discovery import source_list
    return manga_discovery_call(source_list,language,q)

@app.post('/discovery/manga/search',status_code=202)
def discovery_manga_search(body:MangaGlobalSearch,subject=Depends(owner)):
    from manga_discovery import manager
    return manga_discovery_call(manager().start,subject,body.query,body.language,body.sourceIds,body.refresh)

@app.get('/discovery/manga/search/{identity}')
def discovery_manga_status(identity:str,subject=Depends(owner)):
    from manga_discovery import manager
    return manga_discovery_call(manager().status,subject,identity)

@app.delete('/discovery/manga/search/{identity}')
def discovery_manga_cancel(identity:str,subject=Depends(owner)):
    from manga_discovery import manager
    return manga_discovery_call(manager().cancel,subject,identity)

@app.post('/manga/search')
def manga_search(body:MangaDiscovery,subject=Depends(owner)):
    from manga_sources import search_title
    from concurrent.futures import ThreadPoolExecutor
    from suwayomi_bridge import search as bridge_search
    with ThreadPoolExecutor(max_workers=2) as pool:
        native=pool.submit(search_title,body.title,body.language,body.format)
        bridge=pool.submit(bridge_search,body.title,body.language,body.format,body.bridgeOffset,body.bridgeLimit)
        result=native.result();extra=bridge.result()
    known={v['url'] for v in result['results']}
    return {**result,'results':[*result['results'],*[v for v in extra['results'] if (v.get('sourceUrl') or v['url']) not in known]],'providers':[*result['providers'],*extra['providers']],'bridgeSearch':extra.get('window')}


@app.get('/manga/bridge/status')
def manga_bridge_status(subject=Depends(owner)):
    from suwayomi_bridge import status
    return status()

@app.get('/manga/bridge/extensions')
def manga_bridge_extensions(language:str='all',q:str='',subject=Depends(owner)):
    from suwayomi_bridge import extension_catalog
    if language not in {'all','ru','en','ja','ko'}:raise HTTPException(422,'Выбери язык источника.')
    return extension_catalog(language,q)

class MangaExtension(StrictBody):
    package:str=Field(max_length=180)

@app.post('/manga/bridge/install')
def manga_bridge_install(body:MangaExtension,subject=Depends(owner)):
    from suwayomi_bridge import install
    return install(body.package)

class MangaLanguagePack(StrictBody):
    languages:list[str]=Field(min_length=1,max_length=4)

@app.post('/manga/bridge/install-pack',status_code=202)
def manga_bridge_install_pack(body:MangaLanguagePack,subject=Depends(owner)):
    from suwayomi_installer import start
    return start(body.languages)

@app.get('/manga/bridge/install-pack')
def manga_bridge_pack_status(subject=Depends(owner)):
    from suwayomi_installer import status
    return status()

@app.post('/manga/bridge/search')
def manga_bridge_search(body:MangaDiscovery,subject=Depends(owner)):
    from suwayomi_bridge import search
    return search(body.title,body.language,body.format,body.bridgeOffset,body.bridgeLimit)

class MangaInspection(StrictBody):
    url:str=Field(max_length=8192)
    title:dict|None=None

@app.post('/manga/inspect')
def manga_inspect(body:MangaInspection,subject=Depends(owner)):
    from manga_sources import inspect,title_aliases
    from title_identity import match_title
    value=inspect(body.url)
    if body.title:
        if len(json.dumps(body.title).encode())>50000:raise HTTPException(422,'Слишком большое описание манги.')
        candidate={'title':value['title'],'aliases':list(dict.fromkeys([*title_aliases(value['title']),*(value.get('identityTitles') or value.get('aliases') or [])])),'kind':'manga','year':value.get('year'),'ids':value.get('ids') or {}}
        if body.title.get('kind')!='manga' or not match_title(body.title,candidate)[0]:raise HTTPException(422,'Источник относится к другому произведению. Выбери перевод нужной манги.')
    return value


class QualityInspection(StrictBody):
    url: str = Field(max_length=8192)


@app.post('/sources/qualities')
def source_qualities(body: QualityInspection, subject=Depends(owner)):
    from source_quality import inspect_qualities
    return inspect_qualities(body.url)


@app.post('/sources/discover')
def discover_voices(body: TitleDiscovery, subject=Depends(owner)):
    from source_discovery import discover
    if len(json.dumps(body.title)) > 10000:
        raise HTTPException(422, 'Слишком большое описание тайтла.')
    try:
        return discover(body.title,refresh=body.refresh,continuing=body.continuing)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None

@app.get('/discovery/voices')
def discovery_voice_suggestions(q:str='',subject=Depends(owner)):
    from source_discovery import voice_suggestions
    if len(q)>80:raise HTTPException(422,'Слишком длинный запрос озвучки.')
    return voice_suggestions(q)


@app.get('/sources/calendar')
def source_calendar(subject=Depends(owner)):
    from release_calendar import calendar
    return calendar()


class ImportTask(StrictBody):
    job: dict
    vault_key: str = Field(min_length=44, max_length=44)


@app.post("/jobs", status_code=202)
def submit(body: ImportTask, subject=Depends(owner), idempotency_key: str = Header(default="")):
    validate_job(body.job)
    try:
        if len(base64.b64decode(body.vault_key, validate=True)) != 32:
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "Некорректный ключ открытой библиотеки.") from None
    if not re.fullmatch(r"[\w-]{16,100}", idempotency_key, re.ASCII):
        raise HTTPException(422, "Нужен уникальный идентификатор запроса.")
    if not store.setting("google:" + subject):
        raise HTTPException(409, "Подключи Google Drive к серверу один раз перед первым импортом.")
    try:
        task = store.add(subject, {"job": body.job, "vault_key": body.vault_key}, idempotency_key)
    except ValueError as error:
        raise HTTPException(429, str(error)) from None
    wakeup.set()
    return task


@app.get("/jobs")
def tasks(subject=Depends(owner)):
    return {"jobs": store.list(subject)}


class Enrichment(StrictBody):
    library_id: str = Field(pattern=r'^[A-Za-z0-9_-]{5,256}$')
    vault_key: SecretStr
    title_id: str | None = Field(default=None,max_length=300)


@app.post('/library/enrich',status_code=202)
def enrich_library(body: Enrichment,subject=Depends(owner),idempotency_key: str=Header(default='')):
    try:
        if len(base64.b64decode(body.vault_key.get_secret_value(),validate=True))!=32:raise ValueError()
    except ValueError:raise HTTPException(422,'Некорректный ключ библиотеки.') from None
    if not re.fullmatch(r'[\w-]{16,100}',idempotency_key,re.ASCII):raise HTTPException(422,'Нужен идентификатор синхронизации.')
    if not store.setting('google:'+subject):raise HTTPException(409,'Подключи фоновый доступ к Drive.')
    try:task=store.add(subject,{'kind':'enrich','library_id':body.library_id,'vault_key':body.vault_key.get_secret_value(),'title_id':body.title_id},idempotency_key)
    except ValueError as error:raise HTTPException(429,str(error)) from None
    wakeup.set();return task


@app.get("/jobs/{task_id}")
def task(task_id: str, subject=Depends(owner)):
    value = store.get(task_id, subject)
    if not value:
        raise HTTPException(404, "Задание не найдено.")
    return value


@app.post("/jobs/{task_id}/cancel")
def cancel(task_id: str, subject=Depends(owner)):
    value = task(task_id, subject)
    active = value["status"] == "running"
    store.update(task_id, status="cancelling" if active else "cancelled", forget_key=not active)
    return task(task_id, subject)


@app.post("/jobs/{task_id}/resume")
def resume(task_id: str, subject=Depends(owner)):
    value = task(task_id, subject)
    if value["status"] not in {"failed", "waiting_auth"}:
        raise HTTPException(409, "Это задание сейчас нельзя продолжить.")
    private = store.get(task_id, subject, private=True)
    if not private["data"].get("vault_key"):
        raise HTTPException(409, "Открой библиотеку и запусти новое задание: завершённые серии будут пропущены.")
    store.update(task_id, status="queued", progress={"message": "", "phase": "queued",'cursor':0,'saved':0,'skipped':0,'failed':0,'recover_needed':True})
    wakeup.set()
    return task(task_id, subject)

from trailer_service import install as install_trailers
install_trailers(app, os.getenv("DATA_DIR", "/data"))

from reader_translation import install as install_reader_translation
install_reader_translation(app, os.getenv("DATA_DIR", "/data"), owner)
from anime_music import install as install_anime_music
install_anime_music(app)

from online_sessions import install as install_online
install_online(app,owner)
from music_playback import install as install_music_playback
install_music_playback(app)
from music_artists import install as install_music_artists
install_music_artists(app)
