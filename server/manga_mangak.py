"""MangaK and Toonily.me catalogue and Next.js reader (Keiyoushi Apache-2.0)."""

import json
import re
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_madara import CHAPTER_NUMBER, SEGMENT, VOLUME_NUMBER, image_url
from manga_page_media import MANGAK_FRAGMENT, mangak_cdn
from manga_source_tags import unique
from manga_vinetheme import dictionaries, flight_models, flight_stream, resolve_fields
from source_parser import SourceError, public_url


API_ID = r'[A-Za-z0-9_-]{1,100}'
TITLE_PATH = re.compile(rf'/({SEGMENT})/?')
CHAPTER_PATH = re.compile(rf'/({SEGMENT})/(?:{SEGMENT})(?:/{SEGMENT}){{0,2}}/?')
CHAPTER_API = re.compile(rf'/titles/{API_ID}/chapters')
FILTER_SLUG = re.compile(r'[a-z0-9][a-z0-9-]{0,100}')


def object_data(value):
    if not isinstance(value, dict):
        raise SourceError('MangaK вернул некорректную карточку.')
    return value


def records(value):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SourceError('MangaK вернул некорректный список.')
    return value


def names(value):
    return unique(row.get('name') for row in records(value or []))


def page_props(document, field):
    soup = BeautifulSoup(document, 'html.parser')
    node = soup.select_one('script#__NEXT_DATA__')
    if node:
        try:
            parsed = json.loads(node.string or '')
        except (ValueError, RecursionError):
            parsed = {}
        if isinstance(parsed, dict):
            props = parsed.get('props')
            if isinstance(props, dict) and isinstance(props.get('pageProps'), dict):
                value = props['pageProps'].get(field)
                if isinstance(value, dict):
                    return value
    models = flight_models(flight_stream(document))
    for model in models.values():
        for row in dictionaries(model):
            if (props := row.get('pageProps')) is not None:
                # Resolve references before reading nested lists in serialized React data.
                decoded = resolve_fields(props, models, [60000])
                if isinstance(decoded, dict) and isinstance(decoded.get(field), dict):
                    return decoded[field]
    raise SourceError('MangaK не предоставил ожидаемые данные читалки.')


class MangaK:
    IS_NSFW = True
    LANGUAGE = 'en'
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    index_sort = 'updated'

    def __init__(self, sid, name, root):
        self.SOURCE_ID, self.NAME, self.ROOT = sid, name, root
        self.host = urlsplit(root).netloc
        self.api_host = 'api.' + self.host

    def site_link(self, value, base=None):
        if isinstance(value, str) and value:
            try:
                target = urljoin(base or self.ROOT, value)
                if urlsplit(target).netloc == self.host:
                    return public_url(target, resolve_dns=False)
            except (ValueError, SourceError):
                pass
        return ''

    def get(self, http, path, params=None):
        url = 'https://' + self.api_host + path + ('?' + urlencode(params) if params else '')
        text, final, _ = http.document(url, headers={'Referer': self.ROOT + '/', 'Origin': self.ROOT})
        if final != url:
            raise SourceError('MangaK перенаправил запрос каталогов.')
        try:
            return object_data(object_data(json.loads(text)).get('data'))
        except (ValueError, RecursionError):
            raise SourceError('MangaK вернул страницу вместо данных API.') from None

    def document(self, http, url, field):
        text, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'})
        if not self.site_link(final) or urlsplit(final).path.rstrip('/') != urlsplit(url).path.rstrip('/'):
            raise SourceError('MangaK перенаправил запрос читалки.')
        return page_props(text, field)

    def row(self, data):
        from manga_sources import title_aliases

        url = self.site_link(data.get('url'))
        path = TITLE_PATH.fullmatch(urlsplit(url).path)
        name = data.get('name')
        if not path or not isinstance(name, str) or not name.strip():
            raise SourceError('MangaK не указал название или адрес произведения.')
        cover = image_url(data.get('cover'), self.ROOT + '/')
        media = data.get('type')
        kind = media.get('name') if isinstance(media, dict) else ''
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{path[1]}', 'sourceId': self.SOURCE_ID,
                'url': url, 'sourceUrl': url, 'sourceURL': url, 'providerName': self.NAME,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'title': name.strip()[:500],
                'aliases': unique([*title_aliases(name), *names(data.get('altNames'))]),
                'description': (data.get('summary') or '')[:12000], 'cover': cover,
                'kind': 'manga', 'language': self.LANGUAGE, 'ids': {}, 'sourceOnly': True,
                'authors': names(data.get('authors')), 'artists': names(data.get('artists')),
                'genres': names(data.get('genres')), 'tags': names(data.get('tags')), 'format': kind or '',
                'status': data.get('status') or ''}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or not isinstance(tag, str):
            raise SourceError('Некорректные параметры каталога MangaK.')
        params = {'page': page, 'limit': 24}
        if query:
            filtered = ''.join(char for char in query if char.isalnum() or char == ' ').strip()[:50]
            if not filtered:
                return [], False
            params['q'] = filtered
        elif not tag:
            params['sort'] = 'latest' if sort == 'updated' else 'popular'
            if params['sort'] == 'popular':
                params['window'] = 'week'
        if tag:
            if not FILTER_SLUG.fullmatch(tag):
                raise SourceError('Некорректный жанр MangaK.')
            params['genres'] = tag
        data = self.get(http, '/titles/search', params)
        return [self.row(value) for value in records(data.get('items'))], object_data(data.get('pagination')).get('has_next') is True

    def vocabulary(self, http):
        data = self.get(http, '/genres')
        return [{'label': row['name'], 'sourceId': row['slug'], 'category': 'genre'}
                for row in records(data.get('items')) if isinstance(row.get('name'), str)
                and isinstance(row.get('slug'), str) and FILTER_SLUG.fullmatch(row['slug'])]

    def title(self, http, url):
        data = self.document(http, url, 'initialManga')
        row = self.row({**data, 'url': data.get('url') or url})
        if urlsplit(row['url']).path.rstrip('/') != urlsplit(url).path.rstrip('/'):
            raise SourceError('MangaK вернул другое произведение.')
        identity = data.get('id')
        if not isinstance(identity, str) or not re.fullmatch(API_ID, identity):
            raise SourceError('MangaK не указал ID произведения.')
        return row, identity

    def details(self, http, value):
        url = self.site_link(value)
        if not TITLE_PATH.fullmatch(urlsplit(url).path):
            raise SourceError('Некорректная ссылка на тайтл MangaK.')
        return self.title(http, url)[0]

    def chapters(self, http, identity, slug):
        data = self.get(http, '/titles/' + identity + '/chapters', {'cv': int(time.time() * 1000)})
        episodes = []
        rows = records(data.get('chapters'))
        for index, item in enumerate(rows):
            url = self.site_link(item.get('url'))
            match = CHAPTER_PATH.fullmatch(urlsplit(url).path)
            name = item.get('name')
            if not match or match[1] != slug or not isinstance(name, str) or not name.strip():
                raise SourceError('MangaK вернул ссылку на другую главу.')
            number = CHAPTER_NUMBER.search(name) or CHAPTER_NUMBER.search(urlsplit(url).path.rsplit('/', 1)[-1])
            volume = VOLUME_NUMBER.search(name)
            stamp = item.get('updated_at')
            date = stamp[:10] if isinstance(stamp, str) and re.match(r'\d{4}-\d{2}-\d{2}', stamp) else ''
            episodes.append({'url': url, 'title': name, 'number': float(number[1].replace(',', '.')) if number else len(rows) - index,
                             'season': int(volume[1]) if volume else 1, 'language': self.LANGUAGE, 'translator': '',
                             'publishedAt': date})
        return sorted(episodes, key=lambda item: (item['season'], item['number']))

    def inspect(self, value, http):
        url = self.site_link(value)
        path = urlsplit(url).path
        title, chapter = TITLE_PATH.fullmatch(path), CHAPTER_PATH.fullmatch(path)
        if not (title or chapter):
            raise SourceError('Некорректная ссылка на читалку MangaK.')
        slug = (title or chapter)[1]
        row, identity = self.title(http, self.ROOT + '/' + slug)
        episodes = self.chapters(http, identity, slug)
        pages = []
        if chapter:
            episodes = [entry for entry in episodes if urlsplit(entry['url']).path.rstrip('/') == path.rstrip('/')]
            if len(episodes) != 1:
                raise SourceError('Глава не относится к выбранному произведению MangaK.')
            data = self.document(http, episodes[0]['url'], 'initialChapter')
            images = data.get('images')
            if not isinstance(images, list) or not 0 < len(images) <= 500:
                raise SourceError('MangaK не предоставил полный набор страниц.')
            for value in images:
                image = image_url(value, url)
                if not image:
                    raise SourceError('MangaK вернул некорректный адрес страницы.')
                parts = urlsplit(image)
                pages.append(urlunsplit(parts._replace(fragment=MANGAK_FRAGMENT)) if mangak_cdn(parts.hostname) else image)
        return {**row, 'url': url, 'episodes': episodes, 'pages': pages, 'available': bool(episodes),
                'truncated': False, 'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({item['season'] for item in episodes})],
                'dubs': [], 'releases': [], 'translations': []}

    def saved_chapter_url(self, value, _slug, root):
        return self.site_link(value, root)


SOURCES = (
    MangaK('5020395055978987501', 'MangaK', 'https://mangak.io'),
    MangaK('1581110056159285576', 'Toonily.me', 'https://toontop.io'),
)
HOSTS = frozenset(adapter.api_host for adapter in SOURCES)


def public_api(host, path, query):
    if host not in HOSTS:
        return False
    if path == '/genres':
        return not query
    if CHAPTER_API.fullmatch(path):
        return bool(re.fullmatch(r'cv=[0-9]{10,16}', query))
    if path != '/titles/search':
        return False
    try:
        params = parse_qs(query, strict_parsing=True, keep_blank_values=True, max_num_fields=7)
    except ValueError:
        return False
    if not params.keys() <= {'page', 'limit', 'sort', 'window', 'q', 'genres'} or any(len(v) != 1 for v in params.values()):
        return False
    page = params.get('page', [''])[0]
    q = params.get('q', [''])[0]
    return (bool(re.fullmatch(r'[1-9][0-9]{0,3}', page)) and int(page) <= 2000 and params.get('limit') == ['24']
            and params.get('sort', ['']) in ([''], ['popular'], ['latest'])
            and params.get('window', ['']) in ([''], ['week'])
            and ('q' not in params or 0 < len(q) <= 50 and all(char.isalnum() or char == ' ' for char in q))
            and ('genres' not in params or bool(FILTER_SLUG.fullmatch(params['genres'][0]))))
