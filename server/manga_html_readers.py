"""Direct FanFox, ManhwaRead and New Manhwa reader layouts."""

import base64
import binascii
import json
import re
from urllib.parse import urlsplit

from manga_direct_catalogues import Browse, DirectCatalogue, Layout, MANGA, SERIES, SLUG
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Archive, Cards, Meta, picture
from manga_source_tags import unique
from manga_webcomics import query_url
from source_parser import SourceError


FOX_READER = re.compile(rf'/roll_manga/{SEGMENT}(?:/{SEGMENT}){{1,4}}/?')


class FanFox(DirectCatalogue):
    def __init__(self, identity):
        pager = '.pager-list-left a.active + a + a'
        browse = Cards('ul.manga-list-1-list li', 'a[href]', title_attr='title', cover='a img', next=pager)
        search = Cards('ul.manga-list-4-list li', 'a[href]', title_attr='title', cover='a img', next=pager)
        super().__init__(identity, Layout(
            MANGA, rf'/manga/{SLUG}(?:/{SEGMENT}){{1,4}}/?', browse,
            Meta('.detail-info-right-title-font, h1', '.detail-info-cover-img', '.detail-info-right p.fullcontent',
                 genres='.detail-info-right-tag-list a', author='.detail-info-right-say a',
                 status='.detail-info-right-title-tip'),
            Archive('ul.detail-main-list li a[href]', anchor='', title='.detail-main-list-main p:first-child',
                    date='.detail-main-list-main p:last-child', date_pattern='%b %d,%Y'),
            '#viewer img[data-original]', Browse('/directory/{page}.html', first_path='/directory/'),
            Browse('/search', cards=search), title_path='/manga/', suffix='/',
        ))
        self.origin.interval = 1

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query or tag:
            if tag and not re.fullmatch(r'[1-9]\d{0,5}', tag):
                raise SourceError('Некорректный жанр каталога FanFox.')
            target = query_url(self.ROOT + '/search', title=query, genres=tag, nogenres='', sort='', stype=1, page=page)
            cards = self.layout.search.cards
        else:
            target = self.layout.popular.url(self.ROOT, page, query, tag)
            if sort == 'updated':
                target += '?latest'
            cards = self.layout.cards
        return self.card_rows(*self.document(http, target), cards)

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/search')
        rows = {}
        for node in doc.select('input[name="genre"][value], input[name="genres"][value]'):
            key, label = node['value'], node_text(node.parent)
            if re.fullmatch(r'[1-9]\d{0,5}', key) and label:
                rows[key] = {'label': label, 'sourceId': key, 'category': 'genre'}
        return list(rows.values())

    def pages(self, http, url):
        wire = 'https://m.fanfox.net' + urlsplit(url).path.replace('/manga/', '/roll_manga/', 1)
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(wire, headers={'Referer': 'https://m.fanfox.net/'}, action='fanfox-reader')
        if urlsplit(final).hostname != 'm.fanfox.net' or urlsplit(final).path.rstrip('/') != urlsplit(wire).path.rstrip('/'):
            raise SourceError('FanFox перенаправил запрос на другую главу.')
        from bs4 import BeautifulSoup

        doc = BeautifulSoup(raw, 'html.parser')
        return [picture(node, final, ('data-original',)) for node in doc.select(self.layout.reader)]


class ManhwaRead(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/manhwa/{SLUG}/?', rf'/manhwa/{SLUG}/(?:{SEGMENT}/){{0,2}}{SEGMENT}/?',
            Cards('.main-container .manga-item', 'a.manga-item__link[href]', cover='.manga-item__img img', next='.wp-pagenavi a.last'),
            Meta('#mangaSummary .manga-titles h1', 'head meta[property="og:image"]', '#mangaDesc > .manga-desc__content',
                 '#mangaSummary .manga-titles h2', '#mangaSummary .manga-genres a',
                 '#mangaSummary .text-primary:-soup-contains("Tags:") + .flex a span:first-child',
                 '#mangaSummary .text-primary:-soup-contains("Author:") + .flex a span:first-child'),
            Archive('#chaptersList > a.chapter-item[href]', anchor='', title='span.chapter-item__name',
                    date='span.chapter-item__date', date_pattern='%d/%m/%Y'),
            '', Browse('/page/{page}/', first_path='/'), title_path='/manhwa/', suffix='/',
        ))
        self.legacy_hosts = {'manhwaread.com', 'manhwaread.org'}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        url = self.layout.popular.url(self.ROOT, page, query, tag)
        args = {'s': query, 'sortby': 'release' if sort == 'updated' else 'weekly_top', 'order': 'desc'}
        if tag:
            taxonomy, _, key = tag.partition(':')
            if taxonomy not in {'genre', 'tag'} or not re.fullmatch(r'[1-9]\d{0,6}', key):
                raise SourceError('Некорректная метка каталога.')
            args['genre[]' if taxonomy == 'genre' else 'including[]'] = key
        return self.card_rows(*self.document(http, query_url(url, **args)), self.layout.cards)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        status = doc.select_one('#mangaSummary .manga-status[data-status]')
        row['status'] = status['data-status'] if status else ''
        row['artists'] = unique(node_text(node) for node in doc.select(
            '#mangaSummary .text-primary:-soup-contains("Artist:") + .flex a span:first-child'))
        return row

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        decoder = json.JSONDecoder()
        for script in doc.select('script'):
            text = script.string or ''
            match = re.search(r'\bvar\s+chapterData\s*=\s*(?=\{)', text)
            if match is None:
                continue
            try:
                data, _ = decoder.raw_decode(text, match.end())
                base = image_url(data['base'], final).rstrip('/') + '/'
                rows = json.loads(base64.b64decode(data['data'], validate=True))
                if not isinstance(rows, list) or base == '/':
                    raise ValueError('Invalid pages')
                return [image_url(row['src'], base) for row in rows]
            except (KeyError, TypeError, ValueError, binascii.Error, RecursionError):
                raise SourceError('Источник изменил формат страниц ManhwaRead.') from None
        raise SourceError('Источник не предоставил список страниц главы.')


class NewManhwa(DirectCatalogue):
    def __init__(self, identity):
        path = rf'/(?:en/)?series/{SLUG}/?'
        super().__init__(identity, Layout(
            path, rf'/(?:en/)?series/{SLUG}/chapter-{SEGMENT}/?',
            Cards('article.series-card', 'a.series-card-cover[href]', 'div.series-card-body h2 a',
                  cover='a.series-card-cover img', next='a:-soup-contains("Next"):not(.disabled)'),
            Meta('h1', 'aside.series-left .cover-card img', 'div.series-v72-description',
                 genres='div.series-v72-genres a',
                 author='aside.series-v72-sidebar .series-v72-meta span:-soup-contains-own("Author") + strong',
                 status='aside.series-v72-sidebar .series-v72-meta span:-soup-contains-own("Status") + strong'),
            Archive('div.series-v72-chapter-list a.series-v72-chapter-row[href]:not(:has(.chapter-mini-lock))', anchor='',
                    title='.series-chapter-number-text', date='time.series-chapter-date'),
            '.reader-pages img', Browse('/popular', (('page', '{page}'),)),
            Browse('/series', (('q', '{query}'), ('page', '{page}'))), Browse('/latest', (('page', '{page}'),)),
            Browse('/series', (('genre', '{tag}'), ('page', '{page}'))), title_path='/series/',
            tag_index='/en/genres', tag_anchor='a.panel.genre-card[href]',
        ))
        self.legacy_hosts = {'saymanhwa.com'}

    def title_for(self, url):
        return url.rsplit('/', 1)[0] if not url.endswith('/') else url.rstrip('/').rsplit('/', 1)[0]

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        route = self.layout.search if query else self.layout.browse_tag if tag else self.layout.latest if sort == 'updated' else self.layout.popular
        doc, final = self.document(http, route.url(self.ROOT, page, query, tag))
        if query and self.is_title(final) and doc.select_one('aside.series-left'):
            return [self.metadata(doc, final, self.meta)], False
        rows, more = self.card_rows(doc, final, self.layout.cards)
        for row in rows:
            row['title'] = re.sub(r'^#\d+\s+', '', row['title'])
        return rows, more

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row['description'] = re.split(r'\s+(?:Tags|Keywords):', row['description'], maxsplit=1, flags=re.I)[0]
        row['format'], row['readingMode'] = 'manhwa', 'scroll'
        return row
