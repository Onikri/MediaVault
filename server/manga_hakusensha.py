"""Hakusensha e-net public guest catalogue and free browser reader."""

import re
from threading import Lock
from time import monotonic, time
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup
from requests import RequestException

from manga_clipstudio import endpoint, json_data, viewer_pages
from manga_direct_payloads import JsonSeries, strings
from manga_madara import SEGMENT, image_url
from manga_rayuba import uploaded
from manga_series_port import number
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://www.hakusensha-e.net'
PRODUCT = 'https://product.api.hakusensha-e.net/v1'
READER = 'https://reader.api.hakusensha-e.net/v1'
ASSETS = 'https://assets.hakusensha-e.net/'
TITLE = rf'/store/(?:group|koma/product)/({SEGMENT})/?'
CHAPTER = rf'/store/(?:group|koma/product)/({SEGMENT})/read/({SEGMENT})/?'
GUEST_PATTERN = re.compile(rb'\bguestToken\s*:\s*\{\s*token\s*:\s*["\']([A-Za-z0-9]{32})["\']')
GUEST = re.compile(r'[A-Za-z0-9]{32}')
GENRES = ('ラブ', 'ファンタジー', '学園', 'アクション', 'コメディ', 'ミステリー', 'ヒューマンドラマ',
          'スポーツ・音楽・芸能', '青春・友情', '感動モノ', '時代モノ', 'SF', 'グルメ', '絵本', 'BLコミック')


def public_api(host, path, query):
    pairs = parse_qsl(query)
    args = dict(pairs)
    if len(args) != len(pairs):
        return False
    if host == 'reader.api.hakusensha-e.net':
        return bool(re.fullmatch(rf'/v1/keys/(?:koma/)?free/{SEGMENT}', path)) and args == {'viewer': 'bs', 'platform': 'web'}
    if host != 'product.api.hakusensha-e.net':
        return False
    if path == '/v1/ranking/week':
        return (set(args) == {'platform', 'type', 'ts'} and args['platform'] == 'web' and args['type'] == 'comic'
                and bool(re.fullmatch(r'\d{13}', args['ts'])))
    if path == '/v1/search/keyword':
        return set(args) == {'type', 'keyword'} and args['type'] == 'keyword' and 1 <= len(args['keyword']) <= 160
    if path == '/v1/search/product':
        return args in ({'type': 'new'}, {'type': 'free'})
    if path == '/v1/search/group':
        return args == {'type': 'complete'} or (set(args) == {'type', 'target'} and
                args['type'] == 'category' and args['target'] in GENRES)
    return not query and bool(re.fullmatch(rf'/v1/products/group/{SEGMENT}', path))


class Hakusensha(JsonSeries):
    def __init__(self):
        super().__init__(('3812676510487645204', 'Hakusensha e-net', 'ja', ROOT, True), TITLE, CHAPTER, interval=.35)
        self.token_guard = Lock()
        self.guest = ('', 0.)

    def guest_token(self, http):
        with self.token_guard:
            if self.guest[1] > monotonic():
                return self.guest[0]
            raw, final, _ = http.document(ROOT + '/')
            if urlsplit(final).netloc != 'www.hakusensha-e.net':
                raise SourceError('Hakusensha перенаправил конфигурацию.')
            doc = BeautifulSoup(raw, 'html.parser')
            asset = next((node['src'] for node in doc.select('script[src]')
                          if re.fullmatch(r'/?main\.[a-f0-9]{8,32}\.js', node['src'])), None)
            if not asset:
                raise SourceError('Hakusensha не предоставил конфигурацию гостевого режима.')
            target = endpoint(asset, ROOT + '/')
            response, landed = http._open(target, headers={'Referer': ROOT + '/'})
            try:
                if target != landed:
                    raise SourceError('Hakusensha перенаправил запрос конфигурации.')
                tail, size = b'', 0
                for block in response.iter_content(65536):
                    size += len(block)
                    if size > 16 * 1024 * 1024:
                        break
                    data = tail + block
                    if found := GUEST_PATTERN.search(data):
                        self.guest = (found[1].decode('ascii'), monotonic() + 900)
                        return self.guest[0]
                    tail = data[-256:]
            except RequestException:
                raise SourceError('Hakusensha прервал выдачу гостевой конфигурации.') from None
            finally:
                response.close()
            raise SourceError('Hakusensha изменил конфигурацию гостевого режима.')

    def api(self, http, target):
        self.origin.wait(getattr(http, 'deadline', None))
        token = self.guest_token(http)
        raw, final, _ = http.document(target, headers={'Referer': ROOT + '/', 'Hakusensha-Guest': token},
                                      action='hakusensha-public')
        if final != target:
            raise SourceError('Hakusensha перенаправил гостевой запрос.')
        return json_data(raw)

    def title_url(self, key, kind):
        return ROOT + ('/store/koma/product/' if kind == 'koma' else '/store/group/') + key

    def title_for(self, url):
        if not self.is_chapter(url):
            return ''
        return ROOT + urlsplit(url).path.rsplit('/read/', 1)[0]

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        return self.title_url(key, '') if re.fullmatch(SEGMENT, key) else url if self.is_title(url) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        key = urlsplit(url).path.strip('/')
        return title.rstrip('/') + '/read/' + key if self.is_title(title) and re.fullmatch(SEGMENT, key) else ''

    def cover(self, value):
        return image_url(value, ASSETS) if isinstance(value, str) and value else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1:
            return [], False
        if query:
            data = self.api(http, query_url(PRODUCT + '/search/keyword', type='keyword', keyword=query))
        elif tag in GENRES:
            data = self.api(http, query_url(PRODUCT + '/search/group', type='category', target=tag))
        elif sort == 'updated':
            data = self.api(http, query_url(PRODUCT + '/search/product', type='new'))
        else:
            response = self.api(http, query_url(PRODUCT + '/ranking/week', platform='web', type='comic',
                                                ts=int(time() * 1000)))
            data = {'groups': [entry.get('product') for entry in response.get('ranking') or [] if isinstance(entry, dict)]}
        rows = {}
        for item in data.get('groups') or data.get('products') or []:
            if not isinstance(item, dict):
                continue
            key, title = item.get('product_group_name'), item.get('product_group_title') or item.get('product_search_title')
            if isinstance(key, str) and re.fullmatch(SEGMENT, key) and isinstance(title, str) and title:
                dest = self.title_url(key, item.get('type'))
                rows[dest] = self.record(dest, title, self.cover(item.get('cover_image')))
        return list(rows.values()), False

    def vocabulary(self, http):
        return [{'key': tag, 'label': tag, 'kind': 'genre'} for tag in GENRES]

    def listed(self, http, title):
        key = self.title_key(title)
        result = self.api(http, PRODUCT + '/products/group/' + key)
        return sorted((item for item in result.get('products') or [] if isinstance(item, dict)),
                      key=lambda item: number(item.get('product_order')) or 0)

    def series(self, http, url):
        data = self.listed(http, url)
        if not data or not isinstance(title := data[0].get('product_group_title'), str):
            raise SourceError('Hakusensha не предоставил карточку произведения.')
        first = data[0]
        authors = [author['author_name'] for author in first.get('author') or [] if isinstance(author, dict)
                   and isinstance(author.get('author_name'), str)]
        row = self.record(url, title, self.cover(data[-1].get('cover_image')), authors=authors,
                          description=str(first.get('introduction') or ''), genres=strings(first.get('category')))
        episodes = {}
        for item in data:
            key = item.get('product_name')
            if (not isinstance(key, str) or not re.fullmatch(SEGMENT, key)
                    or (number(item.get('release_at')) or 0) > time() * 1000):
                continue
            name = str(item.get('product_order_title') or '')
            if not item.get('is_free_streaming') or str(item.get('type') or '').startswith('novel'):
                name = '🔒 ' + name
            dest = url.rstrip('/') + '/read/' + key
            episodes[dest] = self.chapter(dest, name, number(item.get('product_order')), uploaded(item.get('release_at')))
        return row, self.order(episodes)

    def pages(self, http, url):
        title = self.title_for(url)
        key = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)[2]
        item = next((item for item in self.listed(http, title) if item.get('product_name') == key), None)
        if not item or item.get('is_free_streaming') is not True or str(item.get('type') or '').startswith('novel'):
            raise SourceAccessError('Hakusensha ограничивает доступ к выпуску.')
        route = '/keys/koma/free/' if item.get('type') == 'koma' else '/keys/free/'
        data = self.api(http, query_url(READER + route + key, platform='web', viewer='bs'))
        viewer = (data.get('bs') or {}).get('url')
        if not isinstance(viewer, str) or not viewer:
            raise SourceAccessError('Hakusensha не предоставил открытую читалку.')
        return viewer_pages(http, endpoint(viewer, ROOT + '/'), url)


SOURCES = (Hakusensha(),)
