"""emaqi (keiyoushi ``src/en/emaqi`` at 6f345a8).

The site's GraphQL API answers guests with the home sections, search,
series data and the contents of free chapters, free volumes and the trial
pages of a volume. A content request carries a fresh RSA public key
(``X-Hash``); the answer wraps the page key with RSA-OAEP-SHA256 and every
page is AES encrypted (CBC, or GCM when the first byte is 2) behind a 16
byte IV, decoded like the extension's ``ImageInterceptor``. Paid chapters
stay listed as ``locked``; login is not part of the guest route.
"""

import base64
from dataclasses import dataclass
import json
import re
import threading
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.padding import PKCS7
from cryptography.exceptions import InvalidTag

from manga_direct_payloads import JsonSeries
from manga_japanese_readers import JapanesePage, packed_refs
from manga_madara import image_url
from manga_ninth_routes import Route, register
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://emaqi.com'
API = 'https://api.emaqi.com/graphql'
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
SLUG = r'[a-z0-9][a-z0-9-]{0,199}'
SECTIONS = {'popular': 'this-week-s-bestsellers', 'updated': 'hot-release'}
GENRES = (
    ('death-game', 'Death Game'), ('psychological', 'Psychological'), ('boys-love', 'Boys Love'), ('suspense', 'Suspense'),
    ('military', 'Military'), ('rom-com', 'Rom-Com'), ('mystery', 'Mystery'), ('adventure', 'Adventure'),
    ('drama', 'Drama'), ('slice-of-life', 'Slice of Life'), ('girls-love', 'Girls Love'), ('sports', 'Sports'),
    ('dark-drama', 'Dark Drama'), ('sci-fi', 'Sci-Fi'), ('isekai', 'Isekai'), ('action', 'Action'),
    ('fantasy', 'Fantasy'), ('horror', 'Horror'), ('romance', 'Romance'), ('comedy', 'Comedy'),
)
GENRE_KEYS = frozenset(key for key, _ in GENRES)
SEARCH_LIMIT = 50
HOME_PAGES = 10
MAX_IMAGE = 30 * 1024 * 1024

QUERIES = {
    'FetchHomeSection': '''query FetchHomeSection($slug: String!, $mangaAfter: String) {
  homeSection(slug: $slug) {
    mangaConn(first: 40, after: $mangaAfter) {
      edges {
        node {
          comic {
            comicId
            slug
            title
            cover {
              url
            }
          }
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}''',
    'Search': '''query Search($input: SearchInput!) {
  search(input: $input) {
    comicId
    slug
    title
    cover {
      url
    }
  }
}''',
    'FetchComicData': '''query FetchComicData($comicId: String!) {
  comicVolumes(comicId: $comicId) {
    comic {
      slug
      title
      synopsis
      rating
      creators
      publisher
      completed
      cover {
        url
      }
      genres {
        ... on Tag {
          name
        }
      }
    }
    volumes {
      comicId
      volumeNumber
      eisbn
      slug
      name
      trialPage
      purchased
      free
      releasesAt
    }
  }
  chapters(comicId: $comicId) {
    comicId
    chapterNumber
    name
    purchased
    free
    releasesAt
  }
}''',
    'FetchChapterContents': '''query FetchChapterContents($comicId: String!, $chapterNumber: Int!) {
  chapter(comicId: $comicId, chapterNumber: $chapterNumber) {
    contents {
      pages {
        url
      }
      hash
    }
  }
}''',
    'FetchMangaContents': '''query FetchMangaContents($comicId: String!, $volumeNumber: Int!) {
  manga(comicId: $comicId, volumeNumber: $volumeNumber) {
    contents {
      pages {
        url
      }
      hash
    }
  }
}''',
}
CONTENTS = {'FetchChapterContents', 'FetchMangaContents'}
HASH = re.compile(r'[A-Za-z0-9+/]{390,420}={0,2}')


def body(operation, variables):
    return json.dumps({'query': QUERIES[operation], 'operationName': operation, 'variables': variables},
                      separators=(',', ':')).encode()


def number(value, high=100000):
    return type(value) is int and 0 <= value <= high


def accepted_variables(operation, values):
    if not isinstance(values, dict):
        return False
    if operation == 'FetchHomeSection':
        after = values.get('mangaAfter')
        return (set(values) == {'slug', 'mangaAfter'} and values['slug'] in SECTIONS.values()
                and (after is None or isinstance(after, str) and re.fullmatch(r'[A-Za-z0-9+/=_-]{1,200}', after)))
    if operation == 'Search':
        data = values.get('input')
        return (set(values) == {'input'} and isinstance(data, dict)
                and set(data) == {'keyword', 'tagSlugGroups', 'page', 'limit'} and isinstance(data['keyword'], str)
                and len(data['keyword']) <= 160 and number(data['page'], 2000) and data['page'] >= 1
                and data['limit'] == SEARCH_LIMIT and isinstance(data['tagSlugGroups'], list)
                and len(data['tagSlugGroups']) <= 1
                and all(isinstance(group, dict) and set(group) == {'tagSlugs'} and group['tagSlugs'] in [[key] for key in GENRE_KEYS]
                        for group in data['tagSlugGroups']))
    if not re.fullmatch(UUID, str(values.get('comicId', ''))):
        return False
    if operation == 'FetchComicData':
        return set(values) == {'comicId'}
    if operation == 'FetchChapterContents':
        return set(values) == {'comicId', 'chapterNumber'} and number(values['chapterNumber'])
    return set(values) == {'comicId', 'volumeNumber'} and number(values['volumeNumber'])


def accepted_body(data, headers):
    if not isinstance(data, bytes) or len(data) > 4096:
        return False
    try:
        request = json.loads(data)
    except ValueError:
        return False
    if not isinstance(request, dict) or set(request) != {'query', 'operationName', 'variables'}:
        return False
    operation = request['operationName']
    if operation not in QUERIES or request['query'] != QUERIES[operation]:
        return False
    if operation in CONTENTS and not HASH.fullmatch(headers.get('X-Hash', '')):
        return False
    return accepted_variables(operation, request['variables']) and data == body(operation, request['variables'])


def route(url, method, data, headers):
    if url.netloc != 'api.emaqi.com' or url.path != '/graphql' or url.query or method != 'POST':
        return None
    if not accepted_body(data, headers):
        return None
    extra = {'X-Hash': headers['X-Hash']} if headers.get('X-Hash') else {}
    return Route(headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'Origin': ROOT,
                          'Referer': ROOT + '/', **extra}, post=True, data=data, redirect=False)


register('emaqi', route)


class Keys:
    """One RSA key pair per process, like the extension's lazy key pair."""

    lock = threading.Lock()
    private = None

    @classmethod
    def get(cls):
        with cls.lock:
            if cls.private is None:
                cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            return cls.private

    @classmethod
    def public(cls):
        der = cls.get().public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        return base64.b64encode(der).decode()

    @classmethod
    def unwrap(cls, value):
        try:
            return cls.get().decrypt(base64.b64decode(value), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                                                           algorithm=hashes.SHA256(), label=None))
        except ValueError:
            raise SourceError('emaqi изменил формат ключа страниц.') from None


def decrypt(raw, key):
    try:
        if raw[:1] == b'\x02':
            iv, sealed = raw[2:18], raw[18:]
            return AESGCM(key).decrypt(iv, sealed, None)
        iv, sealed = raw[:16], raw[16:]
        decoder = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        plain = decoder.update(sealed) + decoder.finalize()
        unpadder = PKCS7(128).unpadder()
        return unpadder.update(plain) + unpadder.finalize()
    except (InvalidTag, ValueError):
        raise SourceError('emaqi вернул повреждённую страницу.') from None


@dataclass(frozen=True)
class EmaqiPage(JapanesePage):
    def fetch(self, http, referer):
        from manga_page_media import read_image

        response, _ = http._open(self.url, headers={'Referer': ROOT + '/'})
        return decrypt(read_image(http, response), self.key)


class Emaqi(JsonSeries):
    def __init__(self):
        super().__init__(('3383118804501081522', 'emaqi', 'en', ROOT, True), rf'/manga/({SLUG})', rf'/reader/({SLUG})',
                         interval=.3)
        self.cursors = {}
        self.cursor_lock = threading.Lock()

    def is_title(self, url):
        return super().is_title(url) and bool(re.fullmatch(UUID, param(url, 'mv_comic')))

    def is_chapter(self, url):
        kind = param(url, 'type')
        index = param(url, 'chapter' if kind == 'chapter' else 'volume')
        return (super().is_chapter(url) and bool(re.fullmatch(UUID, param(url, 'mv_comic')))
                and kind in {'chapter', 'volume'} and bool(re.fullmatch(r'[0-9]{1,5}', index)))

    def title_url(self, slug, comic):
        return query_url(f'{ROOT}/manga/{slug}', mv_comic=comic)

    def title_for(self, url):
        return self.title_url(self.chapter_key(url), param(url, 'mv_comic'))

    def title_identity(self, value):
        return param(value, 'mv_comic') or super().title_identity(value)

    def chapter_identity(self, url):
        kind = param(url, 'type')
        return param(url, 'mv_comic'), kind, param(url, 'chapter' if kind == 'chapter' else 'volume')

    def saved_title_url(self, value):
        target = self.canonical(value)
        if self.is_title(target):
            return target
        # Suwayomi stored the bare comic ID ("<id>#<slug>" in older versions).
        comic = urlsplit(target).path.strip('/')
        return self.title_url(comic, comic) if re.fullmatch(UUID, comic) else ''

    def saved_chapter(self, row, root, title):
        comic = param(title, 'mv_comic')
        real = str(row.get('realUrl') or '')
        value = str(row.get('url') or '')
        slug = self.title_key(title)
        if not comic:
            return ''
        found = re.search(r'[?&]chapter=([0-9]{1,5})(?:&|$)', real)
        if found or re.fullmatch(r'[0-9]{1,5}', value) and 'type=chapter' in real:
            return query_url(f'{ROOT}/reader/{slug}', type='chapter', chapter=found[1] if found else value, mv_comic=comic)
        if re.fullmatch(r'[0-9]{1,4}', value):
            return query_url(f'{ROOT}/reader/{slug}', type='volume', volume=value, mv_comic=comic)
        return ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and param(target, 'mv_comic') == param(title, 'mv_comic')

    def call(self, http, operation, variables, headers=None):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, _ = http.document(API, method='POST', data=body(operation, variables), headers=headers or {},
                                  action='n9:emaqi')
        try:
            data = json.loads(raw)
        except ValueError:
            raise SourceError('emaqi изменил формат API.') from None
        if not isinstance(data, dict) or not isinstance(data.get('data'), dict):
            raise SourceError('emaqi изменил формат API.')
        return data['data']

    def comic_row(self, comic, **extra):
        if not isinstance(comic, dict) or not re.fullmatch(UUID, str(comic.get('comicId', ''))):
            return None
        if not re.fullmatch(SLUG, str(comic.get('slug', ''))) or not isinstance(comic.get('title'), str):
            return None
        cover = (comic.get('cover') or {}).get('url') if isinstance(comic.get('cover'), dict) else ''
        return self.record(self.title_url(comic['slug'], comic['comicId']), comic['title'].strip(),
                           image_url(cover, ROOT), **extra)

    def home(self, http, section, page):
        after = None
        for index in range(1, page + 1):
            with self.cursor_lock:
                cached = self.cursors.get((section, index))
            if cached is not None and index < page:
                after = cached
                continue
            data = self.call(http, 'FetchHomeSection', {'slug': section, 'mangaAfter': after})
            conn = ((data.get('homeSection') or {}).get('mangaConn') or {}) if isinstance(data.get('homeSection'), dict) else {}
            info = conn.get('pageInfo') if isinstance(conn, dict) else None
            if not isinstance(info, dict) or not isinstance(conn.get('edges'), list):
                raise SourceError('emaqi изменил формат каталога.')
            if index == page:
                rows = [row for edge in conn['edges'] if isinstance(edge, dict)
                        if (row := self.comic_row(((edge.get('node') or {}).get('comic'))))]
                return rows, bool(info.get('hasNextPage'))
            if not info.get('hasNextPage') or not isinstance(info.get('endCursor'), str):
                return [], False
            after = info['endCursor']
            with self.cursor_lock:
                self.cursors[(section, index)] = after
                while len(self.cursors) > 64:
                    self.cursors.pop(next(iter(self.cursors)))
        return [], False

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and tag not in GENRE_KEYS:
            return [], False
        if query or tag:
            groups = [{'tagSlugs': [tag]}] if tag else []
            data = self.call(http, 'Search', {'input': {'keyword': query, 'tagSlugGroups': groups, 'page': page,
                                                        'limit': SEARCH_LIMIT}})
            items = data.get('search')
            if not isinstance(items, list):
                raise SourceError('emaqi изменил формат поиска.')
            rows = [row for item in items if (row := self.comic_row(item))]
            return rows, len(items) == SEARCH_LIMIT
        if page > HOME_PAGES:
            return [], False
        return self.home(http, SECTIONS['updated' if sort == 'updated' else 'popular'], page)

    def vocabulary(self, http):
        return [{'key': key, 'label': label, 'kind': 'genre'} for key, label in GENRES]

    def series(self, http, url):
        comic = param(url, 'mv_comic')
        if not re.fullmatch(UUID, comic):
            raise SourceError('Некорректная ссылка на тайтл emaqi.')
        data = self.call(http, 'FetchComicData', {'comicId': comic})
        volumes = data.get('comicVolumes') if isinstance(data.get('comicVolumes'), dict) else {}
        details = volumes.get('comic')
        if not isinstance(details, dict):
            raise SourceError('emaqi не предоставил карточку тайтла.')
        genres = [item.get('name') for item in details.get('genres') or [] if isinstance(item, dict)]
        description = str(details.get('synopsis') or '')
        if details.get('publisher'):
            description += f'\n\nPublisher: {details["publisher"]}'
        row = self.comic_row({**details, 'comicId': comic}, description=description.strip(), genres=genres,
                             authors=[name for name in details.get('creators') or [] if isinstance(name, str)],
                             status='completed' if details.get('completed') else 'ongoing')
        if row is None:
            raise SourceError('emaqi не предоставил карточку тайтла.')
        if type(details.get('rating')) is int and details['rating'] >= 18:
            row['adult'] = True
        slug = self.title_key(row['url'])
        chapters = {}
        for item in data.get('chapters') or []:
            if not isinstance(item, dict) or not number(item.get('chapterNumber')):
                continue
            n = item['chapterNumber']
            target = query_url(f'{ROOT}/reader/{slug}', type='chapter', chapter=str(n), mv_comic=comic)
            chapters[target] = {**self.chapter(target, str(item.get('name') or f'Chapter {n}'), float(n),
                                               str(item.get('releasesAt') or '')[:10]), 'season': 1,
                                'locked': not item.get('free')}
        for item in volumes.get('volumes') or []:
            if not isinstance(item, dict) or not number(item.get('volumeNumber')):
                continue
            trial = type(item.get('trialPage')) is int and item['trialPage'] > 0
            n = item['volumeNumber']
            name = str(item.get('name') or '') or 'Oneshot'
            target = query_url(f'{ROOT}/reader/{slug}', type='volume', volume=str(n), mv_comic=comic)
            # Volumes follow the chapters, like the extension's list.
            chapters[target] = {**self.chapter(target, name if item.get('free') else f'(Preview) {name}', float(n),
                                               str(item.get('releasesAt') or '')[:10]), 'season': 2,
                                'locked': not item.get('free') and not trial}
        return row, self.order(chapters)

    def pages(self, http, url):
        comic, kind, index = self.chapter_identity(url)
        if kind == 'chapter':
            data = self.call(http, 'FetchChapterContents', {'comicId': comic, 'chapterNumber': int(index)},
                             {'X-Hash': Keys.public()})
            contents = (data.get('chapter') or {}).get('contents') if isinstance(data.get('chapter'), dict) else None
        else:
            data = self.call(http, 'FetchMangaContents', {'comicId': comic, 'volumeNumber': int(index)},
                             {'X-Hash': Keys.public()})
            contents = (data.get('manga') or {}).get('contents') if isinstance(data.get('manga'), dict) else None
        pages = contents.get('pages') if isinstance(contents, dict) else None
        if not pages or not isinstance(contents.get('hash'), str):
            raise SourceAccessError('Глава emaqi доступна только после покупки.')
        key = Keys.unwrap(contents['hash'])
        if len(key) not in {16, 24, 32}:
            raise SourceError('emaqi изменил формат ключа страниц.')
        rows = []
        for page in pages:
            link = page.get('url') if isinstance(page, dict) else None
            target = urlsplit(link or '')
            if target.scheme != 'https' or target.netloc != 'pr.emaqi.com' or not target.path.startswith('/contents/'):
                raise SourceError('emaqi изменил адрес страниц.')
            rows.append(EmaqiPage(link, key))
        return packed_refs(rows, url)


SOURCES = (Emaqi(),)
