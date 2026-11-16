"""Comics Kingdom's bilingual WordPress feature and strip catalogue."""

import json
import re
from html import unescape
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import MAX_PAGES, SeriesPort
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://wp.comicskingdom.com'
FEATURE = '/wp-json/wp/v2/ck_feature'
STRIP = '/wp-json/wp/v2/ck_comic'
ID = r'[1-9]\d{0,10}'
FEATURE_FIELDS = 'id,link,title,content,meta,yoast_head'
STRIP_FIELDS = 'id,date,assets,link'
NUMBER = re.compile(r'"totalItems"\s*:\s*(\d{1,7})')
THUMB = re.compile(r'"thumbnailUrl"\s*:\s*"([^"]+)"')
GENRES = ('action', 'adventure', 'classic', 'comedy', 'crime', 'fantasy', 'gag-cartoons', 'mystery',
          'new-arrivals', 'non-fiction', 'offbeat', 'political-cartoons', 'romance', 'sci-fi',
          'slice-of-life', 'superhero', 'vintage')


class ComicsKingdom(SeriesPort):
    def __init__(self, sid, language):
        self.site_language = 'spanish' if language == 'es' else 'english'
        super().__init__((sid, 'Comics Kingdom', language, ROOT, False), rf'{FEATURE}/({ID})/?',
                         rf'({STRIP})(?:/{ID})?/?', hosts=('comicskingdom.com', 'www.comicskingdom.com'), interval=.35)

    def title_url(self, target, slug):
        return query_url(ROOT + FEATURE + '/' + target, slug=slug)

    def raw(self, http, target):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, headers = http.document(target)
        if urlsplit(final).netloc != 'wp.comicskingdom.com' or urlsplit(final).path.rstrip('/') != urlsplit(target).path.rstrip('/'):
            raise SourceError('Comics Kingdom перенаправил публичный запрос.')
        return json.loads(raw), headers

    def feature_request(self, http, suffix='', **args):
        return self.raw(http, query_url(ROOT + FEATURE + suffix, per_page=20, _fields=FEATURE_FIELDS,
                                        ck_language=self.site_language, **args))

    def build_title(self, data):
        key = str(data.get('id', ''))
        raw_link = data.get('link') or ''
        link = self.site_link(raw_link)
        title = unescape((data.get('title') or {}).get('rendered') or '')
        slug = urlsplit(link).path.strip('/').rsplit('/', 1)[-1]
        if not title or not re.fullmatch(ID, key) or not re.fullmatch(SEGMENT, slug):
            return None
        cover = THUMB.search(data.get('yoast_head') or '')
        cover = image_url(cover[1].replace(r'\/', '/'), link) if cover else ''
        summary = node_text(BeautifulSoup((data.get('content') or {}).get('rendered') or '', 'html.parser'))
        author = (data.get('meta') or {}).get('ck_byline_on_app') or ''
        row = self.record(self.title_url(key, slug), title, cover, description=summary, authors=[author.removeprefix('By').strip()])
        row['format'] = 'comic'
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'page': page}
        if query:
            args.update(search=query, orderby='relevance')
        else:
            args['orderBy'] = 'modified' if sort == 'updated' else 'relevance'
        if tag in GENRES:
            args['ck_genre'] = tag
        payload, headers = self.feature_request(http, **args)
        if not isinstance(payload, list):
            raise SourceError('Comics Kingdom изменил каталог.')
        rows = [row for item in payload if (row := self.build_title(item))]
        pages = next((str(v) for k, v in headers.items() if k.lower() == 'x-wp-totalpages'), '')
        return rows, (page < int(pages) if pages.isdecimal() else len(payload) == 20)

    def vocabulary(self, http):
        return [{'key': name, 'label': name.replace('-', ' ').title(), 'kind': 'genre'} for name in GENRES]

    def is_chapter(self, url):
        path = urlsplit(url).path.rstrip('/')
        if urlsplit(url).netloc != 'wp.comicskingdom.com' or not super().is_chapter(url):
            return False
        if path != STRIP:
            return True
        return bool(re.fullmatch(SEGMENT, param(url, 'ck_feature')) and re.fullmatch(ID, param(url, 'page')))

    def title_for(self, url):
        key = param(url, 'mv_ck_title')
        slug = param(url, 'ck_feature')
        return self.title_url(key, slug) if re.fullmatch(ID, key) and re.fullmatch(SEGMENT, slug) else ''

    def saved_chapter_matches(self, target, title):
        if not self.is_chapter(target):
            return False
        key = param(target, 'mv_ck_title')
        slug = param(target, 'ck_feature')
        return bool((key and key == self.title_key(title)) or (slug and slug == param(title, 'slug')))

    def feature(self, http, value):
        url = self.canonical(value)
        if self.is_title(url):
            result, _ = self.feature_request(http, '/' + self.title_key(url))
        else:
            slug = urlsplit(url).path.strip('/').rsplit('/', 1)[-1]
            if not re.fullmatch(SEGMENT, slug):
                raise SourceError('Некорректная карточка Comics Kingdom.')
            matches, _ = self.feature_request(http, slug=slug)
            result = matches[0] if matches else {}
        row = self.build_title(result)
        if not row or (self.is_title(url) and self.title_key(url) != self.title_key(row['url'])):
            raise SourceError('Comics Kingdom не предоставил нужную карточку.')
        return row, result

    def details(self, http, url):
        return self.feature(http, url)[0]

    def strips(self, http, slug, page, order='asc'):
        return self.raw(http, query_url(ROOT + STRIP, per_page=100, _fields=STRIP_FIELDS, orderBy='date',
                                        order=order, ck_feature=slug, page=page))

    def chapters(self, http, row, item):
        slug = param(self.site_link(row['url']), 'slug')
        key = str(item['id'])
        doc, _ = self.document(http, self.site_link(item['link']))
        count = next((int(m[1]) for m in NUMBER.finditer(str(doc)) if int(m[1]) > 0), 0)
        if not count:
            data, headers = self.strips(http, slug, 1)
            count = int(next((value for k, value in headers.items() if k.lower() == 'x-wp-total'), len(data)))
        chunks = (count + 99) // 100
        return [self.chapter(query_url(ROOT + STRIP, ck_feature=slug, page=i, mv_ck_title=key),
                             f'{(i - 1) * 100 + 1}–{min(i * 100, count)}', i)
                for i in range(1, min(chunks, 2000) + 1)], chunks > 2000

    def pages(self, http, url):
        if urlsplit(url).path.rstrip('/') == STRIP:
            slug = param(url, 'ck_feature')
            page = int(param(url, 'page'))
            data, _ = self.strips(http, slug, page, 'desc' if param(url, 'order') == 'desc' else 'asc')
        else:
            identifier = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]
            strip, _ = self.raw(http, query_url(ROOT + STRIP + '/' + identifier, _fields=STRIP_FIELDS))
            data = [strip]
        return [src for strip in data if isinstance(strip, dict)
                and (src := image_url((((strip.get('assets') or {}).get('single') or {}).get('url')), ROOT))]

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_chapter(url):
            row, item = self.feature(http, url)
            chapters, truncated = self.chapters(http, row, item)
            return self.reader_result(row, url, chapters, [], truncated)
        pages = self.pages(http, url)
        if not 1 <= len(pages) <= MAX_PAGES:
            raise SourceError('Comics Kingdom не предоставил открытые страницы выпуска.')
        title = self.title_for(url)
        row = self.feature(http, title)[0] if title else self.record(url, 'Comics Kingdom')
        return self.reader_result(row, url, [self.chapter(url)], pages)


SOURCES = (ComicsKingdom('3350274514125477391', 'en'), ComicsKingdom('6467305425630534148', 'es'))
