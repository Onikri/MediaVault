"""INKR Comics (keiyoushi ``src/en/inkr`` at 6f345a8).

The Android client's two JSON APIs answer guests: ``icq-api`` returns the
title IDs of the catalogue or of a search, ``icd-api`` hydrates any object
IDs (titles, chapters, images, genres, creators, chapter pages) through
``content_json/batch``. The catalogue is sorted locally by reads or by the
latest chapter, like the extension; explicit titles stay hidden like its
default. Only free and ad-supported chapters are listed: others return no
pages without a login. Page images (``w1600.ikc``) are AES-CBC encrypted
with the client's static key behind a 4-byte size and a 16-byte IV, decoded
like the extension's ``ImageInterceptor``.
"""

from dataclasses import dataclass
import json
import re
import struct
import threading
import time
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from manga_direct_payloads import JsonSeries
from manga_japanese_readers import JapanesePage, packed_refs
from manga_ninth_routes import Route, register
from source_parser import SourceError

ROOT = 'https://comics.inkr.com'
QUERY = 'https://icq-api.inkr.com/v1'
CONTENT = 'https://icd-api.inkr.com/v1/content_json/batch'
PAGE_SIZE = 20
BATCH = 500
CACHE_SECONDS = 900
KEY = bytes(value ^ 0x5A for value in (
    0x1F, 0x17, 0x0B, 0x11, 0x39, 0x2D, 0x03, 0x2B, 0x0B, 0x2E, 0x36, 0x12, 0x68, 0x63, 0x11, 0x20,
    0x09, 0x00, 0x29, 0x1E, 0x35, 0x38, 0x12, 0x16, 0x6B, 0x37, 0x12, 0x2C, 0x20, 0x35, 0x2E, 0x36))
OID = re.compile(r'ik-(?:title|chapter|image|genre|creator)-[0-9]{1,10}')
ID = r'[1-9][0-9]{0,9}'
LIST_FIELDS = ['oid', 'name', 'thumbnailImage', 'releaseStatus', 'styleOrigin', 'keyGenreList', 'summary', 'pageReadCount',
               'latestChapterFirstPublishedDate', 'isExplicit', 'monetizationType', 'isAvailable', 'isRemovedFromSale']
DETAIL_FIELDS = LIST_FIELDS + ['chapterList', 'titleCreators']
CHAPTER_FIELDS = ['oid', 'name', 'order', 'firstPublishedDate', 'publishedDate', 'revenueType', 'coinPrice',
                  'isPurchasedByCoin', 'isPurchasedBySub']
NAMED_FIELDS = ['oid', 'name', 'url']
PAGES = {'chapterPages': {'fields': ['oid', 'width', 'height', 'type'], 'includes': {}, 'includeKey': 'page'}}
HEADERS = {'User-Agent': 'okhttp/4.9.1', 'ikc-platform': 'android', 'cf-ipcountry': 'en-GB',
           'Accept': 'application/json', 'Content-Type': 'application/json'}


def encode(value):
    return json.dumps(value, separators=(',', ':')).encode()


def accepted_body(path, data):
    if not isinstance(data, bytes) or len(data) > 65536:
        return False
    try:
        value = json.loads(data)
    except ValueError:
        return False
    if encode(value) != data:
        return False
    if path == '/v1/title/filtered':
        return value == {'limit': 10000}
    if path == '/v1/title/search':
        return isinstance(value, dict) and set(value) == {'query'} and isinstance(value['query'], str) \
            and 1 <= len(value['query']) <= 160
    if path != '/v1/content_json/batch' or not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        return False
    query = value[0]
    oids = query.get('oids')
    if not isinstance(oids, list) or not 1 <= len(oids) <= BATCH or not all(isinstance(oid, str) and OID.fullmatch(oid)
                                                                            for oid in oids):
        return False
    fields = query.get('fields')
    if set(query) == {'fields', 'oids', 'includes'}:
        return fields == ['chapterPages'] and query['includes'] == PAGES and len(oids) == 1
    return set(query) == {'fields', 'oids'} and fields in (LIST_FIELDS, DETAIL_FIELDS, CHAPTER_FIELDS, NAMED_FIELDS)


def route(url, method, data, headers):
    if method != 'POST' or url.query or url.netloc not in {'icq-api.inkr.com', 'icd-api.inkr.com'}:
        return None
    if (url.netloc == 'icd-api.inkr.com') != (url.path == '/v1/content_json/batch') or not accepted_body(url.path, data):
        return None
    return Route(headers=HEADERS, post=True, data=data, redirect=False)


register('inkr', route)


def decrypt(raw):
    if len(raw) < 36:
        raise SourceError('INKR вернул повреждённую страницу.')
    size = struct.unpack('<I', raw[:4])[0]
    sealed = raw[20:]
    sealed = sealed[:len(sealed) // 16 * 16]
    if not 0 < size <= len(sealed):
        raise SourceError('INKR вернул повреждённую страницу.')
    decoder = Cipher(algorithms.AES(KEY), modes.CBC(raw[4:20])).decryptor()
    return (decoder.update(sealed) + decoder.finalize())[:size]


@dataclass(frozen=True)
class InkrPage(JapanesePage):
    def fetch(self, http, referer):
        from manga_page_media import read_image

        response, _ = http._open(self.url, headers={'User-Agent': HEADERS['User-Agent']})
        return decrypt(read_image(http, response))


class Inkr(JsonSeries):
    def __init__(self):
        super().__init__(('6949560025265725268', 'INKR', 'en', ROOT, True), rf'/title/({ID})(?:-[A-Za-z0-9-]{{0,200}})?',
                         rf'/title/({ID})/chapter/({ID})', interval=.25)
        self.cache = None
        self.cache_lock = threading.Lock()

    def title_for(self, url):
        return f'{ROOT}/title/{self.chapter_key(url)}'

    def chapter_identity(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return match.groups() if match else ()

    def title_identity(self, value):
        return self.title_key(value) or super().title_identity(value)

    def saved_title_url(self, value):
        # Suwayomi stored the object ID "ik-title-<id>".
        target = self.canonical(value)
        found = re.search(rf'(?:ik-title-|/title/)({ID})', urlsplit(target).path)
        return f'{ROOT}/title/{found[1]}' if found else ''

    def saved_chapter(self, row, root, title):
        value = str(row.get('url') or '')
        found = re.search(rf'ik-chapter-({ID})', value)
        key = self.title_key(title)
        return f'{ROOT}/title/{key}/chapter/{found[1]}' if found and key else ''

    def post(self, http, url, body):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, _ = http.document(url, method='POST', data=encode(body), headers={}, action='n9:inkr')
        try:
            data = json.loads(raw)
        except ValueError:
            raise SourceError('INKR изменил формат API.') from None
        if not isinstance(data, dict):
            raise SourceError('INKR изменил формат API.')
        return data.get('data')

    def objects(self, http, oids, fields, includes=None):
        result = {}
        for start in range(0, len(oids), BATCH):
            query = {'fields': fields, 'oids': oids[start:start + BATCH]}
            if includes:
                query['includes'] = includes
            data = self.post(http, CONTENT, [query])
            if not isinstance(data, dict):
                raise SourceError('INKR изменил формат API.')
            result.update({key: value for key, value in data.items() if isinstance(value, dict)})
        return result

    def visible(self, item):
        return (isinstance(item, dict) and item.get('isAvailable', True) and not item.get('isRemovedFromSale')
                and not item.get('isExplicit') and isinstance(item.get('name'), str) and item['name'].strip()
                and re.fullmatch(r'ik-title-[0-9]{1,10}', str(item.get('oid', ''))))

    def directory(self, http):
        with self.cache_lock:
            if self.cache and time.monotonic() - self.cache[0] < CACHE_SECONDS:
                return self.cache[1]
        oids = self.post(http, f'{QUERY}/title/filtered', {'limit': 10000})
        if not isinstance(oids, list):
            raise SourceError('INKR изменил формат каталога.')
        oids = [oid for oid in oids if isinstance(oid, str) and OID.fullmatch(oid)][:10000]
        items = self.objects(http, oids, LIST_FIELDS)
        titles = [items[oid] for oid in oids if self.visible(items.get(oid))]
        with self.cache_lock:
            self.cache = (time.monotonic(), titles)
        return titles

    def rows(self, http, titles):
        named = self.objects(http, list(dict.fromkeys(
            [item['thumbnailImage'] for item in titles if isinstance(item.get('thumbnailImage'), str)
             and OID.fullmatch(item['thumbnailImage'])]
            + [oid for item in titles for oid in item.get('keyGenreList') or [] if isinstance(oid, str) and OID.fullmatch(oid)])),
            NAMED_FIELDS) if titles else {}
        return [self.title_row(item, named) for item in titles]

    def title_row(self, item, named, authors=()):
        key = item['oid'].removeprefix('ik-title-')
        image = named.get(item.get('thumbnailImage'), {}).get('url') or ''
        genres = [str(item.get('styleOrigin') or '').replace('-', ' ').capitalize()]
        genres += [named.get(oid, {}).get('name') or '' for oid in item.get('keyGenreList') or []]
        summary = item.get('summary')
        status = str(item.get('releaseStatus') or '').lower()
        return self.record(f'{ROOT}/title/{key}', item['name'].strip(), image if image.startswith('https://') else '',
                           description='\n'.join(value for value in summary if isinstance(value, str)) if isinstance(summary, list) else '',
                           genres=genres, authors=authors,
                           status=status if status in {'ongoing', 'completed', 'hiatus'} else '')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag:
            return [], False
        if query:
            found = self.post(http, f'{QUERY}/title/search', {'query': query})
            oids = found.get('title') if isinstance(found, dict) else None
            if not isinstance(oids, list):
                raise SourceError('INKR изменил формат поиска.')
            oids = [oid for oid in oids if isinstance(oid, str) and OID.fullmatch(oid)][:BATCH]
            items = self.objects(http, oids, LIST_FIELDS)
            titles = [items[oid] for oid in oids if self.visible(items.get(oid))
                      and query.casefold() in items[oid]['name'].casefold()]
        else:
            titles = self.directory(http)
            if sort == 'updated':
                titles = sorted(titles, key=lambda item: str(item.get('latestChapterFirstPublishedDate') or ''), reverse=True)
            else:
                titles = sorted(titles, key=lambda item: item.get('pageReadCount') or 0, reverse=True)
        start = (page - 1) * PAGE_SIZE
        return self.rows(http, titles[start:start + PAGE_SIZE]), start + PAGE_SIZE < len(titles)

    def series(self, http, url):
        oid = 'ik-title-' + self.title_key(url)
        item = self.objects(http, [oid], DETAIL_FIELDS).get(oid)
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not item['name'].strip():
            raise SourceError('INKR не предоставил карточку тайтла.')
        creators = [row.get('creator') for row in item.get('titleCreators') or [] if isinstance(row, dict)]
        extra = [value for value in creators if isinstance(value, str) and OID.fullmatch(value)]
        named = self.objects(http, list(dict.fromkeys(
            ([item['thumbnailImage']] if isinstance(item.get('thumbnailImage'), str) and OID.fullmatch(item['thumbnailImage']) else [])
            + [value for value in item.get('keyGenreList') or [] if isinstance(value, str) and OID.fullmatch(value)] + extra)),
            NAMED_FIELDS)
        row = self.title_row({**item, 'oid': oid}, named, [named.get(value, {}).get('name') or '' for value in extra])
        if item.get('isExplicit'):
            row['adult'] = True
        chapter_oids = [value for value in item.get('chapterList') or [] if isinstance(value, str)
                        and re.fullmatch(r'ik-chapter-[0-9]{1,10}', value)][:5000]
        chapters = {}
        key = self.title_key(url)
        for value in self.objects(http, chapter_oids, CHAPTER_FIELDS).values():
            if str(value.get('revenueType') or '').lower() not in {'ad', 'free'}:
                continue
            found = re.fullmatch(r'ik-chapter-([0-9]{1,10})', str(value.get('oid', '')))
            if not found:
                continue
            order = value.get('order')
            target = f'{ROOT}/title/{key}/chapter/{found[1]}'
            chapters[target] = {**self.chapter(target, str(value.get('name') or ''),
                                               float(order) if isinstance(order, (int, float)) else None,
                                               str(value.get('firstPublishedDate') or value.get('publishedDate') or '')[:10]),
                                'season': 1}
        return row, self.order(chapters)

    def pages(self, http, url):
        _, chapter = self.chapter_identity(url)
        oid = 'ik-chapter-' + chapter
        data = self.objects(http, [oid], ['chapterPages'], PAGES).get(oid) or {}
        pages = data.get('chapterPages')
        if not pages:
            from source_parser import SourceAccessError

            raise SourceAccessError('Глава INKR доступна только с монетами или подпиской.')
        rows = []
        for page in pages:
            link = page.get('url') if isinstance(page, dict) else None
            target = urlsplit(link or '')
            if target.scheme != 'https' or target.netloc != 'i.inkr.com' or target.query:
                raise SourceError('INKR изменил адрес страниц.')
            rows.append(InkrPage(link.rstrip('/') + '/w1600.ikc'))
        return packed_refs(rows, url)


SOURCES = (Inkr(),)
