"""HTTP transport for Alloha's published iframe and BNSI playback API.

Protocol reference: Lampac NextGen PR #232, commit 0a0cfa5 (AllohaBorth.cs).
The bit permutations below are expressed as index maps, independently of the
reference implementation. The transport does not start a browser or WebSocket.
"""
import asyncio
from collections import Counter
import hashlib
from html.parser import HTMLParser
import json
import math
import re
from urllib.parse import parse_qs, quote, urljoin, urlsplit

import httpx

from alloha_browser import SourceInvalid, SourceRefused, browser_destination
from source_parser import is_alloha_player


MODES = {'bnsi', 'browser'}
IDENTIFIER = re.compile(r'[A-Za-z0-9_-]{1,100}')
FILE_LIST = re.compile(r"""\bfileList\s*=\s*JSON\.parse\(\s*(['"])((?:\\.|(?!\1).)*?)\1\s*\)""", re.S)
FINGERPRINT = hashlib.sha256(b'fingerprint-alloha').hexdigest()
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'


def ungroup(text, indices, descending=False):
    cursor, chunks = 0, {}
    for index, size in sorted(Counter(indices).items(), reverse=descending):
        chunks[index] = iter(text[cursor:cursor + size])
        cursor += size
    return ''.join(next(chunks[index]) for index in indices)


def borth(text):
    if not text:
        return ''
    size = len(text)
    first = ungroup(text, [i.bit_length() for i in range(size)], True)
    second = ungroup(first, [(i & -i).bit_length()-1 if i else (size-1).bit_length() for i in range(size)])
    prime = size + 1
    while any(prime % i == 0 for i in range(2, math.isqrt(prime) + 1)):
        prime += 1
    order = ((2*i) % prime for i in range(1, prime+1)) if size > 1 else iter((0,))
    result = [''] * size
    for position, char in zip((i for i in order if i < size), second):
        result[position] = char
    return FINGERPRINT + '|' + ''.join(result)


class Viewport(HTMLParser):
    content = ''

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            attributes = dict(attrs)
            if attributes.get('name') == 'viewporti':
                self.content = attributes.get('content') or ''


def iframe_data(text, params):
    meta = Viewport()
    meta.feed(text)
    match = FILE_LIST.search(text)
    if not re.fullmatch(r'[!-~]{1,1024}', meta.content) or not match:
        raise SourceInvalid('Alloha iframe does not contain a BNSI configuration')
    try:
        raw = match[2]
        try:
            table = json.loads(raw)
        except ValueError:
            table = json.loads(re.sub(r'\\([\\\x27\x22])', r'\1', raw))
        active = table.get('active') or {}
        translation = params.get('translation', [''])[0]
        season = params.get('season', [''])[0]
        episode = params.get('episode', [''])[0]
        published = table.get('all') or {}
        row = active
        if translation:
            if table.get('type') == 'movie':
                releases = (published.get(active.get('typeList')) or {}).get('t' + translation) or {}
                rows = [item for item in releases.values() if isinstance(item, dict) and item.get('id')]
                row = next((v for v in rows if str(v['id']) == str(active.get('id'))), rows[0] if rows else {})
            elif season and episode:
                episode_rows = (published.get(season) or {}).get(episode) or {}
                row = episode_rows.get('t' + translation) or {}
            if not row or (row is active and str(row.get('id_translation')) != translation):
                raise SourceInvalid('Selected Alloha translation is not published', status=404)
        active_id = str(row.get('id') or '')
        catalog_audio = translation or str(row.get('id_translation') or 66)
    except (TypeError, AttributeError, ValueError) as error:
        raise SourceInvalid('Invalid Alloha iframe configuration') from error
    if not IDENTIFIER.fullmatch(active_id) or not re.fullmatch(r'\d{1,10}', catalog_audio):
        raise SourceInvalid('Invalid Alloha release or translation')
    return meta.content, active_id, catalog_audio


def time_intervals(value):
    if isinstance(value, str):
        value = [part.split('-') for part in value.split(',')]
    if isinstance(value, dict):
        value = value.get('pointsSkip')
    result = []
    for interval in value[:40] if isinstance(value, list) else []:
        if isinstance(interval, (list, tuple)) and len(interval) == 2:
            try:
                start, end = map(float, interval)
            except (ValueError, TypeError):
                continue
            if 0 <= start < end <= 86400:
                result.append([start, end])
    return result


class BnsiSession:
    playback_telemetry = False

    def __init__(self, iframe, *, referer=None, client=None):
        self.iframe, self.referer = iframe, referer
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(12, connect=5), trust_env=False,
                                                  headers={'User-Agent': USER_AGENT})
        self.hosts = set()
        self.origin = ''

    async def request(self, url, *, method='GET', headers=None, data=None, maximum=4*1024**2,
                      redirects=0, iframe=False, sample=False):
        try:
            for i in range(redirects + 1):
                host = urlsplit(url).hostname
                if iframe and not is_alloha_player(url):
                    raise SourceInvalid('Alloha iframe redirected outside the player')
                url = await asyncio.to_thread(browser_destination, url, resolve_dns=host not in self.hosts)
                if len(self.hosts) >= 32 and host not in self.hosts:
                    raise SourceInvalid('Too many Alloha resource hosts')
                self.hosts.add(host)
                async with self.client.stream(method, url, headers=headers, data=data, follow_redirects=False) as reply:
                    if reply.is_redirect and i < redirects and reply.headers.get('location'):
                        url = urljoin(url, reply.headers['location'])
                        continue
                    status = reply.status_code
                    if status in {401, 403, 429}:
                        reason = reply.headers.get('x-vd', '')
                        raise SourceRefused('Alloha refused HTTP transport', status=status,
                                            reason=reason if re.fullmatch(r'[A-Za-z0-9_-]{1,50}',reason) else None)
                    if not 200 <= status < 300:
                        raise SourceInvalid('Alloha HTTP transport failed', status=status)
                    content = bytearray()
                    async for chunk in reply.aiter_bytes(chunk_size=65536):
                        if len(content) + len(chunk) > maximum and not sample:
                            raise SourceInvalid('Alloha resource exceeds the allowed size')
                        content.extend(chunk[:maximum-len(content)])
                        if sample and len(content) == maximum:
                            break
                    return bytes(content), dict(reply.headers), status, str(reply.url)
        except (httpx.HTTPError, ValueError) as error:
            raise SourceInvalid('Alloha HTTP transport failed') from error
        raise SourceInvalid('Alloha resource redirected too many times')

    async def open(self, audio=None):
        parts = urlsplit(self.iframe)
        origin = f'{parts.scheme}://{parts.netloc}'
        raw, _, _, final = await self.request(self.iframe, headers={'Referer': self.referer or origin+'/'},
                                              iframe=True, redirects=3)
        parts = urlsplit(final)
        self.origin = f'{parts.scheme}://{parts.netloc}'
        params = parse_qs(parts.query)
        token = params.get('token', [''])[0]
        if not token or len(token) > 1024:
            raise SourceInvalid('Alloha iframe does not carry a playback token')
        viewport, act_id, catalog_audio = iframe_data(raw.decode('utf-8', 'replace'), params)
        payload, _, _, _ = await self.request(self.origin+'/bnsi/movies/'+quote(act_id, safe=''), method='POST',
            headers={'Origin': self.origin, 'Referer': final, 'Borth': borth(viewport),
                     'Accept': 'application/json, text/plain, */*', 'X-Requested-With': 'XMLHttpRequest'},
            data={'token': token, 'av1': 'true', 'autoplay': '0', 'audio': catalog_audio})
        try:
            body = json.loads(payload)
        except (ValueError, UnicodeError) as error:
            raise SourceInvalid('Alloha returned invalid BNSI metadata') from error
        if not isinstance(body, dict) or not isinstance(body.get('hlsSource'), list):
            raise SourceInvalid('Alloha returned no BNSI media')
        sources = [row for row in body['hlsSource'][:40] if isinstance(row, dict)
                   and IDENTIFIER.fullmatch(str(row.get('audioId', ''))) and isinstance(row.get('quality'), dict)]
        active = (next((row for row in sources if str(row['audioId']) == audio), None) if audio is not None else
                  next((row for row in sources if row.get('default')), sources[0] if sources else None))
        if active is None:
            raise SourceInvalid('Alloha no longer publishes this audio track', status=404)
        tracks = []
        for track in (body['tracks'][:40] if isinstance(body.get('tracks'), list) else []):
            if not isinstance(track, dict) or track.get('kind') == 'thumbnails':
                continue
            src = track.get('file') or track.get('src') or track.get('url')
            if isinstance(src, str) and urlsplit(src).path.lower().endswith('.vtt'):
                tracks.append({'src': urljoin(final, src), 'label': track.get('label'),
                               'lang': track.get('lang') or track.get('srclang')})
        self.data = {'active_id': act_id, 'active': str(active['audioId']), 'sources': sources,
                     'skip': time_intervals(body.get('skipTime')), 'subtitles': tracks}

    async def metadata(self):
        return self.data

    async def fetch(self, url, byte_range='', maximum=32*1024**2, *, probe=False):
        headers = {'Origin': self.origin, 'Referer': self.origin+'/'}
        if byte_range:
            headers['Range'] = byte_range
        return await self.request(url, headers=headers, maximum=65536 if probe else maximum, redirects=4, sample=probe)

    async def update_playback(self, _state):
        pass  # Direct BNSI has no playback-state channel.

    async def close(self):
        await self.client.aclose()
