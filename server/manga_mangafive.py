"""Manga-5 catalogue, episodic publications, and two open Publus formats."""

import re
from urllib.parse import parse_qsl, quote, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_madara import node_text, release_date
from manga_publus_reader import plain_content_pack, reader_pages, signed_content
from manga_publus_sources import BOOST_CHAPTER, BOOST_TITLE, CID, KEY
from manga_series_port import Cards, Meta, SeriesPort
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://manga-5.com'
LICENSE = ROOT + '/api4js/contents/license'
GENRES = ('オリジナル作品', '妖怪ウォッチシリーズ', 'レベルファイブ作品')
CLICK = re.compile(r'''['"]([^'"]+cid=[^'"]+)['"]''')


def public_api(host, path, query):
    args = parse_qsl(query)
    return (host == 'manga-5.com' and path == '/api4js/contents/license' and len(args) == 1
            and args[0][0] == 'cid' and bool(re.fullmatch(CID, args[0][1])))


class MangaFive(JsonSeries):
    pager = '.pagination-list-item.to-next:not(.disabled)'
    cards = Cards('a.book-list-item[href]', '', 'h3.title', 'img.thum', pager, image_attrs=('data-src',))
    meta = Meta('.comic-main-right-detail h1.comic-title', '.comic-main-thum-wrapper img', '.comic-discription-text',
                author='.comic-main-right-detail .author-list .author')

    def __init__(self):
        super().__init__(('8712903623054427832', 'Manga-5', 'ja', ROOT, False), BOOST_TITLE, BOOST_CHAPTER, interval=.4)

    def title_for(self, url):
        key = param(url, 'mv_manga5_title')
        return ROOT + '/content/' + key if self.is_chapter(url) and re.fullmatch(KEY, key) else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        return ROOT + '/content/' + key if re.fullmatch(KEY, key) else url if self.is_title(url) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = self.chapter_key(url) if self.is_chapter(url) else urlsplit(url).path.strip('/')
        return query_url(ROOT + '/product/' + key, mv_manga5_title=self.title_key(title)) if (
            self.is_title(title) and re.fullmatch(KEY, key)) else ''

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            url = query_url(ROOT + '/search', k=query, p=page, order='desc')
        elif tag in GENRES:
            url = query_url(ROOT + '/genre/' + quote(tag), p=page, order='desc')
        elif sort == 'updated':
            url = query_url(ROOT + '/series', p=page)
        else:
            if page != 1:
                return [], False
            url = ROOT + '/ranking'
        return self.card_rows(*self.document(http, url), self.cards)

    def vocabulary(self, http):
        return [{'key': label, 'label': label, 'kind': 'genre'} for label in GENRES]

    def series(self, http, url):
        first, final = self.title_document(http, url)
        row = self.metadata(first, final, self.meta)
        row['status'] = 'completed' if '完結' in row['title'] else 'ongoing'
        key = self.title_key(final)
        result = {}
        for page in range(1, 81):
            doc = first if page == 1 else self.document(http, query_url(final, p=page))[0]
            for item in doc.select('a.book-product-list-item[data-id]'):
                chapter = item['data-id']
                if not re.fullmatch(KEY, chapter):
                    continue
                locked = 'js-read' in item.get('class', ())
                url = query_url(ROOT + '/product/' + chapter, mv_manga5_title=key, mv_manga5_locked='1' if locked else [])
                name = node_text(item.select_one('h4.title'))
                raw = node_text(item.select_one('p.update-date')).split(' ', 1)[0]
                result[url] = self.chapter(url, ('🔒 ' if locked else '') + name, date=release_date(raw, '%Y/%m/%d'))
            if not doc.select_one(self.pager):
                break
        return row, self.order(result)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            return SeriesPort.inspect(self, url, http)
        return super().inspect(url, http)

    def pages(self, http, url):
        if param(url, 'mv_manga5_locked'):
            raise SourceAccessError('Manga-5 ограничивает доступ к выпуску.')
        referer = self.title_for(url) or ROOT + '/'
        target = ROOT + '/product/' + self.chapter_key(url)
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(target, headers={'Referer': referer})
        if urlsplit(final).netloc != 'manga-5.com':
            raise SourceError('Manga-5 перенаправил на другой домен.')
        if urlsplit(final).path.endswith('/ads_before_launching_viewer.html'):
            button = BeautifulSoup(raw, 'html.parser').select_one('button[onclick]')
            match = CLICK.search(button['onclick']) if button else None
            final = match[1] if match else ''
        cid = param(final, 'cid')
        if not re.fullmatch(CID, cid):
            raise SourceAccessError('Manga-5 не предоставил открытый выпуск.')
        reply = self.json(http, query_url(LICENSE, cid=cid), referer)
        if reply.get('cty') == 3:
            raise SourceAccessError('Издатель предоставляет только текстовое издание.')
        base, auth = signed_content(reply, url)
        return plain_content_pack(http, base, url, auth) if reply.get('cty') == 6 else reader_pages(http, base, url, auth=auth)


SOURCES = (MangaFive(),)
