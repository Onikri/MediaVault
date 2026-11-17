"""Japanese readers that answer only from Japan (Keiyoushi, Apache-2.0, 6f345a8).

Ports of ``ja/fodfuji``, ``ja/linemanga``, ``ja/sokuyomi`` and ``ja/soraraw``.
Their requests travel through the admin-configured Japan route
(``manga-source-routes.json`` → ``suwayomi-jp-router``), the same one the
Suwayomi server uses, and only for hosts listed there. Nothing here logs in:
only chapters a guest may open are listed. Page images are descrambled exactly
as the extensions' interceptors do (``manga_japan_scramble``).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import html
import json
import re
import threading
import time
from urllib.parse import parse_qsl, urlsplit

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from manga_direct_payloads import JsonSeries
from manga_japanese_readers import JapanesePage, packed_refs
from manga_madara import image_url
from manga_ninth_routes import Route, register
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError, SourceTemporaryError

FOD = 'https://manga.fod.fujitv.co.jp'
LINE = 'https://manga.line.me'
SOKU = 'https://sokuyomi.jp'
SOKU_API = 'https://api.sokuyomi.jp/graphql'
SOKU_CDN = 'https://cdn.sokuyomi.jp'
SORA = 'https://soraraw.com'
SORA_THUMBS = 'https://i.mangaraw.lat'
SORA_MANIFEST_HOSTS = frozenset({'api.mangarawgo.site'})
NUMERIC = r'[0-9]{1,12}'
PAGE = r'[1-9][0-9]{0,3}'
JST = timezone(timedelta(hours=9))


def query_args(url, limit=8):
    try:
        fields = parse_qsl(url.query, keep_blank_values=True, max_num_fields=limit)
    except ValueError:
        return None
    args = dict(fields)
    return args if len(args) == len(fields) else None


def loads(raw, name):
    try:
        return json.loads(raw)
    except (TypeError, ValueError, RecursionError):
        raise SourceError(f'{name} изменил формат ответа.') from None


def as_dict(value):
    return value if isinstance(value, dict) else {}


def as_list(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def text(value):
    return value.strip() if isinstance(value, str) else ''


def day(value):
    value = text(value)
    return value[:10] if re.fullmatch(r'[0-9]{4}[-/][0-9]{2}[-/][0-9]{2}.*', value) else ''


@dataclass(frozen=True)
class RoutedPage(JapanesePage):
    """A page fetched (through the Japan route when its action asks) and descrambled."""
    action: str = ''
    cookie: str = ''
    scheme: str = ''

    def fetch(self, http, referer):
        from manga_japan_scramble import apply
        from manga_page_media import read_image

        headers = {'Referer': referer}
        if self.cookie:
            headers['Fod-Cookie'] = self.cookie
        response, _ = http._open(self.url, headers=headers, action=self.action or None)
        return apply(read_image(http, response), self.scheme)


# ====================================================================== FOD

FOD_API = {
    'genreRanking': {'category': r'0', 'sort_type': r'2', 'page': PAGE},
    'newArrival': {'category': r'0', 'sort_type': r'0', 'page': PAGE},
    'search': {'keyword': r'.{1,160}', 'page': PAGE},
    'detail': {'book_id': NUMERIC, 'episode_id': r'[A-Za-z0-9]{1,64}'},
    'licenceKey': {'book_id': NUMERIC, 'episode_id': r'[A-Za-z0-9]{1,64}'},
}
CLOUDFRONT = re.compile(r'CloudFront-(?:Policy|Signature|Key-Pair-Id)=[A-Za-z0-9_~=-]{1,4096}'
                        r'(?:; CloudFront-(?:Policy|Signature|Key-Pair-Id)=[A-Za-z0-9_~=-]{1,4096}){2}')


def fod_route(url, method, data, headers):
    if method != 'GET' or data is not None:
        return None
    if url.netloc == 'manga.fod.fujitv.co.jp':
        match = re.fullmatch(r'/web/books/(\w+)', url.path)
        rules = FOD_API.get(match[1]) if match else None
        args = query_args(url)
        if not rules or args is None or set(args) != set(rules):
            return None
        if not all(re.fullmatch(pattern, args[key], re.S) for key, pattern in rules.items()):
            return None
        return Route({'Zk-Web-Version': '1.3.5', 'X-Requested-With': 'XMLHttpRequest',
                      'Accept': 'application/json', 'Cookie': 'sfsc=0'}, redirect=False, japan=True)
    if url.netloc.endswith('.manga.fod.fujitv.co.jp') and url.path.startswith('/books_file/'):
        cookie = headers.get('Fod-Cookie', '')
        if not CLOUDFRONT.fullmatch(cookie) or not re.fullmatch(r'/books_file/[A-Za-z0-9_/.-]{1,400}', url.path):
            return None
        return Route({'Cookie': cookie}, redirect=False, japan=True)
    return None


register('fod', fod_route)


class Fod(JsonSeries):
    index_sort = 'updated'

    def __init__(self):
        super().__init__(('813084616937908482', 'FOD', 'ja', FOD, True),
                         r'/books/([0-9]{1,12})/([A-Za-z0-9]{1,64})/?', r'/viewer/([0-9]{1,12})/([A-Za-z0-9]{1,64})/?',
                         interval=.4)

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(self.title_for(url))

    def title_for(self, url):
        series, episode = param(url, 'mv_series'), param(url, 'mv_episode')
        if re.fullmatch(NUMERIC, series) and re.fullmatch(r'[A-Za-z0-9]{1,64}', episode):
            return f'{FOD}/books/{series}/{episode}'
        return ''

    def title_identity(self, url):
        # The episode in a FOD title link is only the one the listing was built
        # from (rankings and search name different ones); the book is the title.
        match = self.TITLE_PATH.fullmatch(urlsplit(url).path)
        return 'books/' + match[1] if match else super().title_identity(url)

    def ids(self, url, pattern):
        match = pattern.fullmatch(urlsplit(url).path)
        if not match:
            raise SourceError('Некорректная ссылка FOD.')
        return match[1], match[2]

    def saved_title_url(self, url):
        return self.canonical(url)

    def api(self, http, name, **args):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, _ = http.document(query_url(f'{FOD}/web/books/{name}', **args), headers={'Referer': FOD + '/'},
                                  action='n9:fod')
        data = loads(raw, 'FOD')
        if not isinstance(data, dict):
            raise SourceError('FOD изменил формат ответа.')
        return data

    def record_from(self, item):
        book, episode, name = str(item.get('book_id') or ''), str(item.get('episode_id') or ''), text(item.get('book_name'))
        if not re.fullmatch(NUMERIC, book) or not re.fullmatch(r'[A-Za-z0-9]{1,64}', episode) or not name:
            return None
        description = re.sub(r'<[^>]+>', '\n', html.unescape(str(item.get('book_review_long') or '')))
        names = lambda key: [text(entry.get('name')) for entry in as_list(item.get(key))]
        return self.record(f'{FOD}/books/{book}/{episode}', name, image_url(item.get('thumbnail'), FOD),
                           description=re.sub(r'\n{3,}', '\n\n', description).strip()[:12000],
                           genres=names('genres') + names('sub_genres'), authors=names('authors'))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag:
            return [], False
        if query:
            data = self.api(http, 'search', keyword=query, page=page)
            info = as_dict(data.get('search_info'))
            items, more = data.get('search_books'), info.get('end_page_num', 0) < info.get('search_result_num', 0)
        elif sort == 'updated':
            data = self.api(http, 'newArrival', category=0, sort_type=0, page=page)
            items, more = data.get('new_arrival_books'), data.get('current_page', 0) < data.get('total', 0)
        elif page == 1:
            data = self.api(http, 'genreRanking', category=0, sort_type=2, page=1)
            items, more = data.get('ranking_books'), False
        else:
            return [], False
        if not isinstance(items, list):
            raise SourceError('FOD не вернул каталог.')
        rows = [row for row in map(self.record_from, as_list(items)) if row]
        return rows, bool(rows and more is True)

    def series(self, http, url):
        book, episode = self.ids(self.canonical(url), self.TITLE_PATH)
        data = self.api(http, 'detail', book_id=book, episode_id=episode)
        detail = as_dict(data.get('book_detail'))
        row = self.record_from(detail)
        if not row or str(detail.get('book_id')) != book:
            raise SourceError('FOD вернул карточку другого тайтла.')
        chapters = {}
        for item in as_list(data.get('book_series')):
            cid, eid = str(item.get('book_id') or ''), str(item.get('episode_id') or '')
            # Guests open only free episodes; purchases need the owner's account.
            if item.get('is_free') is not True or not re.fullmatch(NUMERIC, cid) or not re.fullmatch(r'[A-Za-z0-9]{1,64}', eid):
                continue
            target = query_url(f'{FOD}/viewer/{cid}/{eid}', mv_series=book, mv_episode=episode)
            count = item.get('episode_count')
            chapters[target] = self.chapter(target, text(item.get('book_name')), count if type(count) is int else None,
                                            day(item.get('episode_price_start')))
        return row, self.order(chapters)

    def pages(self, http, url):
        book, episode = self.ids(url, self.CHAPTER_PATH)
        data = self.api(http, 'licenceKey', book_id=book, episode_id=episode)
        book_data, pages = data.get('book_data'), as_dict(data.get('pages_data'))
        server = text(data.get('GUARDIAN_SERVER'))
        if not isinstance(book_data, dict) or not server:
            raise SourceAccessError('FOD открывает эту главу только после покупки.')
        session = getattr(http, 'session', None)
        jar = getattr(session, 'cookies', None) or []
        cookie = '; '.join(f'{c.name}={c.value}' for c in jar if str(getattr(c, 'name', '')).startswith('CloudFront-'))
        # OkHttp reads the escaped "\/" of the key as "/", and the CloudFront
        # cookie path is issued for that doubled-slash form.
        base = (server + '/' + text(book_data.get('s3_key'))).replace('\\', '/')
        if not image_url(base, FOD).startswith('https://') or not urlsplit(base).netloc.endswith('.manga.fod.fujitv.co.jp'):
            raise SourceError('FOD изменил адрес страниц.')
        signed = text(data.get('ADDITIONAL_QUERY_STRING'))
        suffix = '?' + signed if signed else ''
        keys = pages.get('keys')
        if book_data.get('imaged_reflow') is True:
            book_json = RoutedPage(f'{base}/book.json{suffix}', action='n9:fod', cookie=cookie)
            response, _ = http._open(book_json.url, headers={'Referer': url, 'Fod-Cookie': cookie}, action='n9:fod')
            try:
                profiles = as_list(as_dict(json.loads(response.content).get('reflowData')).get('profiles'))
            except (ValueError, AttributeError):
                raise SourceError('FOD изменил формат книги.') from None
            finally:
                response.close()
            profile = next((p for p in profiles if p.get('id') == 'mincho_medium'), profiles[0] if profiles else None)
            if not profile or not isinstance(keys, dict):
                raise SourceError('FOD не предоставил страницы книги.')
            count = as_dict(profile.get('bookInfo')).get('page_count')
            key = str(keys.get(profile['id']) or '')
            names = [f"{profile['id']}/{index + 1}.jpg" for index in range(count if type(count) is int else 0)]
            page_keys = [key] * len(names)
        else:
            if not isinstance(keys, list):
                raise SourceError('FOD не предоставил ключи страниц.')
            names = [f'{index + 1}.jpg' for index in range(len(keys))]
            page_keys = [str(key) for key in keys]
        rows = [RoutedPage(f'{base}/{name}{suffix}', action='n9:fod', cookie=cookie, scheme='fod:' + key)
                for name, key in zip(names, page_keys)]
        return packed_refs(rows, url)


# ====================================================================== LINE Manga

LINE_API = {
    '/api/periodic/gender_ranking': ({'gender', 'page'}, {'gender': r'[01]', 'page': PAGE}),
    '/api/daily_list': ({'week_day', 'page'}, {'week_day': r'[1-7]', 'page': PAGE}),
    '/api/search_product/list': ({'word', 'page'}, {'word': r'.{1,160}', 'page': PAGE}),
}
LINE_PRODUCT = r'[A-Z][0-9]{1,15}'
LINE_BOOK = r'[A-Za-z0-9_-]{1,64}'


def line_route(url, method, data, headers):
    if method != 'GET' or data is not None or url.netloc != 'manga.line.me':
        return None
    args = query_args(url)
    if args is None:
        return None
    if url.path in LINE_API:
        keys, rules = LINE_API[url.path]
        if set(args) != keys or not all(re.fullmatch(rules[k], args[k], re.S) for k in keys):
            return None
    elif url.path == '/api/book/product_list':
        if not re.fullmatch(LINE_PRODUCT, args.get('product_id', '')):
            return None
        if set(args) != {'product_id'} and args != {'product_id': args['product_id'], 'need_read_info': '1',
                                                     'rows': '1000', 'is_periodic': '1'}:
            return None
    elif url.path == '/book/viewer':
        if set(args) != {'id'} or not re.fullmatch(LINE_BOOK, args['id']):
            return None
        return Route({}, redirect=False, japan=True)
    else:
        return None
    return Route({'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}, redirect=False, japan=True)


register('linemanga', line_route)


def line_locked(row):
    price = row.get('selling_buy_price')
    if price is None:
        return row.get('fin_of_purchase') != 1
    if row.get('expired_on') is not None:
        return False
    return not isinstance(price, int) or price > 0


def line_thumbnail(value):
    url = image_url(value, LINE)
    if not url:
        return ''
    parts = urlsplit(url)
    segments = parts.path.split('/')
    if len(segments) > 2:
        del segments[2]
    return parts._replace(path='/'.join(segments)).geturl()


class LineManga(JsonSeries):
    def __init__(self):
        super().__init__(('7324763859222949244', 'Line Manga', 'ja', LINE, True),
                         r'(/product/periodic)', r'(/book/viewer)', interval=.4)

    def title_key(self, url):
        value = param(url, 'id')
        return value if super().is_title(url) and re.fullmatch(LINE_PRODUCT, value) else ''

    def is_title(self, url):
        return bool(self.title_key(url))

    def chapter_key(self, url):
        value = param(url, 'id')
        return value if super().is_chapter(url) and re.fullmatch(LINE_BOOK, value) else ''

    def is_chapter(self, url):
        return bool(self.chapter_key(url) and re.fullmatch(LINE_PRODUCT, param(url, 'mv_product')))

    def chapter_identity(self, url):
        return self.chapter_key(url)

    def title_for(self, url):
        product = param(url, 'mv_product')
        return query_url(LINE + '/product/periodic', id=product) if re.fullmatch(LINE_PRODUCT, product) else ''

    def saved_title_url(self, url):
        if isinstance(url, str) and re.fullmatch(LINE_PRODUCT, url):
            return query_url(LINE + '/product/periodic', id=url)
        return self.canonical(url)

    def api(self, http, path, **args):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, _ = http.document(query_url(LINE + path, **args), headers={'Referer': LINE + '/'}, action='n9:linemanga')
        data = loads(raw, 'LINE Manga')
        if not isinstance(data, dict):
            raise SourceError('LINE Manga изменила формат ответа.')
        return data

    def record_from(self, item):
        pid, name = text(item.get('id')), text(item.get('series_name') or item.get('name'))
        if not re.fullmatch(LINE_PRODUCT, pid) or not name or item.get('is_light_novel') is True:
            return None
        description = '\n\n'.join(part for part in (text(item.get('caption')), text(item.get('explanation')),
                                                    text(item.get('periodic_description'))) if part)
        conclusion = item.get('conclusion')
        row = self.record(query_url(LINE + '/product/periodic', id=pid), name, line_thumbnail(item.get('thumbnail')),
                          description=description[:12000], genres=[text(item.get('genre_name'))],
                          authors=[text(a.get('name')) for a in as_list(item.get('authors'))],
                          status='completed' if conclusion is True else 'ongoing' if conclusion is False else '')
        if item.get('is_restricted18') is True:
            row['adult'] = True
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag:
            return [], False
        if query:
            data = as_dict(self.api(http, '/api/search_product/list', word=query, page=page).get('result'))
        elif sort == 'updated':
            weekday = (datetime.now(JST).isoweekday() % 7) + 1
            data = self.api(http, '/api/daily_list', week_day=weekday, page=page)
            data = as_dict(data.get('result')) or data
        else:
            data = as_dict(self.api(http, '/api/periodic/gender_ranking', gender=0, page=page).get('result'))
        items = data.get('items') if isinstance(data.get('items'), list) else data.get('rows')
        if not isinstance(items, list):
            raise SourceError('LINE Manga не вернула каталог.')
        rows = [row for row in map(self.record_from, as_list(items)) if row]
        return rows, bool(rows and as_dict(data.get('pager')).get('hasNext') is True)

    def series(self, http, url):
        pid = self.title_key(self.canonical(url))
        if not pid:
            raise SourceError('Некорректная ссылка LINE Manga.')
        args = {} if pid.startswith('E') else {'need_read_info': 1, 'rows': 1000, 'is_periodic': 1}
        result = as_dict(self.api(http, '/api/book/product_list', product_id=pid, **args).get('result'))
        product = as_dict(result.get('product'))
        row = self.record_from({**product, 'id': pid})
        if not row:
            raise SourceError('LINE Manga не предоставила карточку тайтла.')
        series_name = text(product.get('series_name'))
        chapters = {}
        for item in as_list(result.get('rows')):
            bid = text(item.get('id'))
            if not re.fullmatch(LINE_BOOK, bid):
                continue
            name = text(item.get('name'))
            if series_name:
                name = name.replace(series_name, '').strip() or name
            volume = item.get('volume')
            target = query_url(LINE + '/book/viewer', id=bid, mv_product=pid)
            chapters[target] = {**self.chapter(target, name, volume + 1 if type(volume) is int else None,
                                               day(item.get('permit_start')).replace('/', '-')),
                                'locked': line_locked(item)}
        return row, self.order(chapters)

    def pages(self, http, url):
        bid = self.chapter_key(url)
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, _ = http.document(query_url(LINE + '/book/viewer', id=bid), headers={'Referer': LINE + '/'},
                                  action='n9:linemanga')
        imgs, portal, in_portal, is_portal = [], [], False, False
        quoted = lambda line: (re.search(r"'([^']*)'\s*[,;]?\s*$", line) or [None, ''])[1]
        numeric = lambda line: int((re.search(r'(\d+)\s*,?\s*$', line) or [None, '0'])[1])
        for line in raw.splitlines():
            line = line.lstrip()
            if line.startswith('imgs['):
                in_portal = False
            elif line.startswith('portal_pages['):
                if '.metadata.m[' in line and portal:
                    portal[-1]['m'].append(quoted(line))
                else:
                    in_portal = True
            elif line.startswith("'url'"):
                value = quoted(line)
                if in_portal:
                    portal.append({'url': value, 'hc': 0, 'bwd': 0, 'm': []})
                else:
                    imgs.append(value)
            elif line.startswith("'hc'") and portal:
                portal[-1]['hc'] = numeric(line)
            elif line.startswith("'bwd'") and portal:
                portal[-1]['bwd'] = numeric(line)
            elif line.startswith('isPortal'):
                is_portal = 'true' in line
        if is_portal:
            rows = [RoutedPage(image_url(page['url'], LINE),
                               scheme=f"line:{page['hc']}:{page['bwd']}:" + ':'.join(page['m'])) for page in portal]
            return packed_refs(rows, url)
        pages = [image_url(value, LINE) for value in imgs if 'inline_ads_banner' not in value]
        if not pages or not all(pages):
            raise SourceAccessError('LINE Manga не открыла эту главу без покупки.')
        return pages


# ====================================================================== Sokuyomi

SOKU_FIELDS = 'pageInfo { totalPage currentPage } edges { node { name slug title_cover { key } } }'
SOKU_QUERIES = {
    'ListTitle': (
        'query ListTitle($keyword: String, $tagSlug: String, $perPage: Int!, $pageNumber: Int!, '
        '$field: PostOrderFields!, $sort: PostOrderSorts!) { listTitle(input: {name: {contains: $keyword}, '
        'author_name: {contains: $keyword}, tag_name: {contains: $keyword}, tag_slug: {eq: $tagSlug}} '
        'page: {perPage: $perPage, pageNumber: $pageNumber} orderBy: {field: $field, sort: $sort}) { '
        + SOKU_FIELDS + ' } }'),
    'GetTitle': (
        'query GetTitle($titleSlug: String!) { getTitle(input: {slug: {eq: $titleSlug}}) { name name_hiragana '
        'name_katakana description is_adult is_finished label { publisher { name } } genre { name } '
        'title_cover { origin_key } authors { name } tags { name } } '
        'listVolume(input: {title_slug: {eq: $titleSlug}} page: {perPage: 1000, pageNumber: 0} '
        'orderBy: {field: VOLUME_NUMBER, sort: DESC}) { edges { node { volume_number name consumption_coin '
        'opend_at slug is_purchase is_available_for_sale volume_consumption_coin { consumption_coin } } } } '
        'listChapter(input: {title_slug: {eq: $titleSlug}} page: {perPage: 1000, pageNumber: 0} '
        'orderBy: {field: CHAPTER_NUMBER, sort: DESC}) { edges { node { chapter_number name consumption_coin '
        'opend_at slug is_purchase is_available_for_sale chapter_consumption_coin { consumption_coin } } } } }'),
    'GetVolumeViewer': ('query GetVolumeViewer($slug: String!) { getVolumeViewer(input: {volume_slug: {eq: $slug}}) '
                        '{ volume_pages { page_number key } } }'),
    'GetChapterViewer': ('query GetChapterViewer($slug: String!) { getChapterViewer(input: {chapter_slug: {eq: $slug}}) '
                         '{ chapter_pages { page_number key } } }'),
}
SOKU_SLUG = r'[a-z0-9]{8,64}'


def soku_variables(operation, variables):
    if not isinstance(variables, dict):
        return False
    if operation == 'ListTitle':
        allowed = {'perPage', 'pageNumber', 'field', 'sort', 'keyword', 'tagSlug'}
        return (set(variables) <= allowed and {'perPage', 'pageNumber', 'field', 'sort'} <= set(variables)
                and variables['perPage'] in (20, 50) and type(variables['pageNumber']) is int
                and 0 <= variables['pageNumber'] < 2000 and variables['field'] in {'LIKE_COUNT', 'LATEST_BOOK_OPEND_AT'}
                and variables['sort'] in {'ASC', 'DESC'}
                and all(isinstance(variables.get(k, ''), str) and len(variables.get(k, '')) <= 160 for k in ('keyword', 'tagSlug')))
    key = 'titleSlug' if operation == 'GetTitle' else 'slug'
    return set(variables) == {key} and isinstance(variables[key], str) and bool(re.fullmatch(SOKU_SLUG, variables[key]))


def soku_route(url, method, data, headers):
    if method != 'POST' or url.netloc != 'api.sokuyomi.jp' or url.path != '/graphql' or url.query:
        return None
    if not isinstance(data, dict) or set(data) != {'operationName', 'query', 'variables'}:
        return None
    operation = data['operationName']
    if SOKU_QUERIES.get(operation) != data['query'] or not soku_variables(operation, data['variables']):
        return None
    return Route({'Client-Version': datetime.now(JST).strftime('%Y%m%d'), 'Content-Type': 'application/json',
                  'Accept': 'application/json', 'Origin': SOKU, 'Referer': SOKU + '/'}, post=True,
                 data=json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode(), redirect=False, japan=True)


register('sokuyomi', soku_route)


def soku_locked(node, coin_key):
    campaign = as_dict(node.get(coin_key)).get('consumption_coin')
    return (node.get('consumption_coin') != 0 and node.get('is_purchase') is not True
            and (campaign != 0 or node.get('is_available_for_sale') is not True))


class Sokuyomi(JsonSeries):
    def __init__(self):
        super().__init__(('3115293328774708452', 'Sokuyomi', 'ja', SOKU, True),
                         rf'/comics/({SOKU_SLUG})/detail/?', rf'/viewer/(chapter|volume)/({SOKU_SLUG})/?', interval=.4)

    def chapter_parts(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return (match[1], match[2]) if match else ('', '')

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(re.fullmatch(SOKU_SLUG, param(url, 'mv_title')))

    def title_for(self, url):
        slug = param(url, 'mv_title')
        return f'{SOKU}/comics/{slug}/detail/' if re.fullmatch(SOKU_SLUG, slug) else ''

    def saved_title_url(self, url):
        if isinstance(url, str) and re.fullmatch(SOKU_SLUG, url):
            return f'{SOKU}/comics/{url}/detail/'
        return self.canonical(url)

    def gql(self, http, operation, variables):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, _ = http.document(SOKU_API, method='POST', headers={'Referer': SOKU + '/'}, action='n9:sokuyomi',
                                  data={'operationName': operation, 'query': SOKU_QUERIES[operation], 'variables': variables})
        data = loads(raw, 'Sokuyomi')
        if not isinstance(data, dict):
            raise SourceError('Sokuyomi изменил формат ответа.')
        if data.get('errors') or not isinstance(data.get('data'), dict):
            raise SourceAccessError('Sokuyomi открывает этот выпуск только после входа или покупки.')
        return data['data']

    def node_row(self, node):
        slug, name = text(node.get('slug')), text(node.get('name'))
        if not re.fullmatch(SOKU_SLUG, slug) or not name:
            return None
        cover = as_dict(node.get('title_cover'))
        key = text(cover.get('origin_key') or cover.get('key'))
        return self.record(f'{SOKU}/comics/{slug}/detail/', name, f'{SOKU_CDN}/{key}' if key else '')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag:
            return [], False
        variables = {'perPage': 50, 'pageNumber': page - 1, 'sort': 'DESC',
                     'field': 'LATEST_BOOK_OPEND_AT' if sort == 'updated' and not query else 'LIKE_COUNT'}
        if query:
            variables['keyword'] = query
        result = as_dict(self.gql(http, 'ListTitle', variables).get('listTitle'))
        info = as_dict(result.get('pageInfo'))
        rows = [row for edge in as_list(result.get('edges')) if (row := self.node_row(as_dict(edge.get('node'))))]
        more = type(info.get('currentPage')) is int and type(info.get('totalPage')) is int and info['currentPage'] + 1 < info['totalPage']
        return rows, bool(rows and more)

    def series(self, http, url):
        slug = self.title_key(self.canonical(url))
        data = self.gql(http, 'GetTitle', {'titleSlug': slug})
        title = as_dict(data.get('getTitle'))
        row = self.node_row({**title, 'slug': slug})
        if not row:
            raise SourceError('Sokuyomi не предоставил карточку тайтла.')
        row.update(aliases=list(dict.fromkeys(a for a in (row['title'], text(title.get('name_hiragana')),
                                                           text(title.get('name_katakana'))) if a)),
                   description=text(title.get('description'))[:12000],
                   authors=[text(a.get('name')) for a in as_list(title.get('authors')) if text(a.get('name'))],
                   genres=[g for g in [text(as_dict(title.get('genre')).get('name'))] if g],
                   tags=[text(t.get('name')) for t in as_list(title.get('tags')) if text(t.get('name'))],
                   status='completed' if title.get('is_finished') is True else 'ongoing')
        if title.get('is_adult') is True:
            row['adult'] = True
        chapters = {}
        for kind, key, number_key, coin in (('chapter', 'listChapter', 'chapter_number', 'chapter_consumption_coin'),
                                            ('volume', 'listVolume', 'volume_number', 'volume_consumption_coin')):
            for edge in as_list(as_dict(data.get(key)).get('edges')):
                node = as_dict(edge.get('node'))
                cslug = text(node.get('slug'))
                if not re.fullmatch(SOKU_SLUG, cslug):
                    continue
                target = query_url(f'{SOKU}/viewer/{kind}/{cslug}/', mv_title=slug)
                n = node.get(number_key)
                chapters[target] = {**self.chapter(target, text(node.get('name')),
                                                   n if isinstance(n, (int, float)) else None, day(node.get('opend_at'))),
                                    'locked': soku_locked(node, coin)}
        return row, self.order(chapters)

    def pages(self, http, url):
        kind, slug = self.chapter_parts(url)
        operation = 'GetChapterViewer' if kind == 'chapter' else 'GetVolumeViewer'
        viewer = as_dict(self.gql(http, operation, {'slug': slug}).get('get' + operation[3:]))
        pages = as_list(viewer.get('chapter_pages' if kind == 'chapter' else 'volume_pages'))
        pages.sort(key=lambda page: page.get('page_number') if type(page.get('page_number')) is int else 0)
        keys = [text(page.get('key')) for page in pages]
        if not keys or not all(re.fullmatch(r'[A-Za-z0-9/_.-]{1,300}', key) for key in keys):
            raise SourceAccessError('Sokuyomi не открыл этот выпуск без входа.')
        return packed_refs([RoutedPage(f'{SOKU_CDN}/{key}', scheme='sokuyomi') for key in keys], url)


# ====================================================================== SoraRaw

SORA_SLUG = r'[a-z0-9][a-z0-9-]{0,299}'
SORA_CHAPTER = r'[a-z0-9][a-z0-9.-]{0,79}'
SEARCH_FIELDS = ('name', 'slug', 'alt_names', 'author', 'views', 'img', 'is_adult')
MANIFEST_KEY = b'/fuCkYou!!!'
IMAGE_KEY = b'202508055d0db38bae2e86cc41649f90'


def sora_route(url, method, data, headers):
    if method != 'GET' or data is not None:
        return None
    if url.netloc == 'soraraw.com':
        if url.query:
            return None
        if not re.fullmatch(rf'/(?:config\.json|newest(?:/page/{PAGE})?|top/last7Days\.json|mangas_{PAGE}\.json'
                            rf'|manga/{SORA_SLUG}(?:/{SORA_CHAPTER})?)', url.path):
            return None
        return Route({'Referer': SORA + '/'}, redirect=False, japan=True)
    if url.netloc in SORA_MANIFEST_HOSTS:
        args = query_args(url, 2)
        if (args is None or set(args) != {'t'} or not re.fullmatch(r'[0-9]{10,16}', args['t'])
                or not re.fullmatch(r'/[0-9]{1,12}/[0-9]{1,15}\.json', url.path)):
            return None
        return Route({'Referer': SORA + '/', 'Origin': SORA}, redirect=False, japan=True)
    return None


register('soraraw', sora_route)


def next_data(raw):
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', raw, re.S)
    if not match:
        raise SourceError('SoraRaw изменил формат страницы.')
    return as_dict(as_dict(loads(match[1], 'SoraRaw').get('props')).get('pageProps'))


def find(value, test, depth=0):
    """The first dictionary (depth-first) inside Next.js page props that passes test."""
    if depth > 12:
        return {}
    if isinstance(value, dict):
        if test(value):
            return value
        children = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return {}
    for child in children:
        if found := find(child, test, depth + 1):
            return found
    return {}


def b64(value):
    value = value.replace('-', '+').replace('_', '/')
    return base64.b64decode(value + '=' * (-len(value) % 4))


def xor(data, key):
    return bytes(value ^ key[index % len(key)] for index, value in enumerate(data))


class SoraRaw(JsonSeries):
    index_sort = 'updated'
    CATALOG_TTL = 3600

    def __init__(self):
        super().__init__(('8499664924001897518', 'SoraRaw', 'ja', SORA, True),
                         rf'/manga/({SORA_SLUG})/?', rf'/manga/({SORA_SLUG})/({SORA_CHAPTER})/?', interval=.35)
        self.cache_lock = threading.Lock()
        self.search_lock = threading.Lock()
        self.cache = {}

    def is_title(self, url):
        return super().is_title(url) and not self.CHAPTER_PATH.fullmatch(urlsplit(url).path)

    def title_for(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return f'{SORA}/manga/{match[1]}' if match else ''

    def saved_title_url(self, url):
        if isinstance(url, str) and re.fullmatch(SORA_SLUG, url):
            return f'{SORA}/manga/{url}'
        return self.canonical(url)

    def saved_chapter(self, row, root, title):
        value = str(row.get('realUrl') or row.get('url') or '')
        if re.fullmatch(rf'{SORA_SLUG}/{SORA_CHAPTER}', value):
            return f'{SORA}/manga/{value}'
        return super().saved_chapter(row, root, title)

    def get(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, _ = http.document(url, headers={'Referer': SORA + '/'}, action='n9:soraraw')
        return raw

    def cached(self, key, ttl, load):
        with self.cache_lock:
            entry = self.cache.get(key)
            if entry and entry[0] > time.monotonic():
                return entry[1]
        value = load()
        with self.cache_lock:
            self.cache[key] = (time.monotonic() + ttl, value)
        return value

    def config(self, http):
        return self.cached('config', 600, lambda: as_dict(loads(self.get(http, SORA + '/config.json'), 'SoraRaw')))

    def record_from(self, item, adult=None):
        slug, name = text(item.get('slug')), text(item.get('name'))
        if not re.fullmatch(SORA_SLUG, slug) or not name:
            return None
        image = text(item.get('image') or item.get('img'))
        row = self.record(f'{SORA}/manga/{slug}', name, f'{SORA_THUMBS}/{image}' if image else '',
                          aliases=[a.strip() for a in re.split(r'[,、;]', text(item.get('alt_names'))) if a.strip()],
                          authors=[a for a in [text(item.get('author'))] if a and a != '更新中'])
        if (item.get('is_adult') == 'yes') if adult is None else adult:
            row['adult'] = True
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag:
            return [], False
        if query:
            return (self.search(http, query) if page == 1 else []), False
        if sort == 'updated':
            props = next_data(self.get(http, SORA + ('/newest' if page == 1 else f'/newest/page/{page}')))
            listing = find(props, lambda d: isinstance(d.get('results'), list) and isinstance(d.get('pagination'), dict))
            if not isinstance(listing.get('results'), list):
                raise SourceError('SoraRaw не вернул каталог.')
            pager = as_dict(listing.get('pagination'))
            rows = [row for item in as_list(listing['results']) if (row := self.record_from(item))]
            more = type(pager.get('current_page')) is int and type(pager.get('total_page')) is int and pager['current_page'] < pager['total_page']
            return rows, bool(rows and more)
        if page != 1:
            return [], False
        ranking = as_dict(loads(self.get(http, SORA + '/top/last7Days.json'), 'SoraRaw'))
        rows = [row for item in as_list(ranking.get('mangas')) if (row := self.record_from(item, False))]
        return rows, False

    def search(self, http, query):
        def fetch_part(index):
            client = http.fork() if hasattr(http, 'fork') else http
            try:
                for attempt in range(2):
                    try:
                        raw, _, _ = client.document(f'{SORA}/mangas_{index}.json', headers={'Referer': SORA + '/'},
                                                    action='n9:soraraw')
                        break
                    except SourceTemporaryError:
                        deadline = getattr(client, 'deadline', None)
                        if attempt or (deadline and deadline - time.monotonic() < 2):
                            raise
            finally:
                if client is not http:
                    client.close()
            # Keep only what the search and the result rows read (~20 MB of JSON).
            return [{key: entry.get(key) for key in SEARCH_FIELDS}
                    for entry in as_list(as_dict(loads(raw, 'SoraRaw')).get('list'))]

        def part(index):
            return self.cached(f'catalogue-part:{index}', self.CATALOG_TTL, lambda: fetch_part(index))

        def load():
            from concurrent.futures import ThreadPoolExecutor

            pages = self.config(http).get('m')
            if type(pages) is not int or not 1 <= pages <= 60:
                raise SourceError('SoraRaw изменил каталог поиска.')
            # The site's own search downloads the same files in the browser.
            with ThreadPoolExecutor(max_workers=6) as pool:
                return [entry for chunk in pool.map(part, range(1, pages + 1)) for entry in chunk]

        deadline = getattr(http, 'deadline', None)
        remaining = max(0, deadline - time.monotonic()) if deadline else 20
        if not self.search_lock.acquire(timeout=remaining):
            raise SourceTemporaryError('SoraRaw ещё загружает поисковый каталог.')
        try:
            entries = self.cached('catalog', self.CATALOG_TTL, load)
        finally:
            self.search_lock.release()
        words = [w.casefold() for w in query.split()]
        found = []
        for entry in entries:
            haystack = ' '.join(text(entry.get(k)) for k in ('name', 'alt_names', 'author')).casefold()
            if all(word in haystack for word in words):
                found.append(entry)
        found.sort(key=lambda entry: entry.get('views') if isinstance(entry.get('views'), (int, float)) else 0, reverse=True)
        return [row for entry in found[:100] if (row := self.record_from(entry))]

    def series(self, http, url):
        slug = self.title_key(self.canonical(url))
        props = next_data(self.get(http, f'{SORA}/manga/{slug}'))
        manga = as_dict(find(props, lambda d: isinstance(d.get('manga'), dict) and 'chapters' in d['manga']).get('manga'))
        if text(manga.get('slug')) != slug:
            raise SourceError('SoraRaw вернул карточку другого тайтла.')
        row = self.record_from(manga)
        description = []
        try:
            for block in as_list(as_dict(json.loads(manga.get('content') or '{}')).get('blocks')):
                data = as_dict(block.get('data'))
                if isinstance(data.get('text'), str):
                    description.append(re.sub(r'<[^>]+>', '', html.unescape(data['text'])).strip())
                for item in data.get('items') or []:
                    if isinstance(item, str):
                        description.append('• ' + re.sub(r'<[^>]+>', '', html.unescape(item)).strip())
        except (TypeError, ValueError):
            pass
        names = [text(n.get('name')) for n in as_list(manga.get('names')) if text(n.get('name'))]
        row.update(description='\n'.join(d for d in description if d)[:12000],
                   aliases=list(dict.fromkeys([row['title'], *names])),
                   genres=[text(g.get('name')) for g in as_list(manga.get('genres')) if text(g.get('name'))],
                   status={'incomplete': 'ongoing', 'complete': 'completed'}.get(text(manga.get('type')), ''))
        chapters = {}
        for item in as_list(manga.get('chapters')):
            path = text(item.get('path'))
            part = path.removeprefix(slug + '-')
            if not re.fullmatch(SORA_CHAPTER, part):
                continue
            target = f'{SORA}/manga/{slug}/{part}'
            n = item.get('name')
            label = ' '.join(p for p in (f'第{n:g}話' if isinstance(n, (int, float)) else '', text(item.get('title'))) if p)
            chapters[target] = self.chapter(target, label, n if isinstance(n, (int, float)) else None, day(item.get('published_at')))
        return row, self.order(chapters)

    def pages(self, http, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        props = next_data(self.get(http, f'{SORA}/manga/{match[1]}/{match[2]}'))
        chapter = as_dict(find(props, lambda d: isinstance(d.get('chapter'), dict) and 'uuid' in d['chapter']).get('chapter'))
        # The JSON is read leniently upstream: ids arrive as numbers or digit strings.
        cid, mid, uuid = str(chapter.get('id') or ''), str(chapter.get('manga_id') or ''), text(chapter.get('uuid'))
        host = text(chapter.get('_b'))
        if not re.fullmatch(r'[0-9]{1,15}', cid) or not re.fullmatch(r'[0-9]{1,12}', mid) or not re.fullmatch(r'[0-9a-f]{32}|[0-9a-f]{48}|[0-9a-f]{64}', uuid):
            raise SourceAccessError('SoraRaw не открыл эту главу.')
        if not re.fullmatch(r'https://[a-z0-9.-]{1,120}', host):
            raise SourceError('SoraRaw изменил адрес страниц.')
        api = text(self.config(http).get('apiImage'))
        if urlsplit(api).netloc not in SORA_MANIFEST_HOSTS:
            raise SourceError('SoraRaw изменил адрес списка страниц.')
        try:
            stamp = int(datetime.fromisoformat(text(chapter.get('updated_at')).replace('Z', '+00:00')).timestamp() * 1000)
        except ValueError:
            raise SourceError('SoraRaw изменил формат главы.') from None
        manifest = as_dict(loads(self.get(http, query_url(f'{api}/{mid}/{cid}.json', t=stamp)), 'SoraRaw'))
        try:
            entries = json.loads(xor(b64(text(manifest.get('d'))), MANIFEST_KEY).decode().rstrip('\x00'))
        except (ValueError, UnicodeError):
            raise SourceError('SoraRaw изменил формат списка страниц.') from None
        mode, token = text(chapter.get('mode')), text(chapter.get('token'))
        scheme = f'canva:{cid}:{token}' if mode == 'canva' else f'canva2:{cid}' if mode == 'canva2' else ''
        key = bytes.fromhex(uuid)
        rows = []
        for entry in sorted(as_list(entries), key=lambda e: e.get('order') if isinstance(e.get('order'), (int, float)) else 0):
            try:
                raw = xor(b64(text(entry.get('b'))), IMAGE_KEY)
                decryptor = Cipher(algorithms.AES(key), modes.CTR(raw[:16])).decryptor()
                path = (decryptor.update(raw[16:]) + decryptor.finalize()).decode()
            except (ValueError, UnicodeError):
                raise SourceError('SoraRaw изменил шифрование страниц.') from None
            if not re.fullmatch(r'[A-Za-z0-9/_.-]{1,300}', path):
                raise SourceError('SoraRaw изменил адрес страниц.')
            rows.append(RoutedPage(f'{host}/{path.lstrip("/")}', scheme=scheme))
        return packed_refs(rows, url)


SOURCES = (Fod(), LineManga(), Sokuyomi(), SoraRaw())
