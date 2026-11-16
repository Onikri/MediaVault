"""Honeytoon language variants and tiled reader image transport."""

import json
import re
from io import BytesIO
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup
from PIL import Image
from PIL.Image import DecompressionBombError

from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, Meta, SeriesPort, picture
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://honeytoon.com'
HOST = 'honeytoon.com'
CDN = 'https://pic.honeytoon.com/'
SYNC = '/api/common/resource/sync'
SEARCH = re.compile(r'/(?:de/|es/|fr/|it/|pt/)?api/comic/search')
LANGUAGE_PATH = r'(?:/(?:de|es|fr|it|pt))?'
TOKEN = re.compile(r'[A-Za-z0-9_+./=-]{4,1800}')


def public_api(host, path, query):
    if host != HOST:
        return False
    if SEARCH.fullmatch(path):
        return not query
    parts = parse_qsl(query)
    return path == SYNC and len(parts) == 1 and parts[0][0] == 't' and bool(TOKEN.fullmatch(parts[0][1]))


def search_form(url, data):
    parts = urlsplit(url)
    return (parts.netloc == HOST and SEARCH.fullmatch(parts.path) and not parts.query and set(data) == {'query'}
            and isinstance(data['query'], str) and 1 <= len(data['query']) <= 160)


def merge_strips(raw, header):
    values = header.split(',')
    if not 1 <= len(values) <= 256 or not all(re.fullmatch(r'[1-9]\d{0,7}', v.strip()) for v in values):
        raise SourceError('Honeytoon вернул некорректные размеры частей страницы.')
    sizes = [int(v) for v in values]
    if sum(sizes) != len(raw):
        raise SourceError('Honeytoon вернул неполную страницу.')
    try:
        width = height = offset = 0
        strips = []
        for size in sizes:
            with Image.open(BytesIO(raw[offset:offset + size])) as block:
                offset += size
                width, height = max(width, block.width), height + block.height
                if width * height > 35_000_000:
                    raise SourceError('Размер страницы Honeytoon превышает лимит.')
                strips.append(block.convert('RGBA'))
        result = Image.new('RGBA', (width, height))
        top = 0
        for image in strips:
            result.paste(image, (0, top))
            top += image.height
        output = BytesIO()
        result.save(output, 'WEBP', lossless=True)
        return output.getvalue()
    except (OSError, ValueError, DecompressionBombError):
        raise SourceError('Honeytoon вернул повреждённую часть страницы.') from None


class HoneytoonPage:
    """A guest sync response may contain several consecutive image strips."""


class Honeytoon(SeriesPort):
    meta = Meta('h1', '.comic-book-img img', '.comic-book__desc', '',
                '.comic-book-content a[href*="genre"]', '.comic-tag', '.comic-book__story-art a')

    def __init__(self, sid, lang):
        self.locale = '' if lang == 'en' else ('/pt' if lang == 'pt-BR' else '/' + lang)
        title = rf'{LANGUAGE_PATH}/comic/({SEGMENT})'
        super().__init__((sid, 'Honeytoon', lang, ROOT, True), title + '/?',
                         title + rf'/{SEGMENT}/?', interval=.35)

    def page_url(self, slug):
        return ROOT + self.locale + '/comic/' + slug

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.page_url(key) if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        slug = self.title_key(url) or self.chapter_key(url)
        return self.page_url(slug) if slug else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page > 1:
            return [], False
        if query:
            path = ROOT + self.locale + '/api/comic/search'
            raw, final, _ = http.document(path, method='POST', data={'query': query}, action='native-series-form')
            if path != final:
                raise SourceError('Honeytoon перенаправил поиск.')
            results = json.loads(raw)
            if not isinstance(results, list):
                raise SourceError('Honeytoon изменил структуру поиска.')
            rows = []
            for item in results:
                url = self.site_link(item.get('link'))
                title = node_text(BeautifulSoup(item.get('title') or '', 'html.parser'))
                if title and self.is_title(url):
                    cover = image_url(CDN + str(item.get('image') or '').lstrip('/'), ROOT)
                    rows.append(self.record(self.page_url(self.title_key(url)), title, cover))
            return rows, False
        group = '.new' if sort == 'updated' else '.popular'
        cards = Cards(f'.section{group} .preview-card__link[href]', '', '.preview-card__title',
                      '.preview-card__image', next='')
        return self.card_rows(*self.document(http, ROOT + self.locale + '/ranking'), cards)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        if doc.select_one('.comic-book-content .label__item--complete'):
            row['status'] = 'completed'
        elif doc.select_one('.comic-book-content .label__item--dayofpublication'):
            row['status'] = 'ongoing'
        row['format'] = 'webtoon'
        return row

    def chapters(self, http, doc, final):
        rows = {}
        for index, anchor in enumerate(doc.select('.comic-list-items > a'), 1):
            target = self.site_link(anchor.get('href'), final)
            locked = bool(anchor.select_one('.lock-ico, .token-ico'))
            if locked:
                target = query_url(self.page_url(self.title_key(final)) + f'/locked-{index}', mv_honey_locked=1)
            if not self.is_chapter(target) or self.title_key(final) != self.chapter_key(target):
                continue
            label = node_text(anchor.select_one('.comic-list__title-desc'))
            stamp = node_text(anchor.select_one('.comic-list__title-date'))
            date = release_date(re.sub(r'\s+,', ',', stamp), '%B %d, %Y')
            row = self.chapter(target, label + (' 🔒' if locked else ''), date=date)
            if locked:
                row['available'] = False
            rows[target] = row
        return self.order(rows), False

    def pages(self, http, url):
        if param(url, 'mv_honey_locked') == '1' or urlsplit(url).fragment == 'locked':
            raise SourceAccessError('Глава доступна на условиях Honeytoon.')
        doc, final = self.page_document(http, url)
        result = []
        for element in doc.select('.single__item img, .comic-canvas-scramble'):
            if element.name == 'img':
                url = picture(element, final, ('data-src',))
                if url:
                    result.append((url, ('', '')))
                continue
            token = element.get('data-token', '')
            if not TOKEN.fullmatch(token):
                raise SourceError('Honeytoon не предоставил ресурс страницы.')
            url = query_url(ROOT + SYNC, t=token)
            result.append((url, HoneytoonPage()))
        return remember(result, final)


IDS = (('1063521896373496908', 'en'), ('5514199583083468982', 'es'), ('6559632390565356882', 'fr'),
       ('7482415595909557945', 'pt-BR'), ('8586216664933826829', 'de'), ('9071118557363497394', 'it'))
SOURCES = tuple(Honeytoon(*item) for item in IDS)
