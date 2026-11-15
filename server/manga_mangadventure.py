"""Public MangAdventure v2 reader, from the Apache-2.0 Keiyoushi source."""

from datetime import datetime, timezone
import json
import math
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from manga_madara import SEGMENT, image_url
from manga_source_tags import unique
from source_parser import SourceError, public_url


ID = r'[1-9][0-9]{0,10}'
BASE = '/api/v2'
TITLE_PATH = re.compile(rf'/reader/({SEGMENT})/?')
CHAPTER_PATH = re.compile(rf'/reader/({SEGMENT})/chapter/({ID})/?')
STORED_CHAPTER = re.compile(rf'{BASE}/chapters/({ID})/read/?')
SERIES_PATH = re.compile(rf'{BASE}/series/({SEGMENT})(/chapters)?')
PAGES_PATH = re.compile(rf'{BASE}/chapters/({ID})/pages')
COMMON_GENRES = ('4-Koma', 'Action', 'Adventure', 'Comedy', 'Doujinshi', 'Drama', 'Ecchi', 'Fantasy', 'Gender Bender',
                 'Harem', 'Hentai', 'Historical', 'Horror', 'Josei', 'Martial Arts', 'Mecha', 'Mystery', 'Psychological',
                 'Romance', 'School Life', 'Sci-Fi', 'Seinen', 'Shoujo', 'Shoujo Ai', 'Shounen', 'Shounen Ai',
                 'Slice of Life', 'Smut', 'Sports', 'Supernatural', 'Tragedy', 'Yaoi', 'Yuri')
ARC_GENRES = ('4-Koma', 'Chaos;Head', 'Collection', 'Comedy', 'Drama', 'Jubilee', 'Mystery', 'Psychological',
              'Robotics;Notes', 'Romance', 'Sci-Fi', 'Seinen', 'Shounen', 'Steins;Gate', 'Supernatural', 'Tragedy')


def records(data):
    rows = data.get('results')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise SourceError('MangAdventure вернул некорректный список.')
    return rows


def labels(value):
    return unique(value) if isinstance(value, list) else []


def published(value):
    if not re.fullmatch(r'[0-9]{1,13}', str(value)):
        return ''
    seconds = int(value)
    if seconds > 10**11:
        seconds /= 1000
    return datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat() if seconds < 4_102_444_800 else ''


class MangAdventure:
    LANGUAGE = 'en'
    IS_NSFW = False
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    index_sort = 'updated'

    def __init__(self, sid, name, root, genres):
        self.SOURCE_ID, self.NAME, self.ROOT, self.genres = sid, name, root, genres
        self.host = urlsplit(root).netloc

    def site_link(self, value, base=None):
        if isinstance(value, str) and value:
            try:
                target = urljoin(base or self.ROOT, value)
                if urlsplit(target).netloc == self.host:
                    return public_url(target, resolve_dns=False)
            except (ValueError, SourceError):
                pass
        return ''

    def request(self, http, endpoint, params=None):
        url = self.ROOT + BASE + endpoint + ('?' + urlencode(params) if params else '')
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'})
        if url != final:
            raise SourceError('MangAdventure перенаправил запрос на другой маршрут.')
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            raise SourceError('MangAdventure вернул страницу вместо данных API.') from None
        if not isinstance(data, dict):
            raise SourceError('MangAdventure вернул неожиданную карточку.')
        return data

    def row(self, data):
        from manga_sources import title_aliases

        slug, name = data.get('slug'), data.get('title')
        if not isinstance(slug, str) or not re.fullmatch(SEGMENT, slug) or not isinstance(name, str) or not name.strip():
            raise SourceError('MangAdventure не указал название или ссылку тайтла.')
        url = self.ROOT + '/reader/' + slug
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'sourceId': self.SOURCE_ID, 'sourceUrl': url,
                'sourceURL': url, 'url': url, 'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME,
                'kind': 'manga', 'language': self.LANGUAGE, 'title': name.strip()[:500],
                'aliases': unique([*title_aliases(name), *labels(data.get('aliases'))]),
                'authors': labels(data.get('authors')), 'artists': labels(data.get('artists')),
                'genres': labels(data.get('categories')), 'tags': [], 'ids': {}, 'sourceOnly': True,
                'cover': image_url(data.get('cover'), self.ROOT + '/'),
                'status': 'licensed' if data.get('licensed') is True else data.get('status') or '',
                'description': (data.get('description') or '')[:12000]}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or tag and tag not in self.genres:
            raise SourceError('Некорректные параметры каталога MangAdventure.')
        params = {'page': page}
        if query := query.strip()[:160]:
            params['title'] = query
        elif not tag:
            params['sort'] = '-latest_upload' if sort == 'updated' else '-views'
        if tag:
            params['categories'] = tag
        data = self.request(http, '/series', params)
        return [self.row(item) for item in records(data)], data.get('last') is False

    def vocabulary(self, http):
        return [{'label': label, 'sourceId': label, 'category': 'genre'} for label in self.genres]

    def series(self, http, slug):
        data = self.request(http, '/series/' + slug)
        if data.get('slug') != slug:
            raise SourceError('MangAdventure вернул другой тайтл.')
        return self.row(data)

    def details(self, http, value):
        match = TITLE_PATH.fullmatch(urlsplit(self.site_link(value)).path)
        if not match:
            raise SourceError('Некорректная ссылка на тайтл MangAdventure.')
        return self.series(http, match[1])

    def chapters(self, http, slug):
        data = self.request(http, f'/series/{slug}/chapters', {'date_format': 'timestamp'})
        episodes = []
        for item in records(data):
            identity, number = str(item.get('id')), item.get('number')
            if (not re.fullmatch(ID, identity) or type(number) not in (int, float) or not 0 <= number <= 100000
                    or not math.isfinite(number)):
                raise SourceError('MangAdventure вернул некорректную главу.')
            volume = item.get('volume')
            title = (item.get('full_title') or item.get('title') or f'Chapter {number}') + (' [END]' if item.get('final') is True else '')
            episodes.append({'url': f'{self.ROOT}/reader/{slug}/chapter/{identity}', 'title': title,
                             'number': number, 'season': volume if type(volume) is int and volume > 0 else 1,
                             'publishedAt': published(item.get('published')), 'language': self.LANGUAGE,
                             'translator': ', '.join(labels(item.get('groups')))})
        return episodes

    def pages(self, http, identity):
        rows = records(self.request(http, f'/chapters/{identity}/pages', {'track': 'true'}))
        positions = [item.get('number') for item in rows]
        if (not rows or len(rows) > 500 or any(type(n) is not int or n < 0 for n in positions)
                or len(set(positions)) != len(rows)):
            raise SourceError('MangAdventure не предоставил полный список страниц.')
        urls = [image_url(item.get('image'), self.ROOT + '/') for item in sorted(rows, key=lambda item: item['number'])]
        if not all(urls):
            raise SourceError('MangAdventure вернул некорректный адрес страницы.')
        return urls

    def inspect(self, value, http):
        target = self.site_link(value)
        path = urlsplit(target).path
        title, chapter = TITLE_PATH.fullmatch(path), CHAPTER_PATH.fullmatch(path)
        if not (title or chapter):
            raise SourceError('Некорректная ссылка на читалку MangAdventure.')
        slug = (title or chapter)[1]
        row = self.series(http, slug)
        episodes, pages = self.chapters(http, slug), []
        if chapter:
            episodes = [item for item in episodes if item['url'] == target.rstrip('/')]
            if len(episodes) != 1:
                raise SourceError('Глава не относится к выбранному тайтлу.')
            pages = self.pages(http, chapter[2])
        return {**row, 'url': target, 'episodes': episodes, 'pages': pages, 'available': bool(episodes),
                'truncated': False, 'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({item['season'] for item in episodes})],
                'dubs': [], 'releases': [], 'translations': unique(item['translator'] for item in episodes)}

    def saved_title_url(self, value):
        path = urlsplit(value).path
        if TITLE_PATH.fullmatch(path):
            return value
        slug = path.strip('/')
        return self.ROOT + '/reader/' + slug if re.fullmatch(SEGMENT, slug) else ''

    def saved_chapter_url(self, value, slug, root):
        if not isinstance(value, str):
            return ''
        if re.fullmatch(ID, value):
            return f'{self.ROOT}/reader/{slug}/chapter/{value}'
        parts = urlsplit(urljoin(root, value))
        match = STORED_CHAPTER.fullmatch(parts.path)
        if match and parts.scheme == 'https' and parts.netloc == self.host:
            return f'{self.ROOT}/reader/{slug}/chapter/{match[1]}'
        return self.site_link(value, root)


SOURCES = (
    MangAdventure('6809555026902049727', 'Arc-Relight', 'https://arc-relight.com', ARC_GENRES),
    MangAdventure('8088090686762347480', 'Assorted Scans', 'https://assortedscans.com', COMMON_GENRES),
)
HOSTS = {adapter.host: adapter for adapter in SOURCES}


def public_api(host, path, query):
    adapter = HOSTS.get(host)
    if adapter is None:
        return False
    if match := SERIES_PATH.fullmatch(path):
        return query == ('date_format=timestamp' if match[2] else '')
    if PAGES_PATH.fullmatch(path):
        return query == 'track=true'
    if path != BASE + '/series':
        return False
    try:
        params = parse_qs(query, keep_blank_values=True, strict_parsing=True, max_num_fields=4)
    except ValueError:
        return False
    if not params.keys() <= {'page', 'sort', 'title', 'categories'} or any(len(values) != 1 for values in params.values()):
        return False
    page = params.get('page', [''])[0]
    return (bool(re.fullmatch(r'[1-9][0-9]{0,3}', page)) and int(page) <= 2000
            and ('sort' not in params or params['sort'][0] in {'-views', '-latest_upload'})
            and ('title' not in params or 0 < len(params['title'][0]) <= 160)
            and ('categories' not in params or params['categories'][0] in adapter.genres))
