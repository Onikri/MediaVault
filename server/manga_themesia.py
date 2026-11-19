"""Native MangaThemesia catalogue and reader, based on Keiyoushi's Apache-2.0 multisrc."""

import base64
import json
import re
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_madara import CHAPTER_NUMBER, SEGMENT, VOLUME_NUMBER, OriginPace, image_url, node_text, release_date
from manga_source_tags import unique
from manga_source_urls import reader_url, split_reader_url
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
                 cards=CARDS, alternate=ALTERNATE, ignore_comments=False, language='en'):
        self.SOURCE_ID, self.NAME, self.ROOT, self.IS_NSFW = identity
        self.LANGUAGE = language
        self.scoped_urls = language != 'en'
        self.host = urlsplit(self.ROOT).netloc
        self.section = section
        self.TITLE_PATH = re.compile(rf'/{section}/({SEGMENT})/?')
        self.CHAPTER_PATH = re.compile(rf'/({SEGMENT})/?')
        self.chapter_selector = chapters
        self.cards = cards
        self.alternate = alternate
        self.ignore_comments = ignore_comments
        self.reader_selector = '#readerarea img'
        self.chapter_name_selector = '.lch a, .chapternum'
        self.chapter_date_selector = '.chapterdate'
        self.chapter_date_format = '%B %d, %Y'
        self.origin = OriginPace()
        self.origin.interval = interval

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, target = split_reader_url(urljoin(base or self.ROOT, value))
            if selected not in (None, self.SOURCE_ID):
                return ''
            parsed = urlsplit(target)
            if parsed.scheme == 'https' and parsed.netloc == self.host:
                return public_url(target, resolve_dns=False)
        except (ValueError, SourceError):
            pass
        return ''

    def reader_url(self, url):
        return reader_url(url, self.SOURCE_ID) if self.scoped_urls else url

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
        url = self.reader_url(url)
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'provider': 'suwayomi:' + self.SOURCE_ID,
                'providerName': self.NAME, 'sourceId': self.SOURCE_ID, 'sourceUrl': url, 'sourceURL': url, 'url': url,
                'kind': 'manga', 'language': self.LANGUAGE, 'title': label[:500], 'aliases': title_aliases(label),
                'cover': thumbnail, 'sourceOnly': True, 'ids': {}}

    def catalogue_route(self, page, query, sort, tag):
        filters = {'page': page}
        if query:
            filters['title'] = query[:160]
        elif not tag:
            filters['order'] = 'update' if sort == 'updated' else 'popular'
        if tag:
            filters['genre[]'] = tag
        return f'/{self.section}/?' + urlencode(filters), self.cards, 'div.pagination .next, div.hpage .r'

    def card_label(self, card, anchor):
        return anchor.get('title') or node_text(card.select_one('.tt'))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if not isinstance(page, int) or not 1 <= page <= 2000 or not isinstance(tag, str) or (tag and not FILTER_ID.fullmatch(tag)):
            raise SourceError('Некорректные параметры каталога MangaThemesia.')
        route, cards, next_page = self.catalogue_route(page, query, sort, tag)
        if not route:
            return [], False
        soup, final = self.document(http, self.ROOT + route)
        rows = {}
        for card in soup.select(cards):
            anchor = card if card.name == 'a' and card.has_attr('href') else card.select_one('a[href]')
            href = self.site_link(anchor.get('href'), final) if anchor else ''
            label = self.card_label(card, anchor).strip() if anchor else ''
            if href and label and self.TITLE_PATH.fullmatch(urlsplit(href).path):
                rows[href] = self.row(href, label, image(card.select_one('img'), final))
        more = bool(next_page and soup.select_one(next_page))
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

    def title_document(self, http, url):
        return self.document(http, url)

    def details(self, http, value):
        target = self.site_link(value)
        if not self.TITLE_PATH.fullmatch(urlsplit(target).path):
            raise SourceError('Некорректная ссылка на тайтл MangaThemesia.')
        return self.metadata(*self.title_document(http, target))

    def chapters(self, soup, url):
        chapters = {}
        for entry in soup.select(self.chapter_selector):
            anchor = entry.select_one('a[href]')
            target = self.site_link(anchor['href'], url) if anchor else ''
            path = urlsplit(target).path
            key = path.rstrip('/')
            if not self.CHAPTER_PATH.fullmatch(path) or key == '/' + self.section or key in chapters:
                continue
            label = node_text(entry.select_one(self.chapter_name_selector)) or node_text(anchor)
            number = CHAPTER_NUMBER.search(label) or CHAPTER_NUMBER.search(path)
            volume = VOLUME_NUMBER.search(label)
            node = entry.select_one(self.chapter_date_selector)
            date = release_date(re.sub(r'(?<=\d)(?:st|nd|rd|th)\b', '', node_text(node)), self.chapter_date_format)
            if not chapters and not date:
                updated = soup.select_one('.listinfo time[itemprop=dateModified], .fmed time[datetime], span:-soup-contains("Updated") time[datetime]')
                date = release_date(updated.get('datetime', '') if updated else '', '%Y-%m-%d')
            chapters[key] = {'url': self.reader_url(target), 'title': label, 'publishedAt': date, 'language': self.LANGUAGE,
                             'number': float(number[1].replace(',', '.')) if number else None,
                             'season': int(volume[1]) if volume else 1, 'translator': ''}
        rows = list(chapters.values())
        for index, row in enumerate(rows):
            if row['number'] is None:
                row['number'] = len(rows) - index
        return sorted(rows, key=lambda row: (row['season'], row['number']))

    def pages(self, soup, url):
        pages = [self.reader_image(node, url) for node in soup.select(self.reader_selector)]
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
                        pages = [self.script_image(value, url) for value in values]
                        break
                if pages:
                    break
        if not pages or not all(pages) or len(pages) > 500:
            raise SourceError('MangaThemesia не предоставил полный список страниц открытой главы.')
        return pages

    def reader_image(self, node, url):
        return image(node, url)

    def script_image(self, value, url):
        return image_url(value, url)

    def series_link(self, soup, url):
        for anchor in soup.select('.allc a[href], .ts-breadcrumb a[href], [class*="breadcrumb"] a[href], a[rel="up"][href]'):
            link = self.site_link(anchor['href'], url)
            if self.TITLE_PATH.fullmatch(urlsplit(link).path):
                return link
        return ''

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
        soup, url = (self.title_document(http, target) if is_title else self.document(http, target))
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
            chapters = [{'url': self.reader_url(url), 'title': label, 'language': self.LANGUAGE,
                         'number': float(number[1].replace(',', '.')) if number else 0, 'season': 1, 'translator': ''}]
            pages = self.pages(soup, url)
        return {**series, 'url': self.reader_url(url), 'episodes': chapters, 'pages': pages, 'available': bool(chapters),
                'truncated': False, 'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({c['season'] for c in chapters})],
                'dubs': [], 'releases': [], 'translations': []}


PAID_CHAPTERS = ', '.join(selector.strip() + ':has(a[href]):not(:has(a[data-bs-target], a[data-coin], .locked-badge))'
                          for selector in CHAPTERS.split(','))


class MiauScan(MangaThemesia):
    LANGUAGE_MARK = re.compile(r'^\(\s*Portugu[êe]s\s*\)\s*', re.I)
    # leemiau.com moved to leer.lectovela.com (extension 04d0ed69, 2026-11-16).
    LEGACY_HOSTS = frozenset({'leemiau.com', 'www.leemiau.com'})
    # Chapters from 2023 still list http://miauscans.com/wp-content/uploads/...;
    # that domain now redirects to an unrelated site, while the same uploads are
    # served by the current host.
    OLD_UPLOADS = frozenset({'miauscans.com', 'www.miauscans.com', 'leemiau.com', 'www.leemiau.com'})

    def script_image(self, value, url):
        try:
            parts = urlsplit(value) if isinstance(value, str) else None
        except ValueError:
            parts = None
        if parts and parts.netloc in self.OLD_UPLOADS and parts.path.startswith('/wp-content/uploads/'):
            value = urlunsplit(('https', self.host, parts.path, parts.query, ''))
        return super().script_image(value, url)

    def site_link(self, value, base=None):
        found = super().site_link(value, base)
        if found or not isinstance(value, str):
            return found
        try:
            parts = urlsplit(value)
        except ValueError:
            return ''
        if parts.scheme in {'http', 'https'} and parts.netloc in self.LEGACY_HOSTS:
            return super().site_link(urlunsplit(parts._replace(scheme='https', netloc=self.host)))
        return ''

    def __init__(self, identity, language):
        super().__init__(identity, language=language, chapters=CHAPTERS + ', #chapterlist .lm4-chapter-item')
        self.chapter_name_selector = '.lm4-chapter-name, .chapternum'
        self.chapter_date_selector = '.lm4-chapter-date, .chapterdate'
        self.chapter_date_format = '%d/%m/%Y'

    def series_link(self, soup, url):
        # The lectovela reader links its title from the top bar and summary card.
        for anchor in soup.select('a.lm-reader-summary-mini[href], a.lm-reader-topbar-btn[href]'):
            link = self.site_link(anchor['href'], url)
            if self.TITLE_PATH.fullmatch(urlsplit(link).path):
                return link
        return super().series_link(soup, url)

    def catalogue_route(self, page, query, sort, tag):
        path, selectors, nxt = super().catalogue_route(page, query, sort, tag)
        if self.LANGUAGE == 'pt-BR' and tag != '307':
            path += '&' + urlencode({'genre[]': '307'})
        return path, selectors, nxt

    def row(self, url, label, thumbnail):
        return super().row(url, self.LANGUAGE_MARK.sub('', label), thumbnail)

    def metadata(self, soup, url):
        row = super().metadata(soup, url)
        row['cover'] = image(soup.select_one('img.lm4-poster-image'), url) or row['cover']
        row['description'] = node_text(soup.select_one('.lm4-summary-full, .lm4-summary-short')) or row['description']
        row['status'] = node_text(soup.select_one('.lm4-poster-status')) or row.get('status', '')
        row['genres'] = [label for label in row['genres'] if label.casefold() not in {'português', 'portugues'}]
        return row

    def chapters(self, soup, url):
        result = super().chapters(soup, url)
        subtitles = {}
        for node in soup.select(self.chapter_selector):
            link = node.select_one('a[href]')
            target = self.site_link(link['href'], url) if link else ''
            subtitle = node_text(node.select_one('.lm4-chapter-subtitle'))
            if target and subtitle:
                subtitles[self.reader_url(target)] = subtitle
        for entry in result:
            subtitle = subtitles.get(entry['url'])
            if subtitle and subtitle != entry['title']:
                entry['title'] += ' — ' + subtitle
        return result

    def vocabulary(self, http):
        return [row for row in super().vocabulary(http) if row['sourceId'] != '307']

    def reader_image(self, node, url):
        return self.script_image(node.get('data-lm-orig-src'), url) or super().reader_image(node, url)


class ComicAsura(MangaThemesia):
    def __init__(self, identity):
        super().__init__(identity, interval=2, chapters='.chapter-items')
        self.chapter_name_selector = '.text-sm.text-white'
        self.chapter_date_selector = '[class~="text-[#A2A2A2]"].text-xs:not(:has(span))'
        self.chapter_date_format = '%B %d %Y'
        self.reader_selector = 'div > img.object-cover.mx-auto'
        self.CHAPTER_PATH = re.compile(rf'/(?:manga/{SEGMENT}/|chapter/)?({SEGMENT})/?')

    def catalogue_route(self, page, query, sort, tag):
        params = {'name': query, 'page': page}
        if not query:
            params['sort'] = 'latest' if sort == 'updated' else 'rating'
        if tag:
            params['genres'] = tag
        return ('/advanced-search/?' + urlencode(params),
                '.grid > a[href*=manga], .flex-wrap.flex a[href*=manga]', 'a:has(img[alt=Next])')

    def card_label(self, card, anchor):
        img = card.select_one('img[title]')
        return img['title'] if img else super().card_label(card, anchor)

    def metadata(self, soup, url):
        block = soup.select_one('[class~="bg-[#222222]"]:has(h1)')
        label = node_text(block.select_one('.comic-title-content')) if block else ''
        if not label:
            raise SourceError('Comic Asura не предоставил карточку произведения.')
        row = self.row(url, label, image(block.select_one('img[alt=poster]'), url))
        row['description'] = node_text(block.select_one('.comic-content.mobile'))
        row['genres'] = unique(node_text(a) for a in block.select('div.hidden div:-soup-contains("Genres") + div > a'))
        row['status'] = node_text(block.select_one('div:-soup-contains("Status") + div'))
        row['tags'] = []
        return row

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/advanced-search/')
        return [{'label': node_text(row.select_one('span')), 'sourceId': row.select_one('input')['value'], 'category': 'genre'}
                for row in doc.select('.filter-dropdown-container label:has(input[name*=genres][value]):has(span)')]


class RotatingSlugThemesia(MangaThemesia):
    def permanent(self, url):
        parts = urlsplit(url)
        match = self.TITLE_PATH.fullmatch(parts.path)
        if not match:
            return url
        slug = re.sub(r'^\d+-', '', match[1])
        return urlunsplit(parts._replace(path=f'/{self.section}/{slug}/'))

    def row(self, url, label, thumbnail):
        return super().row(self.permanent(url), label, thumbnail)

    def saved_title_url(self, url):
        return self.permanent(url)

    def title_document(self, http, url):
        if self.permanent(url).rstrip('/') != url.rstrip('/'):
            return self.document(http, url)
        directory = f'{self.ROOT}/{self.section}/list-mode/'
        doc, final = self.document(http, directory)
        for anchor in doc.select('div#content div.soralist ul li a.series[href]'):
            link = self.site_link(anchor['href'], final)
            if link and self.permanent(link).rstrip('/') == url.rstrip('/'):
                return self.document(http, link)
        return self.document(http, url)

    def saved_chapter_matches(self, target, title):
        http = PublicHttp(timeout=(3, 6))
        try:
            soup, final = self.document(http, target)
            parent = self.series_link(soup, final)
            return bool(parent and self.permanent(parent).rstrip('/') == self.permanent(title).rstrip('/'))
        finally:
            http.close()


class RokariComics(RotatingSlugThemesia):
    def catalogue_route(self, page, query, sort, tag):
        if tag:
            return super().catalogue_route(page, query, sort, tag)
        if query:
            return '/?' + urlencode({'s': query, 'page': page}), self.cards, 'div.hpage .r, div.pagination .next'
        if sort == 'updated':
            return ('/' if page == 1 else f'/page/{page}/',
                    '.bixbox:has(h2:-soup-contains("Latest")) .bs .bsx', 'div.hpage .r, div.pagination .next')
        return ('/' if page == 1 else '', '.bixbox:has(h2:-soup-contains("Popular")) .bs .bsx', '')


class ThunderScans(RotatingSlugThemesia):
    def card_label(self, card, anchor):
        return node_text(card.select_one('.bigor .tt, h3 a')) or super().card_label(card, anchor)


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
                 chapters='#chapterlist li:has(.eph-num):has(a[href])', interval=0.5),
    MiauScan(('2886862669347225416', 'Miau Scan', 'https://leer.lectovela.com', True), 'es'),
    MiauScan(('6705370418823255358', 'Miau Scan', 'https://leer.lectovela.com', True), 'pt-BR'),
    ComicAsura(('499082788596590240', 'Comic Asura', 'https://comicasura.net', True)),
    MangaThemesia(('1124131000360667434', 'Scythe Scans', 'https://scythescans.com', False), interval=1/3),
    MangaThemesia(('1911019612901009263', 'Eva Scans', 'https://evascans.net', False),
                 section='series', chapters=PAID_CHAPTERS, alternate='.desktop-titles'),
    MangaThemesia(('9025563662441338944', 'Madara Scans', 'https://madarascans.net', False),
                 section='series', chapters=PAID_CHAPTERS),
    RokariComics(('830150807344972132', 'RokariComics', 'https://rokaricomics.com', False),
                 chapters='#chapterlist li:has(div.chbox):has(div.eph-num):has(a[href]):not(:has(.text-gold))'),
    ThunderScans(('2848420679472350044', 'Thunder Scans', 'https://en-thunderscans.com', False),
                 section='comics', chapters=PAID_CHAPTERS),
)

ENABLED = {'8513894820944573933', '1931493862544259486', '7925933833035450162', '9079184529211162476'}
ACTIVE_SOURCES = tuple(adapter for adapter in SOURCES if adapter.SOURCE_ID in ENABLED)
