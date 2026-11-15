"""Public VineTheme catalogue and React Flight data used by Keiyoushi's Apache-2.0 extensions."""

import base64
import json
import re
import time
import unicodedata
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, image_url
from manga_source_tags import unique
from source_parser import PublicHttp, SourceAccessError, SourceError, public_url


SLUG = re.compile(SEGMENT)
TITLE_PATH = re.compile(rf'/series/comic/({SEGMENT})/?')
NUMBER = r'[0-9]{1,6}(?:\.[0-9]{1,8})?'
CHAPTER_PATH = re.compile(rf'/series/comic/({SEGMENT})/chapter/({NUMBER})/?')
FLIGHT_ROW = re.compile(rb'([0-9a-f]{1,12}):', re.I)
FLIGHT_TEXT = re.compile(rb'T([0-9a-f]{1,8}),', re.I)
REFERENCE = re.compile(r'\$[@LQW]?([0-9a-f]{1,12})(?::([^\n]+))?', re.I)
PUSH = re.compile(r'self\.__next_f\.push\(\s*')
COUNTER = re.compile(r'\s+\(\d+\)$')
JSON = json.JSONDecoder()
MAX_CHAPTER_PAGES = 1000


def flight_stream(text):
    if not text.lstrip().startswith('<'):
        return text.encode('utf-8')
    chunks = []
    soup = BeautifulSoup(text, 'html.parser')
    for script in soup.select('script:not([src])'):
        body = script.string or ''
        for match in PUSH.finditer(body):
            try:
                payload, _ = JSON.raw_decode(body, match.end())
                if isinstance(payload, list) and len(payload) >= 2 and isinstance(payload[1], str):
                    if payload[0] == 1:
                        chunks.append(payload[1].encode('utf-8'))
                    elif payload[0] == 3:
                        chunks.append(base64.b64decode(payload[1], validate=True))
            except (ValueError, RecursionError):
                continue
    return b''.join(chunks)


def flight_models(data):
    models = {}
    cursor = 0
    while cursor < len(data):
        row = FLIGHT_ROW.match(data, cursor)
        newline = data.find(b'\n', cursor)
        next_row = newline + 1 if newline >= 0 else len(data)
        if not row:
            cursor = next_row
            continue
        identity = row[1].decode('ascii').lower()
        if length := FLIGHT_TEXT.match(data, row.end()):
            cursor = length.end() + int(length[1], 16)
            if cursor > len(data):
                raise SourceError('VineTheme вернул обрезанный текстовый блок.')
            try:
                models[identity] = data[length.end():cursor].decode('utf-8')
            except UnicodeDecodeError as error:
                raise SourceError('VineTheme вернул неверную кодировку текстового блока.') from error
            continue
        try:
            models[identity] = json.loads(data[row.end():next_row])
        except (ValueError, RecursionError):
            pass
        cursor = next_row
    return models


def dictionaries(value):
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            yield item
            stack.extend(reversed(item.values()))
        elif isinstance(item, list):
            stack.extend(reversed(item))


def resolve_fields(value, models, remaining, parents=frozenset(), depth=0):
    remaining[0] -= 1
    if depth > 48 or remaining[0] < 0:
        raise SourceError('Данные VineTheme превышают лимит разбора.')
    if isinstance(value, list):
        return [resolve_fields(child, models, remaining, parents, depth + 1) for child in value]
    if isinstance(value, dict):
        return {key: resolve_fields(child, models, remaining, parents, depth + 1) for key, child in value.items()}
    if not isinstance(value, str):
        return value
    if value.startswith('$$'):
        return value[1:]
    if value == '$undefined':
        return None
    if value.startswith('$D'):
        return value[2:]
    match = REFERENCE.fullmatch(value)
    if not match or match[1].lower() not in models:
        return value
    identity = match[1].lower()
    if identity in parents:
        raise SourceError('VineTheme вернул циклические ссылки в данных.')
    lineage = parents | {identity}
    item = models[identity]
    if match[2]:
        for part in match[2].split(':'):
            if isinstance(item, str):
                item = resolve_fields(item, models, remaining, lineage, depth + 1)
            if isinstance(item, list) and part.isdecimal() and len(part) < 8 and int(part) < len(item):
                item = item[int(part)]
            elif isinstance(item, dict) and part in item:
                item = item[part]
            else:
                return value
    item = resolve_fields(item, models, remaining, lineage, depth + 1)
    if value.startswith('$Q') and isinstance(item, list):
        return {pair[0]: pair[1] for pair in item
                if isinstance(pair, list) and len(pair) == 2 and isinstance(pair[0], str)}
    return item


def flight_data(text, shape):
    models = flight_models(flight_stream(text))
    for model in models.values():
        for item in dictionaries(model):
            if shape == 'chapter':
                chapter = item.get('chapter')
                if isinstance(chapter, str):
                    chapter = resolve_fields(chapter, models, [60000])
                if isinstance(chapter, dict) and 'pages' in chapter:
                    return resolve_fields(chapter, models, [60000])
                continue
            keys = ('series', 'chapters', 'totalPages') if shape == 'series' else ('genres', 'tags', 'tagTotal')
            if set(keys[:2]) <= item.keys() and (shape != 'filters' or 'tagTotal' in item):
                return resolve_fields({key: item[key] for key in keys if key in item}, models, [60000])
    raise SourceError('VineTheme не предоставил ожидаемые данные страницы.')


def payload_rows(value):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise SourceError('VineTheme вернул некорректный список.')
    return value


def term_parts(row):
    nested = row.get('genre')
    slug = row.get('slug') or (nested.get('slug') if isinstance(nested, dict) else '') or ''
    name = row.get('name') or slug
    if not isinstance(slug, str) or not isinstance(name, str):
        return '', ''
    label = ''.join(char for char in name if char.isascii() or unicodedata.category(char).startswith('L'))
    return slug, label.strip()


class VineTheme:
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    LANGUAGE = 'en'

    def __init__(self, sid, name, root, adult=False):
        self.SOURCE_ID, self.NAME, self.ROOT, self.IS_NSFW = sid, name, root, adult
        self.host = urlsplit(root).netloc

    def site_link(self, value, base=None):
        if isinstance(value, str) and value:
            try:
                target = urljoin(base or self.ROOT, value)
                parts = urlsplit(target)
                if parts.scheme == 'https' and parts.netloc == self.host:
                    return public_url(target, resolve_dns=False)
            except (ValueError, SourceError):
                pass
        return ''

    def request(self, http, path, params=None, *, action):
        url = self.ROOT + path + ('?' + urlencode(params) if params else '')
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/series'}, action=action)
        if not self.site_link(final) or urlsplit(final).path.rstrip('/') != path.rstrip('/'):
            raise SourceError('VineTheme перенаправил запрос на другую страницу.')
        return raw

    def row(self, data, fallback=''):
        from manga_sources import title_aliases
        label = data.get('title') or ''
        slug = data.get('urlSlug') or fallback or data.get('slug') or ''
        if not isinstance(label, str) or not label.strip() or not isinstance(slug, str) or not SLUG.fullmatch(slug):
            raise SourceError('VineTheme вернул карточку без названия или ссылки.')
        url = self.ROOT + '/series/comic/' + slug
        genres = unique(term_parts(item)[1] for item in payload_rows(data.get('genres') or []))
        tags = unique(term_parts(item)[1] for item in payload_rows(data.get('tags') or []))
        if data.get('isMature') is True:
            tags = unique([*tags, 'Mature'])
        team = data.get('team')
        alternative = data.get('aliases') or []
        aliases = unique([*title_aliases(label), data.get('originalTitle'), *(alternative if isinstance(alternative, list) else [])])
        description = BeautifulSoup(data.get('description') or '', 'html.parser').get_text(' ', strip=True)
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'provider': 'suwayomi:' + self.SOURCE_ID,
                'providerName': self.NAME, 'sourceId': self.SOURCE_ID, 'sourceUrl': url, 'sourceURL': url, 'url': url,
                'kind': 'manga', 'language': self.LANGUAGE, 'title': label.strip()[:500], 'ids': {}, 'sourceOnly': True,
                'aliases': aliases, 'cover': image_url(data.get('coverImage'), url), 'description': description[:12000],
                'format': (data.get('type') or '').casefold(), 'status': (data.get('status') or '').casefold(),
                'genres': genres, 'tags': tags, 'authors': unique([team.get('name')]) if isinstance(team, dict) else []}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(tag, str):
            raise SourceError('Некорректные параметры каталога VineTheme.')
        params = {'limit': 24, 'contentMode': 'comics', 'page': page}
        if query:
            params['q'] = query[:160].strip()
        elif not tag:
            params['sort'] = 'updated' if sort == 'updated' else 'popular'
        if tag:
            kind, _, slug = tag.partition(':')
            if kind not in {'tag', 'genre'} or not SLUG.fullmatch(slug):
                raise SourceError('VineTheme не распознал фильтр каталога.')
            params[kind] = slug
        rows, more = self.listing(http, params)
        return [self.row(row) for row in rows], more

    def listing(self, http, params):
        raw = self.request(http, '/api/series', params, action='vine-json')
        try:
            data = json.loads(raw)
        except ValueError:
            raise SourceError('VineTheme вернул HTML вместо каталога.') from None
        if not isinstance(data, dict):
            raise SourceError('VineTheme вернул некорректный каталог.')
        entries = payload_rows(data.get('data'))
        meta = data.get('meta')
        return entries, isinstance(meta, dict) and meta.get('hasMore') is True

    def vocabulary(self, http):
        data = flight_data(self.request(http, '/series', action='vine-rsc'), 'filters')
        values = {}
        for field, kind in [('genres', 'genre'), ('tags', 'tag')]:
            for row in payload_rows(data[field]):
                slug, label = term_parts(row)
                if slug and label and SLUG.fullmatch(slug) and row.get('count') != 0:
                    identity = kind + ':' + slug
                    values[identity] = {'sourceId': identity, 'label': label, 'category': kind}
        return list(values.values())

    def legacy_term_label(self, label):
        return COUNTER.sub('', label)

    def series(self, http, value, page=1):
        path = urlsplit(self.site_link(value)).path
        match = TITLE_PATH.fullmatch(path)
        if not match:
            raise SourceError('Некорректная ссылка на тайтл VineTheme.')
        params = {'sort': 'desc'}
        if page != 1:
            params['page'] = page
        payload = flight_data(self.request(http, path, params, action='vine-rsc'), 'series')
        data = payload.get('series')
        if not isinstance(data, dict):
            raise SourceError('VineTheme не предоставил карточку произведения.')
        row = self.row(data, match[1])
        if unquote(urlsplit(row['url']).path.rstrip('/')) != unquote(path.rstrip('/')):
            raise SourceError('VineTheme вернул карточку другого произведения.')
        return row, payload

    def details(self, http, value):
        return self.series(http, value)[0]

    def resolve_stored_title(self, data):
        identity = data.get('url')
        title = data.get('title')
        if not isinstance(identity, str) or not SLUG.fullmatch(identity) or not isinstance(title, str) or not title.strip():
            return ''
        http = PublicHttp(timeout=(3, 6), deadline=time.monotonic() + 14)
        try:
            for page in range(1, 5):
                rows, more = self.listing(http, {'limit': 24, 'contentMode': 'comics', 'page': page, 'q': title.strip()[:160]})
                for row in rows:
                    if row.get('id') == identity:
                        return self.row(row)['url']
                if not more:
                    break
        finally:
            http.close()
        return ''

    def saved_chapter(self, row, root, title):
        target = self.site_link(row.get('realUrl') or row.get('url'), root)
        if CHAPTER_PATH.fullmatch(urlsplit(target).path):
            return target
        identity = row.get('url')
        if not isinstance(identity, str) or not SLUG.fullmatch(identity):
            return ''
        http = PublicHttp(timeout=(3, 6), deadline=time.monotonic() + 18)
        try:
            series, payload = self.series(http, title)
            for chapter, entry in self.entries(http, series['url'], payload):
                if chapter.get('id') == identity:
                    return entry['url']
        finally:
            http.close()
        return ''

    def entries(self, http, series, payload):
        total = payload.get('totalPages', 1)
        if type(total) is not int or not 1 <= total <= MAX_CHAPTER_PAGES:
            raise SourceError('VineTheme вернул некорректное число страниц оглавления.')
        for page in range(1, total + 1):
            data = payload if page == 1 else self.series(http, series, page)[1]
            for item in payload_rows(data['chapters']):
                if item.get('isLocked') is True:
                    continue
                number = str(item.get('number')).removesuffix('.0')
                if not re.fullmatch(NUMBER, number):
                    continue
                target = series + '/chapter/' + number
                title = item.get('title')
                yield item, {'url': target, 'title': title if title and title != number else 'Chapter ' + number,
                             'number': float(number), 'season': 1, 'language': self.LANGUAGE, 'translator': '',
                             'publishedAt': (item.get('publishedAt') or '')[:10]}

    def chapters(self, http, series, payload):
        chapters = {entry['url']: entry for _, entry in self.entries(http, series, payload)}
        return sorted(chapters.values(), key=lambda item: item['number'])

    def inspect(self, value, http):
        path = urlsplit(self.site_link(value)).path
        chapter = CHAPTER_PATH.fullmatch(path)
        if chapter:
            chapter_data = flight_data(self.request(http, path, action='vine-rsc'), 'chapter')
            if chapter_data.get('isLocked') is True:
                raise SourceAccessError('Глава VineTheme закрыта у источника.')
            url = self.ROOT + path.rstrip('/')
            pages = [image_url(row.get('imageUrl'), url) for row in payload_rows(chapter_data['pages'])]
            if not pages or len(pages) > 500 or not all(pages):
                raise SourceError('VineTheme не предоставил полный список страниц открытой главы.')
            result, _ = self.series(http, self.ROOT + '/series/comic/' + chapter[1])
            episodes = [{'url': url, 'title': chapter_data.get('title') or 'Chapter ' + chapter[2],
                         'number': float(chapter[2]), 'language': self.LANGUAGE, 'season': 1, 'translator': ''}]
        else:
            result, data = self.series(http, value)
            url = result['url']
            episodes, pages = self.chapters(http, url, data), []
        return {**result, 'url': url, 'episodes': episodes, 'pages': pages, 'available': bool(episodes),
                'truncated': False, 'seasons': [{'number': 1, 'name': 'Том 1'}] if episodes else [],
                'dubs': [], 'releases': [], 'translations': []}


SOURCES = (
    VineTheme('3513996752712952755', 'Diva Scans', 'https://divascans.org', True),
    VineTheme('7298341958704597260', 'Drake Scans', 'https://drakecomic.net'),
    VineTheme('7881856136524765210', 'Elf Toon', 'https://elftoon.net'),
    VineTheme('6622233282902198923', 'Kayn Scans', 'https://kaynscans.com'),
    VineTheme('7842256049285233541', 'KeroScans', 'https://keroscans.net', True),
    VineTheme('9114028255622294379', 'Valir Scans', 'https://valirscans.org'),
    VineTheme('3119719730967642939', 'WitchScans', 'https://witchtoons.net'),
)
ENABLED = {'7298341958704597260', '7881856136524765210', '6622233282902198923', '9114028255622294379'}
ACTIVE_SOURCES = tuple(source for source in SOURCES if source.SOURCE_ID in ENABLED)
HOSTS = frozenset(adapter.host for adapter in SOURCES)


def public_api(host, path, query):
    if host not in HOSTS or path != '/api/series':
        return False
    try:
        values = parse_qs(query, strict_parsing=True, max_num_fields=6)
    except ValueError:
        return False
    if any(len(items) != 1 for items in values.values()):
        return False
    args = {key: items[0] for key, items in values.items()}
    page = args.get('page', '')
    return (args.keys() <= {'limit', 'contentMode', 'page', 'sort', 'q', 'genre', 'tag'}
            and args.get('limit') == '24' and args.get('contentMode') == 'comics'
            and bool(re.fullmatch(r'[1-9][0-9]{0,3}', page)) and int(page) <= 2000
            and args.get('sort', '') in {'', 'popular', 'updated'}
            and len(args.get('q', '')) <= 160
            and all(SLUG.fullmatch(args[key]) for key in ('genre', 'tag') if key in args))


def rsc_route(host, path, query):
    if host not in HOSTS:
        return False
    try:
        values = parse_qs(query, keep_blank_values=True, max_num_fields=3)
    except ValueError:
        return False
    token = values.pop('_rsc', [''])
    if len(token) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]{0,64}', token[0]):
        return False
    if path.rstrip('/') == '/series' or CHAPTER_PATH.fullmatch(path):
        return not values
    if not TITLE_PATH.fullmatch(path):
        return False
    page = values.get('page', ['1'])
    return (values.keys() <= {'sort', 'page'} and values.get('sort') == ['desc']
            and len(page) == 1 and bool(re.fullmatch(r'[1-9][0-9]{0,3}', page[0]))
            and int(page[0]) <= MAX_CHAPTER_PAGES)
