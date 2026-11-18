"""Coolmic (keiyoushi ``src/en/coolmic`` at 6f345a8).

Search and rankings come from ``/api/v1/search_titles``; the title page
embeds its episodes in the ``:page-objects`` attribute of ``<title-page>``.
Only free episodes open; the others stay listed as paid (``locked``): the guest viewer gives no images for the
others. Every page is a signed JSON envelope of an AES-CBC image whose key
the site's own ``/api/v1/decryption_keys`` form releases for the guest
session (CSRF token from the home page); the key is stretched with
PBKDF2-SHA256 exactly like the extension's ``ImageInterceptor``.
"""

import base64
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from manga_direct_payloads import JsonSeries
from manga_japanese_readers import JapanesePage, packed_refs
from manga_ninth_routes import Route, register
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://coolmic.me'
API = ROOT + '/api/v1/'
CDN = 'https://en-img.coolmic.me'
CONTENT = 'en-contents.coolmic.me'
ID = r'[1-9][0-9]{0,9}'
PER = 20
SORTS = {'popular': 'like_vote', 'updated': 'newest', 'search': 'relevance'}
TOKEN = re.compile(r'[A-Za-z0-9_+/=-]{20,200}')
COOKIE = {'Cookie': 'is_mature=true'}


def route(url, method, data, headers):
    if url.netloc == 'coolmic.me':
        if method == 'POST':
            token = headers.get('X-CSRF-TOKEN', '')
            if url.path != '/api/v1/decryption_keys' or url.query or not TOKEN.fullmatch(token) or not key_body(data):
                return None
            return Route(headers={'Accept': 'application/json', 'Content-Type': 'application/json', 'X-CSRF-TOKEN': token,
                                  'X-Requested-With': 'XMLHttpRequest', 'Origin': ROOT, 'Referer': ROOT + '/'},
                         cookies=True, post=True, data=data, redirect=False)
        if method != 'GET' or data is not None:
            return None
        if url.path == '/api/v1/search_titles':
            try:
                args = dict(parse_qsl(url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=6))
            except ValueError:
                return None
            if (set(args) == {'keyword', 'page', 'per', 'search_field', 'sort'} and len(args['keyword']) <= 160
                    and re.fullmatch(r'[1-9][0-9]{0,3}', args['page']) and args['per'] == str(PER)
                    and args['search_field'] == 'all' and args['sort'] in SORTS.values()):
                return Route(headers={**COOKIE, 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                             redirect=False)
            return None
        if re.fullmatch(rf'/api/v1/viewer/comic/secure_episodes/{ID}', url.path) and not url.query:
            return Route(headers={**COOKIE, 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                         cookies=True, redirect=False)
        if (url.path == '/' or re.fullmatch(rf'/titles/{ID}', url.path)) and not url.query:
            return Route(headers={**COOKIE, 'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'}, cookies=True,
                         redirect=False)
        return None
    if (url.netloc == CONTENT and method == 'GET' and data is None
            and re.fullmatch(r'/encrypted/encrypted-image-data/[0-9/]{1,40}/[0-9]{9}-[0-9]{3}\.json', url.path)):
        return Route(headers={'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'Referer': ROOT + '/'},
                     redirect=False)
    return None


def key_body(data):
    if not isinstance(data, bytes) or len(data) > 4096:
        return False
    try:
        value = json.loads(data)
    except ValueError:
        return False
    return (isinstance(value, dict) and set(value) == {'encrypted_key', 'file_name'}
            and isinstance(value['encrypted_key'], str) and re.fullmatch(r'[A-Za-z0-9+/=]{16,2048}', value['encrypted_key'])
            and isinstance(value['file_name'], str) and re.fullmatch(r'[A-Za-z0-9_./-]{1,200}', value['file_name'])
            and data == json.dumps(value, separators=(',', ':')).encode())


register('coolmic', route)


def unwrap(page, password):
    try:
        key = hashlib.pbkdf2_hmac('sha256', password.encode(), base64.b64decode(page['salt']), int(page['iterations']), 32)
        decoder = Cipher(algorithms.AES(key), modes.CBC(base64.b64decode(page['iv']))).decryptor()
        plain = decoder.update(base64.b64decode(page['encrypted_image'])) + decoder.finalize()
        unpadder = PKCS7(128).unpadder()
        return unpadder.update(plain) + unpadder.finalize()
    except (KeyError, TypeError, ValueError):
        raise SourceError('Coolmic вернул повреждённую страницу.') from None


def csrf(http, refresh=False):
    token = getattr(http, '_coolmic_csrf', None)
    if token and not refresh:
        return token
    raw, _, _ = http.document(ROOT + '/', headers={'Referer': ROOT + '/'}, action='n9:coolmic')
    node = BeautifulSoup(raw, 'html.parser').select_one('meta[name=csrf-token][content]')
    if not node or not TOKEN.fullmatch(node['content']):
        raise SourceError('Coolmic не выдал гостевую сессию.')
    http._coolmic_csrf = node['content']
    return node['content']


@dataclass(frozen=True)
class CoolmicPage(JapanesePage):
    def fetch(self, http, referer):
        raw, _, _ = http.document(self.url, headers={'Referer': ROOT + '/'}, action='n9:coolmic')
        try:
            page = json.loads(raw)
            sealed = {'encrypted_key': page['kms_encrypted_data_key'], 'file_name': page['file_name']}
            int(page['iterations'])
        except (KeyError, TypeError, ValueError):
            raise SourceError('Coolmic изменил формат страницы.') from None
        if not 1 <= int(page['iterations']) <= 1000000:
            raise SourceError('Coolmic изменил формат страницы.')
        data = json.dumps(sealed, separators=(',', ':')).encode()
        for refresh in (False, True):
            try:
                answer, _, _ = http.document(API + 'decryption_keys', method='POST', data=data,
                                             headers={'X-CSRF-TOKEN': csrf(http, refresh)}, action='n9:coolmic')
                password = json.loads(answer)['decrypted_key']
                break
            except SourceAccessError:
                if refresh:
                    raise
            except (KeyError, TypeError, ValueError):
                raise SourceError('Coolmic не выдал ключ страницы.') from None
        if not isinstance(password, str) or not password:
            raise SourceError('Coolmic не выдал ключ страницы.')
        return unwrap(page, password)


def cover_of(title_id):
    key = str(title_id).rjust(9, '0')
    return f'{CDN}/titles/{key[:3]}/{key[:6]}/{key}/{key}_large_vertical.jpg'


class Coolmic(JsonSeries):
    def __init__(self):
        super().__init__(('5279120461134453793', 'Coolmic', 'en', ROOT, True), rf'/titles/({ID})', rf'/episodes/({ID})',
                         interval=.3)

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(re.fullmatch(ID, param(url, 'mv_title')))

    def title_for(self, url):
        return f'{ROOT}/titles/{param(url, "mv_title")}'

    def chapter_identity(self, url):
        return self.chapter_key(url)

    def saved_title_url(self, value):
        target = self.canonical(value)
        key = urlsplit(target).path.strip('/').removeprefix('titles/')
        return f'{ROOT}/titles/{key}' if re.fullmatch(ID, key) else ''

    def saved_chapter(self, row, root, title):
        # Suwayomi stored the bare episode ID.
        value = str(row.get('url') or '').strip('/').removeprefix('episodes/')
        key = self.title_key(title)
        return query_url(f'{ROOT}/episodes/{value}', mv_title=key) if re.fullmatch(ID, value) and key else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and param(target, 'mv_title') == self.title_key(title)

    def read(self, http, url, **headers):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, _ = http.document(url, headers={'Referer': ROOT + '/', **headers}, action='n9:coolmic')
        return raw

    def api(self, http, url):
        try:
            return json.loads(self.read(http, url))
        except ValueError:
            raise SourceError('Coolmic изменил формат API.') from None

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag:
            return [], False
        order = SORTS['search'] if query else SORTS['updated' if sort == 'updated' else 'popular']
        data = self.api(http, query_url(API + 'search_titles', keyword=query, page=str(page), per=str(PER),
                                        search_field='all', sort=order))
        items = data.get('results') if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SourceError('Coolmic изменил формат каталога.')
        rows = []
        for item in items:
            if not isinstance(item, dict) or type(item.get('title_id')) is not int or not isinstance(item.get('title_name'), str):
                continue
            row = self.record(f'{ROOT}/titles/{item["title_id"]}', item['title_name'].strip(), cover_of(item['title_id']),
                              description=str(item.get('title_summary') or ''),
                              genres=[*(item.get('genre_name') or []), *(item.get('sub_genre_name') or [])],
                              tags=item.get('tag') or [], authors=item.get('artist_name') or [])
            row['adult'] = bool(item.get('is_mature'))
            rows.append(row)
        total = data.get('total')
        return rows, type(total) is int and page * PER < total

    def series(self, http, url):
        key = self.title_key(url)
        doc = BeautifulSoup(self.read(http, f'{ROOT}/titles/{key}'), 'html.parser')
        node = doc.select_one('title-page[\\:page-objects]')
        try:
            data = json.loads(node[':page-objects'])
            title, episodes = data['title'], data['episodes']
        except (KeyError, TypeError, ValueError):
            raise SourceError('Coolmic изменил формат карточки.') from None
        if not isinstance(title, dict) or str(title.get('id')) != key or not isinstance(episodes, list):
            raise SourceError('Coolmic вернул карточку другого тайтла.')
        names = lambda field: [item.get('name') for item in title.get(field) or [] if isinstance(item, dict)]
        description = str(title.get('summary') or '')
        if title.get('agency'):
            description += f'\n\nPublisher: {title["agency"]}'
        cover = str(title.get('vertical_thumbnail_url') or '').replace('_vertical.jpg', '_large_vertical.jpg')
        row = self.record(f'{ROOT}/titles/{key}', str(title.get('name') or '').strip(), cover or cover_of(key),
                          description=description.strip(), genres=[*names('genres'), *names('sub_genres')],
                          tags=names('tags'), authors=names('artists'),
                          status='completed' if title.get('is_completed') else 'ongoing')
        if not row['title']:
            raise SourceError('Coolmic не предоставил карточку тайтла.')
        row['adult'] = bool(title.get('is_mature'))
        chapters = {}
        for item in episodes:
            if not isinstance(item, dict) or type(item.get('id')) is not int:
                continue
            if item.get('is_closed'):
                continue
            date = ''
            try:
                date = datetime.strptime(str(item.get('start_at') or ''), '%m/%d/%y').date().isoformat()
            except ValueError:
                pass
            order = item.get('display_order')
            target = query_url(f'{ROOT}/episodes/{item["id"]}', mv_title=key)
            chapters[target] = {**self.chapter(target, f'Chapter {item.get("number") or order}',
                                               float(order) if type(order) is int else None, date), 'season': 1,
                                'locked': item.get('is_free') is not True}
        return row, self.order(chapters)

    def pages(self, http, url):
        data = self.api(http, f'{API}viewer/comic/secure_episodes/{self.chapter_key(url)}')
        images = data.get('image_data') if isinstance(data, dict) else None
        if not images:
            raise SourceAccessError('Эпизод Coolmic доступен только после покупки.')
        rows = []
        for image in sorted((item for item in images if isinstance(item, dict)), key=lambda item: item.get('num', 0)):
            link = image.get('path')
            if not isinstance(link, str) or urlsplit(link).netloc != CONTENT or not route(urlsplit(link), 'GET', None, {}):
                raise SourceError('Coolmic изменил адрес страниц.')
            rows.append(CoolmicPage(link))
        return packed_refs(rows, url)


SOURCES = (Coolmic(),)
