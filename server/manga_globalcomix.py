"""GlobalComix public catalogue and accessible releases from Keiyoushi."""

import os
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from manga_dot_nami_http import document, json_data, mapping, records
from manga_global_dbm_profiles import GLOBAL
from manga_madara import OriginPace, image_url
from manga_source_tags import labels, unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import SourceAccessError, SourceError, public_url


ROOT = 'https://globalcomix.com'
API = 'https://api.globalcomix.com'
API_PREFIX = '/v1'
ID = r'[1-9][0-9]{0,14}'
SLUG = r'[A-Za-z0-9][A-Za-z0-9_-]{0,219}'
CHAPTER = r'[A-Za-z0-9_-]{1,128}'
TITLE_PATH = re.compile(rf'/c/({SLUG})/?')
CHAPTER_PATH = re.compile(rf'/read/({CHAPTER})(?:/[0-9]+)?/?')
STATUS = {'Ongoing': 'ongoing', 'Preview': 'ongoing', 'Finished': 'completed', 'On hold': 'hiatus',
          'Cancelled': 'cancelled'}
LANGS = {'sq': 'al', 'pt-BR': 'br', 'zh-Hans': 'cn', 'cs': 'cz', 'da': 'dk', 'fil': 'fo', 'he': 'iw',
         'ja': 'jp', 'ko': 'kr', 'ms': 'my', 'sv': 'se', 'uk': 'ua'}
LOCALES = {LANGS.get(lang, lang) for _, lang in GLOBAL}
PACE = OriginPace()
PACE.interval = .35


def public_request(value):
    parts = urlsplit(value)
    if parts.scheme != 'https' or parts.netloc != 'api.globalcomix.com' or parts.fragment:
        return False
    try:
        args = parse_qs(parts.query, keep_blank_values=True, max_num_fields=5, strict_parsing=True)
    except ValueError:
        return False
    if any(len(val) != 1 for val in args.values()):
        return False
    args = {key: val[0] for key, val in args.items()}
    if parts.path == API_PREFIX + '/comics':
        return (args.keys() <= {'lang_id[]', 'p', 'q', 'sort'} and args.get('lang_id[]') in LOCALES
                and bool(re.fullmatch(r'[1-9][0-9]{0,3}', args.get('p', '')))
                and ('q' not in args or 1 <= len(args['q']) <= 160) and args.get('sort') in (None, 'recent', 'relevance'))
    if re.fullmatch(rf'{API_PREFIX}/comics/{ID}/releases', parts.path):
        return args.keys() == {'lang_id', 'all'} and args['lang_id'] in LOCALES and args['all'] == 'true'
    return not args and bool(re.fullmatch(rf'{API_PREFIX}/(?:read/{SLUG}|readV2/{CHAPTER})', parts.path))


def client_header():
    value = os.getenv('GLOBALCOMIX_CLIENT_ID', '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', value):
        raise SourceAccessError('Для API GlobalComix нужен серверный идентификатор клиента.')
    return value


def get(http, endpoint, params=()):
    PACE.wait(http.deadline)
    reply = json_data(document(http, API, API_PREFIX + endpoint, params, action='globalcomix-json'))
    return mapping(mapping(reply).get('payload'))


def slug_from(item):
    for key in ('slug', 'comic_slug', 'slug_name', 'url_slug'):
        value = item.get(key)
        if isinstance(value, str) and re.fullmatch(SLUG, value):
            return value
    return re.sub(r'[^a-z0-9]+', '-', str(item.get('name', '')).lower()).strip('-')


class GlobalComix:
    ROOT = ROOT
    NAME = 'GlobalComix'
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    IS_NSFW = False
    scoped_urls = True
    index_sort = 'updated'

    def __init__(self, sid, language):
        self.SOURCE_ID, self.LANGUAGE = sid, language
        self.lang = LANGS.get(language, language)

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, raw = split_reader_url(urljoin(base or ROOT + '/', value))
            url = urlsplit(raw)
            if selected not in (None, self.SOURCE_ID) or url.scheme != 'https' or url.netloc != 'globalcomix.com':
                return ''
            parent = parse_qs(url.query, keep_blank_values=True, max_num_fields=8).get('title', [])
            if parent and (len(parent) != 1 or not re.fullmatch(SLUG, parent[0]) or not CHAPTER_PATH.fullmatch(url.path)):
                return ''
            return public_url(urlunsplit(url._replace(query=urlencode({'title': parent[0]}) if parent else '')),
                              resolve_dns=False)
        except (ValueError, SourceError):
            return ''

    def reader_url(self, value):
        return reader_url(value, self.SOURCE_ID)

    def row(self, item, *, requested_slug=''):
        identity = str(item.get('id', ''))
        title = item.get('name')
        slug = requested_slug or slug_from(item)
        if not re.fullmatch(ID, identity) or not re.fullmatch(SLUG, slug) or not isinstance(title, str) or not title.strip():
            raise SourceError('GlobalComix вернул карточку без ID, названия или ссылки.')
        url = self.reader_url(ROOT + '/c/' + slug)
        creator = item.get('artist') or {}
        genre = item.get('category_name')
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{identity}', 'sourceId': self.SOURCE_ID,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME,
                'url': url, 'sourceUrl': url, 'kind': 'manga', 'language': self.LANGUAGE, 'format': 'comic',
                'title': title.strip()[:500], 'aliases': unique([title]),
                'description': str(item.get('description') or '')[:12000],
                'authors': unique([creator.get('roman_name') or creator.get('name')]),
                'status': STATUS.get(item.get('status_name'), ''), 'genres': labels(genre), 'tags': [],
                'cover': image_url(item.get('image_url'), ROOT + '/'), 'sourceOnly': True, 'ids': {}}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or tag:
            raise SourceError('Некорректные параметры каталога GlobalComix.')
        params = {'lang_id[]': self.lang, 'p': page}
        if query := query.strip()[:160]:
            params.update(q=query, sort='relevance')
        elif sort == 'updated':
            params['sort'] = 'recent'
        payload = get(http, '/comics', params)
        rows = records(payload.get('results'))
        pagination = mapping(payload.get('pagination'))
        total = pagination.get('total_pages', 0)
        return [self.row(row) for row in rows], bool(rows and type(total) is int and page < total)

    def vocabulary(self, http):
        return []

    def work(self, http, slug):
        item = mapping(get(http, '/read/' + slug).get('results'))
        return self.row(item, requested_slug=slug), str(item['id'])

    def details(self, http, value):
        title = TITLE_PATH.fullmatch(urlsplit(self.site_link(value)).path)
        if not title:
            raise SourceError('Некорректная ссылка на комикс GlobalComix.')
        return self.work(http, title[1])[0]

    def chapter_url(self, key, slug):
        return ROOT + '/read/' + key + '?title=' + slug

    def chapters(self, http, slug, identity):
        from manga_sources import chapter_number

        items = records(get(http, f'/comics/{identity}/releases', {'lang_id': self.lang, 'all': 'true'}).get('results'))
        result = []
        for item in items:
            key = item.get('key')
            if not isinstance(key, str) or not re.fullmatch(CHAPTER, key):
                raise SourceError('GlobalComix вернул выпуск без идентификатора.')
            number = str(item.get('chapter') or '0')
            try:
                numeric = chapter_number(number)
            except SourceError:
                numeric = 0
            date = item.get('published_time') or ''
            language = item.get('lang_id')
            if language is not None and language != self.lang:
                continue
            result.append({'url': self.reader_url(self.chapter_url(key, slug)), 'number': numeric, 'season': 1,
                           'language': self.LANGUAGE, 'title': ' — '.join(filter(None, ['Глава ' + number, item.get('title')])),
                           'publishedAt': date[:10], 'locked': item.get('premium_only') in (1, '1')})
        return result

    def pages(self, http, identity):
        item = mapping(get(http, '/readV2/' + identity).get('results'))
        if item.get('key', identity) != identity or item.get('premium_only') in (1, '1'):
            raise SourceAccessError('GlobalComix ограничивает доступ к выпуску.')
        pages = records(item.get('page_objects') or [])
        if any(page.get('is_page_paid') in (True, '1', 'true') for page in pages):
            raise SourceAccessError('GlobalComix предоставил только часть выпуска.')
        urls = [image_url(page.get('desktop_image_url'), ROOT + '/') for page in pages]
        if not 1 <= len(urls) <= 500 or not all(urls):
            raise SourceError('GlobalComix не предоставил полный список страниц.')
        return urls

    def inspect(self, value, http):
        target = self.site_link(value)
        path = urlsplit(target)
        title, chapter = TITLE_PATH.fullmatch(path.path), CHAPTER_PATH.fullmatch(path.path)
        if not (title or chapter):
            raise SourceError('Некорректная ссылка на читалку GlobalComix.')
        slug = title[1] if title else parse_qs(path.query).get('title', [''])[0]
        if not slug:
            raise SourceError('Открой выпуск из оглавления GlobalComix.')
        row, identity = self.work(http, slug)
        episodes = self.chapters(http, slug, identity)
        pages = []
        if chapter:
            canonical = self.reader_url(self.chapter_url(chapter[1], slug))
            episodes = [episode for episode in episodes if episode['url'] == canonical]
            if len(episodes) != 1:
                raise SourceError('Выпуск отсутствует в оглавлении GlobalComix на выбранном языке.')
            if episodes[0]['locked']:
                raise SourceAccessError('GlobalComix ограничивает доступ к выпуску.')
            pages = self.pages(http, chapter[1])
        return {**row, 'url': self.reader_url(target), 'episodes': episodes, 'pages': pages,
                'available': any(not episode['locked'] for episode in episodes), 'truncated': False,
                'translations': [], 'seasons': [{'number': 1, 'name': 'Том 1'}] if episodes else [], 'dubs': [], 'releases': []}

    def saved_chapter_url(self, value, slug, root):
        if not isinstance(value, str):
            return ''
        chapter = CHAPTER_PATH.fullmatch(urlsplit(self.site_link(value, root)).path)
        identity = value if re.fullmatch(CHAPTER, value) else chapter[1] if chapter else ''
        return self.chapter_url(identity, slug) if identity else ''

    def saved_chapter_matches(self, chapter, title):
        return parse_qs(urlsplit(chapter).query).get('title') == [TITLE_PATH.fullmatch(urlsplit(title).path)[1]]


SOURCES = tuple(GlobalComix(*profile) for profile in GLOBAL)
