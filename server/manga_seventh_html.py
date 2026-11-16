"""Catalogue and reader ports for sites serving complete HTML."""

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, node_text, release_date
from manga_series_port import Cards, MAX_CHAPTERS, MAX_PAGES, Meta, SeriesPort, picture
from manga_webcomics import param, query_url
from source_parser import SourceError

HOT = 'https://hotcomics.io'
INCASE = 'https://incase.buttsmithy.com'
ALFIE = 'https://buttsmithy.com'
WP_PAGE = rf'/(?:{SEGMENT}/){{0,4}}({SEGMENT})/?'
HOT_PATH = rf'/en/({SEGMENT}(?:/{SEGMENT}){{0,5}})/?'
HOT_TOP = {'new', 'weekly', 'genres', 'search', 'login', 'sign-in', 'sign-up', 'account', 'profile'}
HOT_GENRES = ('Sports', 'Historical', 'Drama', 'BL', 'Thriller', 'School_life', 'Comedy',
              'GL', 'Action', 'Sci-fi', 'Horror', 'Fantasy', 'Romance')


class HotComics(SeriesPort):
    cards = Cards('li[itemtype*="ComicSeries"]:not(.no-comic) > a', '', 'div.main-text > h4.title',
                  'div.visual img', next='div.pagination a.vnext:not(.disabled)', image_attrs=('data-src',))
    meta = Meta('h2.episode-title', 'meta[property="og:image"]', 'div.episode-contents header',
                status='p.type_box span.date')

    def __init__(self):
        super().__init__(('6335003343669033128', 'HotComics', 'en', HOT, True),
                         HOT_PATH, HOT_PATH, interval=.35)

    def is_title(self, url):
        key = self.title_key(url)
        return bool(key and key.split('/', 1)[0] not in HOT_TOP and param(url, 'mv_hot_read') != '1')

    def is_chapter(self, url):
        key = self.chapter_key(url)
        return bool(key and key.split('/', 1)[0] not in HOT_TOP and (param(url, 'mv_hot_read') == '1'
                    or re.search(r'(?:^|/)(?:view|viewer|read|chapter|episode)(?:[-_/]|$)', key, re.I)))

    def title_for(self, url):
        key = param(url, 'mv_hot_parent')
        target = HOT + '/en/' + key
        return target if self.is_title(target) else ''

    def document(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, action='hotcomics-doc')
        if urlsplit(final).netloc != 'hotcomics.io':
            raise SourceError('HotComics перенаправил запрос на другой сайт.')
        return BeautifulSoup(raw, 'html.parser'), final

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            if page > 1:
                return [], False
            url = query_url(HOT + '/en/search', keyword=query)
        else:
            route = '/en/new' if sort == 'updated' else '/en'
            if tag in HOT_GENRES:
                route = '/en/genres/' + tag
            elif tag == 'weekly':
                route = '/en/weekly'
            url = query_url(HOT + route, page=page) if page > 1 else HOT + route
        return self.card_rows(*self.document(http, url), self.cards)

    def vocabulary(self, http):
        return [{'key': name, 'label': name.replace('_', ' '), 'kind': 'genre'} for name in HOT_GENRES]

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        writer = node_text(doc.select_one('p.type_box span.writer')).rsplit('ⓒ', 1)[-1].strip()
        row['authors'] = [writer] if writer else []
        row['genres'] = [v.strip() for v in node_text(doc.select_one('p.type_box span.type')).split('/') if v.strip()]
        row['status'] = 'completed' if row['status'] in ('End', 'Ende') else 'ongoing' if row['status'] else ''
        more = node_text(doc.select_one('div.title_content > h2:not(.episode-title)'))
        row['description'] = '\n\n'.join(filter(None, (row.get('description'), more)))
        return row

    def chapters(self, http, doc, final):
        seen = {}
        for anchor in doc.select('#tab-chapter a'):
            match = re.search(r"""popupLogin\(\s*['"]([^'"]+)""", anchor.get('onclick', ''))
            href = self.site_link(match[1] if match else anchor.get('href'), final)
            if not href:
                continue
            target = query_url(href, mv_hot_read=1, mv_hot_parent=self.title_key(final))
            if self.is_chapter(target):
                name = node_text(anchor.select_one('.cell-num'))
                stamp = release_date(node_text(anchor.select_one('.cell-time')), '%b %d, %Y')
                seen[target] = self.chapter(target, name, date=stamp)
        return self.order(seen), False

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and (self.title_key(self.title_for(target)) == self.title_key(title)
                                                 or self.confirm_archive_membership(target, title)))

    def pages(self, http, url):
        clean = query_url(url, mv_hot_read=[])
        clean = query_url(clean, mv_hot_parent=[])
        doc, final = self.document(http, clean)
        if self.chapter_identity(final) != self.chapter_identity(url):
            raise SourceError('HotComics перенаправил на другой выпуск.')
        return [src for node in doc.select('#viewer-img img') if (src := picture(node, final, ('data-src',)))]

    def inspect(self, value, http):
        target = self.canonical(value)
        if self.is_chapter(target) and self.is_title(target):
            target = query_url(target, mv_hot_read=1)
        return super().inspect(target, http)


class Buttsmithy(SeriesPort):
    def __init__(self):
        super().__init__(('5116114496934092518', 'Buttsmithy', 'en', INCASE, True),
                         rf'(?:/|{WP_PAGE})', WP_PAGE, hosts=('buttsmithy.com',), interval=.35)

    def is_title(self, url):
        parts = urlsplit(url)
        if parts.netloc == 'buttsmithy.com':
            return parts.path == '/'
        return super().is_chapter(url) and param(url, 'mv_incase_read') != '1'

    def is_chapter(self, url):
        parts = urlsplit(url)
        return bool(super().is_chapter(url) and (
            (parts.netloc == 'buttsmithy.com' and parts.path.startswith('/archives/')) or
            (parts.netloc == 'incase.buttsmithy.com' and param(url, 'mv_incase_read') == '1')))

    def saved_title_url(self, value):
        url = self.canonical(value)
        if urlsplit(url).netloc == 'buttsmithy.com':
            return ALFIE + '/'
        return url if self.is_title(url) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        doc, final = self.document(http, INCASE)
        rows = {ALFIE + '/': self.record(ALFIE + '/', 'Alfie', authors=['InCase'], genres=['Fantasy'])}
        for anchor in doc.select('#menu-item-331 .menu-item-type-custom a[href], #menu-item-38 .menu-item-type-custom a[href]'):
            name = node_text(anchor)
            url = self.site_link(anchor['href'], final)
            if url and name and 'alfie' not in name.casefold() and self.is_title(url):
                rows[url] = self.record(url, name, authors=['InCase'], status='completed')
        return [row for row in rows.values() if query in row['title'].casefold()], False

    def title_for(self, url):
        if urlsplit(url).netloc == 'buttsmithy.com':
            return ALFIE + '/'
        key = param(url, 'mv_incase_parent')
        target = self.site_link('/' + key.lstrip('/'), INCASE + '/') if key else ''
        return target if self.is_title(target) else ''

    def title_key(self, url):
        parts = urlsplit(url)
        return 'alfie' if parts.netloc == 'buttsmithy.com' and parts.path == '/' else parts.path.strip('/')

    def details(self, http, url):
        target = self.saved_title_url(url)
        if not target:
            raise SourceError('Некорректная карточка Buttsmithy.')
        name = 'Alfie' if target == ALFIE + '/' else ''
        cover = ''
        if not name:
            doc, final = self.document(http, target)
            if self.chapter_identity(final) != self.chapter_identity(target):
                raise SourceError('Buttsmithy перенаправил страницу комикса.')
            headline = next((value for node in doc.select('meta[property="og:title"]')
                             if (value := node.get('content', '').strip())), '')
            name = headline or node_text(doc.select_one('#comic h1, .comic-title, h1')) or self.title_key(target).replace('-', ' ')
            cover = picture(doc.select_one('#comic img'), final)
        return self.record(target, name, cover, authors=['InCase'], genres=['Fantasy'] if target == ALFIE + '/' else [])

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        if urlsplit(target).netloc == 'incase.buttsmithy.com' and self.is_title(title):
            return query_url(target, mv_incase_read=1, mv_incase_parent=self.title_key(title))
        return ''

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title))

    def chapters(self, http, title):
        doc, current = self.document(http, title)
        if title == ALFIE + '/':
            rows = {}
            for item in doc.select('#chapter option.level-0[value]'):
                target = self.site_link(item['value'], current)
                if self.is_chapter(target):
                    rows[target] = self.chapter(target, node_text(item))
            return self.order(rows), False

        first = doc.select_one('a.comic-nav-first[href]')
        if first:
            candidate = self.site_link(first['href'], current)
            if candidate and candidate != current:
                doc, current = self.document(http, candidate)
        rows = []
        seen = set()
        while current not in seen and len(rows) < MAX_CHAPTERS:
            if urlsplit(current).netloc != 'incase.buttsmithy.com':
                break
            seen.add(current)
            img = doc.select_one('#comic img')
            if not picture(img, current):
                break
            target = query_url(current, mv_incase_read=1, mv_incase_parent=self.title_key(title))
            rows.append(self.chapter(target, img.get('alt', ''), len(rows) + 1))
            link = doc.select_one('.comic-nav-next[href]')
            next_url = self.site_link(link['href'], current) if link else ''
            if not next_url or next_url in seen:
                break
            doc, current = self.document(http, next_url)
        return rows, len(rows) == MAX_CHAPTERS

    def pages(self, http, target):
        url = query_url(query_url(target, mv_incase_read=[]), mv_incase_parent=[])
        doc, final = self.document(http, url)
        if urlsplit(final).hostname != urlsplit(url).hostname or self.chapter_identity(final) != self.chapter_identity(url):
            raise SourceError('Buttsmithy перенаправил на другой выпуск.')
        if final.startswith(INCASE + '/'):
            image = picture(doc.select_one('#comic img'), final)
            return [image] if image else []
        link = doc.select_one('.comic-chapter a[href]')
        archive = self.site_link(link['href'], final) if link else ''
        if urlsplit(archive).netloc != 'buttsmithy.com' or not urlsplit(archive).path.startswith('/archives/chapter/'):
            raise SourceError('Buttsmithy не предоставил архив страниц.')
        first, base = self.document(http, archive)
        last = re.search(r'\bof\s+(\d{1,4})', node_text(first.select_one('.paginav-pages')))
        count = int(last[1]) if last else 1
        if count > 80:
            raise SourceError('Архив Buttsmithy превышает лимит страниц.')
        pages = []
        for offset in range(1, count + 1):
            html, here = (first, base) if offset == 1 else self.document(http, archive.rstrip('/') + f'/page/{offset}')
            for img in html.select('.comic-thumbnail-in-archive img'):
                if src := picture(img, here):
                    pages.append(re.sub(r'-\d+x\d+(?=\.\w+$)', '', src))
        return list(dict.fromkeys(reversed(pages)))

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url):
            images = self.pages(http, url)
            if not 1 <= len(images) <= MAX_PAGES:
                raise SourceError('Buttsmithy не предоставил полный список страниц.')
            title = self.title_for(url) or url
            name = 'Alfie' if title == ALFIE + '/' else self.title_key(title).replace('-', ' ')
            return self.reader_result(self.record(title, name), url, [self.chapter(url, name)], images)
        title = self.saved_title_url(url)
        row = self.details(http, title)
        chapters, truncated = self.chapters(http, title)
        return self.reader_result(row, url, chapters, [], truncated)


SOURCES = (HotComics(), Buttsmithy())
