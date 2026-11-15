"""Native YiiManga and YiiMadara sources (Keiyoushi Apache-2.0)."""

import re
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from manga_madara import CHAPTER_NUMBER, SEGMENT, VOLUME_NUMBER, OriginPace, image_url, node_text, release_date
from manga_source_tags import unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import SourceAccessError, SourceError, public_url


SLUG = re.compile(SEGMENT)
HEADING = 'h1.main-info-title, .post-title h1, .manga-detail .info h1'
SYNPOSIS = '.short-desc-content, .dsct, .description-summary, .ss-manga, .post-content_item .entry-content'
COVER = 'img.img-cover, .summary_image img, .manga-detail .poster img'
YY_DATES = ('%d %b %Y', '%d %b %y', '%b %y')
ORIGIN_PACES = {}


def own_text(node):
    return ' '.join(text.strip() for text in node.find_all(string=True, recursive=False) if text.strip()) if node else ''


def image(node, base):
    return image_url(node.get('data-src') or node.get('src'), base) if node else ''


def source_date(value):
    for pattern in YY_DATES:
        if result := release_date(value, pattern):
            return result
    return ''


def valid_label(value):
    return value.casefold() not in {'', '-', 'updating', 'n/a', 'unknown'}


class Yii:
    IS_NSFW = True
    index_sort = 'updated'

    def __init__(self, sid, name, root, language='en', *, layout='manga', section='manga', search=None,
                 popular='', directory='manga', raw='', completed='completed', slash=False,
                 page_segment=False, mode='', scoped=False, interval=0):
        self.SOURCE_ID, self.NAME, self.ROOT, self.LANGUAGE = sid, name, root, language
        self.host = urlsplit(root).netloc
        self.layout, self.section, self.mode, self.scoped_urls = layout, section, mode, scoped
        self.search_param = search or ('q' if layout == 'madara' else 's')
        self.popular, self.directory, self.raw, self.completed = popular, directory, raw, completed
        self.slash, self.page_segment = slash, page_segment
        self.TITLE_PATH = re.compile(rf'/{section}/({SEGMENT})/?')
        self.CHAPTER_PATH = re.compile(rf'/{section}/({SEGMENT})/({SEGMENT})/?')
        self.pace = ORIGIN_PACES.setdefault(self.host, OriginPace())
        self.pace.interval = max(self.pace.interval, interval)

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, target = split_reader_url(urljoin(base or self.ROOT, value))
            parts = urlsplit(target)
            if selected in (None, self.SOURCE_ID) and parts.netloc == self.host:
                return public_url(target, resolve_dns=False)
        except (SourceError, ValueError):
            pass
        return ''

    def reader_url(self, target):
        return reader_url(target, self.SOURCE_ID) if self.scoped_urls else target

    def document(self, http, url):
        from manga_sources import guard

        self.pace.wait(getattr(http, 'deadline', None))
        text, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'})
        if not self.site_link(final) or urlsplit(final).path.rstrip('/') != urlsplit(url).path.rstrip('/'):
            raise SourceError('Yii перенаправил запрос на другой маршрут.')
        soup = BeautifulSoup(text, 'html.parser')
        guard(soup)
        return soup, final

    def row(self, label, url, slug, cover=''):
        from manga_sources import title_aliases

        ref = self.reader_url(url)
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'sourceId': self.SOURCE_ID,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME, 'kind': 'manga',
                'sourceUrl': ref, 'sourceURL': ref, 'url': ref, 'sourceOnly': True, 'ids': {},
                'language': self.LANGUAGE, 'title': label[:500], 'aliases': title_aliases(label), 'cover': cover}

    def list_url(self, page, query, sort, tag):
        if query:
            suffix = '/' if self.layout == 'manga' or self.slash else ''
            term = query.replace("'", '’') if self.layout == 'madara' else query
            return self.ROOT + '/search' + suffix + '?' + urlencode({self.search_param: term, 'page': page}), False
        if self.layout == 'manga':
            if tag:
                path = 'genre/' + tag
                paging = '/' if self.mode == 'toongod' else '/page/'
                return f'{self.ROOT}/{path}{paging}{page}/', False
            path = self.popular + '/' if sort == 'popular' and self.popular else ''
            return f'{self.ROOT}/{path}page/{page}/' + ('?order=views' if path else ''), False
        if self.mode == 'fx' and not tag:
            if sort == 'popular':
                return f'{self.ROOT}/hot-manga?page={page}', False
            return f'{self.ROOT}/page/{page}', False
        path = tag or self.directory
        segment = '/page' if self.page_segment or self.mode == 'dna' and path == self.directory else ''
        suffix = '/' if self.slash else ''
        order = '?orderby=trending' if sort == 'popular' and not tag else ''
        return f'{self.ROOT}/{path}{segment}/{page}{suffix}{order}', bool(self.raw and path == self.raw)

    def accept_language(self, label, path, raw_listing):
        if self.layout != 'madara' or self.LANGUAGE == 'all' or self.mode == 'dass' or raw_listing:
            return True
        raw = path.rstrip('/').endswith('-raw') or label.casefold().endswith(' raw')
        return raw == (self.LANGUAGE == 'ko')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or not isinstance(tag, str):
            raise SourceError('Некорректные параметры каталога Yii.')
        if tag and not self.valid_term(tag):
            raise SourceError('Некорректный жанр каталога Yii.')
        if self.mode == 'buddy' and sort == 'popular' and not query and not tag:
            if page != 1:
                return [], False
            url, cards, anchors, next_page, raw = self.ROOT + '/', '.item-move', '.name a[href]', None, False
        else:
            url, raw = self.list_url(page, query.strip()[:160], sort, tag)
            if self.layout == 'manga':
                cards = '.latest-list .latest-item, .list .list-item'
                anchors = '.latest-right a:has(h3, h4), .item-title a[href]'
                next_page = '#pagination li.next a[href]'
            else:
                cards, anchors = 'div.page-item, div.page-item-detail, div.home-item, div.manga-item', 'h3 a[href]'
                next_page = '#blog-pager li.next a[href]'
        soup, final = self.document(http, url)
        rows = {}
        for card in soup.select(cards):
            anchor = card.select_one(anchors)
            if not anchor:
                continue
            target = self.site_link(anchor.get('href'), final)
            path = urlsplit(target).path
            match = self.TITLE_PATH.fullmatch(path)
            label = node_text(anchor)
            if not match or not label or not self.accept_language(label, path, raw):
                continue
            thumbnail = card.select_one('.latest-left img, .item-img img') if self.layout == 'manga' and self.mode != 'buddy' else card.select_one('img')
            rows.setdefault(match[1], self.row(label, target, match[1], image(thumbnail, final)))
        return list(rows.values()), bool(next_page and soup.select_one(next_page))

    def valid_term(self, term):
        if self.layout == 'manga':
            return bool(SLUG.fullmatch(term))
        return term in {self.raw, self.completed} or bool(re.fullmatch(rf'genre/{SEGMENT}', term))

    def vocabulary(self, http):
        if self.mode == 'm18me':
            return [{'label': label, 'sourceId': 'genre/' + slug, 'category': 'genre'} for label, slug in M18_GENRES]
        soup, final = self.document(http, self.ROOT + '/')
        terms = {}
        links = ('.genre-list a[href], a.item-nav[href*="/genre/"], a.item-nav-mb[href*="/genre/"]'
                 if self.layout == 'manga' else 'a[href*="genre/"]')
        for item in soup.select(links):
            label = node_text(item)
            target = urlsplit(self.site_link(item.get('href'), final)).path.strip('/')
            if self.layout == 'manga':
                target = target.removeprefix('genre/') if target.startswith('genre/') else ''
            if label and target and self.valid_term(target):
                terms.setdefault(target, {'label': label, 'sourceId': target, 'category': 'genre'})
        return list(terms.values())

    def fields(self, soup):
        result = {}
        if self.layout == 'manga':
            for item in soup.select('.main-info-list li, .post-content_item, .info-item'):
                label = item.select_one(':scope > h5, :scope > .summary-heading > h5, :scope > span.sh')
                value = item.select_one(':scope > :not(h5, .summary-heading, .sh)')
                key = node_text(label).rstrip(' :-').casefold()
                if label and value:
                    result[key] = value
        else:
            for item in soup.select('.post-content_item, .minfo'):
                label = item.select_one(':scope > .summary-heading, :scope > b')
                value = item.select_one(':scope > .summary-content, :scope > i, :scope > span:not(.summary-heading)')
                key = (node_text(label) or own_text(item)).rstrip(' :-').casefold()
                if key and value:
                    result[key] = value
        return result

    def metadata(self, soup, url):
        match = self.TITLE_PATH.fullmatch(urlsplit(url).path)
        heading = soup.select_one(HEADING)
        label = (own_text(heading) or node_text(heading)) if self.layout == 'madara' else node_text(heading)
        if not label or not match:
            raise SourceError('Yii не предоставил карточку тайтла.')
        row = self.row(label, url, match[1], image(soup.select_one(COVER), url))
        fields = self.fields(soup)

        def value(*keys):
            return next((fields[key] for key in keys if key in fields), None)

        for key, choices in (('genres', ('genres', 'genre', 'genre(s)', 'géneros')),
                             ('authors', ('author', 'author(s)', 'autores')),
                             ('artists', ('artist', 'artist(s)', 'artistas'))):
            node = value(*choices)
            linked = [own_text(a) or node_text(a) for a in node.select('a')] if node else []
            names = linked or re.split(r'[,;]', node_text(node))
            row[key] = unique(name for part in names if valid_label(name := part.strip()))
        synopsis = soup.select_one(SYNPOSIS)
        alternative = node_text(value('alternative')) or node_text(soup.select_one('.main-info-list li > h4, .manga-detail .info h6'))
        row.update(description=node_text(synopsis)[:12000], status=node_text(value('status', 'estado') or soup.select_one('.manga-detail .info p.type')),
                   aliases=unique([*row['aliases'], *re.split(r'\s*[;|]\s*|\s+/\s+', alternative)]),
                   tags=[], format=node_text(value('type')).casefold())
        return row

    def details(self, http, value):
        url = self.site_link(value)
        if not self.TITLE_PATH.fullmatch(urlsplit(url).path):
            raise SourceError('Некорректная ссылка на тайтл Yii.')
        return self.metadata(*self.document(http, url))

    def chapters(self, soup, url, slug):
        result = {}
        for item in soup.select('ul.chapter-list li, ul.row-content-chapter li, .list-items li.item'):
            anchor = item.select_one('a[href]')
            target = self.site_link(anchor.get('href'), url) if anchor else ''
            path = urlsplit(target).path
            match = self.CHAPTER_PATH.fullmatch(path)
            if not match or match[1] != slug:
                continue
            title = node_text(item.select_one('.chapter-name, .item a > span:first-child')) or node_text(anchor)
            number = CHAPTER_NUMBER.search(title) or CHAPTER_NUMBER.search(match[2])
            volume = VOLUME_NUMBER.search(title)
            stamp = node_text(item.select_one('.ct-update, .chapter-time, .item a > span:nth-child(2)'))
            result.setdefault(path.rstrip('/'), {'url': self.reader_url(target), 'title': title,
                'number': float(number[1].replace(',', '.')) if number else None, 'season': int(volume[1]) if volume else 1,
                'language': self.LANGUAGE, 'translator': '', 'publishedAt': source_date(stamp)})
        rows = list(result.values())
        for i, chapter in enumerate(rows):
            if chapter['number'] is None:
                chapter['number'] = len(rows) - i
        return sorted(rows, key=lambda item: (item['season'], item['number']))

    def inspect(self, value, http):
        target = self.site_link(value)
        path = urlsplit(target).path
        title, chapter = self.TITLE_PATH.fullmatch(path), self.CHAPTER_PATH.fullmatch(path)
        if not (title or chapter):
            raise SourceError('Некорректная ссылка на тайтл или главу Yii.')
        soup, url = self.document(http, target)
        pages = []
        if title:
            row = self.metadata(soup, url)
            episodes = self.chapters(soup, url, title[1])
        else:
            images = '.read-content img' if self.layout == 'madara' else '.reading-content img, .read-content img'
            pages = [image(node, url) for node in soup.select(images)]
            if not 0 < len(pages) <= 500 or not all(pages):
                raise SourceAccessError('Yii не предоставил полный набор страниц открытой главы.')
            suffix = '/' if self.slash or self.layout == 'manga' else ''
            parent = f'{self.ROOT}/{self.section}/{chapter[1]}{suffix}'
            row = self.details(http, parent)
            label = node_text(soup.select_one('.chapter-title, .post-title h1, h1'))
            number = CHAPTER_NUMBER.search(label) or CHAPTER_NUMBER.search(chapter[2])
            episodes = [{'url': self.reader_url(url), 'title': label or chapter[2], 'language': self.LANGUAGE,
                         'number': float(number[1].replace(',', '.')) if number else 1, 'season': 1, 'translator': ''}]
        return {**row, 'url': self.reader_url(url), 'episodes': episodes, 'pages': pages, 'available': bool(episodes),
                'truncated': False, 'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({c['season'] for c in episodes})],
                'dubs': [], 'releases': [], 'translations': []}

    def saved_chapter_url(self, value, slug, root):
        if isinstance(value, str) and SLUG.fullmatch(value):
            return f'{self.ROOT}/{self.section}/{slug}/{value}'
        return self.site_link(value, root)


M18_GENRES = (
    ('Action', 'action'),
    ('Adult', 'adult'),
    ('Adventure', 'adventure'),
    ('BL', 'bl'),
    ('Comedy', 'comedy'),
    ('Drama', 'drama'),
    ('Ecchi', 'ecchi'),
    ('Family', 'family'),
    ('Fantasy', 'fantasy'),
    ('Gender Bender', 'gender-bender'),
    ('GL', 'gl'),
    ('Harem', 'harem'),
    ('Hentai', 'hentai'),
    ('Historical', 'historical'),
    ('Horror', 'horror'),
    ('Isekai', 'isekai'),
    ('Josei', 'josei'),
    ('Magic', 'magic'),
    ('Manhua', 'manhua'),
    ('Manhwa', 'manhwa'),
    ('Martial Arts', 'martial-arts'),
    ('Mature', 'mature'),
    ('Mystery', 'mystery'),
    ('Psychological', 'psychological'),
    ('Romance', 'romance'),
    ('School Life', 'school-life'),
    ('Sci-Fi', 'sci-fi'),
    ('Seinen', 'seinen'),
    ('Shoujo', 'shoujo'),
    ('Shounen', 'shounen'),
    ('Slice of Life', 'slice-of-life'),
    ('Smut', 'smut'),
    ('Sports', 'sports'),
    ('Supernatural', 'supernatural'),
    ('Thriller', 'thriller'),
    ('Tragedy', 'tragedy'),
    ('Uncensored', 'uncensored'),
    ('Yaoi', 'yaoi'),
    ('Yuri', 'yuri'),
)


SOURCES = (
    Yii('5575864808495704378', 'Manga18fx', 'https://manga18fx.com', 'all',
        layout='madara', raw='manhwa-raw', directory='', completed='', mode='fx', scoped=True),
    Yii('3157287889751723714', 'Manga18fx', 'https://manga18fx.com',
        layout='madara', raw='manhwa-raw', directory='', completed='', mode='fx', scoped=True),
    Yii('1353606378087565589', 'Manga18.me', 'https://manga18.me', 'all',
        layout='madara', raw='manhwa-raw', mode='m18me', scoped=True),
    Yii('6244055465910932489', 'Manga18.me', 'https://manga18.me',
        layout='madara', raw='manhwa-raw', mode='m18me', scoped=True),
    Yii('5181311401760417052', 'MangaDNA', 'https://mangadna.com',
        layout='madara', raw='manhwa-raw', completed='', interval=0.5, mode='dna', scoped=True),
    Yii('6255493077716027174', 'MangaDNA', 'https://mangadna.com', 'all',
        layout='madara', raw='manhwa-raw', completed='', interval=0.5, mode='dna', scoped=True),
    Yii('4841602236575491202', 'Manhwa18.cc', 'https://manhwa18.cc',
        layout='madara', section='webtoon', raw='raw', directory='webtoons', scoped=True),
    Yii('6864643444164576223', 'Manhwa18.cc', 'https://manhwa18.cc', 'ko',
        layout='madara', section='webtoon', raw='raw', directory='raw', scoped=True),
    Yii('993336618407081332', 'Manhwa18.cc', 'https://manhwa18.cc', 'all',
        layout='madara', section='webtoon', raw='raw', directory='webtoons', scoped=True),
    Yii('3992984777516935224', '4PornComic', 'https://4porncomic.com',
        section='comic', search='q', popular='porn-comics'),
    Yii('3598862142817438721', 'Hentai20 (Unoriginal)', 'https://hentai20.lol',
        section='manga', popular='manga-lists'),
    Yii('5571661567325096882', 'Manga Dass', 'https://mangadass.com',
        layout='madara', raw='raw-manhwa', interval=0.333333, mode='dass'),
    Yii('1509372624702907317', 'Manhwa18TX', 'https://manhwa18tx.com',
        section='manhwa', search='q'),
    Yii('397029358682805931', 'ManhwaBuddy', 'https://manhwabuddy.com',
        section='manhwa', mode='buddy'),
    Yii('562792527363909585', 'Manhwaddict', 'https://manhwaddict.com',
        section='manga', search='q'),
    Yii('7576857265985588198', 'ManhwaGalaxy', 'https://manhwagalaxy.com',
        section='manhwa', search='q'),
    Yii('6460882153975501439', 'ManhwaOnline', 'https://manhwaonline.org',
        section='manga', popular='webtoons'),
    Yii('3074048504222281188', 'ManhwaUS', 'https://manhwaus.net',
        layout='madara', section='webtoon', search='s', raw='raw', directory='webtoons', slash=True, page_segment=True),
    Yii('2242106898634732967', 'MyReadingComic', 'https://myreadingcomic.com',
        section='comic', search='q', popular='porn-comics'),
    Yii('8341261297497729714', 'ReadManga18', 'https://readmanga18.com',
        layout='madara', search='s', raw='raw', completed='', slash=True),
    Yii('339438238793535753', 'ToonGod (Unoriginal)', 'https://toongod.cc',
        section='webtoon', popular='webtoons', mode='toongod'),
    Yii('2975409305226490397', 'YaoiScan (Unoriginal)', 'https://yaoiscan.me',
        section='read', search='q'),
)
