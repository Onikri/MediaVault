"""ToonLook language editions and horizontal strip decoder (Keiyoushi, Apache-2.0)."""

import base64
import binascii
import hashlib
from io import BytesIO
import json
import re
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit
import warnings

from PIL import Image

from manga_direct_catalogues import SLUG
from manga_html_archives import LinkedArchive
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, MAX_PAGES, Meta
from manga_speedbinb import compose, remember
from manga_webcomics import param, query_url
from source_parser import SourceError


ROOT = 'https://toonlook.com'
LANG = re.compile(r'[a-z]{2,3}(?:-[a-zA-Z0-9]{2,8}){0,2}')
DATA = re.compile(r'\bchapterData\s*=\s*')
U32 = (1 << 32) - 1


def strip_order(length, url, language, salt, height):
    parts = [unquote(value).lower() for value in urlsplit(url).path.split('/') if value]
    index = next((i for i, value in enumerate(parts) if value == language.lower()), -1)
    seed_key = '/'.join(parts[index:index + 4] if 0 <= index <= len(parts) - 4 else parts[-4:])
    state = int.from_bytes(hashlib.sha256(f'{salt}|{height}|{seed_key}'.encode()).digest()[:4], 'big')
    order = list(range(length))
    for i in range(length - 1, 0, -1):
        state = (state + 0x6d2b79f5) & U32
        value = ((state ^ (state >> 15)) * (state | 1)) & U32
        value ^= (value + ((value ^ (value >> 7)) * (value | 61))) & U32
        rand = value ^ (value >> 14)
        swap = (rand * (i + 1)) >> 32
        order[i], order[swap] = order[swap], order[i]
    return order


class Strips:
    def __init__(self, url, language, salt, height):
        self.url, self.language, self.salt, self.height = url, language, salt, height

    def decode(self, raw):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as image:
                    width, height = image.size
            if width * height > 24_000_000 or height // self.height > 10000:
                raise ValueError('Image size')
            order = strip_order(height // self.height, self.url, self.language, self.salt, self.height)
            layout = [(0, i * self.height, width, self.height, 0, dest * self.height)
                      for i, dest in enumerate(order)]
            rest = height - len(order) * self.height
            if rest:
                start = height - rest
                layout.append((0, start, width, rest, 0, start))
            return compose(raw, (width, height, layout))
        except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
            raise SourceError('ToonLook вернул повреждённую страницу.') from None


class ToonLook(LinkedArchive):
    cards = Cards('.manga-item', 'a.manga-item__link', cover='img.manga-item__img-inner', next='a.next')
    chinese_cards = Cards('.manga-item:has(img.mangora-flag--card[alt="中文"])', 'a.manga-item__link',
                          cover='img.manga-item__img-inner', next='a.next')
    meta = Meta('.manga-titles h1', 'img[src*="/img/cover/"]', '.manga-desc__content', '.manga-titles h2',
                genres='.manga-genres a', author='div.items-start a[rel=tag][href*="/manga-author/"] > span:first-child')

    def __init__(self, identity):
        super().__init__(identity, rf'/manhwa/{SLUG}/?', rf'/{SLUG}/?', interval=.35)

    def saved_title_url(self, value):
        target = self.canonical(value)
        key = self.title_key(target) or urlsplit(target).path.strip('/')
        return self.ROOT + '/manhwa/' + key + '/' if re.fullmatch(SEGMENT, key) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if not self.is_chapter(target):
            return ''
        language = param(target, 'lang') if self.LANGUAGE == 'all' else self.LANGUAGE
        return query_url(target, lang=language) if LANG.fullmatch(language) else ''

    def chapter_identity(self, value):
        return self.chapter_key(value), param(value, 'lang')

    @staticmethod
    def upstream(url):
        parts = urlsplit(url)
        values = {key: val for key, val in parse_qsl(parts.query) if key == 'lang'}
        return query_url(urlunsplit(parts._replace(query='', fragment='')), **values)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        path = '' if query else '/manhwa'
        args = {'s': query} if query else {'sortby': 'latest' if sort == 'updated' else 'daily_top'}
        if not query and re.fullmatch(SEGMENT, tag):
            args['genre'] = tag
        path += f'/page/{page}/' if page > 1 else '/'
        cards = self.chinese_cards if self.LANGUAGE == 'zh' else self.cards
        return self.card_rows(*self.document(http, query_url(self.ROOT + path, **args)), cards)

    def vocabulary(self, http):
        rows = self.json(http, self.ROOT + '/wp-json/wp/v2/genre?per_page=100')
        return [{'label': row['name'], 'sourceId': row['slug'], 'category': 'genre'} for row in rows if
                isinstance(row, dict) and row.get('name') and re.fullmatch(SEGMENT, str(row.get('slug', '')))] if isinstance(rows, list) else []

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        record = self.metadata(doc, final, self.meta)
        record['format'] = 'manhwa'
        status = doc.select_one('.manga-status[data-status]')
        if status:
            record['status'] = status['data-status']
        rows = {}
        for node in doc.select('a.chapter-item[href][data-langs]'):
            href = self.site_link(node['href'], final)
            parts = urlsplit(href).path.strip('/').split('/')
            if not href or not parts or not re.fullmatch(SEGMENT, parts[-1]):
                continue
            date = release_date(node_text(node.select_one('.chapter-item__date')), '%d/%m/%y')
            languages = [lang for lang in node['data-langs'].split() if LANG.fullmatch(lang) and self.LANGUAGE in ('all', lang)]
            for language in languages:
                target = query_url(f'{self.ROOT}/{parts[-1]}', lang=language, mv_title=urlsplit(final).path)
                label = node.get('data-title-' + language) or node_text(node.select_one('.chapter-item__name'))
                rows[target] = self.chapter(target, label, date=date)
                rows[target]['language'] = language
        return record, self.order(rows)

    def pages(self, http, url):
        doc, final = self.chapter_document(http, url)
        language = param(url, 'lang')
        if not LANG.fullmatch(language):
            raise SourceError('Не указан язык главы ToonLook.')
        try:
            data = None
            for script in doc.select('script:not([src])'):
                raw = script.string or ''
                if match := DATA.search(raw):
                    data = json.JSONDecoder().raw_decode(raw, match.end())[0]
                    break
            if not isinstance(data, dict) or not isinstance(data.get('data'), str) or len(data['data']) > 1_000_000:
                raise ValueError('Invalid manifest')
            if data.get('lang') != language:
                raise ValueError('Wrong reader language')
            rows = json.loads(base64.b64decode(data['data'], validate=True))
            if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_PAGES:
                raise ValueError('Invalid page count')
            base = data['base'].rstrip('/') + '/'
            values = [image_url(base + item['src'].lstrip('/'), final) for item in rows]
            if not all(values):
                raise ValueError('Missing image')
            layout = data.get('imageScramble') or {}
            if not layout.get('enabled'):
                return values
            salt, height = layout['salt'], layout.get('stripHeight', 500)
            if not isinstance(salt, str) or not 1 <= len(salt) <= 160 or type(height) is not int or not 4 <= height <= 10000:
                raise ValueError('Invalid strip key')
            return remember([(value, Strips(value, language, salt, height)) for value in values], final)
        except (KeyError, AttributeError, TypeError, ValueError, RecursionError, binascii.Error):
            raise SourceError('ToonLook изменил формат данных главы.') from None


def public_api(host, path, query):
    return host == 'toonlook.com' and path == '/wp-json/wp/v2/genre' and query == 'per_page=100'


SOURCES = tuple(ToonLook((sid, 'ToonLook', lang, ROOT, True)) for sid, lang in (
    ('5303680762449162883', 'zh'), ('5739821732870359662', 'all'), ('8320348786843379620', 'en'),
))
