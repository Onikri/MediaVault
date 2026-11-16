"""MangaBox Japanese public GraphQL, JSON-RPC and XOR page transport."""

import json
import re
from time import time
from unicodedata import normalize
from urllib.parse import parse_qsl, urlsplit

from manga_direct_payloads import items, strings
from manga_mangaplus import XorPage
from manga_rayuba import uploaded
from manga_series_port import SeriesPort, number
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://www.mangabox.me'
HOST = 'www.mangabox.me'
API = ROOT + '/api/honshi'
THUMBS = 'https://image-c.cdn.mangabox.me/image/upload/manga_episode_grid/manga_episode_grid_'
ID = r'[1-9]\d{0,9}'
TITLE = rf'/reader/({ID})/episodes/?'
CHAPTER = rf'/reader/({ID})/episodes/({ID})/?'
IMAGE_KEY = re.compile(r'[A-Za-z0-9_+=./~%-]{4,1800}')
QUERIES = {
    'Ranking': 'query Ranking { featured { sections { ... on RankingSection { items { mangaID title } } } } }',
    'NewArrivals': 'query NewArrivals { featured { sections { ... on NewArrivalsSection { items { mangaID title } } } } }',
    'Search': 'query Search { honshiMangas { mangaID title searchKeywords } }',
}


def public_api(host, path, query):
    if host != HOST:
        return False
    if path == '/api/honshi/image':
        pairs = parse_qsl(query)
        return len(pairs) == 1 and pairs[0][0] == 'd' and bool(IMAGE_KEY.fullmatch(pairs[0][1]))
    return not query and bool(re.fullmatch(rf'/api/honshi/(?:graphql|jsonrpc|episode/{ID}/images)', path))


def form(url, body):
    if not isinstance(body, bytes) or len(body) > 4096 or url not in {API + '/graphql', API + '/jsonrpc'}:
        return False
    try:
        data = json.loads(body)
        if url.endswith('/graphql'):
            key = data['operationName']
            return (set(data) == {'query', 'operationName'} and key in QUERIES and QUERIES[key] == data['query'])
        params = data['params']
        return (set(data) == {'jsonrpc', 'method', 'params'} and data['jsonrpc'] == '2.0'
                and data['method'] == 'get_all_episodes_by_manga_id' and set(params) == {'mangaId', 'withTags'}
                and type(params['withTags']) is int and params['withTags'] == 1
                and bool(re.fullmatch(ID, params['mangaId'])))
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def compare(value):
    return normalize('NFKC', value).casefold()


class MangaBox(SeriesPort):
    def __init__(self):
        super().__init__(('1624494110013319952', 'MangaBox', 'ja', ROOT, True), TITLE, CHAPTER, interval=.35)

    def title_url(self, identity):
        return ROOT + f'/reader/{identity}/episodes/'

    def title_for(self, url):
        identity = self.chapter_key(url)
        return self.title_url(identity) if identity else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        key = urlsplit(url).path.strip('/')
        return self.title_url(key) if re.fullmatch(ID, key) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        cid = urlsplit(url).path.strip('/')
        return self.title_url(self.title_key(title)) + cid + '/' if self.is_title(title) and re.fullmatch(ID, cid) else ''

    def post(self, http, route, data):
        self.origin.wait(getattr(http, 'deadline', None))
        url = API + '/' + route
        raw, final, _ = http.document(url, method='POST', data=json.dumps(data, separators=(',', ':')).encode(),
                                      headers={'Referer': ROOT + '/reader/'}, action='mangabox-read')
        if final != url:
            raise SourceError('MangaBox перенаправил публичный запрос.')
        obj = json.loads(raw)
        key = 'data' if route == 'graphql' else 'result'
        if obj.get('errors') or not isinstance(obj.get(key), dict):
            raise SourceError('MangaBox отклонил запрос каталога.')
        return obj[key]

    def summary(self, value, catalogue=False):
        key = str(value.get('mangaID') if catalogue else value.get('id'))
        label = value.get('title')
        if not re.fullmatch(ID, key) or not isinstance(label, str) or not label:
            return None
        tags = value.get('tags') or {}
        authors = [item.get('name') for item in value.get('authors') or [] if isinstance(item, dict)]
        genres = [item.get('name') for item in tags.get('genre') or [] if isinstance(item, dict)]
        props = [item.get('name') for field in ('subgenre', 'original') for item in tags.get(field) or []
                 if isinstance(item, dict)]
        return self.record(self.title_url(key), label, THUMBS + key + '.png', description=value.get('description') or '',
                           authors=authors, genres=genres, tags=props)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1:
            return [], False
        op = 'Search' if query else 'NewArrivals' if sort == 'updated' else 'Ranking'
        data = self.post(http, 'graphql', {'query': QUERIES[op], 'operationName': op})
        if query:
            needle = compare(query)
            result = [item for item in items(data, 'honshiMangas') if any(needle in compare(value)
                      for value in [*strings(item.get('searchKeywords')), str(item.get('title') or '')])]
        else:
            blocks = (data.get('featured') or {}).get('sections') or []
            result = [item for block in blocks for item in block.get('items') or []]
        return [row for item in result if (row := self.summary(item, catalogue=True))], False

    def title_data(self, http, url):
        key = self.title_key(url)
        if not key:
            raise SourceError('Некорректная карточка MangaBox.')
        payload = self.post(http, 'jsonrpc', {'jsonrpc': '2.0', 'method': 'get_all_episodes_by_manga_id',
                                            'params': {'mangaId': key, 'withTags': 1}})
        row = self.summary(payload)
        if not row or str(payload.get('id')) != key:
            raise SourceError('MangaBox подменил выбранный тайтл.')
        return row, payload

    def details(self, http, value):
        return self.title_data(http, self.saved_title_url(value))[0]

    def chapters(self, url, payload):
        now = int(time())
        entries = {}
        for item in items(payload, 'episodes'):
            key = str(item.get('id') or '')
            if not re.fullmatch(ID, key) or (item.get('downloadableDate') or 0) > now:
                continue
            available = (item.get('publishedDate') or 0) <= now < (item.get('expiredDate') or 0)
            date = uploaded(item.get('appearedDate') or item.get('publishedDate'))
            ordinal = number(item.get('volume'))
            name = str(item.get('displayVolume') or (f'第{ordinal:g}話' if ordinal is not None else 'Chapter'))
            target = self.title_url(self.title_key(url)) + key + '/'
            if not available:
                target = query_url(target, mv_mbox_locked=1)
            row = self.chapter(target, ('🔒 ' if not available else '') + name, ordinal, date=date)
            if not available:
                row['available'] = False
            entries[target] = row
        return self.order(entries)

    def pages(self, http, url):
        if param(url, 'mv_mbox_locked') == '1':
            raise SourceAccessError('Глава доступна на условиях MangaBox.')
        identity = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)[2]
        result = self.json(http, API + f'/episode/{identity}/images', url)
        key = result.get('mask')
        if type(key) is not int or not -128 <= key <= 255:
            raise SourceAccessError('MangaBox не предоставил открытые страницы.')
        refs = [(query_url(API + '/image', d=token), XorPage(bytes([key & 255])))
                for token in strings(result.get('imageUrls')) if IMAGE_KEY.fullmatch(token)]
        return remember(refs, url)

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_title(url):
            return super().inspect(url, http)
        row, payload = self.title_data(http, url)
        return self.reader_result(row, url, self.chapters(url, payload), [])


SOURCES = (MangaBox(),)
