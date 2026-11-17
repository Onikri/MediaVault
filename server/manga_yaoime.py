"""Yaoi.me language catalogues (keiyoushi ``src/all/yaoime`` at 6f345a8).

Browse pages are HTML; a series page carries its chapter groups in the
Next.js flight data. The reader API is called with the web app's request
signature (HMAC-SHA256 of the path and time) and may return the page hashes
sealed with AES-GCM, exactly as the extension and the site reader do.
"""

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, node_text
from manga_ninth_routes import Route, register
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://yaoi.me'
SIGN_KEY = bytes.fromhex('85cedf4fed3602c3a35c18010b502584dee9594708ba673052d562c7f2b1a9de')
SEAL_KEY = bytes.fromhex('10dd8dff9911000f9286d3dfd8b9f72b3f763c2f783f89f5c384cff4a11988ac')
IMAGE_WIDTHS = (90, 140, 200, 260, 360, 500, 720, 1000, 1400)
SORTS = {'popular': 'popular', 'updated': 'update', 'new': 'create', 'rating': 'rating', 'alphabet': 'az'}
STATUSES = {'completed': 'completed', 'releasing': 'ongoing', 'hiatus': 'hiatus', 'cancelled': 'cancelled'}
BROWSE_KEYS = {'q', 'langs', 'sort', 'dir', 'genre', 'page'}


def reader_path(series, chapter):
    return f'/api/reader/chapter?s={series}&c={chapter}'


def public_api(host, path, query):
    if host != 'yaoi.me' or path != '/api/reader/chapter':
        return False
    return bool(re.fullmatch(r's=[1-9][0-9]{0,11}&c=[1-9][0-9]{0,14}', query))


def route(url, method, data, headers):
    if url.netloc != 'yaoi.me' or method != 'GET' or data is not None:
        return None
    if public_api(url.netloc, url.path, url.query):
        stamp, signature = headers.get('Yaoime-Time', ''), headers.get('Yaoime-Signature', '')
        if not re.fullmatch(r'[0-9]{13}', stamp) or abs(int(stamp) / 1000 - time.time()) > 120:
            return None
        expected = sign(url.path + '?' + url.query, stamp)
        if not hmac.compare_digest(signature, expected):
            return None
        return Route({'Accept': 'application/json', 'x-yf-t': stamp, 'x-yf-s': signature}, redirect=False)
    return None


def sign(path, stamp):
    digest = hmac.new(SIGN_KEY, f'{path} {stamp}'.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode()


def unseal(value):
    try:
        data = base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
        key = hashlib.sha256(SEAL_KEY + data[:16]).digest()
        pages = json.loads(AESGCM(key).decrypt(data[16:28], data[28:], None))['p']
    except (InvalidTag, ValueError, KeyError, TypeError):
        raise SourceError('Yaoi.me изменил защиту списка страниц.') from None
    if not isinstance(pages, list) or not all(isinstance(p, str) and re.fullmatch(r'[A-Za-z0-9_-]{8,200}', p) for p in pages):
        raise SourceError('Yaoi.me изменил формат списка страниц.')
    return pages


def flight(text):
    decoder, parts, pos = json.JSONDecoder(), [], 0
    while (pos := text.find('self.__next_f.push(', pos)) >= 0:
        pos += 19
        try:
            item, _ = decoder.raw_decode(text[pos:])
        except ValueError:
            continue
        if isinstance(item, list) and len(item) > 1 and item[0] == 1 and isinstance(item[1], str):
            parts.append(item[1])
    return ''.join(parts)


def chapter_groups(text):
    data = flight(text)
    decoder = json.JSONDecoder()
    for match in re.finditer(r'"groups":\[', data):
        start = data.rfind('{', 0, match.start())
        while start >= 0:
            try:
                value, _ = decoder.raw_decode(data[start:])
            except ValueError:
                start = data.rfind('{', 0, start)
                continue
            if isinstance(value, dict) and isinstance(value.get('groups'), list) and 'sources' in value:
                return value
            start = data.rfind('{', 0, start)
    return None


register('yaoime', route, public_api)


class YaoiMe(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/series/([1-9][0-9]{{0,11}})(?:/{SEGMENT})?/?',
                         r'/chapter/([1-9][0-9]{0,11}/[1-9][0-9]{0,14})/?', interval=.4)
        self.site_lang = identity[2].lower()

    def title_key(self, url):
        match = self.TITLE_PATH.fullmatch(urlsplit(url).path)
        return match[1] if match else ''

    def title_for(self, url):
        series = param(url, 'mv_series')
        return f'{ROOT}/series/{series}' if re.fullmatch(r'[1-9][0-9]{0,11}', series) else ''

    def chapter_identity(self, url):
        return urlsplit(url).path.rstrip('/')

    def canonical(self, value):
        url = super().canonical(value)
        if not url and isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,11}', value):
            return f'{ROOT}/series/{value}'
        return url

    def saved_title_url(self, url):
        return self.canonical(url)

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target) and self.is_title(title) and not param(target, 'mv_series'):
            return query_url(target, mv_series=self.title_key(title))
        return target

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title)

    def card_from(self, link, covers):
        url = self.canonical(link.get('href'))
        title = (link.get('title') or node_text(link)).strip()
        if not self.is_title(url) or not title:
            return None
        cover = covers.get(urlsplit(url).path, '')
        url = f'{ROOT}/series/{self.title_key(url)}'
        return self.record(url, title, cover)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'langs': self.site_lang, 'sort': SORTS.get(sort, 'popular'), 'dir': 'desc'}
        if query:
            args['q'] = query
        if tag:
            if not re.fullmatch(r"[\w &'.+-]{1,60}", tag):
                return [], False
            args['genre'] = tag
        if page > 1:
            args['page'] = str(page)
        doc, final = self.document(http, query_url(ROOT + '/browse', **args))
        covers = {}
        for tile in doc.select('a.tile[href]'):
            image = tile.select_one('img[src]')
            if image:
                parts = urlsplit(self.site_link(image['src'], final) or '')
                covers[urlsplit(self.site_link(tile['href'], final) or '').path] = urlunsplit(parts._replace(query=''))
        rows = {}
        for link in doc.select('a.card-title[href]'):
            row = self.card_from(link, covers)
            if row:
                rows[row['id']] = row
        more = any(node_text(a) == 'Next' for a in doc.select('nav a'))
        return list(rows.values()), more

    def series(self, http, url):
        series_id = self.title_key(url)
        raw, final, _ = http.document(f'{ROOT}/series/{series_id}', headers={'Referer': ROOT + '/'})
        if self.title_key(final) != series_id:
            raise SourceError('Yaoi.me перенаправил на другой тайтл.')
        doc = BeautifulSoup(raw, 'html.parser')
        info = None
        for node in doc.select('script[type="application/ld+json"]'):
            try:
                value = json.loads(node.string or '')
            except ValueError:
                continue
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, dict) and item.get('@type') == 'ComicSeries':
                    info = item
        if not info or not isinstance(info.get('name'), str):
            raise SourceError('Yaoi.me не предоставил карточку тайтла.')
        cover = urlunsplit(urlsplit(info['image'])._replace(query='')) if isinstance(info.get('image'), str) else ''
        genres = [node_text(a) for a in doc.select('a[href^="/genre/"]')]
        tags = [node_text(a) for a in doc.select('a[href^="/tag/"]')]
        authors = [node_text(a) for a in doc.select('a[href^="/author/"]')]
        status = ''
        for term in doc.select('dt'):
            if node_text(term).lower() == 'status' and (value := term.find_next_sibling('dd')):
                status = STATUSES.get(node_text(value).lower(), '')
        synopsis = ''
        for section in doc.select('section'):
            heading = section.find('h2', recursive=False)
            if heading and 'synopsis' in node_text(heading).lower() and (prose := section.select_one('.prose-text')):
                synopsis = prose.get_text('\n').strip()
        row = self.record(f'{ROOT}/series/{series_id}', info['name'].strip(), cover,
                          aliases=[a for a in info.get('alternateName') or [] if isinstance(a, str)],
                          description=synopsis, genres=genres, tags=tags, authors=authors, status=status)
        groups = chapter_groups(raw) or {'groups': []}
        chapters = {}
        for group in groups.get('groups') or []:
            if not isinstance(group, dict):
                continue
            number = group.get('num') if group.get('numReal') == 1 and isinstance(group.get('num'), (int, float)) else None
            stamp = group.get('createdAt')
            date = (datetime.fromtimestamp(stamp / 1000, timezone.utc).date().isoformat()
                    if type(stamp) is int and 0 < stamp < 10 ** 14 else '')
            for variant in group.get('variants') or []:
                if not isinstance(variant, dict) or (variant.get('lang') or 'en') != self.site_lang:
                    continue
                if type(variant.get('id')) is not int or type(variant.get('s')) is not int:
                    continue
                target = query_url(f'{ROOT}/chapter/{variant["s"]}/{variant["id"]}', mv_series=series_id)
                label = str(group.get('label') or '')
                translator = str((groups.get('sources') or {}).get(str(variant['s'])) or '')
                chapters[target] = self.chapter(target, label, float(number) if number is not None else None, date,
                                                translator=translator)
        return row, self.order(chapters)

    def pages(self, http, url):
        series, chapter = self.chapter_key(url).split('/')
        path = reader_path(series, chapter)
        stamp = str(int(time.time() * 1000))
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, _ = http.document(ROOT + path, headers={'Referer': url, 'Yaoime-Time': stamp,
                                                        'Yaoime-Signature': sign(path, stamp)}, action='n9:yaoime')
        try:
            reader = json.loads(raw)['chapter']
            pages = reader['pages']
        except (KeyError, TypeError, ValueError):
            raise SourceAccessError('Yaoi.me не открыл эту главу.') from None
        if not isinstance(pages, list):
            raise SourceError('Yaoi.me изменил формат читалки.')
        hashes = unseal(reader['sealed']) if reader.get('sealed') else [
            p.get('hash') if isinstance(p, dict) else '' for p in pages]
        if len(hashes) != len(pages):
            raise SourceError('Yaoi.me вернул неполный список страниц.')
        result = []
        for page, digest in zip(pages, hashes):
            if not isinstance(digest, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,200}', digest):
                return []
            width = page.get('w') if isinstance(page, dict) else None
            size = next((w for w in IMAGE_WIDTHS if type(width) is int and width > 0 and w >= width), None)
            result.append(f'{ROOT}/i/p/{digest}' + (f'?w={size}' if size else ''))
        return result


LANGUAGES = (
    ('232952896490317872', 'pt'), ('418222621742506139', 'mn'), ('440596664459681045', 'cs'),
    ('539129098615592048', 'pt-BR'), ('684979558971387583', 'ja'), ('897292737452472946', 'uk'),
    ('2168411991469853368', 'de'), ('2307425329251826653', 'fa'), ('2452661550434610263', 'tr'),
    ('3655991679509066856', 'th'), ('3681435886557602253', 'en'), ('3771454461235531869', 'it'),
    ('4095510774501140142', 'ar'), ('4814355377128062865', 'ko'), ('5641437402179331405', 'es-419'),
    ('5795748004620209296', 'zh'), ('7019584478930992166', 'vi'), ('7082138383955241331', 'id'),
    ('7744489183918674408', 'pl'), ('7848768801791608136', 'ru'), ('7877477352716506018', 'hu'),
    ('8120530126288646203', 'es'), ('9187201611611882471', 'fr'),
)
SOURCES = tuple(YaoiMe((sid, 'Yaoi.me', lang, ROOT, True)) for sid, lang in LANGUAGES)
