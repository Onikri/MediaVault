"""Honto public shop catalogue and guest browser reading."""

import json
import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_clipstudio import endpoint, viewer_pages
from manga_direct_payloads import JsonSeries
from manga_madara import image_url, node_text, release_date
from manga_series_port import Meta
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://honto.jp'
ID = r'\d{5,16}'
TITLE = rf'/ebook/pd-series_({ID})\.html'
CHAPTER = rf'/ebook/pd_({ID})\.html'
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36')
GENRES = {'29004000000': '漫画・コミック', '29004150000': '男性向けコミック', '29004160000': '女性向けコミック',
          '29037000000': 'ライトノベル', '29001000000': '小説・文学', '29004140000': 'メンズラブ',
          '29029000000': 'BL(ボーイズラブ)', '29039000000': 'TL(ティーンズラブ)'}


def doc_route(value, method, data):
    parsed = urlsplit(value)
    if parsed.netloc != 'honto.jp' or data is not None:
        return False
    if method == 'HEAD':
        return parsed.path == '/' and not parsed.query
    if method != 'GET':
        return False
    if re.fullmatch(TITLE, parsed.path):
        return not parsed.query
    filters = parse_qsl(parsed.query, keep_blank_values=True)
    args = dict(filters)
    if len(args) != len(filters):
        return False
    if parsed.path == '/ebook/search_0750_09-srsdspodr.html':
        return (set(args) <= {'srsid', 'adtDisp', 'pgno'} and bool(re.fullmatch(ID, args.get('srsid', '')))
                and args.get('adtDisp') == '1' and bool(re.fullmatch(r'[1-9]\d{0,3}', args.get('pgno', '1'))))
    return (bool(re.fullmatch(r'/ebook/search_0750(?:_02\d{11})?(?:_09-(?:salesnum30d|saledate))?\.html', parsed.path))
            and {'unt', 'pgno'} <= set(args) <= {'unt', 'pgno', 'k'} and args['unt'] == '1'
            and bool(re.fullmatch(r'[1-9]\d{0,3}', args['pgno'])) and len(args.get('k', '')) <= 160)


def public_form(value, data):
    if value != ROOT + '/view_interface.php' or not isinstance(data, dict):
        return False
    identifier = data.get('itemId')
    return (isinstance(identifier, str) and bool(re.fullmatch(ID, identifier))
            and data == {'className': 'PrdDisplayElectronicBookProductSpecificationPc',
                         'redirectToUrl': ROOT + f'/ebook/pd_{identifier}.html',
                         'browserFreeReading': '1', 'itemId': identifier})


class Honto(JsonSeries):
    meta = Meta('h1.stTitle', '#product-detail__main-image img', 'p.accordion-more-info__content',
                genres='#stTopicPath a[href*="/ebook/gr/"]', author='p.stAuthor a')
    products = 'div.stBoxLine01 > div.stProduct02'

    def __init__(self):
        super().__init__(('4717734884893722363', 'Honto', 'ja', ROOT, True), TITLE, CHAPTER, interval=.45)

    def title_for(self, url):
        identifier = param(url, 'mv_honto_series')
        return ROOT + f'/ebook/pd-series_{identifier}.html' if self.is_chapter(url) and re.fullmatch(ID, identifier) else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_for(target) == title

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        return ROOT + f'/ebook/pd-series_{key}.html' if re.fullmatch(ID, key) else url if self.is_title(url) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = urlsplit(url).path.strip('/')
        if re.fullmatch(ID, key):
            url = ROOT + f'/ebook/pd_{key}.html'
        return query_url(url, mv_honto_series=self.title_key(title)) if self.is_chapter(url) and self.is_title(title) else ''

    def document(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        headers = {'Referer': ROOT + '/', 'User-Agent': USER_AGENT}
        try:
            content, final, _ = http.document(url, headers=headers, action='honto-public')
        except SourceAccessError:
            response, _ = http._open(ROOT + '/', method='HEAD', headers=headers, action='honto-public')
            response.close()
            content, final, _ = http.document(url, headers=headers, action='honto-public')
        if urlsplit(final).netloc != 'honto.jp' or urlsplit(final).path != urlsplit(url).path:
            raise SourceError('Honto перенаправил запрос на другую страницу.')
        return BeautifulSoup(content, 'html.parser'), final

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        genre = '_02' + tag if tag in GENRES else ''
        order = '' if query else '_09-' + ('saledate' if sort == 'updated' else 'salesnum30d')
        dest = query_url(ROOT + '/ebook/search_0750' + genre + order + '.html', unt=1, pgno=page, k=query or [])
        doc, final = self.document(http, dest)
        rows = {}
        for item in doc.select(self.products):
            link = item.select_one('a.dyTitle[href]')
            name = node_text(link)
            if not name:
                continue
            image = item.select_one('img.dyImage')
            cover = image_url(image.get('data-src') or image.get('src'), final) if image else ''
            identity = urlsplit(cover).path.rsplit('/', 1)[-1].split('_', 1)[0]
            target = self.site_link(link['href'], final)
            if not self.is_title(target) and re.fullmatch(ID, identity):
                target = ROOT + f'/ebook/pd-series_{identity}.html'
            if self.is_title(target):
                rows[target] = self.record(target, name, cover)
        return list(rows.values()), bool(rows and doc.select_one('ul.stPager li.stNext a'))

    def vocabulary(self, http):
        return [{'key': key, 'label': label, 'kind': 'category'} for key, label in GENRES.items()]

    def listed_volumes(self, http, key):
        url = query_url(ROOT + '/ebook/search_0750_09-srsdspodr.html', srsid=key, adtDisp=1)
        first, final = self.document(http, url)
        last = max((int(raw) for anchor in first.select('ul.stPager li a')
                    if re.fullmatch(r'\d{1,3}', raw := node_text(anchor))), default=1)
        for page in range(1, min(last, 80) + 1):
            doc, ref = (first, final) if page == 1 else self.document(http, query_url(url, pgno=page))
            for product in doc.select(self.products):
                link = product.select_one('a.dyTitle[href]')
                target = self.site_link(link['href'], ref) if link else ''
                if self.is_chapter(target):
                    browser = any(node_text(node) == 'ブラウザ' for node in product.select('ul.stIcon01 li'))
                    free = browser and node_text(product.select_one('span.dyPrice')) == '0'
                    raw = node_text(product.select_one('ul.stData li:-soup-contains("販売開始日")')).split('：')[-1].strip()
                    yield (query_url(target, mv_honto_series=key), node_text(link), free,
                           release_date(raw, '%Y/%m/%d'))

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        row = self.metadata(doc, final, self.meta)
        row['status'] = 'completed' if doc.select_one('.product-info-icon-area__conclusion-icon') else 'ongoing'
        chapters = {}
        for target, name, free, stamp in self.listed_volumes(http, self.title_key(url)):
            chapters[target] = self.chapter(target, name if free else '🔒 ' + name, date=stamp)
        return row, self.order(chapters)

    def pages(self, http, url):
        title = self.title_for(url)
        cid = self.chapter_key(url)
        if not any(free and self.chapter_key(candidate) == cid
                   for candidate, _, free, _ in self.listed_volumes(http, self.title_key(title))):
            raise SourceAccessError('Honto требует покупку тома.')
        data = {'className': 'PrdDisplayElectronicBookProductSpecificationPc',
                'redirectToUrl': ROOT + f'/ebook/pd_{cid}.html', 'browserFreeReading': '1', 'itemId': cid}
        headers = {'Referer': data['redirectToUrl'], 'User-Agent': USER_AGENT}
        raw, _, _ = http.document(ROOT + '/view_interface.php', headers=headers, method='POST', data=data, action='honto-view')
        try:
            reader = json.loads(raw).get('url')
        except (AttributeError, ValueError):
            reader = None
        if not isinstance(reader, str) or not reader:
            raise SourceAccessError('Honto не предоставил открытый том.')
        return viewer_pages(http, endpoint(reader, ROOT + '/'), url)


SOURCES = (Honto(),)
