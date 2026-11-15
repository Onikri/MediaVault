"""Public MangaHub reader protocol shared by the Keiyoushi MangaHub family."""

import base64
from decimal import Decimal, InvalidOperation
import json
import re
import secrets
import threading
import time
from urllib.parse import urljoin, urlsplit

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from manga_source_tags import unique
from source_parser import SourceAccessError, SourceError, SourceTemporaryError, USER_AGENT, public_url


THUMBNAILS = 'https://thumb.mghcdn.com/'
IMAGES = 'https://imgx.mghcdn.com/'
TITLE_PATH = re.compile(r'/manga/([\w-]{1,180})/?')
CHAPTER_PATH = re.compile(r'/chapter/([\w-]{1,180})/chapter-(\d{1,4}(?:\.\d{1,4})?)/?')
PACE = threading.Lock()
NEXT_REQUEST = 0.0


def pace(deadline):
    global NEXT_REQUEST
    with PACE:
        now = time.monotonic()
        scheduled = max(now, NEXT_REQUEST)
        if deadline is not None and scheduled >= deadline:
            raise SourceTemporaryError('MangaHub: достигнут лимит времени запроса.')
        NEXT_REQUEST = scheduled + 0.25
    if scheduled > now:
        time.sleep(scheduled - now)


def quote(value):
    return json.dumps(value, ensure_ascii=False)


def decode_b64(value):
    return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)


def decode_pages(value, parameters):
    version, key_id, iv, tag, ciphertext = value.removeprefix('enc:').split(':', 4)
    if version != 'v1':
        raise SourceError('MangaHub изменил формат списка страниц.')
    key = (parameters.get('keys') or {}).get(key_id)
    if not key and parameters.get('keyId') in {None, key_id}:
        key = parameters.get('key')
    if not key:
        raise SourceError('MangaHub не вернул параметры открытого ридера.')
    try:
        return AESGCM(decode_b64(key)).decrypt(
            decode_b64(iv), decode_b64(ciphertext) + decode_b64(tag), None,
        ).decode()
    except (InvalidTag, ValueError, UnicodeError):
        raise SourceError('MangaHub вернул повреждённый список страниц.') from None


def chapter_number(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise SourceError('MangaHub вернул некорректный номер главы.') from None
    if not number.is_finite() or number < 0 or number > 9999 or number.as_tuple().exponent < -4:
        raise SourceError('MangaHub вернул некорректный номер главы.')
    return number


class MangaHub:
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    LANGUAGE = 'en'
    IS_NSFW = True  # The catalogue includes titles with age restrictions.

    def __init__(self, sid, name, host, channel):
        self.SOURCE_ID = sid
        self.NAME = name
        self.HOST = host
        self.ROOT = 'https://' + host
        self.channel = channel
        self.guest = secrets.token_hex(16)
        self.page_guest_ready = False
        self.lock = threading.Lock()

    def site_link(self, value, base=None):
        if not value:
            return ''
        url = urljoin(base or self.ROOT, value)
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != self.HOST:
            return ''
        return public_url(url, resolve_dns=False)

    def saved_chapter_url(self, value, title, root):
        path = urlsplit(value or '')
        if not path.netloc and path.path.startswith('/' + title + '/chapter-'):
            value = '/chapter' + path.path
        return self.site_link(value, root)

    def request(self, http, path, key, *, query=None, referer=None, refresh=False):
        if path not in {'/graphql', '/api/chapter-crypto'} and not (
            TITLE_PATH.fullmatch(path) or CHAPTER_PATH.fullmatch(path)
        ):
            raise SourceError('Недопустимый маршрут MangaHub.')
        pace(http.deadline)
        url = public_url(self.ROOT + path + ('?reloadKey=1' if refresh else ''), allow_api=True)
        headers = {
            'User-Agent': USER_AGENT, 'Referer': referer or self.ROOT + '/', 'DNT': '1',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept': 'application/json' if query or path.startswith('/api/') else 'text/html',
        }
        if query is not None or path.startswith('/api/'):
            headers.update({'Origin': self.ROOT, 'x-mhub-access': key})
        options = {'json': {'query': query}} if query is not None else {}
        try:
            http.session.cookies.clear()
            return http.session.request(
                'POST' if query is not None else 'GET', url, headers=headers, cookies={'mhub_access': key},
                allow_redirects=False, stream=True, timeout=http.timeout, **options,
            )
        except requests.RequestException:
            raise SourceTemporaryError('MangaHub временно не отвечает.') from None

    def payload(self, http, path, key, query=None):
        with self.request(http, path, key, query=query) as response:
            if response.status_code in {401, 403} or 300 <= response.status_code < 400:
                raise SourceAccessError('Источник MangaHub ограничивает доступ к этому маршруту.')
            if response.status_code != 200:
                raise SourceTemporaryError(f'MangaHub вернул HTTP {response.status_code}.')
            if 'json' not in response.headers.get('Content-Type', '').lower():
                raise SourceError('MangaHub вернул HTML вместо ответа API.')
            data = bytearray()
            try:
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > 4 * 1024 * 1024 or http.deadline and time.monotonic() >= http.deadline:
                        raise SourceTemporaryError('MangaHub: превышен лимит ответа API.')
                result = json.loads(data)
            except (ValueError, requests.RequestException):
                raise SourceError('MangaHub вернул некорректный ответ API.') from None
            if not isinstance(result, dict):
                raise SourceError('MangaHub изменил формат ответа API.')
            return result

    def graphql(self, http, query, refresh_path='', *, with_key=False):
        old_key = self.guest
        key = old_key
        result = self.payload(http, '/graphql', old_key, query)
        errors = result.get('errors') or []
        if (errors and refresh_path
            and any(re.search(r'api\s*key|encryption', str(item.get('message', '')), re.I) for item in errors if isinstance(item, dict))):
            with self.lock:
                if self.guest == old_key:
                    self.refresh_guest(http, refresh_path)
            if self.guest != old_key:
                key = self.guest
                result = self.payload(http, '/graphql', key, query)
        if result.get('errors') or not isinstance(result.get('data'), dict):
            if any('rate limit' in str(item.get('message', '')).lower() for item in result.get('errors') or [] if isinstance(item, dict)):
                raise SourceTemporaryError('MangaHub ограничил частоту запросов.')
            raise SourceError('MangaHub не предоставил данные для этого запроса.')
        return (result['data'], key) if with_key else result['data']

    def refresh_guest(self, http, path):
        match = CHAPTER_PATH.fullmatch(path)
        referer = self.ROOT + ('/manga/' + match[1] if match else path)
        with self.request(http, path, self.guest, refresh=True, referer=referer) as response:
            candidate = response.cookies.get('mhub_access', '')
            # Sites can issue the guest cookie before redirecting the reader.
            # Consume only this origin's cookie without following the redirect.
            if 200 <= response.status_code < 400 and re.fullmatch(r'[A-Za-z0-9_.~-]{8,128}', candidate):
                self.guest = candidate
                if match:
                    self.page_guest_ready = True

    def row(self, slug, title, image=''):
        from manga_sources import title_aliases
        url = f'{self.ROOT}/manga/{slug}'
        try:
            cover = public_url(urljoin(THUMBNAILS, image), resolve_dns=False) if image else ''
        except SourceError:
            cover = ''
        return {
            'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'provider': 'suwayomi:' + self.SOURCE_ID,
            'providerName': self.NAME, 'sourceId': self.SOURCE_ID,
            'sourceUrl': url, 'sourceURL': url, 'url': url, 'kind': 'manga', 'language': self.LANGUAGE,
            'title': title[:500], 'aliases': title_aliases(title), 'cover': cover, 'sourceOnly': True, 'ids': {},
        }

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        order = {'popular': 'POPULAR', 'updated': 'LATEST'}[sort]
        expression = (
            '{search(x: '+self.channel+', q: '+quote(query)+', genre: '+quote(tag or 'all')
            + f', mod: {order}, hideNSFW: false, hideYaoi: false, offset: {(page - 1) * 30})'
            + ' {rows {title slug image}}}'
        )
        payload = self.graphql(http, expression)
        search = payload.get('search')
        values = search.get('rows') if isinstance(search, dict) else None
        if not isinstance(values, list):
            raise SourceError('MangaHub изменил формат выдачи каталога.')
        rows = [self.row(item['slug'], item['title'], item.get('image') or '') for item in values
                if isinstance(item, dict) and re.fullmatch(r'[\w-]{1,180}', str(item.get('slug') or ''))
                and isinstance(item.get('title'), str) and item['title'].strip()]
        return rows, len(values) == 30

    def vocabulary(self, http):
        values = self.graphql(http, '{genres {title slug group}}').get('genres')
        if not isinstance(values, list):
            raise SourceError('MangaHub изменил формат справочника.')
        return [{'label': item['title'], 'sourceId': item['slug'],
                 'category': 'genre' if item.get('group') == 'Genre' else 'tag'}
                for item in values if isinstance(item, dict) and item.get('title') and item.get('slug')]

    def title(self, http, slug):
        expression = ('{manga(x: '+self.channel+', slug: '+quote(slug)
                      + ') {title slug status image author artist genres description alternativeTitle chapters {number title date}}}')
        raw = self.graphql(http, expression, '/manga/' + slug).get('manga')
        if not isinstance(raw, dict) or raw.get('slug') != slug or not raw.get('title'):
            raise SourceError('Источник MangaHub не подтвердил тайтл.')
        return raw

    def metadata(self, raw):
        row = self.row(raw['slug'], raw['title'], raw.get('image') or '')
        row['aliases'] = list(dict.fromkeys([*row['aliases'], *(s.strip() for s in (raw.get('alternativeTitle') or '').split(';') if s.strip())]))
        row['description'] = (raw.get('description') or '')[:12000]
        row['author'] = raw.get('author') or ''
        row['artist'] = raw.get('artist') or ''
        row['status'] = raw.get('status') or ''
        row['genres'] = unique((raw.get('genres') or '').split(','))
        row['tags'] = []
        return row

    def details(self, http, url):
        match = TITLE_PATH.fullmatch(urlsplit(self.site_link(url)).path)
        if not match:
            raise SourceError('Некорректная ссылка на тайтл MangaHub.')
        return self.metadata(self.title(http, match[1]))

    def chapter_entry(self, slug, number, title=''):
        label = format(number.normalize(), 'f')
        title = ' '.join(title.split())
        if label not in title:
            title = 'Chapter '+label+(' - '+title if title else '')
        return {'url': f'{self.ROOT}/chapter/{slug}/chapter-{label}', 'number': float(number),
                'language': self.LANGUAGE, 'title': title, 'season': 1, 'translator': ''}

    def pages(self, http, slug, number, path):
        if not self.page_guest_ready:
            with self.lock:
                if not self.page_guest_ready:
                    self.refresh_guest(http, path)
        expression = ('{chapter(x: '+self.channel+', slug: '+quote(slug)
                      + ', number: '+format(number, 'f')+') {pages mangaID number}}')
        payload, key = self.graphql(http, expression, path, with_key=True)
        raw = payload.get('chapter')
        if not isinstance(raw, dict) or not isinstance(raw.get('pages'), str) or chapter_number(raw.get('number')) != number:
            raise SourceError('MangaHub не подтвердил опубликованную главу.')
        value = raw['pages']
        try:
            if value.startswith('enc:'):
                value = decode_pages(value, self.payload(http, '/api/chapter-crypto', key))
            data = json.loads(value)
            if isinstance(data, dict):
                data = [data.get('p', '') + part for part in data['i']] if 'i' in data else list(data.values())
            if not isinstance(data, list) or not 0 < len(data) <= 500 or any(not isinstance(url, str) or not url for url in data):
                raise ValueError
            return [public_url(urljoin(IMAGES, url), resolve_dns=False) for url in data]
        except (TypeError, ValueError):
            raise SourceError('MangaHub изменил формат списка страниц.') from None

    def inspect(self, url, http):
        path = urlsplit(self.site_link(url)).path
        title_match, chapter_match = TITLE_PATH.fullmatch(path), CHAPTER_PATH.fullmatch(path)
        if not (title_match or chapter_match):
            raise SourceError('Некорректная ссылка на главу или тайтл MangaHub.')
        if chapter_match:
            slug, text_number = chapter_match.groups()
            number = chapter_number(text_number)
            pages = self.pages(http, slug, number, path)
            episodes = [self.chapter_entry(slug, number)]
            row = self.row(slug, slug.replace('-', ' '))
            truncated = False
        else:
            raw = self.title(http, title_match[1])
            row = self.metadata(raw)
            values = raw.get('chapters')
            if not isinstance(values, list):
                raise SourceError('MangaHub изменил формат списка глав.')
            episodes = [self.chapter_entry(raw['slug'], chapter_number(item['number']), item.get('title') or '')
                        for item in values[:1500]]
            episodes.sort(key=lambda item: item['number'])
            pages = []
            truncated = len(values) > 1500
        return {**row, 'url': url, 'episodes': episodes, 'pages': pages, 'truncated': truncated,
                'seasons': [{'number': 1, 'name': 'Том 1'}] if episodes else [],
                'dubs': [], 'releases': [], 'translations': [], 'available': bool(episodes)}


class OneManga(MangaHub):
    def __init__(self, sid, name, host, channel, redirect_source):
        super().__init__(sid, name, host, channel)
        self.redirect_source = redirect_source

    def pages(self, http, slug, number, path):
        try:
            return super().pages(http, slug, number, path)
        except SourceError as error:
            if isinstance(error, SourceTemporaryError):
                raise
            # The site publishes some of its chapters on 1Manga.co. Use the
            # provider's own redirect for this exact chapter, never search.
            with self.request(http, path, self.guest, referer=self.ROOT + '/manga/' + slug) as response:
                if response.status_code not in {301, 302, 307, 308}:
                    raise
                target = self.redirect_source.site_link(response.headers.get('Location'))
            # 1Manga can redirect its short slug to the catalogue slug.
            reader = self.redirect_source
            for _ in range(2):
                target_path = urlsplit(target).path
                match = CHAPTER_PATH.fullmatch(target_path)
                if not match or chapter_number(match[2]) != number or re.sub(r'_\d+$', '', match[1]) != re.sub(r'_\d+$', '', slug):
                    raise SourceError('OneManga перенаправил запрос на другую главу.') from None
                with reader.request(http, target_path, reader.guest) as response:
                    if response.status_code == 200:
                        break
                    if response.status_code not in {301, 302, 307, 308}:
                        raise SourceError('1Manga не открыл опубликованную главу OneManga.') from None
                    target = reader.site_link(response.headers.get('Location'))
            else:
                raise SourceError('Слишком много перенаправлений между читалками OneManga.') from None
            return reader.pages(http, match[1], number, target_path)


ONE_MANGA_CO = MangaHub('6314378952940608115', '1Manga.co', '1manga.co', 'mn03')
MANGA_HERE = MangaHub('3901872639081578162', 'MangaHere.onl', 'mangahere.onl', 'mh01')
SOURCES = (
    MangaHub('8144054169452081697', 'MangaFox.fun', 'mangafox.fun', 'mf01'),
    MangaHub('4758858684982406533', 'MangaHub', 'mangahub.io', 'm01'),
    MangaHub('6491120161556233904', 'Mangakakalot.fun', 'mangakakalot.fun', 'mn01'),
    MangaHub('678343830630527432', 'MangaNel', 'manganel.me', 'mn05'),
    MangaHub('5320360676060919240', 'MangaOnline.fun', 'mangaonline.fun', 'm02'),
    MangaHub('7661417715431651982', 'MangaPanda.onl', 'mangapanda.onl', 'mr02'),
    MangaHub('2527199067559866087', 'MangaReader.site', 'mangareader.site', 'mr01'),
    MangaHub('868511056418443637', 'MangaToday', 'mangatoday.fun', 'm03'),
    ONE_MANGA_CO,
    OneManga('1622381620031536307', 'OneManga.info', 'onemanga.info', 'mn02', ONE_MANGA_CO),
)
