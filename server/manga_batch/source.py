"""Read-only importer credentials + bounded RAM-only, authenticated CBZ access.

Never construct TaskStore here: its startup recovery mutates the import queue.
The derived vault key lives only in an expiring session, not the translation DB.
"""
from __future__ import annotations
import base64, hashlib, hmac, io, json, os, re, secrets, sqlite3, threading, time, zipfile
from collections import OrderedDict
from concurrent.futures import Future
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from vault_drive import CHUNK_SIZE, GoogleDriveAdapter, VaultDrive, open_chunk

IMAGE = re.compile(r'\.(png|jpe?g|webp|avif)$', re.I)

def manifest(item, names):
    raw=[item['id'],item['size'],[[c['fileId'],c['iv']] for c in item['chunks']],names]
    return hashlib.sha256(json.dumps(raw,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

class ReadOnlySettings:
    def __init__(self, directory): self.root=Path(directory)
    def key(self): return (self.root/'service.key').read_bytes()
    def setting(self, name):
        with sqlite3.connect((self.root/'tasks.sqlite').as_uri()+'?mode=ro',uri=True) as db:
            row=db.execute('SELECT value FROM settings WHERE name=?',(name,)).fetchone()
        if not row:return None
        raw=row[0];return json.loads(AESGCM(self.key()).decrypt(raw[:12],raw[12:],name.encode()))
    def owner(self, token):
        try:
            body,signature=token.split('.')
            expected=base64.urlsafe_b64encode(hmac.digest(self.key(),body.encode(),'sha256')).rstrip(b'=').decode()
            if not hmac.compare_digest(expected,signature):raise ValueError()
            data=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
            if data['exp']<=time.time() or not isinstance(data['sub'],str):raise ValueError()
            return data['sub']
        except (ValueError,KeyError,TypeError):raise PermissionError('Войди в профиль владельца ВМ.')
    def drive(self,subject):
        from google.oauth2.credentials import Credentials
        token=self.setting('google:'+subject);config=self.setting('configuration:google-oauth') or {}
        if not token or not token.get('refresh_token'):raise ValueError('Подключи фоновый доступ ВМ к Drive.')
        secret=config.get('client_secret') or os.getenv('GOOGLE_CLIENT_SECRET','')
        if not secret:raise ValueError('На ВМ не найден OAuth-клиент Drive.')
        credentials=Credentials(token=None,refresh_token=token['refresh_token'],token_uri='https://oauth2.googleapis.com/token',client_id=os.getenv('GOOGLE_CLIENT_ID','262576202069-9gcrr64crhdubh2drhsspsnq9c0rtfri.apps.googleusercontent.com'),client_secret=secret,scopes=['https://www.googleapis.com/auth/drive'])
        return GoogleDriveAdapter.from_adc(credentials)

class Archive:
    def __init__(self, drive, key, item):
        self.drive=drive;self.key=key;self.item=item;self.chunks=OrderedDict();self.flights={};self.lock=threading.RLock();self.leases=0;self.closed=False
        if not 22<=item['size']<=8*1024**3 or len(item['chunks'])!=(item['size']+CHUNK_SIZE-1)//CHUNK_SIZE:raise ValueError('Некорректный архив главы.')
    def chunk(self,index):
        with self.lock:
            if index in self.chunks:
                self.chunks.move_to_end(index);return self.chunks[index]
            flight=self.flights.get(index);leader=flight is None
            if leader:flight=Future();self.flights[index]=flight
        if not leader:return flight.result(timeout=60)
        try:
            c=self.item['chunks'][index];raw=open_chunk(self.drive.download(c['fileId']),self.key,self.item['id'],index,c['iv'])
            expected=min(CHUNK_SIZE,self.item['size']-index*CHUNK_SIZE)
            if len(raw)!=expected:raise ValueError('Размер части архива изменился.')
            with self.lock:
                self.chunks[index]=raw;self.chunks.move_to_end(index)
                while len(self.chunks)>4:self.chunks.popitem(last=False)
            flight.set_result(raw);return raw
        except BaseException as e:flight.set_exception(e);raise
        finally:
            with self.lock:self.flights.pop(index,None)
    def reader(self):return RangeReader(self)
    def names(self):
        with zipfile.ZipFile(self.reader()) as z:
            names=[i.filename for i in z.infolist() if not i.is_dir() and IMAGE.search(i.filename) and not i.filename.startswith('__MACOSX/')]
            if not 1<=len(names)<=1500 or len(names)!=len(set(names)):raise ValueError('Некорректный список страниц CBZ.')
            return names
    def page(self,name):
        with zipfile.ZipFile(self.reader()) as z:
            info=z.getinfo(name)
            if info.file_size>10*1024**2 or info.flag_bits&1:raise ValueError('Страница превышает лимит 10 МиБ или защищена ZIP-паролем.')
            return z.read(info)
    def acquire(self):
        with self.lock:self.leases+=1
    def release(self):
        with self.lock:
            self.leases-=1
            if self.closed and self.leases==0:self.key=None;self.chunks.clear()
    def close(self):
        with self.lock:
            self.closed=True
            if self.leases==0:self.key=None;self.chunks.clear()

class RangeReader(io.RawIOBase):
    def __init__(self,archive):self.archive=archive;self.position=0
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        p=offset if whence==0 else self.position+offset if whence==1 else self.archive.item['size']+offset
        if p<0:raise ValueError('Negative archive position')
        self.position=p;return p
    def read(self,size=-1):
        end=min(self.archive.item['size'],self.position+size) if size>=0 else self.archive.item['size'];out=[]
        while self.position<end:
            index,offset=divmod(self.position,CHUNK_SIZE);data=self.archive.chunk(index);n=min(end-self.position,len(data)-offset)
            out.append(data[offset:offset+n]);self.position+=n
        return b''.join(out)

class SourceSessions:
    def __init__(self,settings,ttl=1800):self.settings=settings;self.ttl=ttl;self.sessions={};self.lock=threading.RLock();self.open_lock=threading.Lock()
    def sweep(self):
        with self.lock:
            for id,s in list(self.sessions.items()):
                if s['expires']<time.monotonic():s['archive'].close();self.sessions.pop(id)
    def open(self,subject,library,item_id,key,names):
        with self.open_lock:return self._open(subject,library,item_id,key,names)
    def _open(self,subject,library,item_id,key,names):
        self.sweep()
        with self.lock:
            if len(self.sessions)>=4:raise ValueError('Закрой предыдущие главы: одновременно открыты четыре сеанса ВМ.')
        drive=self.settings.drive(subject);vault=VaultDrive(drive,retry_attempts=2)
        try:
            vault.unlock_key(library,key)
            item=next((i for i in vault.catalog['items'] if i['id']==item_id and i.get('category')=='manga'),None)
            if not item:raise ValueError('Глава отсутствует в этой библиотеке.')
            archive=Archive(drive,key,item);actual=archive.names()
            if len(names)!=len(actual) or set(names)!=set(actual):raise ValueError('Список страниц изменился. Открой главу заново.')
        finally:vault.close()
        session={'archive':archive,'subject':subject,'scope':subject+':'+library,'manifest':manifest(item,names),'names':names,'expires':time.monotonic()+self.ttl}
        id=secrets.token_urlsafe(24)
        with self.lock:self.sessions[id]=session
        return id,session
    def get(self,id,subject):
        self.sweep()
        with self.lock:
            s=self.sessions.get(id)
            if not s or s['subject']!=subject:raise KeyError('Сеанс главы истёк. Открой главу заново.')
            s['expires']=time.monotonic()+self.ttl;return s
    def close(self,id,subject):
        with self.lock:
            s=self.sessions.get(id)
            if s and s['subject']==subject:self.sessions.pop(id);s['archive'].close()
