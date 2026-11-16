"""Public catalogue and reader APIs for WaManga and Tomilo-lib."""

import json
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from manga_direct_payloads import JsonSeries, items, segment, strings
from manga_madara import SEGMENT, image_url
from manga_series_port import number
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


TOMILO = 'tomilo-lib.ru'
WA = 'wamanga.ru'
CDN = 'https://tomilolib.s3.regru.cloud'
ID = r'[a-fA-F0-9]{24}'
POSITION = r'\d{1,9}(?:\.\d{1,12})?'
WA_SERIES = rf'/((?:manga|manhwa|manhua|rumanga|comic|webtoon|manuscript|oel|doujinshi|other)/{SEGMENT})'
SVELTE = 'x-sveltekit-invalidated'
PAGE_SIZE = 24
CHAPTER_SIZE = 200


def public_api(host, path, query):
    args = parse_qs(query)
    if host == WA:
        if args.get(SVELTE) != ['001']:
            return False
        if path == '/catalog/__data.json':
            return (set(args) <= {SVELTE, 'offset', 'limit', 'sortKey', 'sortDescending', 'query'}
                    and args.get('limit') == ['24'] and len(args.get('offset', ())) == 1
                    and bool(re.fullmatch(r'\d{1,6}', args['offset'][0]))
                    and all(len(v) == 1 and len(v[0]) <= 160 for v in args.values()))
        return set(args) == {SVELTE} and bool(re.fullmatch(rf'{WA_SERIES}(?:/glava-{POSITION})?/__data\.json', path))
    if host != TOMILO:
        return False
    if re.fullmatch(rf'/api/(?:titles|chapters)/{ID}', path):
        return not query
    if path == '/api/chapters':
        return (set(args) == {'titleId', 'page', 'limit'} and args['limit'] == ['200']
                and len(args['titleId']) == len(args['page']) == 1 and bool(re.fullmatch(ID, args['titleId'][0]))
                and bool(re.fullmatch(r'[1-9]\d{0,3}', args['page'][0])))
    if path == '/api/titles':
        return (set(args) <= {'page', 'limit', 'sortBy', 'order', 'search', 'genres'} and args.get('limit') == ['30']
                and args.get('sortBy') in (['views'], ['updatedAt']) and args.get('order') == ['desc']
                and len(args.get('page', ())) == 1 and bool(re.fullmatch(r'[1-9]\d{0,3}', args['page'][0]))
                and all(len(v) == 1 and len(v[0]) <= 160 for v in args.values()))
    return False


def svelte_value(pool):
    if not isinstance(pool, list) or not pool:
        raise ValueError('Missing devalue pool')
    active, remaining = set(), 100000

    def expand(value, depth=0):
        nonlocal remaining
        remaining -= 1
        if depth > 40 or remaining < 0:
            raise ValueError('Unbounded devalue pool')
        if isinstance(value, list):
            if len(value) == 2 and value[0] == 'Promise':
                return None
            return [resolve(item, depth + 1) for item in value]
        if isinstance(value, dict):
            return {key: resolve(item, depth + 1) for key, item in value.items()}
        return value

    def resolve(value, depth):
        if type(value) is not int:
            return expand(value, depth)
        if value < 0:
            return None
        if value in active or value >= len(pool):
            raise ValueError('Invalid devalue reference')
        active.add(value)
        try:
            return expand(pool[value], depth)
        finally:
            active.remove(value)

    return resolve(0, 0)


class WaManga(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'{WA_SERIES}/?', rf'{WA_SERIES}/glava-({POSITION})/?', interval=.4)

    def wire(self, http, path, **options):
        endpoint = query_url(self.ROOT + path.rstrip('/') + '/__data.json', **{SVELTE: '001', **options})
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(endpoint, headers={'Referer': self.ROOT + '/'}, action='native-series-json')
        if final != endpoint:
            raise SourceError('WaManga перенаправил запрос на другой маршрут.')
        try:
            header = json.loads(next(line for line in raw.splitlines() if line.strip()))
            pool = next(node['data'] for node in reversed(header['nodes']) if node and node.get('type') == 'data')
            result = svelte_value(pool)
            if not isinstance(result, dict):
                raise ValueError('Unexpected payload')
            return result
        except (ValueError, KeyError, TypeError, StopIteration, RecursionError, AttributeError):
            raise SourceError('WaManga изменил формат данных SvelteKit.') from None

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.ROOT + '/' + key if key else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        path = urlsplit(target).path
        if match := re.fullmatch(rf'{WA_SERIES}/({POSITION})/?', path):
            return f'{self.ROOT}/{match[1]}/glava-{match[2]}'
        return ''

    def record_data(self, data):
        key, category, title = segment(data.get('slug')), data.get('type'), data.get('title')
        target = f'{self.ROOT}/{category}/{key}'
        if not self.is_title(target) or not isinstance(title, str) or not title.strip():
            raise SourceError('WaManga не предоставил карточку тайтла.')
        aliases = [item for item in strings(data.get('alternateTitles')) if item.strip() != data.get('slug')]
        if isinstance(data.get('titleEnglish'), str):
            aliases.append(data['titleEnglish'])
        row = self.record(target, title, image_url(data.get('coverUrl'), target), description=data.get('description') or '',
                          aliases=aliases, genres=strings(data.get('genres')), tags=strings(data.get('tags')),
                          authors=[item for item in strings(data.get('authors')) if item != 'N/A'],
                          status=str(data.get('statusTitle') or '').lower())
        row.update(format=category, artists=[item for item in strings(data.get('artists')) if item != 'N/A'])
        if type(data.get('year')) is int:
            row['year'] = data['year']
        if data.get('pegiRating') == '18+':
            row['adult'] = True
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'offset': (page - 1) * PAGE_SIZE, 'limit': PAGE_SIZE,
                'sortKey': 'updatedAt' if sort == 'updated' else 'likes', 'sortDescending': 'true'}
        if query:
            args['query'] = query
        rows = items(self.wire(http, '/catalog', **args), 'initialMangas')
        records = [self.record_data(row) for row in rows if isinstance(row, dict)]
        if tag:
            records = [row for row in records if tag.casefold() in {item.casefold() for item in (*row['genres'], *row['tags'])}]
        return records, len(rows) >= PAGE_SIZE

    def source_details(self, http, url):
        key = self.title_key(url)
        if not key:
            raise SourceError('Некорректная ссылка на карточку WaManga.')
        data = self.wire(http, '/' + key).get('manga')
        if not isinstance(data, dict) or f"{data.get('type')}/{segment(data.get('slug'))}" != key:
            raise SourceError('WaManga вернул другой тайтл.')
        return self.record_data(data), data

    def details(self, http, url):
        return self.source_details(http, self.saved_title_url(url))[0]

    def series(self, http, url):
        record, data = self.source_details(http, url)
        key = self.title_key(url)
        chapters = {}
        for row in data.get('chapters') or ():
            pos = str(row.get('position')) if isinstance(row, dict) else ''
            if re.fullmatch(POSITION, pos):
                target = f'{self.ROOT}/{key}/glava-{pos}'
                chapters[target] = self.chapter(target, f'Глава {pos}', float(pos), str(row.get('createdAt') or '')[:10])
        return record, self.order(chapters)

    def pages(self, http, url):
        data = self.wire(http, urlsplit(url).path)
        files = items(data.get('chapter'), 'files')
        rows = [(float(str(row['position'])), row['diskFile']) for row in files if isinstance(row, dict)
                and re.fullmatch(POSITION, str(row.get('position'))) and isinstance(row.get('diskFile'), str)]
        if len(rows) != len(files):
            raise SourceError('WaManga вернул неполный список страниц.')
        return [image_url(path, self.ROOT) for _, path in sorted(rows, key=lambda row: row[0])]


def locked_now(chapter):
    price = chapter.get('unlockPrice')
    if not chapter.get('isPaid') or type(price) is not int or price <= 0:
        return False
    try:
        value = datetime.fromisoformat(chapter['freeAt'])
        return value.astimezone(UTC) > datetime.now(UTC)
    except (KeyError, TypeError, ValueError):
        return True


class TomiloLib(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/titles/({SEGMENT})/?', rf'/chapters/({ID})/?', interval=.35)

    def asset(self, value):
        if not isinstance(value, str) or not value:
            return ''
        for root in (CDN, self.ROOT):
            if value.startswith(root + '/uploads/'):
                value = value[len(root + '/uploads'):]
                break
        return image_url(value.removeprefix('/uploads/'), CDN + '/')

    def endpoint(self, http, path, **options):
        target = self.ROOT + '/api' + path
        result = self.json(http, query_url(target, **options) if options else target)
        data = result.get('data') if isinstance(result, dict) else None
        if not isinstance(data, dict):
            raise SourceError('Tomilo-lib изменил формат ответа.')
        return data

    def row_data(self, row):
        key, slug, label = row.get('_id'), segment(row.get('slug')), row.get('name')
        if not isinstance(key, str) or not re.fullmatch(ID, key) or not isinstance(label, str) or not label.strip():
            raise SourceError('Tomilo-lib не предоставил карточку тайтла.')
        url = query_url(f'{self.ROOT}/titles/{slug or key}', mv_id=key)
        data = self.record(url, label, self.asset(row.get('coverImage')), aliases=strings(row.get('altNames')),
                           genres=strings(row.get('genres')), tags=strings(row.get('tags')), authors=[row.get('author')],
                           description=row.get('description') or '', status=str(row.get('status') or ''))
        data.update(artists=[row['artist']] if row.get('artist') else [], adult=row.get('isAdult') is True)
        if row.get('type') in {'manga', 'manhwa', 'manhua', 'comic'}:
            data['format'] = row['type']
        return data

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        filters = {'sortBy': 'updatedAt' if sort == 'updated' else 'views', 'order': 'desc', 'page': page, 'limit': 30}
        if query:
            filters['search'] = query
        if tag:
            filters['genres'] = tag[:120]
        data = self.endpoint(http, '/titles', **filters)
        rows = [self.row_data(row) for row in items(data, 'titles') if isinstance(row, dict)]
        total_pages = number((data.get('pagination') or {}).get('pages')) or page
        return rows, page < total_pages

    def saved_title_url(self, value):
        target = self.canonical(value)
        if self.is_title(target):
            return target
        if match := re.fullmatch(rf'/({SEGMENT})/({ID})/?', urlsplit(target).path):
            return query_url(f'{self.ROOT}/titles/{match[1]}', mv_id=match[2])
        return ''

    def title_for(self, url):
        slug, key = segment(param(url, 'mv_slug')), param(url, 'mv_id')
        return query_url(f'{self.ROOT}/titles/{slug}', mv_id=key) if slug and re.fullmatch(ID, key) else ''

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(self.title_for(url))

    def get_key(self, http, url):
        key = param(url, 'mv_id')
        if re.fullmatch(ID, key):
            return key
        slug = self.title_key(url)
        if re.fullmatch(ID, slug):
            return slug
        rows, _ = self.catalogue(http, query=slug.replace('-', ' '))
        return next((param(self.site_link(row['url']), 'mv_id') for row in rows
                     if slug == self.title_key(self.site_link(row['url']))), '')

    def details(self, http, url):
        target = self.saved_title_url(url)
        key = self.get_key(http, target) if target else ''
        if not key:
            raise SourceError('Tomilo-lib не предоставил ID тайтла.')
        data = self.endpoint(http, '/titles/' + key)
        if data.get('_id') != key:
            raise SourceError('Tomilo-lib вернул другой тайтл.')
        record = self.row_data(data)
        slug = self.title_key(target)
        if slug not in {key, self.title_key(self.site_link(record['sourceUrl']))}:
            raise SourceError('Сохранённая ссылка относится к другому тайтлу.')
        return record

    def series(self, http, url):
        record = self.details(http, url)
        title = self.site_link(record['sourceUrl'])
        key, slug = param(title, 'mv_id'), self.title_key(title)
        chapters = {}
        for page in range(1, 81):
            result = self.endpoint(http, '/chapters', titleId=key, page=page, limit=CHAPTER_SIZE)
            for row in items(result, 'chapters'):
                if not isinstance(row, dict) or row.get('isPublished') is False:
                    continue
                chapter = row.get('_id')
                if not isinstance(chapter, str) or not re.fullmatch(ID, chapter) or locked_now(row):
                    continue
                target = query_url(f'{self.ROOT}/chapters/{chapter}', mv_id=key, mv_slug=slug)
                n = number(row.get('chapterNumber'))
                chapters[target] = self.chapter(target, row.get('name') or f'Глава {n or 0:g}', n,
                                                str(row.get('releaseDate') or '')[:10])
            if page >= (number((result.get('pagination') or {}).get('pages')) or page):
                return record, self.order(chapters)
        raise SourceError('Tomilo-lib не предоставил полное оглавление.')

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        path = urlsplit(target).path
        chapter = path.rsplit('/', 1)[-1]
        if re.fullmatch(ID, chapter) and re.fullmatch(ID, key := param(title, 'mv_id')) and (slug := self.title_key(title)):
            return query_url(f'{self.ROOT}/chapters/{chapter}', mv_id=key, mv_slug=slug)
        return target if self.is_chapter(target) else ''

    def saved_chapter_matches(self, target, title):
        return bool(param(title, 'mv_id') and param(title, 'mv_id') == param(target, 'mv_id'))

    def pages(self, http, url):
        data = self.endpoint(http, '/chapters/' + self.chapter_key(url))
        rows = items(data, 'pages')
        if not rows and data.get('isPaid'):
            raise SourceAccessError('Глава платная и ещё не открыта бесплатно.')
        return [self.asset(page) for page in rows]
