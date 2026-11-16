"""HentaiNexus and its guest reader payload, following the upstream public format."""

import base64
import binascii
import json
import re
from urllib.parse import urlsplit

from manga_madara import image_url, node_text, release_date
from manga_series_port import Cards, Meta, SeriesPort
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceError

HOST = 'hentainexus.com'
ROOT = 'https://' + HOST
ID = r'[1-9]\d{0,11}'
READER = re.compile(r'initReader\(\s*"([A-Za-z0-9+/=\r\n]+)"\s*,')
PRIMES = (2, 3, 5, 7, 11, 13, 17, 19)


def reader_data(encoded):
    try:
        raw = bytearray(base64.b64decode(''.join(encoded.split()), validate=True))
    except binascii.Error:
        raise SourceError('HentaiNexus вернул повреждённый список изображений.') from None
    if len(raw) < 66:
        raise SourceError('HentaiNexus вернул неполные данные читалки.')
    for i, byte in enumerate(HOST.encode('ascii')):
        raw[i] ^= byte
    key = raw[:64]
    prime = 0
    for byte in key:
        prime ^= byte
        for _ in range(8):
            prime = (prime >> 1) ^ (12 if prime & 1 else 0)
    step = PRIMES[prime & 7]

    order = list(range(256))
    position = 0
    for i in range(256):
        position = (position + order[i] + key[i % 64]) % 256
        order[i], order[position] = order[position], order[i]
    cursor = second = carry = stream = 0
    for i in range(64, len(raw)):
        cursor = (cursor + step) % 256
        second = (carry + order[(second + order[cursor]) % 256]) % 256
        carry = (carry + cursor + order[cursor]) % 256
        order[cursor], order[second] = order[second], order[cursor]
        stream = order[(second + order[(cursor + order[(stream + carry) % 256]) % 256]) % 256]
        raw[i] ^= stream
    try:
        return json.loads(raw[64:].decode('latin-1'))
    except (TypeError, ValueError):
        raise SourceError('HentaiNexus изменил формат страницы.') from None


class HentaiNexus(SeriesPort):
    cards = Cards('.container .column:has(.card-header-title)', 'a[href]', '.card-header-title',
                  '.card-image img', next='a.pagination-next[href]')
    meta = Meta('h1.title', 'figure.image img', 'td.viewcolumn:-soup-contains-own("Description") + td',
                tags='.view-page-details span.tag a')

    def __init__(self):
        super().__init__(('7719798645438596394', 'HentaiNexus', 'en', ROOT, True),
                         rf'/view/({ID})/?', rf'/read/({ID})/?', interval=1)

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + '/view/' + key if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        if self.is_chapter(url):
            return self.title_for(url)
        key = urlsplit(url).path.strip('/')
        return ROOT + '/view/' + key if re.fullmatch(ID, key) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        key = self.title_key(title)
        return ROOT + '/read/' + key if key else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query.startswith('id:') and re.fullmatch(ID, query[3:]):
            if page > 1:
                return [], False
            target = ROOT + '/view/' + query[3:]
            return [self.details(http, target)], False
        hot = not query and not tag and sort == 'popular'
        if hot and page == 1:
            rows, _ = self.card_rows(*self.document(http, ROOT + '/explore/hot'), self.cards)
            return rows, bool(rows)
        if hot:
            page -= 1
            query = 'sort:popular'
        if tag and re.fullmatch(r'[\w -]{1,80}', tag):
            query = 'tag:"' + tag + '" ' + query
        target = ROOT + (f'/page/{page}' if page > 1 else '/')
        return self.card_rows(*self.document(http, query_url(target, q=query.strip()) if query else target), self.cards)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row['tags'] = [re.sub(r'\s*\([\d,]+\)$', '', tag) for tag in row['tags']]
        names = '.view-page-details td.viewcolumn:-soup-contains-own("Author") + td a, ' \
                '.view-page-details td.viewcolumn:-soup-contains-own("Artist") + td a, ' \
                '.view-page-details td.viewcolumn:-soup-contains-own("Circle") + td a'
        row.update(authors=list(dict.fromkeys(node_text(a) for a in doc.select(names) if node_text(a))), status='completed')
        return row

    def chapters(self, http, doc, final):
        stamp = node_text(doc.select_one('.view-page-details td.viewcolumn:-soup-contains-own("Published") + td'))
        url = ROOT + '/read/' + self.title_key(final)
        return [self.chapter(url, 'Chapter', 1, release_date(stamp, '%d %B %Y'))], False

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        match = READER.search(str(doc))
        if not match:
            raise SourceAccessError('HentaiNexus не предоставил гостевой список страниц.')
        data = reader_data(match[1])
        if not isinstance(data, list):
            raise SourceError('HentaiNexus изменил список страниц.')
        return [url for page in data if isinstance(page, dict) and page.get('type') == 'image'
                and (url := image_url(page.get('image_fallback') or page.get('image_avif'), final))]


SOURCES = (HentaiNexus(),)
