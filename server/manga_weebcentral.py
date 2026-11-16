"""WeebCentral HTML search, series catalogue and long-strip chapter frames."""

import re
from urllib.parse import urlsplit

from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Cards, Meta, picture
from manga_webcomics import query_url
from source_parser import SourceError


KEY = r'[A-Za-z0-9]{8,40}'
SERIES = rf'/series/({KEY})/{SEGMENT}/?'
CHAPTER = rf'/chapters/({KEY})/?'
PAGE_SIZE = 32
CARD = Cards('article > section > a[href]', '', 'div:not([class]):last-child', next='button[hx-get], button[hx-post]')
DETAIL = Meta('section[x-data] > section h1', 'section[x-data] > section img',
              'li:has(> strong:-soup-contains("Description")) > p',
              tags='ul > li:has(> strong:-soup-contains("Tag")) a',
              author='ul > li:has(> strong:-soup-contains("Author")) > span > a',
              status='ul > li:has(> strong:-soup-contains("Status")) > a')
SORT = {'popular': 'Popularity', 'updated': 'Latest Updates'}


class WeebCentral(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, SERIES, CHAPTER, interval=2)

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(self.title_for(url))

    def title_for(self, url):
        from manga_webcomics import param
        parent = param(url, 'mv_parent')
        return self.ROOT + parent if re.fullmatch(SERIES, parent) else ''

    def cover(self, node, base):
        src = node.select_one('source[srcset]')
        srcset = src['srcset'].split() if src else []
        if srcset:
            return image_url(srcset[0].replace('/small/', '/normal/'), base)
        return picture(node.select_one('img'), base)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        cleaned = re.sub(r'[^\w\s-]', ' ', query).strip()
        args = {'text': cleaned, 'sort': 'Best Match' if cleaned else SORT.get(sort, 'Popularity'),
                'order': 'Descending', 'official': 'Any', 'anime': 'Any', 'adult': 'Any',
                'limit': PAGE_SIZE, 'offset': (page - 1) * PAGE_SIZE, 'display_mode': 'Full Display'}
        if tag:
            args['included_tag'] = tag[:120]
        doc, final = self.document(http, query_url(self.ROOT + '/search/data', **args))
        rows, more = self.card_rows(doc, final, CARD)
        covers = {self.site_link(node['href'], final): self.cover(node, final) for node in doc.select(CARD.rows)}
        for row in rows:
            row['cover'] = covers.get(self.site_link(row['sourceUrl']), row['cover'])
        return rows, more or bool(rows and doc.select_one('button:has([hx-get]), button[onclick]'))

    def details(self, http, url):
        url = self.saved_title_url(url)
        if not self.is_title(url):
            raise SourceError('Некорректная ссылка на карточку WeebCentral.')
        doc, final = self.title_document(http, url)
        row = self.metadata(doc, final, DETAIL)
        header = doc.select_one('section[x-data] > section')
        if header:
            row['cover'] = self.cover(header, final)
        aliases = [node_text(node) for node in doc.select('li:has(> strong:-soup-contains("Associated Name")) li')]
        row['aliases'] = list(dict.fromkeys([*row['aliases'], *aliases]))
        form = node_text(doc.select_one('li:has(> strong:-soup-contains("Type")) a'))
        if form:
            row['format'] = form.casefold()
        return row

    def series(self, http, url):
        row = self.details(http, url)
        title = self.site_link(row['sourceUrl'])
        parent = urlsplit(title).path
        outline = self.ROOT + '/series/' + self.title_key(title) + '/full-chapter-list'
        doc, final = self.document(http, outline)
        if urlsplit(final).path != urlsplit(outline).path:
            raise SourceError('Источник перенаправил запрос на другое оглавление.')
        chapters = {}
        for node in doc.select('div[x-data] > a[href]'):
            url = self.site_link(node['href'], final)
            if not re.fullmatch(CHAPTER, urlsplit(url).path):
                continue
            label = node_text(node.select_one('span.flex > span'))
            when = node.select_one('time[datetime]')
            official = any('official' in img.get('src', '').lower() for img in node.select('img'))
            target = query_url(url, mv_parent=parent)
            chapters[target] = self.chapter(target, label, date=when['datetime'][:10] if when else '',
                                            translator='Official' if official else '')
        return row, self.order(chapters)

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if re.fullmatch(CHAPTER, urlsplit(target).path) and self.is_title(title):
            return query_url(target.split('?')[0], mv_parent=urlsplit(title).path)
        return ''

    def saved_chapter_matches(self, target, title):
        return bool(self.title_key(title) and self.title_key(title) == self.title_key(self.title_for(target)))

    def pages(self, http, url):
        root = self.ROOT + '/chapters/' + self.chapter_key(url) + '/images'
        endpoint = query_url(root, is_prev='False', reading_style='long_strip')
        doc, final = self.document(http, endpoint)
        if urlsplit(final).path != urlsplit(root).path:
            raise SourceError('Источник перенаправил запрос на другую главу.')
        return [picture(node, final) for node in doc.select('section[x-data*="scroll"] > img[src]')]
