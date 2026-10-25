"""Opt-in remembered devices: browser holds a non-exportable signing key.

Google refresh tokens stay encrypted on this server. Restoring a session needs
a fresh one-use signed challenge, not a Google token saved in a JS cookie.
"""
import base64
import hashlib
import json
import secrets
import time

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives import hashes
from fastapi import Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field


def unb64(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)


class Registration(Strict):
    public_key: dict


class Device(Strict):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{32,100}$')


class Proof(Device):
    nonce: str = Field(pattern=r'^[A-Za-z0-9_-]{32,100}$')
    signature: str = Field(min_length=80, max_length=100)


def install(app, api):
    def public_key(jwk):
        if jwk.get('kty') != 'EC' or jwk.get('crv') != 'P-256' or len(jwk.get('x', '')) != 43 or len(jwk.get('y', '')) != 43:
            raise ValueError()
        return ec.EllipticCurvePublicNumbers(int.from_bytes(unb64(jwk['x']), 'big'), int.from_bytes(unb64(jwk['y']), 'big'), ec.SECP256R1()).public_key()

    def device(identity):
        value = api.store.setting('device:' + identity)
        if not value or value.get('expires', 0) < time.time():
            raise HTTPException(401, 'Срок запоминания устройства истёк. Войди через Google один раз.')
        return value

    def verify(proof):
        value = device(proof.id)
        with api.store.lock:
            pending=api.store.setting('device-challenge:'+proof.id) or {'values':[]}
            digest=hashlib.sha256(proof.nonce.encode()).hexdigest()
            challenge=next((v for v in pending['values'] if v['hash']==digest),None)
            api.store.setting('device-challenge:'+proof.id,{'values':[v for v in pending['values'] if v['hash']!=digest]})
        try:
            if not challenge or challenge['expires'] < time.time() or challenge['hash'] != hashlib.sha256(proof.nonce.encode()).hexdigest():
                raise ValueError()
            signature = unb64(proof.signature)
            if len(signature) != 64:
                raise ValueError()
            der = encode_dss_signature(int.from_bytes(signature[:32], 'big'), int.from_bytes(signature[32:], 'big'))
            public_key(value['key']).verify(der, ('MediaVault device session\n' + proof.id + '\n' + proof.nonce).encode(), ec.ECDSA(hashes.SHA256()))
        except Exception:
            raise HTTPException(401, 'Устройство не подтвердило вход. Повтори подключение.') from None
        return value

    @app.post('/devices/register')
    def register(body: Registration, authorization: str = Header(default='')):
        if not authorization.startswith('Bearer '):
            raise HTTPException(401, 'Сначала войди через Google.')
        user = api.google_identity(authorization[7:])
        try:
            public_key(body.public_key)
        except (ValueError, KeyError, TypeError):
            raise HTTPException(422, 'Некорректный ключ устройства.') from None
        identity = secrets.token_urlsafe(32)
        admin = hashlib.sha256(user['email'].strip().lower().encode()).hexdigest() == api.ADMIN_EMAIL_SHA256
        ready = admin and bool(api.store.setting('google:' + user['sub']))
        with api.store.lock:
            identities=api.store.setting('device-index:'+user['sub']) or {'ids':[]}
            active=[i for i in identities['ids'] if (api.store.setting('device:'+i) or {}).get('expires',0)>time.time()]
            if len(active)>=10:raise HTTPException(429,'У аккаунта уже 10 запомненных устройств. Удали ненужное устройство перед добавлением нового.')
            api.store.setting('device:' + identity, {'key': {k: body.public_key[k] for k in ('kty','crv','x','y')}, 'sub': user['sub'], 'admin': admin,
                                                  'expires': time.time() + (90 * 86400 if ready else 600), 'ready': ready})
            api.store.setting('device-index:'+user['sub'],{'ids':[*active,identity]})
        result = {'id': identity, 'ready': ready}
        if not ready:
            result['url'] = api.oauth_url(user['sub'], device_id=identity, readonly=not admin)
        return result

    @app.post('/devices/challenge')
    def challenge(body: Device):
        device(body.id)
        nonce = secrets.token_urlsafe(32)
        with api.store.lock:
            pending=api.store.setting('device-challenge:'+body.id) or {'values':[]}
            values=[v for v in pending['values'] if v['expires']>time.time()][-3:]
            api.store.setting('device-challenge:'+body.id,{'values':[*values,{'expires':time.time()+60,'hash':hashlib.sha256(nonce.encode()).hexdigest()}]})
        return {'nonce': nonce}

    @app.post('/devices/restore')
    def restore(body: Proof):
        value = verify(body)
        if not value.get('ready'):
            raise HTTPException(401, 'Заверши разрешение Google для запоминания устройства.')
        saved = api.store.setting('device-google:' + body.id) or (api.store.setting('google:' + value['sub']) if value.get('admin') else None)
        if not saved:
            raise HTTPException(401, 'Нужно однократно разрешить Google запомнить вход.')
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        credentials = Credentials(token=None, refresh_token=saved['refresh_token'], token_uri='https://oauth2.googleapis.com/token',
                                  client_id=api.CLIENT_ID, client_secret=api.client_secret())
        try:
            transport = Request()
            credentials.refresh(lambda *args, **kwargs: transport(*args, **{**kwargs, 'timeout': 12}))
            user = api.google_identity(credentials.token)
            if user['sub'] != value['sub']:
                raise ValueError()
        except Exception:
            raise HTTPException(401, 'Google отозвал сохранённый вход. Подключи аккаунт ещё раз.') from None
        scopes = saved.get('scope') or ('openid email profile https://www.googleapis.com/auth/drive' if value.get('admin') else 'openid email profile https://www.googleapis.com/auth/drive.readonly')
        return {'access_token': credentials.token, 'expires_in': 3500, 'scope': scopes, 'user': user}

    @app.post('/devices/remove')
    def remove(body: Proof):
        verify(body)
        api.store.consume('device:' + body.id)
        api.store.consume('device-google:' + body.id)
        return {'removed': True}
