"""Dynasty Scans browse feeds, tagged series, and standalone chapters."""

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import strings
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import MAX_CHAPTERS, MAX_PAGES, SeriesPort, number, picture
from manga_webcomics import param, query_url
from source_parser import PublicHttp, SourceError

ROOT = 'https://dynasty-scans.com'
TYPES = {'Series': 'series', 'Anthology': 'anthologies', 'Doujin': 'doujins', 'Issue': 'issues'}
DIRS = '(?:' + '|'.join(TYPES.values()) + '|chapters)'
TITLE = rf'/{DIRS}/({SEGMENT})/?'
CHAPTER = rf'/chapters/({SEGMENT})/?'


def public_api(host, path, query):
    return (host == 'dynasty-scans.com' and bool(re.fullmatch(rf'/{DIRS}/{SEGMENT}\.json', path))
            and (not query or bool(re.fullmatch(r'page=\d{1,4}', query))))


def entries(value):
    return (item for item in value if isinstance(item, dict)) if isinstance(value, list) else ()


def labels(obj, field):
    return [tag['name'] for tag in entries(obj.get('tags')) if tag.get('type') == field
            and isinstance(tag.get('name'), str)]


class Dynasty(SeriesPort):
    def __init__(self):
        super().__init__(('669095474988166464', 'Dynasty Scans', 'en', ROOT, True), TITLE, CHAPTER,
                         hosts=('www.dynasty-scans.com',), interval=1.)

    def is_standalone(self, url):
        return super().is_chapter(url) and urlsplit(url).path.rstrip('/') != '/chapters/added'

    def is_chapter(self, url):
        return self.is_standalone(url) and bool(param(url, 'mv_title'))

    def title_for(self, url):
        return self.site_link(url.split('?', 1)[0].rstrip('/'))

    def chapter_identity(self, url):
        return self.chapter_key(url)

    def by_type(self, kind, key):
        return ROOT + '/' + kind + '/' + key if kind and isinstance(key, str) and re.fullmatch(SEGMENT, key) else ''

    def json_for(self, http, url, page=None):
        target = ROOT + urlsplit(url).path.rstrip('/') + '.json'
        if page is not None:
            target = query_url(target, page=page)
        value = self.json(http, target, ROOT + '/')
        if not isinstance(value, dict):
            raise SourceError('Dynasty Scans изменил формат каталога.')
        return value

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        rows = {}
        if not query and not tag and sort == 'updated':
            data = self.json_for(http, ROOT + '/chapters/added', page - 1)
            for chapter in entries(data.get('chapters')):
                parent = False
                for linked in entries(chapter.get('tags')):
                    url = self.by_type(TYPES.get(linked.get('type')), linked.get('permalink'))
                    if url and isinstance(linked.get('name'), str):
                        rows[url] = self.record(url, linked['name'])
                        parent |= linked.get('type') == 'Series'
                url = self.by_type('chapters', chapter.get('permalink'))
                if not parent and url and isinstance(chapter.get('title'), str):
                    rows[url] = self.record(url, chapter['title'])
            total = number(data.get('total_pages')) or 0
            current = number(data.get('current_page')) or page - 1
            return list(rows.values()), bool(rows and current < total)
        popular = not query and not tag
        if popular and page != 1:
            return [], False
        filters = {'q': query, 'sort': '' if query else 'released_on', 'page': page}
        if re.fullmatch(r'\d{1,12}', tag):
            filters['with[]'] = tag
        doc, final = self.document(http, ROOT + '/' if popular else query_url(ROOT + '/search', **filters))
        selector = ('h4:-soup-contains("Most Popular of Past 7 Days") ~ ul.cover-list a.thumbnail'
                    if popular else '.chapter-list a.name[href], .chapter-list .doujin_tags a[href]')
        for node in doc.select(selector):
            url = self.site_link(node.get('href'), final)
            if not self.is_title(url):
                continue
            thumbnail = node.select_one('img')
            name = node_text(node) or (thumbnail.get('alt') if thumbnail else '') or ''
            if not name:
                name = self.title_key(url).replace('_', ' ')
            rows[url] = self.record(url, name, picture(thumbnail, final))
        return list(rows.values()), bool(rows and not popular and doc.select_one('.pagination [rel=next]'))

    def chapters_for(self, first, items):
        result = {}
        header = ''
        for item in items:
            if 'header' in item:
                header = str(item['header'] or '')
                continue
            key = item.get('permalink')
            target = self.by_type('chapters', key)
            if not target:
                continue
            target = query_url(target, mv_title=urlsplit(first).path.strip('/'))
            name = ' '.join(filter(None, [header, str(item.get('title') or '')]))
            result[target] = self.chapter(target, name, date=release_date(str(item.get('released_on') or ''), '%Y-%m-%d'),
                                          translator=', '.join(labels(item, 'Scanlator')))
        return self.order(result)

    def detail_payload(self, http, url):
        target = self.site_link(url.split('?', 1)[0])
        data = self.json_for(http, target)
        if data.get('permalink') != self.title_key(target):
            raise SourceError('Dynasty Scans вернул данные другого произведения.')
        single = self.is_standalone(target)
        name = data.get('title' if single else 'name')
        if not isinstance(name, str) or not name:
            raise SourceError('Dynasty Scans не предоставил название.')
        description = BeautifulSoup(str(data.get('description') or ''), 'html.parser').get_text('\n', strip=True)
        pages = self.image_links(data, target) if single else []
        statuses = labels(data, 'Status')
        state = 'completed' if single else next((s for tag, s in (
            ('Ongoing', 'ongoing'), ('Completed', 'completed'), ('On Hiatus', 'hiatus')) if tag in statuses), '')
        row = self.record(target, name, image_url(data.get('cover'), target) or next(iter(pages), ''),
                          description=description, aliases=strings(data.get('aliases')), tags=labels(data, 'General'),
                          authors=labels(data, 'Author'), status=state)
        return row, data, pages

    def details(self, http, url):
        return self.detail_payload(http, url)[0]

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_standalone(target) and self.is_title(title):
            return query_url(target, mv_title=urlsplit(title).path.strip('/'))
        return ''

    def saved_chapter_matches(self, target, title):
        if not self.is_chapter(target) or not self.is_title(title):
            return False
        if self.is_standalone(title):
            return self.chapter_identity(title) == self.chapter_identity(target)
        http = PublicHttp(timeout=(3, 6))
        try:
            data = self.json_for(http, target)
            return any(
                urlsplit(self.by_type(TYPES.get(tag.get('type')), tag.get('permalink'))).path ==
                urlsplit(title).path.rstrip('/')
                for tag in entries(data.get('tags'))
            )
        finally:
            http.close()

    def image_links(self, data, url):
        return [page for item in entries(data.get('pages')) if (page := image_url(item.get('url'), url))]

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_title(url):
            raise SourceError('Некорректная ссылка Dynasty Scans.')
        row, data, pages = self.detail_payload(http, url)
        if self.is_standalone(url):
            reading = self.is_chapter(url)
            if reading and not 1 <= len(pages) <= MAX_PAGES:
                raise SourceError('Dynasty Scans не предоставил полный список изображений.')
            chapters = self.chapters_for(url, [data])
            return self.reader_result(row, url, chapters, pages if reading else [])
        entries_all = list(entries(data.get('taggings')))
        total = int(number(data.get('total_pages')) or 1)
        for page in range(2, min(total, 80) + 1):
            entries_all.extend(entries(self.json_for(http, url, page).get('taggings')))
            if len(entries_all) >= MAX_CHAPTERS:
                break
        chapters = self.chapters_for(url, entries_all)
        return self.reader_result(row, url, chapters[:MAX_CHAPTERS], [], total > 80 or len(chapters) > MAX_CHAPTERS)


SOURCES = (Dynasty(),)
