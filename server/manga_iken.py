"""Native reader for Keiyoushi's Apache-2.0 Iken extension family."""

import json
import math
import re
import threading
import time
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, image_url
from manga_source_tags import unique
from source_parser import SourceAccessError, SourceError, public_url


TITLE_PATH = re.compile(rf'/series/({SEGMENT})/?')
CHAPTER_PATH = re.compile(rf'/series/({SEGMENT})/({SEGMENT})/?')
ID = re.compile(r'[1-9][0-9]{0,10}')
PAGE_NUMBER = re.compile(r'[0-9]+')
CHAPTER_PARAM = 'mv_iken_chapter'


def novel(post):
    return post.get('isNovel') is True or (post.get('seriesType') or '').casefold() == 'novel'


def locked(chapter):
    return (chapter.get('isLocked') is True or chapter.get('isTimeLocked') is True
            or (chapter.get('chapterPurchased', False) is False and chapter.get('price', 0) != 0))


def dict_rows(items):
    if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
        raise SourceError('Iken вернул некорректный список.')
    return items


def encode_slug(value):
    if not isinstance(value, str) or not value:
        return ''
    encoded = quote(unquote(value), safe='')
    return encoded if re.fullmatch(SEGMENT, encoded) else ''


class Iken:
    LANGUAGE = 'en'
    IS_NSFW = False
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH

    def __init__(self, identity, *, page_size=18, sort_filenames=False, separate_novels=False, fresh_images=False):
        self.SOURCE_ID, self.NAME, self.ROOT = identity
        self.host = urlsplit(self.ROOT).netloc
        self.api_root = 'https://api.' + self.host
        self.page_size = page_size
        self.sort_filenames = sort_filenames
        self.separate_novels = separate_novels
        self.fresh_images = fresh_images
        self.novel_cache = (0, frozenset())
        self.novel_lock = threading.Lock()

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            target = urljoin(base or self.ROOT, value)
            parsed = urlsplit(target)
            if parsed.scheme == 'https' and parsed.netloc == self.host:
                parts = parsed.path.split('/')
                encoded = [encode_slug(part) for part in parts]
                if any(part and not normal for part, normal in zip(parts, encoded)):
                    return ''
                return public_url(urlunsplit(parsed._replace(path='/'.join(encoded))), resolve_dns=False)
        except (SourceError, ValueError):
            pass
        return ''

    def saved_title_url(self, value):
        path = urlsplit(value).path
        if TITLE_PATH.fullmatch(path):
            return value
        if re.fullmatch(rf'/({SEGMENT})/?', path):
            return self.ROOT + '/series' + path
        return ''

    def saved_chapter(self, row, root, _title):
        stored = row.get('url') or ''
        target = self.site_link(row.get('realUrl') or stored, root)
        reference = urlsplit(stored)
        local = self.site_link(stored, root)
        if local and self.same_chapter_path(local, target) and ID.fullmatch(reference.fragment):
            return self.chapter_url(target, reference.fragment)
        return target

    @staticmethod
    def same_chapter_path(left, right):
        return urlsplit(left).path.rstrip('/') == urlsplit(right).path.rstrip('/')

    @staticmethod
    def chapter_url(target, identity):
        return urlunsplit(urlsplit(target)._replace(query=urlencode({CHAPTER_PARAM: identity})))

    def page_headers(self, url):
        headers = {'Referer': urlunsplit(urlsplit(url)._replace(query=''))}
        if self.fresh_images:
            headers['Cache-Control'] = 'no-cache'
        return headers

    def api(self, http, path, **params):
        url = self.api_root + '/api/' + path + ('?' + urlencode(params) if params else '')
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/', 'Origin': self.ROOT})
        if final != url:
            raise SourceError('Iken перенаправил запрос API.')
        try:
            payload = json.loads(raw)
        except ValueError as error:
            raise SourceError('Iken вернул страницу вместо данных API.') from error
        if not isinstance(payload, list if path == 'genres' else dict):
            raise SourceError('Iken вернул неожиданный формат данных API.')
        return payload

    def novel_ids(self, http):
        if not self.separate_novels:
            return frozenset()
        with self.novel_lock:
            expires, cached = self.novel_cache
            if expires > time.monotonic():
                return cached
            found = set()
            for page in range(1, 2001):
                data = self.api(http, 'posts', page=page, perPage=100)
                items = dict_rows(data.get('novelPosts'))
                found.update(item['id'] for item in items)
                if not items or len(found) >= data['novelTotalCount']:
                    self.novel_cache = (time.monotonic() + 3600, frozenset(found))
                    return self.novel_cache[1]
            raise SourceError('Отдельный список новелл Iken превысил лимит страниц.')

    def row(self, post):
        from manga_sources import title_aliases
        slug = encode_slug(post.get('slug'))
        label = post.get('postTitle')
        if not slug or not isinstance(label, str) or not label.strip():
            raise SourceError('Iken вернул карточку без названия или ссылки.')
        url = self.ROOT + '/series/' + slug
        alternative = re.split(r'\s*[;|]\s*|\s+/\s+', post.get('alternativeTitles') or '')
        description = BeautifulSoup(post.get('postContent') or '', 'html.parser').get_text(' ', strip=True)
        status = (post.get('seriesStatus') or '').replace('_', ' ').casefold()
        kind = (post.get('seriesType') or '').casefold()
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'provider': 'suwayomi:' + self.SOURCE_ID,
                'providerName': self.NAME, 'sourceId': self.SOURCE_ID, 'sourceUrl': url, 'sourceURL': url, 'url': url,
                'kind': 'manga', 'language': self.LANGUAGE, 'title': label.strip()[:500], 'ids': {}, 'sourceOnly': True,
                'aliases': unique([*title_aliases(label), *alternative]), 'cover': image_url(post.get('featuredImage'), url),
                'genres': unique(item.get('name') for item in dict_rows(post.get('genres', []))), 'tags': [],
                'description': description[:12000], 'authors': unique([post.get('author')]),
                'artists': unique([post.get('artist')]), 'format': kind, 'status': status}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if not isinstance(page, int) or not 1 <= page <= 2000 or not isinstance(tag, str) or (tag and not ID.fullmatch(tag)):
            raise SourceError('Некорректные параметры каталога Iken.')
        params = {'perPage': self.page_size, 'searchTerm': query[:160].strip()}
        if not query and not tag:
            params['orderBy'] = 'lastChapterAddedAt' if sort == 'updated' else 'totalViews'
        if tag:
            params['genreIds'] = tag
        excluded = self.novel_ids(http)
        while True:
            data = self.api(http, 'query', **params, page=page)
            posts = dict_rows(data.get('posts'))
            rows = [self.row(post) for post in posts if not novel(post) and post.get('id') not in excluded]
            more = data['totalCount'] > page * self.page_size and page < 2000
            if rows or not more or not query:
                return rows, more
            page += 1

    def vocabulary(self, http):
        return [{'sourceId': str(row['id']), 'label': row['name'], 'category': 'genre'}
                for row in dict_rows(self.api(http, 'genres')) if ID.fullmatch(str(row.get('id'))) and row.get('name')]

    def post(self, http, slug):
        data = self.api(http, 'post', postSlug=unquote(slug))
        post = data.get('post')
        if not isinstance(post, dict) or encode_slug(post.get('slug')) != slug or novel(post):
            raise SourceError('Iken вернул карточку другого тайтла или новеллы.')
        return post, data.get('totalChapterCount')

    def details(self, http, value):
        match = TITLE_PATH.fullmatch(urlsplit(self.site_link(value)).path)
        if not match:
            raise SourceError('Некорректная ссылка на тайтл Iken.')
        return self.row(self.post(http, match[1])[0])

    def chapters(self, http, post, total):
        rows = dict_rows(post.get('chapters', []))
        if type(total) is int and total > len(rows) and ID.fullmatch(str(post.get('id'))):
            complete = dict_rows(self.api(http, 'chapters', postId=post['id'])['post'].get('chapters'))
            if len(complete) > len(rows):
                rows = complete
        result = {}
        for row in rows:
            slug = encode_slug(row.get('slug'))
            identity = str(row.get('id'))
            if slug and ID.fullmatch(identity):
                result.setdefault(slug, {})[identity] = row
        return result

    def entry(self, post, chapter, *, scoped=False):
        raw_number = str(chapter.get('number'))
        number = float(raw_number.replace(',', '.')) if re.fullmatch(r'[0-9]+(?:[.,][0-9]+)?', raw_number) else 0.0
        suffix = (' — ' + chapter['title']) if chapter.get('title') else ''
        url = self.ROOT + '/series/' + encode_slug(post['slug']) + '/' + encode_slug(chapter['slug'])
        if scoped:
            url = self.chapter_url(url, chapter['id'])
        return {'url': url,
                'title': 'Chapter ' + raw_number + suffix, 'number': number if math.isfinite(number) else 0,
                'language': self.LANGUAGE, 'season': 1, 'translator': '',
                'publishedAt': (chapter.get('createdAt') or '')[:10]}

    def pages(self, http, chapter):
        if not ID.fullmatch(str(chapter.get('id'))):
            raise SourceError('Iken не предоставил ID открытой главы.')
        payload = self.api(http, 'chapter', chapterId=chapter['id'])['chapter']
        if any(payload.get(name) for name in ('isPermanentlyLocked', 'isLockedByCoins', 'isShortLinkLocked')):
            raise SourceAccessError('Глава закрыта у источника.')
        images = dict_rows(payload.get('images'))
        if self.sort_filenames:
            def order(row):
                match = PAGE_NUMBER.search(urlsplit(row.get('url') or '').path.rsplit('/', 1)[-1])
                return int(match[0]) if match else math.inf
        else:
            def order(row):
                value = row.get('order')
                return value if type(value) is int else math.inf
        pages = [image_url(item.get('url'), self.ROOT + '/') for item in sorted(images, key=order)]
        if not pages or len(pages) > 500 or not all(pages):
            raise SourceError('Iken не предоставил полный список страниц главы.')
        return pages

    def inspect(self, value, http):
        target = urlsplit(self.site_link(value))
        chapter = CHAPTER_PATH.fullmatch(target.path)
        match = chapter or TITLE_PATH.fullmatch(target.path)
        if match is None:
            raise SourceError('Некорректная ссылка на читалку Iken.')
        post, total = self.post(http, match[1])
        result = self.row(post)
        chapters = self.chapters(http, post, total)
        pages = []
        url = result['url']
        if chapter:
            variants = chapters.get(chapter[2], {})
            try:
                selected = parse_qs(target.query, keep_blank_values=True, max_num_fields=8).get(CHAPTER_PARAM, [])
            except ValueError as error:
                raise SourceError('Некорректная ссылка на главу Iken.') from error
            if selected:
                if len(selected) != 1 or not ID.fullmatch(selected[0]):
                    raise SourceError('Некорректный ID главы Iken.')
                item = variants.get(selected[0])
            else:
                item = next((row for row in variants.values() if not locked(row)), next(iter(variants.values()), None))
            if item is None:
                raise SourceError('Iken не нашёл главу у этого тайтла.')
            if locked(item):
                raise SourceAccessError('Глава закрыта у источника.')
            entry = self.entry(post, item, scoped=bool(selected) or len(variants) > 1)
            pages = self.pages(http, item)
            url = entry['url']
            episodes = [entry]
        else:
            episodes = sorted((self.entry(post, item, scoped=len(variants) > 1)
                               for variants in chapters.values() for item in variants.values() if not locked(item)),
                              key=lambda item: item['number'])
        return {**result, 'url': url, 'episodes': episodes, 'pages': pages, 'available': bool(episodes),
                'truncated': False, 'seasons': [{'number': 1, 'name': 'Том 1'}] if episodes else [],
                'dubs': [], 'releases': [], 'translations': []}


SOURCES = (
    Iken(('2559570015828016575', 'Vortex Scans', 'https://vortexscans.org'), separate_novels=True),
    Iken(('454381816904772144', 'Hijala Scans', 'https://en-hijala.com')),
    Iken(('6311653253665366075', 'Hive Scans', 'https://hivetoons.org'), fresh_images=True),
    Iken(('7831933086917318633', 'Ken Scans', 'https://kencomics.com')),
    Iken(('1589747287364201069', 'Magus Manga', 'https://magustoon.org'), sort_filenames=True),
    Iken(('419822582289753882', 'Nyx Scans', 'https://nyxscans.com'), separate_novels=True),
    Iken(('7776050777496310004', 'Orion Scans', 'https://orion-scans.com')),
    Iken(('1931508394363321246', 'Sana Scans', 'https://sanascans.com'), page_size=30, sort_filenames=True),
)

API_HOSTS = {urlsplit(adapter.api_root).hostname: adapter for adapter in SOURCES}


def public_api(host, path, query):
    adapter = API_HOSTS.get(host)
    if adapter is None:
        return False
    try:
        params = parse_qs(query, keep_blank_values=True, strict_parsing=True, max_num_fields=5)
    except ValueError:
        return False
    if any(len(values) != 1 for values in params.values()):
        return False
    args = {key: values[0] for key, values in params.items()}
    if path == '/api/genres':
        return not args
    if path in {'/api/chapter', '/api/chapters'}:
        key = 'chapterId' if path == '/api/chapter' else 'postId'
        return args.keys() == {key} and bool(ID.fullmatch(args[key]))
    if path == '/api/post':
        return args.keys() == {'postSlug'} and bool(encode_slug(args['postSlug']))
    page = args.get('page', '')
    if not re.fullmatch(r'[1-9][0-9]{0,3}', page) or int(page) > 2000:
        return False
    if path == '/api/posts':
        return adapter.separate_novels and args.keys() == {'page', 'perPage'} and args['perPage'] == '100'
    return (path == '/api/query' and {'page', 'perPage', 'searchTerm'} <= args.keys()
            and args.keys() <= {'page', 'perPage', 'searchTerm', 'orderBy', 'genreIds'}
            and args['perPage'] == str(adapter.page_size) and len(args['searchTerm']) <= 160
            and args.get('orderBy', '') in {'', 'lastChapterAddedAt', 'totalViews'}
            and ('genreIds' not in args or bool(ID.fullmatch(args['genreIds']))))
