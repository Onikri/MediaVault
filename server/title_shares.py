"""Revocable title links with a playback-only, source-scoped session."""
import hashlib
import re
import secrets
import time
from typing import Literal

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from source_parser import SourceError, public_url

PREFIX = 'title-share:'


class Entry(BaseModel):
    model_config = ConfigDict(extra='ignore')
    url: str = Field(max_length=8192)
    number: float = Field(ge=0, le=100000)
    season: int = Field(default=1, ge=1, le=1000)
    title: str = Field(default='', max_length=500)

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        try:
            return public_url(value, resolve_dns=False)
        except SourceError as error:
            raise ValueError(str(error)) from None


class Title(BaseModel):
    model_config = ConfigDict(extra='ignore')
    name: str = Field(min_length=1, max_length=500)
    cover: str = Field(default='', max_length=8192)
    description: str = Field(default='', max_length=16000)
    year: int | None = None
    ids: dict = Field(default_factory=dict)


class Create(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: Title
    kind: Literal['video', 'manga']
    entries: list[Entry] = Field(min_length=1, max_length=500)
    initial: int = Field(default=0, ge=0, le=499)
    referer: str | None = Field(default=None, max_length=8192)
    dub: str = Field(default='', max_length=180)
    language: str = Field(default='ru', max_length=20)
    quality: str = Field(default='best', pattern=r'^(best|[1-9][0-9]{1,3})$')
    translate: bool = False
    translation: dict = Field(default_factory=dict)

    @field_validator('referer')
    @classmethod
    def valid_referer(cls,value):
        return Entry.valid_url(value) if value else None


class TitleShares:
    def __init__(self, get_store, sign, decode):
        self.store, self.sign, self.decode = get_store, sign, decode

    def record(self, identity):
        row = self.store().setting(PREFIX + identity)
        if not row or row.get('revoked'):
            raise HTTPException(410, 'Владелец закрыл ссылку на этот тайтл.')
        return row

    def subject(self, authorization, request):
        payload = self.decode(authorization)
        subject = payload.get('sub', '')
        if payload.get('role') != 'share' or not subject.startswith('share:'):
            raise HTTPException(403, 'Нужна ссылка на тайтл.')
        row = self.record(subject[6:])
        path = request.url.path
        allowed = (
            request.method == 'POST' and path == '/online/prepare'
            or request.method == 'DELETE' and re.fullmatch(r'/online/[A-Za-z0-9_-]{20,100}', path)
            or request.method == 'POST' and re.fullmatch(r'/online/[A-Za-z0-9_-]{20,100}/(?:heartbeat|playback)', path)
            or request.method == 'GET' and re.fullmatch(r'/online/[A-Za-z0-9_-]{20,100}/[A-Za-z0-9_-]+', path)
            or request.method == 'GET' and path == '/reader/google/keys' and row['translate']
            or request.method == 'POST' and path == '/reader/google/generate' and row['translate']
        )
        if not allowed:
            raise HTTPException(403, 'По этой ссылке доступен только выбранный тайтл.')
        return subject

    def authorize_source(self, subject, body):
        if not str(subject).startswith('share:'):
            return
        row = self.record(subject[6:])
        if body.kind != row['kind'] or body.url not in {e['url'] for e in row['entries']}:
            raise HTTPException(403, 'Эта серия или глава не открыта по ссылке.')
        body.referer = row.get('referer')

    def create(self, owner, body):
        if body.initial >= len(body.entries):
            raise HTTPException(422, 'Выбери опубликованную серию или главу.')
        token = secrets.token_urlsafe(32)
        identity = hashlib.sha256(token.encode()).hexdigest()
        value = body.model_dump()
        value['referer'] = public_url(body.referer, resolve_dns=False) if body.referer else None
        # Keep only rendering/model preferences. Credentials never enter a link.
        fields = {'language', 'directModel', 'directInput', 'font', 'inpaint', 'directDetector', 'directBatchPages'}
        value['translation'] = {k: v for k, v in body.translation.items()
                                if k in fields and isinstance(v, (str, int, bool)) and len(str(v)) < 100}
        value['translate'] = body.kind == 'manga' and body.translate
        self.store().setting(PREFIX + identity, {**value, 'owner': owner, 'created': time.time()})
        return {'id': identity, 'token': token}

    def open(self, token):
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            raise HTTPException(404, 'Ссылка на тайтл не найдена.')
        identity = hashlib.sha256(token.encode()).hexdigest()
        row = self.record(identity)
        expires = int(time.time()) + 86400
        public = {k: v for k, v in row.items() if k not in {'owner', 'created', 'revoked'}}
        return {**public, 'id': identity, 'expiresAt': expires,
                'token': self.sign({'sub': 'share:' + identity, 'role': 'share', 'exp': expires})}


def install(app, owner, get_store, sign, decode):
    shares = TitleShares(get_store, sign, decode)
    app.state.title_shares = shares

    @app.post('/shares/title', status_code=201)
    def create(body: Create, subject=Depends(owner)):
        return shares.create(subject, body)

    @app.get('/shares/title/{token}')
    def open_share(token: str):
        return shares.open(token)

    @app.delete('/shares/title/{identity}')
    def revoke(identity: str, subject=Depends(owner)):
        if not re.fullmatch(r'[a-f0-9]{64}', identity):
            raise HTTPException(404, 'Ссылка не найдена.')
        with get_store().lock:
            row = shares.record(identity)
            if row['owner'] != subject:
                raise HTTPException(404, 'Ссылка не найдена.')
            get_store().setting(PREFIX + identity, {**row, 'revoked': True})
        return {'revoked': True}

    return shares
