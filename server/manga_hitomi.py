"""Hitomi public title index and image routing, based on the site's browser protocol."""
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
import re
import struct
from threading import Lock
from time import monotonic
from urllib.parse import urlencode, urlsplit

from source_parser import SourceError

ROOT = 'https://hitomi.la'
DOMAIN = 'gold-usergeneratedcontent.net'
INDEX = 'https://ltn.' + DOMAIN
SOURCES = tuple({'id': str(990000000000000010+i), 'name': 'Hitomi', 'lang': lang,
                 'baseUrl': ROOT, 'isNsfw': True} for i, lang in enumerate(('en', 'ja', 'ru', 'ko')))
LANGUAGE = {'english': 'en', 'japanese': 'ja', 'russian': 'ru', 'korean': 'ko'}
THUMBNAIL_PATH = re.compile(r'/webpbigtn/[a-f0-9]/[a-f0-9]{2}/[a-f0-9]{64}\.webp')
_cache = {}
_lock = Lock()


def setting(http, path, parse):
    with _lock:
        old = _cache.get(path)
        if old and old[0] > monotonic():
            return old[1]
    value = parse(http.document(INDEX + path)[0])
    with _lock:
        _cache[path] = monotonic() + 120, value
    return value


def version(text):
    value = text.strip()
    if not re.fullmatch(r'\d{1,24}', value):
        raise SourceError('Hitomi изменил формат версии индекса.')
    return value


def route_table(text):
    prefix = re.search(r"\bb:\s*'(\d{1,24})/'", text)
    if not prefix or not re.search(r'var o = 0;\s*switch \(g\)', text) or not re.search(r'o = 1;\s*break;', text):
        raise SourceError('Hitomi изменил маршрутизацию изображений.')
    return prefix[1], frozenset(map(int, re.findall(r'\bcase (\d+):', text)))


def range_bytes(http, url, offset, size):
    response, final = http._open(url, byte_range=f'bytes={offset}-{offset+size-1}')
    try:
        expected = f'bytes {offset}-{offset+size-1}/'
        if final != url or response.status_code != 206 or not response.headers.get('Content-Range', '').startswith(expected):
            raise SourceError('Hitomi не предоставил диапазон индекса.')
        data = response.raw.read(size + 1)
        if len(data) != size:
            raise SourceError('Hitomi вернул неполный диапазон индекса.')
        return data
    finally:
        response.close()


def decode_node(data):
    pos = 0

    def take(fmt):
        nonlocal pos
        value = struct.unpack_from('>' + fmt, data, pos)
        pos += struct.calcsize('>' + fmt)
        return value

    try:
        count, = take('I')
        if count > 16:
            raise ValueError
        keys = []
        for _ in range(count):
            size, = take('I')
            if size != 4:
                raise ValueError
            keys.append(bytes(take('4B')))
        count_data, = take('I')
        if count_data != count:
            raise ValueError
        records = [take('QI') for _ in keys]
        children = take('17Q')
        return keys, records, children
    except (struct.error, ValueError):
        raise SourceError('Hitomi изменил формат поискового индекса.') from None


def lookup(http, index, term):
    key = sha256(term.encode()).digest()[:4]
    address = 0
    for _ in range(12):
        keys, records, children = decode_node(range_bytes(http, index + '.index', address, 464))
        at = bisect_left(keys, key)
        if at < len(keys) and keys[at] == key:
            offset, size = records[at]
            if not 4 <= size <= 8 * 1024 * 1024 or size % 4:
                raise SourceError('Hitomi вернул неподдерживаемый размер индекса.')
            data = range_bytes(http, index + '.data', offset, size)
            count, = struct.unpack_from('>I', data)
            if count != (len(data)-4)//4:
                raise SourceError('Hitomi вернул неправильный список результатов.')
            return [value for value, in struct.iter_unpack('>I', memoryview(data)[4:])]
        address = children[at]
        if not address:
            return []
    raise SourceError('Hitomi не завершил поиск в индексе.')


def gallery(http, identity):
    url = f'{INDEX}/galleries/{identity}.js'
    text, final, _ = http.document(url)
    try:
        match = re.fullmatch(r'\s*var\s+galleryinfo\s*=\s*(\{.*\})\s*;?\s*', text, re.S)
        data = json.loads(match[1]) if final == url and match else {}
        if str(data.get('id')) == str(identity) and isinstance(data.get('files'), list):
            return data
    except (ValueError, AttributeError):
        pass
    raise SourceError('Hitomi не предоставил данные галереи.')


def image(file, table, *, thumbnail=False):
    digest = file.get('hash', '')
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise SourceError('Hitomi вернул неверный идентификатор изображения.')
    tail = digest[-1] + digest[-3:-1]
    prefix, webp_hosts = table
    shard = int(tail, 16)
    split = int(shard in webp_hosts)
    if thumbnail:
        return f'https://{chr(97+split)}tn.{DOMAIN}/webpbigtn/{tail[0]}/{tail[1:]}/{digest}.webp'
    extension = 'avif' if file.get('hasavif') else 'webp'
    return f'https://{extension[0]}{split+1}.{DOMAIN}/{prefix}/{shard}/{digest}.{extension}'


def row(data, table):
    title = (data.get('title') or data.get('japanese_title') or '').strip()
    if not title or not data['files'] or data.get('type') not in {'manga', 'doujinshi', 'artistcg', 'western'}:
        return None
    lang = LANGUAGE.get(data.get('language'), 'und')
    source = next((s for s in SOURCES if s['lang'] == lang), SOURCES[0])
    identity = int(data['id'])
    url = f'{ROOT}/reader/{identity}.html'
    names = list(dict.fromkeys(filter(None, (title, data.get('japanese_title')))))
    cover = image(data['files'][0], table, thumbnail=True)
    server = os.getenv('PUBLIC_URL', '').rstrip('/')
    if server:
        cover = server + '/artwork?' + urlencode({'url': cover})
    return {'id': f'hitomi:{identity}', 'provider': 'hitomi', 'providerName': 'Hitomi',
            'sourceId': source['id'], 'title': title[:500], 'aliases': names,
            'url': url, 'sourceURL': url, 'sourceUrl': url, 'sourceOnly': True,
            'kind': 'manga', 'format': 'manga', 'language': lang, 'age': 18, 'adult': True,
            'cover': cover}


def search(query, http, language='all'):
    words = list(dict.fromkeys(re.findall(r'\w+', query.lower().replace('_', ' '))))[:8]
    if not words:
        return []
    index = INDEX + '/galleriesindex/galleries.' + setting(http, '/galleriesindex/version', version)
    ids = lookup(http, index, words[0])
    for term in words[1:]:
        if not ids:
            return []
        other = set(lookup(http, index, term))
        ids = [identity for identity in ids if identity in other]
    if ids and language != 'all':
        code = next((name for name, value in LANGUAGE.items() if value == language), None)
        if not code:
            return []
        url = INDEX + '/n/index-' + code + '.nozomi'
        response, final = http._open(url)
        try:
            data = response.raw.read(4 * 1024 * 1024 + 1, decode_content=True)
            if final != url or len(data) > 4 * 1024 * 1024 or len(data) % 4:
                raise SourceError('Hitomi вернул неверный индекс языка.')
        finally:
            response.close()
        matches = set(ids).intersection(value for value, in struct.iter_unpack('>I', data))
        ids = [identity for identity in ids if identity in matches]
    if not ids:
        return []
    table = setting(http, '/gg.js', route_table)

    def load(identity):
        client = http.fork()
        try:
            result = row(gallery(client, identity), table)
            return result if result and language in ('all', result['language']) else None
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        return [result for result in pool.map(load, ids[:24]) if result]


def inspect(url, http):
    match = re.fullmatch(r'/(?:reader/|(?:[^/]+/)?[^/]*-)(\d{1,10})\.html', urlsplit(url).path)
    if not match:
        raise SourceError('Выбери конкретную галерею Hitomi.')
    data = gallery(http, int(match[1]))
    table = setting(http, '/gg.js', route_table)
    result = row(data, table)
    if not result or len(data['files']) > 500:
        raise SourceError('Hitomi не предоставил поддерживаемую галерею.')
    return {**result, 'pages': [image(file, table) for file in data['files']],
            'episodes': [{'number': 1, 'season': 1, 'url': result['url'], 'title': 'Глава 1',
                          'language': result['language'], 'translator': ''}],
            'seasons': [{'number': 1, 'name': 'Том 1'}], 'dubs': [], 'releases': [],
            'translations': [], 'available': True}
