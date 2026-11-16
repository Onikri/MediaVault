"""Multporn Drupal catalogues and Juicebox gallery metadata."""

import re
from urllib.parse import quote, urlsplit

from manga_madara import SEGMENT, node_text
from manga_series_port import Cards, Meta, SeriesPort, picture
from manga_webcomics import param, query_url

ROOT = 'https://multporn.net'
SECTIONS = ('category', 'characters', 'authors_comics', 'comics', 'category_hentai', 'characters_hentai',
            'authors_hentai_comics', 'hentai_manga', 'authors_albums', 'pictures', 'hentai', 'rule_63',
            'category_gay')
PAGE = rf'/((?:comics|hentai_manga|pictures|hentai|rule_63|gay_comics|albums|node|sfw)/{SEGMENT}(?:/{SEGMENT})?)/?'
TYPES = {'1', '2', '3', '4', '5', '10', '11', '13'}


class Multporn(SeriesPort):
    cards = Cards('.masonry-item', '.views-field-title a[href]', '.views-field-title', 'img',
                  next='.pager-next a[href]')
    alternate_cards = Cards('#content .col-1:-soup-contains("Views:"), #content .col-2:-soup-contains("Views:")',
                            '.views-field-title a[href]', '.views-field-title', 'img',
                            next='.pager-next a[href]')
    meta = Meta('h1#page-title', '.jb-image img', '', '',
                '.field:has(.field-label:-soup-contains-own("Section:")) .links a',
                '.field:has(.field-label:-soup-contains-own("Tags:")) .links a, '
                '.field:has(.field-label:-soup-contains-own("Characters:")) .links a',
                '.field:has(.field-label:-soup-contains-own("Author:")) .links a, '
                '.field-name-field-author a, .field-name-field-authors-gr a, .field-name-field-img-group a, '
                '.field-name-field-hentai-img-group a, .field-name-field-rule-63-section a')

    def __init__(self):
        super().__init__(('1483013328567191791', 'Multporn', 'en', ROOT, True),
                         PAGE, PAGE, hosts=('www.multporn.net',), interval=.35)

    def is_title(self, url):
        return super().is_title(url) and param(url, 'mv_multi_gallery') != '1'

    def title_for(self, url):
        path = urlsplit(url).path
        return ROOT + path if self.is_chapter(url) else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        return query_url(url, mv_multi_gallery=1) if self.is_chapter(url) else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(target) == self.title_key(title)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        kind, _, value = tag.partition(':')
        if kind in SECTIONS and value:
            target = query_url(ROOT + '/' + kind + '/' + quote(value[:160].replace(' ', '-'), safe=''), page=f'0,{page-1}')
            return self.card_rows(*self.document(http, target), self.alternate_cards)
        source = value if kind == 'type' and value in TYPES else '1'
        args = {'page': page - 1, 'type': source}
        if query:
            path = '/search'
            args.update(search_api_views_fulltext=query, sort_by='search_api_relevance')
        else:
            path = '/new' if sort == 'updated' else '/best'
            args.update(sort_by='created' if sort == 'updated' else 'totalcount_1', sort_order='DESC')
        return self.card_rows(*self.document(http, query_url(ROOT + path, **args)), self.cards)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row['status'] = 'ongoing' if 'Ongoings' in row['genres'] else 'completed'
        paragraphs = [', '.join(row['genres']), f'{len(doc.select(".jb-image img"))} pages']
        row['description'] = '\n\n'.join(filter(None, paragraphs))
        return row

    def chapters(self, http, doc, final):
        return [self.chapter(query_url(final, mv_multi_gallery=1), 'Chapter', 1)], False

    def pages(self, http, url):
        doc, final = self.page_document(http, self.title_for(url))
        result = []
        for node in doc.select('.jb-image img'):
            src = picture(node, final)
            if src:
                result.append(src.replace('/styles/juicebox_2k/public', '').split('?', 1)[0])
        return list(dict.fromkeys(result))


SOURCES = (Multporn(),)
