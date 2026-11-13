"""Unattended, owner-only importer. Run with uvicorn api:app --port 7860.

Google offline consent happens once. Refresh credentials and queued encryption
keys are encrypted on the server's private volume; completed/cancelled tasks
discard their vault key. Public source clients never receive Google credentials.
"""
from __future__ import annotations

import asyncio
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
from source_parser import SourceError,public_url
from task_store import TaskStore
import drive_grants
import system_status
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


def sign_payload(payload):
    body = b64url(json.dumps(payload, separators=(",", ":")).encode())
    return body + "." + b64url(hmac.digest(store.key, body.encode(), "sha256"))


def session_token(subject):
    return sign_payload({"sub": subject, "exp": int(time.time()) + 86400, "nonce": secrets.token_urlsafe(12)})


def token_payload(authorization):
    try:
        token = authorization.removeprefix("Bearer ")
        body, signature = token.split(".")
        if not hmac.compare_digest(signature, b64url(hmac.digest(store.key, body.encode(), "sha256"))):
            raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if payload["exp"] < time.time() or not payload.get("sub"):
            raise ValueError()
        return payload
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(401, "Войди на сайте заново.") from None


def owner(authorization: str = Header(default="")):
    payload = token_payload(authorization)
    # Guest sessions share the signing key but never reach owner endpoints.
    if payload.get("role") in {"guest","share"} or str(payload["sub"]).startswith(("guest:","share:")):
        raise HTTPException(403, "Это действие доступно только владельцу MediaVault.")
    return payload["sub"]


def guest_may_open(subject, title):
    """Owner: always. Guest: only titles (and kinds) the owner opened for them."""
    if not str(subject or '').startswith('guest:'):
        return
    import guest_profiles
    record = store.setting('guest:' + str(subject)[6:]) if store else None
    identity = str(subject)[6:]
    if not guest_profiles.allows(record, title):
        guest_activity.event(identity, 'Попытка открыть закрытый тайтл', title)
        raise HTTPException(403, 'Владелец пока не открыл тебе этот тайтл. Попроси его добавить тайтл в твой доступ.')
    guest_activity.opened(identity, title)


def viewer(request:Request=None, authorization: str = Header(default="")):
    """Owner or an active guest profile: online viewing, reading and music only."""
    payload = token_payload(authorization)
    if payload.get('role')=='share':
        return app.state.title_shares.subject(authorization,request)
    if payload.get("role") == "guest" or str(payload["sub"]).startswith("guest:"):
        return guest_subject(authorization).get("id") and payload["sub"]
    return payload["sub"]


def google_identity(token):
    try:
        response = requests.get("https://www.googleapis.com/oauth2/v3/userinfo", headers={"Authorization": "Bearer " + token}, timeout=(6, 15))
        response.raise_for_status()
        user = response.json()
        if user.get("email_verified") is not True or not user.get("email") or not user.get("sub"):
            raise HTTPException(403, "Google не подтвердил аккаунт.")
        return user
    except (requests.RequestException, ValueError) as cause:
        if getattr(getattr(cause, 'response', None), 'status_code', None) in {401, 403}:
            raise HTTPException(401, "Google не подтвердил вход. Подключи аккаунт на сайте заново.") from None
        raise HTTPException(503, "Google временно не подтвердил вход. Повтори немного позже.") from None


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


def import_auth_error(error):
    from google.auth.exceptions import RefreshError
    if isinstance(error,RefreshError):return not getattr(error,'retryable',False)
    if isinstance(error,VaultError):return str(error).startswith('Подключи Google Drive к серверу')
    return isinstance(error,HTTPException) and error.status_code in {401,403} and any(v in str(error.detail).casefold() for v in ('google','drive'))

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
        task_id, vault,credential = task["id"], None,None
        if task["created"] < time.time() - 7 * 86400:
            store.update(task_id, status="cancelled", progress={"message": "Срок хранения задания истёк."}, forget_key=True)
            continue
        try:
            data = task["data"]
            store.update(task_id, progress={"phase":"preparing","operation":"Открываем каталог Google Drive","message":"","taskType":data.get('kind','import')})
            credential=drive_credentials(task["owner"])
            vault = VaultDrive(GoogleDriveAdapter.from_adc(credential))
            library_id=data.get('library_id') or data['job']['library_id']
            vault.unlock_key(library_id, base64.b64decode(data["vault_key"], validate=True))
            if not task['progress'].get('recover_needed',True):vault._manifest_cache=[]
            base_counts={key:task['progress'].get(key,0) for key in ('saved','skipped','failed')}
            def progress(event):
                event={**event,**{key:base_counts[key]+event[key] for key in base_counts if key in event}}
                store.update(task_id, progress=event)
            vault.checkpoint_progress=lambda checked:progress({"operation":f"Проверяем незавершённые файлы в Drive · {checked}"})
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
                                 temporary_dir=store.directory / "temporary",start_index=task['progress'].get('cursor',0),max_files=1,on_saved=saved,
                                 alloha_downloader=app.state.alloha_importer.download,
                                 alloha_streamer=app.state.alloha_importer.stream,
                                 alloha_cache=store.directory / ".codex-local" / "alloha-import" / task_id,
                                 staged_source=lambda identity,directory,owner=task['owner']:__import__('local_exports').manager().take(owner,identity,directory))
            if stopping.is_set():continue
            result={**result,**{key:base_counts[key]+result[key] for key in base_counts}}
            if cancelled():
                store.update(task_id, status="cancelled", progress={"phase": "cancelled"}, forget_key=True)
            elif result.get('remaining'):
                store.update(task_id,status='queued',progress={**result,'phase':'queued','operation':'Ожидает следующего прохода','recover_needed':False,'message':'Следующий файл оформления — после других заданий.' if data.get('kind')=='enrich' else 'Следующая серия — после одного файла из других заданий.'})
                wakeup.set()
            elif result["failed"]:
                reason=store.get(task_id)["progress"].get("sourceError")
                store.update(task_id, status="failed", progress={"phase": "failed", **result,
                    "message": reason or "Некоторые файлы недоступны в источнике. Сохранённые уже в коллекции; задание можно продолжить."})
            else:
                store.update(task_id, status="completed", progress={"phase": "done", **result}, forget_key=True)
        except Exception as error:
            if stopping.is_set():continue
            if store.get(task_id)["status"] == "cancelling":
                store.update(task_id, status="cancelled", progress={"phase": "cancelled"}, forget_key=True)
            elif import_auth_error(error):
                if credential is not None:drive_grants.rejected(store,task["owner"],getattr(credential,'refresh_token',None))
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
    from alloha_import import AllohaImporter, prune_checkpoints
    prune_checkpoints(store.directory / ".codex-local" / "alloha-import")
    application.state.alloha_importer = AllohaImporter(application.state.alloha_delivery, asyncio.get_running_loop())
    stopping.clear()
    threads=[threading.Thread(target=worker,daemon=True,name="media-import-"+str(i)) for i in range(max(1,min(2,int(os.getenv("IMPORT_WORKERS","2")))))]
    if os.getenv("MEDIA_VAULT_DISABLE_WORKER") != "1":
        from hentaichan_video import index_catalog
        catalog_stop = threading.Event()
        catalog_thread = threading.Thread(target=index_catalog, args=(catalog_stop,), daemon=True, name='hentaichan-catalog')
        catalog_thread.start()
        for thread in threads:thread.start()
    else:
        catalog_stop = None
    await lyrics_relay.start()
    application.state.alloha_delivery.start_profile_refresh()
    yield
    stopping.set()
    try:
        guest_activity.flush()
    except Exception:
        pass
    if catalog_stop:
        catalog_stop.set()
    await lyrics_relay.close()
    await application.state.alloha_delivery.close()
    wakeup.set()
    from manga_discovery import shutdown as shutdown_manga_discovery
    shutdown_manga_discovery()
    from local_exports import shutdown as shutdown_local_exports
    shutdown_local_exports()
    for thread in threads:
        if thread.is_alive():thread.join(timeout=2)
    # A live worker may still be finishing a bounded source request during shutdown.
    if not any(thread.is_alive() for thread in threads):
        store.close()


app = FastAPI(title="MediaVault import service", version="8.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=[ORIGIN], allow_methods=["GET", "HEAD", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Range"], expose_headers=["Content-Disposition","Content-Range","Accept-Ranges","Content-Length","X-Alloha-Quality","X-Alloha-Degradation","Retry-After"])


@app.middleware("http")
async def limits(request: Request, call_next):
    if request.method in {"POST","PUT","PATCH","DELETE"}:
        if request.headers.get("origin") not in (None, ORIGIN):
            return JSONResponse({"detail": "Origin denied"}, status_code=403)
    if request.method in {"POST","PUT","PATCH"}:
        maximum=30*1024*1024 if re.fullmatch(r"/online/exports/[0-9a-f]{32}/(?:pages/\d+/\d+|segments/\d+)",request.url.path) else 20*1024*1024 if request.url.path=="/reader/google/generate" else 14*1024*1024 if request.url.path=="/reader/translate" else 2*1024*1024 if request.url.path=="/music/youtube/session" else 512*1024
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
    return {"application": "MediaVault", "version": 70, "ranobeDriveText":True,"videoChapters":True,"mangaOriginProbe":True,"titleSharing":True, "allohaConnector":True, "geminiVoice":True, "bookLanguageFallback":True, "browserStagedVideo":True, "mangaSearchBackoff":True, "googleKeyPool":True, "ranobeReader":True, "bookReader":True, "lostfilmCatalogue":True, "playerBalancer":True, "ukrainianContent":True, "hikkaMetadata":True, "controlCenter":True, "systemStatus":True, "siteRules":True, "mangaExports":True, "mangaTranslationExport":os.path.isfile(os.path.join(os.getenv("MANGA_EXPORT_ASSETS","/app/export-assets"),"manga-export.html")), "parallelImportWorkers":max(1,min(2,int(os.getenv("IMPORT_WORKERS","2")))), "kodikCatalogue":True, "mangaDiscoveryWorkers":max(1,min(8,int(os.getenv("MANGA_DISCOVERY_WORKERS","8")))), "watchRooms":True, "roomConversation":True, "driveGrantStatus":True, "mangaSourceHealth":True, "progressiveTitleBackgrounds":True, "franchiseSeasons":True, "characterProfiles":True, "progressiveDiscovery":True, "playbackPreparationVersion":2, "chapterThumbnails":True, "nativeTitleBackgrounds":True, "lyricsRelay":True, "animeDiscovery":True, "googleGatewayVersion":5, "googleParallelKeys":6, "mangaGlobalDiscovery":True, "onlinePlayback":True, "mangaLanguages":["ru","uk","en","ja","ko"], "mangaFormats":["manga","manhwa","manhua","webtoon"], "readerTranslation":True, "animeMusic":True, "mangaImport":True,"platformRatings":True,"voiceDiscovery": True, "sourceQualities": True, "rememberedDevices": True, "oauthConfigured": bool(client_secret() and PUBLIC_URL.startswith("https://")),
            "origin": ORIGIN, "worker": "server", "paidServices": False}


@app.post("/auth/session")
def authenticate(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer ") or len(authorization) > 8192:
        raise HTTPException(401, "Нужен вход через Google.")
    user = google_user(authorization[7:])
    return {"token": session_token(user["sub"]), "driveConnected": drive_grants.status(store,user["sub"])["connected"], "driveNeedsConsent":drive_grants.status(store,user["sub"])["needsConsent"],
            "oauthConfigured": bool(client_secret() and PUBLIC_URL.startswith("https://"))}


drive_grants.install(app,owner,lambda:store,drive_credentials)
system_status.install(app,owner,lambda:os.getenv("DATA_DIR","/data"),drive_credentials,lambda:store)

import google_pool
google_pool.install(app,owner,lambda:store,translator=viewer)
import video_chapters
video_chapters.install(app,viewer,os.getenv("DATA_DIR","/data"))
import gemini_voice
gemini_voice.install(app,owner,google_pool.saved)
import kodik_api
kodik_api.install(app,owner,lambda:store)
import lostfilm_catalog
lostfilm_catalog.install(app,viewer)
import hikka_metadata
hikka_metadata.install(app)
import watch_rooms,site_rules
watch_rooms.install(app,viewer,owner,lambda:site_rules.current(store)['rooms'])


@app.get('/admin/rules')
def read_rules(subject=Depends(owner)):
    return {'rules':site_rules.current(store),'defaults':site_rules.DEFAULTS}


@app.put('/admin/rules')
def write_rules(body:site_rules.Rules,subject=Depends(owner)):
    return {'rules':site_rules.save(store,body),'defaults':site_rules.DEFAULTS}
import guest_profiles
import guest_activity as guest_activity_module
guest_activity = guest_activity_module.Activity(lambda: store)
app.state.guest_activity = guest_activity
guest_subject,_,_=guest_profiles.install(app,owner,lambda:store,sign_payload,token_payload,activity=guest_activity)
import title_shares
title_shares.install(app,owner,lambda:store,sign_payload,token_payload)


def activity_subject(authorization):
    try:
        payload = token_payload(authorization)
    except HTTPException:
        return None
    return payload['sub'] if payload.get('role') == 'guest' else None


from online_sessions import sessions as online_session_table
app.add_middleware(guest_activity_module.Middleware, activity=guest_activity, identify=activity_subject,
                   stream_owner=guest_activity_module.stream_owner(online_session_table, lambda: app.state.alloha_delivery))
import title_upscale_model
title_upscale_model.install(app)

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
    store.setting(destination, {"refresh_token": refresh, 'scope': tokens.get('scope', ''),'needs_consent':False,'checked_at':time.time()})
    if pending.get('device'):
        device = store.setting('device:' + pending['device'])
        if not device or device['sub'] != user['sub']:
            raise HTTPException(403, 'Устройство больше не зарегистрировано.')
        store.setting('device:' + pending['device'], {**device, 'ready': True, 'expires':None,'last_seen':time.time()})
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

@app.get('/metadata/anime-browse')
def anime_browse(kind:str='',value:str='',identity:str='',label:str='',page:int=1):
    from anime_browse import browse
    return browse(kind,value,identity,label,page)

@app.get('/metadata/anime-home')
def anime_home():
    from jikan_metadata import home_feed
    return home_feed()


@app.get('/metadata/jikan-data')
def jikan_data(request:Request,path:str='',q:str='',page:int=1,limit:int=16):
    from jikan_metadata import jikan_json
    return jikan_json(path,{**dict(request.query_params),'q':q,'page':page,'limit':limit})


@app.get("/metadata/{provider}")
def catalogue(provider: str, q: str = "", kind: str = "anime", page: int = 1, identity: str | None = None, year: int | None = None, part: str = '',genre:str='',tag:str=''):
    return metadata(provider, query=q, kind=kind, page=page, identity=identity, year=year, part=part,genre=genre,tag=tag)


@app.get('/artwork')
def artwork(url: str):
    from artwork import fetch_image
    data,mime=fetch_image(url)
    return Response(data,media_type=mime,headers={'Cache-Control':'public,max-age=86400','X-Content-Type-Options':'nosniff'})


@app.get("/sources/search")
def source_search(q: str, kind: str = "anime", subject=Depends(viewer)):
    if not 2 <= len(q.strip()) <= 160:
        raise HTTPException(422, "Укажи название от 2 до 160 символов.")
    if kind=='manga':
        from manga_sources import search_title
        return search_title({'kind':'manga','title':q.strip()})
    return search_sources(q.strip(), kind)


@app.get("/sources/availability")
def availability(q: str, subject=Depends(viewer)):
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
def source_inspect(body: Inspection, subject=Depends(viewer)):
    if body.kind not in {"anime", "movie", "tv", "manga", "ranobe"}:
        raise HTTPException(422, "Неизвестный тип произведения.")
    from kodik_api import cached_inspection
    direct=cached_inspection(body.dub_url or body.url,body.season)
    if direct and direct['kind']==body.kind:return direct
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
    language:str=Field(default='auto',pattern=r'^(auto|all|ru|uk|en|ja|ko)$')
    format:str=Field(default='all',pattern=r'^(all|manga|manhwa|manhua|webtoon)$')
    bridgeOffset:int=Field(default=0,ge=0,le=10000)
    bridgeLimit:int=Field(default=8,ge=1,le=16)

class MangaGlobalSearch(StrictBody):
    query:str=Field(min_length=2,max_length=160)
    language:str=Field(default='all',pattern=r'^(all|ru|uk|en|ja|ko)$')
    sourceIds:list[str]|None=Field(default=None,max_length=1000)
    refresh:bool=False
    title:dict|None=None

def manga_discovery_call(action,*args):
    from manga_discovery import SearchLimit,SearchMissing
    try:return action(*args)
    except SearchLimit as error:raise HTTPException(429,str(error)) from None
    except SearchMissing as error:raise HTTPException(404,str(error)) from None
    except ValueError as error:raise HTTPException(422,str(error)) from None

@app.get('/manga/catalog')
def manga_catalog(q:str='',tag:str='',provider:str='',format:str='',offset:int=0,limit:int=30,subject=Depends(owner)):
    from manga_discovery import manager
    from manga_catalog_index import browse
    store=manager()
    with store.lock:
        return browse(store.db,q=q,tag=tag,provider=provider,format=format,offset=offset,limit=limit)

@app.get('/manga/catalog/tags')
def manga_catalog_tags(provider:str='',sourceId:str='',limit:int=100,subject=Depends(owner)):
    from manga_discovery import manager
    from manga_catalog_index import tags
    store=manager()
    with store.lock:
        return tags(store.db,provider=provider,source_id=sourceId,limit=limit)

@app.get('/manga/catalog/stats')
def manga_catalog_stats(subject=Depends(owner)):
    from manga_discovery import manager
    from manga_catalog_index import stats
    store=manager()
    with store.lock:
        return stats(store.db)

class MangaCatalogBackfill(StrictBody):
    offset:int=Field(default=0,ge=0,le=50000)
    limit:int=Field(default=250,ge=1,le=500)

@app.post('/manga/catalog/backfill')
def manga_catalog_backfill(body:MangaCatalogBackfill,subject=Depends(owner)):
    from manga_discovery import manager
    from manga_catalog_index import backfill
    store=manager()
    with store.lock,store.db:
        return backfill(store.db,offset=body.offset,limit=body.limit)

class MangaCatalogEnrich(StrictBody):
    ids:list[str]=Field(default_factory=list,max_length=3)

@app.post('/manga/catalog/enrich')
def manga_catalog_enrich(body:MangaCatalogEnrich,subject=Depends(owner)):
    # Explicit bounded metadata check; no image bytes, bulk crawler or new
    # playback endpoint. A failure never changes the existing reader.
    from manga_discovery import manager
    from manga_catalog_index import title,missing_tags,upsert
    from manga_sources import site_for
    from manga_inspection import inspect
    store=manager()
    with store.lock:
        if body.ids:
            if any(not re.fullmatch(r'[a-f0-9]{32}',key) for key in body.ids):
                raise HTTPException(422,'Выбери известные записи каталога.')
            targets=[(key,(title(store.db,key) or {}).get('sourceUrl','')) for key in body.ids]
        else:
            targets=missing_tags(store.db,limit=2)
    result=[]
    for key,url in targets:
        if not url or not site_for(url) or site_for(url).family=='suwayomi':
            result.append({'id':key,'status':'unsupported'})
            continue
        try:
            detail=inspect(url)
            with store.lock,store.db:
                count=upsert(store.db,[detail])
            result.append({'id':key,'status':'indexed' if count else 'skipped',
                           'tags':len(detail.get('tags') or []),
                           'genres':len(detail.get('genres') or [])})
        except SourceError as error:
            result.append({'id':key,'status':'unavailable','reason':str(error)[:240]})
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Manga catalogue enrichment failed')
            result.append({'id':key,'status':'failed'})
    return {'items':result}

@app.get('/manga/catalog/{catalog_id}')
def manga_catalog_title(catalog_id:str,subject=Depends(owner)):
    from manga_discovery import manager
    from manga_catalog_index import title
    if not re.fullmatch(r'[a-f0-9]{32}',catalog_id):
        raise HTTPException(422,'Неверный идентификатор записи каталога.')
    store=manager()
    with store.lock:
        result=title(store.db,catalog_id)
    if result is None:
        raise HTTPException(404,'Произведение не найдено в индексе.')
    return result

@app.get('/manga/source-coverage')
def manga_source_coverage(subject=Depends(owner)):
    from manga_source_coverage import report
    return report()

@app.get('/discovery/manga/sources')
def discovery_manga_sources(language:str='all',q:str='',subject=Depends(viewer)):
    from manga_discovery import source_list
    return manga_discovery_call(source_list,language,q)

@app.post('/discovery/manga/search',status_code=202)
def discovery_manga_search(body:MangaGlobalSearch,subject=Depends(viewer)):
    from manga_discovery import manager
    return manga_discovery_call(manager().start,subject,body.query,body.language,body.sourceIds,body.refresh,body.title)

@app.get('/discovery/manga/search/{identity}')
def discovery_manga_status(identity:str,subject=Depends(viewer)):
    from manga_discovery import manager
    return manga_discovery_call(manager().status,subject,identity)

@app.delete('/discovery/manga/search/{identity}')
def discovery_manga_cancel(identity:str,subject=Depends(viewer)):
    from manga_discovery import manager
    return manga_discovery_call(manager().cancel,subject,identity)

@app.post('/manga/search')
def manga_search(body:MangaDiscovery,subject=Depends(viewer)):
    guest_may_open(subject,{**body.title,'kind':body.title.get('kind') or 'manga'})
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
    if language not in {'all','ru','uk','en','ja','ko'}:raise HTTPException(422,'Выбери язык источника.')
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
def manga_bridge_search(body:MangaDiscovery,subject=Depends(viewer)):
    from suwayomi_bridge import search
    guest_may_open(subject,{**body.title,'kind':body.title.get('kind') or 'manga'})
    return search(body.title,body.language,body.format,body.bridgeOffset,body.bridgeLimit)

class MangaInspection(StrictBody):
    url:str=Field(max_length=8192)
    title:dict|None=None
    verifyPages:bool=False
    refresh:bool=False

class RanobeSearch(StrictBody):
    title:dict
    language:str=Field(default='all',max_length=8)

class RanobeLink(StrictBody):
    url:str=Field(max_length=2048)
    title:dict|None=None

@app.post('/ranobe/search')
def ranobe_search(body:RanobeSearch,subject=Depends(viewer)):
    if len(json.dumps(body.title).encode())>50000:raise HTTPException(422,'Слишком большое описание тайтла.')
    guest_may_open(subject,{**body.title,'kind':'ranobe'})
    from ranobe_sources import search
    try:return search(body.title,body.language)
    except SourceError as error:raise HTTPException(422,str(error)) from None

@app.post('/ranobe/inspect')
def ranobe_inspect(body:RanobeLink,subject=Depends(viewer)):
    if body.title:guest_may_open(subject,{**body.title,'kind':'ranobe'})
    from ranobe_sources import inspect
    try:return inspect(body.url)
    except SourceError as error:raise HTTPException(422,str(error)) from None

@app.post('/ranobe/chapter')
def ranobe_chapter(body:RanobeLink,subject=Depends(viewer)):
    if body.title:guest_may_open(subject,{**body.title,'kind':'ranobe'})
    from ranobe_sources import chapter
    try:return chapter(body.url)
    except SourceError as error:raise HTTPException(422,str(error)) from None

@app.post('/manga/inspect')
def manga_inspect(body:MangaInspection,subject=Depends(viewer)):
    if body.title:guest_may_open(subject,{**body.title,'kind':body.title.get('kind') or 'manga'})
    from manga_sources import title_aliases
    from manga_inspection import inspect
    from title_identity import match_title
    value=inspect(body.url,refresh=body.refresh and not body.verifyPages)
    if body.title:
        if len(json.dumps(body.title).encode())>50000:raise HTTPException(422,'Слишком большое описание манги.')
        candidate={'title':value['title'],'aliases':list(dict.fromkeys([*title_aliases(value['title']),*(value.get('identityTitles') or value.get('aliases') or [])])),'kind':'manga','year':value.get('year'),'ids':value.get('ids') or {}}
        # Discovery permits an upstream English alias when the publication
        # year also agrees. Opening that verified source must apply the same
        # identity rule; missing/conflicting years retain canonical-only names.
        if body.title.get('year') and value.get('year') and str(body.title['year'])[:4]==str(value['year'])[:4]:
            candidate['aliases']=list(dict.fromkeys([*candidate['aliases'],*(value.get('aliases') or [])]))
        if body.title.get('kind')!='manga' or not match_title(body.title,candidate)[0]:raise HTTPException(422,'Источник относится к другому произведению. Выбери перевод нужной манги.')
    if not value.get('pages'):
        # A successful title inspection enriches the persistent catalogue.
        # Indexing failure must never break a working reader.
        try:
            from manga_discovery import manager as manga_catalog_manager
            from manga_catalog_index import upsert as catalog_upsert
            catalog=manga_catalog_manager()
            with catalog.lock,catalog.db:
                catalog_upsert(catalog.db,[value])
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Could not index manga source metadata')
    if body.verifyPages:
        from manga_readability import verify
        value={**value,**verify(value,body.refresh)}
        if value.get('readable') and value.get('provider','').startswith('suwayomi:'):
            from manga_source_health import record
            record(value['provider'].split(':',1)[1],value.get('providerName',''),value.get('language',''),'working','image')
        elif value.get('readable') and value.get('providerName') in {'MangaDex','MangaLib','HentaiLib'}:
            from suwayomi_bridge import sources
            from manga_source_health import record
            for source in sources():
                if source.get('name')==value['providerName'] and source.get('lang')==value.get('language'):record(source['id'],source['name'],source['lang'],'working','image')
    return value

@app.post('/manga/summary')
def manga_summary(body:MangaInspection,subject=Depends(viewer)):
    value=manga_inspect(body,subject)
    return {key:value.get(key) for key in ('provider','providerName','language','chapterCount','volumeCount','truncated','readable','readabilityError','verifiedPages','verifiedChapterUrl','pagesCheckedAt') if key in value}

@app.get('/discovery/manga/health')
def manga_source_health(subject=Depends(owner)):
    from manga_source_health import report
    from manga_discovery import manager
    # Search pauses after repeated failures, with their reasons (never removals).
    return {**report(),'searchPaused':manager().reachability()}


class QualityInspection(StrictBody):
    url: str = Field(max_length=8192)
    referer: str|None = Field(default=None,max_length=8192)


@app.post('/sources/qualities')
def source_qualities(body: QualityInspection, subject=Depends(viewer)):
    from source_quality import cached_qualities
    if body.referer:public_url(body.referer,resolve_dns=False)
    return cached_qualities(body.url,resolver_cache=getattr(app.state,'playback_resolver',None),subject=subject,**({'referer':body.referer} if body.referer else {}))


@app.post('/sources/discover')
def discover_voices(body: TitleDiscovery, subject=Depends(viewer)):
    from source_discovery import discover
    guest_may_open(subject, body.title)
    if len(json.dumps(body.title)) > 10000:
        raise HTTPException(422, 'Слишком большое описание тайтла.')
    try:
        return discover(body.title,refresh=body.refresh,continuing=body.continuing)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None

@app.get('/discovery/voices')
def discovery_voice_suggestions(q:str='',language:str='all',subject=Depends(viewer)):
    from source_discovery import voice_suggestions
    if len(q)>80:raise HTTPException(422,'Слишком длинный запрос озвучки.')
    return voice_suggestions(q,language=language)


@app.get('/sources/calendar')
def source_calendar(subject=Depends(viewer)):
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
    if not drive_grants.status(store,subject)["connected"]:
        raise HTTPException(409, "Подключи Google Drive к серверу один раз перед первым импортом.")
    try:
        task = store.add(subject, {"job": body.job, "vault_key": body.vault_key}, idempotency_key)
    except ValueError as error:
        raise HTTPException(429, str(error)) from None
    wakeup.set()
    return task


@app.get("/jobs")
def tasks(subject=Depends(owner)):
    return {"jobs": store.list(subject),"driveConnection":drive_grants.status(store,subject)}


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
    if not drive_grants.status(store,subject)['connected']:raise HTTPException(409,'Обнови фоновый доступ Google Drive на ВМ в профиле.')
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
    if not drive_grants.status(store,subject)['connected']:raise HTTPException(409,'Обнови фоновый доступ Google Drive на ВМ в профиле.')
    value = task(task_id, subject)
    if value["status"] not in {"failed", "waiting_auth"}:
        raise HTTPException(409, "Это задание сейчас нельзя продолжить.")
    private = store.get(task_id, subject, private=True)
    if not private["data"].get("vault_key"):
        raise HTTPException(409, "Открой библиотеку и запусти новое задание: завершённые серии будут пропущены.")
    store.update(task_id, status="queued", progress={"message": "", "sourceError": "", "phase": "queued",'cursor':0,'saved':0,'skipped':0,'failed':0,'recover_needed':True})
    wakeup.set()
    return task(task_id, subject)

from trailer_service import install as install_trailers
install_trailers(app, os.getenv("DATA_DIR", "/data"))

from reader_translation import install as install_reader_translation
install_reader_translation(app, os.getenv("DATA_DIR", "/data"), owner)
from anime_music import install as install_anime_music
install_anime_music(app)
from wtas_ost import install as install_wtas_ost
install_wtas_ost(app, os.getenv("DATA_DIR", "/data"))

from alloha_delivery import install as install_alloha
install_alloha(app)
from online_sessions import install as install_online
install_online(app,viewer,owner)
# HanimeTV refuses the Oracle address: its playlists go through the owner's Worker.
from hanime_relay import install as install_hanime_relay
install_hanime_relay()
from music_playback import install as install_music_playback
install_music_playback(app)
from music_audio import install as install_music_audio
install_music_audio(app,viewer)
from music_lyrics import LyricsRelay,install as install_music_lyrics
lyrics_relay=LyricsRelay()
install_music_lyrics(app,viewer,lyrics_relay)
from youtube_auth import install as install_youtube_auth
install_youtube_auth(app,owner,lambda:store)
from music_artists import install as install_music_artists
install_music_artists(app)

from title_background import install as install_title_background
install_title_background(app, os.getenv("DATA_DIR", "/data"))

from chapter_thumbnails import install as install_chapter_thumbnails
install_chapter_thumbnails(app, viewer)

from character_profile import install as install_character_profile
install_character_profile(app)
