"""Public data routes for independent series catalogues."""

import base64
import binascii
import json
import re
from datetime import datetime, timezone
from html import unescape
from threading import Lock
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from manga_direct_catalogues import Browse, DirectCatalogue, Layout, SERIES, SLUG
from manga_direct_payloads import JsonSeries, items, segment, strings
from manga_madara import SEGMENT, image_url
from manga_series_port import Archive, Cards, Meta, number
from manga_vinetheme import dictionaries, flight_models, flight_stream, resolve_fields
from manga_webcomics import param, query_url
from source_parser import SourceError


ID = r'\d{1,12}'
BUILD = r'[A-Za-z0-9_-]{1,120}'
CDN = 'https://cdn.flamecomics.xyz/uploads/images/series'


def date_seconds(value):
    if type(value) not in {int, float}:
        return ''
    try:
        return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return ''


def rows_of(value, key):
    return [row for row in items(value, key) if isinstance(row, dict)]


class NexComic(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, SERIES, rf'/series/{SLUG}/chapter/{SEGMENT}/?', interval=.35)

    def title_for(self, url):
        return self.ROOT + '/series/' + self.chapter_key(url)

    def saved_title_url(self, url):
        value = self.canonical(url)
        path = urlsplit(value).path
        if match := re.fullmatch(rf'/(?:manga/)?{SLUG}/?', path):
            return f'{self.ROOT}/series/{match[1]}'
        return value

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        if match := re.fullmatch(rf'/{SLUG}/({SEGMENT})/?', urlsplit(value).path):
            return f'{self.ROOT}/series/{match[1]}/chapter/{match[2]}'
        return value

    def record_data(self, row):
        slug, title = segment(row.get('slug')), row.get('title')
        if not slug or not isinstance(title, str):
            raise SourceError('Источник вернул некорректную карточку тайтла.')
        url = f'{self.ROOT}/series/{slug}'
        avatar = row.get('avatar') or {}
        record = self.record(url, title, image_url(avatar.get('url'), url), aliases=strings(row.get('alternativeTitles')),
                             description=row.get('description') or '', authors=strings(row.get('authors')) + strings(row.get('artists')),
                             genres=strings(row.get('genres')), tags=strings(row.get('tags')), status=row.get('status') or '')
        if row.get('type') in {'manga', 'manhwa', 'manhua', 'webtoon', 'comic'}:
            record['format'] = row['type']
        return record

    def records(self, http):
        return rows_of(self.json(http, self.ROOT + '/api/local/series'), 'data')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        rows = self.records(http)
        if sort != 'updated' and not query:
            popular = rows_of(self.json(http, self.ROOT + '/api/local/popular?limit=100&period=all'), 'data')
            order = {row.get('slug'): n for n, row in enumerate(popular)}
            rows.sort(key=lambda row: order.get(row.get('slug'), len(order)))
        return [self.record_data(row) for row in rows
                if (not query or any(query in title.casefold() for title in [str(row.get('title') or ''), *strings(row.get('alternativeTitles'))]))
                and (not tag or tag in strings(row.get('genres')))], False

    def vocabulary(self, http):
        genres = {label for row in self.records(http) for label in strings(row.get('genres')) if label}
        return [{'label': name, 'sourceId': name, 'category': 'genre'} for name in sorted(genres)]

    def flight(self, http, url, keys):
        path = url.rstrip('/') + '.rsc'
        self.origin.wait(getattr(http, 'deadline', None))
        text, final, _ = http.document(path, headers={'Referer': url}, action='native-series-html-api')
        if path != final:
            raise SourceError('Читалка перенаправила запрос на другой маршрут.')
        models = flight_models(flight_stream(text))
        for model in models.values():
            for item in dictionaries(model):
                if keys <= item.keys():
                    found = resolve_fields(item, models, [100000])
                    if isinstance(found.get('pages', []), list):
                        return found
        raise SourceError('Источник изменил данные читалки.')

    def series(self, http, url):
        data = self.flight(http, url, {'series', 'chapters'})
        slug = self.title_key(url)
        item = next((row for row in rows_of(data, 'series') if row.get('slug') == slug), None)
        if item is None:
            raise SourceError('Источник не предоставил запрошенный тайтл.')
        chapters = {}
        for row in rows_of(data, 'chapters'):
            if row.get('seriesSlug') != slug or row.get('locked'):
                continue
            chapter, n = segment(str(row.get('id') or '').rsplit(':', 1)[-1]), number(row.get('chapterNumber'))
            if not chapter or n is None:
                continue
            target = f'{self.ROOT}/series/{slug}/chapter/{chapter}'
            label = f'Chapter {n:g}' + (' - ' + str(row['title']) if row.get('title') else '')
            timestamp = row.get('publishedAt')
            date = date_seconds(timestamp / 1000) if type(timestamp) in {int, float} else ''
            chapters[target] = self.chapter(target, label, n, date)
        return self.record_data(item), self.order(chapters)

    def pages(self, http, url):
        data = self.flight(http, url, {'chapterNumber', 'pages'})
        rows = sorted(rows_of(data, 'pages'), key=lambda item: number(item.get('pageNumber')) or 0)
        return [image_url(item.get('url'), url) for item in rows]


class FlameComics(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/series/({ID})/?', rf'/series/({ID})/{SEGMENT}/?', interval=1)
        self.build, self.build_lock = '', Lock()

    def title_for(self, url):
        return self.ROOT + '/series/' + self.chapter_key(url)

    def build_id(self, http, stale=None):
        with self.build_lock:
            if self.build and self.build != stale:
                return self.build
            doc, _ = self.document(http, self.ROOT + '/')
            script = doc.select_one('#__NEXT_DATA__')
            try:
                key = json.loads(script.string)['buildId']
            except (TypeError, ValueError, KeyError, AttributeError):
                key = ''
            if not isinstance(key, str) or not re.fullmatch(BUILD, key):
                raise SourceError('Источник не предоставил ID сборки каталога.')
            self.build = key
            return self.build

    def data(self, http, path, **params):
        build = self.build_id(http)
        root = f'{self.ROOT}/_next/data/'
        try:
            data = self.json(http, query_url(f'{root}{build}/{path}', **params))
        except SourceError as error:
            if str(error) != 'Источник вернул HTTP 404.':
                raise
            build = self.build_id(http, stale=build)
            data = self.json(http, query_url(f'{root}{build}/{path}', **params))
        props = data.get('pageProps') if isinstance(data, dict) else None
        if not isinstance(props, dict):
            raise SourceError('Источник изменил формат каталога.')
        return props

    def record_data(self, item):
        sid, title = str(item.get('series_id') or ''), item.get('title')
        if not re.fullmatch(ID, sid) or not isinstance(title, str) or not title:
            raise SourceError('Источник вернул некорректную карточку тайтла.')
        url = self.ROOT + '/series/' + sid
        cover = segment(item.get('cover'))
        version = str(item.get('last_edit') or '')
        cover_url = f'{CDN}/{sid}/{cover}?{version}' if cover and version.isdecimal() else f'{CDN}/{sid}/{cover}' if cover else ''
        desc = BeautifulSoup(str(item.get('description') or ''), 'html.parser').get_text(' ', strip=True)
        row = self.record(url, title, cover_url, aliases=strings(item.get('altTitles')), description=desc,
                          authors=strings(item.get('author')) + strings(item.get('artist')), tags=strings(item.get('tags')),
                          status=item.get('status') or '')
        kind = str(item.get('type') or '').casefold()
        if kind in {'manhua', 'manhwa', 'manga'}:
            row['format'] = kind
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        normalize = lambda value: re.sub(r'[^a-z0-9 ]', '', value.casefold())
        if page != 1:
            return [], False
        latest = sort == 'updated' and not query
        rows = rows_of(self.data(http, 'latest.json' if latest else 'browse.json'), 'allSeries' if latest else 'series')
        if sort == 'popular' and not query:
            rows.sort(key=lambda row: number(row.get('popularityRank')) or float('inf'))
        query = normalize(query)
        return [self.record_data(row) for row in rows if row.get('series_id') and
                query in normalize(str(row.get('title') or '')) and (not tag or tag in strings(row.get('tags')))], False

    def series(self, http, url):
        sid = self.title_key(url)
        page = self.data(http, f'series/{sid}.json', id=sid)
        row = page.get('series')
        if not isinstance(row, dict) or str(row.get('series_id')) != sid:
            raise SourceError('Источник вернул другой тайтл.')
        chapters = {}
        for item in rows_of(page, 'chapters'):
            token, n = segment(item.get('token')), number(item.get('chapter'))
            if not token or n is None or str(item.get('series_id')) != sid:
                continue
            target = url.rstrip('/') + '/' + token
            label = f'Chapter {n:g}' + (' - ' + str(item['title']) if item.get('title') else '')
            chapters[target] = self.chapter(target, label, n, date_seconds(item.get('release_date')))
        return self.record_data(row), self.order(chapters)

    def pages(self, http, url):
        sid, token = urlsplit(url).path.strip('/').split('/')[-2:]
        data = self.data(http, f'series/{sid}/{token}.json', id=sid, token=token).get('chapter')
        if not isinstance(data, dict) or str(data.get('series_id')) != sid or segment(data.get('token')) != token:
            raise SourceError('Источник вернул другую главу.')
        files = data.get('images')
        version = str(data.get('release_date') or '')
        return [f'{CDN}/{sid}/{token}/{path}?{version}' if version.isdecimal() else f'{CDN}/{sid}/{token}/{path}'
                for item in files.values() if isinstance(item, dict) and (path := segment(item.get('name')))] if isinstance(files, dict) else []


class Milftoon(JsonSeries):
    def __init__(self, identity):
        path = rf'/comics/{SLUG}/?'
        super().__init__(identity, path, path, interval=.35)

    def is_chapter(self, url):
        return super().is_chapter(url) and param(url, 'mv_chapter') == '1'

    def title_for(self, url):
        return self.ROOT + '/comics/' + self.chapter_key(url)

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        return query_url(value, mv_chapter=1) if self.is_title(value) else ''

    def route(self, http, url):
        doc, final = self.document(http, url)
        for script in doc.select('script'):
            if match := re.search(r'window\.__INITIAL_ROUTE_DATA__\s*=\s*(?=\{)', script.string or ''):
                try:
                    parsed = json.JSONDecoder().raw_decode(script.string, match.end())[0]['data']
                except (ValueError, TypeError, KeyError, RecursionError):
                    break
                if isinstance(parsed, dict):
                    return parsed, doc, final
        raise SourceError('Источник не предоставил данные маршрута.')

    def record_data(self, row, description=''):
        key = segment(row.get('slug'))
        title = row.get('title')
        if not key or not isinstance(title, str):
            raise SourceError('Источник не предоставил карточку тайтла.')
        return self.record(self.ROOT + '/comics/' + key, title, image_url(row.get('coverPath'), 'https://fdc1.azhentai.com/'),
                           description=description, authors=[row['author']] if isinstance(row.get('author'), str) else [])

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        path = '/search_result' if query else '/manga_list/all' if sort == 'updated' else '/ranking/hottest'
        url = query_url(self.ROOT + path, page=page, **({'q': query} if query else {}))
        data, _, _ = self.route(http, url)
        return [self.record_data(row) for row in rows_of(data, 'items')], page * (number(data.get('pageSize')) or 24) < (
            number(data.get('total')) or 0)

    def series(self, http, url):
        data, doc, final = self.route(http, url)
        row = data.get('comic')
        if not isinstance(row, dict) or segment(row.get('slug')) != self.title_key(url) or self.title_key(final) != self.title_key(url):
            raise SourceError('Источник вернул другой тайтл.')
        desc = doc.select_one('meta[name=description][content]')
        chapter = data.get('chapter')
        chapters = [self.chapter(query_url(url, mv_chapter=1), chapter.get('name') or 'Глава', 1,
                                 str(chapter.get('publishedAt') or '')[:10])] if isinstance(chapter, dict) else []
        return self.record_data(row, desc['content'] if desc else ''), chapters

    def pages(self, http, url):
        data, _, final = self.route(http, self.title_for(url))
        return [image_url(item.get('src'), final) for item in rows_of(data, 'pages')]


def post_json(adapter, http, url, data):
    adapter.origin.wait(getattr(http, 'deadline', None))
    raw, final, _ = http.document(url, method='POST', action='native-series-data-form',
                                   headers={'Referer': adapter.ROOT + '/'}, data=data)
    if url != final:
        raise SourceError('Источник перенаправил запрос данных.')
    try:
        result = json.loads(raw)
    except ValueError:
        raise SourceError('Источник изменил формат ответа.') from None
    if not isinstance(result, dict):
        raise SourceError('Источник вернул некорректные данные каталога.')
    return result


class MangaYi(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/read/{SLUG}/?', rf'/read/{SLUG}/{SEGMENT}/?', Cards('', ''),
            Meta('h1.m-title', '.cover-wrap img.cover-image', '.m-summary p', genres='.m-genres .pill',
                 author='.m-authors', status='.m-stat:-soup-contains("Status") .value'),
            Archive('div.chapters-list a.c:not(.unreleased)', anchor='', title='.t', date='.chapter-d'),
            'div.c-images img', Browse('/api/search'), title_path='/read/', suffix='/',
        ))
        self.page_size = 1

    def saved_title_url(self, url):
        value = self.canonical(url)
        slug = urlsplit(value).path.strip('/')
        return f'{self.ROOT}/read/{slug}/' if re.fullmatch(SEGMENT, slug) else value

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        payload = json.dumps({'p': page, **({'s': query} if query else {'t': 1})}).encode()
        data = post_json(self, http, self.ROOT + '/api/search', payload)
        rows = {}
        for item in rows_of(data, 'results'):
            slug, title = segment(item.get('i')), item.get('t')
            if slug and isinstance(title, str):
                target = f'{self.ROOT}/read/{slug}/'
                rows[slug] = self.record(target, title, f'https://scp.keterfoundation.com/cover/{slug}.jpg')
        self.page_size = max(self.page_size, len(rows))
        return list(rows.values()), bool(rows and page * self.page_size < (number(data.get('total')) or 0))


class MLBBLore(JsonSeries):
    API = 'https://api.mobilelegends.com/lore/album'

    def __init__(self, identity):
        path = rf'/lore/album/({ID})/?'
        super().__init__(identity, path, path, interval=.5)

    def is_chapter(self, url):
        return super().is_chapter(url) and param(url, 'mv_chapter') == '1'

    def title_for(self, url):
        return self.ROOT + '/lore/album/' + self.chapter_key(url)

    def saved_title_url(self, url):
        value = self.canonical(url)
        key = urlsplit(value).path.strip('/')
        return self.ROOT + '/lore/album/' + key if re.fullmatch(ID, key) else value

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        target = self.saved_title_url(value)
        return query_url(target, mv_chapter=1) if self.is_title(target) and self.title_key(target) == self.title_key(title) else ''

    def record_item(self, row):
        key = str(row.get('id') or '')
        title = row.get('title')
        if not re.fullmatch(ID, key) or not isinstance(title, str) or not title:
            raise SourceError('Источник не предоставил карточку комикса.')
        url = self.ROOT + '/lore/album/' + key
        return self.record(url, title, image_url(row.get('thumb'), self.ROOT), description=row.get('share_content') or '',
                           authors=[row['hero_name']] if isinstance(row.get('hero_name'), str) else [], status='completed')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        data = post_json(self, http, self.API + '/list',
                         {'type': '3', 'sort': '1' if sort == 'updated' else '3', 'page': str(page), 'page_size': '5',
                          'lang': 'en', 'token': ''})
        rows = rows_of(data, 'data')
        return [self.record_item(row) for row in rows if row.get('type') == 3 and query in str(row.get('title') or '').casefold()], len(rows) >= 5

    def item(self, http, url):
        key = self.title_key(url)
        data = post_json(self, http, self.API + '/detail', {'id': key, 'lang': 'en', 'token': ''}).get('data')
        if not isinstance(data, dict) or str(data.get('id')) != key:
            raise SourceError('Источник вернул другой комикс.')
        return data

    def series(self, http, url):
        row = self.item(http, url)
        return self.record_item(row), [self.chapter(query_url(url, mv_chapter=1), 'Глава', 1)]

    def pages(self, http, url):
        return [image_url(page, self.ROOT) for page in items(self.item(http, url), 'comic_content')]


def labels(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return strings(value)


class MangaUno(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/m/{SLUG}/?', rf'/r/{SLUG}/({ID})/?', interval=.35)

    def title_for(self, url):
        return self.ROOT + '/m/' + self.chapter_key(url)

    def saved_title_url(self, url):
        value = self.canonical(url)
        slug = urlsplit(value).path.strip('/')
        return self.ROOT + '/m/' + slug if re.fullmatch(SEGMENT, slug) else value

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        if match := re.fullmatch(rf'/{SLUG}/({ID})/?', urlsplit(value).path):
            return f'{self.ROOT}/r/{match[1]}/{match[2]}'
        return value

    def data(self, http, path, **args):
        return self.json(http, query_url(self.ROOT + '/api' + path, **args))

    def record_manga(self, row):
        slug = segment(row.get('slug'))
        title = row.get('english_title') or row.get('title')
        if not slug or not isinstance(title, str) or not title:
            raise SourceError('Источник не предоставил карточку тайтла.')
        url = self.ROOT + '/m/' + slug
        aliases = [item for item in (row.get('title'), row.get('japanese_title')) if isinstance(item, str)]
        authors = [item for item in (row.get('author'), row.get('artist')) if isinstance(item, str)]
        record = self.record(url, title, image_url(row.get('cover'), 'https://xz7.fstr-cdn.com/'), aliases=aliases,
                             description=row.get('synopsis') or '', genres=labels(row.get('genres')), tags=labels(row.get('tags')),
                             authors=authors, status=row.get('status') or '')
        if row.get('type') in {'manga', 'manhwa', 'manhua', 'webtoon'}:
            record['format'] = row['type']
        return record

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        path, args = ('/list/latest' if sort == 'updated' else '/list/popular'), {'page': page, 'limit': 24}
        if query or tag:
            path = '/search/advanced'
            if query:
                args['title'] = query
            if tag:
                kind, _, label = tag.partition(':')
                if kind not in {'genres', 'tags'} or not label:
                    raise SourceError('Некорректная метка каталога.')
                args[kind] = label[:120]
        rows = rows_of(self.data(http, path, **args), 'data')
        return [self.record_manga(row) for row in rows], len(rows) >= 24

    def vocabulary(self, http):
        data = self.data(http, '/search/facets')
        return [{'label': row['name'], 'sourceId': f'{kind}:{row["name"]}', 'category': category}
                for kind, category in (('genres', 'genre'), ('tags', 'tag'))
                for row in rows_of(data, kind) if isinstance(row.get('name'), str) and row['name']]

    def series(self, http, url):
        slug = self.title_key(url)
        data = self.data(http, '/manga/' + slug)
        manga = data.get('manga')
        if not isinstance(manga, dict) or segment(manga.get('slug')) != slug:
            raise SourceError('Источник вернул другой тайтл.')
        rows = {}
        for row in rows_of(data, 'chapters'):
            key = str(row.get('id') or '')
            if not re.fullmatch(ID, key):
                continue
            target = f'{self.ROOT}/r/{slug}/{key}'
            n, vol = number(row.get('chapter_number')), row.get('volume')
            title = (f'Ch. {n:g} ' if n is not None else '') + unescape(str(row.get('title') or '')).strip()
            rows[target] = self.chapter(target, title.strip(), n, str(row.get('published_at') or '')[:10],
                                         vol if type(vol) is int and vol > 0 else 1,
                                         str(row.get('source_group_name') or row.get('source') or ''))
        return self.record_manga(manga), self.order(rows)

    def pages(self, http, url):
        key = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]
        data = self.json(http, self.ROOT + '/api/chapter/' + key, url)
        chapter = data.get('chapter') if isinstance(data, dict) else None
        count = chapter.get('page_count') if isinstance(chapter, dict) else None
        if type(count) is not int or not 1 <= count <= 1500:
            return []
        return [f'{self.ROOT}/api/chapter/{key}/page/{i}' for i in range(1, count + 1)]


class MangaMelon(JsonSeries):
    API = 'https://api.mangamelon.com'

    def __init__(self, identity):
        super().__init__(identity, rf'/manga/{SLUG}/?', rf'/chapter/{SLUG}/{SEGMENT}/?', interval=.35)

    def title_for(self, url):
        return self.ROOT + '/manga/' + self.chapter_key(url)

    def call(self, http, path, data):
        body = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
        return post_json(self, http, self.API + '/api/' + path, {'data': body, 'sessionid': ''})

    def record_item(self, row):
        key, title = segment(row.get('id')), row.get('title')
        if not key or not isinstance(title, str):
            raise SourceError('Источник изменил формат карточки тайтла.')
        target = self.ROOT + '/manga/' + key
        return self.record(target, title, image_url(row.get('cover'), self.ROOT), description=row.get('desc') or '',
                           genres=strings(row.get('genres')), authors=[row['authors']] if isinstance(row.get('authors'), str) else [],
                           status=row.get('status') or '')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        ordering = 'latest' if query or sort == 'updated' else 'popular'
        offset = (page - 1) * 36
        data = self.call(http, 'manga/list', {'search': query, 'genre': tag[:120], 'lang': 'en',
                                            'sort': ordering, 'includeNsfw': True, 'limit': 36, 'skip': offset})
        rows = rows_of(data, 'list')
        total = number(data.get('total')) or 0
        return [self.record_item(row) for row in rows], (offset + len(rows) < total if total else len(rows) >= 36)

    def saved_title_url(self, url):
        value = self.canonical(url)
        key = urlsplit(value).path.strip('/')
        return self.ROOT + '/manga/' + key if re.fullmatch(SEGMENT, key) else value

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        key = urlsplit(value).path.strip('/')
        return f'{self.ROOT}/chapter/{self.title_key(title)}/{key}' if re.fullmatch(SEGMENT, key) else value

    def series(self, http, url):
        key = self.title_key(url)
        row = self.call(http, 'manga/get', {'target': key, 'withReviews': False}).get('manga')
        if not isinstance(row, dict) or segment(row.get('id')) != key:
            raise SourceError('Источник вернул другой тайтл.')
        rows = {}
        for offset in range(0, 10000, 1000):
            data = self.call(http, 'chapter/list', {'target': key, 'status': 0, 'limit': 1000,
                                                  'skip': offset, 'pending': '', 'force': True})
            chapters = rows_of(data, 'chapters')
            for item in chapters:
                chapter = segment(item.get('id'))
                if not chapter:
                    continue
                target = f'{self.ROOT}/chapter/{key}/{chapter}'
                stamp = str(item.get('updated') or '')[:10]
                rows[target] = self.chapter(target, item.get('title') or '', number(item.get('seq')),
                                             stamp if not stamp.startswith('0001-') else '')
            if len(chapters) < 1000:
                break
        return self.record_item(row), self.order(rows)

    def pages(self, http, url):
        chapter = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]
        data = self.call(http, 'chapter/get', {'target': chapter, 'all': True}).get('chapter')
        if not isinstance(data, dict) or segment(data.get('id')) != chapter:
            raise SourceError('Источник вернул другую главу.')
        return [image_url(row.get('url'), url) for row in sorted(rows_of(data, 'pages'), key=lambda item: number(item.get('seq')) or 0)]


def melon_form(url, form):
    if not isinstance(form, dict) or set(form) != {'data', 'sessionid'} or form['sessionid'] != '':
        return False
    if not isinstance(form['data'], str) or len(form['data']) > 2200:
        return False
    try:
        data = json.loads(base64.b64decode(form['data'], validate=True))
    except (ValueError, binascii.Error):
        return False
    if not isinstance(data, dict):
        return False
    if url == MangaMelon.API + '/api/manga/list':
        return (set(data) == {'search', 'genre', 'lang', 'sort', 'includeNsfw', 'limit', 'skip'} and
                all(isinstance(data[field], str) and len(data[field]) <= 160 for field in ('search', 'genre')) and
                data['lang'] == 'en' and data['sort'] in ('popular', 'latest') and data['includeNsfw'] is True and
                data['limit'] == 36 and type(data['skip']) is int and 0 <= data['skip'] <= 72000)
    if not segment(data.get('target')):
        return False
    if url == MangaMelon.API + '/api/manga/get':
        return set(data) == {'target', 'withReviews'} and data['withReviews'] is False
    if url == MangaMelon.API + '/api/chapter/get':
        return set(data) == {'target', 'all'} and data['all'] is True
    return (url == MangaMelon.API + '/api/chapter/list' and
            set(data) == {'target', 'status', 'limit', 'skip', 'pending', 'force'} and data['status'] == 0 and
            data['limit'] == 1000 and type(data['skip']) is int and 0 <= data['skip'] <= 10000 and
            data['pending'] == '' and data['force'] is True)


class Komix(JsonSeries):
    CHAPTER = r'\d{1,9}(?:\.\d{1,4})?'

    def __init__(self, identity):
        super().__init__(identity, rf'/title/{SLUG}/?', rf'/title/{SLUG}/chapter/{self.CHAPTER}/?', interval=.35)

    def title_for(self, url):
        return self.ROOT + '/title/' + self.chapter_key(url)

    def saved_title_url(self, url):
        value = self.canonical(url)
        slug = urlsplit(value).path.strip('/')
        return self.ROOT + '/title/' + slug if re.fullmatch(SEGMENT, slug) else value

    def chapter_identity(self, url):
        return super().chapter_identity(url), param(url, 'group')

    def record_manga(self, data, description=''):
        slug, title = segment(data.get('slug')), data.get('title')
        if not slug or not isinstance(title, str) or not title.strip():
            raise SourceError('Источник вернул некорректную карточку тайтла.')
        url = self.ROOT + '/title/' + slug
        genres = [item.get('name') for item in data.get('genres') or [] if isinstance(item, dict)]
        authors = [item for item in (data.get('author'), data.get('artist')) if isinstance(item, str)]
        row = self.record(url, title.strip(), image_url(data.get('cover_image'), url), description=description,
                          authors=authors, genres=genres, aliases=strings(data.get('alternative_titles')),
                          status=data.get('status') or '')
        if data.get('type') in {'manga', 'manhwa', 'manhua', 'webtoon'}:
            row['format'] = data['type']
        return row

    def browse(self, http, **args):
        return self.json(http, query_url(self.ROOT + '/api/page-data/browse', **args))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'page': page} if page > 1 else {}
        if sort == 'updated':
            args['sort'] = 'date'
        if query:
            args['q'] = query
        if tag:
            if not segment(tag):
                raise SourceError('Некорректный жанр каталога.')
            args['genre'] = tag
        data = self.browse(http, **args)
        return [self.record_manga(row) for row in rows_of(data, 'results')], page * 60 < (number(data.get('totalCount')) or 0)

    def vocabulary(self, http):
        return [{'label': row['name'], 'sourceId': row['slug'], 'category': 'genre'}
                for row in rows_of(self.browse(http), 'allGenres') if segment(row.get('slug')) and isinstance(row.get('name'), str)]

    def series(self, http, url):
        slug = self.title_key(url)
        data = self.json(http, self.ROOT + '/api/page-data/title/' + slug, url)
        item = data.get('manga')
        if not isinstance(item, dict) or segment(item.get('slug')) != slug:
            raise SourceError('Источник вернул другой тайтл.')
        desc = ''
        if isinstance(data.get('jsonLd'), str):
            try:
                graph = json.loads(data['jsonLd']).get('@graph', [])
                desc = next((node['description'] for node in graph if isinstance(node, dict) and node.get('@type') == 'Book'
                             and isinstance(node.get('description'), str)), '')
            except (ValueError, AttributeError, TypeError):
                pass
        rows = {}
        for row in rows_of(data, 'chapters'):
            n = number(row.get('chapter_number'))
            if n is None:
                continue
            chapter = f'{n:.4f}'.rstrip('0').rstrip('.')
            target = f'{self.ROOT}/title/{slug}/chapter/{chapter}'
            team = row.get('group') if isinstance(row.get('group'), str) else ''
            if team:
                target = query_url(target, group=team)
            label = row.get('title') or f'Chapter {chapter}'
            rows[target] = self.chapter(target, label, n, str(row.get('release_date') or row.get('created_at') or '')[:10],
                                        translator='' if team == '(none)' else team)
        return self.record_manga(item, desc), self.order(rows)

    def pages(self, http, url):
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'})
        if self.chapter_identity(final) != self.chapter_identity(url):
            raise SourceError('Читалка перенаправила запрос на другой выпуск.')
        models = flight_models(flight_stream(raw))
        for model in models.values():
            for item in dictionaries(model):
                if not {'chapter', 'manga'} <= item.keys() or not isinstance(item['chapter'], dict):
                    continue
                chapter = resolve_fields(item['chapter'], models, [50000])
                if not isinstance(chapter.get('pages'), list):
                    continue
                return [query_url(self.ROOT + '/api/images', t=row['enc']) for row in rows_of(chapter, 'pages')
                        if isinstance(row.get('enc'), str) and 1 <= len(row['enc']) <= 800]
        return []


def public_form(url, data):
    if url.startswith(MangaMelon.API + '/api/'):
        return melon_form(url, data)
    if url == 'https://mangayi.com/api/search':
        if not isinstance(data, bytes) or len(data) > 2048:
            return False
        try:
            args = json.loads(data)
        except ValueError:
            return False
        return (isinstance(args, dict) and type(args.get('p')) is int and 1 <= args['p'] <= 2000 and
                (set(args) == {'p', 't'} and args['t'] == 1 or
                 set(args) == {'p', 's'} and isinstance(args['s'], str) and 1 <= len(args['s']) <= 160))
    if not isinstance(data, dict) or data.get('lang') != 'en' or data.get('token') != '':
        return False
    if url == MLBBLore.API + '/list':
        return (set(data) == {'type', 'sort', 'page', 'page_size', 'lang', 'token'} and data['type'] == '3' and
                data['page_size'] == '5' and data['sort'] in {'1', '3'} and
                isinstance(data['page'], str) and bool(re.fullmatch(r'[1-9]\d{0,3}', data['page'])))
    return (url == MLBBLore.API + '/detail' and set(data) == {'id', 'lang', 'token'} and
            isinstance(data['id'], str) and bool(re.fullmatch(ID, data['id'])))


def public_api(host, path, query):
    if host == 'komix.to':
        args = parse_qs(query)
        if path == '/api/images':
            return set(args) == {'t'} and len(args['t']) == 1 and 1 <= len(args['t'][0]) <= 800
        if path == '/api/page-data/browse':
            return (set(args) <= {'page', 'q', 'sort', 'genre'} and args.get('sort') in (None, ['date']) and
                    all(len(values) == 1 and len(values[0]) <= 160 for values in args.values()))
        return not query and bool(re.fullmatch(rf'/api/page-data/title/{SEGMENT}', path))
    if host == 'api.mangamelon.com':
        return not query and path in {'/api/manga/list', '/api/manga/get', '/api/chapter/list', '/api/chapter/get'}
    if host == 'manga.uno':
        if path in {'/api/list/popular', '/api/list/latest', '/api/search/advanced'}:
            args = parse_qs(query)
            return (set(args) <= {'page', 'limit', 'title', 'genres', 'tags'} and args.get('limit') == ['24'] and
                    len(args.get('page', [])) == 1 and bool(re.fullmatch(r'[1-9]\d{0,3}', args['page'][0])) and
                    all(len(values) == 1 and len(values[0]) <= 160 for values in args.values()))
        return not query and bool(re.fullmatch(rf'/api/(?:search/facets|manga/{SEGMENT}|chapter/{ID}(?:/page/[1-9]\d{{0,3}})?)', path))
    if host == 'api.mobilelegends.com':
        return not query and path in {'/lore/album/list', '/lore/album/detail'}
    if host == 'mangayi.com':
        return not query and path == '/api/search'
    if host == 'nexcomic.com':
        if path == '/api/local/popular':
            return query == 'limit=100&period=all'
        return not query and bool(re.fullmatch(rf'/api/local/series|/series/{SEGMENT}(?:/chapter/{SEGMENT})?\.rsc', path))
    if host != 'flamecomics.xyz':
        return False
    match = re.fullmatch(rf'/_next/data/{BUILD}/(?:(?:latest|browse)|series/({ID})(?:/({SEGMENT}))?)\.json', path)
    if not match:
        return False
    params = {'id': [match[1]]} if match[1] else {}
    if match[2]:
        params['token'] = [match[2]]
    return parse_qs(query, keep_blank_values=True) == params
