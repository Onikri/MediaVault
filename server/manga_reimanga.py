"""ReiManga catalogue, React Flight reader and byte-ranged WebP packs."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from manga_additional_catalogues import flight_objects
from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, image_url
from manga_public_zip import PAGE_LIMIT, range_bytes
from manga_series_port import MAX_PAGES, number
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://reimanga.net'
HOST = 'reimanga.net'
ID = r'[1-9]\d{0,16}'
TITLE_KEY = rf'{SEGMENT}-{ID}'
TITLE = rf'/manga/({TITLE_KEY})/?'
CHAPTER = rf'/manga/({TITLE_KEY})/({ID})/?'
LIST = '/api/manga'
PACK_START = 'mv_rei_offset'


def public_api(host, path, query):
    if host != HOST:
        return False
    if path == LIST + '/trending':
        return query == 'limit=100'
    if re.fullmatch(LIST + '/' + ID, path):
        return not query
    if path != LIST:
        return False
    pairs = parse_qsl(query)
    args = dict(pairs)
    required = {'page', 'limit', 'sort', 'order'}
    optional = {'search', 'genre', 'tag'}
    return (len(args) == len(pairs) and required <= set(args) <= required | optional
            and args['limit'] == '24' and args['order'] == 'desc' and args['sort'] in {'latest', 'viewed'}
            and bool(re.fullmatch(r'[1-9]\d{0,3}', args['page'])) and all(len(value) <= 160 for value in args.values()))


def public_rsc(host, path, query):
    return host == HOST and not query and (path == '/advanced-search' or bool(re.fullmatch(TITLE, path) or re.fullmatch(CHAPTER, path)))


@dataclass(frozen=True)
class PackedWebp:
    url: str
    offset: int
    size: int

    def fetch(self, http, referer):
        raw, _ = range_bytes(http, self.url, self.offset, self.offset + self.size - 1, referer=referer)
        return raw


def pack_pages(data, base):
    index = data.get('index') or {}
    urls, counts, sizes = data.get('urls'), index.get('s'), index.get('p')
    if not all(isinstance(value, list) for value in (urls, counts, sizes)) or len(urls) != len(counts):
        raise SourceError('ReiManga изменил описание сегментов главы.')
    if not 1 <= len(sizes) <= MAX_PAGES or not all(type(n) is int and 0 <= n <= len(sizes) for n in counts) or sum(counts) != len(sizes):
        raise SourceError('ReiManga не предоставил полный индекс страниц.')
    result = []
    cursor = 0
    for href, count in zip(urls, counts):
        target = image_url(href, base)
        if not target or param(target, PACK_START):
            raise SourceError('ReiManga вернул ошибочную ссылку на сегмент.')
        offset = 0
        for dimensions in sizes[cursor:cursor + count]:
            if not isinstance(dimensions, list) or not dimensions or type(dimensions[0]) is not int or not 1 <= dimensions[0] <= PAGE_LIMIT:
                raise SourceError('ReiManga вернул некорректный размер страницы.')
            size = dimensions[0]
            result.append((query_url(target, **{PACK_START: offset}), PackedWebp(target, offset, size)))
            offset += size
        cursor += count
    return result


class ReiManga(JsonSeries):
    def __init__(self):
        super().__init__(('5627909338430537186', 'ReiManga', 'en', ROOT, True),
                         TITLE, CHAPTER, interval=.35)

    @staticmethod
    def key(value):
        number = str(value.get('id', ''))
        slug = str(value.get('name_url', ''))
        return slug + '-' + number if re.fullmatch(SEGMENT, slug) and re.fullmatch(ID, number) else ''

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + '/manga/' + key if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        if self.is_title(url):
            return url
        if self.is_chapter(url):
            return self.title_for(url)
        return ROOT + '/manga/' + key if re.fullmatch(TITLE_KEY, key) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        path = urlsplit(target).path.strip('/')
        if re.fullmatch(rf'{TITLE_KEY}/{ID}', path):
            return ROOT + '/manga/' + path
        if self.is_title(title) and re.fullmatch(ID, path):
            return title.rstrip('/') + '/' + path
        return ''

    def rsc(self, http, target):
        self.origin.wait(getattr(http, 'deadline', None))
        payload, final, _ = http.document(target, headers={'Referer': ROOT + '/'}, action='native-series-rsc')
        if not final.startswith(ROOT + '/') or urlsplit(final).path.rstrip('/') != urlsplit(target).path.rstrip('/'):
            raise SourceError('ReiManga перенаправил публичный запрос ридера.')
        return flight_objects(payload)

    def summary(self, item):
        key = self.key(item)
        name = item.get('title')
        if not key or not isinstance(name, str) or not name:
            return None
        url = ROOT + '/manga/' + key
        cover = image_url(item.get('cover_url') or f'/covers/{item["id"]}/thumbnail.png', url)
        aliases = re.split(r'\s*[,;]\s*|\s+/\s+', str(item.get('alt_title') or ''))
        authors = [entry.get('name') for entry in item.get('authors') or [] if isinstance(entry, dict)]
        genres = [entry.get('name') for entry in item.get('genres') or [] if isinstance(entry, dict)]
        tags = [entry.get('name') for entry in item.get('tags') or [] if isinstance(entry, dict)]
        row = self.record(url, name, cover, aliases=aliases, authors=authors, genres=genres, tags=tags,
                          status='completed' if item.get('completed') == 1 else 'ongoing' if 'completed' in item else '',
                          description=item.get('ai_description') or item.get('description') or '')
        if item.get('is_adult') == 1:
            row['isNsfw'] = True
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page == 1 and not query and not tag and sort == 'popular':
            result, more = self.json(http, ROOT + LIST + '/trending?limit=100'), True
        else:
            args = {'page': page - 1 if sort == 'popular' and not query and not tag else page,
                    'limit': 24, 'sort': 'viewed' if sort == 'popular' else 'latest', 'order': 'desc'}
            if query:
                args['search'] = query
            if tag:
                kind, _, text = tag.partition(':')
                args[kind if kind in {'genre', 'tag'} and text else 'genre'] = (text or tag)[:160]
            data = self.json(http, query_url(ROOT + LIST, **args))
            result = data.get('data', data.get('initialData'))
            pages = data.get('pagination') or {}
            more = (number(pages.get('totalPages')) or 0) > (number(pages.get('currentPage')) or args['page'])
        if not isinstance(result, list):
            raise SourceError('ReiManga изменил структуру каталога.')
        return [row for item in result if isinstance(item, dict) and (row := self.summary(item))], more

    def vocabulary(self, http):
        objects = self.rsc(http, ROOT + '/advanced-search')
        groups = next((item for item in objects if isinstance(item.get('genres'), list)
                       and isinstance(item.get('tags'), list)), {})
        return [{'key': kind + ':' + row['slug'], 'label': row['name'], 'kind': kind}
                for kind in ('genre', 'tag') for row in groups.get(kind + 's', [])
                if isinstance(row, dict) and isinstance(row.get('name'), str) and isinstance(row.get('slug'), str)]

    def main_series(self, http, url):
        identity = self.title_key(url).rsplit('-', 1)[-1]
        data = self.json(http, ROOT + LIST + '/' + identity).get('manga') or {}
        main_id = str(data.get('main_manga_id') or identity)
        if main_id != identity and re.fullmatch(ID, main_id):
            data = self.json(http, ROOT + LIST + '/' + main_id).get('manga') or {}
        row = self.summary(data)
        if not row or str(data.get('id')) != main_id:
            raise SourceError('ReiManga не предоставил нужный тайтл.')
        return row, data

    def details(self, http, value):
        url = self.saved_title_url(value)
        if not self.is_title(url):
            raise SourceError('Некорректная ссылка на тайтл ReiManga.')
        return self.main_series(http, url)[0]

    def series(self, http, url):
        row, data = self.main_series(http, url)
        target = self.site_link(row['url'])
        result = self.rsc(http, target)
        series = next((item for item in result if isinstance(item.get('manga'), dict) and
                       self.key(item['manga']) == self.key(data) and isinstance(item.get('chapters'), list)), {})
        chapters = {}
        for item in series.get('chapters', []):
            cid = str(item.get('id', ''))
            title = ' '.join(str(item.get('name', '')).split())
            if re.fullmatch(ID, cid):
                url = target.rstrip('/') + '/' + cid
                date = str(item.get('gdrive_upload_date') or item.get('updated_at') or item.get('created_at') or '')[:10]
                chapters[url] = self.chapter(url, title, date=date)
        return row, self.order(chapters)

    def pages(self, http, url):
        objects = self.rsc(http, url)
        result = next((item for item in objects if isinstance(item.get('images'), list) or isinstance(item.get('pack'), dict)), {})
        if isinstance(result.get('pack'), dict):
            return remember(pack_pages(result['pack'], url), url)
        return [src for item in result.get('images', []) if isinstance(item, dict)
                and (src := image_url(item.get('image_url'), url))]


SOURCES = (ReiManga(),)
