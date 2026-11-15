"""Native BakkinReaderX catalogue and reader (Keiyoushi Apache-2.0)."""

import json
import os
import re
import threading
import time
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit, urlunsplit

from manga_madara import SEGMENT
from source_parser import SourceError, public_url


PART = re.compile(SEGMENT)


def part(value):
    if isinstance(value, str):
        encoded = quote(unquote(value), safe='')
        if PART.fullmatch(encoded):
            return encoded
    return ''


def only_rows(value):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SourceError('Bakkin вернул некорректный каталог.')
    return value


class Bakkin:
    IS_NSFW = False
    LANGUAGE = 'en'

    def __init__(self, sid, name, root):
        self.SOURCE_ID, self.NAME = sid, name
        self.ROOT = root.rstrip('/') + '/'
        location = urlsplit(self.ROOT)
        self.host = location.netloc
        self.prefix = location.path.rstrip('/')
        path = re.escape(self.prefix)
        self.TITLE_PATH = re.compile(rf'{path}/series/({SEGMENT})/?')
        self.CHAPTER_PATH = re.compile(rf'{path}/series/({SEGMENT})/({SEGMENT})/({SEGMENT})/?')
        self.cache = (0, {})
        self.lock = threading.Lock()

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            candidate = urljoin(base or self.ROOT, value)
            parts = urlsplit(candidate)
            if parts.netloc != self.host or (parts.path.rstrip('/') != self.prefix
                                              and not parts.path.startswith(self.prefix + '/')):
                return ''
            url = public_url(candidate, resolve_dns=False)
            if parts.path.rstrip('/') == self.prefix and parts.fragment.startswith('m='):
                return url + '#' + parts.fragment
            return url
        except (ValueError, SourceError):
            return ''

    def asset(self, value):
        if not isinstance(value, str) or not value:
            return ''
        url = self.site_link(value)
        parts = urlsplit(url)
        if not url or any(not part(segment) for segment in parts.path[len(self.prefix) + 1:].split('/')):
            return ''
        path = self.prefix + '/' + '/'.join(part(segment) for segment in parts.path[len(self.prefix) + 1:].split('/'))
        return urlunsplit(parts._replace(path=path, fragment=''))

    def data(self, http):
        target = self.site_link(self.ROOT + 'main.php')
        if not target:
            raise SourceError('Серверный адрес Bakkin Self-hosted ещё не настроен.')
        with self.lock:
            expires, cached = self.cache
            if expires > time.monotonic():
                return cached
            raw, final, _ = http.document(target, headers={'Referer': self.ROOT})
            if final != target:
                raise SourceError('Bakkin перенаправил каталог на другую страницу.')
            try:
                values = json.loads(raw)
            except (ValueError, RecursionError):
                raise SourceError('Bakkin вернул страницу вместо каталога.') from None
            if not isinstance(values, dict):
                raise SourceError('Bakkin вернул некорректный каталог.')
            rows = {}
            for row in values.values():
                if not isinstance(row, dict) or not (slug := part(row.get('dir'))) or slug in rows:
                    raise SourceError('Bakkin вернул некорректный или повторяющийся ID.')
                rows[slug] = row
            self.cache = (time.monotonic() + 60, rows)
            return rows

    def row(self, slug, data):
        from manga_sources import title_aliases
        from manga_source_tags import unique

        label = data.get('name') or unquote(slug)
        url = self.ROOT + 'series/' + slug
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'sourceId': self.SOURCE_ID,
                'sourceUrl': url, 'sourceURL': url, 'url': url, 'title': label[:500], 'aliases': title_aliases(label),
                'language': self.LANGUAGE, 'kind': 'manga', 'sourceOnly': True, 'ids': {},
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME,
                'cover': self.asset(data.get('thumb') or 'static/nocover.png'), 'authors': unique([data.get('author')]),
                'status': (data.get('status') or '').casefold(), 'genres': [], 'tags': []}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or page < 1 or not isinstance(query, str) or tag:
            raise SourceError('Некорректные параметры каталога Bakkin.')
        if page > 1:
            return [], False
        term = query.strip().casefold()
        cards = [self.row(slug, data) for slug, data in self.data(http).items()]
        return [row for row in cards if term in row['title'].casefold()], False

    def vocabulary(self, http):
        return []

    def lookup(self, http, slug):
        data = self.data(http).get(slug)
        if data is None:
            raise SourceError('Bakkin не нашёл выбранное произведение.')
        return data

    def details(self, http, value):
        target = self.saved_title_url(self.site_link(value))
        title = self.TITLE_PATH.fullmatch(urlsplit(target).path)
        if not title:
            raise SourceError('Некорректная ссылка на тайтл Bakkin.')
        return self.row(title[1], self.lookup(http, title[1]))

    def inspect(self, value, http):
        target = self.site_link(value)
        legacy = self.legacy(target)
        if legacy.get('m') and legacy.get('v') and legacy.get('c'):
            target = self.ROOT + f'series/{legacy["m"]}/{legacy["v"]}/{legacy["c"]}'
        path = urlsplit(target).path
        chapter = self.CHAPTER_PATH.fullmatch(path)
        if not chapter:
            target = self.saved_title_url(target)
        title = self.TITLE_PATH.fullmatch(urlsplit(target).path)
        if not (title or chapter):
            raise SourceError('Некорректная ссылка на читалку Bakkin.')
        slug = (title or chapter)[1]
        data = self.lookup(http, slug)
        row = self.row(slug, data)
        episodes, pages = [], []
        for vol_position, volume in enumerate(only_rows(data.get('volumes')), 1):
            vol_id = part(volume.get('dir'))
            if not vol_id:
                raise SourceError('Bakkin вернул некорректный ID тома.')
            for ch_position, item in enumerate(only_rows(volume.get('chapters')), 1):
                ch_id = part(item.get('dir'))
                if not ch_id:
                    raise SourceError('Bakkin вернул некорректный ID главы.')
                if chapter and (vol_id, ch_id) != (chapter[2], chapter[3]):
                    continue
                match = re.search(r'c([0-9]{1,5}(?:\.[0-9]{1,3})?)$', ch_id, re.I)
                label = (volume.get('name') or unquote(vol_id)) + ' - ' + (item.get('name') or unquote(ch_id))
                url = self.ROOT + f'series/{slug}/{vol_id}/{ch_id}'
                episodes.append({'url': url, 'title': label, 'number': float(match[1]) if match else ch_position,
                                 'season': vol_position, 'language': self.LANGUAGE, 'translator': ''})
                if chapter:
                    entries = item.get('pages')
                    if not isinstance(entries, list) or not 0 < len(entries) <= 500:
                        raise SourceError('Bakkin не предоставил полный список страниц.')
                    pages = [self.asset(image) for image in entries]
                    if not all(pages):
                        raise SourceError('Bakkin вернул некорректный адрес страницы.')
        if chapter and len(episodes) != 1:
            raise SourceError('Bakkin не нашёл главу выбранного тома.')
        return {**row, 'url': episodes[0]['url'] if chapter else row['url'], 'episodes': episodes, 'pages': pages,
                'available': bool(episodes), 'truncated': False, 'dubs': [], 'releases': [], 'translations': [],
                'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({entry['season'] for entry in episodes})]}

    def legacy(self, url):
        parts = urlsplit(url)
        if parts.path.rstrip('/') != self.prefix:
            return {}
        try:
            args = parse_qs(parts.fragment, strict_parsing=True, max_num_fields=3)
        except ValueError:
            return {}
        if not set(args) <= {'m', 'v', 'c'} or any(len(values) != 1 for values in args.values()):
            return {}
        return {key: part(value[0]) for key, value in args.items()}

    def saved_title_url(self, value):
        path = urlsplit(value).path
        if self.TITLE_PATH.fullmatch(path):
            return value
        if slug := self.legacy(value).get('m'):
            return self.ROOT + 'series/' + slug
        if path.startswith(self.prefix + '/'):
            local = path[len(self.prefix) + 1:].strip('/')
            if slug := part(local):
                return self.ROOT + 'series/' + slug
        return ''

    def saved_chapter(self, row, root, title):
        slug = self.TITLE_PATH.fullmatch(urlsplit(title).path)[1]
        actual = self.site_link(row.get('realUrl'), root)
        if self.CHAPTER_PATH.fullmatch(urlsplit(actual).path):
            return actual
        args = self.legacy(actual)
        if args.get('m') == slug and args.get('v') and args.get('c'):
            return self.ROOT + f'series/{slug}/{args["v"]}/{args["c"]}'
        stored = row.get('url')
        if isinstance(stored, str) and len(segments := stored.strip('/').split('/')) == 3:
            m, v, c = map(part, segments)
            if m == slug and v and c:
                return self.ROOT + f'series/{slug}/{v}/{c}'
        return ''


def self_hosted_root():
    configured = os.getenv('BAKKIN_SELF_HOSTED_URL', '').strip()
    if configured:
        try:
            parts = urlsplit(configured)
            if not parts.query and not parts.fragment:
                return public_url(configured, resolve_dns=False)
        except (ValueError, SourceError):
            pass
    return 'http://127.0.0.1/'


SOURCES = (
    Bakkin('2005076600562293471', 'Bakkin', 'https://bakkin.moe/reader/'),
    Bakkin('6251873330157357206', 'Bakkin Self-hosted', self_hosted_root()),
)
