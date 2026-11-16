"""InkStory and PureManga public TanStack server functions and image format."""

import json
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

from manga_direct_catalogues import SLUG
from manga_direct_payloads import JsonSeries, items, segment
from manga_madara import SEGMENT, image_url
from manga_series_port import number
from manga_source_tags import unique
from manga_webcomics import query_url
from source_parser import SourceError


FUNCTIONS = {
    'catalogue': '5e920c6f2538a89f74b8cc297001d862340f690c4684e8ab6c14522960998b2e',
    'book': 'f1eb190aebb53f98ebd70df7ef5ec57105819b52503dba8d8943811d2bced2f2',
    'chapters': '1c9d8e028fe5eab8c867ee5fc39b0a75acc20270c6cecf479cfd582404e947bc',
    'chapter': 'c342d30c43b5931eec428542eb9d2bf68431a41a046ae931929f8f018d7f5505',
}
SERVICES = {'inkstory.net': 'inkstory', 'v1.puremanga.me': 'puremanga.me'}
RESTRICTIONS = ('NONE', 'AUTHORIZED_ONLY', 'LIBRARY_ONLY')
ESCAPE = {'"': r'\"', '\\': r'\\', '\n': r'\n', '\r': r'\r', '\b': r'\b', '\t': r'\t', '\f': r'\f', '<': r'\x3C',
          '\u2028': r'\u2028', '\u2029': r'\u2029'}
UNESCAPE = {value: key for key, value in ESCAPE.items()}
ESCAPED = re.compile('|'.join(map(re.escape, UNESCAPE)))
KEY = b'UySkp0BzPhwlvP2V'
PAGE_MARKER = 'mv_inkstory_page'
PAGE_NAME = re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-x[a-f0-9]{3}(?:-[a-f0-9]{4})-[a-f0-9]{12}\.[A-Za-z0-9]{1,5}')


def public_api(host, path, query):
    if host == 'api.inuko.me':
        return path == '/v2/labels' and query in {'serviceName=' + value for value in SERVICES.values()}
    if host not in SERVICES or path.removeprefix('/_serverFn/') not in FUNCTIONS.values() or not path.startswith('/_serverFn/'):
        return False
    args = parse_qs(query)
    return set(args) == {'payload'} and len(args['payload']) == 1 and 1 <= len(args['payload'][0]) <= 2200


def payload(data):
    sequence = iter(range(10000))

    def encode(value):
        if isinstance(value, dict):
            index = next(sequence)
            return {'t': 10, 'i': index, 'p': {'k': list(value), 'v': [encode(item) for item in value.values()]}, 'o': 0}
        if isinstance(value, (list, tuple)):
            return {'t': 9, 'i': next(sequence), 'a': [encode(item) for item in value], 'o': 0}
        if value is None or type(value) is bool:
            return {'t': 2, 's': 0 if value is None else 2 if value else 3}
        if isinstance(value, str):
            return {'t': 1, 's': ''.join(ESCAPE.get(char, char) for char in value)}
        return {'t': 0, 's': value}

    return json.dumps({'t': encode({'data': data}), 'f': 127, 'm': []}, ensure_ascii=False, separators=(',', ':'))


def decode_result(data):
    refs, remaining = {}, 100000

    def decode(node, depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 40:
            raise ValueError('Unbounded serialization')
        kind = node['t']
        if kind in (0, 1, 2):
            raw = node['s']
            if kind == 1:
                return ESCAPED.sub(lambda match: UNESCAPE[match[0]], raw)
            if kind == 2:
                return {2: True, 3: False}.get(raw)
            return raw
        if kind == 4:
            return refs[node['i']]
        if kind == 9:
            value = [decode(item, depth + 1) for item in node['a']]
        elif kind in (10, 11):
            props = node['p']
            value = {key: decode(item, depth + 1) for key, item in zip(props['k'], props['v'], strict=True)}
        else:
            raise ValueError('Unknown serialization node')
        if 'i' in node:
            refs[node['i']] = value
        return value

    try:
        props = data['p']
        node = props['v'][props['k'].index('result')]
        result = decode(node)
        if not isinstance(result, dict):
            raise ValueError('Missing object')
        return result
    except (KeyError, IndexError, TypeError, ValueError, RecursionError):
        raise SourceError('Источник изменил формат ответа каталога.') from None


def xor_page(value):
    parts = urlsplit(value)
    return parts.hostname == 'static.inuko.me' and bool(PAGE_NAME.fullmatch(parts.path.rsplit('/', 1)[-1]))


def decode_image(raw):
    output = bytearray(raw)
    for offset, key in enumerate(KEY):
        output[offset::len(KEY)] = output[offset::len(KEY)].translate(bytes.maketrans(bytes(range(256)),
                                                                                     bytes(val ^ key for val in range(256))))
    return output


class InkStory(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/content/{SLUG}/?', rf'/content/{SLUG}/{SEGMENT}/?', interval=.5)

    def title_for(self, url):
        return self.ROOT + '/content/' + self.chapter_key(url)

    def function(self, http, operation, data):
        target = query_url(f'{self.ROOT}/_serverFn/{FUNCTIONS[operation]}', payload=payload(data))
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(target, headers={'Referer': self.ROOT + '/'}, action='inkstory-json')
        if final != target:
            raise SourceError('Источник перенаправил запрос на другой маршрут.')
        try:
            return decode_result(json.loads(raw))
        except ValueError:
            raise SourceError('Источник изменил формат ответа каталога.') from None

    def record_data(self, row):
        slug = segment(row.get('slug'))
        name = row.get('name') or {}
        names = unique([name.get(key) for key in ('ru', 'en', 'original')]
                       + [other.get('name') for other in row.get('altNames') or [] if isinstance(other, dict)])
        if not slug or not names:
            raise SourceError('Источник не предоставил карточку тайтла.')
        labels = [label for label in row.get('labels') or [] if isinstance(label, dict)]
        authors = [item['publisher'].get('name') for item in row.get('relations') or []
                   if isinstance(item, dict) and item.get('type') in {'AUTHOR', 'ARTIST'} and isinstance(item.get('publisher'), dict)]
        status = {'ONGOING': 'ongoing', 'DONE': 'completed', 'FROZEN': 'hiatus', 'ANNOUNCE': 'announced'}
        url = self.ROOT + '/content/' + slug
        result = self.record(url, names[0], image_url(row.get('poster'), url), aliases=names,
                             description=row.get('description') or '', authors=authors, status=status.get(row.get('status'), ''),
                             genres=[label.get('name') for label in labels if label.get('kind') == 'GENRE'],
                             tags=[label.get('name') for label in labels if label.get('kind') == 'TAG'])
        if type(row.get('year')) is int:
            result['year'] = row['year']
        if 'WEBTOON' in (row.get('formats') or []):
            result['format'] = 'webtoon'
        return result

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'size': 40, 'page': page - 1, 'sort': 'latestChapterAt' if sort == 'updated' else 'viewsCount',
                'orderBy': 'desc', 'readingRestriction': RESTRICTIONS}
        if query:
            args['search'] = query
        if tag:
            if not segment(tag):
                raise SourceError('Некорректная метка каталога.')
            args['labelsInclude'] = [tag]
        data = self.function(http, 'catalogue', args)
        return [self.record_data(row) for row in items(data, 'books') if isinstance(row, dict)], 40 * page < (number(data.get('total')) or 0)

    def vocabulary(self, http):
        url = query_url('https://api.inuko.me/v2/labels', serviceName=SERVICES[self.hostname])
        labels = self.json(http, url)
        if not isinstance(labels, list):
            raise SourceError('Источник изменил формат справочника.')
        return [{'label': label['name'], 'sourceId': label['id'], 'category': label['kind'].lower()}
                for label in labels if isinstance(label, dict) and isinstance(label.get('name'), str)
                and segment(label.get('id')) and label.get('kind') in {'GENRE', 'TAG'}]

    def saved_title_url(self, url):
        target = self.canonical(url)
        path = urlsplit(target).path.strip('/')
        return f'{self.ROOT}/content/{path}' if re.fullmatch(SEGMENT, path) else target

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        path = urlsplit(target).path.strip('/')
        return title.rstrip('/') + '/' + path if re.fullmatch(SEGMENT, path) else target

    def series(self, http, url):
        slug = self.title_key(url)
        data = self.function(http, 'book', {'slug': slug, 'createView': False})
        key = data.get('id')
        if segment(data.get('slug')) != slug or not segment(key):
            raise SourceError('Источник вернул другой тайтл.')
        chapters = self.function(http, 'chapters', key)
        result = {}
        for row in items(chapters, 'chapters'):
            if not isinstance(row, dict) or not (identity := segment(row.get('id'))):
                continue
            target = url.rstrip('/') + '/' + identity
            n = number(row.get('number'))
            vol = number(row.get('volume'))
            result[target] = self.chapter(target, row.get('title') or '', n, str(row.get('createdAt') or '')[:10],
                                           int(vol) if vol else 1, str(row.get('publisherNames') or ''))
        return self.record_data(data), self.order(result)

    def pages(self, http, url):
        chapter = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]
        data = self.function(http, 'chapter', {'id': chapter, 'createView': False})
        rows = [row for row in items(data, 'pages') if isinstance(row, dict)]
        pages = []
        for row in sorted(rows, key=lambda item: number(item.get('index')) or 0):
            image = image_url(row.get('image'), url)
            pages.append(urlunsplit(urlsplit(image)._replace(fragment=PAGE_MARKER)) if xor_page(image) else image)
        return pages
