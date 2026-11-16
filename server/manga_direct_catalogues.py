"""Direct catalogue and chapter routes from the installed extension inventory."""

import base64
import binascii
import re
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from urllib.parse import parse_qs, quote, urljoin, urlsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Archive, Cards, Meta, SeriesPort, picture
from manga_source_tags import unique
from manga_webcomics import param, query_url
from source_parser import SourceError


SLUG = rf'({SEGMENT})'
MANGA = rf'/manga/{SLUG}/?'
CHAPTER = rf'/manga/{SLUG}/{SEGMENT}(?:/{SEGMENT})?/?'
SERIES = rf'/series/{SLUG}/?'
SERIES_CHAPTER = rf'/series/{SLUG}/{SEGMENT}/?'


@dataclass(frozen=True)
class Browse:
    path: str
    args: tuple = ()
    cards: Cards | None = None
    one_page: bool = False
    first_path: str | None = None

    def url(self, root, page, query, tag):
        def component(value):
            return quote(value, safe='')

        options = {'page': page, 'query': component(query), 'tag': component(tag)}
        template = self.first_path if page == 1 and self.first_path is not None else self.path
        path = template.format(**options)
        args = {name: value.format(page=page, query=query, tag=tag) for name, value in self.args}
        return query_url(root + path, **args) if args else root + path


@dataclass(frozen=True)
class Layout:
    title: str
    chapter: str
    cards: Cards
    meta: Meta
    archive: Archive
    reader: str
    popular: Browse
    search: Browse | None = None
    latest: Browse | None = None
    browse_tag: Browse | None = None
    title_path: str = '/manga/'
    suffix: str = ''
    reader_source: str = ''
    tag_index: str = ''
    tag_anchor: str = ''
    title_trim: str = ''


class DirectCatalogue(SeriesPort):
    def __init__(self, identity, layout):
        super().__init__(identity, layout.title, layout.chapter, interval=.35)
        self.layout, self.meta = layout, layout.meta

    def title_for(self, url):
        if self.layout.reader_source == 'mangafreak':
            slug = re.sub(r'_\d+(?:[.,]\d+|[a-i]+)?$', '', self.chapter_key(url))
            return self.ROOT + '/Manga/' + slug
        return self.ROOT + self.layout.title_path + self.chapter_key(url) + self.layout.suffix

    def saved_chapter_matches(self, target, title):
        return super().saved_chapter_matches(target, title) or self.confirm_archive_membership(target, title)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        layout = self.layout
        if query:
            route = layout.search or layout.popular
        elif tag and layout.browse_tag:
            route = layout.browse_tag
        else:
            route = (layout.latest if sort == 'updated' else None) or layout.popular
        if route.one_page and page != 1:
            return [], False
        rows, more = self.card_rows(*self.document(http, route.url(self.ROOT, page, query, tag)), route.cards or layout.cards)
        if query and layout.search is None:
            rows = [row for row in rows if query.casefold() in row['title'].casefold()]
        for row in rows:
            row['title'] = self.clean_title(row['title'])
        return rows, bool(rows and more and not route.one_page)

    def clean_title(self, title):
        rule = self.layout.title_trim
        if rule == 'colorized':
            return title.removeprefix('Colorized').strip()
        if rule == 'hachiraw':
            return title.partition(' - ')[0]
        if rule == 'twi4':
            match = re.fullmatch(r'『(.+)』.+ \| ツイ４ \| 最前線', title)
            return match[1] if match else title
        return title.removesuffix(rule).strip() if rule else title

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row['title'] = self.clean_title(row['title'])
        if self.layout.title_trim == 'colorized':
            row['genres'] = unique(node_text(doc.select_one('aside p[class*="text-[11px]"]')).split('·'))
        return row

    def vocabulary(self, http):
        if not self.layout.tag_index:
            return []
        doc, final = self.document(http, self.ROOT + self.layout.tag_index)
        result = {}
        for anchor in doc.select(self.layout.tag_anchor):
            target = self.site_link(anchor.get('href'), final)
            tag = urlsplit(target).path.rstrip('/').rsplit('/', 1)[-1]
            name = node_text(anchor)
            if name and re.fullmatch(SEGMENT, tag):
                result[tag] = {'label': name, 'sourceId': tag, 'category': 'genre'}
        return list(result.values())

    def chapters(self, http, doc, url):
        return self.list_chapters(http, doc, url, self.layout.archive)

    def pages(self, http, url):
        if self.layout.reader_source == 'hentaifc':
            doc, final = self.title_document(http, self.title_for(url))
            return [picture(node.select_one('img'), final, ('data-src',)) for node in doc.select('.thumbs .wrap_item')
                    if (anchor := node.select_one('a[href]')) and
                    self.chapter_identity(self.site_link(anchor['href'], final)) == self.chapter_identity(url)]
        doc, final = self.page_document(http, url)
        source = self.layout.reader_source
        if source == 'manga18':
            for script in doc.select('script'):
                value = re.search(r'\bslides_p_path\s*=\s*\[([^\]]+)\]', script.string or '')
                if value:
                    try:
                        return [image_url(base64.b64decode(item.strip(' "\r\n\t'), validate=True).decode(), final)
                                for item in value[1].strip().rstrip(',').split(',')]
                    except (UnicodeError, binascii.Error):
                        raise SourceError('Читалка изменила формат списка страниц.') from None
            return []
        if source == 'mangakuro':
            chapter_id = next((match[1] for node in doc.select('script') if
                               (match := re.search(r'\bCHAPTER_ID\s*=\s*(\d{1,18});', node.string or ''))), '')
            if not chapter_id:
                return []
            response = self.json(http, f'{self.ROOT}/ajax/image/list/chap/{chapter_id}', final)
            if not isinstance(response, dict) or response.get('status') is not True or not isinstance(response.get('html'), str):
                return []
            doc = BeautifulSoup(response['html'], 'html.parser')
        pages = [picture(node, final, ('data-original', 'data-src')) for node in doc.select(self.layout.reader)]
        if source == 'hachiraw':
            return [page for page in pages if page and not urlsplit(page).path.endswith('/lazy.png')]
        if source == 'miuraw':
            path = '/wp-content/themes/manga-theme-MangaVerse/img-proxy.php'
            return [query_url(self.ROOT + path, url=page) if page and urlsplit(page).path != path else page for page in pages]
        return pages


def query(page_path, name):
    return Browse(page_path, ((name, '{query}'), ('page', '{page}')))


MWZ_NEXT = 'nav.pagination a[aria-label="Next page"]'
COMIC_NEXT = 'ul.pagination a[rel=next]:not([hidden])'
RAWDEX_CARDS = Cards('article.rdx-library-card', '.rdx-library-card__body h2 a',
                     cover='.rdx-library-card__cover img', next='a.next.page-numbers')

LAYOUTS = {
    'manhwaz': Layout(
        rf'/(?:manga|manhwa|series)/{SLUG}/?', rf'/(?:manga|manhwa|series|read|chapter)/{SLUG}(?:/{SEGMENT})+/?',
        Cards('article.popular-card', 'h3 a', next=MWZ_NEXT),
        Meta('section.profile-manga h1', 'div.series-cover-frame img', 'p.series-summary',
             genres='div.series-facts dt:-soup-contains("Genre") + dd a',
             author='div.series-facts dt:-soup-contains("Author") + dd',
             status='div.series-facts dt:-soup-contains("Status") + dd'),
        Archive('a.release-row', anchor='', title='strong', next=MWZ_NEXT),
        'div.reader-pages figure.reader-page-image img',
        Browse('/', one_page=True), query('/search', 's'),
        Browse('/', (('page', '{page}'),), Cards('article.latest-card', 'h3 a', next=MWZ_NEXT)),
        Browse('/genre/{tag}', (('page', '{page}'),)), tag_index='/genre', tag_anchor='.genre-directory a',
    ),
    'comichubfree': Layout(
        rf'/comic/{SLUG}/?', rf'/comic/{SLUG}/{SEGMENT}(?:/{SEGMENT})?/?',
        Cards('.movie-list-index > .cartoon-box:has(.detail)', 'a[href]', 'h3', next=COMIC_NEXT),
        Meta('div.movie-info h1, div.movie-info h2', 'div.series-info img', 'div#film-content',
             genres='div.series-info dt:-soup-contains("Genres:") + dd a',
             author='div.series-info dt:-soup-contains("Author:") + dd',
             status='div.series-info dt:-soup-contains("Status:") + dd'),
        Archive('div.episode-list > div > table > tbody > tr', date='td:last-of-type', date_pattern='%d-%b-%Y', next=COMIC_NEXT),
        'img.chapter_img', Browse('/popular-comic', (('page', '{page}'),)), query('/search-comic', 'key'),
        Browse('/new-comic', (('page', '{page}'),)), title_path='/comic/',
    ),
    'colorizedmangas': Layout(
        rf'/{SLUG}/?', rf'/{SLUG}(?:/{SEGMENT})+/?',
        Cards('div.lib-color-view a[href], div.lib-bw-view a[href]', '', 'h3', next=''),
        Meta('aside h1', 'aside img', 'aside p.border-t', author='aside dt:-soup-contains("Author") + dd'),
        Archive('div.space-y-4 section div.space-y-2 > a', anchor=''),
        'main img[src*=pages]', Browse('/', one_page=True), title_path='/', title_trim='colorized',
    ),
    'manga1000': Layout(
        rf'/(?:manga/)?{SLUG}/?', rf'/(?:manga/)?{SLUG}(?:/{SEGMENT})+/?',
        Cards('article.post.manga', '.entry-title a', cover='.featured-thumb img', next='nav.pagination a.next'),
        Meta('h1.entry-title', '.entry-content img', '.entry-content > p:not(:-soup-contains("Author:")):not(:-soup-contains("Category:"))',
             genres='.entry-content > p:-soup-contains("Category:") a', author='.entry-content > p:-soup-contains("Author:")'),
        Archive('.chaplist table tbody tr td a', anchor=''), '.entry-content img',
        Browse('/page/{page}/', first_path='/'), Browse('/search/page/{page}/', (('query', '{query}'),), first_path='/search'),
        browse_tag=Browse('/category/{tag}/page/{page}/', first_path='/category/{tag}/'),
        title_path='/', reader_source='hachiraw', title_trim='hachiraw',
    ),
    'mangakuro': Layout(
        MANGA, CHAPTER, Cards('div.story_item', 'div.mg_name a', next='a[title="Last Page"]'),
        Meta('div.detail_name > h1', '.detail_avatar img', '.detail_reviewContent', genres='div.detail_listInfo a.genres-el',
             author='div:has(.lnr-user) + .info_value a[href*="/authors/"]', status='div:has(.lnr-leaf) + .info_value'),
        Archive('div.chapter_box .item', anchor='a.chapter_num'), 'div.image_story img',
        Browse('/all-manga/{page}', (('sort', 'views'),)), Browse('/search/{page}', (('keyword', '{query}'),)),
        Browse('/all-manga/{page}', (('sort', 'latest-updated'),)), reader_source='mangakuro',
    ),
    'miuraw': Layout(
        MANGA, CHAPTER, Cards('.manga-card', 'a.manga-card-thumb', '.manga-card-title', '.manga-card-thumb img',
                             '.pagination a:has(i.fa-chevron-right)'),
        Meta('.md-title', '.md-cover img', '.md-desc-content', genres='.md-tag',
             author='.md-meta-row:has(.fa-user) .md-meta-val', status='.md-meta-row:has(.fa-rss) .md-meta-val'),
        Archive('.md-chapter-row', anchor='.md-chapter-name a'), '.reader-page img',
        Browse('/manga/page/{page}/', (('orderby', 'views'),)),
        Browse('/page/{page}/', (('s', '{query}'), ('post_type', 'manga')), first_path='/'),
        Browse('/manga/page/{page}/', (('orderby', 'date'),)), reader_source='miuraw', title_trim=' (Raw – Free)',
    ),
    'rawdex': Layout(
        MANGA, CHAPTER, RAWDEX_CARDS,
        Meta('.rdx-manga-heading h1', 'img.rdx-manga-cover', '.rdx-manga-summary', '.rdx-manga-alternative',
             '.rdx-manga-tags a', author='dl.rdx-manga-meta dt:-soup-contains("Author") + dd', status='.rdx-manga-status'),
        Archive('.rdx-chapter-list > a.rdx-chapter-row', anchor='', title='.rdx-chapter-row__label'),
        '.rdx-reader-page img',
        Browse('/manga/page/{page}/', (('m_orderby', 'views'),)), Browse('/', (('s', '{query}'), ('spage', '{page}'))),
        Browse('/manga/page/{page}/', (('m_orderby', 'latest'),)),
    ),
    'mangafreak': Layout(
        rf'/Manga/{SLUG}/?', rf'/Read1_{SLUG}/?', Cards('div.ranking_item', 'a[href]', next='a.next_p'),
        Meta('div.manga_series_data h5', 'div.manga_series_image img', 'div.manga_series_description p',
             genres='div.series_sub_genre_list a', author='div.manga_series_data > div:nth-of-type(4)',
             status='div.manga_series_data > div:nth-of-type(3)'),
        Archive('div.manga_series_list tr:has(a)', title='td:first-of-type', date='td:nth-of-type(2)', date_pattern='%Y/%m/%d'),
        'img#gohere[src]', Browse('/Genre/All/{page}'),
        Browse('/Find/{query}', cards=Cards('div.manga_search_item, div.mangaka_search_item', 'h3 a, h5 a'), one_page=True),
        Browse('/Latest_Releases/{page}', cards=Cards('div.latest_releases_item', 'a[href]', next='a.next_p'),
               first_path='/Latest_Releases'),
        title_path='/Manga/',
    ),
    'twi4': Layout(
        rf'/comics/twi4/{SLUG}/?', rf'/comics/twi4/{SLUG}/{SEGMENT}\.html/?',
        Cards('#lineup_recent > div > section, #lineup > div > section:not(.zadankai):not([id])',
              'div.hgroup > h3 > a', cover='div.figgroup > figure > a > img', next=''),
        Meta('title', '#introduction > header > div > h2 > img', '#introduction > div > div > p',
             author='#introduction > div > section > header > div > h3 span'),
        Archive('#backnumbers > div > ul > li'), 'article.comic > div > div > p > img',
        Browse('', one_page=True), title_path='/', title_trim='twi4',
    ),
    'yaoihot': Layout(
        MANGA, CHAPTER, Cards('.manga-grid .manga-card', '.manga-card-link', '.manga-card-title',
                             '.manga-cover-img', '.next.page-numbers'),
        Meta('.manga-title', '.manga-cover-img', '.summary-content', genres='.genre-tag', author='.author-line'),
        Archive('.chapters-list a.chapter-item, .chapters-list .chapter-item > a', anchor='', title='.chapter-title'),
        '.reader-page img', Browse('/manga/page/{page}/', (('orderby', 'views'),), first_path='/manga/'),
        Browse('/page/{page}/', (('s', '{query}'), ('post_type', 'manga')), first_path='/'),
        Browse('/manga/page/{page}/', (('orderby', 'modified'),), first_path='/manga/'),
    ),
    'hentaifc': Layout(
        rf'/e/{SLUG}/?', rf'/e/{SLUG}/c\d+/?',
        Cards('#book_list .wrap_item', 'h3.title a', cover='.wrap_img img', next='a.next.page-numbers'),
        Meta('h1.heading', '.thumbs .wrap_item img', tags='.genres a[href*="/tag/"]', author='.d-cell.value.authors a.author'),
        Archive('.thumbs .wrap_item a[href]', anchor=''), '', Browse('/page/{page}', first_path='/'),
        Browse('/', (('search', '{query}'), ('search_by', 'title')), one_page=True), title_path='/e/', reader_source='hentaifc',
    ),
    'mangademon': Layout(
        rf'/manga/{SLUG}/?', rf'/(?:manga|chapter|read)/{SLUG}(?:/{SEGMENT})+/?',
        Cards('div#advanced-content > div.advanced-element', 'a[href]', 'h1',
              next='div.pagination > ul > a:has(li:-soup-contains("Next"))'),
        Meta('div#manga-info-container h1.big-fat-titles', 'div#manga-page img',
             'div#manga-info-rightColumn > div > div.white-font', genres='div.genres-list > li',
             author='div#manga-info-stats > div:has(> li:first-of-type:-soup-contains("Author")) > li:nth-of-type(2)',
             status='div#manga-info-stats > div:has(> li:first-of-type:-soup-contains("Status")) > li:nth-of-type(2)'),
        Archive('div#chapters-list a.chplinks', anchor='', date='span', date_pattern='%Y-%m-%d'),
        'div > img.imgholder',
        Browse('/advanced.php', (('list', '{page}'), ('status', 'all'), ('orderby', 'VIEWS DESC'))),
        Browse('/search.php', (('manga', '{query}'),), Cards('body > a[href]', '', 'div.seach-right > div'), True),
        Browse('/lastupdates.php', (('list', '{page}'),), Cards(
            'div#updates-container > div.updates-element:not(:has(.toffee-badge))', 'div.updates-element-info a',
            cover='div.thumb img', next='div.pagination > ul > a:has(li:-soup-contains("Next"))')),
        Browse('/advanced.php', (('list', '{page}'), ('genre[]', '{tag}'))),
    ),
}

MANGA18 = Layout(
    rf'/manhwa/{SLUG}/?', rf'/manhwa/{SLUG}(?:/{SEGMENT})+/?',
    Cards('div.story_item', 'div.mg_info > div.mg_name a', next='.pagination > li:last-child:not(.active)'),
    Meta('div.detail_name > h1', 'div.detail_avatar > img', 'div.detail_reviewContent',
         'div.item:-soup-contains("Other name") div.info_value',
         'div.info_value > a[href*="/manga-list/"]', author='div.info_label:-soup-contains("author") + div.info_value',
         status='div.item:-soup-contains("Status") div.info_value'),
    Archive('div.chapter_box .item', date='p', date_pattern='%d-%m-%Y'),
    '', Browse('/list-manga/{page}', (('order_by', 'views'),)),
    Browse('/list-manga/{page}', (('search', '{query}'),)), Browse('/list-manga/{page}'),
    Browse('/manga-list/{tag}/{page}'), title_path='/manhwa/', reader_source='manga18',
    tag_index='/list-manga/1', tag_anchor='div.grid_cate li > a',
)

LAYOUTS.update(eighteenporncomic=MANGA18, manga18club=MANGA18)


class Snafu(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/{SLUG}/?', rf'/{SLUG}/(?!archive/?$){SEGMENT}/?',
            Cards('a[href]:has(img)', '', 'img', title_attr='alt', next=''), Meta('h1', 'main img'),
            Archive(''), 'img[src*="/comics/"]', Browse('/all-comics', one_page=True), title_path='/',
        ))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        doc, final = self.document(http, self.ROOT + '/all-comics')
        rows = {}
        for link in doc.select('a[href]:has(img)'):
            target = self.site_link(link['href'], final)
            label, sep, author = node_text(link).partition(' by ')
            image = link.select_one('img')
            title = image.get('alt') or label
            if self.is_title(target) and sep and title and (query in title.casefold() or query in author.casefold()):
                rows[self.title_key(target)] = self.record(target, title, picture(image, final), authors=[author])
        return list(rows.values()), False

    def details(self, http, url):
        rows, _ = self.catalogue(http)
        key = self.title_key(self.canonical(url))
        for row in rows:
            if self.title_key(self.site_link(row['url'])) == key:
                return row
        raise SourceError('Источник не предоставил тайтл.')

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_title(url):
            return super().inspect(value, http)
        row = self.details(http, url)
        target = url.rstrip('/') + '/archive'
        doc, final = self.document(http, target)
        slug = self.title_key(url)
        heading = next((element for element in doc.select('h1,h2,h3,h4') if node_text(element).casefold() == 'archive'), None)
        anchors = []
        if heading:
            for element in heading.next_siblings:
                if getattr(element, 'name', None) in {'h1', 'h2', 'h3', 'h4'}:
                    break
                if getattr(element, 'name', None):
                    anchors.extend(element.select('a[href]'))
        else:
            anchors = doc.select('a[href]')
        chapters = {}
        for node in anchors or doc.select('select option[value]'):
            value = node.get('href') or node.get('value') or ''
            target = self.site_link(value, url.rstrip('/') + '/')
            if self.is_chapter(target) and self.chapter_key(target) == slug:
                chapters[target] = self.chapter(target, node_text(node))
        return self.reader_result(row, url, self.order(chapters), [])


class JumpRookie(DirectCatalogue):
    def __init__(self, identity):
        cards = Cards('section.series-contents', 'a[href]', '.series-title', '.cover-image', '.button-next')
        super().__init__(identity, Layout(
            rf'/series/{SLUG}/?', rf'/series/{SLUG}/{SEGMENT}/?',
            cards, Meta('.series-title', '.cover-image', '.series-description', genres='.series-category', author='.user-name'),
            Archive('#episode-list > li', anchor='a.episode-content', title='.episode-title'),
            '.js-page-image', Browse('/api/media/series_list'),
            Browse('/search', (('query', '{query}'),), Cards('#search-series section.series-contents', 'a[href]',
                                                           '.series-title', '.cover-image', ''), True),
            Browse('/categories/general/recent', (('page', '{page}'),)), title_path='/series/',
        ))
        self.cursors = OrderedDict()
        self.cursor_lock = Lock()

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query or sort == 'updated' and not tag:
            return super().catalogue(http, page, query=query, sort=sort, tag=tag)
        if tag and not re.fullmatch(SEGMENT, tag):
            raise SourceError('Некорректная категория Jump Rookie.')
        args = {'type': 'popular'}
        if tag:
            args['category'] = tag
        if page > 1:
            with self.cursor_lock:
                cursor = self.cursors.get((tag, page))
            if not cursor:
                return [], False
            args['key'] = cursor
        url = query_url(self.ROOT + '/api/media/series_list', **args)
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, headers = http.document(url, action='native-series-html-api')
        if final != url:
            raise SourceError('Каталог перенаправил запрос на другой маршрут.')
        link = next((urljoin(final, value) for name, value in headers.items() if name.casefold() == 'tky-link-rel-next'), '')
        parts = urlsplit(link)
        key = param(link, 'key') if parts.netloc == self.hostname and parts.path == '/api/media/series_list' else ''
        if key and len(key) <= 450:
            with self.cursor_lock:
                self.cursors[(tag, page + 1)] = key
                self.cursors.move_to_end((tag, page + 1))
                if len(self.cursors) > 512:
                    self.cursors.popitem(last=False)
        rows, _ = self.card_rows(BeautifulSoup(raw, 'html.parser'), final, self.layout.cards)
        return rows, bool(key and len(key) <= 450 and rows)


class JoomlaGallery(DirectCatalogue):
    def __init__(self, identity, package):
        self.xiu = package == 'xiutaku'
        cards = Cards('.blog > div', '.item-content .item-link', next='.pagination-next:not([disabled])') if self.xiu else Cards(
            'div.blog > div.items-row', 'a.item-link', 'h2', next='nav > a.pagination-next:not([disabled])')
        super().__init__(identity, Layout(
            rf'/{SLUG}/?', rf'/{SLUG}/?', cards,
            Meta('div.article-header', 'div.article-fulltext img', '.article-info:not(:has(small))',
                 tags='div.article-tags .tags > .tag, div.article-tags a.tag > span'),
            Archive(''), 'div.article-fulltext img[src]', Browse('/hot'), title_path='/',
        ))

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(re.fullmatch(r'[1-9]\d{0,3}', param(url, 'page')))

    def title_for(self, url):
        return self.ROOT + '/' + self.chapter_key(url)

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_chapter(url):
            return super().inspect(value, http)
        pages = self.pages(http, url)
        if not pages or not all(pages):
            raise SourceError('Источник не предоставил страницы галереи.')
        number = int(param(url, 'page'))
        row = self.details(http, self.title_for(url))
        return self.reader_result(row, url, [self.chapter(url, f'Page {number}', number)], pages)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        path = '/' if query or sort == 'updated' else '/hot'
        args = {'start': (page - 1) * 20, **({'search': query} if query else {})}
        return self.card_rows(*self.document(http, query_url(self.ROOT + path, **args)), self.layout.cards)

    def chapter_identity(self, url):
        return self.chapter_key(url), param(url, 'page') or '1'

    def chapters(self, http, doc, url):
        rows = []
        if self.xiu:
            page = node_text(doc.select_one('.pagination-list > span:last-child > a'))
            total = min(int(page), 1500) if re.fullmatch(r'\d{1,4}', page) else 1
            rows = [(n, query_url(url, page=n)) for n in range(1, total + 1)]
        else:
            for anchor in doc.select('nav.pagination:first-of-type a[href]'):
                target = self.site_link(anchor['href'], url)
                text = node_text(anchor)
                if self.title_key(target) == self.title_key(url) and re.fullmatch(r'\d{1,4}', text):
                    rows.append((int(text), query_url(target, page=text)))
        return [self.chapter(target, f'Page {n}', n) for n, target in sorted(set(rows or [(1, query_url(url, page=1))]))], False


def public_api(host, path, query_string):
    if host == 'rookie.shonenjump.com' and path == '/api/media/series_list':
        query = parse_qs(query_string)
        return (set(query) <= {'type', 'key', 'category'} and query.get('type') == ['popular']
                and len(query.get('key', [])) <= 1 and len(query.get('key', [''])[0]) <= 450
                and len(query.get('category', [])) <= 1 and all(re.fullmatch(SEGMENT, tag) for tag in query.get('category', [])))
    return host == 'mangakuro.net' and not query_string and bool(re.fullmatch(r'/ajax/image/list/chap/\d{1,18}', path))


def sources():
    from manga_third_batch_profiles import HTML

    aux = {'snafucomic': Snafu, 'jumprookie': JumpRookie}
    return tuple(aux[package](identity) if package in aux else
                 JoomlaGallery(identity, package) if package in {'kiutaku', 'xiutaku'} else
                 DirectCatalogue(identity, LAYOUTS[package]) for package, identity in HTML)
