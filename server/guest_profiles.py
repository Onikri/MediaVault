"""Owner-issued guest profiles.

The owner creates a profile (name + lifetime) and hands out a one-time invite
link. The guest opens it, chooses a login and password, and can sign in again
later. Guest sessions only reach viewing endpoints (see ``viewer`` in api.py);
every request re-checks the profile, so revoking or expiring it is immediate.
Passwords are stored as scrypt hashes inside the sealed settings table.
"""
import hashlib
import hmac
import re
import secrets
import threading
import time
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

INVITE_SECONDS = 7 * 86400
SESSION_SECONDS = 30 * 86400
LOGIN = re.compile(r'^[a-z0-9][a-z0-9._-]{2,31}$')
INDEX = 'guests:index'


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)


class Create(Strict):
    name: str = Field(min_length=1, max_length=40)
    days: Optional[int] = Field(default=None, ge=1, le=3650)


class AccessTitle(Strict):
    key: str = Field(pattern=r'^(anime|manga):\d{1,9}$')
    title: str = Field(default='', max_length=300)
    cover: str = Field(default='', max_length=600)


class Access(Strict):
    scope: str = Field(default='all', pattern=r'^(all|titles)$')
    watch: bool = True
    read: bool = True
    titles: list[AccessTitle] = Field(default_factory=list, max_length=500)


class Change(Strict):
    access: Optional[Access] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=40)
    days: Optional[int] = Field(default=None, ge=1, le=3650)
    unlimited: bool = False
    disabled: Optional[bool] = None


class Enroll(Strict):
    invite: str = Field(min_length=20, max_length=80)
    login: str = Field(min_length=3, max_length=32)
    password: SecretStr
    name: Optional[str] = Field(default=None, min_length=1, max_length=40)


class Login(Strict):
    login: str = Field(min_length=1, max_length=64)
    password: SecretStr


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return salt.hex(), value.hex()


def check_password(password, record):
    try:
        _, value = hash_password(password, bytes.fromhex(record['salt']))
        return hmac.compare_digest(value, record['password'])
    except (KeyError, ValueError, TypeError):
        return False


WATCH_KINDS = {'anime', 'movie', 'tv', 'ona', 'ova', 'special'}
READ_KINDS = {'manga', 'ranobe', 'book', 'manhwa', 'manhua', 'novel', 'one_shot', 'doujin'}
FULL_ACCESS = {'scope': 'all', 'watch': True, 'read': True, 'titles': []}


def access_of(record):
    value = (record or {}).get('access')
    return {**FULL_ACCESS, **value} if isinstance(value, dict) else dict(FULL_ACCESS)


def title_group(kind):
    kind = str(kind or 'anime').lower()
    return 'manga' if kind in READ_KINDS else 'anime'


def allows(record, title):
    """Whether a guest may open this catalogue title (dict with kind and ids)."""
    access = access_of(record)
    group = title_group((title or {}).get('kind'))
    if not access['watch' if group == 'anime' else 'read']:
        return False
    if access['scope'] == 'all':
        return True
    ids = (title or {}).get('ids') or {}
    mal = str(ids.get('mal') or '').strip()
    return bool(mal) and (group + ':' + mal) in {t.get('key') for t in access['titles']}


def public(record, now=None):
    now = now or time.time()
    expires = record.get('expires_at')
    return {'id': record['id'], 'name': record['name'], 'login': record.get('login') or '',
            'createdAt': record['created_at'], 'expiresAt': expires, 'disabled': bool(record.get('disabled')),
            'expired': bool(expires and expires < now), 'enrolled': bool(record.get('password')),
            'inviteExpiresAt': record.get('invite_expires_at') if record.get('invite_hash') else None,
            'lastSeen': record.get('last_seen'), 'access': access_of(record)}


class Attempts:
    """Small in-memory brake for password guessing (per address and per login)."""

    def __init__(self, limit=8, window=600):
        self.limit, self.window, self.values, self.lock = limit, window, {}, threading.Lock()

    def check(self, *keys):
        now = time.monotonic()
        with self.lock:
            for key in keys:
                start, count = self.values.get(key, (now, 0))
                if now - start > self.window:
                    self.values.pop(key, None)
                elif count >= self.limit:
                    raise HTTPException(429, 'Слишком много попыток входа. Повтори через несколько минут.')

    def fail(self, *keys):
        now = time.monotonic()
        with self.lock:
            if len(self.values) > 4096:
                self.values.clear()
            for key in keys:
                start, count = self.values.get(key, (now, 0))
                self.values[key] = (start, count + 1) if now - start <= self.window else (now, 1)

    def clear(self, *keys):
        with self.lock:
            for key in keys:
                self.values.pop(key, None)


def install(app, owner, get_store, sign, decode, activity=None):
    attempts = Attempts()
    from guest_activity import request_address

    def note(identity, action, request=None, detail=''):
        if activity is not None and identity:
            activity.event(identity, action, detail=detail, address=request_address(request) if request is not None else None, force=True)

    def store():
        return get_store()

    def load(identity):
        return store().setting('guest:' + identity)

    def save(record):
        store().setting('guest:' + record['id'], record)
        return record

    def ids():
        return list((store().setting(INDEX) or {}).get('ids') or [])

    def lifetime(days):
        return int(time.time() + days * 86400) if days else None

    def issue_invite(record):
        token = secrets.token_urlsafe(32)
        if record.get('invite_hash'):
            store().consume('guest-invite:' + record['invite_hash'])
        record['invite_hash'] = digest(token)
        record['invite_expires_at'] = int(time.time() + INVITE_SECONDS)
        store().setting('guest-invite:' + record['invite_hash'], {'id': record['id'], 'expires': record['invite_expires_at']})
        return token

    def active(record):
        if not record or record.get('disabled'):
            raise HTTPException(401, 'Гостевой доступ закрыт владельцем.')
        if record.get('expires_at') and record['expires_at'] < time.time():
            raise HTTPException(401, 'Срок гостевого доступа истёк. Попроси владельца продлить его.')
        return record

    def session(record):
        expires = int(time.time() + SESSION_SECONDS)
        if record.get('expires_at'):
            expires = min(expires, int(record['expires_at']))
        token = sign({'sub': 'guest:' + record['id'], 'role': 'guest', 'exp': expires, 'nonce': secrets.token_urlsafe(12),
                      'v': record.get('session_version', 1)})
        return {'token': token, 'expiresAt': expires, 'guest': public(record), 'driveConnected': False, 'role': 'guest'}

    def guest_subject(authorization: str = Header(default='')):
        payload = decode(authorization)
        if payload.get('role') != 'guest' or not str(payload.get('sub', '')).startswith('guest:'):
            raise HTTPException(403, 'Это действие доступно только гостевому профилю.')
        record = active(load(payload['sub'][6:]))
        if payload.get('v', 1) != record.get('session_version', 1):
            raise HTTPException(401, 'Вход по этому профилю был сброшен. Войди заново.')
        if time.time() - float(record.get('last_seen') or 0) > 300:
            record['last_seen'] = int(time.time())
            save(record)
        return record

    def resolve_invite(token):
        invite = store().setting('guest-invite:' + digest(token))
        if not invite or invite.get('expires', 0) < time.time():
            raise HTTPException(404, 'Приглашение недействительно или уже использовано.')
        record = load(invite['id'])
        if not record or record.get('invite_hash') != digest(token):
            raise HTTPException(404, 'Приглашение недействительно или уже использовано.')
        return active(record)

    # ---- Guest side -------------------------------------------------------
    @app.get('/guests/invite/{token}')
    def invite_preview(token: str):
        if not 20 <= len(token) <= 80:
            raise HTTPException(404, 'Приглашение недействительно или уже использовано.')
        record = resolve_invite(token)
        return {'name': record['name'], 'expiresAt': record.get('expires_at'), 'login': record.get('login') or '',
                'reset': bool(record.get('password')), 'inviteExpiresAt': record.get('invite_expires_at')}

    @app.post('/guests/enroll')
    def enroll(body: Enroll, request: Request):
        address = 'ip:' + (request_address(request) or '?')
        attempts.check(address)
        login = body.login.strip().lower()
        password = body.password.get_secret_value()
        if not LOGIN.fullmatch(login):
            raise HTTPException(422, 'Логин: 3–32 латинские буквы, цифры, точка, дефис или подчёркивание.')
        if not 8 <= len(password) <= 128:
            raise HTTPException(422, 'Пароль должен быть от 8 до 128 символов.')
        with store().lock:
            try:
                record = resolve_invite(body.invite)
            except HTTPException:
                attempts.fail(address)
                raise
            taken = store().setting('guest-login:' + login)
            if taken and taken.get('id') != record['id']:
                raise HTTPException(409, 'Этот логин уже занят. Выбери другой.')
            if record.get('login') and record['login'] != login:
                store().consume('guest-login:' + record['login'])
            record['salt'], record['password'] = hash_password(password)
            record['login'] = login
            if body.name:
                record['name'] = body.name.strip()
            record['enrolled_at'] = int(time.time())
            record['session_version'] = int(record.get('session_version', 1)) + 1
            store().consume('guest-invite:' + record.pop('invite_hash'))
            record.pop('invite_expires_at', None)
            store().setting('guest-login:' + login, {'id': record['id']})
            save(record)
        note(record['id'], 'Сменил пароль по ссылке' if record.get('session_version', 2) > 2 else 'Зарегистрировался', request, 'логин ' + login)
        return session(record)

    @app.post('/guests/login')
    def login(body: Login, request: Request):
        name = body.login.strip().lower()
        address, account = 'ip:' + (request_address(request) or '?'), 'login:' + name
        attempts.check(address, account)
        pointer = store().setting('guest-login:' + name) if LOGIN.fullmatch(name) else None
        record = load(pointer['id']) if pointer else None
        if not record or not check_password(body.password.get_secret_value(), record):
            attempts.fail(address, account)
            if record:
                note(record['id'], 'Неверный пароль', request)
            raise HTTPException(401, 'Неверный логин или пароль.')
        attempts.clear(account)
        try:
            active(record)
        except HTTPException as error:
            note(record['id'], 'Вход отклонён', request, error.detail)
            raise
        note(record['id'], 'Вошёл в профиль', request)
        return session(record)

    @app.get('/guests/me')
    def me(record=Depends(guest_subject)):
        return {'guest': public(record)}

    # ---- Owner management -------------------------------------------------
    @app.get('/guests/activity')
    def activity_overview(subject=Depends(owner)):
        if activity is None:
            return {'guests': {}}
        return {'guests': {identity: activity.summary(identity) for identity in ids()}}

    @app.get('/guests/{identity}/activity')
    def activity_report(identity: str, subject=Depends(owner)):
        record = load(identity)
        if not record or activity is None:
            raise HTTPException(404, 'Гостевой профиль не найден.')
        return {'guest': public(record), **activity.report(identity)}

    @app.delete('/guests/{identity}/activity')
    def activity_clear(identity: str, subject=Depends(owner)):
        if not load(identity) or activity is None:
            raise HTTPException(404, 'Гостевой профиль не найден.')
        activity.forget(identity)
        return {'cleared': True}

    @app.get('/guests')
    def list_guests(subject=Depends(owner)):
        now = time.time()
        rows = [public(r, now) for r in (load(i) for i in ids()) if r]
        return {'guests': sorted(rows, key=lambda r: -r['createdAt'])}

    @app.post('/guests', status_code=201)
    def create(body: Create, subject=Depends(owner)):
        with store().lock:
            present = ids()
            if len(present) >= 50:
                raise HTTPException(429, 'Слишком много гостевых профилей. Удали ненужные.')
            identity = secrets.token_hex(8)
            record = {'id': identity, 'name': body.name.strip(), 'created_at': int(time.time()), 'expires_at': lifetime(body.days),
                      'disabled': False, 'session_version': 1}
            invite = issue_invite(record)
            save(record)
            store().setting(INDEX, {'ids': [identity, *present]})
        return {'guest': public(record), 'invite': invite}

    @app.post('/guests/{identity}')
    def change(identity: str, body: Change, subject=Depends(owner)):
        record = load(identity)
        if not record:
            raise HTTPException(404, 'Гостевой профиль не найден.')
        if body.name is not None:
            record['name'] = body.name.strip()
        if body.unlimited:
            record['expires_at'] = None
        elif body.days is not None:
            record['expires_at'] = lifetime(body.days)
        if body.disabled is not None:
            record['disabled'] = body.disabled
        if body.access is not None:
            record['access'] = body.access.model_dump()
        return {'guest': public(save(record))}

    @app.post('/guests/{identity}/invite')
    def reinvite(identity: str, subject=Depends(owner)):
        record = load(identity)
        if not record:
            raise HTTPException(404, 'Гостевой профиль не найден.')
        invite = issue_invite(record)
        return {'guest': public(save(record)), 'invite': invite}

    @app.post('/guests/{identity}/sessions/reset')
    def reset_sessions(identity: str, subject=Depends(owner)):
        record = load(identity)
        if not record:
            raise HTTPException(404, 'Гостевой профиль не найден.')
        record['session_version'] = int(record.get('session_version', 1)) + 1
        return {'guest': public(save(record))}

    @app.delete('/guests/{identity}')
    def remove(identity: str, subject=Depends(owner)):
        with store().lock:
            record = store().consume('guest:' + identity)
            if record:
                if record.get('login'):
                    store().consume('guest-login:' + record['login'])
                if record.get('invite_hash'):
                    store().consume('guest-invite:' + record['invite_hash'])
            store().setting(INDEX, {'ids': [i for i in ids() if i != identity]})
        if activity is not None:
            activity.forget(identity)
        return {'removed': bool(record)}

    return guest_subject, active, load
