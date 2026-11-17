"""Docomo series shelf and guest Publus reader session."""

import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_clipstudio import json_data
from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, node_text
from manga_publus_reader import reader_pages
from manga_series_port import Cards, Meta, SeriesPort
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://dbook.docomo.ne.jp'
API = 'https://dxp-system.docomo.ne.jp/element/seriesshelf/get_contents'
SESSION = 'https://rs4x.mw-pf.jp/responder/sessionValidate'
ID = r'[A-Za-z0-9_.~-]{1,180}'
SID = r'[A-Za-z0-9._~+/%=-]{1,2048}'
TITLE = rf'/item/({SEGMENT})(?:/({ID}))?/?'
VIEWER = '/view/'
CHAPTER = r'(/view)/?'


def public_api(host, path, query):
    pairs = parse_qsl(query)
    args = dict(pairs)
    return (host == 'dxp-system.docomo.ne.jp' and path == '/element/seriesshelf/get_contents' and len(pairs) == len(args)
            and set(args) == {'seriesId', 'order', 'page'} and args['order'] == 'a'
            and bool(re.fullmatch(ID, args['seriesId'])) and bool(re.fullmatch(r'[1-9]\d{0,3}', args['page'])))


def public_form(url, body, referer):
    ref = urlsplit(referer)
    return (url == SESSION and ref.netloc == 'dbook.docomo.ne.jp' and ref.path.rstrip('/') == '/view'
            and isinstance(body, dict) and set(body) == {'cid', 'sesid'}
            and isinstance(body['cid'], str) and bool(re.fullmatch(ID, body['cid']))
            and param(referer, 'cid') == body['cid'] and isinstance(body['sesid'], str)
            and bool(re.fullmatch(SID, body['sesid'])))


class Docomo(JsonSeries):
    cards = Cards('.o-ranking-list__item, .o-card-list-light__item', 'a[href*="/item/"]',
                  '.m-basic-card__title, .m-card-light__title', 'img.cd-cover',
                  '.m-pager__next:not([style*="display"]) a, .m-pager__list li.-current + li:not([style*="display"]) a')
    meta = Meta('h1.p-header__title', '.p-cover__image img', '.o-product-information__summary-text',
                genres='.m-data-list__name:-soup-contains("ジャンル") + .m-data-list__data a',
                author='.p-information__author-list li a')

    def __init__(self):
        super().__init__(('2833994049092509182', 'Docomo', 'ja', ROOT, False), TITLE, CHAPTER, interval=.4)

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(re.fullmatch(ID, param(url, 'cid')))

    def title_for(self, url):
        key = param(url, 'mv_docomo_title')
        version = param(url, 'mv_docomo_version')
        if not self.is_chapter(url) or not re.fullmatch(SEGMENT, key):
            return ''
        return ROOT + '/item/' + key + ('/' + version if re.fullmatch(ID, version) else '') + '/'

    def chapter_key(self, url):
        return param(url, 'cid') if self.is_chapter(url) else ''

    def chapter_identity(self, url):
        return self.chapter_key(url)

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title))

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = self.chapter_key(url) or urlsplit(url).path.strip('/')
        return self.episode_url(title, key) if self.is_title(title) and re.fullmatch(ID, key) else ''

    def episode_url(self, title, cid, name=''):
        match = self.TITLE_PATH.fullmatch(urlsplit(title).path)
        return query_url(ROOT + VIEWER, cid=cid, cti=name[:180], cc='0000', mv_docomo_title=match[1],
                         mv_docomo_version=match[2] or [])

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            target = query_url(ROOT + '/search/', q=query, p=page, s='sort_seriespop', t=2, ss=1)
        else:
            target = query_url(ROOT + '/ranking/all/', s='daily', page=page)
        return self.card_rows(*self.document(http, target), self.cards)

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        record = self.metadata(doc, final, self.meta)
        series_id = doc.select_one('input#series_id[value]')
        if not series_id or not re.fullmatch(ID, identifier := series_id['value']):
            raise SourceError('Docomo не предоставил идентификатор серии.')
        chapters = {}
        for page in range(1, 81):
            result = self.json(http, query_url(API, seriesId=identifier, order='a', page=page), final)
            if not isinstance(html := result.get('html'), str):
                raise SourceError('Docomo изменил формат оглавления.')
            shelf = BeautifulSoup(html, 'html.parser')
            for entry in shelf.select('.o-series-list__card-item'):
                item = entry.select_one('.o-series-list__card[data-product_id]')
                if not item or not re.fullmatch(ID, cid := item['data-product_id']):
                    continue
                name = node_text(entry.select_one('.o-series-list__card-title'))
                target = self.episode_url(final, cid, name)
                chapters[target] = self.chapter(target, name)
            if result.get('hasNext') is not True:
                break
        return record, self.order(chapters)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            return SeriesPort.inspect(self, url, http)
        return super().inspect(url, http)

    def pages(self, http, url):
        chapter = self.chapter_key(url)
        target = query_url(ROOT + VIEWER, cid=chapter, cti=param(url, 'cti')[:180], cc='0000')
        doc, final = self.document(http, target)
        guest = doc.select_one('#mwrs4b-params[data-sesid]')
        if not guest or not re.fullmatch(SID, session := guest['data-sesid']):
            raise SourceAccessError('Docomo требует покупку выпуска.')
        raw, final_session, _ = http.document(SESSION, headers={'Referer': final}, method='POST',
                                              data={'cid': chapter, 'sesid': session}, action='docomo-reader')
        if final_session != SESSION:
            raise SourceError('Docomo перенаправил гостевой запрос.')
        value = json_data(raw).get('url')
        if not isinstance(value, str) or not value:
            raise SourceAccessError('Docomo не предоставил открытый выпуск.')
        return reader_pages(http, value, url)


SOURCES = (Docomo(),)
