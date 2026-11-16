"""momon:GA WordPress gallery listings."""

import re
from urllib.parse import urlsplit

from manga_madara import SEGMENT, node_text, release_date
from manga_series_port import Cards, Meta, SeriesPort, picture
from manga_webcomics import param, query_url

ROOT = 'https://momon-ga.com'
ENTRY = rf'/({SEGMENT}(?:/{SEGMENT}){{0,3}})/?'
GROUPS = {'fanzine': '同人誌', 'magazine': '商業誌', 'trend': '急上昇', 'popularity': '人気', 'rated': '高評価'}
BROWSE = {*GROUPS, 'page', 'tag', 'category', 'author', 'wp-admin', 'wp-json'}


class Momonga(SeriesPort):
    cards = Cards('div.post-list > a[href]', '', 'span', 'div.post-list-image > img',
                  next='div.wp-pagenavi > a.nextpostslink[href]')
    meta = Meta('#post-data > h1', '#post-hentai > img', '',
                tags='#post-tag div.post-tag-table:has(div.post-tag-title:-soup-contains-own("内容")) div.post-tags > a',
                author='#post-tag div.post-tag-table:has(div.post-tag-title:-soup-contains-own("作者"), '
                       'div.post-tag-title:-soup-contains-own("サークル")) div.post-tags > a')

    def __init__(self):
        super().__init__(('5332628982027198645', 'momon:GA', 'ja', ROOT, True),
                         ENTRY, ENTRY, interval=.35)

    def is_title(self, url):
        return self.is_chapter(url) and param(url, 'mv_momon_reader') != '1'

    def is_chapter(self, url):
        return super().is_chapter(url) and self.chapter_key(url).split('/', 1)[0] not in BROWSE

    def title_for(self, url):
        path = urlsplit(url).path
        return ROOT + path if self.is_chapter(url) else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        return query_url(url, mv_momon_reader=1) if self.is_chapter(url) else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(target) == self.title_key(title)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        path = '' if query else '/' + (tag if tag in GROUPS else 'trend' if sort == 'updated' else 'popularity')
        if page > 1:
            path += f'/page/{page}'
        path += '/'
        url = query_url(ROOT + path, s=query) if query else ROOT + path
        return self.card_rows(*self.document(http, url), self.cards)

    def vocabulary(self, http):
        return [{'key': key, 'label': name, 'kind': 'category'} for key, name in GROUPS.items()]

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row.update(status='completed', format='gallery')
        return row

    def chapters(self, http, doc, final):
        stamp = node_text(doc.select_one('#post-time'))
        match = re.search(r'\d{4}年\d{1,2}月\d{1,2}日', stamp)
        date = release_date(match[0], '%Y年%m月%d日') if match else ''
        return [self.chapter(query_url(final, mv_momon_reader=1), '単一章', 1, date=date)], False

    def pages(self, http, url):
        doc, final = self.page_document(http, self.title_for(url))
        return [src for image in doc.select('#post-hentai > img') if (src := picture(image, final))]


SOURCES = (Momonga(),)
