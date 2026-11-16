"""Language-specific YellowNote catalogues and public album paging."""

import re
from urllib.parse import quote, urlsplit

from manga_madara import SEGMENT, node_text
from manga_series_port import Cards, Meta, SeriesPort, picture

PROFILES = (
    ('170542391855030753', 'zh-Hans', 'xchina.co'),
    ('4899554363948814001', 'zh-Hant', 'tw.xchina.co'),
    ('6844007153169388830', 'en', 'en.xchina.co'),
    ('385228898502560286', 'es', 'es.xchina.co'),
    ('7263133157381353850', 'ko', 'kr.xchina.co'),
)
ALBUM = rf'/(?:photos?|amateurs?|album)/({SEGMENT})'
DETAIL = 'div.info-card.photo-detail'


class YellowNote(SeriesPort):
    meta = Meta('h1', 'meta[property="og:image"]')
    cards = Cards('div.list.photo-list > div.item.photo, div.list.amateur-list > div.item.amateur',
                  'a[title][href]', cover='div.img', next='div.pager a.next', title_attr='title')

    def __init__(self, identity, language, host):
        super().__init__((identity, '小黄书', language, 'https://' + host, True),
                         ALBUM + r'\.html', ALBUM + r'/[1-9]\d{0,3}\.html', interval=.35)

    def title_for(self, url):
        return self.ROOT + urlsplit(url).path.rsplit('/', 1)[0] + '.html' if self.is_chapter(url) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        part = '/photos'
        if query:
            part += '/keyword-' + quote(query, safe='')
        elif re.fullmatch(r'(?:album-[1-9]\d?|series-[a-f\d]{13})', tag):
            part += '/' + tag
        elif sort != 'updated':
            part += '/sort-hot'
        return self.card_rows(*self.document(http, f'{self.ROOT}{part}/{page}.html'), self.cards)

    def info(self, doc, icon):
        return doc.select_one(f'{DETAIL} div.item:has(.icon > i.{icon}) div.text')

    def metadata(self, doc, url, spec):
        title = ' '.join(filter(None, (node_text(self.info(doc, 'fa-address-card')), node_text(self.info(doc, 'fa-file')))))
        cover = doc.select_one('meta[property="og:image"]')
        genres = [node_text(n) for n in doc.select(f'{DETAIL} div.item:has(i.fa-video-camera) div.text > *') if node_text(n) != '-']
        tags = [node_text(n) for icon in ('fa-filter', 'fa-tags') for n in
                doc.select(f'{DETAIL} div.item:has(i.{icon}) div.text > *')]
        creator = node_text(doc.select_one(f'{DETAIL} div.item.floating')) or node_text(self.info(doc, 'fa-circle-user'))
        return self.record(url, title or node_text(doc.select_one('h1')) or self.title_key(url),
                           picture(cover, url, ('content',)), genres=genres, tags=tags, authors=[creator], status='completed')

    def chapters(self, http, doc, final):
        date = node_text(self.info(doc, 'fa-calendar-days'))
        if not date:
            date = node_text(doc.select_one('div.tab-content > div.info-card div.text'))
        match = re.search(r'\d{4}\.\d{2}\.\d{2}', date)
        date = match[0].replace('.', '-') if match else ''
        pager = doc.select_one('div.pager')
        links = pager.select('a.pager-num') if pager else ()
        count = max((int(node_text(a)) for a in links if re.fullmatch(r'\d{1,4}', node_text(a))), default=1)
        return [self.chapter(f'{final.removesuffix(".html")}/{i}.html', f'Page {i}', i, date)
                for i in range(1, min(count, 1000) + 1)], count > 1000

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        return [src.replace('_600x0.webp', '.jpg') for n in doc.select(
            'div.list.photo-items > div.item.photo-image div.img[style], '
            'div.list.amateur-items > div.item.amateur-image div.img[style]') if (src := picture(n, final))]


SOURCES = tuple(YellowNote(*row) for row in PROFILES)
