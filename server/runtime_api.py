"""Owner-only API for a single private MediaVault VM. Run behind HTTPS."""
import base64
import hashlib
import os
import re
import threading
import time

from flask import Flask, jsonify, request
import requests
from google.oauth2.credentials import Credentials
from catalog_search import CatalogSearch
from run_import import validate_job
from runtime_store import Store
from source_parser import SourceError
from vault_drive import ADMIN_EMAIL_SHA256, GoogleDriveAdapter, VaultDrive


def runtime_store():
    return Store(os.environ.get('MEDIAVAULT_DATA', 'runtime-data'))


def drive_credentials(store):
    value = store.secret('google-oauth')
    if not value:
        raise ValueError('Сначала подключи Google Drive на сервере по инструкции настройки.')
    return Credentials.from_authorized_user_info(value, scopes=['https://www.googleapis.com/auth/drive'])


def open_vault(store):
    return VaultDrive(GoogleDriveAdapter.from_adc(drive_credentials(store)))


class OwnerAuth:
    def __init__(self, client_id, owner_hash):
        if not client_id:
            raise RuntimeError('MEDIAVAULT_CLIENT_ID is required')
        self.client_id, self.owner_hash = client_id, owner_hash
        self.cache, self.lock = {}, threading.Lock()

    def __call__(self, token):
        fingerprint = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            if self.cache.get(fingerprint, 0) > time.monotonic():
                return True
        try:
            # Fixed Google endpoints, no redirects, no access logs containing these URLs.
            info = requests.get('https://www.googleapis.com/oauth2/v1/tokeninfo',
                params={'access_token': token}, timeout=(5, 10), allow_redirects=False)
            info.raise_for_status()
            data = info.json()
            if data.get('audience') != self.client_id or int(data.get('expires_in', 0)) < 1:
                return False
            user = requests.get('https://www.googleapis.com/oauth2/v3/userinfo',
                headers={'Authorization': 'Bearer ' + token}, timeout=(5, 10), allow_redirects=False)
            user.raise_for_status()
            user = user.json()
            if user.get('email_verified') is not True:
                return False
            email_hash = hashlib.sha256(str(user.get('email', '')).strip().lower().encode()).hexdigest()
            if email_hash != self.owner_hash:
                return False
            with self.lock:
                if len(self.cache) > 100:
                    self.cache.clear()
                self.cache[fingerprint] = time.monotonic() + min(60, int(data['expires_in']))
            return True
        except (requests.RequestException, ValueError, TypeError):
            return False


def create_app(*, store=None, auth=None, catalog=None, vault_factory=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 32768
    store = store or runtime_store()
    auth = auth or OwnerAuth(os.environ.get('MEDIAVAULT_CLIENT_ID'), ADMIN_EMAIL_SHA256)
    catalog = catalog or CatalogSearch()
    vault_factory = vault_factory or (lambda: open_vault(store))
    allowed_origin = os.environ.get('MEDIAVAULT_ORIGIN', 'https://onikri.github.io')
    search_slots = threading.BoundedSemaphore(2)
    search_times, rate_lock = [], threading.Lock()

    @app.before_request
    def authorize():
        origin = request.headers.get('Origin')
        if origin and origin != allowed_origin:
            return jsonify(error='Этот сайт не разрешён.'), 403
        if request.method == 'OPTIONS':
            return '', 204
        if request.path == '/health':
            return None
        bearer = request.headers.get('Authorization', '')
        if not bearer.startswith('Bearer ') or len(bearer) > 4096 or not auth(bearer[7:]):
            return jsonify(error='Войди в аккаунт владельца и обнови доступ Google.'), 401

    @app.after_request
    def headers(response):
        if request.headers.get('Origin') == allowed_origin:
            response.headers['Access-Control-Allow-Origin'] = allowed_origin
            response.headers['Vary'] = 'Origin'
            response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.errorhandler(Exception)
    def error(cause):
        from werkzeug.exceptions import HTTPException
        if isinstance(cause, HTTPException):
            return jsonify(error='Некорректный запрос.'), cause.code
        if isinstance(cause, (ValueError, SourceError)):
            return jsonify(error=str(cause)), 400
        # Never expose requests exceptions, credential values, source signatures or tracebacks.
        return jsonify(error='Операция не выполнена. Проверь доступ сервера к Google Drive и свободное место.'), 503

    def library_id(value):
        if not isinstance(value, str) or not re.fullmatch(r'[\w-]{5,256}', value, flags=re.ASCII):
            raise ValueError('Некорректный ID библиотеки.')
        return value

    def body():
        value = request.get_json()
        if not isinstance(value, dict):
            raise ValueError('Нужен JSON-объект.')
        return value

    def limited_search(operation):
        with rate_lock:
            now = time.monotonic()
            search_times[:] = [stamp for stamp in search_times if stamp > now - 60]
            if len(search_times) >= 20:
                return jsonify(error='Слишком много запросов. Подожди минуту.'), 429
            search_times.append(now)
        if not search_slots.acquire(blocking=False):
            return jsonify(error='Поиск ещё выполняется. Подожди несколько секунд.'), 429
        try:
            return jsonify(operation())
        finally:
            search_slots.release()

    @app.get('/health')
    def health():
        return jsonify(ok=True)

    @app.get('/status')
    def status():
        library = library_id(request.args.get('library', ''))
        heartbeat = store.secret('worker-heartbeat') or 0
        return jsonify(drive_connected=bool(store.secret('google-oauth')),
                       library_connected=bool(store.secret('library:' + library)),
                       worker_online=time.time() - heartbeat < 90,
                       providers=[{'id': p['id'], 'name': p['name']} for p in catalog.providers])

    @app.get('/search')
    def search():
        return limited_search(lambda: catalog.search(request.args.get('q', '')))

    @app.get('/anime/<int:identifier>')
    def detail(identifier):
        return limited_search(lambda: catalog.detail(identifier))

    @app.post('/libraries/unlock')
    def unlock():
        value = body()
        library = library_id(value.get('library_id'))
        phrase = value.get('passphrase')
        if not isinstance(phrase, str) or not 12 <= len(phrase) <= 1024:
            raise ValueError('Введи секретную фразу библиотеки.')
        vault = vault_factory()
        try:
            try:
                vault.unlock(library, phrase)
            except Exception:
                raise ValueError('Не удалось открыть библиотеку: проверь фразу, ID и аккаунт сервера.') from None
            # Persist only the derived key. The VM's master key protects this record at rest.
            store.put_secret('library:' + library, base64.b64encode(vault._key).decode())
            return jsonify(connected=True)
        finally:
            vault.close()

    @app.delete('/libraries/<library>')
    def disconnect(library):
        library_id(library)
        if any(job['status'] in ('queued', 'running') for job in store.jobs(library)):
            raise ValueError('Сначала останови задания и дождись завершения текущей операции.')
        store.delete_secret('library:' + library)
        return jsonify(connected=False)

    @app.get('/jobs')
    def jobs():
        return jsonify(jobs=store.jobs(library_id(request.args.get('library', ''))))

    @app.post('/jobs')
    def enqueue():
        value = body()
        job = value.get('job')
        validate_job(job)
        if not store.secret('google-oauth') or not store.secret('library:' + job['library_id']):
            raise ValueError('Сначала подключи Drive и библиотеку на сервере.')
        heartbeat = store.secret('worker-heartbeat') or 0
        if time.time() - heartbeat >= 90:
            return jsonify(error='Обработчик не запущен. Проверь службу mediavault-worker на VM.'), 503
        request_id = value.get('request_id', '')
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}', request_id):
            raise ValueError('Некорректный идентификатор задания.')
        return jsonify(id=store.enqueue(job, request_id)), 202

    @app.post('/jobs/<identifier>/cancel')
    def cancel(identifier):
        if not store.cancel(identifier):
            return jsonify(error='Задание не найдено.'), 404
        return jsonify(cancel_requested=True)

    return app
