"""Short-lived RAM-only source/manifest singleflight. No playback capabilities cached."""
from collections import OrderedDict
import copy
import threading
import time
from urllib.parse import urlsplit,parse_qs
from source_parser import SourceError


class PlaybackResolver:
    def __init__(self):
        self.cache=OrderedDict();self.pending={};self.lock=threading.RLock();self.slots=threading.BoundedSemaphore(6);self.preview_slots=threading.BoundedSemaphore(2)

    def clear(self):
        with self.lock:self.cache.clear()

    def get(self,key,loader,ttl=90,refresh=False,preview=False):
        with self.lock:
            if refresh:self.cache.pop(key,None)
            old=self.cache.get(key)
            if old and old[0]>time.monotonic():
                self.cache.move_to_end(key);return copy.deepcopy(old[1]),True
            pending=self.pending.get(key);leader=pending is None
            if leader:
                if len(self.pending)>=64:raise SourceError('Подготовка других потоков ещё выполняется. Повтори запрос.')
                pending=self.pending[key]={'event':threading.Event()}
        if not leader:
            if not pending['event'].wait(45):raise SourceError('Источник не завершил подготовку потока.')
            if 'result' not in pending:raise SourceError('Источник пока не ответил. Повтори подключение.')
            return copy.deepcopy(pending['result']),True
        acquired=False
        try:
            slots=self.preview_slots if preview else self.slots
            acquired=slots.acquire(timeout=3)
            if not acquired:raise SourceError('Сервер готовит другие потоки. Повтори подключение.')
            value=loader()
            lifetime=ttl
            # Explicit signed-link expiry may shorten, never extend, our bounded TTL.
            streams=list(getattr(value,'streams',[]) or [])
            if isinstance(key,tuple) and key[0]=='manifest':
                streams.append({'url':key[1]})
                if '#EXT-X-ENDLIST' not in value[0] and '#EXT-X-STREAM-INF' not in value[0]:lifetime=min(lifetime,5)
            for stream in streams:
                query=parse_qs(urlsplit(stream.get('url','')).query)
                for name in ('expires','expire','exp'):
                    for raw in query.get(name,[]):
                        if raw.isdigit() and len(raw) in (10,13):lifetime=min(lifetime,int(raw)/(1000 if len(raw)==13 else 1)-time.time()-5)
            with self.lock:
                pending['result']=copy.deepcopy(value)
                if lifetime>0:self.cache[key]=(time.monotonic()+lifetime,copy.deepcopy(value))
                while len(self.cache)>192:self.cache.popitem(last=False)
            return value,False
        finally:
            if acquired:slots.release()
            with self.lock:self.pending.pop(key,None);pending['event'].set()

    def page(self,subject,url,referer,loader,refresh=False,preview=False):
        return self.get(('page',subject,url,referer),loader,refresh=refresh,preview=preview)

    def document(self,http,url,headers=None,refresh=False):
        key=('manifest',url,tuple(sorted((headers or {}).items())))
        return self.get(key,lambda:http.document(url,headers=headers),ttl=90,refresh=refresh,preview=getattr(http,'preview',False))[0]
