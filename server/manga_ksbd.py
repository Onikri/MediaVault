"""Kill Six Billion Demons, with book-specific ComicPress archives."""

import re
from urllib.parse import urlsplit

from manga_madara import SEGMENT, node_text
from manga_series_port import MAX_CHAPTERS, MAX_PAGES, SeriesPort, number, picture
from manga_webcomics import param, query_url
from source_parser import PublicHttp, SourceError

ROOT = 'https://killsixbilliondemons.com'
BOOK = rf'/chapter/((?!\d+(?:[-/]|$)){SEGMENT})/?'
ARCHIVE = rf'/chapter/({SEGMENT})/?'
READER = rf'/(?:chapter|comic)/({SEGMENT})/?'
THUMBNAIL = re.compile(r'-\d+x\d+(?=\.(?:jpe?g|png|webp|gif)(?:\?.*)?$)', re.I)


class KillSixBillionDemons(SeriesPort):
    def __init__(self):
        super().__init__(('5520021760150818261', 'KillSixBillionDemons', 'en', ROOT, False),
                         BOOK, READER, interval=.35)

    def title_for(self, url):
        key = param(url, 'mv_ksbd_book')
        target = ROOT + '/chapter/' + key + '/'
        return target if self.is_title(target) else ''

    def saved_chapter_matches(self, target, title):
        if not self.is_chapter(target) or self.is_title(target):
            return False
        bound = self.title_for(target)
        if bound:
            return self.title_key(bound) == self.title_key(title)
        http = PublicHttp(timeout=(3, 6))
        try:
            _, options = self.title_data(http, title)
            rows, _ = self.chapters(http, options, title)
            return any(self.chapter_identity(self.site_link(row['url'])) == self.chapter_identity(target) for row in rows)
        finally:
            http.close()

    def options(self, doc, final):
        for node in doc.select('#chapter option[value]'):
            target = self.site_link(node['value'], final)
            label = re.split(r'\s+\(', node_text(node), maxsplit=1)[0].strip()
            if label and target and self.is_chapter(target):
                yield target, label, self.is_title(target)

    def summary(self, start, title, landing=None):
        cover = picture(landing.select_one('.comic-thumbnail-in-archive img'), start) if landing else ''
        row = self.record(start, title, cover, authors=['Abbadon'])
        row['format'] = 'comic'
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page > 1:
            return [], False
        doc, final = self.document(http, ROOT + '/')
        return [self.summary(target, label) for target, label, is_book in self.options(doc, final)
                if is_book and query in label.casefold()], False

    def title_data(self, http, url):
        doc, final = self.document(http, query_url(url, order='ASC'))
        key = self.title_key(url)
        if self.title_key(final) != key:
            raise SourceError('Kill Six Billion Demons перенаправил книгу.')
        options = list(self.options(doc, final))
        label = next((label for target, label, is_book in options if is_book and self.title_key(target) == key), '')
        if not label:
            raise SourceError('Kill Six Billion Demons не предоставил указанную книгу.')
        return self.summary(url, label, doc), options

    def details(self, http, value):
        url = self.canonical(value)
        if not self.is_title(url):
            raise SourceError('Некорректная книга Kill Six Billion Demons.')
        return self.title_data(http, url)[0]

    def archive(self, http, url):
        request = query_url(url.split('?', 1)[0], order='ASC')
        path = urlsplit(request).path.rstrip('/')
        rows = {}
        seen = set()
        for _ in range(80):
            if request in seen:
                break
            seen.add(request)
            doc, final = self.document(http, request)
            current = urlsplit(final).path.rstrip('/')
            if current != path and not re.fullmatch(re.escape(path) + r'/page/[1-9]\d{0,3}', current):
                raise SourceError('Kill Six Billion Demons перенаправил архив.')
            for link in doc.select('.comic-thumbnail-in-archive a[href]'):
                target = self.site_link(link['href'], final)
                if target and urlsplit(target).path.startswith('/comic/') and self.is_chapter(target):
                    rows[target] = link.get('title', '').strip()
            next_link = doc.select_one('.paginav-next a[href]')
            request = self.site_link(next_link['href'], final) if next_link else ''
            if not request:
                return rows
            next_path = urlsplit(request).path.rstrip('/')
            if next_path != path and not re.fullmatch(re.escape(path) + r'/page/[1-9]\d{0,3}', next_path):
                raise SourceError('Некорректное продолжение архива Kill Six Billion Demons.')
        raise SourceError('Не удалось получить полный архив Kill Six Billion Demons.')

    def chapters(self, http, options, book):
        key = self.title_key(book)
        result = []
        within_book = False
        for url, label, is_book in options:
            if is_book:
                if within_book:
                    break
                within_book = self.title_key(url) == key
                continue
            if within_book:
                target = query_url(url, mv_ksbd_book=key)
                result.append(self.chapter(target, f'Chapter {label}', number(label) or len(result) + 1))
        if result:
            active = result.pop()
            ending = self.site_link(active['url'])
            for i, (url, label) in enumerate(self.archive(http, ending).items(), 1):
                url = query_url(url, mv_ksbd_book=key)
                result.append(self.chapter(url, active['title'] + (' — ' + label if label else f' · {i}'),
                                           active['number'] + i / 1000))
            if not result or not any(row['number'] > active['number'] for row in result):
                result.append(active)
        return result[:MAX_CHAPTERS], len(result) > MAX_CHAPTERS

    def image_urls(self, http, url):
        target = url.split('?', 1)[0]
        doc, final = self.document(http, target)
        if self.chapter_identity(final) != self.chapter_identity(target):
            raise SourceError('Kill Six Billion Demons перенаправил страницу.')
        return [THUMBNAIL.sub('', src) for node in doc.select('#comic img[src]') if (src := picture(node, final))]

    def pages(self, http, url):
        if re.fullmatch(ARCHIVE, urlsplit(url).path):
            pages = []
            for post in self.archive(http, url):
                pages.extend(self.image_urls(http, post))
                if len(pages) > MAX_PAGES:
                    break
            return pages
        return self.image_urls(http, url)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_title(url):
            row, options = self.title_data(http, url)
            chapters, truncated = self.chapters(http, options, url)
            return self.reader_result(row, url, chapters, [], truncated)
        if not self.is_chapter(url):
            raise SourceError('Некорректный выпуск Kill Six Billion Demons.')
        title = self.title_for(url) or url
        pages = self.pages(http, url)
        if not 1 <= len(pages) <= MAX_PAGES:
            raise SourceError('Kill Six Billion Demons не предоставил полный выпуск.')
        label = 'Kill Six Billion Demons'
        return self.reader_result(self.summary(title, label), url, [self.chapter(url, label)], pages)


SOURCES = (KillSixBillionDemons(),)
