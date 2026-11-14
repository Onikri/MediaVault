"""Alloha-only resolver and HLS proxy, in one Python 3.12/FastAPI process.

Standalone entry point: uvicorn alloha_delivery:app --workers 1 --port 7864.
The existing API mounts the same service for Alloha playback only.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urljoin, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
import httpx
import m3u8

from alloha_browser import NativeSession, SourceInvalid, SourceRefused
from alloha_bnsi import BnsiSession, MODES
from alloha_profiles import NativeProfiles, PROFILE_RETRY_INTERVAL
from source_parser import is_alloha_player, public_url
from alloha_cache import VodCache, identity as cache_identity

logger = logging.getLogger('mediavault.alloha')
TTL = 900
RANGE = re.compile(r'bytes=(?:\d+-\d*|-\d+)$')
IDENTIFIER = re.compile(r'[A-Za-z0-9_-]{1,100}$')


async def cache_io(function, *args):
    # Cancelling a prefetch does not stop to_thread. Finish its disk operation
    # before teardown can remove the cache or close the session.
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def invalid(message='Источник вернул неподдерживаемый поток.'):
    return HTTPException(502, message)


def media(raw, headers):
    mime = headers.get('content-type', '').split(';')[0].strip().lower()
    if not raw or mime in {'text/html', 'application/xhtml+xml'} or raw.lstrip().startswith((b'<', b'<!')):
        raise SourceInvalid('Source returned HTML or empty data instead of media')
    if mime and not (mime.startswith(('video/', 'audio/')) or mime in {'application/octet-stream', 'binary/octet-stream', 'application/mp4'}):
        raise SourceInvalid('Source returned a non-media content type')
    return mime or 'application/octet-stream'


class SegmentCache:
    def __init__(self, directory, *, ttl=3600, maximum=512 * 1024 * 1024):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.ttl, self.maximum = ttl, maximum

    def paths(self, url, byte_range):
        # A partial response must never poison the full segment at the same URL.
        digest = hashlib.sha256(url.encode()).hexdigest()
        suffix = '-' + hashlib.sha256(byte_range.encode()).hexdigest()[:16] if byte_range else ''
        target = self.directory / (digest + suffix)
        return target, target.with_suffix('.json')

    def get(self, url, byte_range=''):
        data, metadata = self.paths(url, byte_range)
        try:
            record = json.loads(metadata.read_text())
            if time.time() - record['created'] >= self.ttl or data.stat().st_size != record['size']:
                return None
            return data.read_bytes(), record['headers'], record['status'], record['final']
        except (OSError, ValueError, KeyError):
            return None

    def put(self, url, byte_range, value):
        raw, headers, status, final = value
        if not raw or len(raw) > self.maximum:
            return
        self.prune(len(raw))
        data, metadata = self.paths(url, byte_range)
        temporary = self.directory / (data.name + '.' + secrets.token_hex(8) + '.pending')
        try:
            temporary.write_bytes(raw)
            temporary.replace(data)
            temporary.write_text(json.dumps({'created': time.time(), 'size': len(raw),
                                              'headers': headers, 'status': status, 'final': final}))
            temporary.replace(metadata)
        finally:
            temporary.unlink(missing_ok=True)

    def prune(self, reserve=0):
        entries, total = [], 0
        for metadata in self.directory.glob('*.json'):
            try:
                record = json.loads(metadata.read_text())
                data = metadata.with_suffix('')
                size = data.stat().st_size
                entries.append((record['created'], data, metadata, size))
                total += size
            except (OSError, ValueError, KeyError):
                metadata.unlink(missing_ok=True)
        for created, data, metadata, size in sorted(entries):
            if time.time() - created < self.ttl and total + reserve <= self.maximum:
                break
            data.unlink(missing_ok=True)
            metadata.unlink(missing_ok=True)
            total -= size


@dataclass
class DeliverySession:
    sid: str
    iframe: str
    profile: object
    source: object
    expires: float
    address: str
    referer: str = ''
    active: str = ''
    active_id: str = ''
    translations: dict = field(default_factory=dict)
    resources: dict = field(default_factory=dict)
    resource_ids: dict = field(default_factory=dict)
    resource_urls: dict = field(default_factory=dict)
    manifests: dict = field(default_factory=dict)
    skip: list = field(default_factory=list)
    subtitles: list = field(default_factory=list)
    online_quality: str = ''
    owner: str = ''
    mode: str = 'browser'
    published_qualities: list = field(default_factory=list)
    closed: bool = False
    switch_lock: object = field(default_factory=asyncio.Lock)
    io_lock: object = field(default_factory=asyncio.Lock)
    prefetch_io: object = field(default_factory=asyncio.Lock)
    next_segments: dict = field(default_factory=dict)
    transfers: dict = field(default_factory=dict)
    prefetches: set = field(default_factory=set)
    cache_key: str = ''
    cache_complete: bool = False
    cache_started: bool = False
    demands: int = 0
    aliases: dict = field(default_factory=dict)
    generation: int = 0
    refreshes: int = 0
    refreshed_at: float = 0
    refresh_lock: object = field(default_factory=asyncio.Lock)
    promotions: dict = field(default_factory=dict)


class AllohaDelivery:
    def __init__(self, directory=None, *, profiles=None, factory=NativeSession, direct_factory=BnsiSession,
                 clock=time.monotonic, queue_timeout=30, session_ttl=TTL, default_mode='bnsi'):
        root = Path(directory or Path(os.getenv('DATA_DIR') or Path(__file__).resolve().parents[1]) / '.codex-local' / 'alloha-delivery')
        self.profiles = profiles or NativeProfiles(root / 'profiles', clock=clock)
        self.cache = SegmentCache(root / 'segments')
        self.vod = VodCache(root / 'vod', maximum=int(os.getenv('ALLOHA_VOD_CACHE_BYTES', str(60*1024**3))),
                            reserve=int(os.getenv('ALLOHA_VOD_FREE_BYTES', str(8*1024**3))))
        self.archive = None
        self.archive_tasks = set()
        self.restore_locks = {}
        self.prefetch_interval = max(0, float(os.getenv('ALLOHA_PREFETCH_INTERVAL', '2')))
        self.prefetch_pacing = asyncio.Lock()
        self.prefetch_next = 0
        self.factory, self.clock = factory, clock
        self.direct_factory, self.default_mode = direct_factory, default_mode
        self.queue_timeout, self.ttl = queue_timeout, session_ttl
        self.sessions = {}
        self.slots = asyncio.Semaphore(2)
        self.external_address = os.getenv('ALLOHA_EXTERNAL_ADDRESS', '')
        self.reaper = None
        self.profile_refresher = None
        self.stopping = False
        self.preparing = set()
        self.closures = set()
        self.start_lock = asyncio.Lock()
        self.online_clients = {}
        self.log_directory = root / 'logs'
        self.logger = logging.getLogger('mediavault.alloha.' + hashlib.sha256(str(root).encode()).hexdigest()[:12])
        self.log_handler = None

    async def start(self):
        async with self.start_lock:
            await self._start()

    async def _start(self):
        if self.stopping:
            raise HTTPException(503, 'Сервис останавливается.', headers={'Retry-After': '30'})
        if self.reaper:
            return
        if not self.external_address:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get('https://api.ipify.org')
                response.raise_for_status()
                self.external_address = str(ipaddress.ip_address(response.text.strip()))
        if not ipaddress.ip_address(self.external_address).is_global:
            raise RuntimeError('Alloha requires the actual public egress address')
        self.log_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.log_handler = RotatingFileHandler(self.log_directory / 'requests.log', maxBytes=4 * 1024 * 1024, backupCount=2)
        self.logger.addHandler(self.log_handler)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.stopping = False
        self.reaper = asyncio.create_task(self.expire_loop())

    def start_profile_refresh(self):
        if self.profile_refresher is None:
            self.profile_refresher = asyncio.create_task(self.refresh_profiles())

    async def refresh_profiles(self):
        while True:
            try:
                await self.profiles.refresh()
            except Exception as error:
                logger.warning('Alloha profile refresh failed (%s)', type(error).__name__)
            await asyncio.sleep(PROFILE_RETRY_INTERVAL)

    async def expire_loop(self):
        try:
            while True:
                await asyncio.sleep(5)
                await self.expire()
        except asyncio.CancelledError:
            pass

    async def expire(self):
        for session in list(self.sessions.values()):
            if session.expires <= self.clock():
                await self.close_session(session)
        if self.vod.clock()-self.vod.last_prune >= 30:
            await cache_io(self.vod.prune)

    async def close_session(self, session):
        if session.closed:
            return
        session.closed = True
        self.sessions.pop(session.sid, None)
        pending = (set(session.transfers.values()) | session.prefetches) - {asyncio.current_task()}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        session.transfers.clear()
        session.promotions.clear()
        session.prefetches.clear()
        if session.cache_key:
            await cache_io(self.vod.release, session.cache_key)
        for key, value in list(self.online_clients.items()):
            if value == session.sid:
                self.online_clients.pop(key, None)
        async def close_source():
            try:
                await session.source.close()
            finally:
                if session.profile is not None:
                    session.profile.in_use -= 1
                self.slots.release()
        task = asyncio.create_task(close_source())
        self.closures.add(task)
        task.add_done_callback(self.closures.discard)
        await asyncio.shield(task)

    async def close(self):
        self.stopping = True
        if self.profile_refresher:
            self.profile_refresher.cancel()
            await asyncio.gather(self.profile_refresher, return_exceptions=True)
            self.profile_refresher = None
        if self.reaper:
            self.reaper.cancel()
            await self.reaper
            self.reaper = None
        for task in list(self.preparing):
            task.cancel()
        if self.preparing:
            await asyncio.gather(*list(self.preparing), return_exceptions=True)
        await asyncio.gather(*(self.close_session(s) for s in list(self.sessions.values())), return_exceptions=True)
        if self.closures:
            await asyncio.gather(*list(self.closures), return_exceptions=True)
        if self.archive_tasks:
            await asyncio.gather(*list(self.archive_tasks), return_exceptions=True)
        if self.log_handler:
            self.logger.removeHandler(self.log_handler)
            self.log_handler.close()
            self.log_handler = None

    def log(self, session, status, url, *, reason=None, **timing):
        self.logger.info(json.dumps({'sid': session.sid, 'profile': session.profile.id if session.profile else 'bnsi',
                                'external_address': session.address, 'status': status,
                                'source_host': urlsplit(url).hostname, **({'reason': reason} if reason else {}), **timing}, ensure_ascii=True))

    async def failed(self, session, error, url):
        if not session.closed and session.profile is not None:
            if isinstance(error, SourceRefused):
                self.profiles.refused(session.profile, session.iframe)
            else:
                self.profiles.unavailable(session.profile, session.iframe)
        code = 409 if isinstance(error, SourceRefused) else 502
        self.log(session, code, url)
        await self.close_session(session)
        if code == 409:
            raise HTTPException(409, 'Alloha временно отказал сессии. Разреши iframe заново.', headers={'Retry-After': '120'})
        if getattr(error, 'status', None) in {404, 410}:
            raise invalid('Ссылка Alloha больше недоступна. Обнови список источников.')
        raise invalid()

    def session(self, sid):
        session = self.sessions.get(sid)
        if not session or session.closed or session.expires <= self.clock():
            raise HTTPException(404, 'Сессия Alloha истекла.')
        return session

    def renew(self, session):
        session.expires = self.clock() + self.ttl
        return self.ttl

    def register(self, session, url, kind):
        url = public_url(url, resolve_dns=False)
        if len(session.resources) >= 20000 and url not in session.resources:
            raise SourceInvalid('Too many resources in source playlist')
        session.resources[url] = kind
        if url not in session.resource_ids:
            token = secrets.token_urlsafe(18)
            session.resource_ids[url] = token
            session.resource_urls[token] = url
        return '/hls/' + session.sid + '?u=' + session.resource_ids[url]

    async def fetch(self, session, url, *, kind='media', byte_range='', probe=False, cache=True):
        started = self.clock()
        if session.cache_key and cache and kind != 'manifest' and not probe:
            cached = await cache_io(self.vod.get, session.cache_key, url, byte_range)
            if cached:
                self.log(session, cached[2], url, cached=True, elapsed_ms=round((self.clock()-started)*1000), bytes=len(cached[0]))
                return cached
            if session.cache_complete:
                raise HTTPException(410, 'Кэш потока повреждён. Обновляем подключение.')
        if cache and kind != 'manifest' and not probe:
            cached = await cache_io(self.cache.get, url, byte_range)
            if cached:
                if session.cache_key:
                    await cache_io(self.vod.put, session.cache_key, url, byte_range, cached)
                self.log(session, cached[2], url, cached=True, elapsed_ms=round((self.clock()-started)*1000), bytes=len(cached[0]))
                return cached
        if session.mode == 'bnsi':
            try:
                value = await session.source.fetch(session.aliases.get(url, url), byte_range, probe=probe)
            except SourceRefused as error:
                self.log(session, error.status or 403, url, reason=error.reason)
                raise
        else:
            value = await session.source.fetch(url, byte_range)
        raw, headers, status, final = value
        self.log(session, status, final, cached=False, elapsed_ms=round((self.clock()-started)*1000), bytes=len(raw))
        if kind == 'manifest':
            if not raw.lstrip().startswith(b'#EXTM3U') or len(raw) > 4 * 1024 * 1024:
                raise SourceInvalid('Source returned a non-HLS document')
        elif kind == 'subtitle':
            if not raw.lstrip().startswith(b'WEBVTT'):
                raise SourceInvalid('Source returned invalid subtitles')
        elif kind == 'key':
            if len(raw) != 16:
                raise SourceInvalid('Invalid AES-128 key')
        else:
            media(raw, headers)
        if cache and kind != 'manifest' and not probe:
            if session.cache_key:
                await cache_io(self.vod.put, session.cache_key, url, byte_range, value)
            else:
                await cache_io(self.cache.put, url, byte_range, value)
        return value

    async def transfer(self, session, url, kind, byte_range='', *, background=False):
        """Join an in-flight lookahead instead of fetching the same segment twice."""
        key = (url, byte_range)
        task = session.transfers.get(key)
        if task is not None and not background:
            urgent = session.promotions.get(key)
            if urgent is not None:
                urgent.set()
        if task is None:
            urgent = asyncio.Event()
            session.promotions[key] = urgent
            async def load():
                if background and session.cache_key:
                    cached = await cache_io(self.vod.get, session.cache_key, url, byte_range)
                    if cached:
                        return cached
                    # Match the existing Alloha importer cadence. An unlimited
                    # full-film burst can invalidate an otherwise healthy CDN session.
                    async with self.prefetch_pacing:
                        reserved = max(time.monotonic(), self.prefetch_next)
                        self.prefetch_next = reserved+self.prefetch_interval
                    delay = reserved-time.monotonic()
                    if delay > 0 and not urgent.is_set():
                        try:
                            await asyncio.wait_for(urgent.wait(), delay)
                        except asyncio.TimeoutError:
                            pass
                while background and not urgent.is_set() and session.demands:
                    await asyncio.sleep(.01)
                # BNSI is ordinary HTTP: one background transfer may overlap
                # one foreground seek. Native WS/browser transports keep their
                # existing serialized I/O. Neither path adds source bursts.
                guard = session.prefetch_io if background and not urgent.is_set() and session.mode == 'bnsi' and session.cache_key else session.io_lock
                generation = session.generation
                if session.mode == 'bnsi' and session.cache_key and not session.cache_complete and session.refreshed_at and self.clock()-session.refreshed_at >= 1080:
                    await self.refresh_http(session, generation)
                    generation = session.generation
                try:
                    async with guard:
                        self.session(session.sid)
                        return await self.fetch(session, url, kind=kind, byte_range=byte_range)
                except (SourceRefused, SourceInvalid) as error:
                    if not session.cache_key or session.mode != 'bnsi' or getattr(error, 'status', None) not in {401, 403, 404, 410}:
                        raise
                    await self.refresh_http(session, generation)
                    async with guard:
                        self.session(session.sid)
                        return await self.fetch(session, url, kind=kind, byte_range=byte_range)
            task = asyncio.create_task(load())
            session.transfers[key] = task
            def finished(done):
                session.promotions.pop(key, None)
                # Retain a failed speculative request until demanded: never send
                # the same refused request again through the same source session.
                if done.cancelled() or done.exception() is None:
                    if session.transfers.get(key) is done:
                        session.transfers.pop(key, None)
            task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def refresh_http(self, session, generation):
        """Renew expiring HTTP links without replacing the viewer capability.

        Reuse the importer's strict track/layout/map/key compatibility check.
        Different cuts, audio, durations or encryption never share old fragments.
        """
        from alloha_import import AllohaImportHttp
        from types import SimpleNamespace
        async with session.refresh_lock:
            if session.generation != generation:
                return
            if session.refreshes >= 8 or session.cache_complete:
                raise SourceInvalid('Alloha renewal limit reached')
            async with session.io_lock, session.prefetch_io:
                replacement = self.direct_factory(session.iframe, referer=session.referer or None)
                accepted = False
                try:
                    await replacement.open(session.active)
                    metadata = await replacement.metadata()
                    row = next((r for r in metadata['sources'] if str(r.get('audioId')) == session.active), None)
                    quality = session.online_quality
                    if not row or str(metadata['active_id']) != session.active_id or str(metadata['active']) != session.active or str(row.get('label') or session.active) != session.translations[session.active]['name']:
                        raise SourceInvalid('Renewed Alloha audio/cut changed')
                    url = (row.get('quality') or {}).get(quality) or (row.get('quality') or {}).get(quality+'p')
                    if not isinstance(url, str):
                        raise SourceInvalid('Renewed Alloha quality changed')
                    renewed = DeliverySession('renewal', session.iframe, None, replacement, session.expires,
                                              session.address, mode='bnsi', online_quality=quality)
                    def plan(native):
                        value = AllohaImportHttp(SimpleNamespace(service=self), session.iframe, quality, lambda _: None, None, None)
                        value.session, value.selected = native, quality
                        return value
                    old, new = plan(session), plan(renewed)
                    await old.build(session.translations[session.active]['qualities'][quality], 'root')
                    await new.build(public_url(url.split(' or ')[0].strip(), resolve_dns=False), 'root')
                    if old.layout != new.layout or old.resources.keys() != new.resources.keys():
                        raise SourceInvalid('Renewed Alloha segment layout changed')
                    for name, (target, interval, kind) in old.resources.items():
                        if kind not in {'map', 'key'}:
                            continue
                        original = await cache_io(self.vod.get, session.cache_key, target, interval)
                        if original is None:
                            raise SourceInvalid('Original Alloha initialization missing')
                        fresh_url, fresh_range, _ = new.resources[name]
                        fresh = await self.fetch(renewed, fresh_url, byte_range=fresh_range, kind='key' if kind == 'key' else 'media', cache=False)
                        if hashlib.sha256(original[0]).digest() != hashlib.sha256(fresh[0]).digest():
                            raise SourceInvalid('Renewed Alloha initialization changed')
                    aliases = {target: new.resources[name][0] for name, (target, _, _) in old.resources.items()}
                    first_name = next((n for n, (_, _, kind) in old.resources.items() if kind == 'media'), None)
                    if first_name:
                        old_url, interval, _ = old.resources[first_name]
                        original = await cache_io(self.vod.get, session.cache_key, old_url, interval)
                        if original is not None:
                            start = int(interval[6:].split('-')[0]) if interval else 0
                            length = min(65536, len(original[0]))
                            sample = await self.fetch(renewed, new.resources[first_name][0],
                                byte_range=f'bytes={start}-{start+length-1}', probe=True, cache=False)
                            if sample[0][:length] != original[0][:length]:
                                raise SourceInvalid('Renewed Alloha video changed')
                    for track in session.subtitles:
                        matches = [t for t in metadata.get('subtitles', []) if str(t.get('label') or 'Субтитры')[:160] == track['label'] and str(t.get('lang') or 'und')[:20] == track['lang']]
                        if len(matches) == 1:
                            target = session.resource_urls[track['src'].split('?u=', 1)[-1]]
                            aliases[target] = public_url(matches[0]['src'], resolve_dns=False)
                    old_source = session.source
                    session.source, session.aliases = replacement, aliases
                    session.generation += 1
                    session.refreshes += 1
                    session.refreshed_at = self.clock()
                    accepted = True
                    await old_source.close()
                    self.log(session, 200, session.iframe, reason='renewed-compatible-vod')
                finally:
                    if not accepted:
                        await replacement.close()

    def lookahead(self, session, url, byte_range):
        if session.cache_key:
            return  # The selected VOD has its own bounded, continuous downloader.
        following = session.next_segments.get(url)
        # One segment per request, at most two queued (video + audio). No chain,
        # whole-film download, parallel source bursts or ranged-file speculation.
        if (byte_range or not following or session.closed or len(session.prefetches) >= 2
                or (following, '') in session.transfers):
            return
        async def preload():
            try:
                await self.transfer(session, following, 'media')
            except (HTTPException, SourceRefused, SourceInvalid):
                pass  # The demand path reports the saved error and renews normally.
        task = asyncio.create_task(preload())
        session.prefetches.add(task)
        task.add_done_callback(session.prefetches.discard)

    async def playlist(self, session, url):
        cached = session.manifests.get(url)
        if cached and cached[0] > self.clock():
            return self.selected_manifest(session, cached[1], cached[2]), cached[2]
        raw, _, _, final = await self.fetch(session, url, kind='manifest')
        text = raw.decode('utf-8-sig')
        # Finished VOD playlists don't change. Refetching their expiring signed
        # URLs during a long pause needlessly destroys otherwise playable media.
        finished = m3u8.loads(text, uri=final).is_endlist
        session.manifests[url] = (float('inf') if finished else self.clock() + 20, text, final)
        return self.selected_manifest(session, text, final), final

    @staticmethod
    def selected_manifest(session, text, final):
        if not session.cache_key or not session.online_quality:
            return text
        parsed = m3u8.loads(text, uri=final)
        if not parsed.playlists:
            return text
        choices = [p for p in parsed.playlists if not p.stream_info.resolution or p.stream_info.resolution[1] <= int(session.online_quality)]
        if not choices:
            raise SourceInvalid('Source has no selected VOD quality')
        chosen = max(choices, key=lambda p: (p.stream_info.resolution or (0, 0), p.stream_info.bandwidth or 0))
        parsed.playlists[:] = [chosen]
        tracks = [p for p in parsed.media if p.type == 'AUDIO' and p.group_id == chosen.stream_info.audio]
        audio = next((p for p in tracks if p.default == 'YES'), tracks[0] if tracks else None)
        parsed.media[:] = [p for p in parsed.media if p is audio or
                           p.type == 'SUBTITLES' and p.group_id == chosen.stream_info.subtitles or
                           p.type == 'CLOSED-CAPTIONS' and p.group_id == chosen.stream_info.closed_captions]
        return parsed.dumps()

    async def warm_vod(self, session, root):
        """One sequential downloader; foreground seeks take the next I/O slot."""
        resources, documents, seen, planned = [], {}, set(), []

        async def visit(url, depth=0, track_kind='media'):
            if depth > 4 or len(seen) > 20000:
                raise SourceInvalid('VOD cache exceeds playlist limits')
            if url in seen:
                return
            seen.add(url)
            text, final = await self.playlist(session, url)
            parsed = m3u8.loads(text, uri=final)
            if parsed.session_keys:
                raise SourceInvalid('Unsupported session key')
            if parsed.playlists:
                choices = [p for p in parsed.playlists if not p.stream_info.resolution or p.stream_info.resolution[1] <= int(session.online_quality)]
                chosen = max(choices, key=lambda p: (p.stream_info.resolution or (0, 0), p.stream_info.bandwidth or 0))
                parsed.playlists[:] = [chosen]
                tracks = [p for p in parsed.media if p.uri]
                text = parsed.dumps()
                documents[url] = [text, final]
                session.manifests[url] = (float('inf'), text, final)
                await visit(chosen.absolute_uri, depth+1)
                for track in tracks:
                    await visit(track.absolute_uri, depth+1, 'subtitle' if track.type == 'SUBTITLES' else 'media')
                return
            if not parsed.is_endlist or not parsed.segments:
                raise SourceInvalid('Only completed VOD is archived')
            documents[url] = [text, final]
            offsets = {}
            for segment in parsed.segments:
                if len(resources) > 20000:
                    raise SourceInvalid('Too many cached resources')
                items = []
                if segment.key and segment.key.method != 'NONE':
                    if segment.key.method != 'AES-128' or segment.key.keyformat not in {None, 'identity'}:
                        raise SourceInvalid('Unsupported encrypted media')
                    items.append((segment.key.absolute_uri, '', 'key'))
                if segment.init_section:
                    items.append((urljoin(final, segment.init_section.uri), segment.init_section.byterange or '', 'media'))
                items.append((segment.absolute_uri, segment.byterange or '',
                              'subtitle' if track_kind == 'subtitle' and urlsplit(segment.absolute_uri).path.endswith(('.vtt', '.webvtt')) else 'media'))
                for target, interval, kind in items:
                    if interval:
                        length, _, offset = interval.partition('@')
                        begin = int(offset) if offset else offsets.get(target, 0)
                        offsets[target] = begin+int(length)
                        interval = f'bytes={begin}-{offsets[target]-1}'
                    pair = (target, interval)
                    if pair in wanted:
                        continue
                    wanted.add(pair)
                    planned.append((target, interval, kind))

        wanted = set()
        try:
            await visit(root)
            # Freeze every track's VOD document before long background downloads
            # can outlive a signed child-playlist URL.
            for target, interval, kind in planned:
                await self.transfer(session, target, kind, interval, background=True)
                if await cache_io(self.vod.get, session.cache_key, target, interval) is None:
                    raise SourceInvalid('VOD cache is full or unavailable')
                resources.append((target, interval))
                await asyncio.sleep(0)
            subtitles = []
            for track in session.subtitles:
                token = track['src'].split('?u=', 1)[-1]
                url = session.resource_urls[token]
                await self.transfer(session, url, 'subtitle', background=True)
                resources.append((url, ''))
                subtitles.append({'label': track['label'], 'lang': track['lang'], 'url': url})
            record = {'resources': resources, 'manifests': documents, 'root': root,
                      'quality': session.online_quality, 'active': session.active,
                      'active_id': session.active_id, 'translations': session.translations,
                      'skip': session.skip, 'mode': session.mode, 'subtitles': subtitles,
                      'published_qualities': session.published_qualities}
            session.cache_complete = await cache_io(self.vod.complete, session.cache_key, record)
            if session.cache_complete and self.archive:
                await cache_io(self.vod.pin, session.cache_key)
                async def save():
                    try:
                        await asyncio.to_thread(self.archive.save, session.owner, session.cache_key)
                    except Exception as error:
                        self.log(session, 503, session.iframe, reason='archive-'+type(error).__name__)
                    finally:
                        await cache_io(self.vod.release, session.cache_key)
                task = asyncio.create_task(save())
                self.archive_tasks.add(task)
                task.add_done_callback(self.archive_tasks.discard)
        except (HTTPException, SourceRefused, SourceInvalid, OSError, ValueError) as error:
            # A speculative failure must never close the foreground player.
            self.log(session, 503, session.iframe, reason='prefetch-'+type(error).__name__)

    async def cached_online(self, key, body, subject):
        # Pin before a potentially slow Drive restore so the reaper can't evict it.
        await cache_io(self.vod.pin, key)
        try:
            record = await cache_io(self.vod.load, key)
            if record is None and self.archive:
                try:
                    await asyncio.wait_for(cache_io(self.archive.restore, subject, key), 180)
                    record = await cache_io(self.vod.load, key)
                except Exception as error:
                    logger.info('Alloha archive restore unavailable (%s)', type(error).__name__)
            if record is None:
                return None
            await self.start()
            await asyncio.wait_for(self.slots.acquire(), self.queue_timeout)
            class CachedSource:
                async def close(self): pass
                async def fetch(self, *args, **kwargs):
                    raise SourceInvalid('Cached resource is missing or damaged')
                async def update_playback(self, state): pass
            session = DeliverySession(secrets.token_urlsafe(32), body.url, None, CachedSource(),
                self.clock()+self.ttl, self.external_address, referer=getattr(body, 'referer', None) or '',
                owner=subject, mode=record['mode'], active=record['active'], active_id=record['active_id'],
                translations=record['translations'], online_quality=record['quality'], skip=record['skip'],
                cache_key=key, cache_complete=True, cache_started=True)
            session.published_qualities = record.get('published_qualities') or [int(record['quality'])]
            session.manifests = {url: (float('inf'), *data) for url, data in record['manifests'].items()}
            session.subtitles = [{'label': t['label'], 'lang': t['lang'],
                                  'src': self.register(session, t['url'], 'subtitle')}
                                 for t in record.get('subtitles', [])]
            self.sessions[session.sid] = session
            await cache_io(self.vod.pin, key)
            return session
        finally:
            await cache_io(self.vod.release, key)

    async def ready(self, session, url, quality, depth=0):
        if depth > 4:
            raise SourceInvalid('Playlist nesting exceeds four levels')
        text, final = await self.playlist(session, url)
        playlist = m3u8.loads(text, uri=final)
        if playlist.session_keys or any(key and (key.method not in {'NONE', 'AES-128'} or key.keyformat not in {None, 'identity'}) for key in playlist.keys):
            raise SourceInvalid('Unsupported encrypted media')
        if playlist.playlists:
            variants = [p for p in playlist.playlists if not p.stream_info.resolution or p.stream_info.resolution[1] <= int(quality)]
            if not variants:
                raise SourceInvalid('Source has no variant at the advertised quality')
            selected = max(variants, key=lambda p: (p.stream_info.resolution or (0, 0), p.stream_info.bandwidth or 0))
            await self.ready(session, selected.absolute_uri, quality, depth + 1)
            tracks = [p for p in playlist.media if p.type == 'AUDIO' and p.uri and p.group_id == selected.stream_info.audio]
            if tracks:
                audio = next((p for p in tracks if p.default == 'YES'), tracks[0])
                await self.ready(session, audio.absolute_uri, quality, depth + 1)
            return
        if not playlist.segments:
            raise SourceInvalid('Source playlist has no media segments')
        first = playlist.segments[0]
        resources = [(first.absolute_uri, first.byterange)]
        if first.init_section:
            resources.insert(0, (urljoin(final, first.init_section.uri), first.init_section.byterange))
        for resource, interval in resources:
            byte_range = 'bytes=0-65535'
            if interval:
                match = re.fullmatch(r'(\d+)(?:@(\d+))?', interval)
                if not match or not int(match[1]):
                    raise SourceInvalid('Invalid HLS segment byte range')
                start = int(match[2] or 0)
                byte_range = f'bytes={start}-{start + min(65536, int(match[1])) - 1}'
            await self.fetch(session, resource, byte_range=byte_range, probe=True)

    async def resolve(self, iframe, *, audio=None, online_quality=None, referer=None, mode=None):
        mode = mode or self.default_mode
        if mode not in MODES:
            raise HTTPException(422, 'Неизвестный режим подключения Alloha.')
        try:
            return await self._resolve(iframe, audio=audio, online_quality=online_quality, referer=referer, mode=mode)
        except HTTPException as direct_error:
            if mode != 'bnsi' or direct_error.status_code not in {409, 502}:
                raise
            # Some signed links stop working at the CDN while the iframe is
            # still valid. Try the full browser session for the same release.
            try:
                return await self._resolve(iframe, audio=audio, online_quality=online_quality, referer=referer, mode='browser')
            except HTTPException as browser_error:
                if browser_error.status_code not in {409, 502}:
                    raise
                raise HTTPException(direct_error.status_code,
                    'Alloha не отдал рабочий поток через BNSI и браузерный режим.',
                    headers=direct_error.headers) from None

    async def _resolve(self, iframe, *, audio, online_quality, referer, mode):
        try:
            iframe = public_url(iframe, resolve_dns=False)
            referer = public_url(referer, resolve_dns=False) if referer else None
        except Exception:
            raise HTTPException(422, 'Нужен публичный iframe Alloha.') from None
        if not is_alloha_player(iframe):
            raise HTTPException(422, 'Этот resolver поддерживает только Alloha.')
        await self.start()
        await self.expire()
        if self.stopping:
            raise HTTPException(503, 'Сервис останавливается.', headers={'Retry-After': '30'})
        try:
            await asyncio.wait_for(self.slots.acquire(), self.queue_timeout)
        except asyncio.TimeoutError:
            raise HTTPException(503, 'Два потока Alloha уже активны.', headers={'Retry-After': '30'}) from None
        if self.stopping:
            self.slots.release()
            raise HTTPException(503, 'Сервис останавливается.', headers={'Retry-After': '30'})
        source = session = profile = None
        task = asyncio.current_task()
        self.preparing.add(task)
        try:
            if mode == 'browser':
                try:
                    await self.profiles.refresh()
                except Exception:
                    if not self.profiles.profiles:
                        raise HTTPException(409, 'Нет проверенного профиля Alloha.', headers={'Retry-After': '120'}) from None
                profile = self.profiles.choose(iframe)
                if not profile:
                    raise HTTPException(409, 'Профили Alloha временно недоступны.', headers={'Retry-After': '120'})
                source = self.factory(profile, iframe, referer=referer)
            else:
                source = self.direct_factory(iframe, referer=referer)
            session = DeliverySession(secrets.token_urlsafe(32), iframe, profile, source,
                                      self.clock() + self.ttl, self.external_address, referer=referer or '', mode=mode)
            if profile is not None:
                profile.reservations += 1
                profile.in_use += 1
            await source.open(audio)
            data = await source.metadata()
            session.active, session.active_id = str(data['active']), str(data['active_id'])
            missing_active = None
            for value in data['sources']:
                identifier = str(value.get('audioId', ''))
                if not IDENTIFIER.fullmatch(identifier):
                    continue
                if online_quality is not None and identifier != session.active:
                    continue
                qualities = {}
                published = {}
                for label, url in (value.get('quality') or {}).items():
                    label = str(label).removesuffix('p')
                    if not label.isdigit() or not 1 <= int(label) <= 8640 or not isinstance(url, str):
                        continue
                    url = public_url(url.split(' or ')[0].strip(), resolve_dns=False)
                    published[label] = url
                candidates = list(published)
                if online_quality is not None and published:
                    requested = max(map(int, published)) if online_quality == 'best' else int(online_quality)
                    # Prefer the nearest lower quality on the same published track.
                    candidates.sort(key=lambda q: (int(q) > requested, abs(int(q) - requested)))
                    candidates = candidates[:4]
                missing = set()
                for label in candidates:
                    url = published[label]
                    try:
                        await self.ready(session, url, label)
                    except SourceInvalid as error:
                        if error.status not in {404, 410}:
                            raise
                        self.log(session, error.status, url)
                        missing.add(label)
                        if identifier == session.active:
                            missing_active = error
                        continue
                    self.register(session, url, 'manifest')
                    qualities[label] = url
                    if online_quality is not None:
                        break
                if online_quality is not None:
                    session.published_qualities = sorted((int(q) for q in published if q not in missing), reverse=True)
                if qualities:
                    session.translations[identifier] = {'name': str(value.get('label') or identifier)[:160],
                                                         'default': identifier == session.active, 'qualities': qualities}
            if session.active not in session.translations:
                if missing_active:
                    raise missing_active
                raise SourceInvalid('Active audio has no ready media')
            for interval in data.get('skip', []):
                if (isinstance(interval, (list, tuple)) and len(interval) == 2
                        and all(isinstance(n, (float, int)) for n in interval) and 0 <= interval[0] < interval[1] <= 86400):
                    session.skip.append(list(interval))
            for track in data.get('subtitles', [])[:40]:
                session.subtitles.append({'label': str(track.get('label') or 'Субтитры')[:160],
                                          'lang': str(track.get('lang') or 'und')[:20],
                                          'src': self.register(session, track['src'], 'subtitle')})
            if profile is not None:
                self.profiles.ready(profile)
            session.expires = self.clock() + self.ttl
            session.refreshed_at = self.clock()
            self.sessions[session.sid] = session
            return self.contract(session)
        except (SourceRefused, SourceInvalid) as error:
            if session:
                await self.failed(session, error, iframe)
            raise invalid() from None
        except HTTPException:
            raise
        except Exception as error:
            logger.warning('Alloha session initialization failed (%s)', type(error).__name__)
            if session:
                await self.failed(session, SourceInvalid('Source session initialization failed'), iframe)
            raise invalid() from None
        finally:
            self.preparing.discard(task)
            if session and profile is not None:
                session.profile.reservations -= 1
            if not session or session.sid not in self.sessions:
                if session and not session.closed:
                    await self.close_session(session)
                elif not session:
                    self.slots.release()

    def contract(self, session):
        translations = []
        for identifier, value in session.translations.items():
            qualities = sorted(value['qualities'], key=int, reverse=True)
            translations.append({'id': identifier, 'name': value['name'], 'default': value['default'],
                                 'qualities': qualities, 'play': {q: f'/play/{session.sid}/{identifier}/{q}.m3u8' for q in qualities}})
        return {'sid': session.sid, 'active_id': session.active_id, 'skip': session.skip,
                'subtitles': session.subtitles, 'translations': translations}

    async def prepare_online(self, body, subject):
        """Compatibility with the site's existing player, only for Alloha."""
        key = (subject, body.client_id) if body.client_id else None
        previous = self.online_clients.get(key)
        started = self.clock()
        cache_key = cache_identity(subject, body.url, body.quality, getattr(body, 'referer', None))
        gate = self.restore_locks.setdefault(cache_key, asyncio.Lock())
        async with gate:
            session = await self.cached_online(cache_key, body, subject) if getattr(body, 'purpose', 'playback') == 'playback' else None
        if not gate.locked() and not getattr(gate, '_waiters', None):
            self.restore_locks.pop(cache_key, None)
        # Replace the same viewer only after preparation succeeds. A failed
        # refresh must leave its old buffered player and lease intact.
        if session is None:
            if previous in self.sessions and self.slots.locked():
                raise HTTPException(503, 'Подключение занято. Текущий поток сохранён.')
            data = await self.resolve(body.url, online_quality=body.quality, referer=getattr(body, 'referer', None),
                                      mode=getattr(body, 'alloha_mode', None))
            session = self.session(data['sid'])
            if getattr(body, 'purpose', 'playback') == 'playback':
                session.cache_key = cache_key
                await cache_io(self.vod.pin, cache_key)
        session.owner = subject
        if previous in self.sessions and previous != session.sid:
            await self.close_session(self.sessions[previous])
        if key:
            self.online_clients[key] = session.sid
        qualities = session.translations[session.active]['qualities']
        quality = max(qualities, key=int) if body.quality == 'best' else self.select_quality(qualities, body.quality)
        session.online_quality = quality
        return {'id': session.sid, 'kind': 'video', 'type': 'hls',
                'url': f'/online/{session.sid}/alloha-playback',
                'expiresIn': self.ttl, 'qualities': session.published_qualities,
                'allohaMode': session.mode, 'sessionRecovery': True, 'playbackTelemetry': session.mode == 'browser' and not session.cache_complete,
                'serverCached': session.cache_complete,
                'subtitles': [{'id': str(i), 'name': t['label'], 'language': t['lang'], 'url': t['src']}
                              for i, t in enumerate(session.subtitles)],
                'sourceIntervals': [{'start': a, 'end': b, 'type': 'op' if i == 0 else 'ed', 'source': 'Alloha'}
                                    for i, (a, b) in enumerate(session.skip)],
                'preparationMs': round((self.clock() - started) * 1000)}

    async def report_playback(self, sid, subject, state):
        session = self.session(sid)
        if session.owner != subject:
            raise HTTPException(404, 'Сессия Alloha недоступна.')
        self.renew(session)
        try:
            await session.source.update_playback({**state, 'quality': session.online_quality})
        except SourceRefused as error:
            await self.failed(session, error, session.iframe)
        return {'received': True, 'expiresIn': max(0, int(session.expires - self.clock()))}

    def rewrite(self, session, text, base):
        if not text.lstrip().startswith('#EXTM3U'):
            raise SourceInvalid('Source returned a non-HLS document')
        playlist = m3u8.loads(text, uri=base)
        # Build the adjacency from each media track separately. Init/key URIs
        # and byte-range playlists must never be treated as complete segments.
        if playlist.is_endlist and playlist.segments and not any(s.byterange for s in playlist.segments):
            for current, following in zip(playlist.segments, playlist.segments[1:]):
                session.next_segments[current.absolute_uri] = following.absolute_uri
        lines, next_manifest = [], False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith('#'):
                kind = ('manifest' if stripped.startswith(('#EXT-X-MEDIA:', '#EXT-X-I-FRAME-STREAM-INF:', '#EXT-X-RENDITION-REPORT:'))
                        else 'key' if stripped.startswith('#EXT-X-KEY:') else 'media')
                line = re.sub(r'URI="([^"\r\n]+)"', lambda m: 'URI="' + self.register(session, urljoin(base, m[1]), kind) + '"', line)
                next_manifest = stripped.startswith('#EXT-X-STREAM-INF:') or next_manifest
            elif stripped:
                line = self.register(session, urljoin(base, stripped), 'manifest' if next_manifest else 'media')
                next_manifest = False
            lines.append(line)
        return '\n'.join(lines) + '\n'

    async def play(self, sid, audio, quality):
        session = self.session(sid)
        self.renew(session)
        value = session.translations.get(audio)
        if not value or not re.fullmatch(r'[1-9]\d{0,3}', quality) or int(quality) > 8640:
            raise HTTPException(404, 'Озвучка или качество отсутствуют в сессии.')
        if audio != session.active:
            async with session.switch_lock:
                self.session(sid)
                iframe = session.iframe
                await self.close_session(session)
                result = await self.resolve(iframe, audio=audio, referer=session.referer, mode=session.mode)
                replacement = self.session(result['sid'])
                selected = self.select_quality(replacement.translations[audio]['qualities'], quality)
                return RedirectResponse(f'/play/{result["sid"]}/{audio}/{selected}.m3u8', status_code=307)
        selected = self.select_quality(value['qualities'], quality)
        try:
            text, final = await self.playlist(session, value['qualities'][selected])
            content = self.rewrite(session, text, final)
            if session.cache_key and not session.cache_started:
                session.cache_started = True
                task = asyncio.create_task(self.warm_vod(session, value['qualities'][selected]))
                session.prefetches.add(task)
                task.add_done_callback(session.prefetches.discard)
            headers = {'Cache-Control': 'no-store', 'X-Alloha-Quality': selected}
            if selected != quality:
                headers['X-Alloha-Degradation'] = 'quality-unavailable'
            return Response(content, media_type='application/vnd.apple.mpegurl', headers=headers)
        except (SourceRefused, SourceInvalid) as error:
            await self.failed(session, error, value['qualities'][selected])

    @staticmethod
    def select_quality(qualities, requested):
        smaller = [q for q in qualities if int(q) <= int(requested)]
        return max(smaller, key=int) if smaller else min(qualities, key=int)

    async def resource(self, sid, resource, byte_range=''):
        session = self.session(sid)
        self.renew(session)
        url = session.resource_urls.get(resource)
        kind = session.resources.get(url)
        if not kind:
            raise HTTPException(404, 'Ресурс отсутствует в плейлисте этой сессии.')
        if byte_range and not RANGE.fullmatch(byte_range):
            raise HTTPException(416, 'Некорректный диапазон.')
        try:
            if kind == 'manifest':
                text, final = await self.playlist(session, url)
                return Response(self.rewrite(session, text, final), media_type='application/vnd.apple.mpegurl', headers={'Cache-Control': 'no-store'})
            started = self.clock()
            session.demands += 1
            try:
                raw, headers, status, _ = await self.transfer(session, url, kind, byte_range)
            finally:
                session.demands -= 1
            self.lookahead(session, url, byte_range)
            outgoing = {'Cache-Control': 'private, max-age=3600', 'X-Content-Type-Options': 'nosniff'}
            outgoing['Server-Timing'] = 'alloha;dur=' + str(round((self.clock()-started)*1000))
            if status == 206:
                if not headers.get('content-range'):
                    raise SourceInvalid('Source omitted the partial response range')
                outgoing['Content-Range'] = headers['content-range']
            if headers.get('accept-ranges') == 'bytes':
                outgoing['Accept-Ranges'] = 'bytes'
            return Response(raw, status_code=status, media_type=headers.get('content-type', 'application/octet-stream'), headers=outgoing)
        except (SourceRefused, SourceInvalid) as error:
            if byte_range and getattr(error, 'status', None) == 416:
                raise HTTPException(416, 'Диапазон отсутствует в этом сегменте.') from None
            await self.failed(session, error, url)


def install(app, service=None):
    service = service or AllohaDelivery()
    app.state.alloha_delivery = service

    @app.get('/resolve')
    async def resolve(iframe: str, referer: str | None = None, mode: str | None = None):
        return await service.resolve(iframe, referer=referer, mode=mode)

    @app.get('/play/{sid}/{audio}/{quality}.m3u8')
    async def play(sid: str, audio: str, quality: str):
        return await service.play(sid, audio, quality)

    @app.get('/hls/{sid}')
    async def hls(sid: str, u: str, request: Request):
        return await service.resource(sid, u, request.headers.get('range', ''))

    return service


@asynccontextmanager
async def lifespan(app):
    app.state.alloha_delivery.start_profile_refresh()
    try:
        yield
    finally:
        await app.state.alloha_delivery.close()


app = FastAPI(title='Alloha delivery', lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv('ALLOWED_ORIGIN', 'https://onikri.github.io')],
                   allow_methods=['GET'], allow_headers=['Range'],
                   expose_headers=['Content-Range', 'X-Alloha-Quality', 'X-Alloha-Degradation', 'Retry-After'])
install(app)
