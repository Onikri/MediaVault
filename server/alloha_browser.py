"""A live, isolated Alloha browser. All source I/O uses its native network stack."""
import asyncio
import base64
import contextlib
import html
import json
import secrets
import threading
import time
from urllib.parse import urlsplit

from browser_player import browser_destination, browser_paths

_pace_lock = threading.Lock()
_next_request = 0


def request_delay():
    global _next_request
    with _pace_lock:
        now = time.monotonic()
        delay = max(0, _next_request - now)
        _next_request = max(now, _next_request) + .5
        return delay


class SourceRefused(Exception):
    pass


class SourceInvalid(Exception):
    def __init__(self, message, *, status=None):
        super().__init__(message)
        self.status = status


INIT = """() => {
    const sockets = new Set();
    const Native = window.WebSocket;
    const send = Native.prototype.send;
    window.__allohaDelivery = {
        closed: false,
        playback: null,
        updatePlayback(value) {
            const before = this.playback;
            this.playback = {...value, received: Date.now()};
            const stopped = value.paused || value.seeking || value.buffering;
            const wasStopped = !before || before.paused || before.seeking || before.buffering;
            this.heartbeat(value.ended ? 'ended' : stopped ? 'paused' : wasStopped ? 'resumed' : 'playing');
        },
        heartbeat(event) {
            if (this.closed || typeof player === 'undefined') return;
            const source = player.currentSource;
            if (!source) return;
            const state = this.playback;
            if (state?.ended && !event) return;
            const stopped = !state || state.paused || state.seeking || state.buffering || Date.now() - state.received > 90000;
            const type = event || (state?.ended ? 'ended' : stopped ? 'paused' : 'playing');
            for (const socket of sockets) {
                if (socket.readyState !== Native.OPEN) continue;
                send.call(socket, JSON.stringify({type,
                    current_time: Math.floor(state?.time || 0),
                    resolution: String(state?.quality || player.quality || ''), track_id: String(source.audioId),
                    speed: state?.rate || 1, subtitle: player.currentTrack || 0, ts: Date.now()}));
            }
        },
        close() {
            this.closed = true;
            for (const socket of sockets) socket.close();
            sockets.clear();
        }
    };
    window.WebSocket = new Proxy(Native, {construct(target, args) {
        const url = new URL(args[0], location.href);
        // Validate before the browser can initiate a WebSocket handshake.
        if (url.protocol !== 'wss:' || url.host !== location.host)
            throw new Error('Unsupported Alloha WebSocket destination');
        const socket = Reflect.construct(target, args);
        sockets.add(socket);
        socket.addEventListener('close', () => sockets.delete(socket));
        return socket;
    }});
}"""

FETCH = """async ({url, headers, maximum}) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 25000);
    try {
        const response = await fetch(url, {headers, signal: controller.signal, cache: 'no-store'});
        const result = {status: response.status, url: response.url,
            headers: Object.fromEntries(response.headers.entries()), data: ''};
        if (!response.ok) { await response.body?.cancel(); return result; }
        const reader = response.body.getReader();
        const blocks = []; let size = 0;
        try {
            for (;;) {
                const {done, value} = await reader.read();
                if (done) break;
                size += value.length;
                if (size > maximum) throw new Error('Alloha resource exceeds limit');
                blocks.push(value);
            }
        } finally { await reader.cancel(); }
        let binary = '';
        for (const block of blocks)
            for (let i = 0; i < block.length; i += 16384)
                binary += String.fromCharCode(...block.subarray(i, i + 16384));
        result.data = btoa(binary);
        return result;
    } finally { clearTimeout(timer); }
}"""


class NativeSession:
    def __init__(self, profile, iframe):
        self.profile, self.iframe = profile, iframe
        self.browser = self.context = self.driver = self.page = self.fetch_page = self.frame = None
        self.token_headers = {}
        self.sources = []
        self.active = ''
        self.active_id = secrets.token_urlsafe(20)
        self.skip, self.subtitles = [], []
        self.closed = False
        self.socket_closed = False
        self.sockets = set()
        self.tasks = set()
        self.allowed = set()
        self.request_lock = asyncio.Lock()
        self.heartbeat = None
        self.validated_hosts = {}
        self.response_headers = {}
        self.response_status = {}
        self.bootstrap_denied = False
        self.bootstrap_status = None
        self.bootstrap_failed = asyncio.Event()

    async def validate(self, url):
        host = urlsplit(url).hostname
        resolve = self.validated_hosts.get(host, 0) < time.monotonic()
        value = await asyncio.to_thread(browser_destination, url, resolve_dns=resolve)
        if resolve:
            self.validated_hosts[host] = time.monotonic() + 30
        return value

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def socket(self, socket):
        self.socket_closed = False
        self.sockets.add(socket)
        def received(payload):
            try:
                message = json.loads(payload)
                if not isinstance(message, dict):
                    return
                if message.get('type') == 'config_update':
                    token = message.get('edge_hash')
                    if isinstance(token, str) and 0 < len(token) <= 8192 and '\n' not in token and '\r' not in token:
                        self.token_headers['accepts-controls'] = token
            except (TypeError, ValueError):
                pass
        def closed():
            self.sockets.discard(socket)
            if not self.sockets:
                self.socket_closed = True
        socket.on('framereceived', received)
        socket.on('close', closed)

    async def observe(self, response):
        parts = urlsplit(response.url)
        if (parts.hostname == urlsplit(self.iframe).hostname
                and response.request.resource_type == 'document'
                and response.status in {401, 403, 404, 410, 429}):
            self.bootstrap_status = response.status
            self.bootstrap_failed.set()
        if parts.hostname == urlsplit(self.iframe).hostname and response.status in {401, 403, 429}:
            self.bootstrap_denied = True
        if parts.hostname != urlsplit(self.iframe).hostname or not parts.path.startswith('/bnsi/'):
            return
        try:
            data = await response.json()
            if isinstance(data, dict) and isinstance(data.get('hlsSource'), list):
                self.sources = data['hlsSource'][:40]
                if isinstance(data.get('active_id'), (str, int)):
                    self.active_id = str(data['active_id'])[:200]
        except Exception:
            pass  # DOM extraction below also reads the player's live source list.

    async def open(self, audio=None):
        try:
            await self._open(audio)
        except Exception:
            if self.bootstrap_denied:
                raise SourceRefused('Alloha refused its session bootstrap') from None
            raise

    async def _open(self, audio):
        from playwright.async_api import async_playwright
        browser_paths()
        await self.validate(self.iframe)
        self.driver = await async_playwright().start()
        self.browser = await self.driver.chromium.launch(
            executable_path=self.profile.executable, headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking'])
        if self.browser.version != self.profile.version:
            raise SourceInvalid('Browser changed since the release check')
        # No UA, Client Hint, TLS, HTTP/2 or Origin overrides.
        self.context = await self.browser.new_context(service_workers='block', accept_downloads=False)
        await self.context.add_init_script('(' + INIT + ')()')
        self.page = await self.context.new_page()
        self.fetch_page = await self.context.new_page()
        origin = urlsplit(self.iframe)
        wrapper = f'{origin.scheme}://{origin.netloc}/__mediavault_alloha_{secrets.token_hex(12)}'
        async def guard(route):
            request, url = route.request, route.request.url
            if url == wrapper:
                return await route.fulfill(content_type='text/html', body='<iframe allow="autoplay" src="' + html.escape(self.iframe, quote=True) + '"></iframe>')
            if url == wrapper + '/fetch':
                return await route.fulfill(content_type='text/html', body='<!doctype html><title>Alloha transport</title>')
            try:
                await self.validate(url)
            except Exception:
                return await route.abort()
            if request.frame == self.fetch_page.main_frame:
                previous = request.redirected_from
                if previous and previous.url in self.allowed:
                    self.allowed.add(url)
                return await route.continue_() if url in self.allowed else await route.abort()
            path = urlsplit(url).path.lower()
            if request.resource_type in {'image', 'font', 'media'} or path.endswith(('.m3u8', '.ts', '.m4s', '.mp4', '.aac')):
                for key, value in (await request.all_headers()).items():
                    if key in {'accepts-controls', 'authorizations', 'authorization'}:
                        self.token_headers[key] = value
                return await route.abort()
            return await route.continue_()
        await self.context.route('**/*', guard)
        async def network_response(response):
            self.response_status[response.url] = response.status
            self.response_headers[response.url] = await response.all_headers()
        self.fetch_page.on('response', lambda response: self.spawn(network_response(response)))
        self.page.on('response', lambda response: self.spawn(self.observe(response)))
        self.page.on('websocket', self.socket)
        self.page.on('popup', lambda popup: self.spawn(popup.close()))
        await self.page.goto(wrapper, wait_until='domcontentloaded', timeout=25000)
        element = await self.page.wait_for_selector('iframe', timeout=5000)
        self.frame = await element.content_frame()
        await self.wait_player()
        if audio is not None:
            labels = await self.frame.evaluate("() => (player._wsHlsSource || player.config.hlsSource || []).map(s => ({id:String(s.audioId),label:s.label}))")
            target = next((row for row in labels if row['id'] == audio), None)
            if not target:
                raise SourceInvalid('Alloha no longer publishes this audio track')
            await self.frame.locator('button[data-allplay="audio"]').filter(has_text=target['label']).first.evaluate('node => node.click()')
            await self.frame.wait_for_function('id => String(player.currentSource?.audioId) === id', arg=audio, timeout=10000)
        data = await self.frame.evaluate("""() => ({active:String(player.currentSource.audioId),
            sources:player._wsHlsSource || player.config.hlsSource || [player.currentSource],
            skip:player.skipTime?.pointsSkip || [],
            tracks:Array.from(document.querySelectorAll('video track[src]')).map(t=>({label:t.label,lang:t.srclang,src:t.src}))})""")
        self.active = data['active']
        self.sources = data['sources'] or self.sources
        self.skip, self.subtitles = data['skip'], data['tracks']
        await self.frame.evaluate("() => {player.hls?.stopLoad(); player.media?.pause();}")
        await self.fetch_page.goto(wrapper + '/fetch', wait_until='domcontentloaded')
        if not self.sockets:
            raise SourceInvalid('Alloha did not open its session WebSocket')
        self.heartbeat = asyncio.create_task(self.keepalive())

    async def wait_player(self):
        ready = asyncio.create_task(self.frame.wait_for_function(
            "() => typeof player !== 'undefined' && player.currentSource?.quality", timeout=25000))
        failed = asyncio.create_task(self.bootstrap_failed.wait())
        try:
            await asyncio.wait([ready, failed], return_when=asyncio.FIRST_COMPLETED)
            if self.bootstrap_status in {401, 403, 429}:
                raise SourceRefused('Alloha refused its session bootstrap')
            if self.bootstrap_status in {404, 410}:
                raise SourceInvalid('Alloha iframe no longer exists', status=self.bootstrap_status)
            await ready
        finally:
            for task in (ready, failed):
                if not task.done():
                    task.cancel()
            await asyncio.gather(ready, failed, return_exceptions=True)

    async def keepalive(self):
        try:
            while not self.closed:
                await self.frame.evaluate('() => window.__allohaDelivery.heartbeat()')
                await asyncio.sleep(15)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.socket_closed = True

    async def metadata(self):
        return {'active_id': self.active_id, 'active': self.active, 'sources': self.sources,
                'skip': self.skip, 'subtitles': self.subtitles}

    async def update_playback(self, state):
        if self.closed or self.socket_closed:
            raise SourceRefused('Source session WebSocket closed')
        try:
            await asyncio.wait_for(self.frame.evaluate('value => window.__allohaDelivery.updatePlayback(value)', state), 5)
        except Exception as error:
            raise SourceRefused('Source session no longer accepts playback state') from error

    async def fetch(self, url, byte_range='', maximum=32 * 1024 * 1024):
        if self.closed or self.socket_closed:
            raise SourceRefused('Source session WebSocket closed')
        url = await self.validate(url)
        self.allowed.add(url)
        headers = dict(self.token_headers)
        if byte_range:
            headers['Range'] = byte_range
        # Serial native transfers avoid unbounded body copies and source bursts.
        async with self.request_lock:
            try:
                await asyncio.sleep(request_delay())
                self.response_headers.pop(url, None)
                self.response_status.pop(url, None)
                result = await self.fetch_page.evaluate(FETCH, {'url': url, 'headers': headers, 'maximum': maximum})
                # Browser JS only exposes CORS-safe headers. DevTools also sees
                # Content-Range, which the proxy needs for native byte ranges.
                result['headers'].update(self.response_headers.pop(result['url'], {}))
            except Exception as error:
                if self.response_status.get(url) in {401, 403, 429}:
                    raise SourceRefused('Source refused the browser media request') from None
                raise SourceInvalid('Source browser request failed') from error
        if result['status'] in {401, 403, 429}:
            raise SourceRefused(f'Source returned HTTP {result["status"]}')
        if not 200 <= result['status'] < 300:
            raise SourceInvalid(f'Source returned HTTP {result["status"]}', status=result['status'])
        return base64.b64decode(result['data'], validate=True), result['headers'], result['status'], result['url']

    async def close(self):
        if self.closed:
            return
        self.closed = True
        if self.heartbeat:
            self.heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.heartbeat
        if self.frame:
            with contextlib.suppress(Exception):
                await self.frame.evaluate('() => window.__allohaDelivery.close()')
        if self.context:
            with contextlib.suppress(Exception):
                await self.context.close()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.browser:
            with contextlib.suppress(Exception):
                await self.browser.close()
        if self.driver:
            with contextlib.suppress(Exception):
                await self.driver.stop()
