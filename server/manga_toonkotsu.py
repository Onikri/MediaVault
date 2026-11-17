"""Toonkotsu browse feeds, scanlation variants and published encrypted page files."""

import re
from base64 import urlsafe_b64decode
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from manga_direct_payloads import JsonSeries, strings
from manga_dynasty import entries
from manga_madara import SEGMENT, image_url
from manga_rayuba import uploaded
from manga_series_port import number
from manga_speedbinb import remember
from manga_webcomics import query_url
from source_parser import SourceError

ROOT = 'https://toonkotsu.com'
HOST = 'toonkotsu.com'
HID = r'[a-z][0-9a-z]{4}'
ID = r'[1-9]\d{0,17}'
TITLE = rf'/title/({HID})(?:-{SEGMENT})?/?'
CHAPTER = rf'/title/({HID})(?:-{SEGMENT})?/({ID})/?'
BASE64 = re.compile(r'[A-Za-z0-9_-]{12,43}={0,2}')


def public_api(host, path, query):
    if host != HOST:
        return False
    if re.fullmatch(rf'/cdn/v1/series/{HID}|/api/manga/chapter/{ID}', path):
        return not query
    if path == '/cdn/v1/facets':
        return query == 'sfw=0'
    pairs = parse_qsl(query)
    args = dict(pairs)
    base = {'page', 'limit', 'sfw'}
    if (len(args) != len(pairs) or not base <= set(args) or args['sfw'] != '1'
            or not re.fullmatch(r'[1-9]\d{0,3}', args['page'])):
        return False
    if path == '/cdn/v1/latest':
        return set(args) == base and args['limit'] == '70'
    if path != '/cdn/v1/browse' or not base | {'sort', 'order'} <= set(args) <= base | {'sort', 'order', 'q', 'genres'}:
        return False
    return (args['limit'] == '42' and args['sort'] in {'popular', 'relevance'} and args['order'] == 'desc'
            and all(len(args[key]) <= 160 for key in ('q', 'genres') if key in args))


def b64(value):
    return urlsafe_b64decode(value + '=' * (-len(value) % 4)) if isinstance(value, str) and BASE64.fullmatch(value) else b''


@dataclass(frozen=True)
class EncryptedPage:
    key: bytes
    nonce: bytes

    def decode(self, raw):
        reader = Cipher(algorithms.AES(self.key), modes.CTR(self.nonce)).decryptor()
        return reader.update(raw) + reader.finalize()


class Toonkotsu(JsonSeries):
    def __init__(self):
        super().__init__(('3504033188132514684', 'Toonkotsu', 'en', ROOT, True), TITLE, CHAPTER,
                         hosts=('www.toonkotsu.com',), interval=.35)

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + '/title/' + key if key else ''

    def chapter_identity(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return match.groups() if match else ('', '')

    def row_for(self, obj):
        code, name = obj.get('hid'), obj.get('title')
        if not isinstance(code, str) or not re.fullmatch(HID, code) or not isinstance(name, str) or not name:
            return None
        url = ROOT + '/title/' + code
        cover = image_url(obj.get('cover'), ROOT + '/')
        if cover:
            cover = cover.rsplit('/', 1)[0] + '/720.webp'
        title_map = obj.get('titles') or {}
        aliases = strings(obj.get('alt')) + [value for value in title_map.values() if isinstance(value, str)]
        tags = [value for value in strings(obj.get('tags')) if value not in strings(obj.get('spoilerTags'))]
        state = {'Ongoing': 'ongoing', 'Complete': 'completed', 'Hiatus': 'hiatus', 'Canceled': 'cancelled'}
        row = self.record(url, name, cover, aliases=aliases, authors=strings(obj.get('authors')), tags=tags,
                          description=str(obj.get('description') or ''), status=state.get(obj.get('status'), ''))
        kind = str(obj.get('type', '')).casefold()
        if kind in {'manga', 'manhwa', 'manhua', 'webtoon', 'comic'}:
            row['format'] = kind
        if type(obj.get('year')) is int:
            row['year'] = obj['year']
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        latest = sort == 'updated' and not query and not tag
        if latest:
            url = query_url(ROOT + '/cdn/v1/latest', page=page, limit=70, sfw=1)
        else:
            url = query_url(ROOT + '/cdn/v1/browse', page=page, limit=42, sfw=1, order='desc',
                            sort='relevance' if query else 'popular', q=query or [], genres=tag[:160] or [])
        body = self.json(http, url)
        rows = {}
        for item in entries(body.get('items')):
            data = item.get('series') if latest else item
            if isinstance(data, dict) and (row := self.row_for(data)):
                rows[row['url']] = row
        return list(rows.values()), bool(body.get('hasNextPage'))

    def vocabulary(self, http):
        data = self.json(http, ROOT + '/cdn/v1/facets?sfw=0')
        return [{'key': tag['name'], 'label': tag['name'], 'kind': 'tag' if tag.get('category') else 'genre'}
                for tag in entries(data.get('genres')) if isinstance(tag.get('name'), str) and tag['name']]

    def series(self, http, url):
        key = self.title_key(url)
        data = self.json(http, ROOT + '/cdn/v1/series/' + key)
        meta = data.get('series') or {}
        row = self.row_for(meta)
        if not row or meta.get('hid') != key:
            raise SourceError('Toonkotsu вернул другой тайтл.')
        candidates = []
        for item in entries(data.get('chapters')):
            candidates.append((item, False))
            candidates.extend(({**item, **alt, 'group': alt.get('group') or item.get('group')}, True)
                              for alt in entries(item.get('alts')))
        episodes = {}
        for item, alternate in candidates:
            identifier = str(item.get('id') or '')
            if not re.fullmatch(ID, identifier):
                continue
            target = ROOT + f'/title/{key}/{identifier}'
            n, volume = number(item.get('n')), number(item.get('vol'))
            group = item.get('group') or {}
            note = [str(item['src'])] if alternate and item.get('src') else []
            if item.get('partial'):
                note.append('incomplete')
            translator = str(group.get('name') or '')
            if note and translator:
                translator += ' (' + ', '.join(note) + ')'
            label = str(item.get('label') or '')
            episodes[target] = self.chapter(target, label, n, uploaded(item.get('at')),
                                            int(volume) if volume and volume >= 1 else None, translator)
        return row, self.order(episodes)

    def pages(self, http, url):
        identifier = self.chapter_identity(url)[1]
        data = self.json(http, ROOT + '/api/manga/chapter/' + identifier, url)
        refs = []
        for page in entries((data.get('chapter') or {}).get('pages')):
            target = image_url(page.get('src'), ROOT + '/')
            parts = urlsplit(target)
            if parts.netloc != HOST or not parts.path.startswith('/cdn/e/'):
                raise SourceError('Toonkotsu вернул неизвестный адрес страницы.')
            try:
                key, nonce = b64(page.get('k')), b64(page.get('n'))
            except ValueError:
                raise SourceError('Toonkotsu вернул некорректный формат страницы.') from None
            if len(key) not in (16, 24, 32) or not 8 <= len(nonce) <= 16:
                raise SourceError('Toonkotsu вернул некорректный формат страницы.')
            refs.append((target, EncryptedPage(key, nonce.ljust(16, b'\0'))))
        return remember(refs, url)


SOURCES = (Toonkotsu(),)
