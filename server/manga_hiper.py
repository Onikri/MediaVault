"""Hiper (tRPC) catalogues: Hiperdex.

Port of keiyoushi ``lib-multisrc/hiper`` and ``src/en/hiperdex`` at 6f345a8.
The site answers its tRPC API after a guest page visit sets the ``__st``
cookie; every API call carries the public ``x-cfg-auth`` key of the web app.
"""

from datetime import datetime
import json
import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT
from manga_ninth_routes import Route, register
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

UNDEFINED = ['undefined']
PROCEDURES = {'search.query', 'series.genres', 'auth.me,series.bySlugWithGenres', 'auth.me,series.chapters',
              'auth.me,series.bySlug,reader.chapterPages'}
STATUSES = {'ongoing': 'ongoing', 'hiatus': 'hiatus', 'cancelled': 'cancelled', 'completed': 'completed'}
FORMATS = {'manga': 'manga', 'manhwa': 'manhwa', 'manhua': 'manhua', 'webtoon': 'manhwa', 'one_shot': 'manga'}
SORTS = {'popular': 'popular', 'updated': 'recent', 'new': 'newest', 'rating': 'score', 'alphabet': 'alphabetical'}


class Hiper(JsonSeries):
    AUTH = ''
    HOST = ''

    def __init__(self, identity, *, genres=()):
        root = identity[3]
        super().__init__(identity, rf'/manga/({SEGMENT})/?', rf'/manga/({SEGMENT}/[0-9]{{1,6}}(?:\.[0-9]{{1,3}})?)/?',
                         interval=1 / 3)
        self.genres = tuple(genres)
        self.HOST = urlsplit(root).netloc
        self.action = 'n9:hiper-' + self.HOST

    def route(self, url, method, data, headers):
        if url.netloc != self.HOST or method != 'GET' or data is not None:
            return None
        if url.path == '/' and not url.query:
            return Route({'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}, cookies=True)
        if self.api(url.netloc, url.path, url.query):
            return Route({'Accept': 'application/json', 'x-cfg-auth': self.AUTH}, cookies=True, redirect=False)
        return None

    def api(self, host, path, query):
        if host != self.HOST or not path.startswith('/api/trpc/') or path[10:] not in PROCEDURES:
            return False
        try:
            fields = parse_qsl(query, keep_blank_values=True, max_num_fields=3, strict_parsing=True)
        except ValueError:
            return False
        args = dict(fields)
        return len(fields) == 2 and args.get('batch') == '1' and 0 < len(args.get('input', '')) <= 3000

    def title_key(self, url):
        match = self.TITLE_PATH.fullmatch(urlsplit(url).path)
        return match[1] if match else ''

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.ROOT + '/manga/' + key.split('/', 1)[0] if key else ''

    def chapter_identity(self, url):
        return urlsplit(url).path.rstrip('/') + '#' + param(url, 'mv_chapter')

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title))

    def call(self, http, procedures, payload):
        target = query_url(f'{self.ROOT}/api/trpc/{procedures}', batch='1',
                           input=json.dumps(payload, separators=(',', ':'), ensure_ascii=False))
        for attempt in range(2):
            self.origin.wait(getattr(http, 'deadline', None))
            try:
                raw, _, _ = http.document(target, headers={'Referer': self.ROOT + '/'}, action=self.action)
                break
            except SourceAccessError:
                if attempt:
                    raise
                # The web app issues the guest cookie on its first page view.
                http.document(self.ROOT + '/', headers={'Referer': self.ROOT + '/'}, action=self.action)
        try:
            data = json.loads(raw)
        except ValueError:
            raise SourceError(f'{self.NAME} изменил формат API.') from None
        if not isinstance(data, list) or not data:
            raise SourceError(f'{self.NAME} изменил формат API.')
        results = []
        for item in data:
            if not isinstance(item, dict) or 'error' in item:
                results.append(None)
                continue
            results.append(((item.get('result') or {}).get('data') or {}).get('json'))
        return results

    def record_from(self, item):
        if not isinstance(item, dict) or not isinstance(item.get('slug'), str) or not isinstance(item.get('title'), str):
            return None
        url = self.ROOT + '/manga/' + item['slug']
        if not self.is_title(url):
            return None
        aliases = item.get('alternativeTitles')
        if isinstance(aliases, str):
            try:
                aliases = json.loads(aliases)
            except ValueError:
                aliases = []
        genres = [g for g in item.get('genres') or [] if isinstance(g, str)]
        if isinstance(item.get('type'), str):
            genres.append(item['type'].replace('_', ' ').title())
        tags = [g for g in item.get('tags') or [] if isinstance(g, str)]
        names = lambda key: [n for n in item.get(key) or [] if isinstance(n, str)]
        row = self.record(url, item['title'].strip(), item.get('coverUrl') or '',
                          aliases=[a for a in aliases or [] if isinstance(a, str)],
                          description=(item.get('synopsis') or '').strip(), genres=genres, tags=tags,
                          authors=names('authors') + names('artists'),
                          status=STATUSES.get(str(item.get('status') or '').lower(), ''))
        row['format'] = FORMATS.get(str(item.get('type') or ''), 'manga')
        if type(item.get('year')) is int and 1900 < item['year'] < 2100:
            row['year'] = item['year']
        if item.get('contentRating') in {'pornographic', 'erotica'}:
            row['adult'] = True
        row['seriesId'] = item.get('id')
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and tag not in self.genres:
            return [], False
        values = {'filters.type': UNDEFINED, 'filters.status': UNDEFINED, 'filters.contentRating': UNDEFINED,
                  'filters.author': UNDEFINED, 'filters.artist': UNDEFINED, 'filters.year': UNDEFINED}
        if not tag:
            values['filters.genres'] = UNDEFINED
        payload = {'0': {'json': {
            'q': query, 'sort': 'relevance' if query else SORTS.get(sort, 'popular'),
            'filters': {'genres': [tag] if tag else None, 'type': None, 'status': None, 'contentRating': None,
                        'author': None, 'artist': None, 'year': None},
            'limit': 30, 'offset': (page - 1) * 30, 'maxRating': 'pornographic'}, 'meta': {'values': values}}}
        result = self.call(http, 'search.query', payload)[0]
        hits = result.get('hits') if isinstance(result, dict) else None
        if not isinstance(hits, list):
            raise SourceError(f'{self.NAME} не вернул каталог.')
        rows = [row for row in map(self.record_from, hits) if row]
        total = result.get('totalHits') if isinstance(result.get('totalHits'), int) else None
        more = bool(rows) and (page * 30 < total if total is not None else len(hits) == 30)
        for row in rows:
            row.pop('seriesId', None)
        return rows, more

    def vocabulary(self, http):
        return [{'key': name, 'label': name, 'kind': 'genre'} for name in self.genres]

    def series(self, http, url):
        slug = self.title_key(url)
        detail = self.call(http, 'auth.me,series.bySlugWithGenres',
                           {'0': {'json': None, 'meta': {'values': UNDEFINED}}, '1': {'json': {'slug': slug}}})[-1]
        row = self.record_from(detail)
        if not row or self.title_key(row['url']) != slug or type(row.get('seriesId')) is not int:
            raise SourceError(f'{self.NAME} не предоставил карточку тайтла.')
        series_id = row.pop('seriesId')
        listing = self.call(http, 'auth.me,series.chapters', {
            '0': {'json': {'values': UNDEFINED}},
            '1': {'json': {'seriesId': series_id, 'chapterId': None, 'sort': 'best', 'page': 1, 'limit': 20},
                  'meta': {'values': {'chapterId': UNDEFINED}}},
            '2': {'json': {'seriesId': series_id}}})[-1]
        if not isinstance(listing, list):
            raise SourceError(f'{self.NAME} не предоставил список глав.')
        chapters = {}
        for item in listing:
            if not isinstance(item, dict) or type(item.get('id')) is not int or item.get('isDeleted'):
                continue
            if item.get('status', 'published') != 'published' or not isinstance(item.get('number'), (int, float)):
                continue
            n = float(item['number'])
            label = f'{n:g}'
            title = item.get('title') if isinstance(item.get('title'), str) else ''
            name = title if title and re.search(rf'(?<![\d.]){re.escape(label)}(?![\d.])', title) else (
                f'Chapter {label}' + (f' {title}' if title else ''))
            target = query_url(f'{self.ROOT}/manga/{slug}/{label}', mv_chapter=str(item['id']))
            date = ''
            try:
                date = datetime.fromisoformat(item.get('createdAt', '').replace('Z', '+00:00')).date().isoformat()
            except (AttributeError, ValueError):
                pass
            chapters[item["id"]] = self.chapter(target, name, n, date)
        return row, self.order(chapters)

    def pages(self, http, url):
        key = self.chapter_key(url)
        slug, number = key.split('/', 1)
        chapter = param(url, 'mv_chapter')
        request = {'seriesSlug': slug, 'chapterNumber': float(number)}
        if re.fullmatch(r'[1-9][0-9]{0,11}', chapter):
            request['chapterId'] = int(chapter)
        data = self.call(http, 'auth.me,series.bySlug,reader.chapterPages', {
            '0': {'json': None, 'meta': {'values': UNDEFINED}}, '1': {'json': {'slug': slug}},
            '2': {'json': request}})[-1]
        if not isinstance(data, list):
            raise SourceAccessError(f'{self.NAME} не открыл страницы главы.')
        pages = sorted((item for item in data if isinstance(item, dict) and type(item.get('pageOrder')) is int),
                       key=lambda item: item['pageOrder'])
        return [item.get('avifUrl') or item.get('webpUrl') or '' for item in pages]


class Hiperdex(Hiper):
    AUTH = 'yceqt7qgu004'


HIPERDEX_GENRES = (
    '4-Koma', 'Action', 'Adaptation', 'Adult', 'Adventure', 'Age Gap', 'Aliens', 'Ancient Korea', 'Anthology',
    'Campus', 'Childhood Friends', 'Comedy', 'Cooking', 'Crime', 'Crossdressing', 'Dance', 'Delinquents', 'Demons',
    'Doujinshi', 'Drama', 'Ecchi', 'Escolar', 'Fantasy', 'Fellatio/Blowjob', 'Fetish', 'Full Color', 'Furry',
    'Gender Bender', 'Genderswap', 'Ghosts', "Girls' Love", 'Gore', 'Guideverse', 'Gyaru', 'Hair Color Change',
    'Harem', 'Hentai', 'Heroes', 'Historical', 'Horror', 'Human-Nonhuman Relationship', 'Isekai', 'Josei', 'Korea',
    'Korean Ambience', 'Korean BL', 'Long Strip', 'Long-Haired Male Character/s', 'Long-Haired Male Lead',
    'Love Triangle/s', 'Low Fantasy', 'Maduro', 'Mafia', 'Magic', 'Male Protagonist', 'Manga', 'Martial Arts',
    'Masculine Uke', 'Mature', 'Mecha', 'Medical', 'Military', 'Monster Girls', 'Monsters', 'Monsters Invade Earth',
    'Murim', 'Muscular Male Lead', 'Muscular Uke', 'Music', 'Mystery', 'Nameverse', 'Ninja', 'Office Workers',
    'Older Uke Younger Seme', 'Oneshot', 'Orphan Female Lead', 'Police', 'Post-Apocalyptic', 'Psychological',
    'Red-Haired Male Lead', 'Red-Haired Seme', 'Regression', 'Reincarnation', 'Revenge', 'Romance', 'Samurai',
    'School Life', 'Sci-fi', 'Secret Relationship', 'Seinen', 'Sexual Violence', 'Shota', 'Shoujo', 'Shoujo Ai',
    'Shounen', 'Size Difference', 'Slice of Life', 'Smut', 'Sobrenatural', 'Sports', 'Superhero', 'Supernatural',
    'Survival', 'Suspense', 'Thriller', 'Time Travel', 'Tower', 'Tragedy', 'Uncensored', 'Video Games',
    'Villainess', 'Violence', 'Virtual Reality', 'Web Comic', 'Webtoon', 'Wuxia', 'Yaoi', 'Yuri',
)

SOURCES = (Hiperdex(('3064755045370217842', 'Hiperdex', 'en', 'https://hiperdex.tv', True), genres=HIPERDEX_GENRES),)
for _source in SOURCES:
    register(_source.action[3:], _source.route, _source.api)
