"""Public ScansGG and StoneScape JSON catalogues, chapters and page manifests."""

import re
from urllib.parse import parse_qs, quote, urlsplit

from manga_direct_catalogues import SERIES, SLUG
from manga_direct_payloads import JsonSeries, items, segment, strings
from manga_madara import SEGMENT, image_url
from manga_series_port import NUMBER, number
from manga_webcomics import param, query_url
from source_parser import SourceError


SCANS = 'api.scans.gg'
STONE = 'stonescape.xyz'
NUM = r'[1-9]\d{0,14}'
KEY = r'[A-Za-z0-9_-]{1,120}'
WORDS = ('Fantasy', 'Romance', 'Shoujo', 'Comedy', 'Drama', 'Slice Of Life', 'School Life', 'Thriller', 'Josei',
         'Action', 'Seinen', 'Historical', 'Shounen', 'Sports', 'Supernatural', 'Adventure', 'Sci-fi',
         'Martial Arts', 'Mystery', 'Horror', 'Mature', 'Psychological', 'Suspense', 'Gender Bender', 'Tragedy',
         'Harem', 'Boys Love', 'Shounen Ai', 'Yaoi', 'Shoujo Ai', 'Yuri', 'Gourmet', 'Adult', 'Erotica', 'Smut',
         'Music', 'Ecchi', 'Shotacon', 'Mecha', 'Hentai', 'Girls Love', 'Doujinshi', 'Mahou Shoujo', 'Lolicon',
         'Award Winning', 'Avant Garde', 'Survival', 'Male Protagonist', 'Regression')
SCAN_TERMS = dict(enumerate(WORDS, 1))


def public_api(host, path, query):
    if host not in {SCANS, STONE}:
        return False
    args = parse_qs(query)
    if not all(len(v) == 1 and 1 <= len(v[0]) <= 160 for v in args.values()):
        return False
    if host == SCANS:
        if path == '/series':
            if set(args) == {'id', 'trackers', 'sources'}:
                return args['trackers'] == args['sources'] == ['true'] and bool(re.fullmatch(NUM, args['id'][0]))
            return ({'limit', 'offset'} <= set(args) <= {'limit', 'offset', 'q', 'q_type', 'q_status', 'q_tags'}
                    and args['limit'] == ['21'] and bool(re.fullmatch(r'\d{1,6}', args['offset'][0]))
                    and args.get('q_type', ['[]']) == args.get('q_status', ['[]']) == ['[]']
                    and bool(re.fullmatch(r'\[(?:[1-9]\d?)?\]', args.get('q_tags', ['[]'])[0])))
        if path == '/chapters':
            if set(args) == {'page', 'limit', 'chapters', 'series_details', 'group_details', 'sort'}:
                return (args['limit'] == ['14'] and args['chapters'] == args['series_details'] == args['group_details'] == ['true']
                        and args['sort'] == ['date'] and bool(re.fullmatch(NUM, args['page'][0])))
            return (set(args) == {'series_id', 'limit', 'page', 'group_details'} and args['limit'] == ['100']
                    and args['group_details'] == ['true'] and all(re.fullmatch(NUM, args[k][0]) for k in ('series_id', 'page')))
        return (path == '/chapter-navigation' and set(args) == {'series_id', 'chapter_id', 'group_id'}
                and all(re.fullmatch(r'\d{1,15}', v[0]) for v in args.values()))
    if path in {'/api/series', '/api/series/popular'}:
        return ({'page', 'limit', 'contentType'} <= set(args) <= {'page', 'limit', 'contentType', 'period', 'genres', 'search'}
                and args['limit'] == ['24'] and args['contentType'] == ['manhwa']
                and bool(re.fullmatch(NUM, args['page'][0]))
                and (args.get('period') == ['week'] if path.endswith('popular') else 'period' not in args))
    return not query and bool(re.fullmatch(rf'/api/(?:series/by-slug/{SEGMENT}(?:/chapters)?|chapters/{KEY}/pages)', path))


class ScansGG(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/series/({NUM})/?', rf'/series/({NUM})/chapter-({NUM})/?', interval=.35)

    def title_for(self, url):
        return self.ROOT + '/series/' + self.chapter_key(url)

    def endpoint(self, http, path, **filters):
        return self.json(http, query_url(f'https://{SCANS}{path}', **filters))

    def row_data(self, item):
        key = str(item.get('id', ''))
        title = item.get('title')
        if not re.fullmatch(NUM, key) or not isinstance(title, str) or not title.strip():
            raise SourceError('ScansGG не предоставил карточку тайтла.')
        target = f'{self.ROOT}/series/{key}'
        cover = image_url(item.get('cover'), 'https://cdn.scans.gg/uploads/covers/')
        labels = [SCAN_TERMS[tag] for tag in (item.get('tags') or []) if type(tag) is int and tag in SCAN_TERMS]
        row = self.record(target, title, cover, description=item.get('summary') or '',
                          authors=strings(item.get('author')), tags=labels,
                          status={1: 'ongoing', 2: 'completed', 3: 'cancelled', 4: 'cancelled', 5: 'cancelled'}.get(item.get('status'), ''))
        row['artists'] = strings(item.get('artist'))
        return row

    def vocabulary(self, http):
        return [{'label': name, 'sourceId': str(key), 'category': 'tag'} for key, name in SCAN_TERMS.items()]

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if sort == 'updated' and not query and not tag:
            data = self.endpoint(http, '/chapters', page=page, limit=14, chapters='true', series_details='true',
                                 group_details='true', sort='date')
            rows = items(data, 'data')
            more = (data.get('meta') or {}).get('has_more') is True
        else:
            args = {'limit': 21, 'offset': (page - 1) * 21}
            if query or tag:
                if tag and (not re.fullmatch(r'[1-9]\d?', tag) or int(tag) not in SCAN_TERMS):
                    raise SourceError('Некорректная метка каталога ScansGG.')
                args.update(q_type='[]', q_status='[]', q_tags=f'[{tag}]')
            if query:
                args['q'] = query
            data = self.endpoint(http, '/series', **args)
            rows = items(data, 'data')
            more = len(rows) == 21
        return [self.row_data(row) for row in rows if isinstance(row, dict)], more

    def saved_title_url(self, value):
        return self.ROOT + '/series/' + value if isinstance(value, str) and re.fullmatch(NUM, value) else super().saved_title_url(value)

    def source_details(self, http, url):
        key = self.title_key(url)
        if not key:
            raise SourceError('Некорректная ссылка на тайтл ScansGG.')
        data = self.endpoint(http, '/series', id=key, trackers='true', sources='true')
        item = data.get('data') if isinstance(data, dict) else None
        if not isinstance(item, dict) or str(item.get('id')) != key:
            raise SourceError('ScansGG вернул другой тайтл.')
        return self.row_data(item)

    def details(self, http, url):
        return self.source_details(http, self.saved_title_url(url))

    def series(self, http, url):
        row = self.source_details(http, url)
        key, chapters = self.title_key(url), {}
        for page in range(1, 101):
            data = self.endpoint(http, '/chapters', series_id=key, limit=100, page=page, group_details='true')
            for item in items(data, 'data'):
                if not isinstance(item, dict) or (n := number(item.get('number'))) is None:
                    continue
                chapter, group = str(item.get('id')), str(item.get('group_id') or 0)
                if not re.fullmatch(NUM, chapter) or not re.fullmatch(r'\d{1,15}', group):
                    continue
                target = query_url(f'{self.ROOT}/series/{key}/chapter-{chapter}', mv_group=group)
                label = f'Chapter {n:g}' + (' - ' + str(item['title']) if item.get('title') else '')
                chapters[target] = self.chapter(target, label, n, str(item.get('created_at') or '')[:10],
                                                translator=(item.get('group') or {}).get('title') or '')
            if not (data.get('meta') or {}).get('has_more'):
                return row, self.order(chapters)
        raise SourceError('ScansGG не предоставил полное оглавление.')

    def saved_chapter(self, row, root, title):
        value = row.get('url') or row.get('realUrl') or ''
        if isinstance(value, str) and urlsplit(value).path == '/chapter-navigation':
            key, ch, group = (param(value, name) for name in ('series_id', 'chapter_id', 'group_id'))
            if re.fullmatch(NUM, key) and re.fullmatch(NUM, ch) and re.fullmatch(r'\d{1,15}', group):
                return query_url(f'{self.ROOT}/series/{key}/chapter-{ch}', mv_group=group)
        return super().saved_chapter(row, root, title)

    def chapter_identity(self, url):
        return super().chapter_identity(url), param(url, 'mv_group')

    def pages(self, http, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        data = self.endpoint(http, '/chapter-navigation', series_id=match[1], chapter_id=match[2],
                             group_id=param(url, 'mv_group') or 0)
        chapter = (data.get('data') or {}).get('chapter') if isinstance(data, dict) else None
        if not isinstance(chapter, dict) or str(chapter.get('id')) != match[2]:
            raise SourceError('ScansGG вернул страницы другой главы.')
        rows = items(chapter, 'pages')
        valid = [row for row in rows if isinstance(row, dict) and type(row.get('position')) is int and segment(row.get('path'))]
        if len(valid) != len(rows):
            raise SourceError('ScansGG вернул неполный список страниц.')
        root = f'https://cdn.scans.gg/uploads/pages/{match[2]}/'
        return [root + quote(row['path'], safe='') for row in sorted(valid, key=lambda row: row['position'])]


class StoneScape(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, SERIES, rf'/series/{SLUG}/ch-({NUMBER})/?', interval=.35)

    def title_for(self, url):
        return self.ROOT + '/series/' + self.chapter_key(url)

    def chapter_identity(self, url):
        return super().chapter_identity(url), urlsplit(url).fragment

    def row_data(self, row):
        slug = segment(row.get('slug'))
        title = row.get('title')
        if not slug or not isinstance(title, str) or not title.strip():
            raise SourceError('StoneScape не предоставил карточку тайтла.')
        return self.record(self.ROOT + '/series/' + slug, title, image_url(row.get('coverUrl'), self.ROOT),
                           description=row.get('description') or '', authors=[row.get('author')],
                           genres=[term.replace('-', ' ').title() for term in strings(row.get('genres'))],
                           status=str(row.get('publicationStatus') or '').casefold())

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        options = {'page': page, 'limit': 24, 'contentType': 'manhwa'}
        route = '/api/series'
        if not query and not tag and sort == 'popular':
            route += '/popular'
            options['period'] = 'week'
        if query:
            options['search'] = query
        if tag:
            options['genres'] = tag[:120]
        data = self.json(http, query_url(self.ROOT + route, **options))
        return [self.row_data(row) for row in items(data, 'data') if isinstance(row, dict)], (
            page < (number((data.get('pagination') or {}).get('totalPages')) or page))

    def details(self, http, url):
        slug = self.title_key(self.saved_title_url(url))
        if not slug:
            raise SourceError('Некорректная ссылка на тайтл StoneScape.')
        data = self.json(http, self.ROOT + '/api/series/by-slug/' + slug)
        if not isinstance(data, dict) or segment(data.get('slug')) != slug:
            raise SourceError('StoneScape вернул другой тайтл.')
        row = self.row_data(data)
        row['artists'] = [data['artist']] if data.get('artist') else []
        row['format'] = 'manhwa'
        return row

    def series(self, http, url):
        row = self.details(http, url)
        slug = self.title_key(url)
        response = self.json(http, self.ROOT + '/api/series/by-slug/' + slug + '/chapters')
        chapters = {}
        for item in items(response, 'chapters'):
            if not isinstance(item, dict) or (n := number(item.get('chapterNumber'))) is None:
                continue
            key = item.get('chapterId')
            if not isinstance(key, str) or not re.fullmatch(KEY, key):
                continue
            label = f'Chapter {n:g}' + (' - ' + str(item['title']) if item.get('title') else '')
            target = f'{self.ROOT}/series/{slug}/ch-{n:g}#{key}'
            chapters[target] = self.chapter(target, label, n, str(item.get('createdAt') or '')[:10])
        return row, self.order(chapters)

    def pages(self, http, url):
        key = urlsplit(url).fragment
        if not re.fullmatch(KEY, key):
            raise SourceError('Обнови оглавление StoneScape.')
        payload = self.json(http, self.ROOT + '/api/chapters/' + key + '/pages', url)
        response = payload.get('pages') or payload.get('images') if isinstance(payload, dict) else None
        if not isinstance(response, list):
            raise SourceError('StoneScape не предоставил список страниц.')
        rows = [(item.get('pageNumber') or idx + 1, image_url(item.get('url'), self.ROOT)) for idx, item in enumerate(response)
                if isinstance(item, dict)]
        if len(rows) != len(response):
            raise SourceError('StoneScape вернул неполный список страниц.')
        return [page for _, page in sorted(rows, key=lambda row: row[0])]
