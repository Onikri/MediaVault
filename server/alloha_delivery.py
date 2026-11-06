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
from alloha_profiles import NativeProfiles
from source_parser import is_alloha_player, public_url

logger = logging.getLogger('mediavault.alloha')
TTL = 900
RANGE = re.compile(r'bytes=(?:\d+-\d*|-\d+)$')
IDENTIFIER = re.compile(r'[A-Za-z0-9_-]{1,100}$')


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
    published_qualities: list = field(default_factory=list)
    closed: bool = False
    switch_lock: object = field(default_factory=asyncio.Lock)
    io_lock: object = field(default_factory=asyncio.Lock)


class AllohaDelivery:
    def __init__(self, directory=None, *, profiles=None, factory=NativeSession, clock=time.monotonic,
                 queue_timeout=30, session_ttl=TTL):
        root = Path(directory or Path(os.getenv('DATA_DIR') or Path(__file__).resolve().parents[1]) / '.codex-local' / 'alloha-delivery')
        self.profiles = profiles or NativeProfiles(root / 'profiles', clock=clock)
        self.cache = SegmentCache(root / 'segments')
        self.factory, self.clock = factory, clock
        self.queue_timeout, self.ttl = queue_timeout, session_ttl
        self.sessions = {}
        self.slots = asyncio.Semaphore(2)
        self.external_address = os.getenv('ALLOHA_EXTERNAL_ADDRESS', '')
        self.reaper = None
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

    async def close_session(self, session):
        if session.closed:
            return
        session.closed = True
        self.sessions.pop(session.sid, None)
        for key, value in list(self.online_clients.items()):
            if value == session.sid:
                self.online_clients.pop(key, None)
        async def close_source():
            try:
                await session.source.close()
            finally:
                session.profile.in_use -= 1
                self.slots.release()
        task = asyncio.create_task(close_source())
        self.closures.add(task)
        task.add_done_callback(self.closures.discard)
        await asyncio.shield(task)

    async def close(self):
        self.stopping = True
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
        if self.log_handler:
            self.logger.removeHandler(self.log_handler)
            self.log_handler.close()
            self.log_handler = None

    def log(self, session, status, url):
        self.logger.info(json.dumps({'sid': session.sid, 'profile': session.profile.id,
                                'external_address': session.address, 'status': status,
                                'source_host': urlsplit(url).hostname}, ensure_ascii=True))

    async def failed(self, session, error, url):
        if not session.closed:
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

    async def fetch(self, session, url, *, kind='media', byte_range='', probe=False):
        if kind != 'manifest' and not probe:
            cached = await asyncio.to_thread(self.cache.get, url, byte_range)
            if cached:
                self.log(session, cached[2], url)
                return cached
        value = await session.source.fetch(url, byte_range)
        raw, headers, status, final = value
        self.log(session, status, final)
        if kind == 'manifest':
            if not raw.lstrip().startswith(b'#EXTM3U') or len(raw) > 4 * 1024 * 1024:
                raise SourceInvalid('Source returned a non-HLS document')
        elif kind == 'subtitle':
            if not raw.lstrip().startswith(b'WEBVTT'):
                raise SourceInvalid('Source returned invalid subtitles')
        else:
            media(raw, headers)
        if kind != 'manifest' and not probe:
            await asyncio.to_thread(self.cache.put, url, byte_range, value)
        return value

    async def playlist(self, session, url):
        cached = session.manifests.get(url)
        if cached and cached[0] > self.clock():
            return cached[1], cached[2]
        raw, _, _, final = await self.fetch(session, url, kind='manifest')
        text = raw.decode('utf-8-sig')
        session.manifests[url] = (self.clock() + 20, text, final)
        return text, final

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

    async def resolve(self, iframe, *, audio=None, online_quality=None):
        try:
            iframe = public_url(iframe, resolve_dns=False)
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
            try:
                await self.profiles.refresh()
            except Exception:
                # A verified, unchanged profile may continue during release-server outages.
                if not self.profiles.profiles:
                    raise HTTPException(409, 'Нет проверенного профиля Alloha.', headers={'Retry-After': '120'}) from None
            profile = self.profiles.choose(iframe)
            if not profile:
                raise HTTPException(409, 'Профили Alloha временно недоступны.', headers={'Retry-After': '120'})
            source = self.factory(profile, iframe)
            session = DeliverySession(secrets.token_urlsafe(32), iframe, profile, source,
                                      self.clock() + self.ttl, self.external_address)
            profile.reservations += 1
            profile.in_use += 1
            await source.open(audio)
            data = await source.metadata()
            session.active, session.active_id = str(data['active']), str(data['active_id'])
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
                if online_quality is not None and published:
                    session.published_qualities = sorted(map(int, published), reverse=True)
                    selected = (max(published, key=int) if online_quality == 'best'
                                else self.select_quality(published, online_quality))
                    published = {selected: published[selected]}
                for label, url in published.items():
                    await self.ready(session, url, label)
                    self.register(session, url, 'manifest')
                    qualities[label] = url
                if qualities:
                    session.translations[identifier] = {'name': str(value.get('label') or identifier)[:160],
                                                         'default': identifier == session.active, 'qualities': qualities}
            if session.active not in session.translations:
                raise SourceInvalid('Active audio has no ready media')
            for interval in data.get('skip', []):
                if (isinstance(interval, (list, tuple)) and len(interval) == 2
                        and all(isinstance(n, (float, int)) for n in interval) and 0 <= interval[0] < interval[1] <= 86400):
                    session.skip.append(list(interval))
            for track in data.get('subtitles', [])[:40]:
                session.subtitles.append({'label': str(track.get('label') or 'Субтитры')[:160],
                                          'lang': str(track.get('lang') or 'und')[:20],
                                          'src': self.register(session, track['src'], 'subtitle')})
            self.profiles.ready(profile)
            session.expires = self.clock() + self.ttl
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
            if session:
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
        if previous in self.sessions:
            await self.close_session(self.sessions[previous])
        started = self.clock()
        data = await self.resolve(body.url, online_quality=body.quality)
        session = self.session(data['sid'])
        if key:
            self.online_clients[key] = session.sid
        qualities = session.translations[session.active]['qualities']
        quality = max(qualities, key=int) if body.quality == 'best' else self.select_quality(qualities, body.quality)
        session.online_quality = quality
        return {'id': session.sid, 'kind': 'video', 'type': 'hls',
                'url': f'/online/{session.sid}/alloha-playback',
                'expiresIn': self.ttl, 'qualities': session.published_qualities,
                'subtitles': [{'id': str(i), 'name': t['label'], 'language': t['lang'], 'url': t['src']}
                              for i, t in enumerate(session.subtitles)],
                'sourceIntervals': [{'start': a, 'end': b, 'type': 'op' if i == 0 else 'ed', 'source': 'Alloha'}
                                    for i, (a, b) in enumerate(session.skip)],
                'preparationMs': round((self.clock() - started) * 1000)}

    def rewrite(self, session, text, base):
        if not text.lstrip().startswith('#EXTM3U'):
            raise SourceInvalid('Source returned a non-HLS document')
        lines, next_manifest = [], False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith('#'):
                kind = 'manifest' if stripped.startswith(('#EXT-X-MEDIA:', '#EXT-X-I-FRAME-STREAM-INF:', '#EXT-X-RENDITION-REPORT:')) else 'media'
                line = re.sub(r'URI="([^"\r\n]+)"', lambda m: 'URI="' + self.register(session, urljoin(base, m[1]), kind) + '"', line)
                next_manifest = stripped.startswith('#EXT-X-STREAM-INF:') or next_manifest
            elif stripped:
                line = self.register(session, urljoin(base, stripped), 'manifest' if next_manifest else 'media')
                next_manifest = False
            lines.append(line)
        return '\n'.join(lines) + '\n'

    async def play(self, sid, audio, quality):
        session = self.session(sid)
        value = session.translations.get(audio)
        if not value or not re.fullmatch(r'[1-9]\d{0,3}', quality) or int(quality) > 8640:
            raise HTTPException(404, 'Озвучка или качество отсутствуют в сессии.')
        if audio != session.active:
            async with session.switch_lock:
                self.session(sid)
                iframe = session.iframe
                await self.close_session(session)
                result = await self.resolve(iframe, audio=audio)
                replacement = self.session(result['sid'])
                selected = self.select_quality(replacement.translations[audio]['qualities'], quality)
                return RedirectResponse(f'/play/{result["sid"]}/{audio}/{selected}.m3u8', status_code=307)
        selected = self.select_quality(value['qualities'], quality)
        try:
            text, final = await self.playlist(session, value['qualities'][selected])
            content = self.rewrite(session, text, final)
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
            async with session.io_lock:
                self.session(sid)
                raw, headers, status, _ = await self.fetch(session, url, kind=kind, byte_range=byte_range)
            outgoing = {'Cache-Control': 'private, max-age=3600', 'X-Content-Type-Options': 'nosniff'}
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
    async def resolve(iframe: str):
        return await service.resolve(iframe)

    @app.get('/play/{sid}/{audio}/{quality}.m3u8')
    async def play(sid: str, audio: str, quality: str):
        return await service.play(sid, audio, quality)

    @app.get('/hls/{sid}')
    async def hls(sid: str, u: str, request: Request):
        return await service.resource(sid, u, request.headers.get('range', ''))

    return service


@asynccontextmanager
async def lifespan(app):
    try:
        yield
    finally:
        await app.state.alloha_delivery.close()


app = FastAPI(title='Alloha delivery', lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv('ALLOWED_ORIGIN', 'https://onikri.github.io')],
                   allow_methods=['GET'], allow_headers=['Range'],
                   expose_headers=['Content-Range', 'X-Alloha-Quality', 'X-Alloha-Degradation', 'Retry-After'])
install(app)
