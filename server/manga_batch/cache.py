"""Encrypted JSON only: persistent SQLite + optional bounded Redis hot cache."""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class JsonCache:
    def __init__(self, directory, redis=None):
        self.root=Path(directory);self.root.mkdir(exist_ok=True,parents=True,mode=0o700);self.root.chmod(0o700)
        file=self.root/'json-cache.key'
        try:fd=os.open(file,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError:pass
        else:
            with os.fdopen(fd,'wb') as out:out.write(os.urandom(32))
        self.cipher=AESGCM(file.read_bytes());self.lock=threading.Lock();self.redis=redis
        self.db=sqlite3.connect(self.root/'translations.sqlite',check_same_thread=False)
        with self.db:self.db.executescript('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS pages (key TEXT PRIMARY KEY, scope TEXT NOT NULL, value BLOB NOT NULL, updated REAL NOT NULL);')
        (self.root/'translations.sqlite').chmod(0o600)

    @staticmethod
    def identity(scope, manifest, page, policy):
        raw=json.dumps([scope,manifest,page,policy],sort_keys=True,separators=(',',':')).encode()
        return hashlib.sha256(raw).hexdigest()

    def _get(self,key,scope):
        with self.lock:row=self.db.execute('SELECT value FROM pages WHERE key=? AND scope=?',(key,scope)).fetchone()
        return row[0] if row else None

    async def get(self,key,scope):
        raw=None
        if self.redis:
            try:raw=await self.redis.get('manga:json:'+key)
            except Exception:self.redis=None
        if raw is None:raw=await asyncio.to_thread(self._get,key,scope)
        if raw is None:return None
        try:return json.loads(self.cipher.decrypt(raw[:12],raw[12:],(scope+':'+key).encode()))
        except Exception:return None

    def _put(self,key,scope,raw):
        with self.lock,self.db:self.db.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?,?)',(key,scope,raw,time.time()))

    async def put(self,key,scope,value):
        # Never persist image bytes, partial translations or model exceptions.
        if any(k in value for k in ['image','renderedImage','somImage']):raise ValueError('JSON cache cannot store page images')
        nonce=os.urandom(12);plain=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
        raw=nonce+self.cipher.encrypt(nonce,plain,(scope+':'+key).encode())
        await asyncio.to_thread(self._put,key,scope,raw)
        if self.redis:
            try:
                await self.redis.set('manga:json:'+key,raw,ex=21600)
                await self.redis.publish('manga:ready:'+key,'ready')
            except Exception:self.redis=None

    async def close(self):
        await asyncio.to_thread(self.db.close)
