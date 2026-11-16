"""HTML chapter archives for TodayManga, ToonHey and Oppai Stream."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_direct_catalogues import SLUG
from manga_direct_payloads import JsonSeries, segment
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, Meta, number, picture
from manga_webcomics import param, query_url
from source_parser import SourceError


PAGE_PATH = rf'/({SEGMENT}(?:/{SEGMENT}){{0,6}})/?'
CHAPTER_ID = r'[A-Za-z0-9_.-]{1,80}'
HEY_GENRES = ('Detective', 'Spin-Off', 'Mommy', 'Uncensored', 'New', 'In-Law', 'Cheating', 'MILF', 'Harem',
              'College', 'Business', 'Supernatural', 'Thriller', 'Adventure', 'Romance', 'Drama')


class LinkedArchive(JsonSeries):
    def is_chapter(self, url):
        return super().is_chapter(url) and bool(self.title_for(url))

    def title_for(self, url):
        parent = param(url, 'mv_title')
        if parent.startswith('/') and self.TITLE_PATH.fullmatch(parent):
            return self.ROOT + parent
        return ''

    @staticmethod
    def upstream(url):
        parts = urlsplit(url)
        filtered = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != 'mv_title']
        return urlunsplit(parts._replace(query=urlencode(filtered), fragment=''))

    def saved_chapter(self, row, root, title):
        link = super().saved_chapter(row, root, title)
        if link and self.is_title(title) and self.CHAPTER_PATH.fullmatch(urlsplit(link).path):
            return query_url(link, mv_title=urlsplit(title).path)
        return ''

    def saved_chapter_matches(self, target, title):
        key = self.title_key(title)
        return bool(key and key == self.title_key(self.title_for(target)))

    def chapter_document(self, http, url):
        wire = self.upstream(url)
        page, actual = self.document(http, wire)
        if urlsplit(actual).path.rstrip('/') != urlsplit(wire).path.rstrip('/'):
            raise SourceError('Источник перенаправил запрос на другую главу.')
        return page, actual


class TodayManga(LinkedArchive):
    def __init__(self, identity):
        super().__init__(identity, rf'/book/{SLUG}/?', PAGE_PATH, interval=.35)
        self.meta = Meta('.series-info h1', '.series-info img', '.series-summary',
                         genres='.series-info [itemprop=genre] a', author='.series-info span[itemprop=author] > span',
                         status='.series-info *:-soup-contains-own("Status") + *')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'page': page} if page > 1 else {}
        if query:
            target = self.ROOT + '/search'
            args['q'] = query
        elif tag:
            genre = segment(tag)
            if not genre:
                raise SourceError('Некорректная метка каталога.')
            target = self.ROOT + '/genre/' + genre
        else:
            target = self.ROOT + ('/category/recent' if sort == 'updated' else '/category/most-popular')
        cards = Cards('section > main > div.series-info, section div.serie, ul.series > li', 'a[href]', '.series-name',
                      next='.pagination > ul > li.active + li:has(a)')
        return self.card_rows(*self.document(http, query_url(target, **args)), cards)

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        row = self.metadata(doc, final, self.meta)
        chapters = {}
        for node in doc.select('#chapList > li'):
            anchor = node.select_one('a[href]')
            href = self.site_link(anchor['href'], final) if anchor else ''
            if not href or not self.CHAPTER_PATH.fullmatch(urlsplit(href).path):
                continue
            target = query_url(href, mv_title=urlsplit(final).path)
            label = node_text(node.select_one('strong')) or node_text(anchor)
            date = release_date(node_text(node.select_one('span.muted')), '%b %d, %Y')
            chapters[target] = self.chapter(target, label, date=date)
        return row, self.order(chapters)

    def pages(self, http, url):
        doc, final = self.chapter_document(http, url)
        images = doc.select('.chapter-content > img[data-index]')
        indices = [number(node.get('data-index')) for node in images]
        if not all(index is not None for index in indices):
            raise SourceError('Источник не предоставил порядок изображений.')
        rows = zip(indices, images, strict=True)
        return [picture(node, final, ('data-lazy-src', 'data-src')) for _, node in sorted(rows, key=lambda row: row[0])]


class ToonHey(LinkedArchive):
    def __init__(self, identity):
        super().__init__(identity, PAGE_PATH, PAGE_PATH, interval=.35)
        self.meta = Meta('#titleSubWrapper h1.titCon', 'meta[property="og:image"]', '#modal_detail .cont_area p',
                         tags='#modal_detail a[href*="genres"]')

    def is_title(self, url):
        path = urlsplit(url).path
        return (super().is_title(url) and not param(url, 'mv_title') and not re.match(
            r'/(?:api(?:/|$)|(?:en/)?(?:genres|search|login|register|about)(?:/|$))', path, flags=re.I))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            if page != 1:
                return [], False
            data = self.json(http, query_url(self.ROOT + '/api/complete-search', keyword=query))
            if not isinstance(data, list):
                raise SourceError('Источник изменил формат поиска.')
            rows = []
            for item in data:
                if not isinstance(item, dict) or not isinstance(title := item.get('title'), str):
                    continue
                url = self.site_link(item.get('linkComic'))
                if self.is_title(url) and title.strip():
                    rows.append(self.record(url, title, image_url(item.get('raw_thumb'), self.ROOT)))
            return rows, False
        if sort == 'popular' and page == 1 and not tag:
            doc, final = self.document(http, self.ROOT + '/')
            rows, _ = self.card_rows(doc, final, Cards(
                'section[class*="slider"]:has(h2:-soup-contains("Popular", "Trending")) a[href]', '',
                cover='img:not([alt="badge"])'))
            return rows, bool(rows)
        if sort == 'popular' and not tag:
            page -= 1
        if tag and tag not in HEY_GENRES:
            raise SourceError('Некорректная метка каталога.')
        path = self.ROOT + '/en/genres' + ('/' + segment(tag) if tag else '')
        args = {'orderBy': 'latest' if sort == 'updated' else 'views'}
        if page > 1:
            args['page'] = page
        cards = Cards('div[class*="comicItem"] a[href]', '', 'img:not([alt="badge"])', title_attr='title',
                      cover='img:not([alt="badge"])', next='.wp-pagenavi .nextpostslink')
        return self.card_rows(*self.document(http, query_url(path, **args)), cards)

    def vocabulary(self, http):
        return [{'label': label, 'sourceId': label, 'category': 'tag'} for label in HEY_GENRES]

    def metadata(self, doc, final, spec):
        row = super().metadata(doc, final, spec)
        badges = {node_text(node) for node in doc.select('.badgeArea span')}
        row['status'] = 'completed' if 'Completed' in badges else 'ongoing' if 'Up' in badges else ''
        return row

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        row = self.metadata(doc, final, self.meta)
        chapters = {}
        for node in doc.select('.episodeListConPC a#episodeItemCon[href]'):
            link = self.site_link(node['href'], final)
            if not link or not self.CHAPTER_PATH.fullmatch(urlsplit(link).path):
                continue
            target = query_url(link, mv_title=urlsplit(final).path)
            label = node_text(node.select_one('.comicInfo p.episodeStitle'))
            date = release_date(node_text(node.select_one('.comicInfo .episodeDate')), '%b %d, %Y')
            chapters[target] = self.chapter(target, label, date=date)
        return row, self.order(chapters)

    def pages(self, http, url):
        doc, final = self.chapter_document(http, url)
        return [picture(node, final) for node in doc.select('#comicContent img')]


class OppaiStream(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, r'(/manhwa)/?', r'(/page)/?', interval=.35)
        self.meta = Meta('.manhwa-info-in h1', '.cover-img', '.manhwa-info-in .description',
                         genres='.manhwa-info-in .genres h5', author='.manhwa-info-in h1 a.red')

    def title_key(self, url):
        return segment(param(url, 'm'))

    def chapter_key(self, url):
        return self.title_key(url)

    def is_title(self, url):
        return super().is_title(url) and bool(self.title_key(url))

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(self.chapter_key(url)) and bool(re.fullmatch(CHAPTER_ID, param(url, 'c')))

    def title_for(self, url):
        return query_url(self.ROOT + '/manhwa', m=param(url, 'm'))

    def chapter_identity(self, url):
        return self.chapter_key(url), param(url, 'c')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        params = {'text': query, 'order': 'uploaded' if sort == 'updated' else 'views', 'page': page, 'limit': 36}
        if tag:
            params['genres'] = tag[:120]
        doc, final = self.document(http, query_url(self.ROOT + '/api-search.php', **params))
        rows, elements = [], doc.select('div.in-grid > a[href]')
        for node in elements:
            target = self.site_link(node['href'], final)
            if urlsplit(target).path == '/fw':
                target = self.site_link(param(target, 'to'), final)
            title = node_text(node.select_one('h3.man-title'))
            if title and self.is_title(target):
                rows.append(self.record(self.title_for(target), title, picture(node.select_one('img.read-cover'), final)))
        return rows, len(elements) >= 36

    def details(self, http, url):
        url = self.saved_title_url(url)
        if not self.is_title(url):
            raise SourceError('Некорректная ссылка на тайтл.')
        doc, final = self.title_document(http, url)
        row = self.metadata(doc, final, self.meta)
        row['title'] = re.split(r'\s+By\s+', row['title'], maxsplit=1)[0]
        return row

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        row = self.metadata(doc, final, self.meta)
        row['title'] = re.split(r'\s+By\s+', row['title'], maxsplit=1)[0]
        chapters = {}
        for node in doc.select('.sort-chapters > a[href]'):
            link = self.site_link(node['href'], final)
            if self.is_chapter(link) and self.chapter_key(link) == self.title_key(final):
                title = node_text(node.select_one('div > h4'))
                stamp = release_date(node_text(node.select_one('div > h6')), '%b %d, %Y')
                chapters[link] = self.chapter(link, title, number(param(link, 'c')), stamp)
        return row, self.order(chapters)

    def pages(self, http, url):
        wire = query_url('https://myspacecat.pictures/manhwa/im.php', **{'f-m': param(url, 'm'), 'c': param(url, 'c')})
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(wire, headers={'Referer': url}, action='native-series-html-api')
        if final != wire:
            raise SourceError('Источник перенаправил запрос изображений.')
        return [picture(node, final) for node in BeautifulSoup(raw, 'html.parser').select('img[src]')]


def public_api(host, path, query):
    if host == 'toonhey.com' and path == '/api/complete-search':
        args = dict(parse_qsl(query))
        return set(args) == {'keyword'} and 1 <= len(args['keyword']) <= 160
    if host == 'myspacecat.pictures' and path == '/manhwa/im.php':
        args = dict(parse_qsl(query))
        return set(args) == {'f-m', 'c'} and bool(segment(args['f-m'])) and bool(re.fullmatch(CHAPTER_ID, args['c']))
    return False
