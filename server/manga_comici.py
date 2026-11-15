"""Public publisher catalogue and reader for Keiyoushi's Apache-2.0 Comici Viewer."""

from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_madara import image_url
from manga_page_media import TILE_FRAGMENT, read_tiles
from manga_source_tags import unique
from manga_vinetheme import dictionaries, flight_models, flight_stream, resolve_fields
from source_parser import SourceAccessError, SourceError, public_url


ID = r'[A-Za-z0-9_-]{1,80}'
RANKING = '/ranking/manga'
TITLE_PATH = re.compile(rf'/series/({ID})/?')
STORED_TITLE = re.compile(rf'/(?:{ID}/series/)?({ID})/?')
CHAPTER_PATH = re.compile(rf'/episodes/({ID})/?')
LIST_PAGE = re.compile(r'/(?:series/list/(?:up|new)|category/manga/(?:oneShot|complete|day/[1-8])|category/gravure)/[1-9]\d{0,3}/?')
MAX_PAGES = 500
FILTERS = (('更新順', '/series/list/up'), ('新作順', '/series/list/new'), ('読み切り', '/category/manga/oneShot'),
           ('完結', '/category/manga/complete'),
           *((label + '曜日', f'/category/manga/day/{index}') for index, label in enumerate('月火水木金土日', 1)),
           ('その他', '/category/manga/day/8'))


def items(value):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise SourceError('Comici вернул некорректный список.')
    return value


def obj(value):
    if not isinstance(value, dict):
        raise SourceError('Comici вернул некорректную карточку.')
    return value


def series_id(value):
    return value if isinstance(value, str) and re.fullmatch(ID, value) else ''


def description(value):
    if not isinstance(value, str) or not value:
        return ''
    try:
        sections = items(json.loads(value))
    except (ValueError, SourceError, RecursionError):
        return value[:12000]
    return '\n'.join(''.join(node['text'] for node in dictionaries(section) if isinstance(node.get('text'), str))
                     for section in sections)[:12000]


def published(value):
    if type(value) is int and 0 < value < 4_102_444_800:
        return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
    return ''


def path_only(url):
    return urlsplit(url).path.rstrip('/')


class Comici:
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    index_sort = 'updated'

    def __init__(self, sid, name, root, language, adult, *, gravure=False):
        self.SOURCE_ID, self.NAME, self.ROOT, self.LANGUAGE, self.IS_NSFW = sid, name, root, language, adult
        self.host = urlsplit(root).netloc
        self.filters = {path: label for label, path in FILTERS}
        if gravure:
            self.filters['/category/gravure'] = 'グラビア'

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            target = urljoin(base or self.ROOT, value)
            parts = urlsplit(target)
            if parts.netloc == self.host:
                return public_url(target, resolve_dns=False)
        except (SourceError, ValueError):
            pass
        return ''

    def request(self, http, path, *, params=None, action='comici-json'):
        url = self.ROOT + path + ('?' + urlencode(params) if params else '')
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'}, action=action)
        if not self.site_link(final) or path_only(final) != path_only(url):
            raise SourceError('Comici изменил маршрут запроса.')
        if action != 'comici-json':
            return raw
        try:
            return obj(json.loads(raw))
        except (ValueError, RecursionError):
            raise SourceError('Comici вернул страницу вместо данных API.') from None

    def row(self, data):
        from manga_sources import title_aliases

        slug, name = series_id(data.get('id')), data.get('name')
        if not slug or not isinstance(name, str) or not name.strip():
            raise SourceError('Comici вернул карточку без названия или ссылки.')
        url = self.ROOT + '/series/' + slug
        covers = items(data.get('images') or [])
        authors = unique(item.get('name') for item in items(data.get('author') or []))
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'sourceId': self.SOURCE_ID,
                'sourceUrl': url, 'sourceURL': url, 'url': url, 'sourceOnly': True, 'ids': {},
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME, 'kind': 'manga',
                'language': self.LANGUAGE, 'title': name.strip()[:500], 'aliases': title_aliases(name),
                'cover': image_url(covers[0].get('url'), url) if covers else '', 'authors': authors, 'artists': authors,
                'description': description(data.get('description')), 'genres': [],
                'tags': unique(item.get('name') for item in items(data.get('tag') or [])),
                'status': 'completed' if data.get('isCompleted') is True else 'ongoing'}

    def vocabulary(self, http):
        # The publisher's filter menu contains release schedules and formats.
        # The subjects themselves are the tag names in each series summary.
        return []

    def ranking(self, http):
        raw = self.request(http, RANKING, action='comici-rsc')
        models = flight_models(flight_stream(raw))
        container = next((row for model in models.values() for row in dictionaries(model)
                          if row.get('className') == 'series-list mode-ranking'), None)
        if container is None:
            raise SourceError('Comici не вернул список популярных тайтлов.')
        children = resolve_fields(container.get('children'), models, [60000])
        if not isinstance(children, list):
            raise SourceError('Comici изменил формат рейтинга.')
        rows = []
        for child in children:
            if not isinstance(child, list) or len(child) < 4 or not series_id(child[2]):
                continue
            image = next((item for item in dictionaries(child) if 'src' in item and isinstance(item.get('alt'), str)), None)
            if image and image['alt'].strip():
                srcset = image.get('srcSet') or ''
                cover = srcset.rsplit(', ', 1)[-1].split(' ', 1)[0] if isinstance(srcset, str) else ''
                rows.append(self.row({'id': child[2], 'name': image['alt'],
                                      'images': [{'url': cover or image.get('src')}]}))
        if children and not rows:
            raise SourceError('Comici изменил карточки рейтинга.')
        return rows

    def listing(self, http, path, page):
        soup = BeautifulSoup(self.request(http, f'{path}/{page}', action='comici-html'), 'html.parser')
        rows = []
        for card in soup.select('.series-list-item'):
            link = card.select_one('a.series-list-item-link[href]')
            title = card.select_one('.series-list-item-h [data-e2e=sliTitle]')
            if not link or not title or not title.get_text(strip=True):
                continue
            target = self.site_link(link['href'])
            match = re.fullmatch(rf'/(?:{ID}/)?series/({ID})(?:/new)?/?', urlsplit(target).path)
            if not match:
                continue
            cover = card.select_one('img.series-list-item-img[src]')
            rows.append(self.row({'id': match[1], 'name': title.get_text(' ', strip=True),
                                  'images': [{'url': cover['src']}] if cover else []}))
        return rows, bool(soup.select_one('a.g-pager-link.mode-active + a.g-pager-link'))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or not isinstance(tag, str):
            raise SourceError('Некорректные параметры каталога Comici.')
        if query := query.strip()[:160]:
            data = self.request(http, '/api/search', params={'q': query, 'page': page, 'size': 24})
            series = obj(obj(data.get('searchResult')).get('series'))
            total = series.get('total')
            return [self.row(row) for row in items(series.get('series'))], type(total) is int and total > page * 24
        if tag and tag not in self.filters:
            raise SourceError('Comici не распознал фильтр каталога.')
        if tag or sort == 'updated':
            return self.listing(http, tag or '/series/list/up', page)
        return (self.ranking(http) if page == 1 else []), False

    def series(self, http, slug):
        params = {'seriesHash': slug, 'episodeFrom': '1', 'episodeTo': '9999'}
        data = obj(self.request(http, '/api/episodes', params=params).get('series'))
        row = self.row(obj(data.get('summary')))
        if row['url'] != self.ROOT + '/series/' + slug:
            raise SourceError('Comici вернул другой тайтл.')
        return row, params, items(data.get('episodes') or [])

    def details(self, http, value):
        match = TITLE_PATH.fullmatch(urlsplit(self.site_link(value)).path)
        if not match:
            raise SourceError('Некорректная ссылка на тайтл Comici.')
        return self.series(http, match[1])[0]

    def chapter(self, item, access, number):
        slug = series_id(item.get('id'))
        title = item.get('title')
        if not slug or not isinstance(title, str) or not title.strip():
            raise SourceError('Comici вернул главу без названия или ссылки.')
        locked = access.get('hasAccess') is not True
        if locked:
            title = ('➡️ ' if access.get('accessType') == 'memberOnlyFree' else '🔒 ') + title
        return {'url': self.ROOT + '/episodes/' + slug, 'number': number, 'season': 1, 'title': title,
                'language': self.LANGUAGE, 'translator': '', 'publishedAt': published(item.get('datePublished')),
                'available': not locked}

    def inspect(self, value, http):
        path = urlsplit(self.site_link(value)).path
        pages = []
        if title := TITLE_PATH.fullmatch(path):
            row, params, raw_episodes = self.series(http, title[1])
            access = obj(self.request(http, '/api/series/access', params=params).get('seriesAccess'))
            if access.get('seriesId') != title[1]:
                raise SourceError('Comici вернул доступ к другому тайтлу.')
            by_id = {item.get('episodeId'): item for item in items(access.get('episodeAccesses'))}
            episodes = [self.chapter(item, by_id.get(item.get('id'), {}), number)
                        for number, item in enumerate(reversed(raw_episodes), 1)]
            url = row['url']
        elif chapter := CHAPTER_PATH.fullmatch(path):
            data = obj(self.request(http, '/api' + path.rstrip('/')).get('episode'))
            access, summary = obj(data.get('access')), obj(data.get('summary'))
            if data.get('id') != chapter[1] or access.get('episodeId') != chapter[1] or summary.get('id') != chapter[1]:
                raise SourceError('Comici вернул другую главу.')
            if access.get('hasAccess') is not True:
                raise SourceAccessError('Глава закрыта у источника.')
            row = self.row(obj(data.get('series')))
            number = data.get('seriesEpisodeNumber')
            entry = self.chapter(summary, access, number if type(number) is int and number > 0 else 1)
            episodes, url = [entry], entry['url']
            pages = self.pages(http, data)
        else:
            raise SourceError('Некорректная ссылка на читалку Comici.')
        return {**row, 'url': url, 'episodes': episodes, 'pages': pages,
                'available': any(item['available'] for item in episodes), 'truncated': False,
                'seasons': [{'number': 1, 'name': 'Том 1'}] if episodes else [], 'dubs': [], 'releases': [], 'translations': []}

    def pages(self, http, episode):
        contents = items(episode.get('content'))
        viewer = next((row for row in contents if row.get('type') == 'viewer'), None)
        if viewer is None:
            pages = [self.page_url(row.get('url')) for row in contents if row.get('type') == 'image']
            if not 0 < len(pages) <= MAX_PAGES:
                raise SourceAccessError('Comici не предоставил страницы открытой главы.')
            return pages
        viewer_id, content_id = series_id(viewer.get('viewerId')), episode.get('contentId')
        if not viewer_id or type(content_id) is not int or content_id <= 0:
            raise SourceError('Comici не предоставил ID читалки.')
        args = {'comici-viewer-id': viewer_id, 'contentId': content_id, 'page-from': '0', 'page-to': '0'}
        path = '/api/book/contentsInfo'
        total = self.request(http, path, params=args).get('totalPages')
        if type(total) is not int or not 1 <= total <= MAX_PAGES:
            raise SourceError('Comici не предоставил число открытых страниц.')
        args['page-to'] = str(total)
        rows = items(self.request(http, path, params=args).get('result'))
        sort = [row.get('sort') for row in rows]
        if any(type(index) is not int for index in sort) or sorted(sort) != list(range(total)):
            raise SourceError('Comici вернул неполный набор страниц.')
        return [self.page_url(row.get('imageUrl'), read_tiles(row.get('scramble'))) for row in sorted(rows, key=lambda row: row['sort'])]

    def page_url(self, raw, tiles=None):
        url = image_url(raw, self.ROOT)
        parts = urlsplit(url)
        if not url or not image_route(parts.hostname or ''):
            raise SourceError('Comici вернул неизвестный хост страниц.')
        marker = TILE_FRAGMENT + (','.join(map(str, tiles)) if tiles is not None else '')
        return urlunsplit(parts._replace(fragment=marker))

    def saved_title_url(self, value):
        target = urlsplit(value)
        if TITLE_PATH.fullmatch(target.path):
            return value
        if match := STORED_TITLE.fullmatch(target.path):
            return self.ROOT + '/series/' + match[1]
        return ''

    def saved_chapter_url(self, value, _slug, root):
        if key := series_id(value):
            return self.ROOT + '/episodes/' + key
        return self.site_link(value, root)

    def saved_chapter_matches(self, target, title):
        # The caller selected this chapter by index from this exact stored manga.
        return bool(CHAPTER_PATH.fullmatch(urlsplit(target).path) and TITLE_PATH.fullmatch(urlsplit(title).path))


def image_route(host):
    return any(host == root or host.endswith('.' + root) for root in (*HOSTS, 'comici.jp'))


def public_route(host, path, query, action):
    if host not in HOSTS:
        return False
    if action == 'comici-rsc':
        return path.rstrip('/') == RANKING and (not query or bool(re.fullmatch(r'_rsc(?:=[A-Za-z0-9_-]{0,64})?', query)))
    if action == 'comici-html':
        return not query and bool(LIST_PAGE.fullmatch(path))
    if re.fullmatch(rf'/api/episodes/{ID}/?', path):
        return not query
    try:
        params = parse_qs(query, strict_parsing=True, keep_blank_values=True, max_num_fields=4)
    except ValueError:
        return False
    if any(len(values) != 1 for values in params.values()):
        return False
    args = {name: values[0] for name, values in params.items()}
    if path == '/api/search':
        return (args.keys() == {'q', 'page', 'size'} and 0 < len(args['q']) <= 160
                and args['size'] == '24' and number_in(args['page'], 1, 2000))
    if path in {'/api/episodes', '/api/series/access'}:
        return (args.keys() == {'seriesHash', 'episodeFrom', 'episodeTo'} and bool(series_id(args['seriesHash']))
                and args['episodeFrom'] == '1' and args['episodeTo'] == '9999')
    if path == '/api/book/contentsInfo':
        return (args.keys() == {'comici-viewer-id', 'contentId', 'page-from', 'page-to'}
                and bool(series_id(args['comici-viewer-id'])) and number_in(args['contentId'], 1, 2**32)
                and args['page-from'] == '0' and number_in(args['page-to'], 0, MAX_PAGES))
    return False


def number_in(value, minimum, maximum):
    return bool(re.fullmatch(r'[0-9]{1,10}', value)) and minimum <= int(value) <= maximum


SOURCES = (
    Comici('299423548273637501', 'Comic Growl', 'https://comic-growl.com', 'all', False),
    Comici('6455606609436338494', 'Asacomi', 'https://asacomi.jp', 'ja', False),
    Comici('3726193166490568923', 'Bibibi Comic', 'https://bibibi-comic.com', 'ja', False),
    Comici('2944603286439592172', 'Big Comics', 'https://bigcomics.jp', 'ja', True),
    Comici('4993360009034397146', 'Booklista Studio', 'https://studio.booklista.co.jp', 'ja', False),
    Comici('7310112963091407823', 'G-Comi', 'https://g-comi.jp', 'ja', True),
    Comici('6626616605316433619', 'Comic Pash', 'https://comicpash.jp', 'ja', False),
    Comici('6786869574657969795', 'Comic Ride', 'https://comicride.jp', 'ja', False),
    Comici('1887776535756811938', 'Comic Room Base', 'https://comic-room-base.com', 'ja', False),
    Comici('1496675570830588004', 'Comic Ryu', 'https://comic-ryu.jp', 'ja', True),
    Comici('58641447023846824', 'Comirela', 'https://comirela.com', 'ja', False),
    Comici('6820605856874807465', 'Hana To Yume+', 'https://hanayume.com', 'ja', False),
    Comici('5820719158683766054', 'HAYA Comic', 'https://hayacomic.jp', 'ja', False),
    Comici('6981500022236807277', "HERO'S Web", 'https://heros-web.com', 'ja', False),
    Comici('2876739237900975302', 'J-N Books', 'https://comic.j-nbooks.jp', 'ja', False),
    Comici('645302785022492537', 'KimiComi', 'https://kimicomi.com', 'ja', False),
    Comici('8826192789792786070', 'MagKan', 'https://kansai.mag-garden.co.jp', 'ja', False),
    Comici('6323380629311776595', 'MangaBang Comics', 'https://comics.manga-bang.com', 'ja', False),
    Comici('1497299793762441095', 'MangaBu', 'https://mangabu.jp', 'ja', False),
    Comici('4711824862797870329', 'Champion Cross', 'https://championcross.jp', 'ja', False),
    Comici('1153097454471755439', 'Mangalt', 'https://mangalt.jp', 'ja', False),
    Comici('2566686121922544500', 'Manga SPA', 'https://mangaspa.nikkan-spa.jp', 'ja', True),
    Comici('1066937743995646358', 'Manga Zegra', 'https://manga-zegra.com', 'ja', False),
    Comici('1860491637286237325', 'Nami Comic', 'https://namicomic.jp', 'ja', True),
    Comici('2932724617903419016', 'PiaComic', 'https://piacomic.jp', 'ja', True),
    Comici('8784054084293367959', 'RimacomiPlus', 'https://rimacomiplus.jp', 'ja', False),
    Comici('5158991361251014104', 'TakeComic', 'https://takecomic.jp', 'ja', False),
    Comici('3590997004623427971', 'Young Animal', 'https://younganimal.com', 'ja', True, gravure=True),
    Comici('162182610453532778', 'Young Champion', 'https://youngchampion.jp', 'ja', True),
)
HOSTS = frozenset(adapter.host for adapter in SOURCES)
ENABLED = {'6626616605316433619', '6820605856874807465', '4711824862797870329'}
ACTIVE_SOURCES = tuple(adapter for adapter in SOURCES if adapter.SOURCE_ID in ENABLED)
