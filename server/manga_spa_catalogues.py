"""Public SPA formats from the installed RawUwU, Rawdevartart and OriYami APKs."""

import re
from urllib.parse import parse_qs, quote, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries, items, segment, strings
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import NUMBER, number, picture
from manga_vinetheme import dictionaries, flight_models, flight_stream, resolve_fields
from manga_webcomics import query_url
from source_parser import SourceError


DIGITS = r'[1-9]\d{0,13}'
RAW_HOSTS = {'rawuwu.net', 'rawdevart.art'}
ORI_API = 'https://api.oriyami.com/api/mangas'
FORMATS = {'Manhwa': 'manhwa', 'Manhua': 'manhua', 'Digital Comic': 'digital-comic'}
ORI_PREFIX = r'(?:manga|manhwa|manhua|digital-comic)'


class RawSpas(JsonSeries):
    def __init__(self, identity):
        self.dev = urlsplit(identity[3]).hostname == 'rawdevart.art'
        self.slug_prefix = 'ne' if self.dev else ''
        self.series_prefix = '/g/' if self.dev else '/raw/'
        super().__init__(identity, rf'{self.series_prefix}{self.slug_prefix}({DIGITS})/?',
                         rf'/read/{self.slug_prefix}({DIGITS})/chapter-({NUMBER})/?', interval=.5)

    def title_for(self, url):
        return self.ROOT + self.series_prefix + self.slug_prefix + self.chapter_key(url)

    def title_url(self, key):
        return self.ROOT + self.series_prefix + self.slug_prefix + str(key)

    def saved_title_url(self, value):
        if isinstance(value, str) and re.fullmatch(DIGITS, value):
            return self.title_url(value)
        target = super().saved_title_url(value)
        return self.title_for(target) if self.is_chapter(target) else target

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        path = urlsplit(target).path
        match = re.fullmatch(rf'/spa/manga/({DIGITS})/({NUMBER})/?', path)
        return f'{self.ROOT}/read/{self.slug_prefix}{match[1]}/chapter-{match[2]}' if match else target

    def row_data(self, row, *, tags=(), authors=()):
        key, title = str(row.get('manga_id', '')), row.get('manga_name')
        if not re.fullmatch(DIGITS, key) or not isinstance(title, str) or not title.strip():
            raise SourceError('Источник не предоставил карточку тайтла.')
        cover = row.get('manga_cover_img_full') or row.get('manga_cover_img')
        aliases = re.split(r'[,\n]', str(row.get('manga_others_name') or ''))
        return self.record(self.title_url(key), title, image_url(cover, self.ROOT), aliases=aliases,
                           description=row.get('manga_description') or '', genres=tags, authors=authors,
                           status='completed' if row.get('manga_status') is True else 'ongoing' if 'manga_status' in row else '')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            target = query_url(self.ROOT + '/spa/search', page=page, query=query)
        elif self.dev and sort == 'updated' and not tag:
            target = query_url(self.ROOT + '/spa/latest-manga', page=page)
        else:
            if tag and not re.fullmatch(r'(?:ne)?' + DIGITS, tag):
                raise SourceError('Некорректный жанр каталога.')
            tag = ('ne' + tag.removeprefix('ne')) if self.dev and tag else tag
            filters = {'sort': 'most_viewed'} if sort != 'updated' else {}
            target = query_url(f'{self.ROOT}/spa/genre/{tag or "all"}', page=page, **filters)
        data = self.json(http, target)
        result = [self.row_data(row) for row in items(data, 'manga_list') if isinstance(row, dict)]
        button = (data.get('pagi') or {}).get('button') or {}
        return result, type(button.get('next')) is int and button['next'] > 0

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/genre/all')
        return [{'label': (row.get('title') or node_text(row)).title(), 'sourceId': row['id'], 'category': 'genre'}
                for row in doc.select('.genre-list a[id]') if re.fullmatch(DIGITS, row['id'])]

    def source_details(self, http, url):
        key = self.title_key(self.saved_title_url(url))
        if not key:
            raise SourceError('Некорректная ссылка на карточку источника.')
        data = self.json(http, self.ROOT + '/spa/manga/' + key)
        detail = data.get('detail') if isinstance(data, dict) else None
        if not isinstance(detail, dict) or str(detail.get('manga_id')) != key:
            raise SourceError('Источник вернул другой тайтл.')
        tags = [row.get('tag_name') for row in items(data, 'tags') if isinstance(row, dict)]
        authors = [row.get('author_name') for row in items(data, 'authors') if isinstance(row, dict)]
        return self.row_data(detail, tags=tags, authors=authors), key, data

    def details(self, http, url):
        return self.source_details(http, url)[0]

    def series(self, http, url):
        row, key, data = self.source_details(http, url)
        chapters = {}
        for item in items(data, 'chapters'):
            if not isinstance(item, dict) or (n := number(item.get('chapter_number'))) is None:
                continue
            chapter = f'{n:.4f}'.rstrip('0').rstrip('.')
            label = item.get('chapter_title')
            target = f'{self.ROOT}/read/{self.slug_prefix}{key}/chapter-{chapter}'
            chapters[target] = self.chapter(target, f'Chapter {chapter}: {label}' if label else f'Chapter {chapter}', n,
                                            str(item.get('chapter_date_published') or '')[:10])
        return row, self.order(chapters)

    def pages(self, http, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        data = self.json(http, f'{self.ROOT}/spa/manga/{match[1]}/{match[2]}', url)
        detail = data.get('chapter_detail') if isinstance(data, dict) else None
        if not isinstance(detail, dict) or not isinstance(detail.get('chapter_content'), str):
            raise SourceError('Источник изменил формат страниц.')
        if detail.get('chapter_number') is not None and number(detail['chapter_number']) != number(match[2]):
            raise SourceError('Источник вернул другую главу.')
        server = image_url(detail.get('server'), self.ROOT)
        doc = BeautifulSoup(detail['chapter_content'], 'html.parser')
        return [picture(node, server, ('data-src',)) for node in doc.select('img[data-src]')]


class OriYami(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/{ORI_PREFIX}/({SEGMENT})/?',
                         rf'/{ORI_PREFIX}/({SEGMENT})/([a-z][a-z-]{{0,19}})-({NUMBER})/?', interval=.35)

    def title_for(self, url):
        parts = urlsplit(url).path.strip('/').split('/')
        return f'{self.ROOT}/{parts[0]}/{parts[1]}' if len(parts) > 1 else ''

    def record_data(self, item):
        key = segment(item.get('slug'))
        title = item.get('title')
        if not key or not isinstance(title, str) or not title.strip():
            raise SourceError('Источник не предоставил карточку тайтла.')
        kind = FORMATS.get(item.get('type'), 'manga')
        target = f'{self.ROOT}/{kind}/{key}'
        row = self.record(target, title, image_url(item.get('cover_url'), target), aliases=strings(item.get('alternative_names')),
                          description=item.get('synopsis') or '', authors=strings(item.get('mangakas')),
                          genres=strings(item.get('genres')), tags=[item.get('demographic')],
                          status=str(item.get('status') or '').casefold())
        row['format'] = kind
        if type(item.get('release_year')) is int:
            row['year'] = item['release_year']
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        route = 'recently-updated' if sort == 'updated' else 'popular-list'
        options = {'page': page, 'page_size': 18}
        if query or tag:
            route = 'browse'
            if query:
                options['q'] = query
            if tag:
                options['genre'] = tag[:120]
        data = self.json(http, query_url(ORI_API + f'/{route}/', **options))
        return [self.record_data(row) for row in items(data, 'results') if isinstance(row, dict)], (
            data.get('has_next') is True or bool(data.get('next')))

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/library')
        models = flight_models(flight_stream(str(doc)))
        for entry in models.values():
            for row in dictionaries(entry):
                if 'initialMeta' not in row:
                    continue
                library = resolve_fields(row['initialMeta'], models, [50000])
                if isinstance(library, dict) and isinstance(library.get('genres'), list):
                    return [{'label': name, 'sourceId': name, 'category': 'genre'} for name in strings(library['genres'])]
        return []

    def source_details(self, http, url):
        slug = self.title_key(url)
        if not slug:
            raise SourceError('Некорректная ссылка на карточку OriYami.')
        data = self.json(http, ORI_API + '/' + slug + '/')
        if not isinstance(data, dict) or segment(data.get('slug')) != slug:
            raise SourceError('Источник вернул другой тайтл.')
        return self.record_data(data), data

    def details(self, http, url):
        return self.source_details(http, self.saved_title_url(url))[0]

    def series(self, http, url):
        row, data = self.source_details(http, url)
        title = self.site_link(row['sourceUrl'])
        chapters = {}
        for scan in items(data, 'scans'):
            if not isinstance(scan, dict) or (n := number(scan.get('number'))) is None:
                continue
            kind = str(scan.get('kind', 'Chapter'))
            label = kind + ' ' + str(scan['number'])
            target = f'{title}/{kind.lower()}-{scan["number"]}'
            if self.is_chapter(target):
                chapters[target] = self.chapter(target, label, n, str(scan.get('published_at') or scan.get('created_at') or '')[:10])
        return row, self.order(chapters)

    def pages(self, http, url):
        parts = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        data = self.json(http, f'{ORI_API}/{parts[1]}/chapters/{quote(parts[3], safe=".")}/', url)
        return [image_url(row.get('image_url'), self.ROOT) if isinstance(row, dict) else '' for row in items(data, 'pages')]


def public_api(host, path, query):
    if host in RAW_HOSTS:
        if re.fullmatch(rf'/spa/manga/{DIGITS}(?:/{NUMBER})?', path):
            return not query
        if not re.fullmatch(rf'/spa/(?:search|latest-manga|genre/(?:all|(?:ne)?{DIGITS}))', path):
            return False
        mode = path.split('/')[2]
        args = parse_qs(query)
        fields = {'page', 'query'} if mode == 'search' else {'page'}
        return (fields <= set(args) <= fields | ({'sort'} if mode == 'genre' else set())
                and len(args['page']) == 1 and bool(re.fullmatch(DIGITS, args['page'][0]))
                and ('query' not in args or len(args['query']) == 1 and 1 <= len(args['query'][0]) <= 160)
                and ('sort' not in args or args['sort'] == ['most_viewed']))
    if host != 'api.oriyami.com':
        return False
    if re.fullmatch(r'/api/mangas/(?:popular-list|recently-updated|browse)/', path):
        args = parse_qs(query)
        return (set(args) <= {'q', 'genre', 'page', 'page_size'} and args.get('page_size') == ['18']
                and len(args.get('page', [])) == 1 and bool(re.fullmatch(DIGITS, args['page'][0]))
                and all(len(value) == 1 and len(value[0]) <= 160 for value in args.values()))
    return not query and bool(re.fullmatch(rf'/api/mangas/{SEGMENT}/(?:chapters/{NUMBER}/)?', path))
