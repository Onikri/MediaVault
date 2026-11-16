"""Native InitManga catalogue and publicly readable chapter formats."""

import base64
import binascii
import hashlib
import json
import re
import secrets
from collections import OrderedDict
from threading import Lock
from time import monotonic, sleep
from urllib.parse import parse_qs, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from manga_direct_catalogues import Browse, DirectCatalogue, Layout, MANGA, SLUG
from manga_direct_payloads import items
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Archive, Cards, MAX_CHAPTERS, MAX_PAGES, Meta, number, picture
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceError, SourceRateLimitError


HOSTS = {'mangadrama.com', 'mgread.io'}
SEARCH = '/wp-json/initlise/v1/search'
OUTLINE = '/wp-json/initmanga/v1/chapters'
KEY_API = '/wp-json/initmanga/v1/chapter-key'
VAULT_API = '/wp-admin/admin-ajax.php'
KEY = r'[1-9]\d{0,13}'
TOKEN = r'[A-Za-z0-9_.~+/=%-]{1,1024}'
CHAPTER = rf'/manga/{SLUG}/{SEGMENT}/?'
IMAGE_MARKER = 'mv_imip='
IMAGE_ID = r'[A-Za-z0-9_-]{16}'
AES_KEY = r'(?:[a-fA-F0-9]{32}|[a-fA-F0-9]{48}|[a-fA-F0-9]{64})'
IMIP_KEY = r'[A-Za-z0-9_.~+/=%-]{1,128}'
PAGER = 'ul.uk-pagination li:not(.uk-disabled) a:has([uk-pagination-next])'
CARDS = Cards('div.manga-card, div.manga-item-grid > div.uk-panel, div.manga-item-details', 'h2 a[href], h3 a[href]', next=PAGER)
IMAGE_GRANTS = OrderedDict()
GRANT_LOCK = Lock()


def public_api(host, path, query):
    if host not in HOSTS:
        return False
    args = parse_qs(query)
    if not all(len(v) == 1 and 1 <= len(v[0]) <= 160 for v in args.values()):
        return False
    if path == SEARCH:
        return set(args) == {'term', 'page'} and bool(re.fullmatch(KEY, args['page'][0]))
    if path == OUTLINE:
        return (set(args) == {'manga_id', 'per_page', 'paged'} and args['per_page'] == ['50']
                and all(re.fullmatch(KEY, args[k][0]) for k in ('manga_id', 'paged')))
    return path in {KEY_API, VAULT_API} and not query


def public_form(url, data, headers):
    parts = urlsplit(url)
    referer = urlsplit(headers.get('Referer', ''))
    if parts.scheme != 'https' or parts.netloc not in HOSTS or parts.query or referer.netloc != parts.netloc:
        return ''
    if referer.scheme != 'https' or not re.fullmatch(CHAPTER, referer.path):
        return ''
    if parts.path == VAULT_API and isinstance(data, dict):
        if (set(data) == {'action', 'cid', 'nonce'} and data['action'] == 'imip_gate_unlock'
                and isinstance(data['cid'], str) and re.fullmatch(KEY, data['cid'])
                and isinstance(data['nonce'], str) and re.fullmatch(TOKEN, data['nonce'])):
            return 'vault'
        return ''
    if parts.path != KEY_API or not isinstance(data, bytes) or len(data) > 3000:
        return ''
    nonce = headers.get('X-WP-Nonce', '')
    if nonce and (not isinstance(nonce, str) or not re.fullmatch(TOKEN, nonce)):
        return ''
    try:
        body = json.loads(data)
    except (ValueError, RecursionError):
        return ''
    fields = {'chapter_id', 'epoch', 'grant', 'verdict', 'score', 'codes', 'challenge_token'}
    if (isinstance(body, dict) and set(body) == fields and all(
            type(body[k]) is int and 0 < body[k] < 10**14 for k in ('chapter_id', 'epoch'))
            and body['verdict'] == 'pass' and type(body['score']) is int and body['score'] == 0 and body['codes'] == []
            and isinstance(body['grant'], str) and re.fullmatch(TOKEN, body['grant'])
            and isinstance(body['challenge_token'], str) and (
                not body['challenge_token'] or re.fullmatch(TOKEN, body['challenge_token']))):
        return 'key'
    return ''


def open_image_grant(reference):
    parts = urlsplit(reference)
    marker = parts.fragment.removeprefix(IMAGE_MARKER)
    target = urlunsplit(parts._replace(fragment=''))
    if not re.fullmatch(IMAGE_ID, marker):
        raise SourceError('Некорректный адрес страницы InitManga.')
    with GRANT_LOCK:
        grant = IMAGE_GRANTS.get(marker)
        if not grant or grant[0] <= monotonic() or target not in grant[2]:
            raise SourceAccessError('Ссылка на страницу устарела. Обнови главу.')
        return target, grant[1]


def mask_bytes(seed):
    while True:
        seed = (seed ^ (seed << 13)) & 0xFFFFFFFF
        seed ^= seed >> 17
        seed = (seed ^ (seed << 5)) & 0xFFFFFFFF
        yield seed & 255


def decode_image(raw, key):
    if len(raw) < 68 or not re.fullmatch(IMIP_KEY, key):
        raise SourceError('Некорректные данные страницы InitManga.')
    size = len(raw) - 36
    count = min(1024, size - 32)
    keys = key.encode('ascii')
    seed = 5381
    for byte in keys:
        seed = (seed * 33 + byte) & 0xFFFFFFFF
    seed = (seed * 33 + (size & 65535)) & 0xFFFFFFFF or 1
    rng = mask_bytes(seed)
    body_mask = bytes(next(rng) for _ in range(count))
    header = bytes(raw[size + i] ^ keys[(i * 13 + 3) % len(keys)] ^ next(rng) for i in range(32))
    checksum = 0x5A
    for byte in header:
        checksum ^= byte
    if raw[-4] ^ 0xA5 != checksum:
        raise SourceError('Страница InitManga не прошла проверку целостности.')
    body = bytearray(count)
    for i in range(count):
        byte = raw[32 + i] ^ keys[(i * 7 + 11) % len(keys)] ^ body_mask[i]
        body[i] = ((byte << 4) | (byte >> 4)) & 255
    return header + body + raw[32 + count:size]


def script_objects(doc):
    objects = {}
    decoder = json.JSONDecoder()
    for script in doc.select('script'):
        src = script.get('src', '')
        try:
            text = (base64.b64decode(src.partition('base64,')[2], validate=True).decode()
                    if src.startswith('data:') and 'base64,' in src else script.string or '')
        except (UnicodeError, ValueError, binascii.Error):
            continue
        markers = {'ciphertext', 'decryption_key', 'nonce'}
        if not any(f'"{key}"' in text for key in markers):
            continue
        for candidate in list(re.finditer(r'\{\s*"[\w-]+"\s*:', text))[:250]:
            try:
                value, _ = decoder.raw_decode(text, candidate.start())
            except (ValueError, RecursionError):
                continue
            if isinstance(value, dict):
                for key in markers.intersection(value):
                    if key != 'nonce' or 'url' in value:
                        objects.setdefault(key, value)
    return objects


def decrypt_markup(payload, key):
    try:
        iv = bytes.fromhex(payload['iv'])
        encrypted = base64.b64decode(payload['ciphertext'], validate=True)
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        unpadder = padding.PKCS7(128).unpadder()
        return (unpadder.update(cipher.update(encrypted) + cipher.finalize()) + unpadder.finalize()).decode()
    except (KeyError, ValueError, TypeError, UnicodeError, binascii.Error):
        raise SourceError('Источник вернул нечитаемые данные главы.') from None


class InitManga(DirectCatalogue):
    def __init__(self, identity):
        self.mgread = urlsplit(identity[3]).hostname == 'mgread.io'
        super().__init__(identity, Layout(
            MANGA, CHAPTER, CARDS, Meta('h1', 'a.story-cover img', '#manga-description', '#comic-othername',
                                       genres='div#genre-tags a:not(.uk-disabled)', status='#manga-status'),
            Archive(''), 'div#chapter-content > img', Browse('/manga-ranking/'), title_path='/manga/', suffix='/',
        ))

    def is_title(self, url):
        return super().is_title(url) and not (self.mgread and self.title_key(url).startswith('anime-'))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            raw = self.json(http, query_url(self.ROOT + SEARCH, term=query, page=page))
            if not isinstance(raw, list):
                raise SourceError('Источник изменил формат поиска.')
            rows = []
            for item in raw:
                if not isinstance(item, dict) or item.get('post_type') != 'manga':
                    continue
                target = self.site_link(item.get('url'))
                title = node_text(BeautifulSoup(str(item.get('title') or ''), 'html.parser'))
                if self.is_title(target) and title:
                    rows.append(self.record(target, title, image_url(item.get('thumb'), self.ROOT)))
            return rows, len(raw) == 10
        route = '/recently-updated' if sort == 'updated' else '/manga-ranking'
        options = {}
        if tag:
            if self.mgread and re.fullmatch(SEGMENT, tag) and tag != 'anime':
                route = '/advanced-filter'
                options['genre[]'] = tag
            elif not self.mgread and re.fullmatch(rf'/(?:genre|genres|category|manga-genre)/{SEGMENT}/?', tag):
                route = tag.rstrip('/')
            else:
                raise SourceError('Некорректная метка каталога.')
        path = self.ROOT + route + (f'/page/{page}/' if page > 1 else '/')
        return self.card_rows(*self.document(http, query_url(path, **options) if options else path), CARDS)

    def vocabulary(self, http):
        section = '/advanced-filter/' if self.mgread else '/manga/'
        doc, final = self.document(http, self.ROOT + section)
        if self.mgread:
            return [{'label': node['data-genre-name'], 'sourceId': node['value'], 'category': 'genre'}
                    for node in doc.select('input[name="genre[]"][data-genre-name][value]:not([value="anime"])')
                    if re.fullmatch(SEGMENT, node['value'])]
        rows = []
        for node in doc.select('ul.uk-list.uk-text-small a[href]'):
            path = urlsplit(self.site_link(node['href'], final)).path
            if re.fullmatch(rf'/(?:genre|genres|category|manga-genre)/{SEGMENT}/?', path) and node_text(node):
                rows.append({'label': node_text(node), 'sourceId': path, 'category': 'genre'})
        return rows

    def chapters(self, http, doc, url):
        body = doc.select_one('body')
        item = next((part[7:] for part in (body.get('class') or ()) if part.startswith('postid-')), '') if body else ''
        if not re.fullmatch(KEY, item):
            raise SourceError('Источник не предоставил ID тайтла.')
        rows = {}
        for page in range(1, 201):
            target = query_url(self.ROOT + OUTLINE, manga_id=item, per_page=50, paged=page)
            data = self.json(http, target, url)
            for chapter in items(data, 'items'):
                if not isinstance(chapter, dict) or (chapter.get('lock_type') != 'none' and chapter.get('is_purchased') is not True):
                    continue
                slug = str(chapter.get('slug') or '').strip('/')
                path = f'{url.rstrip("/")}/{slug}/'
                if not re.fullmatch(SEGMENT, slug) or not self.is_chapter(path):
                    continue
                n = number(chapter.get('number'))
                name = chapter.get('title') or f'Chapter {n or 0:g}'
                rows[path] = self.chapter(path, name, n, str(chapter.get('created_at') or '')[:10])
            if len(rows) >= MAX_CHAPTERS or page >= (number(data.get('total_pages')) or 1):
                return self.order(rows)[:MAX_CHAPTERS], len(rows) >= MAX_CHAPTERS
        return self.order(rows)[:MAX_CHAPTERS], True

    def post(self, http, endpoint, data, referer, nonce=''):
        headers = {'Referer': referer}
        if nonce:
            headers['X-WP-Nonce'] = nonce
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(endpoint, method='POST', data=data, headers=headers, action='initmanga-public-form')
        if final != endpoint:
            raise SourceError('Источник перенаправил запрос загрузки главы.')
        try:
            reply = json.loads(raw)
            if not isinstance(reply, dict):
                raise ValueError('Unexpected reply')
            return reply
        except (ValueError, RecursionError):
            raise SourceError('Источник изменил формат ответа читалки.') from None

    def fetch_chapter_key(self, http, payload, url, nonce):
        request = {'chapter_id': payload.get('cid'), 'epoch': payload.get('e'), 'grant': payload.get('g'),
                   'verdict': 'pass', 'score': 0, 'codes': [], 'challenge_token': ''}
        for _ in range(3):
            reply = self.post(http, self.ROOT + KEY_API, json.dumps(request).encode(), url, nonce)
            key = reply.get('key')
            if isinstance(key, str) and re.fullmatch(AES_KEY, key):
                return bytes.fromhex(key)
            code = reply.get('code')
            if code == 'rest_cookie_invalid_nonce' and nonce:
                nonce = ''
            elif code == 'imc_challenge_required' and not request['challenge_token']:
                token = (reply.get('data') or {}).get('token')
                if not isinstance(token, str) or not re.fullmatch(TOKEN, token):
                    break
                sleep(.5)
                request['challenge_token'] = token
            elif code == 'imc_rate_limited':
                raise SourceRateLimitError(None)
            else:
                break
        raise SourceAccessError('Источник не предоставил ключ открытой главы.')

    def protected_images(self, http, gallery, objects, url):
        vault = objects.get('nonce') or {}
        endpoint = self.site_link(vault.get('url'), url)
        if endpoint != self.ROOT + VAULT_API:
            raise SourceError('Источник изменил маршрут защищённых изображений.')
        fields = {'action': 'imip_gate_unlock', 'cid': gallery.get('data-cid'), 'nonce': vault.get('nonce')}
        data = self.post(http, endpoint, fields, url)
        key = (data.get('data') or {}).get('k')
        rows = [image_url(item['data-bin'], url) for item in gallery.select('div.imip-page[data-bin]')]
        if not isinstance(key, str) or not re.fullmatch(IMIP_KEY, key) or not 1 <= len(rows) <= MAX_PAGES or not all(rows):
            raise SourceAccessError('Источник не предоставил ключ страниц.')
        marker = secrets.token_urlsafe(12)
        with GRANT_LOCK:
            IMAGE_GRANTS[marker] = (monotonic() + 1800, key, frozenset(rows))
            while len(IMAGE_GRANTS) > 256:
                IMAGE_GRANTS.popitem(last=False)
        return [page + '#' + IMAGE_MARKER + marker for page in rows]

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        if doc.select_one('div.lock-card'):
            raise SourceAccessError('Глава доступна на условиях источника.')
        objects = script_objects(doc)
        if gallery := doc.select_one('div.imip-protected-gallery'):
            return self.protected_images(http, gallery, objects, final)
        payload = objects.get('ciphertext')
        if not payload:
            return [picture(node, final, ('data-original-src', 'data-src')) for node in doc.select(self.layout.reader)]
        params = objects.get('decryption_key') or {}
        if isinstance(payload.get('salt'), str):
            try:
                passphrase = base64.b64decode(params['decryption_key'], validate=True)
                salt = bytes.fromhex(payload['salt'])
                if not 1 <= len(salt) <= 64:
                    raise ValueError('Salt size')
                key = hashlib.pbkdf2_hmac('sha512', passphrase, salt, 999, 32)
            except (ValueError, KeyError, TypeError, binascii.Error):
                raise SourceError('Источник изменил параметры открытой главы.') from None
        else:
            key = self.fetch_chapter_key(http, payload, final, params.get('nonce'))
        html = BeautifulSoup(decrypt_markup(payload, key), 'html.parser')
        rows = []
        for node in html.select('img, canvas[data-enc]'):
            if node.name == 'canvas':
                try:
                    path = base64.b64decode(node['data-enc'], validate=True)[::-1].decode()
                except (ValueError, UnicodeError, binascii.Error):
                    raise SourceError('Источник вернул некорректную страницу.') from None
                rows.append(image_url(path, final))
            else:
                rows.append(picture(node, final, ('data-original-src', 'data-src')))
        return rows
