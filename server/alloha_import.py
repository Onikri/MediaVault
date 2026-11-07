"""Drive-only Alloha adapter. Worker threads share the API's native browser pool.

No signed URL/cookie is written to a checkpoint. Media is private temporary
source material; VaultDrive alone encrypts and uploads the finished file.
"""
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from urllib.parse import urljoin, urlsplit

from fastapi import HTTPException
import m3u8
from alloha_browser import SourceInvalid, SourceRefused
from media_download import byte_range, choose_variant, download_episode
from source_parser import SourceError, is_alloha_player

PREFIX = 'https://alloha-import.invalid/'


def discard_checkpoint(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    if path.parent == root and path.is_dir():
        shutil.rmtree(path)


def prune_checkpoints(root, *, maximum_age=7*86400):
    root=Path(root)
    if not root.exists():return
    for task in root.iterdir():
        if task.is_dir() and not task.is_symlink():
            for checkpoint in task.iterdir():
                if checkpoint.is_dir() and time.time()-checkpoint.stat().st_mtime>maximum_age:
                    discard_checkpoint(checkpoint,task)
            if not any(task.iterdir()):task.rmdir()


class AllohaImporter:
    def __init__(self, service, loop, *, interval=4):
        self.service, self.loop, self.interval = service, loop, interval
        self.pacing = asyncio.Lock()
        self.next_request = 0

    async def pace(self):
        async with self.pacing:
            await asyncio.sleep(max(0, self.next_request - time.monotonic()))
            self.next_request = time.monotonic() + self.interval

    def download(self, iframe, directory, *, quality='best', progress=lambda _: None,
                 cancelled=None, checkpoint=None, referer=None):
        if not is_alloha_player(iframe):
            raise SourceError('Нативный импорт предназначен только для Alloha.')
        http = AllohaImportHttp(self, iframe, quality, progress, cancelled, checkpoint, referer=referer)
        try:
            http.call(http.open())
            return download_episode({'type': 'hls', 'url': PREFIX+'root', 'headers': {}},
                                    directory, http=http, quality=quality, progress=progress)
        finally:
            http.call(http.close(), cleanup=True)


class AllohaImportHttp:
    """The synchronous HLS downloader never receives an upstream CDN URL."""
    def __init__(self, importer, iframe, quality, progress, cancelled, checkpoint, *, referer=None):
        self.importer, self.service = importer, importer.service
        self.iframe, self.quality, self.progress = iframe, quality, progress
        self.referer = referer
        self.cancelled = cancelled or (lambda: False)
        self.checkpoint = Path(checkpoint) if checkpoint else None
        self.session = None
        self.audio = None
        self.selected = None
        self.resources, self.documents, self.layout = {}, {}, []
        self.initialization = {}
        self.fingerprint = None
        self.recoveries = 0
        self.saved_resources = set()

    def call(self, coroutine, *, cleanup=False):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.importer.loop)
        deadline = time.monotonic()+120
        while True:
            try:
                return future.result(timeout=.25)
            except FutureTimeout:
                if future.done():raise SourceError('Alloha не завершил запрос вовремя.') from None
                if time.monotonic() > deadline or (not cleanup and (self.cancelled() or self.service.stopping)):
                    future.cancel()
                    raise SourceError('Импорт Alloha отменён или источник слишком долго не отвечает.') from None
            except HTTPException as error:
                raise SourceError(str(error.detail)) from None
            except (SourceInvalid, SourceRefused):
                raise SourceError('Alloha не предоставил проверенный сегмент. Задание можно продолжить.') from None

    async def close(self):
        if self.session:
            await self.service.close_session(self.session)
            self.session = None

    async def open(self):
        await self.close()
        data = await self.service.resolve(self.iframe, audio=self.audio,
                                          online_quality=self.selected or self.quality, referer=self.referer)
        self.session = self.service.session(data['sid'])
        self.audio = self.session.active
        qualities = self.session.translations[self.audio]['qualities']
        selected = max(qualities, key=int) if self.quality == 'best' and not self.selected else self.service.select_quality(qualities, self.selected or self.quality)
        if self.selected and selected != self.selected:
            raise SourceError('Alloha больше не отдаёт выбранное качество. Другое качество не подставлено.')
        self.selected = self.session.online_quality = selected
        self.resources, self.documents, self.layout = {}, {}, []
        self.initialization = {}
        await self.build(qualities[selected], 'root')
        # Never mix old segments with a renewed stream's different init/key.
        for key,(url,range_,kind) in self.resources.items():
            if kind not in {'map','key'}:continue
            await self.importer.pace()
            raw,_,_,_=await self.service.fetch(self.session,url,byte_range=range_)
            if kind=='key' and len(raw)!=16:raise SourceInvalid('Invalid AES-128 key')
            self.initialization[key]=raw
            self.layout.append([key,hashlib.sha256(raw).hexdigest()])
        fingerprint = hashlib.sha256(json.dumps([self.audio, selected, self.layout], sort_keys=True).encode()).hexdigest()
        if self.fingerprint and self.fingerprint != fingerprint:
            raise SourceError('Состав видео Alloha изменился. Нельзя смешивать сегменты разных версий.')
        self.fingerprint = fingerprint
        if self.checkpoint:
            self.checkpoint.mkdir(parents=True, exist_ok=True, mode=0o700)
            marker = self.checkpoint/'layout.json'
            if marker.exists() and json.loads(marker.read_text()) != fingerprint:
                discard_checkpoint(self.checkpoint, self.checkpoint.parent)
                self.checkpoint.mkdir(mode=0o700)
            marker.write_text(json.dumps(fingerprint))
        await self.session.source.update_playback({'time': 0, 'paused': True, 'rate': 1,
                                                   'buffering': False, 'seeking': False, 'ended': False, 'quality': selected})

    async def build(self, url, name, depth=0):
        if depth > 4:
            raise SourceError('Слишком много вложенных плейлистов Alloha.')
        text, final = await self.service.playlist(self.session, url)
        playlist = m3u8.loads(text, uri=final)
        if playlist.is_variant:
            variant = choose_variant(playlist.playlists, self.selected)
            await self.build(variant.absolute_uri, name+'-video', depth+1)
            variant.uri = PREFIX+name+'-video'
            audio = [m for m in playlist.media if m.type == 'AUDIO' and m.group_id == variant.stream_info.audio and m.uri]
            track = next((m for m in audio if m.default == 'YES'), audio[0] if audio else None)
            if track:
                await self.build(track.absolute_uri, name+'-audio', depth+1)
                track.uri = PREFIX+name+'-audio'
            playlist.playlists = type(playlist.playlists)([variant])
            playlist.media = type(playlist.media)([track] if track else [])
        else:
            if not playlist.is_endlist or not playlist.segments or len(playlist.segments)>20000:
                raise SourceError('Alloha не отдал законченное видео для сохранения.')
            offsets, maps, keys = {}, {}, {}
            # m3u8 shares key/map objects: capture their original values first.
            original = [(seg, seg.absolute_uri, seg.byterange,
                         urljoin(final, seg.init_section.uri) if seg.init_section else None,
                         seg.init_section.byterange if seg.init_section else None,
                         urljoin(final, seg.key.uri) if seg.key and seg.key.uri else None)
                        for seg in playlist.segments]
            self.layout.append([name, playlist.media_sequence, len(original)])
            for index, (seg, src, interval, init, init_range, key_url) in enumerate(original):
                range_ = byte_range(interval, src, offsets)
                resource = name+'-segment-'+str(index)
                self.resources[resource] = (src, range_ or '', 'media')
                self.layout.append([resource, seg.duration, range_, seg.discontinuity,
                                    seg.key.method if seg.key else None, seg.key.iv if seg.key else None])
                seg.uri, seg.byterange = PREFIX+resource, None
                if init:
                    identity = (init, init_range)
                    if identity not in maps:
                        target = name+'-map-'+str(len(maps));maps[identity] = target
                        self.resources[target] = (init, byte_range(init_range, init, offsets) or '', 'map')
                        self.layout.append([target, self.resources[target][1]])
                    seg.init_section.uri, seg.init_section.byterange = PREFIX+maps[identity], None
                if key_url:
                    if key_url not in keys:
                        target = name+'-key-'+str(len(keys));keys[key_url] = target
                        self.resources[target] = (key_url, '', 'key')
                    seg.key.uri = PREFIX+keys[key_url]
        self.documents[PREFIX+name] = playlist.dumps()

    async def fetch(self, key):
        for attempt in range(3):
            try:
                self.service.session(self.session.sid)
                url, range_, kind = self.resources[key]
                if key in self.initialization:return self.initialization[key]
                await self.importer.pace()
                raw, headers, _, _ = await self.service.fetch(self.session, url, byte_range=range_)
                if kind == 'key' and len(raw) != 16:
                    raise SourceInvalid('Invalid AES-128 key')
                return raw
            except (SourceRefused, SourceInvalid, HTTPException) as error:
                expired = self.session.closed or self.session.expires <= self.service.clock()
                if isinstance(error, SourceInvalid) and not expired and error.status not in {401,403,404,410,429}:
                    raise
                if isinstance(error, HTTPException) and error.status_code not in {404,409,410}:
                    raise
                if isinstance(error, (SourceRefused, SourceInvalid)):
                    try:
                        await self.service.failed(self.session, error, self.session.iframe)
                    except HTTPException:
                        pass
                if attempt == 2 or self.recoveries >= 8:
                    raise SourceError('Alloha прервал скачивание. Сохранённые сегменты доступны для продолжения.') from None
                if not isinstance(error, HTTPException):self.recoveries += 1
                self.progress({'phase':'downloading','operation':'Переподключаем Alloha; скачанные сегменты сохранены'})
                await self.open()
        raise SourceError('Alloha не вернул сегмент.')

    def document(self, url, **_):
        if url not in self.documents:
            raise SourceError('Неизвестный плейлист импорта Alloha.')
        return self.documents[url], url, {}

    def download(self, url, path, *, maximum=None, **_):
        key = url.removeprefix(PREFIX)
        if not url.startswith(PREFIX) or key not in self.resources:
            raise SourceError('Неизвестный сегмент импорта Alloha.')
        cache = self.checkpoint/key if self.checkpoint else None
        raw = None
        if cache and cache.exists() and cache.with_suffix('.json').exists():
            try:
                record = json.loads(cache.with_suffix('.json').read_text())
                if cache.stat().st_size == record['size']:
                    candidate = cache.read_bytes()
                    if hashlib.sha256(candidate).hexdigest() == record['sha256']:raw = candidate
            except (OSError,ValueError,KeyError):pass
        if raw is None:
            raw = self.call(self.fetch(key))
            if maximum is not None and len(raw)>maximum:
                raise SourceError('Недостаточно места для видео Alloha.')
            if cache:
                pending=cache.with_suffix('.pending');pending.write_bytes(raw);pending.replace(cache)
                cache.with_suffix('.json').write_text(json.dumps({'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}))
        if maximum is not None and len(raw)>maximum:
            raise SourceError('Недостаточно места для видео Alloha.')
        # Keep one copy of each cached segment on filesystems supporting links.
        path=Path(path)
        if cache:
            try:os.link(cache,path)
            except OSError:shutil.copyfile(cache,path)
        else:path.write_bytes(raw)
        self.saved_resources.add(key)
        self.progress({'phase':'downloading','operation':f'Скачиваем Alloha · {len(self.saved_resources)} / {len(self.resources)} частей'})
        return len(raw)
