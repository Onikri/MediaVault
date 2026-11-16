"""4KHD public WordPress REST catalogue and gallery reader."""

import json
import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import MAX_PAGES, SeriesPort, picture
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://www.4khd.com'
HOSTS = ('4khd.com',)
ENDPOINT = ROOT + '/index.php'
LIST = '/wp/v2/posts'
ID = r'[1-9]\d{0,10}'
CONTENT = rf'/content/(?:{SEGMENT}/){{1,4}}({SEGMENT})\.html(?:/{ID})?/?'
IMAGE = re.compile(r'\.(?:jpe?g|png|webp|gif|avif)$', re.I)


class FourKHD(SeriesPort):
    def __init__(self):
        super().__init__(('6501663152246384585', '4KHD', 'all', ROOT, True),
                         rf'(?:{CONTENT}|/)', rf'(?:{CONTENT}|/)', hosts=HOSTS, interval=.35)

    def is_title(self, url):
        return bool(self.title_key(url) and param(url, 'mv_4k_gallery') != '1')

    def is_chapter(self, url):
        return bool(self.title_key(url) and param(url, 'mv_4k_gallery') == '1')

    def title_key(self, url):
        path = urlsplit(url).path
        if (opt := param(url, 'post_id') or param(url, 'p')) and re.fullmatch(ID, opt):
            return '#' + opt
        pattern = re.fullmatch(CONTENT, path)
        return pattern[1] if pattern else ''

    def title_for(self, url):
        target = query_url(url, mv_4k_gallery=[])
        return target if self.is_title(target) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        return query_url(target, mv_4k_gallery=1) if self.title_key(target) else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(target) == self.title_key(title)

    def request(self, http, **options):
        self.origin.wait(getattr(http, 'deadline', None))
        target = query_url(ENDPOINT, _embed='1', **options)
        payload, final, headers = http.document(target, headers={'Referer': ROOT + '/'})
        if final != target:
            raise SourceError('4KHD перенаправил публичный запрос WordPress.')
        return json.loads(payload), headers

    def images(self, data, url):
        content = (data.get('content') or {}).get('rendered') or ''
        doc = BeautifulSoup(content, 'html.parser')
        container = doc.select_one('.entry-content.wp-block-post-content, .entry-content') or doc
        result = {}
        for node in container.select('img[data-src], img[data-lazy-src], img[src]'):
            target = picture(node, url, ('data-src', 'data-lazy-src'))
            parts = urlsplit(target)
            if target and IMAGE.search(parts.path):
                result.setdefault(urlunsplit(parts._replace(query='')), target)
        if not result:
            for node in container.select('a[href]'):
                target = image_url(node['href'], url)
                parts = urlsplit(target)
                if target and IMAGE.search(parts.path):
                    result.setdefault(urlunsplit(parts._replace(query='')), target)
        return list(result.values())

    def row_for(self, item):
        raw = self.site_link(item.get('link'))
        if not self.title_key(raw):
            return None
        title = node_text(BeautifulSoup((item.get('title') or {}).get('rendered') or '', 'html.parser'))
        if not title:
            return None
        embedded = item.get('_embedded') or {}
        media = embedded.get('wp:featuredmedia') or []
        cover = item.get('jetpack_featured_media_url') or (media[0].get('source_url') if media else '')
        if not cover:
            cover = next(iter(self.images(item, raw)), '')
        terms = [entry.get('name') for group in embedded.get('wp:term') or [] for entry in group if isinstance(entry, dict)]
        row = self.record(raw, title, image_url(cover, raw), status='completed', tags=terms)
        row['format'] = 'gallery'
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'rest_route': LIST, 'page': page, 'per_page': 20, 'orderby': 'modified' if sort == 'popular' and not query else 'date'}
        if query or tag:
            args['search'] = query or tag[:160]
        data, headers = self.request(http, **args)
        if not isinstance(data, list):
            raise SourceError('4KHD изменил формат каталога.')
        total = next((str(value) for key, value in headers.items() if key.lower() == 'x-wp-totalpages'), '')
        return [row for item in data if isinstance(item, dict) and (row := self.row_for(item))], (
            total.isdecimal() and int(total) > page)

    def item(self, http, url):
        key = self.title_key(url)
        if not key:
            raise SourceError('Некорректная ссылка 4KHD.')
        if key.startswith('#'):
            item, _ = self.request(http, rest_route=LIST + '/' + key[1:])
            if str(item.get('id')) != key[1:]:
                raise SourceError('4KHD подменил галерею.')
        else:
            data, _ = self.request(http, rest_route=LIST, slug=key)
            item = next((entry for entry in data if self.title_key(self.site_link(entry.get('link'))) == key), {})
        row = self.row_for(item)
        if not row:
            raise SourceError('4KHD не предоставил данные галереи.')
        return item, row

    def details(self, http, url):
        return self.item(http, self.canonical(url))[1]

    def inspect(self, value, http):
        url = self.canonical(value)
        item, row = self.item(http, url)
        canonical = self.site_link(row['url'])
        chapters = [self.chapter(query_url(canonical, mv_4k_gallery=1), 'Gallery', 1, str(item.get('date') or '')[:10])]
        pages = self.images(item, canonical) if self.is_chapter(url) else []
        if self.is_chapter(url) and not 1 <= len(pages) <= MAX_PAGES:
            raise SourceError('4KHD не предоставил полный список страниц.')
        return self.reader_result(row, url, chapters, pages)


SOURCES = (FourKHD(),)
