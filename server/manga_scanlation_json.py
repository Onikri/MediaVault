"""Native INKRUSH and Team Shadowi catalogue and reader APIs."""

import re
from urllib.parse import parse_qs, urlsplit

from manga_direct_catalogues import SERIES, SLUG
from manga_direct_payloads import JsonSeries, items, segment, strings
from manga_madara import image_url
from manga_series_port import NUMBER, number
from manga_vinetheme import dictionaries, flight_models, flight_stream, resolve_fields
from manga_webcomics import query_url
from source_parser import SourceError


SHADOWI = 'www.team-shadowi.com'
INKRUSH = 'inkrush.site'
ID = r'[A-Za-z0-9_-]{1,120}'
PAGE = r'[1-9]\d{0,3}'
SHADOWI_GENRES = ('Action', 'Adventure', 'Comedy', 'Drama', 'Ecchi', 'Fantasy', 'Isekai', 'Romance')


def public_api(host, path, query):
    if host not in {INKRUSH, SHADOWI}:
        return False
    try:
        args = parse_qs(query, keep_blank_values=True, max_num_fields=12)
    except ValueError:
        return False
    if not all(len(v) == 1 and len(v[0]) <= 180 for v in args.values()):
        return False
    if host == INKRUSH and path == '/api/library':
        action = args.get('action')
        if action == ['catalog']:
            return (set(args) == {'action', 'q', 'language', 'category', 'page'} and args['language'] in (['en'], ['id'])
                    and args['category'] in (['popular'], ['latest'], ['trending']) and bool(re.fullmatch(PAGE, args['page'][0])))
        if action == ['detail']:
            return (set(args) == {'action', 'id', 'language', 'compact'} and args['language'] in (['en'], ['id'])
                    and args['compact'] == ['1'] and bool(re.fullmatch(ID, args['id'][0])))
        return action == ['pages'] and set(args) == {'action', 'id'} and bool(re.fullmatch(ID, args['id'][0]))
    if host != SHADOWI:
        return False
    if path == '/api/search':
        return set(args) == {'q'} and bool(args['q'][0])
    if path == '/api/series/popular':
        return (set(args) == {'timePeriod', 'genre', 'sortBy', 'offset', 'limit'} and args['timePeriod'] == ['all']
                and args['limit'] == ['20'] and args['sortBy'] in (['created'], ['rating'])
                and bool(re.fullmatch(r'[a-z0-9-]{1,60}', args['genre'][0]))
                and bool(re.fullmatch(r'\d{1,6}', args['offset'][0])))
    return False


def public_rsc(host, path, query):
    return host == SHADOWI and not query and bool(re.fullmatch(rf'{SERIES}|/read/{SLUG}/{NUMBER}/?', path))


class Inkrush(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/comics/({ID})/?', rf'/read/({ID})/({ID})/?', interval=.35)

    def canonical(self, value):
        url = super().canonical(value)
        parts = urlsplit(url)
        mark = parts.fragment
        if parts.path in ('/', ''):
            if match := re.fullmatch(rf'title/({ID})', mark):
                return f'{self.ROOT}/comics/{match[1]}'
            if match := re.fullmatch(rf'read/({ID})/({ID})', mark):
                return f'{self.ROOT}/read/{match[1]}/{match[2]}'
        return url

    def reader_url(self, url):
        from manga_source_urls import reader_url
        parts = urlsplit(url)
        if self.is_title(url):
            return reader_url(self.ROOT + '/#title/' + self.title_key(url), self.SOURCE_ID)
        if self.is_chapter(url):
            return reader_url(self.ROOT + '/#' + parts.path.strip('/'), self.SOURCE_ID)
        return super().reader_url(url)

    def saved_title_url(self, value):
        if isinstance(value, str) and re.fullmatch(ID, value):
            return self.ROOT + '/comics/' + value
        return super().saved_title_url(value)

    def saved_chapter(self, row, root, title):
        value = row.get('realUrl') or row.get('url') or ''
        if isinstance(value, str) and (match := re.fullmatch(rf'/?({ID})/({ID})', value)):
            return f'{self.ROOT}/read/{match[1]}/{match[2]}'
        return super().saved_chapter(row, root, title)

    def title_for(self, url):
        return self.ROOT + '/comics/' + self.chapter_key(url)

    def chapter_identity(self, url):
        return super().chapter_identity(self.canonical(url))

    def load(self, http, action, **options):
        return self.json(http, query_url(self.ROOT + '/api/library', action=action, **options))

    def record_data(self, row):
        key = row.get('id', '')
        title = row.get('title')
        if not isinstance(key, str) or not re.fullmatch(ID, key) or not isinstance(title, str) or not title.strip():
            raise SourceError('INKRUSH не предоставил карточку тайтла.')
        url = f'{self.ROOT}/comics/{key}'
        result = self.record(url, title, image_url(row.get('cover'), self.ROOT), aliases=strings(row.get('altTitles')),
                             description=row.get('description') or '', genres=strings(row.get('genre')),
                             tags=strings(row.get('themes')), authors=[row.get('author')],
                             status=str(row.get('status') or '').casefold())
        if row.get('format'):
            result['format'] = str(row['format']).casefold()
        return result

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        options = {'q': query, 'language': self.LANGUAGE, 'page': page,
                   'category': 'trending' if query else 'latest' if sort == 'updated' else 'popular'}
        data = self.load(http, 'catalog', **options)
        return [self.record_data(row) for row in items(data, 'comics') if isinstance(row, dict)], data.get('hasNextPage') is True

    def source_details(self, http, url):
        key = self.title_key(url)
        if not key:
            raise SourceError('Некорректная ссылка INKRUSH.')
        data = self.load(http, 'detail', id=key, language=self.LANGUAGE, compact=1)
        if not isinstance(data, dict) or data.get('id') != key:
            raise SourceError('INKRUSH вернул другой тайтл.')
        return self.record_data(data), data

    def details(self, http, url):
        return self.source_details(http, self.saved_title_url(url))[0]

    def series(self, http, url):
        row, data = self.source_details(http, url)
        key, chapters = self.title_key(url), {}
        for item in items(data, 'chapters'):
            if not isinstance(item, dict) or not isinstance(ch := item.get('id'), str) or not re.fullmatch(ID, ch):
                continue
            n = number(item.get('chapterNumber'))
            target = f'{self.ROOT}/read/{key}/{ch}'
            chapters[target] = self.chapter(target, item.get('name') or f'Chapter {n or 0:g}', n, str(item.get('releaseDate') or '')[:10])
        return row, self.order(chapters)

    def pages(self, http, url):
        key = self.CHAPTER_PATH.fullmatch(urlsplit(self.canonical(url)).path)[2]
        data = self.load(http, 'pages', id=key)
        return [image_url(row.get('src'), self.ROOT) if isinstance(row, dict) else '' for row in items(data, 'pages')]


class Shadowi(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, SERIES, rf'/read/{SLUG}/{NUMBER}/?', interval=.4)

    def title_for(self, url):
        return self.ROOT + '/series/' + self.chapter_key(url)

    def record_data(self, url, data):
        title = data.get('title')
        if not isinstance(title, str) or not title.strip():
            raise SourceError('Team Shadowi не предоставил карточку тайтла.')
        return self.record(url, title, image_url(data.get('thumbnail_url'), self.ROOT),
                           description=data.get('description') or '', genres=strings(data.get('genres')),
                           tags=strings(data.get('tags')), status=str(data.get('status') or '').casefold())

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query and page != 1:
            return [], False
        if query:
            url = query_url(self.ROOT + '/api/search', q=query)
        else:
            url = query_url(self.ROOT + '/api/series/popular', timePeriod='all', genre=tag or 'all',
                            sortBy='created' if sort == 'updated' else 'rating', offset=(page - 1) * 20, limit=20)
        data = self.json(http, url)
        rows = [self.record_data(f'{self.ROOT}/series/{slug}', item)
                for item in items(data, 'series' if query else 'data') if isinstance(item, dict)
                and (slug := segment(item.get('slug')))]
        return rows, not query and data.get('hasMore') is True

    def vocabulary(self, http):
        return [{'label': name, 'sourceId': name.casefold().replace(' ', '-'), 'category': 'genre'} for name in SHADOWI_GENRES]

    def unpack(self, http, url, keys):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, action='native-series-rsc', headers={'Referer': self.ROOT + '/'})
        if self.site_link(final).rstrip('/') != url.rstrip('/'):
            raise SourceError('Источник перенаправил запрос React Flight.')
        models = flight_models(flight_stream(raw))
        for model in models.values():
            for item in dictionaries(model):
                if keys <= item.keys():
                    return {key: resolve_fields(item[key], models, [50000]) for key in keys}
        raise SourceError('Team Shadowi изменил формат React Flight.')

    def series(self, http, url):
        result = self.unpack(http, url, {'series', 'chapters'})
        if not isinstance(result['series'], dict):
            raise SourceError('Team Shadowi не предоставил карточку тайтла.')
        row = self.record_data(url, result['series'])
        slug = self.title_key(url)
        chapters = {}
        for item in items(result, 'chapters'):
            if not isinstance(item, dict) or (n := number(item.get('number'))) is None:
                continue
            title = f'Chapter {n:g}'
            if item.get('title'):
                title += ': ' + str(item['title'])
            target = f'{self.ROOT}/read/{slug}/{n:g}'
            chapters[target] = self.chapter(target, title, n, str(item.get('created_at') or '')[:10])
        return row, self.order(chapters)

    def pages(self, http, url):
        reply = self.unpack(http, url, {'pages'})
        return [image_url(row, self.ROOT) for row in items(reply, 'pages')]
