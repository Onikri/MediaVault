"""GigaViewer publisher catalogue and public chapters (Keiyoushi Apache-2.0)."""

import base64
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_gigaviewer_profiles import PROFILES
from manga_madara import image_url
from manga_page_media import GIGA_FRAGMENT
from manga_source_tags import unique
from source_parser import SourceAccessError, SourceError, public_url


ID = r'[1-9][0-9]{0,21}'
TITLE_PATH = re.compile(rf'/series/({ID})/?')
CHAPTER_PATH = re.compile(rf'/(episode|volume)/({ID})/?')
PRODUCTS_PATH = '/api/viewer/pagination_readable_products'
LISTING = 'databaseId title thumbnailUri firstEpisode {permalink} firstVolume {permalink} '
LISTING += 'latestEpisode {publishedAt} latestVolume {thumbnailUri} likeCount'
SEARCH = 'query Search($keyword: String!) {searchSeries(keyword: $keyword) {edges {node {' + LISTING + '}}}}'
SERIES = ('query Series($id: String!) {series(databaseId: $id) {databaseId title author {name} description '
          'thumbnailUri firstEpisode {permalink} firstVolume {permalink} latestVolume {thumbnailUri} '
          'episodes: readableProducts(types: [EPISODE], first: 0) {totalCount} '
          'volumes: readableProducts(types: [VOLUME], first: 0) {totalCount}}}')
GROUP_BATCH = 12
MAX_PRODUCTS = 10000
MAX_PAGES = 500
RELEASES = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')


def identifier(value):
    return isinstance(value, str) and bool(re.fullmatch(ID, value))


def dictionary(value):
    if not isinstance(value, dict):
        raise SourceError('GigaViewer вернул некорректную карточку.')
    return value


def records(value):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SourceError('GigaViewer вернул некорректный список.')
    return value


def group_query(count):
    selection = 'series {edges {node {' + LISTING + '}}}'
    fragment = '{... on SerialGroup {' + selection + '} ... on Genre {' + selection + '}}'
    fields = [f'group{index}: node(id: $id{index}) ' + fragment for index in range(count)]
    args = ', '.join(f'$id{index}: ID!' for index in range(count))
    return f'query Collections({args}) {{' + ' '.join(fields) + '}'


def relay_id(value):
    return base64.b64encode((value if ':' in value else 'SerialGroup:' + value).encode('ascii')).decode('ascii')


def date_label(value):
    if isinstance(value, str) and re.match(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        return value[:10]
    return ''


class GigaViewer:
    LANGUAGE = 'ja'
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    index_sort = 'all'

    def __init__(self, sid, name, root, adult, layout, groups, filters):
        self.SOURCE_ID, self.NAME, self.ROOT, self.IS_NSFW = sid, name, root, adult
        self.host = urlsplit(root).netloc
        self.layout, self.groups, self.filters = layout, groups, filters
        self.collection_groups = tuple(dict.fromkeys([*groups, *(key for row in filters.values() for key in row
                                      if identifier(key))]))
        self.allowed_groups = frozenset(relay_id(key) for key in (*groups, *(key for row in filters.values()
                                        for key in row if identifier(key) or key.startswith('Genre:'))))

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            target = urljoin(base or self.ROOT, value)
            if urlsplit(target).netloc == self.host:
                return public_url(target, resolve_dns=False)
        except (SourceError, ValueError):
            pass
        return ''

    def graphql(self, http, query, variables):
        body = json.dumps({'query': query, 'variables': variables}, ensure_ascii=False).encode()
        target = self.ROOT + '/graphql'
        raw, final, _ = http.document(target, method='POST', data=body, action='giga-graphql',
                                      headers={'Referer': self.ROOT + '/', 'Origin': self.ROOT})
        if final != target:
            raise SourceError('GigaViewer перенаправил запрос GraphQL.')
        try:
            data = dictionary(json.loads(raw))
        except (ValueError, RecursionError):
            raise SourceError('GigaViewer вернул страницу вместо данных GraphQL.') from None
        if data.get('errors'):
            raise SourceError('GigaViewer не выполнил запрос каталога.')
        return dictionary(data.get('data'))

    def get(self, http, path, params=None, action='giga-html'):
        raw, final, _ = http.document(self.ROOT + path + ('?' + urlencode(params) if params else ''),
                                      action=action, headers={'Referer': self.ROOT + '/'})
        if not self.site_link(final) or urlsplit(final).path.rstrip('/') != path.rstrip('/'):
            raise SourceError('GigaViewer перенаправил запрос на другую страницу.')
        return raw

    def permalink(self, data):
        for name in ('firstEpisode', 'firstVolume'):
            item = data.get(name)
            if isinstance(item, dict):
                target = self.site_link(item.get('permalink'))
                if target and CHAPTER_PATH.fullmatch(urlsplit(target).path):
                    return target
        return ''

    def row(self, data, permalink):
        from manga_sources import title_aliases

        sid = data.get('databaseId')
        label = data.get('title')
        if not identifier(sid) or not isinstance(label, str) or not label.strip():
            raise SourceError('GigaViewer вернул карточку без названия или ID.')
        url = self.ROOT + '/series/' + sid
        latest = data.get('latestVolume') or {}
        cover = image_url(data.get('thumbnailUri') or latest.get('thumbnailUri'), self.ROOT)
        authors = unique([(data.get('author') or {}).get('name')])
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{sid}', 'provider': 'suwayomi:' + self.SOURCE_ID,
                'providerName': self.NAME, 'sourceId': self.SOURCE_ID, 'sourceUrl': url, 'sourceURL': url, 'url': url,
                'kind': 'manga', 'format': 'manga', 'language': self.LANGUAGE, 'title': label.strip()[:500],
                'aliases': title_aliases(label), 'cover': cover, 'sourceOnly': True, 'ids': {},
                'description': (data.get('description') or '')[:12000], 'genres': [], 'tags': [],
                'authors': authors, 'artists': authors, 'originalUrl': permalink}

    def from_edges(self, node):
        return [dictionary(edge.get('node')) for edge in records(dictionary(node).get('edges'))]

    def cards(self, rows):
        result = {}
        for item in rows:
            if url := self.permalink(item):
                row = self.row(item, url)
                result.setdefault(row['id'], row)
        return list(result.values())

    def collection(self, http, groups):
        if not groups:
            return []
        variables = {f'id{index}': relay_id(key) for index, key in enumerate(groups)}
        data = self.graphql(http, group_query(len(groups)), variables)
        return [row for group in data.values() if isinstance(group, dict) and group.get('series')
                for row in self.from_edges(group['series'])]

    def html_list(self, http, route, sort):
        if self.layout == 'border':
            path, selector = '/', 'section.top-series'
            link_sel, title_sel, image_sel = 'li.first-episode a, li.this-episode a', 'h3', '.top-key-image'
        elif self.layout == 'sunday':
            path, selector = '/series/yoru-sunday', 'ul.webry-series-list li a.webry-series-item-link'
            link_sel, title_sel, image_sel = '', 'h4.series-title', 'div.thumb-wrapper img'
        else:
            path, selector = '/series' + route, 'ul.series-list li a'
            if sort == 'updated' and not route:
                day = RELEASES[datetime.now(timezone(timedelta(hours=9))).weekday()]
                selector = f'h2.series-list-date-week.{day} + ul.series-list li a'
            link_sel, title_sel, image_sel = '', 'h2.series-list-title', 'div.series-list-thumb img'
        soup = BeautifulSoup(self.get(http, path), 'html.parser')
        result = {}
        for item in soup.select(selector):
            anchor = item.select_one(link_sel) if link_sel else item
            title = item.select_one(title_sel)
            img = item.select_one(image_sel)
            cover = image_url(img.get('data-src') or img.get('src'), self.ROOT) if img else ''
            href = self.site_link(anchor.get('href')) if anchor else ''
            if not href or not CHAPTER_PATH.fullmatch(urlsplit(href).path) or not title:
                continue
            paths = urlsplit(unquote(urlsplit(cover).path.rsplit('/', 1)[-1])).path if cover else ''
            match = re.search(rf'/series-[^/]+/({ID})-', paths) or re.search(rf'/series-[^/]+/({ID})-', urlsplit(cover).path)
            if match:
                sid = match[1]
            else:
                # Historic HTML lists occasionally substitute an episode thumbnail.
                sid = self.viewer(http, href)[0]
                if not sid:
                    raise SourceError('GigaViewer не указал произведение главы.')
            name = title.get_text(' ', strip=True)
            if name:
                result.setdefault(sid, self.row({'databaseId': sid, 'title': name, 'thumbnailUri': cover}, href))
        return list(result.values())

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or not isinstance(tag, str):
            raise SourceError('Некорректные параметры каталога GigaViewer.')
        if query := query.strip()[:160]:
            if page != 1:
                return [], False
            data = self.graphql(http, SEARCH, {'keyword': query})
            rows = self.from_edges(data.get('searchSeries'))
            return self.cards(sorted(rows, key=lambda item: not bool(item.get('firstEpisode')))), False
        if tag:
            if tag not in self.filters:
                raise SourceError('Неизвестный раздел каталога GigaViewer.')
            selected = self.filters[tag]
            if selected == () or self.layout == 'jump':
                return (self.html_list(http, selected[0] if selected else '', sort) if page == 1 else []), False
        elif self.layout in {'jump', 'border'}:
            routes = ('', '/oneshot', '/finished') if self.layout == 'jump' and sort == 'all' else ('',)
            if page > len(routes):
                return [], False
            return self.html_list(http, routes[page - 1], sort), page < len(routes)
        else:
            selected = self.collection_groups if sort == 'all' else self.groups
        if self.layout == 'sunday' and sort == 'all' and not tag and (page - 1) * GROUP_BATCH >= len(selected):
            end = (len(selected) + GROUP_BATCH - 1) // GROUP_BATCH + 1
            return (self.html_list(http, '', sort) if page == end else []), False
        start = (page - 1) * GROUP_BATCH
        rows = self.collection(http, selected[start:start + GROUP_BATCH])
        if sort == 'popular':
            rows.sort(key=lambda item: item.get('likeCount') or 0, reverse=True)
        if sort == 'updated':
            rows.sort(key=lambda item: (item.get('latestEpisode') or {}).get('publishedAt') or '', reverse=True)
        next_page = start + GROUP_BATCH < len(selected) or bool(rows and self.layout == 'sunday' and sort == 'all' and not tag)
        return self.cards(rows), next_page

    def vocabulary(self, http):
        return [{'sourceId': label, 'label': label, 'category': 'genre'} for label, groups in self.filters.items()
                if groups and all(group.startswith('Genre:') for group in groups)]

    def series(self, http, sid):
        body = dictionary(self.graphql(http, SERIES, {'id': sid}).get('series'))
        if body.get('databaseId') != sid:
            raise SourceError('GigaViewer вернул другое произведение.')
        return body

    def details(self, http, value):
        match = TITLE_PATH.fullmatch(urlsplit(self.site_link(value)).path)
        if not match:
            raise SourceError('Некорректная ссылка на тайтл GigaViewer.')
        data = self.series(http, match[1])
        return self.row(data, self.permalink(data))

    def products(self, http, sid, kind, count):
        if type(count) is not int or not 0 <= count <= MAX_PRODUCTS:
            raise SourceError('Неизвестное количество глав GigaViewer.')
        rows, seen = [], set()
        while len(rows) < count:
            params = {'type': kind, 'aggregate_id': sid, 'sort_order': 'desc', 'offset': len(rows)}
            response = self.get(http, PRODUCTS_PATH, params, 'giga-json')
            try:
                batch = records(json.loads(response))
            except (ValueError, RecursionError):
                raise SourceError('GigaViewer вернул неправильное оглавление.') from None
            if not batch:
                break
            ids = [item.get('readable_product_id') for item in batch]
            if any(not identifier(key) for key in ids) or len(ids) != len(set(ids)) or seen.intersection(ids):
                raise SourceError('GigaViewer вернул повторяющуюся или неизвестную главу.')
            seen.update(ids)
            rows.extend(batch)
        return rows

    def chapter(self, item, kind, number):
        url = self.site_link(item.get('viewer_uri'))
        match = CHAPTER_PATH.fullmatch(urlsplit(url).path)
        label = item.get('title')
        if not match or (match[1], match[2]) != (kind, item.get('readable_product_id')) or not isinstance(label, str) or not label.strip():
            raise SourceError('GigaViewer вернул главу без названия или ссылки.')
        access = dictionary(item.get('purchase_info'))
        unavailable = access.get('unavailable') is True or (self.layout == 'zenon' and item.get('status') is None)
        readable = access.get('can_read') is True and not unavailable
        prefix = '🔒 ' if unavailable else '💴 ' if not readable else ''
        return {'url': url, 'title': prefix + label, 'number': number, 'season': 1 if kind == 'episode' else 2,
                'language': self.LANGUAGE, 'translator': '', 'publishedAt': date_label(item.get('display_open_at')),
                'available': readable}

    def viewer(self, http, url):
        raw = self.get(http, urlsplit(url).path)
        soup = BeautifulSoup(raw, 'html.parser')
        valve = soup.select_one('script.js-valve[data-giga_series]')
        sid = valve.get('data-giga_series') if valve else ''
        return sid if identifier(sid) else '', soup

    def pages(self, product):
        structure = product.get('pageStructure')
        if product.get('isPublic') is not True or not isinstance(structure, dict):
            raise SourceAccessError('Глава закрыта у издателя.')
        mode = structure.get('choJuGiga')
        if not isinstance(mode, str):
            raise SourceError('GigaViewer не указал формат страниц.')
        pages = []
        for item in records(structure.get('pages')):
            if item.get('type') != 'main':
                continue
            url = image_url(item.get('src'), self.ROOT)
            parts = urlsplit(url)
            if not url or not image_route(parts.hostname or ''):
                raise SourceError('GigaViewer вернул неизвестный хост страниц.')
            marker = GIGA_FRAGMENT + ('=baku' if mode == 'baku' else '')
            pages.append(urlunsplit(parts._replace(fragment=marker)))
        if not 0 < len(pages) <= MAX_PAGES:
            raise SourceAccessError('Издатель не предоставил страницы открытой главы.')
        return pages

    def inspect(self, value, http):
        url = self.site_link(value)
        path = urlsplit(url).path
        pages, truncated = [], False
        if title := TITLE_PATH.fullmatch(path):
            sid = title[1]
            data = self.series(http, sid)
            row = self.row(data, self.permalink(data))
            episodes = []
            for kind in ('episode', 'volume'):
                count = dictionary(data.get(kind + 's')).get('totalCount')
                products = self.products(http, sid, kind, count)
                truncated |= len(products) < count
                episodes.extend(self.chapter(item, kind, number)
                                for number, item in enumerate(reversed(products), 1))
        elif match := CHAPTER_PATH.fullmatch(path):
            sid, soup = self.viewer(http, url)
            viewer = soup.select_one('script#episode-json[data-value]')
            if not viewer:
                raise SourceAccessError('Глава закрыта у издателя.')
            try:
                product = dictionary(dictionary(json.loads(viewer['data-value'])).get('readableProduct'))
            except (ValueError, RecursionError):
                raise SourceError('GigaViewer вернул некорректные данные главы.') from None
            pages = self.pages(product)
            data = dictionary(product.get('series'))
            parent = data.get('id')
            if product.get('id') != match[2] or not identifier(parent) or sid and parent != sid:
                raise SourceError('GigaViewer вернул другую главу.')
            row = self.row({**data, 'databaseId': parent}, url)
            number = product.get('number')
            title = product.get('title') or row['title']
            entry = {'url': url, 'title': title, 'language': self.LANGUAGE, 'translator': '',
                     'number': number if type(number) is int and number >= 0 else 1,
                     'season': 1 if match[1] == 'episode' else 2, 'available': True,
                     'publishedAt': date_label(product.get('publishedAt'))}
            episodes = [entry]
        else:
            raise SourceError('Некорректная ссылка на читалку GigaViewer.')
        seasons = [{'number': index, 'name': label} for index, label in ((1, 'Главы'), (2, 'Тома'))
                   if any(row['season'] == index for row in episodes)]
        return {**row, 'url': url, 'episodes': episodes, 'pages': pages, 'available': any(item['available'] for item in episodes),
                'truncated': truncated, 'seasons': seasons, 'dubs': [], 'releases': [], 'translations': []}

    def resolve_stored_title(self, data):
        from source_parser import PublicHttp

        if identifier(data.get('url')):
            return self.ROOT + '/series/' + data['url']
        url = self.site_link(data.get('realUrl') or data.get('url'))
        if not CHAPTER_PATH.fullmatch(urlsplit(url).path):
            return ''
        http = PublicHttp(timeout=(3, 7))
        try:
            sid, _ = self.viewer(http, url)
            return self.ROOT + '/series/' + sid if sid else ''
        finally:
            http.close()

    def saved_chapter_url(self, value, _sid, root):
        return self.site_link(value, root)

    def saved_chapter_matches(self, target, title):
        # The chapter came from Suwayomi's table of contents for this stored title.
        return bool(CHAPTER_PATH.fullmatch(urlsplit(target).path) and TITLE_PATH.fullmatch(urlsplit(title).path))


SOURCES = tuple(GigaViewer(*profile) for profile in PROFILES)
HOSTS = {adapter.host: adapter for adapter in SOURCES}
ENABLED = {'3399001455113605946', '5161357527629843269'}
ACTIVE_SOURCES = tuple(adapter for adapter in SOURCES if adapter.SOURCE_ID in ENABLED)


def image_route(host):
    return host in {'cdn-img.gigaviewer.com', 'cdn-scissors.gigaviewer.com'} or any(
        host == publisher or host.endswith('.' + publisher.removeprefix('www.')) for publisher in HOSTS)


def public_route(host, path, query, action):
    if host not in HOSTS:
        return False
    if action == 'giga-html':
        return not query and (bool(CHAPTER_PATH.fullmatch(path)) or path.rstrip('/') in {
            '', '/series', '/series/oneshot', '/series/finished', '/series/yoru-sunday'})
    if path == '/graphql':
        return not query
    if path != PRODUCTS_PATH:
        return False
    try:
        values = parse_qs(query, strict_parsing=True, keep_blank_values=True, max_num_fields=4)
    except ValueError:
        return False
    if values.keys() != {'type', 'aggregate_id', 'sort_order', 'offset'} or any(len(row) != 1 for row in values.values()):
        return False
    offset = values['offset'][0]
    return (values['type'][0] in {'episode', 'volume'} and identifier(values['aggregate_id'][0])
            and values['sort_order'] == ['desc'] and bool(re.fullmatch(r'[0-9]{1,5}', offset))
            and int(offset) <= MAX_PRODUCTS)


def graphql_form(host, body):
    if host not in HOSTS or not isinstance(body, bytes) or len(body) > 9000:
        return False
    try:
        value = json.loads(body)
    except (ValueError, RecursionError):
        return False
    if not isinstance(value, dict) or value.keys() != {'query', 'variables'} or not isinstance(value['variables'], dict):
        return False
    query, params = value['query'], value['variables']
    if query == SEARCH:
        return params.keys() == {'keyword'} and isinstance(params['keyword'], str) and 0 < len(params['keyword']) <= 160
    if query == SERIES:
        return params.keys() == {'id'} and identifier(params['id'])
    count = len(params)
    return (1 <= count <= GROUP_BATCH and params.keys() == {f'id{index}' for index in range(count)}
            and query == group_query(count) and all(isinstance(value, str) and value in HOSTS[host].allowed_groups
                                                     for value in params.values()))
