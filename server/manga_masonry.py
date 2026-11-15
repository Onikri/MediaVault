"""Native Masonry gallery catalogue and reader (Keiyoushi, Apache-2.0)."""

import re
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, image_url, node_text
from manga_source_tags import unique
from source_parser import SourceError, public_url


RESERVED = r'archive|updates|tag|search|video|model|category|login|register|page|account|feed|links'
TITLE_PATH = re.compile(rf'/((?!(?:{RESERVED})(?:/|$)){SEGMENT}(?:/{SEGMENT})?)/?', re.I)
CHAPTER_QUERY = 'mv_gallery=1'
CARDS = '.list-gallery:not(.static) figure'


class Masonry:
    IS_NSFW = True
    LANGUAGE = 'all'
    TITLE_PATH = CHAPTER_PATH = TITLE_PATH
    index_sort = 'updated'

    def __init__(self, sid, name, root):
        self.SOURCE_ID, self.NAME, self.ROOT = sid, name, root
        self.host = urlsplit(root).netloc

    def site_link(self, value, base=None):
        if isinstance(value, str) and value:
            try:
                target = urljoin(base or self.ROOT, value)
                if urlsplit(target).netloc == self.host:
                    return public_url(target, resolve_dns=False)
            except (ValueError, SourceError):
                pass
        return ''

    def document(self, http, url):
        from manga_sources import guard

        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'})
        if not self.site_link(final) or urlsplit(final).path.rstrip('/') != urlsplit(url).path.rstrip('/'):
            raise SourceError('Masonry перенаправил запрос на другую страницу.')
        soup = BeautifulSoup(raw, 'html.parser')
        guard(soup)
        return soup, final

    def row(self, label, path, thumbnail='', **fields):
        from manga_sources import title_aliases

        url = self.ROOT + '/' + path.strip('/') + '/'
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{path.strip("/")}', 'sourceId': self.SOURCE_ID,
                'sourceUrl': url, 'sourceURL': url, 'url': url, 'provider': f'suwayomi:{self.SOURCE_ID}',
                'providerName': self.NAME, 'title': label.strip()[:500], 'aliases': title_aliases(label),
                'kind': 'manga', 'language': self.LANGUAGE, 'cover': thumbnail, 'sourceOnly': True, 'ids': {}, **fields}

    @staticmethod
    def image(node, base):
        if not node:
            return ''
        value = (node.get('srcset') or '').split(',')
        first = value[0].split()
        return image_url(first[0] if first else (
            node.get('data-cfsrc') or node.get('data-src') or node.get('data-lazy-src') or node.get('src')), base)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or not isinstance(tag, str):
            raise SourceError('Некорректные параметры каталога Masonry.')
        if query := query.strip()[:160]:
            path = f'/search/post/{quote(query, safe="")}/mpage/{page}/'
        elif tag and re.fullmatch(SEGMENT, tag):
            path = f'/tag/{tag}/page/{page}/'
        elif tag:
            raise SourceError('Некорректный тег каталога Masonry.')
        elif sort == 'updated':
            path = f'/updates/sort/newest/mpage/{page}/'
        else:
            path = '/' if page == 1 else '/archive/' if page == 2 else f'/archive/page/{page - 1}/'
        soup, final = self.document(http, self.ROOT + path)
        rows = {}
        for card in soup.select(CARDS):
            if card.select_one('a[href*="/video/"]'):
                continue
            anchor = card.select_one('a[href]')
            if not anchor:
                continue
            target = self.site_link(anchor['href'], final)
            match = TITLE_PATH.fullmatch(urlsplit(target).path)
            name = (anchor.get('title') or node_text(card.select_one('figcaption'))).strip()
            if match and name:
                rows[match[1]] = self.row(name, match[1], self.image(card.select_one('img'), final))
        return list(rows.values()), bool(soup.select_one('.pagination-a li.next'))

    def vocabulary(self, http):
        soup, _ = self.document(http, self.ROOT + '/updates/sort/newest/')
        result = {}
        for control in soup.select('#filter-a span:has(> input)'):
            label = node_text(control.select_one('label'))
            raw = control.select_one('input[value]')
            slug = raw.get('value', '') if raw else ''
            if label and re.fullmatch(SEGMENT, slug):
                result.setdefault(slug, {'label': label, 'sourceId': slug, 'category': 'tag'})
        return list(result.values())

    def metadata(self, soup, final, path):
        heading = soup.select_one('#content h1, h1')
        name = node_text(heading) or node_text(soup.title)
        if not name:
            raise SourceError('Masonry не предоставил название галереи.')
        models = soup.select('p.link-btn a[href*="/model/"]')
        tags = soup.select('p.link-btn a[href*="/tag/"]')
        cover = soup.select_one('meta[property="og:image"][content]')
        return self.row(name, path, image_url(cover.get('content'), final) if cover else '',
                        description=node_text(soup.select_one('#content > p:not(.link-btn)'))[:12000],
                        tags=unique(node_text(item) for item in tags), genres=[],
                        authors=unique([node_text(soup.select_one('p.link-btn a[href]'))]),
                        artists=unique(node_text(item) for item in models), status='completed')

    def details(self, http, value):
        target = self.site_link(value)
        parts = urlsplit(target)
        match = TITLE_PATH.fullmatch(parts.path)
        if not match or parts.query:
            raise SourceError('Некорректная ссылка на карточку Masonry.')
        soup, final = self.document(http, target)
        return self.metadata(soup, final, match[1])

    def inspect(self, value, http):
        target = self.site_link(value)
        parts = urlsplit(target)
        match = TITLE_PATH.fullmatch(parts.path)
        if not match or parts.query not in {'', CHAPTER_QUERY}:
            raise SourceError('Некорректная ссылка на галерею Masonry.')
        origin = urlunsplit(parts._replace(query=''))
        soup, final = self.document(http, origin)
        row = self.metadata(soup, final, match[1])
        entry = {'url': row['url'] + '?' + CHAPTER_QUERY, 'title': 'Галерея', 'number': 1, 'season': 1,
                 'language': self.LANGUAGE, 'translator': ''}
        pages = []
        if parts.query == CHAPTER_QUERY:
            links = soup.select('.list-gallery a[href^="https://cdn."]')
            pages = [image_url(node.get('href'), final) for node in links]
            if not 0 < len(pages) <= 500 or not all(pages):
                raise SourceError('Masonry не предоставил полный набор страниц.')
        return {**row, 'url': entry['url'] if parts.query else row['url'], 'episodes': [entry], 'pages': pages,
                'available': True, 'truncated': False, 'seasons': [{'number': 1, 'name': 'Том 1'}],
                'dubs': [], 'releases': [], 'translations': []}

    def page_headers(self, value):
        return {'Referer': self.site_link(value).split('?', 1)[0]}

    def saved_chapter_url(self, value, path, root):
        actual = urlsplit(self.site_link(value, root))
        match = TITLE_PATH.fullmatch(actual.path)
        if match and match[1] == path:
            return urlunsplit(actual._replace(query=CHAPTER_QUERY))
        return ''


SOURCES = (
    Masonry('6842598531101194683', 'Elite Babes', 'https://www.elitebabes.com'),
    Masonry('9185590742756804817', 'Femjoy Hunter', 'https://www.femjoyhunter.com'),
    Masonry('2424130356866336342', 'FTV Hunter', 'https://www.ftvhunter.com'),
    Masonry('8421979328901634475', 'Joymii Hub', 'https://www.joymiihub.com'),
    Masonry('3567512546321944475', 'Metart Hunter', 'https://www.metarthunter.com'),
    Masonry('1082062847119890629', 'Playmate Hunter', 'https://pmatehunter.com'),
    Masonry('7425515716363969566', 'XArt Hunter', 'https://www.xarthunter.com'),
)
