"""ParadiseScans, Nuviatoon and Renascans public JSON readers."""

import json
import re
from collections import OrderedDict
from threading import Lock
from time import time
from urllib.parse import parse_qs, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_direct_catalogues import SERIES, SLUG
from manga_direct_payloads import JsonSeries, items, segment, strings
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import MAX_CHAPTERS, MAX_PAGES, NUMBER, document_json, number
from manga_source_tags import labels
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


PARADISE = 'paradisescans.com'
NUVIA = 'nuviatoon.org'
RENA = 'renascans.net'
RENA_ROOT = 'https://' + RENA
KEY = r'[A-Za-z0-9_-]{1,150}'
COUNT = r'[1-9]\d{0,7}'
RENA_MARK = 'mv_rena_page='
RENA_CACHE = OrderedDict()
RENA_LOCK = Lock()


def public_api(host, path, query):
    if host not in {PARADISE, NUVIA, RENA}:
        return False
    args = parse_qs(query)
    if not all(len(v) == 1 and 1 <= len(v[0]) <= 160 for v in args.values()):
        return False
    if host == PARADISE:
        if path == '/api/series':
            return ({'page', 'per_page', 'sort'} <= set(args) <= {'page', 'per_page', 'sort', 'dir', 'q', 'genres'}
                    and args['per_page'] == ['12'] and bool(re.fullmatch(COUNT, args['page'][0]))
                    and args['sort'] in (['latest_chapter'], ['sales'])
                    and args.get('dir', ['desc']) == ['desc'])
        return not query and bool(re.fullmatch(rf'/api/(?:series/{SEGMENT}(?:/chapters)?|chapters/{KEY}/pages)', path))
    if host == NUVIA:
        if path == '/api/comics':
            return ({'page', 'pageSize', 'sort'} <= set(args) <= {'page', 'pageSize', 'sort', 'q', 'genre'}
                    and args['pageSize'] == ['18'] and bool(re.fullmatch(COUNT, args['page'][0]))
                    and args['sort'] in (['popular'], ['newest']))
        return not query and bool(re.fullmatch(rf'/api/(?:genres|comics/{SEGMENT}|comic-chapters/{KEY}/content)', path))
    if path == '/api/v1/manga':
        return ({'offset', 'limit', 'sort'} <= set(args) <= {'offset', 'limit', 'sort', 'q', 'genres'}
                and args['limit'] == ['24'] and bool(re.fullmatch(r'\d{1,6}', args['offset'][0]))
                and args['sort'] in (['popular'], ['newest']))
    return not query and bool(re.fullmatch(rf'/api/v1/(?:manga/{SEGMENT}|chapters/{COUNT}|genres)', path))


def chapter_rows(rows, parent, source, *, date_key, number_key, locked):
    result = {}
    for item in rows:
        if not isinstance(item, dict) or locked(item):
            continue
        key = str(item.get('id', ''))
        n = number(item.get(number_key))
        if not re.fullmatch(KEY, key) or n is None:
            continue
        label = item.get('title')
        if not isinstance(label, str) or not label.strip() or label == f'{n:g}':
            label = f'Chapter {n:g}'
        route = parent + f'/chapter/{n:g}'
        if source.hostname == RENA:
            route = parent + f'/chapter-{n:g}'
        target = query_url(route, mv_id=key)
        result[target] = source.chapter(target, label, n, str(item.get(date_key) or '')[:10])
    return source.order(result)


def ordered_pages(rows, base, order, field):
    if any(not isinstance(row, dict) or type(row.get(order)) is not int for row in rows):
        raise SourceError('Источник предоставил неполный список страниц.')
    return [image_url(row.get(field), base) for row in sorted(rows, key=lambda row: row[order])]


class ScanlationSeries(JsonSeries):
    def title_for(self, url):
        return self.ROOT + self.section + self.chapter_key(url)

    def saved_title_url(self, value):
        if isinstance(value, str) and re.fullmatch(SEGMENT, value):
            return self.ROOT + self.section + value
        return super().saved_title_url(value)

    def record_fields(self, item, title, slug, cover, *, status='', aliases=(), description='', genres=()):
        target = self.ROOT + self.section + slug
        row = self.record(target, title, cover, genres=genres, tags=labels(item.get('tags')),
                          authors=[item.get('author')], aliases=aliases, description=description, status=status)
        row['artists'] = [item['artist']] if isinstance(item.get('artist'), str) and item['artist'] else []
        if item.get('type'):
            row['format'] = str(item['type']).lower()
        return row

    @staticmethod
    def name_slug(data):
        if not isinstance(data, dict) or not (slug := segment(data.get('slug'))) or not isinstance(name := data.get('title'), str) or not name.strip():
            raise SourceError('Источник не предоставил карточку тайтла.')
        return name, slug

    def chapter_id(self, url):
        key = param(url, 'mv_id')
        if not re.fullmatch(KEY, key):
            raise SourceError('Обнови список глав источника.')
        return key

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_chapter(url):
            return super().inspect(value, http)
        row, chapters = self.series(http, self.title_for(url))
        key, path = param(url, 'mv_id'), self.chapter_identity(url)
        matches = []
        for chapter in chapters:
            link = self.site_link(chapter['url'])
            if self.chapter_identity(link) == path and (not key or param(link, 'mv_id') == key):
                matches.append(link)
        if len(matches) != 1:
            raise SourceAccessError('Источник не предоставил однозначную открытую главу. Обнови оглавление.')
        pages = self.pages(http, matches[0])
        if not 1 <= len(pages) <= MAX_PAGES or not all(pages):
            raise SourceError('Источник не предоставил полный список изображений главы.')
        return self.reader_result(row, matches[0], chapters[:MAX_CHAPTERS], pages, len(chapters) > MAX_CHAPTERS)


class ParadiseScans(ScanlationSeries):
    section = '/series/'

    def __init__(self, identity):
        super().__init__(identity, SERIES, rf'/series/{SLUG}/chapter/{NUMBER}/?', interval=.35)

    def row_data(self, data):
        title, slug = self.name_slug(data)
        return self.record_fields(data, title, slug, image_url(data.get('cover_url'), self.ROOT),
                                  description=data.get('description') or '', genres=strings(data.get('genres')),
                                  status=str(data.get('status') or '').casefold())

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        options = {'page': page, 'per_page': 12, 'sort': 'latest_chapter' if sort == 'updated' else 'sales'}
        if sort != 'updated':
            options['dir'] = 'desc'
        if query:
            options['q'] = query
        if tag:
            options['genres'] = tag[:120]
        data = self.json(http, query_url(self.ROOT + '/api/series', **options))
        return [self.row_data(row) for row in items(data, 'data') if isinstance(row, dict)], (
            page < (number((data.get('meta') or {}).get('last_page')) or page))

    def details(self, http, url):
        slug = self.title_key(self.saved_title_url(url))
        if not slug:
            raise SourceError('Некорректная ссылка на тайтл.')
        data = self.json(http, self.ROOT + '/api/series/' + slug)
        if self.name_slug(data)[1] != slug:
            raise SourceError('Источник вернул другой тайтл.')
        return self.row_data(data)

    def series(self, http, url):
        row = self.details(http, url)
        slug = self.title_key(url)
        data = self.json(http, self.ROOT + f'/api/series/{slug}/chapters')
        if not isinstance(data, list):
            raise SourceError('Источник изменил формат оглавления.')
        locked = lambda entry: bool((number(entry.get('price')) or 0) > 0 or entry.get('is_premium')
                                    or entry.get('early_access') or entry.get('early_locked'))
        return row, chapter_rows(data, self.ROOT + self.section + slug, self, date_key='created_at',
                                 number_key='number', locked=locked)

    def pages(self, http, url):
        response = self.json(http, self.ROOT + '/api/chapters/' + self.chapter_id(url) + '/pages', url)
        if not isinstance(response, list):
            raise SourceError('Источник не предоставил страницы.')
        return ordered_pages(response, self.ROOT, 'page_number', 'image_url')


class Nuviatoon(ScanlationSeries):
    section = '/comics/'

    def __init__(self, identity):
        super().__init__(identity, rf'/comics/{SLUG}/?', rf'/comics/{SLUG}/chapter/{NUMBER}/?', interval=.35)

    def row_data(self, data):
        title, slug = self.name_slug(data)
        return self.record_fields(data, title, slug, image_url(data.get('coverUrl') or data.get('coverThumbUrl'), self.ROOT),
                                  description=data.get('description') or '', genres=labels(data.get('genres')),
                                  aliases=strings(data.get('altTitles')), status=str(data.get('seriesStatus') or '').casefold())

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'page': page, 'pageSize': 18, 'sort': 'newest' if sort == 'updated' else 'popular'}
        if query:
            args['q'] = query
        if tag:
            args['genre'] = tag[:120]
        data = self.json(http, query_url(self.ROOT + '/api/comics', **args))
        return [self.row_data(row) for row in items(data, 'data') if isinstance(row, dict)], (
            page < (number((data.get('meta') or {}).get('totalPages')) or page))

    def vocabulary(self, http):
        data = self.json(http, self.ROOT + '/api/genres')
        return [{'label': row['name'], 'sourceId': row['slug'], 'category': 'genre'} for row in items(data, 'data')
                if isinstance(row, dict) and segment(row.get('slug')) and isinstance(row.get('name'), str)]

    def source_details(self, http, url):
        slug = self.title_key(url)
        if not slug:
            raise SourceError('Некорректная ссылка на тайтл Nuviatoon.')
        data = self.json(http, self.ROOT + '/api/comics/' + slug)
        row = data.get('data') if isinstance(data, dict) else None
        if self.name_slug(row)[1] != slug:
            raise SourceError('Nuviatoon вернул другой тайтл.')
        return self.row_data(row), row, slug

    def details(self, http, url):
        return self.source_details(http, self.saved_title_url(url))[0]

    def series(self, http, url):
        row, data, slug = self.source_details(http, url)
        return row, chapter_rows(data.get('chapters') or (), self.ROOT + self.section + slug, self, date_key='publishedAt',
                                 number_key='number', locked=lambda chapter: (number(chapter.get('priceCoins')) or 0) > 0)

    def pages(self, http, url):
        key = self.chapter_id(url)
        reply = self.json(http, f'{self.ROOT}/api/comic-chapters/{key}/content', url)
        return ordered_pages(items(reply.get('data'), 'pages'), self.ROOT, 'index', 'url')


def rena_url(value):
    return image_url('/uploads/' + value if isinstance(value, str) and not value.startswith(('http', '/')) else value, RENA_ROOT)


def rena_pages(http, key, referer):
    data = document_json(http, RENA_ROOT + '/api/v1/chapters/' + key, referer)
    return [rena_url(row) for row in items(data, 'content')]


def rena_marker(value):
    parts = urlsplit(value)
    key = parts.fragment.removeprefix(RENA_MARK)
    if not re.fullmatch(COUNT, key) or not parts.path or not parts.hostname:
        raise SourceError('Некорректная ссылка на страницу Renascans.')
    return urlunsplit(parts._replace(fragment='')), key


def renew_rena(http, value):
    original, key = rena_marker(value)
    parts = urlsplit(original)

    def candidate(rows):
        return next((url for url in rows if (parsed := urlsplit(url)).hostname == parts.hostname
                     and parsed.path == parts.path and parsed.query != parts.query), '')

    with RENA_LOCK:
        item = RENA_CACHE.get(key)
        if item and item[0] > time() and (url := candidate(item[1])):
            return url
        pages = rena_pages(http, key, RENA_ROOT + '/')
        RENA_CACHE[key] = (time() + 45, pages)
        RENA_CACHE.move_to_end(key)
        while len(RENA_CACHE) > 48:
            RENA_CACHE.popitem(last=False)
    if not (url := candidate(pages)):
        raise SourceAccessError('Renascans не обновил ссылку страницы.')
    return url


class Renascans(ScanlationSeries):
    section = '/manga/'

    def __init__(self, identity):
        super().__init__(identity, rf'/(?:manga|series)/{SLUG}/?', rf'/manga/{SLUG}/chapter-{NUMBER}/?', interval=.35)

    def saved_title_url(self, value):
        if isinstance(value, str) and re.fullmatch(rf'{SEGMENT}#\d{{1,15}}', value):
            return self.ROOT + self.section + value.partition('#')[0]
        return super().saved_title_url(value)

    def row_data(self, data):
        title, slug = self.name_slug(data)
        cover = rena_url(data.get('cover'))
        if urlsplit(cover).hostname == 'images.weserv.nl' and (origin := param(cover, 'url')):
            cover = image_url(origin if origin.startswith('https://') else 'https://' + origin, self.ROOT)
        alt = str(data.get('alt_titles') or '')
        row = self.record_fields(data, title, slug, cover, genres=strings(data.get('genres')),
                                 aliases=re.split(r'\s*\|\s*|\n|\s+/\s+', alt),
                                 description=node_text(BeautifulSoup(str(data.get('description') or ''), 'html.parser')),
                                 status=str(data.get('status') or '').casefold())
        if type(data.get('release_year')) is int:
            row['year'] = data['release_year']
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        offset = (page - 1) * 24
        args = {'limit': 24, 'offset': offset, 'sort': 'newest' if sort == 'updated' else 'popular'}
        if query:
            args['q'] = query
        if tag:
            args['genres'] = tag[:120]
        endpoint = query_url(self.ROOT + '/api/v1/manga', **args)
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, headers = http.document(endpoint, headers={'Referer': self.ROOT + '/'}, action='native-series-json')
        if final != endpoint:
            raise SourceError('Renascans перенаправил запрос каталога.')
        try:
            data = json.loads(raw)
            if not isinstance(data, list):
                raise ValueError('Not a list')
            total = number(headers.get('X-Total-Count') or headers.get('x-total-count'))
        except (ValueError, RecursionError):
            raise SourceError('Renascans изменил формат каталога.') from None
        return [self.row_data(row) for row in data if isinstance(row, dict)], (
            offset + len(data) < total if total is not None else len(data) == 24)

    def vocabulary(self, http):
        data = self.json(http, self.ROOT + '/api/v1/genres')
        if not isinstance(data, list):
            raise SourceError('Renascans изменил формат справочника.')
        return [{'label': row['title'], 'sourceId': row['title'], 'category': 'genre'} for row in data
                if isinstance(row, dict) and isinstance(row.get('title'), str) and row['title'].strip()]

    def source_details(self, http, url):
        slug = self.title_key(url)
        if not slug:
            raise SourceError('Некорректная ссылка на тайтл Renascans.')
        data = self.json(http, self.ROOT + '/api/v1/manga/' + slug)
        if self.name_slug(data)[1] != slug:
            raise SourceError('Renascans вернул другой тайтл.')
        return self.row_data(data), data

    def details(self, http, url):
        return self.source_details(http, self.saved_title_url(url))[0]

    def series(self, http, url):
        row, raw = self.source_details(http, url)
        parent = self.ROOT + self.section + self.title_key(url)
        return row, chapter_rows(items(raw, 'chapters'), parent, self, date_key='created_at', number_key='chapter_number',
                                 locked=lambda chapter: chapter.get('is_locked') is True)

    def pages(self, http, url):
        key = self.chapter_id(url)
        if not re.fullmatch(COUNT, key):
            raise SourceError('Некорректный идентификатор главы Renascans.')
        pages = rena_pages(http, key, url)
        if not pages or not all(pages):
            raise SourceAccessError('Renascans не предоставил открытые страницы главы.')
        return [page + '#' + RENA_MARK + key for page in pages]
