"""HanimeTV through the owner's Cloudflare Worker (workers/hanime-relay).

HanimeTV answers every request from datacenter addresses, including the Oracle
VM, with a Cloudflare 403 before it processes signed API calls (also documented
by anime-src/hanime-stremio, which uses the same relay design). The server
signs the player handshake itself and sends it, and the short HLS playlists,
through the Worker. Video segments and the AES-128 key are fetched by the
server directly; their CDN serves Oracle normally. Nothing here solves or
bypasses a challenge: if HanimeTV starts challenging the Worker too, playback
reports it instead of retrying.

Configuration (VM .env): HANIME_RELAY_URL=https://<worker>.workers.dev and
HANIME_RELAY_SECRET (the Worker's RELAY_SECRET, at least 32 characters).
"""
import json
import os
import re
import time
from urllib.parse import urljoin, urlsplit

import requests

from source_parser import SourceAccessError, SourceError, SourceTemporaryError, public_url

HANIME_HOSTS = {'hanime.tv', 'www.hanime.tv'}
EPISODE = re.compile(r'/(?:videos/hentai|hentai/video|playlists/[a-zA-Z0-9]+/video)/([A-Za-z0-9._~-]{1,200})/?')
PLAYLIST = re.compile(r'/hls/\d{1,10}/[A-Za-z0-9]{16,600}')
BROWSER = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36'
PLAYBACK_HEADERS = {'User-Agent': BROWSER, 'Referer': 'https://hanime.tv/', 'Origin': 'https://hanime.tv'}
MAX_PLAYLIST = 1024 * 1024
HINT = ('HanimeTV не пускает сервер Oracle (проверка Cloudflare по адресу дата-центра). '
        'Нужен посредник Cloudflare Worker: задай HANIME_RELAY_URL и HANIME_RELAY_SECRET на сервере.')


def settings():
    url = os.getenv('HANIME_RELAY_URL', '').strip().rstrip('/')
    secret = os.getenv('HANIME_RELAY_SECRET', '')
    parts = urlsplit(url)
    if (not url or len(secret) < 32 or parts.scheme != 'https' or not parts.hostname or parts.username
            or parts.password or parts.path or parts.query or parts.fragment):
        return None
    return url, secret


def session():
    value = requests.Session()
    value.trust_env = False
    return value


def call(method, path, *, headers=None, data=None):
    config = settings()
    if not config:
        raise SourceError(HINT)
    base, secret = config
    with session() as client:
        try:
            response = client.request(method, base + path, headers={**(headers or {}), 'Authorization': 'Bearer ' + secret},
                                      data=data, timeout=(4, 15), allow_redirects=False, stream=True)
        except requests.RequestException:
            raise SourceTemporaryError('Посредник HanimeTV не ответил. Повтори позже.') from None
        with response:
            body = response.raw.read(MAX_PLAYLIST + 1, decode_content=True)
            if len(body) > MAX_PLAYLIST:
                raise SourceError('Посредник HanimeTV вернул слишком большой ответ.')
            if response.headers.get('x-upstream-challenge'):
                raise SourceAccessError('HanimeTV начал проверять и посредника Cloudflare Worker.')
            if response.status_code == 401 and not response.headers.get('x-token'):
                if body.strip() == b'Unauthorized':
                    raise SourceError('Посредник HanimeTV не принял секрет сервера. Проверь HANIME_RELAY_SECRET.')
            return response.status_code, response.headers, body


def slug(url):
    parts = urlsplit(public_url(url, resolve_dns=False))
    match = EPISODE.fullmatch(parts.path) if parts.hostname in HANIME_HOSTS and not parts.query else None
    if not match:
        raise SourceError('Нужна ссылка на конкретный выпуск HanimeTV.')
    return match[1]


def quality_of(source):
    for value in (source.get('height'), source.get('label')):
        digits = re.search(r'\d{3,4}', str(value or ''))
        if digits and 100 <= int(digits[0]) <= 4320:
            return int(digits[0])
    return None


def resolve(url):
    """Episode URL -> published HLS sources, via the signed player handshake."""
    from hanime_player import extractor_class
    player = extractor_class()
    signature, stamp = player._generate_credentials_local()
    token = player._digest_token({'timestamp_unix': int(time.time()), 'directive': 'htv_player_handshake', 'slug': slug(url)})
    status, headers, _ = call('POST', '/handshake', data=json.dumps({'token': token}).encode(), headers={
        'Content-Type': 'application/json', 'Accept': 'application/json', 'X-Csrf-Token': 'null',
        'X-Signature': signature, 'X-Time': str(stamp), 'X-Signature-Version': 'web2'})
    if status != 200 or not headers.get('x-token'):
        raise SourceError(f'HanimeTV не выдал поток (HTTP {status}).')
    try:
        manifest = player._parse_token(headers['x-token'])
    except Exception:
        raise SourceError('HanimeTV изменил формат ответа плеера.') from None
    streams = {}
    for source in manifest.get('sources') or []:
        if not isinstance(source, dict) or source.get('kind') != 'normal':
            continue  # Premium sources need an account and are not used.
        address = urljoin('https://hanime.tv', str(source.get('src') or source.get('url') or ''))
        parts = urlsplit(address)
        if parts.scheme != 'https' or parts.hostname not in HANIME_HOSTS or parts.query or not PLAYLIST.fullmatch(parts.path):
            continue
        quality = quality_of(source)
        streams.setdefault(quality, {'url': address, 'type': 'hls', 'quality': quality, 'headers': dict(PLAYBACK_HEADERS)})
    if not streams:
        raise SourceError('HanimeTV не опубликовал бесплатный поток для этого выпуска.')
    return sorted(streams.values(), key=lambda value: value['quality'] or 0, reverse=True)


class RelayedResponse:
    """The subset of a requests response that PublicHttp callers read."""
    status_code = 200
    encoding = 'utf-8'

    def __init__(self, data, url):
        self.data = data
        self.url = url
        self.headers = {'Content-Type': 'application/vnd.apple.mpegurl', 'Content-Length': str(len(data))}
        self.raw = self

    def iter_content(self, size=65536, decode_unicode=False):
        for offset in range(0, len(self.data), size):
            yield self.data[offset:offset + size]

    def read(self, size=-1, decode_content=False):
        value = self.data if size is None or size < 0 else self.data[:size]
        self.data = self.data[len(value):]
        return value

    def close(self):
        pass


def route(url, headers=None):
    """PublicHttp hook: tokenised hanime.tv/hls playlists come through the Worker."""
    parts = urlsplit(url)
    if parts.hostname not in HANIME_HOSTS or parts.query or not PLAYLIST.fullmatch(parts.path):
        return None
    status, _, body = call('GET', parts.path)
    if status != 200 or not body.lstrip().startswith(b'#EXTM3U'):
        raise SourceError(f'HanimeTV не отдал плейлист (HTTP {status}).')
    return RelayedResponse(body, url), url


def install():
    import source_parser
    source_parser.RELAY_ROUTE = route
