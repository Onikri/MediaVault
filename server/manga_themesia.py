"""Native MangaThemesia catalogue and reader, based on Keiyoushi's Apache-2.0 multisrc."""

import base64
import json
import re
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from manga_madara import CHAPTER_NUMBER, SEGMENT, VOLUME_NUMBER, OriginPace, image_url, node_text, release_date
from manga_source_tags import unique
from source_parser import PublicHttp, SourceError, public_url


CARDS = '.utao .uta .imgu, .listupd .bs .bsx, .listo .bs .bsx'
SERIES = 'div.bigcontent, div.animefull, div.main-info, div.postbody'
TITLE = '.entry-title, .ts-breadcrumb li:last-child span'
ALTERNATE = '.alternative, .wd-full:-soup-contains("alt") span, .alter, .seriestualt'
GENRES = 'div.gnr a, .mgen a, .seriestugenre a, a[href*="genre/"]'
CHAPTERS = 'div.bxcl li, div.cl li, #chapterlist li, ul li:has(div.chbox):has(div.eph-num)'
READER_PREFIX = 'data:text/javascript;base64,dHNfcmVhZGVyLnJ1bih7'
IMAGE_LIST = re.compile(r'''["']?(?:images|imageUrls)["']?\s*[:=]\s*(\[)''')
FILTER_ID = re.compile(r'[\w-]{1,80}')


def image(node, base):
    if node:
        value = next((node[attr] for attr in ('data-lazy-src', 'data-src', 'data-cfsrc', 'src') if node.has_attr(attr)), '')
        return image_url(value, base)
    return ''


class MangaThemesia:
    def __init__(self, identity, *, section='manga', chapters=CHAPTERS, interval=0,
                 cards=CARDS, alternate=ALTERNATE, ignore_comments=False):
        self.SOURCE_ID, self.NAME, self.ROOT, self.IS_NSFW = identity
        self.LANGUAGE = 'en'
        self.host = urlsplit(self.ROOT).netloc
        self.section = section
        self.TITLE_PATH = re.compile(rf'/{section}/({SEGMENT})/?')
        self.CHAPTER_PATH = re.compile(rf'/({SEGMENT})/?')
        self.chapter_selector = chapters
        self.cards = cards
        self.alternate = alternate
        self.ignore_comments = ignore_comments
        self.origin = OriginPace()
        self.origin.interval = interval

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            target = urljoin(base or self.ROOT, value)
            parsed = urlsplit(target)
            if parsed.scheme == 'https' and parsed.netloc == self.host:
                return public_url(target, resolve_dns=False)
        except (ValueError, SourceError):
            pass
        return ''

    def document(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'})
        if not self.site_link(final) or urlsplit(final).path.rstrip('/') != urlsplit(url).path.rstrip('/'):
            raise SourceError('MangaThemesia перенаправил запрос на другую страницу.')
        soup = BeautifulSoup(raw, 'html.parser')
        from manga_sources import guard
        guard(soup)
        return soup, final

    def row(self, url, label, thumbnail):
        from manga_sources import title_aliases
        slug = self.TITLE_PATH.fullmatch(urlsplit(url).path)[1]
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'provider': 'suwayomi:' + self.SOURCE_ID,
                'providerName': self.NAME, 'sourceId': self.SOURCE_ID, 'sourceUrl': url, 'sourceURL': url, 'url': url,
                'kind': 'manga', 'language': self.LANGUAGE, 'title': label[:500], 'aliases': title_aliases(label),
                'cover': thumbnail, 'sourceOnly': True, 'ids': {}}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if not isinstance(page, int) or not 1 <= page <= 2000 or not isinstance(tag, str) or (tag and not FILTER_ID.fullmatch(tag)):
            raise SourceError('Некорректные параметры каталога MangaThemesia.')
        filters = {'page': page}
        if query:
            filters['title'] = query[:160]
        elif not tag:
            filters['order'] = 'update' if sort == 'updated' else 'popular'
        if tag:
            filters['genre[]'] = tag
        soup, final = self.document(http, f'{self.ROOT}/{self.section}/?' + urlencode(filters))
        rows = {}
        for card in soup.select(self.cards):
            anchor = card.select_one('a[href]')
            href = self.site_link(anchor.get('href'), final) if anchor else ''
            label = (anchor.get('title') or node_text(card.select_one('.tt'))).strip() if anchor else ''
            if href and label and self.TITLE_PATH.fullmatch(urlsplit(href).path):
                rows[href] = self.row(href, label, image(card.select_one('img'), final))
        more = bool(soup.select_one('div.pagination .next, div.hpage .r'))
        return list(rows.values()), more

    def vocabulary(self, http):
        soup, _ = self.document(http, f'{self.ROOT}/{self.section}/')
        terms = {}
        for node in soup.select('ul.genrez li'):
            control = node.select_one('input[type=checkbox][value]')
            label = node_text(node.select_one('label'))
            if control and label and FILTER_ID.fullmatch(control['value']):
                key = control['value']
                terms[key] = {'label': label, 'sourceId': key, 'category': 'genre'}
        return list(terms.values())

    def metadata(self, soup, url):
        if self.ignore_comments:
            for comment in soup.select('#comments'):
                comment.decompose()
        series = soup.select_one(SERIES)
        label = node_text(series.select_one(TITLE)) if series else ''
        if not label:
            raise SourceError('MangaThemesia не предоставил карточку произведения.')
        row = self.row(url, label, image(series.select_one('.infomanga > div[itemprop=image] img, .thumb img'), url))
        alternate = node_text(series.select_one(self.alternate))
        row['aliases'] = unique([*row['aliases'], *re.split(r'\s*[;|]\s*|\s+/\s+', alternate)])
        row['description'] = node_text(series.select_one('.desc, .entry-content[itemprop=description]'))[:12000]
        row['genres'] = unique(node_text(node) for node in series.select(GENRES))
        row['tags'] = []
        for heading in ('Status', 'Author', 'Artist', 'Type'):
            field = series.select_one(f'[itemprop="{heading.lower()}"], '
                                      f'.infotable tr:-soup-contains("{heading}") td:last-child, '
                                      f'.imptdt:-soup-contains("{heading}") :is(i, span, a), '
                                      f'.fmed b:-soup-contains("{heading}") + span')
            value = node_text(field)
            if heading in {'Author', 'Artist'}:
                row[heading.lower() + 's'] = [value] if value.casefold() not in {'', '-', 'n/a', 'unknown'} else []
            elif heading == 'Type':
                row['format'] = value.casefold()
            else:
                row['status'] = value
        return row

    def details(self, http, value):
        target = self.site_link(value)
        if not self.TITLE_PATH.fullmatch(urlsplit(target).path):
            raise SourceError('Некорректная ссылка на тайтл MangaThemesia.')
        return self.metadata(*self.document(http, target))

    def chapters(self, soup, url):
        chapters = {}
        for entry in soup.select(self.chapter_selector):
            anchor = entry.select_one('a[href]')
            target = self.site_link(anchor['href'], url) if anchor else ''
            path = urlsplit(target).path
            key = path.rstrip('/')
            if not self.CHAPTER_PATH.fullmatch(path) or key == '/' + self.section or key in chapters:
                continue
            label = node_text(entry.select_one('.lch a, .chapternum')) or node_text(anchor)
            number = CHAPTER_NUMBER.search(label) or CHAPTER_NUMBER.search(path)
            volume = VOLUME_NUMBER.search(label)
            node = entry.select_one('.chapterdate')
            date = release_date(node_text(node), '%B %d, %Y')
            if not chapters and not date:
                updated = soup.select_one('.listinfo time[itemprop=dateModified], .fmed time[datetime], span:-soup-contains("Updated") time[datetime]')
                date = release_date(updated.get('datetime', '') if updated else '', '%Y-%m-%d')
            chapters[key] = {'url': target, 'title': label, 'publishedAt': date, 'language': self.LANGUAGE,
                             'number': float(number[1].replace(',', '.')) if number else None,
                             'season': int(volume[1]) if volume else 1, 'translator': ''}
        rows = list(chapters.values())
        for index, row in enumerate(rows):
            if row['number'] is None:
                row['number'] = len(rows) - index
        return sorted(rows, key=lambda row: (row['season'], row['number']))

    def pages(self, soup, url):
        pages = [image(node, url) for node in soup.select('#readerarea img')]
        if not any(pages):
            scripts = []
            for node in soup.select('script'):
                if node.get('src', '').startswith(READER_PREFIX):
                    try:
                        scripts.append(base64.b64decode(node['src'].partition(',')[2], validate=True).decode())
                    except ValueError:
                        continue
                else:
                    scripts.append(node.string or '')
            decoder = json.JSONDecoder()
            for script in scripts:
                for match in IMAGE_LIST.finditer(script):
                    try:
                        values, _ = decoder.raw_decode(script[match.start(1):])
                    except ValueError:
                        continue
                    if values:
                        pages = [image_url(value, url) for value in values]
                        break
                if pages:
                    break
        if not pages or not all(pages) or len(pages) > 500:
            raise SourceError('MangaThemesia не предоставил полный список страниц открытой главы.')
        return pages

    def series_link(self, soup, url):
        anchor = soup.select_one('.allc a[href]')
        link = self.site_link(anchor['href'], url) if anchor else ''
        return link if self.TITLE_PATH.fullmatch(urlsplit(link).path) else ''

    def saved_chapter_url(self, value, title, root):
        return self.site_link(value, root)

    def saved_chapter_matches(self, target, title):
        http = PublicHttp(timeout=(3, 6))
        try:
            soup, final = self.document(http, target)
            parent = self.series_link(soup, final)
            return bool(parent and urlsplit(parent).path.rstrip('/') == urlsplit(title).path.rstrip('/'))
        finally:
            http.close()

    def inspect(self, value, http):
        target = self.site_link(value)
        path = urlsplit(target).path
        is_title = self.TITLE_PATH.fullmatch(path)
        if not (is_title or self.CHAPTER_PATH.fullmatch(path)):
            raise SourceError('Некорректная ссылка на читалку MangaThemesia.')
        soup, url = self.document(http, target)
        if is_title:
            series = self.metadata(soup, url)
            chapters = self.chapters(soup, url)
            pages = []
        else:
            title = self.series_link(soup, url)
            if not title:
                raise SourceError('MangaThemesia не предоставил ссылку главы на произведение.')
            label = node_text(soup.select_one('.entry-title, h1'))
            series = self.row(title, node_text(soup.select_one('.allc a')) or label, '')
            number = CHAPTER_NUMBER.search(label) or CHAPTER_NUMBER.search(path)
            chapters = [{'url': url, 'title': label, 'language': self.LANGUAGE,
                         'number': float(number[1].replace(',', '.')) if number else 0, 'season': 1, 'translator': ''}]
            pages = self.pages(soup, url)
        return {**series, 'url': url, 'episodes': chapters, 'pages': pages, 'available': bool(chapters),
                'truncated': False, 'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({c['season'] for c in chapters})],
                'dubs': [], 'releases': [], 'translations': []}


SOURCES = (
    MangaThemesia(('8513894820944573933', 'Akaza Scans', 'https://akazascans.org', False)),
    MangaThemesia(('8861274191478178487', 'Arena Scans', 'https://arenascan.com', True)),
    MangaThemesia(('1931493862544259486', 'Aster Scans', 'https://asterscans.com', False)),
    MangaThemesia(('4351130568935854113', 'Hades Scans', 'https://hadesscans.com', False)),
    MangaThemesia(('1428377199095994277', 'Hentai Desi', 'https://hentaidesi.com', True)),
    MangaThemesia(('9153097368891994905', 'King of Shojo', 'https://kingofshojo.com', True)),
    MangaThemesia(('7925933833035450162', 'Lagoon Scans', 'https://lagoonscans.com', False)),
    MangaThemesia(('1983630122600815139', 'Manga Trend', 'https://mangatrend.org', False)),
    MangaThemesia(('263040414613624318', 'Rackus', 'https://rackusreads.com', False)),
    MangaThemesia(('5160001879976399540', 'Raven Scans', 'https://ravenscans.org', True)),
    MangaThemesia(('4082152694771839662', 'Wildtoon', 'https://wildtoon.com', True), section='webtoon'),
    MangaThemesia(('8692263513374836785', 'Rage Scans', 'https://ragescans.com', False),
                 chapters="li:has(.chbox .eph-num):not(:has([data-bs-target='#lockedChapterModal']))", ignore_comments=True),
    MangaThemesia(('9079184529211162476', 'Violet Scans', 'https://violetmanga.com', False),
                 section='comics', chapters='#chapterlist li:not(:has(svg))',
                 cards='.utao .uta .imgu, .listupd .bs .bsx:not(:has(.novelabel)), .listo .bs .bsx:not(:has(.novelabel))',
                 alternate='.alternative .desktop-titles'),
    MangaThemesia(('427734044452073936', 'Athrea Scans', 'https://athreascans.com', True),
                 chapters='#chapterlist li:has(.eph-num a[href])', interval=0.5),
)

ENABLED = {'8513894820944573933', '7925933833035450162', '9079184529211162476'}
ACTIVE_SOURCES = tuple(adapter for adapter in SOURCES if adapter.SOURCE_ID in ENABLED)
