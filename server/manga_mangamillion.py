"""Native public Manga Million catalogue and viewer protocol."""

from collections import OrderedDict
import re
from threading import Lock
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from requests import RequestException

from manga_ball_million_profiles import MILLION
from manga_madara import OriginPace, image_url
from manga_million_wire import Message
from manga_source_tags import unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import SourceAccessError, SourceError, SourceTemporaryError, public_url


ROOT = 'https://mangamillion.shueisha.co.jp'
API_HOST = 'api.mangamillion.shueisha.co.jp'
API = 'https://' + API_HOST + '/api/'
SERVICE_LANGUAGES = frozenset(('de', 'en', 'es', 'fr', 'hi', 'id', 'it', 'ja', 'ko-KR', 'pt-BR', 'ru', 'th', 'vi', 'zh-CN'))
TRANSLATION_LANGUAGES = frozenset(lang for _, lang in MILLION)
LOCALE = r'[a-z]{2,3}(?:-[A-Z]{2})?'
ID = r'[1-9][0-9]{0,9}'
IDENTITY = re.compile(ID)
TITLE_PATH = re.compile(rf'/{LOCALE}/title/({ID})/?')
CHAPTER_PATH = re.compile(rf'/{LOCALE}/title/({ID})/chapter/({ID})/?')
PARAMS = {
    '/api/register': (),
    '/api/manga_list': (),
    '/api/search_parameter': (),
    '/api/search': ('translated_language', 'text', 'tag_id', 'rating_id'),
    '/api/title_detail': ('original_title_id',),
    '/api/chapter_list': ('original_title_id', 'translated_language'),
    '/api/viewer': ('translated_chapter_id', 'quality'),
}
MARKER = 'mv_million_page='
TOKEN = re.compile(r'[\x21-\x7e]{1,2048}')
HEX = re.compile('[a-fA-F0-9]+')
PACE = OriginPace()
PACE.interval = 0.35
_tokens = {}
_token_locks = {lang: Lock() for lang in SERVICE_LANGUAGES}
_lock = Lock()
_catalogues = OrderedDict()
_viewers = OrderedDict()
_catalogue_locks = {lang: Lock() for lang in SERVICE_LANGUAGES}


def public_api(host, path, query):
    options = PARAMS.get(path)
    if host != API_HOST or options is None:
        return False
    try:
        fields = parse_qs(query, keep_blank_values=True, strict_parsing=True, max_num_fields=6)
    except ValueError:
        return False
    if any(len(items) != 1 for items in fields.values()):
        return False
    values = {key: items[0] for key, items in fields.items()}
    if values.pop('service_language', '') not in SERVICE_LANGUAGES:
        return False
    if path == '/api/register':
        return not values
    if values.pop('avif_enable', '') != 'true' or not values.keys() <= set(options):
        return False
    for key, value in values.items():
        if key == 'translated_language' and value not in TRANSLATION_LANGUAGES:
            return False
        if key in {'original_title_id', 'translated_chapter_id', 'rating_id', 'tag_id'} and not IDENTITY.fullmatch(value):
            return False
        if key == 'quality' and value != 'middle' or key == 'text' and not 1 <= len(value) <= 160:
            return False
    required = set(options) - {'text', 'tag_id', 'rating_id'}
    return required <= values.keys()


def fetch(http, endpoint, language, params, token=''):
    fields = {'service_language': language, **params}
    if endpoint != 'register':
        fields['avif_enable'] = 'true'
    url = API + endpoint + '?' + urlencode(fields)
    method = 'POST' if endpoint == 'register' else 'GET'
    PACE.wait(getattr(http, 'deadline', None))
    response, final = http._open(url, method=method, data=b'' if method == 'POST' else None,
                                 action='mangamillion-proto', headers={'Access-Token': token})
    try:
        if final != url or 'text/html' in response.headers.get('Content-Type', '').lower():
            raise SourceError('Manga Million вернул страницу вместо данных API.')
        raw = bytearray()
        for part in response.iter_content(65536):
            raw.extend(part)
            if len(raw) > 24 * 1024 * 1024 or http.deadline and time.monotonic() >= http.deadline:
                raise SourceError('Ответ Manga Million превысил лимит.')
        if not raw:
            raise SourceError('Manga Million вернул пустой ответ.')
        return Message(bytes(raw))
    except RequestException:
        raise SourceTemporaryError('Manga Million прервал ответ.') from None
    finally:
        response.close()


def guest_token(http, language, rejected=''):
    with _token_locks[language]:
        token = _tokens.get(language, '')
        if token and token != rejected:
            return token
        token = fetch(http, 'register', language, {}).message(170).string(1)
        if not TOKEN.fullmatch(token):
            raise SourceAccessError('Manga Million не выдал гостевой доступ.')
        _tokens[language] = token
        return token


def request(http, endpoint, language, **params):
    token = guest_token(http, language)
    try:
        return fetch(http, endpoint, language, params, token)
    except SourceAccessError:
        return fetch(http, endpoint, language, params, guest_token(http, language, token))


def cache_get(store, key):
    with _lock:
        item = store.get(key)
        if item and item[0] > time.monotonic():
            store.move_to_end(key)
            return item[1]
        store.pop(key, None)
        return None


def cache_put(store, key, value, capacity):
    with _lock:
        store[key] = time.monotonic() + 240, value
        store.move_to_end(key)
        if len(store) > capacity:
            store.popitem(last=False)


def decode_series(data, field):
    for entry in data.message(field).messages(1):
        series = entry.message(1)
        yield (str(series.integer(1)), series.string(3), series.string(2), series.integer(7), series.integer(9),
               frozenset(entry.strings(2)))


def catalogue_data(http, language):
    with _catalogue_locks[language]:
        if (cached := cache_get(_catalogues, language)) is not None:
            return cached
        data = tuple(decode_series(request(http, 'manga_list', language), 22))
        cache_put(_catalogues, language, data, len(SERVICE_LANGUAGES))
        return data


def chapter_number(value):
    match = re.fullmatch(r'#([0-9]{1,5}(?:\.[0-9]{1,4})?)(?:,.*|-([0-9]{1,5}))?', value)
    if not match:
        return None
    base, suffix = match.groups()
    return float(base + '.' + suffix) if suffix and len(suffix) < 3 and '.' not in base else float(base)


def page_marker(value):
    try:
        selected, target = split_reader_url(value)
        parts = urlsplit(target)
    except ValueError:
        raise SourceError('Некорректный адрес страницы Manga Million.') from None
    match = CHAPTER_PATH.fullmatch(parts.path)
    page = re.fullmatch(rf'{MARKER}([0-9]{{1,3}})', parts.fragment)
    profile = BY_ID.get(selected)
    if (not profile or parts.scheme != 'https' or parts.netloc != urlsplit(ROOT).netloc or parts.query
            or not match or parts.path.split('/')[1] != profile.service or not page or int(page[1]) >= 500):
        raise SourceError('Некорректный адрес страницы Manga Million.')
    return profile, match[1], match[2], int(page[1])


def page_data(http, value):
    profile, title, chapter, index = page_marker(value)
    key = profile.SOURCE_ID, title, chapter
    data = cache_get(_viewers, key)
    if data is None:
        if not any(urlsplit(item['url']).path.endswith('/chapter/' + chapter) for item in profile.chapters(http, title)):
            raise SourceAccessError('Глава недоступна на языке выбранного профиля Manga Million.')
        data = profile.viewer(http, title, chapter)
    urls, secret, iv = data
    if index >= len(urls):
        raise SourceError('Страница отсутствует в главе Manga Million.')
    return urls[index], secret, iv


def decrypt(raw, key, iv):
    if not raw or len(raw) % 16:
        raise SourceError('Manga Million вернул неполное изображение.')
    try:
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        unpad = padding.PKCS7(128).unpadder()
        return unpad.update(cipher.update(raw) + cipher.finalize()) + unpad.finalize()
    except ValueError:
        raise SourceError('Manga Million вернул некорректное изображение.') from None


class MangaMillion:
    ROOT = ROOT
    NAME = 'Manga Million'
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    IS_NSFW = False
    scoped_urls = True
    index_sort = 'updated'

    def __init__(self, sid, lang):
        self.SOURCE_ID, self.LANGUAGE = sid, lang
        self.service = lang if lang in SERVICE_LANGUAGES else 'en'

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, raw = split_reader_url(urljoin(base or ROOT + '/', value))
            parts = urlsplit(raw)
            if (selected not in (None, self.SOURCE_ID) or parts.scheme != 'https'
                    or parts.netloc != urlsplit(ROOT).netloc or parts.query or parts.fragment):
                return ''
            return public_url(raw, resolve_dns=False)
        except (ValueError, SourceError):
            return ''

    def reader_url(self, value):
        return reader_url(value, self.SOURCE_ID)

    def title_url(self, identity):
        return ROOT + '/' + self.service + '/title/' + identity

    def row(self, identity, name, cover):
        if not IDENTITY.fullmatch(identity) or not name.strip():
            raise SourceError('Manga Million не указал название или ID тайтла.')
        target = self.reader_url(self.title_url(identity))
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{identity}', 'sourceId': self.SOURCE_ID,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME,
                'url': target, 'sourceUrl': target, 'kind': 'manga', 'language': self.LANGUAGE,
                'title': name.strip()[:500], 'aliases': unique([name]), 'cover': image_url(cover, ROOT + '/'),
                'genres': [], 'tags': [], 'ids': {}, 'sourceOnly': True}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or page < 1 or not isinstance(query, str):
            raise SourceError('Некорректные параметры каталога Manga Million.')
        if page > 1:
            return [], False
        query = query.strip()[:160]
        if query or tag:
            params = {'translated_language': self.LANGUAGE}
            if query:
                params['text'] = query
            if tag:
                match = re.fullmatch(rf'(tag|rating):({ID})', tag)
                if not match:
                    raise SourceError('Некорректный фильтр Manga Million.')
                params[match[1] + '_id'] = match[2]
            entries = decode_series(request(http, 'search', self.service, **params), 20)
        else:
            entries = sorted(catalogue_data(http, self.service), key=lambda item: item[4 if sort == 'updated' else 3],
                             reverse=True)
        return [self.row(identity, name, cover) for identity, name, cover, _, _, langs in entries
                if self.LANGUAGE in langs], False

    def vocabulary(self, http):
        message = request(http, 'search_parameter', self.service).message(21)
        terms = {}
        for field in (2, 3, 4, 5):
            for row in message.messages(field):
                identity, label = row.integer(1), row.string(2)
                if identity and label:
                    key = ('rating:' if field == 5 else 'tag:') + str(identity)
                    terms.setdefault(key, {'sourceId': key, 'label': label, 'category': 'genre' if field == 2 else 'tag'})
        return list(terms.values())

    def work(self, http, identity):
        data = request(http, 'title_detail', self.service, original_title_id=identity).message(50).message(1)
        return {**self.row(identity, data.string(2), data.string(1)), 'description': data.string(7)[:12000],
                'authors': unique([data.string(3)]), 'genres': unique(genre.string(2) for genre in data.messages(4))}

    def details(self, http, value):
        match = TITLE_PATH.fullmatch(urlsplit(self.site_link(value)).path)
        if not match:
            raise SourceError('Некорректная ссылка на тайтл Manga Million.')
        return self.work(http, match[1])

    def chapters(self, http, identity):
        data = request(http, 'chapter_list', self.service, original_title_id=identity, translated_language=self.LANGUAGE)
        groups = data.message(60).messages(2)
        episodes = []
        for group in groups:
            for row in group.messages(2):
                chapter = str(row.integer(3))
                if not IDENTITY.fullmatch(chapter):
                    continue
                number_label = row.string(1)
                episodes.append({'url': self.reader_url(self.title_url(identity) + '/chapter/' + chapter),
                                 'title': (row.string(2) or number_label or 'Глава')[:300],
                                 'number': chapter_number(number_label), 'season': 1, 'language': self.LANGUAGE})
        for index, entry in enumerate(episodes):
            if entry['number'] is None:
                following = episodes[index + 1]['number'] if index + 1 < len(episodes) else None
                previous = episodes[index - 1]['number'] if index else None
                if previous is not None:
                    entry['number'] = round(previous + .01, 3)
                else:
                    entry['number'] = max(0, round(following - .01, 3)) if following is not None else 0
        return list(reversed(episodes))

    def viewer(self, http, title, chapter):
        data = request(http, 'viewer', self.service, translated_chapter_id=chapter, quality='middle').message(70)
        key, iv = data.string(7), data.string(8)
        if len(key) not in {32, 48, 64} or len(iv) != 32 or not HEX.fullmatch(key) or not HEX.fullmatch(iv):
            raise SourceError('Manga Million не предоставил параметры открытой страницы.')
        urls = [image_url(page.string(1), ROOT + '/') for page in data.messages(1)]
        if not 1 <= len(urls) <= 500 or not all(urls):
            raise SourceError('Manga Million не предоставил полный список страниц.')
        result = urls, bytes.fromhex(key), bytes.fromhex(iv)
        cache_put(_viewers, (self.SOURCE_ID, title, chapter), result, 128)
        return result

    def inspect(self, value, http):
        target = self.site_link(value)
        path = urlsplit(target).path
        title, chapter = TITLE_PATH.fullmatch(path), CHAPTER_PATH.fullmatch(path)
        if not (title or chapter):
            raise SourceError('Некорректная ссылка на читалку Manga Million.')
        identity = (title or chapter)[1]
        episodes = self.chapters(http, identity)
        pages = []
        if chapter:
            canonical = self.reader_url(self.title_url(identity) + '/chapter/' + chapter[2])
            episodes = [row for row in episodes if row['url'] == canonical]
            if len(episodes) != 1:
                raise SourceAccessError('Manga Million не предоставил главу на языке этого профиля.')
            urls, _, _ = self.viewer(http, identity, chapter[2])
            pages = [canonical + '#' + MARKER + str(index) for index in range(len(urls))]
        return {**self.work(http, identity), 'url': self.reader_url(target), 'episodes': episodes, 'pages': pages,
                'available': bool(episodes), 'truncated': False, 'dubs': [], 'releases': [], 'translations': [],
                'seasons': [{'number': 1, 'name': 'Том 1'}] if episodes else []}

    def saved_title_url(self, value):
        path = urlsplit(value).path
        title = TITLE_PATH.fullmatch(path)
        identity = title[1] if title else path.strip('/')
        return self.title_url(identity) if IDENTITY.fullmatch(identity) else ''

    def saved_chapter_url(self, value, slug, root):
        if isinstance(value, str) and IDENTITY.fullmatch(value):
            return self.title_url(slug) + '/chapter/' + value
        return self.site_link(value, root)


SOURCES = tuple(MangaMillion(*profile) for profile in MILLION)
BY_ID = {profile.SOURCE_ID: profile for profile in SOURCES}
