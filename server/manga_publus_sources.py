"""Direct catalogues for Comic Boost, Comic Nettai and Pash Up!."""

from datetime import date
import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries, strings
from manga_madara import image_url, node_text, release_date
from manga_publus_reader import reader_pages
from manga_series_port import Cards, Meta, SeriesPort, number
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

BOOST = 'https://comic-boost.com'
NETTAI = 'https://www.comicnettai.com'
PASH = 'https://pash-up.jp'
KEY = r'[A-Za-z0-9_.~-]{1,100}'
CID = r'[A-Za-z0-9_+:~./=%-]{1,2048}'
BOOST_TITLE = rf'/content/({KEY})/?'
BOOST_CHAPTER = rf'/product/({KEY})/?'
NETTAI_TITLE = rf'/book/({KEY})/?'
NETTAI_CHAPTER = r'(/publus/viewer\.html)/?'
PASH_CHAPTER = rf'/content/({KEY})/read/({KEY})/?'


def public_api(host, path, query):
    pairs = parse_qsl(query)
    args = dict(pairs)
    if len(args) != len(pairs):
        return False
    if (host, path) in {('comic-boost.com', '/pageapi/viewer/c.php'),
                        ('www.comicnettai.com', '/api/viewer/c'), ('pash-up.jp', '/pageapi/viewer/c.php')}:
        return bool(set(args) == {'cid'} and re.fullmatch(CID, args['cid']))
    if host != 'pash-up.jp':
        return False
    action = args.get('type')
    if path == '/pageapi/contents.php' and action == 'search':
        return (set(args) == {'type', 'reserve', 'keyword', 'limit'} and args['reserve'] == '1'
                and args['limit'] == '9999' and 1 <= len(args['keyword']) <= 160)
    if path == '/pageapi/products.php' and action == 'contents':
        return (set(args) == {'type', 'id', 'limit', 'order'} and args['limit'] == '9999'
                and args['order'] == 'nodesc' and bool(re.fullmatch(KEY, args['id'])))
    offset = args.pop('offset', '')
    if not re.fullmatch(r'\d{1,6}', offset):
        return False
    common = {'period': 'daily', 'category': '2', 'limit': '10'}
    return ((path == '/pageapi/contents.php' and args == {'type': 'ranking', **common}) or
            (path == '/pageapi/products.php' and args == {'type': 'update', 'unit': '2', 'lastest': '1', **common}))


class PublusCatalogue(JsonSeries):
    def read(self, http, url, route, cid, referer=None):
        if not re.fullmatch(CID, cid):
            raise SourceAccessError('Издатель ограничивает доступ к этому выпуску.')
        target = query_url(self.ROOT + route, cid=cid)
        self.origin.wait(getattr(http, 'deadline', None))
        from manga_clipstudio import json_data

        raw, final, _ = http.document(target, headers={'Referer': referer or self.ROOT + '/'}, action='publus-source-json')
        if final != target:
            raise SourceError('Издатель перенаправил запрос читалки Publus.')
        data = json_data(raw)
        path = data.get('url')
        if not isinstance(path, str) or not path:
            raise SourceAccessError('Издатель не предоставил открытый выпуск Publus.')
        return reader_pages(http, path, url)


class PublusHtml(PublusCatalogue):
    def __init__(self, *, boost):
        self.boost = boost
        if boost:
            identity = ('1188951475836296058', 'Comic Boost', 'ja', BOOST, False)
            title, chapter = BOOST_TITLE, BOOST_CHAPTER
            self.next = '.pagination-list.right .to-next:not(.disabled) a[href]'
            self.cards = Cards('.book-list-item', '.book-list-item-thum-wrapper', '.title', 'img.thum',
                               self.next, image_attrs=('data-src',))
            self.meta = Meta('h1.comic-title', '.comic-main-thum-wrapper img', '.comic-description-text',
                             tags='.comic-main-right .tag-list .tag', author='.comic-main-right .author-list .author')
        else:
            identity = ('1398057210066455013', 'Comic Nettai', 'ja', NETTAI, False)
            title, chapter = NETTAI_TITLE, NETTAI_CHAPTER
            self.next = '.pagenation__item:not(.is-hidde) .pagenation__item__link--next[href]'
            self.cards = Cards('.full--comic__list .full--comic__item[href]', '', '.full--comic__title',
                               'img.full--comic__thum', self.next, image_attrs=('data-src',))
            self.meta = Meta('.detail--title', '.detail-catch__img', '.detail--discription',
                             author='.detail__author__item')
        super().__init__(identity, title, chapter, interval=.4)

    def is_chapter(self, url):
        return bool(super().is_chapter(url) and (self.boost or re.fullmatch(CID, param(url, 'cid'))
                                                or re.fullmatch(KEY, param(url, 'mv_product'))))

    def title_for(self, url):
        key = param(url, 'mv_publus_title')
        if not self.is_chapter(url) or not re.fullmatch(KEY, key):
            return ''
        return self.ROOT + ('/content/' if self.boost else '/book/') + key

    def chapter_identity(self, url):
        return self.chapter_key(url) if self.boost else param(url, 'mv_product') or param(url, 'cid')

    def saved_chapter_matches(self, url, title):
        return bool(self.is_chapter(url) and self.title_key(self.title_for(url)) == self.title_key(title))

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        key = urlsplit(target).path.strip('/')
        manga = self.title_key(title)
        if not self.is_chapter(target) and re.fullmatch(KEY, key):
            target = BOOST + '/product/' + key if self.boost else query_url(NETTAI + '/publus/viewer.html', mv_product=key)
        return query_url(target, mv_publus_title=manga) if manga and self.is_chapter(target) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if self.boost:
            target = query_url(BOOST + ('/search' if query else '/genre/'), p=page, k=query or [])
        else:
            target = query_url(NETTAI + ('/search' if query else '/series'), page=page, q=query or [])
        return self.card_rows(*self.document(http, target), self.cards)

    def document(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'}, action='publus-source-document')
        final = self.site_link(final)
        if not final:
            raise SourceError('Издатель перенаправил каталог Publus.')
        return BeautifulSoup(raw, 'html.parser'), final

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        summary = self.metadata(doc, final, self.meta)
        summary['authors'] = [re.sub(r'^(?:原作|漫画|作画|キャラクター原案|原案)：', '', name) for name in summary['authors']]
        episodes, visited = {}, set()
        manga = self.title_key(final)
        for _ in range(80):
            visited.add(final)
            if self.boost:
                for el in doc.select('.book-product-list-item[data-id]'):
                    product = el['data-id']
                    if not re.fullmatch(KEY, product):
                        continue
                    locked = el.select_one('.coin') is not None
                    name = node_text(el.select_one('.title'))
                    target = query_url(BOOST + '/product/' + product, mv_publus_title=manga,
                                       mv_publus_locked='1' if locked else [])
                    stamp = release_date(node_text(el.select_one('.update-date')), '%Y/%m/%d')
                    episodes[target] = self.chapter(target, ('🔒 ' if locked else '') + name, date=stamp)
            else:
                for el in doc.select('.detail--product__list a.detail--product__item[href]'):
                    image = el.select_one('.detail--product__thum')
                    carrier = urlsplit(image.get('data-src', '')).path.strip('/').split('/') if image else []
                    serial = carrier[2] if len(carrier) >= 3 and re.fullmatch(KEY, carrier[2]) else ''
                    cid = param(el['href'], 'cid')
                    if not re.fullmatch(CID, cid):
                        continue
                    target = query_url(NETTAI + '/publus/viewer.html', cid=cid, mv_publus_title=manga, mv_product=serial or [])
                    name = node_text(el.select_one('.detail--product__item__title'))
                    stamp = release_date(node_text(el.select_one('.detail--product__item__sdate')), '%Y.%m.%d')
                    episodes[target] = self.chapter(target, name, date=stamp)
            next_page = doc.select_one(self.next)
            target = self.site_link(next_page['href'], final) if next_page else ''
            if not self.is_title(target) or self.title_key(target) != manga or target in visited:
                break
            doc, final = self.document(http, target)
        return summary, self.order(episodes)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            return SeriesPort.inspect(self, url, http)
        return super().inspect(url, http)

    def pages(self, http, url):
        if not self.boost:
            return self.read(http, url, '/api/viewer/c', param(url, 'cid'))
        if param(url, 'mv_publus_locked'):
            raise SourceAccessError('Comic Boost требует покупку публикации.')
        self.origin.wait(getattr(http, 'deadline', None))
        target = BOOST + urlsplit(url).path
        _, final, _ = http.document(target, headers={'Referer': self.title_for(url) or BOOST + '/'},
                                    action='publus-source-document')
        if urlsplit(final).netloc != 'comic-boost.com':
            raise SourceError('Comic Boost перенаправил читалку на другой домен.')
        return self.read(http, url, '/pageapi/viewer/c.php', param(final, 'cid'), final.split('?', 1)[0])


class PashUp(PublusCatalogue):
    def __init__(self):
        super().__init__(('4500173675620672840', 'Pash Up!', 'ja', PASH, False), BOOST_TITLE, PASH_CHAPTER, interval=.4)

    def title_for(self, url):
        key = self.chapter_key(url)
        return PASH + '/content/' + key if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        return PASH + '/content/' + key if re.fullmatch(KEY, key) else url if self.is_title(url) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = urlsplit(url).path.strip('/')
        return title.rstrip('/') + '/read/' + key if self.is_title(title) and re.fullmatch(KEY, key) else url if self.is_chapter(url) else ''

    def row_for(self, obj):
        key, name = str(obj.get('SeriesID') or ''), obj.get('Name')
        if not re.fullmatch(KEY, key) or not isinstance(name, str) or not name:
            return None
        target = PASH + '/content/' + key
        img = (obj.get('Images') or {}).get('Series')
        raw = str(obj.get('Explain') or '')
        description = BeautifulSoup(raw, 'html.parser').get_text(' ', strip=True)
        authors = [str(writer['name']) for writer in obj.get('Writers') or [] if isinstance(writer, dict) and writer.get('name')]
        tags = strings(obj.get('Tags'))
        return self.record(target, name, image_url(img, target), authors=authors, description=description, tags=tags,
                           status='completed' if '完結' in tags else 'ongoing')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            if page != 1:
                return [], False
            path = '/pageapi/contents.php'
            args = {'type': 'search', 'reserve': '1', 'keyword': query, 'limit': '9999'}
        else:
            args = {'period': 'daily', 'category': '2', 'limit': 10, 'offset': (page - 1) * 10}
            if sort == 'updated':
                path = '/pageapi/products.php'
                args.update(type='update', unit='2', lastest='1')
            else:
                path = '/pageapi/contents.php'
                args['type'] = 'ranking'
        data = self.json(http, query_url(PASH + path, **args))
        rows = {}
        for item in data.get('Contents') or []:
            if isinstance(item, dict) and str(item.get('Category')) == '2' and (row := self.row_for(item)):
                rows[row['url']] = row
        return list(rows.values()), bool(not query and (number(data.get('TotalResults')) or 0) > page * 10)

    def series(self, http, url):
        key = self.title_key(url)
        data = self.json(http, query_url(PASH + '/pageapi/products.php', type='contents', id=key, limit=9999, order='nodesc'))
        contents = [item for item in data.get('Contents') or [] if isinstance(item, dict) and str(item.get('SeriesID')) == key]
        if not contents or not (row := self.row_for(contents[0])):
            raise SourceError('Pash Up! не вернул карточку произведения.')
        episodes = {}
        for item in contents:
            product = item.get('Product')
            if not isinstance(product, dict) or not re.fullmatch(KEY, serial := str(product.get('ID') or '')):
                continue
            end = release_date(str(product.get('EndDate') or ''), '%Y-%m-%d')
            if end and end < date.today().isoformat():
                continue
            drop = str(product.get('DownloadURL') or '')
            cid = param(drop, 'cid')
            open_issue = bool('/pageapi/download' not in drop and re.fullmatch(CID, cid))
            label = str(product.get('Name') or '')
            if not open_issue:
                label = '🔒 ' + label
            target = query_url(PASH + f'/content/{key}/read/{serial}', mv_pash_cid=cid if open_issue else [])
            stamp = release_date(str(product.get('StartDate') or ''), '%Y-%m-%d')
            episodes[target] = self.chapter(target, label, date=stamp, season=2 if product.get('SalesUnit') == '2' else 1)
        return row, self.order(episodes)

    def pages(self, http, url):
        return self.read(http, url, '/pageapi/viewer/c.php', param(url, 'mv_pash_cid'))


SOURCES = (PublusHtml(boost=True), PublusHtml(boost=False), PashUp())
