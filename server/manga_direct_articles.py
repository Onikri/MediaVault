"""Direct webtoon singles, image galleries and comic archives."""

import json
import re
from urllib.parse import urlsplit

from manga_direct_catalogues import Browse, DirectCatalogue, Layout, SLUG, query
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Archive, Cards, MAX_PAGES, Meta, picture
from manga_webcomic_profiles import single
from manga_webcomics import Archive as WebArchive, Reader, Webcomic, param, query_url
from source_parser import SourceError


ARTICLE = rf'/{SLUG}/?'
WP_PAGE = Browse('/page/{page}/', (('s', '{query}'),), first_path='/')
WP_NEXT = 'a.nextp, .pagenav a.next, a.page-numbers.next, a[rel=next]'
ARTICLE_IMAGES = ('data-pswp-src', 'data-pagespeed-lazy-src', 'data-src', 'data-lazy-src')


class Article(DirectCatalogue):
    def __init__(self, identity, package):
        super().__init__(identity, ARTICLES[package])
        self.package = package

    def is_chapter(self, url):
        return super().is_chapter(url) and param(url, 'mv_article') == '1'

    def title_for(self, url):
        return query_url(url.split('?', 1)[0])

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        return query_url(self.title_for(url), mv_article=1) if self.is_title(url) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if self.package == 'photos18' and tag and not query:
            self.catalogue_params(page, query, tag)
            url = query_url(self.ROOT + '/', c=tag, page=page)
            return self.card_rows(*self.document(http, url), self.layout.cards)
        rows, more = super().catalogue(http, page, query=query, sort=sort, tag=tag)
        if self.package == 'ahottie' and query and not rows and page == 1:
            doc, final = self.document(http, self.layout.search.url(self.ROOT, page, query, tag))
            canonical = doc.select_one('link[rel=canonical][href]')
            target = self.site_link(canonical['href'], final) if canonical else ''
            if target and self.is_title(target) and doc.select_one('div.pl-3 > a'):
                return [self.metadata(doc, target, self.meta)], False
        return rows, more

    def metadata(self, doc, url, spec):
        source = self.package
        if source == 'ohjoysextoy':
            title = doc.select_one('meta[property="og:title"][content]')
            if title is None:
                raise SourceError('Источник не предоставил название комикса.')
            title, _, author = title['content'].partition(' by ')
            row = self.record(url, title, authors=[author],
                              genres=[node.get('content', '') for node in doc.select('meta[property="article:section"]')[1:]])
        else:
            row = super().metadata(doc, url, spec)
        cover = doc.select_one('button.js-button-favorite[data-cover], meta[property="og:image"][content]')
        if not row['cover'] and cover:
            row['cover'] = image_url(cover.get('data-cover') or cover.get('content'), url)
        if not row['cover'] and source == 'xyzcomics':
            page = doc.select_one('.pswp-gallery .pswp-gallery__item a[href]')
            row['cover'] = image_url(page.get('href'), url) if page else ''
        desc = doc.select_one('meta[property="og:description"][content]')
        if not row['description'] and desc:
            row['description'] = desc['content'].strip()
        row['status'] = 'completed'
        return row

    def inspect(self, value, http):
        url = self.canonical(value)
        title = self.title_for(url)
        if not self.is_title(title):
            raise SourceError('Некорректная ссылка на комикс.')
        doc, final = self.title_document(http, title)
        row = self.metadata(doc, title, self.meta)
        date = doc.select_one('.post-date, time[datetime], .image-info-time')
        date_value = (date.get('datetime') or node_text(date).lstrip('：: ').strip()) if date else ''
        date_value = release_date(date_value[:10] if re.match(r'\d{4}-\d{2}-\d{2}', date_value) else date_value,
                                  '%B %d, %Y' if self.package == 'ohjoysextoy' else '%Y-%m-%d')
        chapter_url = query_url(title, mv_article=1)
        chapter = self.chapter(chapter_url, self.NAME if self.package == 'ohjoysextoy' else 'Глава', 1, date_value)
        pages = self.article_pages(http, doc, final) if self.is_chapter(url) else []
        if self.is_chapter(url) and (not 1 <= len(pages) <= MAX_PAGES or not all(pages)):
            raise SourceError('Источник не предоставил полный список страниц.')
        return self.reader_result(row, chapter_url if pages else title, [chapter], pages)

    def article_pages(self, http, doc, final):
        result = []
        source = self.package
        seen = set()
        while final not in seen:
            seen.add(final)
            nodes = doc.select(self.layout.reader)
            if source == 'xlecx':
                nodes = doc.select('#content-2 > .imagegall23 > img') or doc.select('.page__text a:has(img)') or nodes
                if not nodes:
                    script = doc.select_one('script[type="application/ld+json"]')
                    try:
                        first = json.loads(script.string)['@graph'][0]
                        return [image_url(item, final) for item in first.get('image', [])]
                    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                        return []
            if source == 'porncomix' and (gallery := doc.select('.pswp-gallery__item[data-pswp-src]')):
                nodes = gallery
            result.extend(image_url(node.get('href'), final) if node.name == 'a' else picture(node, final, ARTICLE_IMAGES)
                          for node in nodes)
            if source == 'ilikecomix':
                return list(dict.fromkeys(value for value in result if '/comic/' in urlsplit(value).path))
            if source not in {'ahottie', 'foamgirl'}:
                return result
            selector = 'a[rel=next]' if source == 'ahottie' else '.page-numbers[title="Next page"]'
            anchor = doc.select_one(selector)
            target = self.site_link(anchor.get('href'), final) if anchor else ''
            if source == 'foamgirl' and not re.search(r'\d+_\d+', urlsplit(target).path):
                target = ''
            if not target:
                return result
            if len(result) > MAX_PAGES or len(seen) >= 80:
                raise SourceError('Источник вернул слишком много страниц галереи.')
            doc, final = self.document(http, target)
        raise SourceError('Источник вернул циклические ссылки галереи.')


ARTICLES = {
    'xyzcomics': Layout(
        ARTICLE, ARTICLE, Cards('article.post', 'figure.post-image a', 'h2.post-title a', 'figure.post-image img.wp-post-image', WP_NEXT),
        Meta('h1.post-title a, h1.post-title, title', '.pswp-gallery .pswp-gallery__item a[href]', tags='a.post-tag-button'),
        Archive(''), '.pswp-gallery .pswp-gallery__item a[href]',
        Browse('/allsexkomix/page/{page}/', first_path='/allsexkomix/'), WP_PAGE,
        browse_tag=Browse('/tag/{tag}/page/{page}/', first_path='/tag/{tag}/'), title_path='/',
    ),
    'porncomix': Layout(
        ARTICLE, ARTICLE, Cards('#loops-wrapper article', 'h2.post-title a', next='a.nextp', image_attrs=ARTICLE_IMAGES),
        Meta('h1.post-title, h1.entry-title', 'div.post-inner img, div.entry-content img, article img',
             'div.entry-content p, div.post-content p', tags='a[rel=tag], .post-tags a, .tags-links a'),
        Archive(''), 'div.entry-content img',
        Browse('/allmultking/page/{page}/', first_path='/allmultking/'), WP_PAGE, title_path='/',
    ),
    'ilikecomix': Layout(
        ARTICLE, ARTICLE, Cards('article', 'h2.post-title a', cover='figure.post-image img', next='a.nextp'),
        Meta('h1.post-title', 'figure.post-image img', tags='a[rel=tag]'),
        Archive(''), 'figure[data-pswp-src], .entry-content img',
        Browse('/king-porn-comics/page/{page}/', first_path='/king-porn-comics/'), WP_PAGE, title_path='/',
    ),
    'ohjoysextoy': Layout(
        ARTICLE, ARTICLE, Cards('.comicthumbwrap', '.comicarchiveframe > a', '.comicthumbdate', '.comicarchiveframe img', '.pagenav-left a'),
        Meta('h1', 'div.comicpane img'), Archive(''), 'div.comicpane img',
        Browse('/category/comic/page/{page}/'),
        Browse('/', (('s', '{query}'),), Cards('h2.post-title', 'a[href]', next=''), True),
        Browse('/', cards=Cards('#MattsRecentComicsBar > ul > div', '.comicarchiveframe > a',
                               '.comicthumbdate', '.comicarchiveframe img', ''), one_page=True),
        title_path='/',
    ),
    'hentaipill': Layout(
        rf'/gallery/{SLUG}/?', rf'/gallery/{SLUG}/?',
        Cards('div.galleries-list > div.gallery-item', 'a[href*="/gallery/"]', 'a[href*="/gallery/"] span',
              'img.lazy', 'ul.pagination a[rel=next]'),
        Meta('div.reading-page-header h1', 'button.js-button-favorite',
             tags='.table-row:has(.table-label:-soup-contains("Tags")) .table-value a',
             author='.table-row:has(.table-label:-soup-contains("Artists")) .table-value a'),
        Archive(''), 'div.reading-pages-content img.lazy',
        Browse('/popular/{page}', first_path='/popular'), query('/search', 'q'),
        Browse('/language/english/{page}', first_path='/language/english'),
        Browse('/genre/{tag}/{page}', first_path='/genre/{tag}'), title_path='/gallery/',
    ),
    'foamgirl': Layout(
        rf'/{SLUG}(?:/{SEGMENT})?/?', rf'/{SLUG}(?:/{SEGMENT})?/?',
        Cards('.update_area .i_list', 'a.meta-title', next='a.next'), Meta('h1, title', '.imageclick-imgbox img'),
        Archive(''), '.imageclick-imgbox',
        Browse('/page/{page}'), Browse('/page/{page}', (('post_type', 'post'), ('s', '{query}'))), title_path='/',
    ),
    'ahottie': Layout(
        rf'/{SLUG}(?:/{SEGMENT})?/?', rf'/{SLUG}(?:/{SEGMENT})?/?',
        Cards('#main > div > div', 'a[href]', 'h2', '.relative img', 'a[rel=next]'),
        Meta('h1', '#main img.block', tags='div.pl-3 > a'), Archive(''), '#main img.block',
        Browse('/', (('page', '{page}'),)), query('/search', 'kw'), title_path='/',
    ),
    'xlecx': Layout(
        rf'/(\d+-{SEGMENT}\.html)', rf'/(\d+-{SEGMENT}\.html)',
        Cards('#dle-content > a.thumb', '', 'img', next='#pagination > .pagination__pages > a:-soup-contains("Next")',
              title_attr='alt'),
        Meta('h1', '', tags='.page__subinfo-item > div:not([class]):-soup-contains("Tags:") ~ a',
             author='.page__subinfo-item > div:not([class]):-soup-contains("Artist:") ~ a'),
        Archive(''), '#content-1 > .imagegall23 > img',
        Browse('/f/sort=news_read/order=desc/page/{page}/', first_path='/f/sort=news_read/order=desc/'),
        Browse('/index.php', (('do', 'search'), ('subaction', 'search'), ('search_start', '{page}'),
                              ('full_search', '0'), ('story', '{query}'))),
        Browse('/f/sort=date/order=desc/page/{page}/', first_path='/f/sort=date/order=desc/'),
        title_path='/',
    ),
    'photos18': Layout(
        rf'/(?:zh-hans/)?{SLUG}/?', rf'/(?:zh-hans/)?{SLUG}/?',
        Cards('#videos > *', '.card-body a', next='.next:not(.disabled)'),
        Meta('h1, title', '#content img', tags='a[href*="/category/"]'), Archive(''), '#content img',
        Browse('/sort/views', (('page', '{page}'),)), query('/', 'q'), Browse('/', (('page', '{page}'),)),
        title_path='/', tag_index='/', tag_anchor='#w2 a[href]',
    ),
}


def beginning_archive(source, http, work, url):
    doc, final = source.document(http, url)
    rows = {}
    for node in doc.select('a[href]'):
        target = source.site_link(node['href'], final)
        path = urlsplit(target).path
        if source.is_chapter(target) and (match := re.search(r'(?:chapter|ch)-(\d+)/?$', path)):
            number = int(match[1])
            if number not in rows or re.search(r'/ch-\d+/?$', path):
                rows[number] = (target, f'Chapter {number}', number, '')
    return [rows[n] for n in sorted(rows)], False


def oglaf_pages(source, http, url):
    pages, seen = [], set()
    story = urlsplit(url).path.strip('/').split('/')[0]
    while url and url not in seen and len(pages) < MAX_PAGES:
        seen.add(url)
        doc, final = source.document(http, url)
        page = picture(doc.select_one('img#strip'), final)
        if not page:
            break
        pages.append(page)
        node = doc.select_one('a[rel=next][href]')
        url = source.site_link(node['href'], final) if node else ''
        if not re.fullmatch(rf'/{re.escape(story)}/\d*/', urlsplit(url).path):
            break
    return '', pages, ''


def sabrina_archive(source, http, work, url):
    doc, final = source.document(http, url)
    rows = {}
    entries = doc.select('center table tr')
    for offset in range(0, len(entries), 2):
        headings = [node_text(node) for node in entries[offset].select('td')] if offset + 1 < len(entries) else []
        row = entries[offset + 1] if headings else entries[offset]
        for idx, cell in enumerate(row.select('td')):
            year = headings[idx] if idx < len(headings) and re.match(r'\d', headings[idx]) else ''
            for anchor in cell.select('a[href]'):
                url = source.site_link(anchor['href'], final)
                if source.is_chapter(url) and (name := node_text(anchor)):
                    rows[url] = (url, ' '.join(filter(None, (year, name))), None, '')
    return list(rows.values())[::-1], False


def sabrina_pages(source, http, url):
    doc, final = source.document(http, url)
    pages = []
    for img in doc.select('center img[src*="strips/"], center img[src*="pages/"]'):
        target = img.parent.get('href') if img.parent and img.parent.name == 'a' else img['src']
        pages.append(image_url(target, final))
    return '', pages, ''


def clown_archive(source, http, work, url):
    doc, final = source.document(http, url)
    count = re.search(r'(\d+)$', node_text(doc.select_one('#paginav li.paginav-pages')))
    maximum = int(count[1]) if count else 1
    rows = {}
    for page in range(1, min(maximum, 100) + 1):
        if page > 1:
            doc, final = source.document(http, source.ROOT + f'/comic/page/{page}/')
        for node in doc.select('.comic:has(.post-title a[href])'):
            anchor = node.select_one('.post-title a[href]')
            target = source.site_link(anchor['href'], final)
            if target and source.is_chapter(target):
                rows[target] = (target, node_text(anchor), None, release_date(node_text(node.select_one('.post-date')), '%B %d, %Y'))
    return list(rows.values())[::-1], maximum > 100


def beginning_pages(source, http, url):
    doc, final = source.document(http, url)
    result = []
    for img in doc.select('.entry-content img'):
        value = picture(img, final, ('data-src', 'data-lazy-src'))
        if not value and img.get('srcset'):
            value = image_url(img['srcset'].split(',', 1)[0].split()[0], final)
        parts = urlsplit(value)
        if parts.hostname in {'blogger.googleusercontent.com', 'bp.blogspot.com', 'img.thebeginningaftertheendmanga.com'} and 'cropped-' not in parts.path:
            result.append(value)
    return '', list(dict.fromkeys(result)), ''


def roved_books(source, http):
    doc, final = source.document(http, source.ROOT + '/')
    for index, anchor in enumerate(doc.select('#menu-menu > li > a[href]'), 1):
        url = source.site_link(anchor['href'], final)
        if re.fullmatch(r'/archive(?:-book-\d+)?/?', urlsplit(url).path):
            archive, final_url = source.document(http, url)
            for chapter in archive.select('.comic-archive-chapter-wrap'):
                first = chapter.select_one('.comic-archive-title > a[href]')
                target = source.site_link(first['href'], final_url) if first else ''
                name = node_text(chapter.select_one('.comic-archive-chapter'))
                if source.is_chapter(target) and name:
                    dates = chapter.select('.comic-archive-date')
                    date = release_date(node_text(dates[-1]), '%b %d, %Y') if dates else ''
                    yield index, target, final_url, name, date, chapter


def roved_archive(source, http, work, url):
    rows = []
    for book, target, _, name, date, _ in roved_books(source, http):
        rows.append((target, f'Book {book}: {name}', len(rows) + 1, date))
    return rows, False


def roved_pages(source, http, url):
    for _, target, final, name, _, chapter in roved_books(source, http):
        if source.title_identity(target) != source.title_identity(url):
            continue
        pages = []
        for anchor in chapter.select('.comic-archive-list-wrap .comic-archive-title > a[href]'):
            page = source.site_link(anchor['href'], final)
            if not source.is_chapter(page) or len(pages) >= MAX_PAGES:
                raise SourceError('Архив содержит некорректный список страниц.')
            doc, page_url = source.document(http, page)
            pages.append(picture(doc.select_one('#comic img'), page_url))
        return name, pages, ''
    return '', [], ''


SINGLES = {
    'oglaf': single('/archive/', 'Oglaf', 'https://i.ibb.co/tzY0VQ9/oglaf.png', author='Trudy Cooper & Doug Bayne',
                    archive=WebArchive('a:has(img[width="400"])'), pages=oglaf_pages,
                    chapter_path=rf'/{SEGMENT}(?:/\d+)?/?'),
    'mahouirexnohentaikarte': single(
        '/', 'Mahoui Rex no Hentai Karte', '/storage/manga/cover.webp', enrich=True,
        title_selector='h1', cover_selector='picture img', description_selector='.synopsis',
        author_selector='dl dt:-soup-contains("Author") + dd', genres_selector='h1 ~ ul li',
        archive=WebArchive('#chapters ol > li > a', title='span span'), images='img[src*="/storage/manga/chapter-"]',
        chapter_path=rf'/(?:manga/{SEGMENT}/)?(?:chapter[-/]){SEGMENT}/?',
        legacy_title={'/manga/mahoui-rex-no-hentai-karte': '/'},
    ),
    'thebeginningaftertheendmangaonline': single(
        '/', 'The Beginning After The End', enrich=True, chapters=beginning_archive,
        pages=beginning_pages,
        chapter_path=rf'/(?:(?:manga/)?beginning-after-the-end-{SEGMENT}(?:/ch-\d+)?|ch-\d+)/?',
    ),
    'sabrinaonline': single('/archive.html', 'Sabrina Online', author='Eric W. Schwartz', chapters=sabrina_archive,
                           pages=sabrina_pages, chapter_path=rf'/(?!archive\.html$)(?:{SEGMENT}/)*{SEGMENT}\.html'),
    'clowncorps': single('/comic', 'Clown Corps', '/wp-content/uploads/2022/11/clowns41.jpg', author='Joe Chouinard',
                         chapters=clown_archive, reader=Reader('#comic img', notes='#comic img', notes_attr='title'),
                         chapter_path=rf'/comic/{SEGMENT}/?'),
    'irovedout': single('/', 'I Roved Out in Search of Truth and Love', 'https://i.ibb.co/2g7Htwq/irovedout.png',
                        author='Alexis Flower', chapters=roved_archive, pages=roved_pages,
                        chapter_path=rf'/(?:comic/)?{SEGMENT}/?'),
}


def sources():
    from manga_third_batch_profiles import ARTICLES as article_profiles, SINGLES as single_profiles

    return (*(Article(identity, package) for package, identity in article_profiles),
            *(Webcomic(identity, SINGLES[package]) for package, identity in single_profiles))
