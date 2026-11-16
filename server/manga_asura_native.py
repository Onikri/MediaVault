"""Asura Scans stable bookmarks, Astro metadata and open chapter pages."""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup
from PIL import Image
from PIL.Image import DecompressionBombError

from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import MAX_PAGES, SeriesPort, number
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://asurascans.com'
API = 'https://api.asurascans.com/api'
TITLE = rf'/(?:comics|series|manga)/({SEGMENT})/?'
ORDINAL = r'\d{1,8}(?:\.\d{1,4})?'
CHAPTER = rf'/(?:comics|series|manga)/({SEGMENT})/chapter/({ORDINAL})/?'
SUFFIX = re.compile(r'-[a-z0-9]{8}$')


def public_api(host, path, query):
    if host != 'api.asurascans.com' or path not in {'/api/series', '/api/creators'}:
        return False
    if path == '/api/creators':
        return not query
    pairs = parse_qsl(query)
    args = dict(pairs)
    core = {'limit', 'offset'}
    allowed = core | {'search', 'genres', 'sort', 'order'}
    sorting = (args.get('sort'), args.get('order'))
    return (len(pairs) == len(args) and core <= set(args) <= allowed
            and args['limit'] == '20' and bool(re.fullmatch(r'\d{1,6}', args['offset']))
            and sorting in ((None, None), ('latest', 'desc'), ('popular', 'desc'))
            and all(len(v) <= 160 for v in args.values()))


def unwrap_astro(value, depth=0):
    if depth > 60:
        raise SourceError('Asura Scans вернул повреждённые данные страницы.')
    if isinstance(value, list):
        if not value or len(value) == 1 and type(value[0]) is int:
            return None
        if len(value) == 2 and type(value[0]) is int:
            return unwrap_astro(value[1], depth + 1)
        return [unwrap_astro(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {k: unwrap_astro(v, depth + 1) for k, v in value.items()}
    return value


def props_for(doc, *keys):
    for node in doc.select('astro-island[props], [data-astro-component][props]'):
        raw = node.get('props', '')
        if not all(f'"{key}"' in raw for key in keys):
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict) and all(key in obj for key in keys):
            return unwrap_astro(obj)
    return {}


@dataclass(frozen=True)
class GridPage:
    cols: int
    rows: int
    order: tuple

    def decode(self, raw):
        try:
            with Image.open(BytesIO(raw)) as image:
                if image.width * image.height > 35_000_000:
                    raise SourceError('Страница Asura Scans превышает лимит размера.')
                bitmap = image.convert('RGB')
            tile_width, tile_height = bitmap.width // self.cols, bitmap.height // self.rows
            if min(tile_width, tile_height) < 1:
                raise SourceError('Asura Scans вернул неверный размер плиток.')
            output = Image.new('RGB', (tile_width * self.cols, tile_height * self.rows))
            for src, dst in enumerate(self.order):
                x1, y1 = (src % self.cols) * tile_width, (src // self.cols) * tile_height
                x2, y2 = (dst % self.cols) * tile_width, (dst // self.cols) * tile_height
                output.paste(bitmap.crop((x1, y1, x1 + tile_width, y1 + tile_height)), (x2, y2))
            encoded = BytesIO()
            output.save(encoded, 'WEBP', lossless=True)
            return encoded.getvalue()
        except (OSError, ValueError, DecompressionBombError):
            raise SourceError('Asura Scans вернул повреждённое изображение.') from None


class AsuraScans(SeriesPort):
    def __init__(self):
        super().__init__(('6247824327199706550', 'Asura Scans', 'en', ROOT, False),
                         TITLE, CHAPTER, hosts=('www.asurascans.com',), interval=.5)

    def stable_slug(self, url):
        match = self.TITLE_PATH.fullmatch(urlsplit(url).path) or self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        if not match:
            return ''
        key = match[1]
        path = urlsplit(url).path
        if path.startswith('/comics/'):
            return SUFFIX.sub('', key)
        if path.startswith('/manga/'):
            return re.sub(r'^\d+-', '', key)
        return key

    def title_key(self, url):
        return self.stable_slug(url) if self.is_title(url) else ''

    def chapter_key(self, url):
        return self.stable_slug(url) if self.is_chapter(url) else ''

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + '/series/' + key if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        key = self.chapter_key(url) or urlsplit(url).path.strip('/')
        return ROOT + '/series/' + key if re.fullmatch(SEGMENT, key) else ''

    def chapter_identity(self, url):
        found = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return (self.chapter_key(url), number(found[2])) if found else ('', None)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'offset': (page - 1) * 20, 'limit': 20}
        if not query and not tag:
            args.update(sort='latest' if sort == 'updated' else 'popular', order='desc')
        if query:
            args['search'] = query
        if re.fullmatch(SEGMENT, tag):
            args['genres'] = tag
        data = self.json(http, query_url(API + '/series', **args))
        rows = []
        for item in data.get('data') or []:
            public = self.site_link(item.get('public_url'))
            slug = item.get('slug', '')
            name = item.get('title')
            if self.is_title(public) and name and re.fullmatch(SEGMENT, slug):
                target = query_url(ROOT + '/series/' + slug, mv_asura_path=urlsplit(public).path)
                rows.append(self.record(target, name, image_url(item.get('cover') or item.get('coverUrl'), public)))
        return rows, bool((data.get('meta') or {}).get('has_more'))

    def vocabulary(self, http):
        doc, _ = self.document(http, ROOT + '/browse')
        return [{'key': row['slug'], 'label': row['name'], 'kind': 'genre'}
                for row in (props_for(doc, 'availableGenres').get('availableGenres') or [])
                if isinstance(row, dict) and isinstance(row.get('slug'), str) and isinstance(row.get('name'), str)]

    def title_data(self, http, url):
        slug = self.title_key(url)
        if not slug:
            raise SourceError('Некорректный тайтл Asura Scans.')
        path = param(url, 'mv_asura_path') or urlsplit(url).path
        target = self.site_link(path) if path.startswith('/comics/') else ROOT + '/comics/' + slug
        if not self.is_title(target) or self.title_key(target) != slug:
            target = ROOT + '/comics/' + slug
        try:
            doc, final = self.document(http, target)
        except SourceError:
            if target == ROOT + '/comics/' + slug:
                raise
            doc, final = self.document(http, ROOT + '/comics/' + slug)
        hints = props_for(doc, 'publicUrl')
        identity = hints.get('seriesSlug') or self.title_key(final)
        public = self.site_link(hints.get('publicUrl') or final)
        if identity != slug or not self.is_title(public):
            raise SourceError('Asura Scans перенаправил на другой тайтл.')
        entry = props_for(doc, 'title', 'description')
        if not isinstance(name := entry.get('title'), str) or not name:
            raise SourceError('Asura Scans не предоставил карточку.')
        state = str(entry.get('status') or '').casefold()
        aliases = re.split(r'\s*[•,]\s*', str(entry.get('alternativeTitles') or ''))
        summary = self.record(query_url(ROOT + '/series/' + slug, mv_asura_path=urlsplit(public).path), name,
                              image_url(entry.get('coverUrl'), public), aliases=aliases,
                              authors=[entry.get('author'), entry.get('artist')],
                              genres=[row.get('name') for row in entry.get('genres') or [] if isinstance(row, dict)],
                              description=node_text(BeautifulSoup(entry.get('description') or '', 'html.parser')),
                              status='cancelled' if state in ('dropped', 'axed') else state)
        summary['format'] = str(entry.get('type') or 'manga').lower()
        return summary, public, doc

    def details(self, http, url):
        return self.title_data(http, self.saved_title_url(url))[0]

    @staticmethod
    def locked(entry):
        if entry.get('is_premium') or entry.get('is_locked'):
            return True
        try:
            return datetime.fromisoformat(str(entry.get('early_access_until') or '').replace('Z', '+00:00')) > datetime.now(timezone.utc)
        except (ValueError, TypeError):
            return False

    def chapters(self, url, public, doc):
        result = {}
        for row in props_for(doc, 'chapters').get('chapters') or []:
            n = number(row.get('number'))
            if n is None or self.locked(row):
                continue
            target = query_url(url.split('?', 1)[0].rstrip('/') + f'/chapter/{n:g}', mv_asura_path=urlsplit(public).path)
            title = f'Chapter {n:g}' + (' - ' + str(row['title']) if row.get('title') else '')
            result[target] = self.chapter(target, title, n, str(row.get('created_at') or '')[:10])
        return self.order(result)

    def pages(self, http, url):
        key, ordinal = self.chapter_identity(url)
        if ordinal is None:
            raise SourceError('Некорректная глава Asura Scans.')
        path = param(url, 'mv_asura_path')
        if not path and urlsplit(url).path.startswith('/comics/'):
            path = urlsplit(url).path.split('/chapter/', 1)[0]
        public = self.site_link(path) if path.startswith('/comics/') else ''
        if not self.is_title(public) or self.title_key(public) != key:
            _, public, _ = self.title_data(http, self.title_for(url))
        target = public.rstrip('/') + f'/chapter/{ordinal:g}'
        try:
            doc, final = self.document(http, target)
        except SourceError:
            _, public, _ = self.title_data(http, self.title_for(url))
            target = public.rstrip('/') + f'/chapter/{ordinal:g}'
            doc, final = self.document(http, target)
        if self.chapter_identity(final) != (key, ordinal):
            raise SourceError('Asura Scans перенаправил на другую главу.')
        records = props_for(doc, 'pages').get('pages')
        if not isinstance(records, list) or not 1 <= len(records) <= MAX_PAGES:
            raise SourceAccessError('Asura Scans не предоставил открытые страницы.')
        refs = []
        for row in records:
            src = image_url(row.get('url'), final)
            if not src:
                raise SourceError('Asura Scans не предоставил изображение страницы.')
            tiles = row.get('tiles')
            if not tiles:
                refs.append((src, ('', '')))
                continue
            cols, rows = row.get('tile_cols') or 4, row.get('tile_rows') or 5
            if (type(cols) is not int or type(rows) is not int or not 1 <= cols <= 25 or not 1 <= rows <= 25
                    or not isinstance(tiles, list) or any(type(tile) is not int for tile in tiles)
                    or len(tiles) != cols * rows or set(tiles) != set(range(cols * rows))):
                raise SourceError('Asura Scans вернул неизвестный порядок плиток.')
            refs.append((src, GridPage(cols, rows, tuple(tiles))))
        return remember(refs, final)

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_title(url):
            return super().inspect(url, http)
        row, public, doc = self.title_data(http, url)
        chapters = self.chapters(url, public, doc)
        return self.reader_result(row, url, chapters, [])


SOURCES = (AsuraScans(),)
