"""The Duck Webcomics directory and page-dropdown chapter grouping."""

import re
from collections import OrderedDict
from threading import Lock
from urllib.parse import urlsplit

from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, node_text
from manga_series_port import MAX_CHAPTERS, MAX_PAGES, picture
from manga_webcomics import query_url
from source_parser import SourceError


TITLE = rf'/({SEGMENT})/?'
CHAPTER = rf'/({SEGMENT})/([1-9]\d{{0,13}})/?'
EXCLUDED = {'search', 'forums', 'news', 'community', 'help', 'login', 'register', 'about'}


class DuckWebcomics(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, TITLE, CHAPTER, interval=.25)
        self.directory = OrderedDict()
        self.directory_lock = Lock()

    def is_title(self, url):
        return super().is_title(url) and self.title_key(url).casefold() not in EXCLUDED

    def title_for(self, url):
        return self.ROOT + '/' + self.chapter_key(url) + '/'

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        options = {'page': page}
        if query:
            options['search'] = query
        elif sort == 'updated':
            options['last_update'] = 'today'
        if tag:
            options['genre'] = tag[:120]
        url = query_url(self.ROOT + '/search/', **options)
        doc, final = self.document(http, url)
        rows = []
        for section in doc.select('.breadcrumb ~ div[style]'):
            node = section.select_one('a.size24[href], .size24 a[href]')
            target = self.site_link(node['href'], final) if node else ''
            title = node_text(node)
            if not self.is_title(target) or not title:
                continue
            genre = node_text(section.select_one('.size10')).partition(',')[0].strip()
            row = self.record(target, title, picture(section.select_one('img'), final),
                              description=node_text(section.select_one('.comicdescparagraphs')),
                              genres=[genre], authors=[node_text(section.select_one('.size18'))])
            row['format'] = 'comic'
            rows.append(row)
        with self.directory_lock:
            for row in rows:
                self.directory[self.title_key(row['sourceUrl'])] = row
                self.directory.move_to_end(self.title_key(row['sourceUrl']))
            while len(self.directory) > 2000:
                self.directory.popitem(last=False)
        return rows, bool(doc.select_one('a.next'))

    def groups(self, doc):
        groups = []
        seen = set()
        for node in reversed(doc.select('#page_dropdown > option[value]')):
            page = node['value']
            if not re.fullmatch(r'[1-9]\d{0,13}', page) or page in seen:
                continue
            seen.add(page)
            name = node_text(node)
            if not groups or not name.startswith('-'):
                groups.append([])
            groups[-1].append((page, name.removeprefix('- ').strip()))
        return [*groups[:-1], *([page] for page in groups[-1])] if groups else []

    def resolve_details(self, url, doc):
        slug = self.title_key(url)
        with self.directory_lock:
            row = self.directory.get(slug)
        if row:
            return row.copy()
        label = node_text(doc.select_one('.breadcrumb a:last-child, h1')) or slug.replace('_', ' ')
        row = self.record(url, label)
        row['format'] = 'comic'
        return row

    def details(self, http, url):
        url = self.saved_title_url(url)
        if not self.is_title(url):
            raise SourceError('Некорректная ссылка на комикс.')
        return self.resolve_details(url, self.document(http, url)[0])

    def series(self, http, url):
        slug = self.title_key(url)
        doc, final = self.document(http, url)
        if not re.fullmatch(rf'/{re.escape(slug)}(?:/[1-9]\d{{0,13}})?/?', urlsplit(final).path):
            raise SourceError('Источник перенаправил запрос на другой комикс.')
        if doc.select_one('.yellow-box > .paranomargin') and not doc.select_one('#page_dropdown'):
            raise SourceError('Источник не предоставил оглавление комикса.')
        groups = self.groups(doc)
        rows = [self.chapter(f'{self.ROOT}/{slug}/{group[0][0]}/', group[0][1], idx)
                for idx, group in enumerate(groups[:MAX_CHAPTERS], 1)]
        return self.resolve_details(url, doc), rows

    def pages(self, http, url):
        doc, final = self.document(http, url)
        if self.chapter_identity(final) != self.chapter_identity(url):
            raise SourceError('Источник перенаправил запрос на другой выпуск.')
        slug = self.chapter_key(url)
        current = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)[2]
        chapter = next((group for group in self.groups(doc) if group[0][0] == current), [(current, '')])
        if len(chapter) > MAX_PAGES:
            raise SourceError('Источник вернул слишком много страниц.')
        urls = []
        for page, _ in chapter:
            target = f'{self.ROOT}/{slug}/{page}/'
            body, actual = (doc, final) if page == current else self.document(http, target)
            if self.chapter_identity(actual) != self.chapter_identity(target):
                raise SourceError('Источник перенаправил запрос на другую страницу.')
            urls.append(picture(body.select_one('.page-image'), actual))
        return urls
