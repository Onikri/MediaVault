"""マンガ図書館Z (keiyoushi ``src/ja/mangatoshokanz`` at 6f345a8).

Rankings, the ``addpage_renewal`` listing and series pages are public HTML.
The ``virgo`` viewer embeds its page list as Base64 JSON (``#doc``); every
page image is a strip of shuffled tiles, recomposed by the crops of the same
list exactly like the extension's ``DescrambleInterceptor``. Books still in
licence negotiation (``.iconConsent``) are skipped like upstream; the R18
mirror needs an age gate cookie and is not part of the public route.
"""

import base64
from dataclasses import dataclass
from io import BytesIO
import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from PIL import Image

from manga_direct_payloads import JsonSeries
from manga_japanese_readers import JapanesePage, packed_refs
from manga_madara import image_url, node_text
from manga_ninth_routes import Route, register
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://www.mangaz.com'
VIEWER = 'https://vw.mangaz.com'
ID = r'[1-9][0-9]{0,9}'
CATEGORIES = (('mens', '少年・男性'), ('womens', '少女・女性'), ('tl', 'TL'), ('bl', 'BL'))
IMAGE_HOSTS = frozenset({'mangaz-books.j-comi.jp', 'books.j-comi.jp'})
MAX_TILES = 64


def route(url, method, data, headers):
    if method != 'GET' or data is not None:
        return None
    if url.netloc == 'www.mangaz.com':
        if url.path == '/title/addpage_renewal':
            return Route(headers={'Cookie': '_LANG_=ja', 'X-Requested-With': 'XMLHttpRequest'})
        if url.path in {'/ranking/views', '/'} or re.fullmatch(rf'/(?:series|book)/detail/{ID}', url.path):
            return Route(headers={'Cookie': '_LANG_=ja'})
    if url.netloc == 'vw.mangaz.com' and re.fullmatch(rf'/virgo/view/{ID}', url.path) and not url.query:
        return Route(headers={'Cookie': '_LANG_=ja'})
    return None


register('mangaz', route)


def crops_from(item):
    scramble = item.get('scramble') if isinstance(item, dict) else None
    if not isinstance(scramble, dict):
        raise SourceError('マンガ図書館Z изменил формат страницы.')
    width, height, crops = scramble.get('w'), scramble.get('h'), scramble.get('crops')
    if (type(width) is not int or type(height) is not int or not 16 <= width <= 8000 or not 16 <= height <= 12000
            or not isinstance(crops, list) or not 1 <= len(crops) <= MAX_TILES):
        raise SourceError('マンガ図書館Z изменил формат страницы.')
    rows = []
    for crop in crops:
        values = tuple(crop.get(key) if isinstance(crop, dict) else None for key in ('x', 'y', 'x2', 'y2', 'w', 'h'))
        if any(type(value) is not int or not 0 <= value <= 40000 for value in values):
            raise SourceError('マンガ図書館Z изменил формат страницы.')
        rows.append(values)
    return width, height, tuple(rows)


def descramble(data, width, height, crops):
    """Each crop copies (x2, y2, w, h) of the tile strip to (x, y) of the page."""
    try:
        with Image.open(BytesIO(data)) as strip, strip.convert('RGB') as source:
            result = Image.new('RGB', (width, height), 'white')
            for x, y, x2, y2, w, h in crops:
                with source.crop((x2, y2, x2 + w, y2 + h)) as tile:
                    result.paste(tile, (x, y))
            output = BytesIO()
            result.save(output, 'JPEG', quality=90)
            return output.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise SourceError('Источник вернул повреждённое изображение.') from None


@dataclass(frozen=True)
class MangazPage(JapanesePage):
    width: int = 0
    height: int = 0
    crops: tuple = ()

    def fetch(self, http, referer):
        from manga_page_media import read_image

        response, _ = http._open(self.url, headers={'Referer': VIEWER + '/'})
        return descramble(read_image(http, response), self.width, self.height, self.crops)


class MangaToshokanZ(JsonSeries):
    def __init__(self):
        super().__init__(('7564150377964448106', 'マンガ図書館Z', 'ja', ROOT, False),
                         rf'/series/detail/({ID})', rf'/virgo/view/({ID})', hosts=('vw.mangaz.com',), interval=.4)

    def is_title(self, url):
        parts = urlsplit(url)
        return parts.hostname == 'www.mangaz.com' and bool(self.TITLE_PATH.fullmatch(parts.path)) and not parts.query

    def is_chapter(self, url):
        parts = urlsplit(url)
        return (parts.hostname == 'vw.mangaz.com' and bool(self.CHAPTER_PATH.fullmatch(parts.path))
                and bool(re.fullmatch(ID, param(url, 'mv_series'))))

    def title_for(self, url):
        series = param(url, 'mv_series')
        return f'{ROOT}/series/detail/{series}' if re.fullmatch(ID, series) else ''

    def chapter_identity(self, url):
        return urlsplit(url).path

    def saved_title_url(self, value):
        # Suwayomi stored the bare series ID.
        if isinstance(value, str) and re.fullmatch(ID, value.strip('/')):
            return f'{ROOT}/series/detail/{value.strip("/")}'
        return self.canonical(value)

    def saved_chapter(self, row, root, title):
        value = str(row.get('realUrl') or row.get('url') or '').strip('/')
        series = self.title_key(title)
        book = value if re.fullmatch(ID, value) else self.chapter_key(self.canonical(value))
        if series and re.fullmatch(ID, book or ''):
            return query_url(f'{VIEWER}/virgo/view/{book}', mv_series=series)
        return ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and param(target, 'mv_series') == self.title_key(title)

    def html(self, http, url, xhr=False):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': ROOT + '/'}, action='n9:mangaz')
        return BeautifulSoup(raw, 'html.parser'), final

    def card(self, node, final):
        if node.select_one('.iconConsent'):
            return None
        anchor = node.select_one('a[href*="/series/detail/"]')
        url = self.canonical(urljoin(final, anchor['href'])) if anchor else ''
        title = node_text(node.select_one('h4, h2, span.trim'))
        if not self.is_title(url) or not title:
            return None
        image = node.select_one('img')
        cover = image_url((image.get('data-src') or image.get('src')) if image else '', final)
        return self.record(url, title, cover, authors=(node_text(node.select_one('p.author')),))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and tag not in dict(CATEGORIES):
            return [], False
        if not query and not tag and sort != 'updated':
            if page != 1:
                return [], False
            doc, final = self.html(http, ROOT + '/ranking/views')
            nodes = doc.select('.itemListMod ul.itemList > li, ul.rankingListThum > li')
            rows = {row['id']: row for node in nodes if (row := self.card(node, final))}
            return list(rows.values()), False
        args = {'query': query} if query else {'type': 'official', 'sort': 'new'}
        if tag:
            args['category'] = tag
        args['page'] = page
        doc, final = self.html(http, query_url(ROOT + '/title/addpage_renewal', **args), xhr=True)
        nodes = doc.find_all('li', recursive=False) or doc.select('body > li')
        rows = {row['id']: row for node in nodes if (row := self.card(node, final))}
        return list(rows.values()), len(nodes) >= 50

    def vocabulary(self, http):
        return [{'key': key, 'label': label, 'kind': 'genre'} for key, label in CATEGORIES]

    def series(self, http, url):
        url = self.saved_title_url(url)
        series = self.title_key(url)
        if not series:
            raise SourceError('Некорректная ссылка на тайтл マンガ図書館Z.')
        doc, final = self.html(http, url)
        meta = doc.select_one('meta[property="og:title"][content]')
        heading, _, _ = (meta['content'] if meta else '').rpartition(' | ')
        title, _, author = heading.rpartition(' - ')
        title = title or node_text(doc.select_one('.GA4_booktitle')) or heading
        if not title:
            raise SourceError('マンガ図書館Z не предоставил карточку тайтла.')
        image = doc.select_one('.itemList li img, meta[property="og:image"][content]')
        cover = image_url((image.get('content') or image.get('src')) if image else '', final)
        description = node_text(doc.select_one('.wordbreak'))
        row = self.record(url, title.strip(), cover, description=description, authors=(author.strip(),))
        chapters = []
        book_page = re.fullmatch(rf'/book/detail/({ID})', urlsplit(final).path)
        if book_page:
            # A single book redirects from its series page to the book page.
            target = query_url(f'{VIEWER}/virgo/view/{book_page[1]}', mv_series=series)
            chapters.append(self.chapter(target, title.strip(), 1.0))
            return row, chapters
        items = doc.select('.itemList li')
        for index, item in enumerate(reversed(items), 1):
            anchor = item.select_one('a[href*="/book/detail/"]')
            match = re.search(rf'/book/detail/({ID})$', anchor.get('href', '')) if anchor else None
            if not match:
                continue
            label = node_text(item.select_one('.title'))
            name = f'第{label}巻' if label.isdigit() else label or f'第{index}巻'
            target = query_url(f'{VIEWER}/virgo/view/{match[1]}', mv_series=series)
            chapters.append(self.chapter(target, name, float(label) if label.isdigit() else float(index)))
        return row, self.order({row['url']: row for row in chapters})

    def pages(self, http, url):
        book = self.chapter_key(url)
        doc, _ = self.html(http, f'{VIEWER}/virgo/view/{book}')
        node = doc.select_one('#doc')
        try:
            data = json.loads(base64.b64decode(node.get_text(strip=True)) if node else b'')
        except (ValueError, TypeError):
            raise SourceAccessError('Выпуск マンガ図書館Z недоступен для открытого чтения.') from None
        location = data.get('Location') if isinstance(data, dict) else None
        orders = data.get('Orders') if isinstance(data, dict) else None
        if not isinstance(location, dict) or not isinstance(orders, list) or not orders:
            raise SourceAccessError('Выпуск マンガ図書館Z недоступен для открытого чтения.')
        base = str(location.get('base') or '')
        folder = str(location.get('scramble_dir') or '')
        if (urlsplit(base).hostname not in IMAGE_HOSTS or not base.startswith('https://')
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', folder)):
            raise SourceError('マンガ図書館Z изменил адрес изображений.')
        rows = []
        for item in sorted((item for item in orders if isinstance(item, dict)), key=lambda item: item.get('no', 0)):
            name = str(item.get('name') or '')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}\.(?:jpe?g|png|webp)', name):
                raise SourceError('マンガ図書館Z изменил формат страницы.')
            width, height, crops = crops_from(item)
            rows.append(MangazPage(f'{base.rstrip("/")}/{folder}/{name}', width=width, height=height, crops=crops))
        return packed_refs(rows, url)


SOURCES = (MangaToshokanZ(),)
