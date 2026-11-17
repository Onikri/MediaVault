"""DMM/FANZA publisher catalogues and open Publus previews."""

import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_dynasty import entries
from manga_madara import image_url, release_date
from manga_publus_reader import reader_pages, signed_content
from manga_publus_sources import CID, KEY
from manga_series_port import Cards, number
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

HOSTS = {'book.dmm.com': 'general', 'book.dmm.co.jp': 'adult'}
TITLE = rf'/product/({KEY})/?'
CHAPTER = rf'/product/({KEY})/({KEY})/?'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36')
NAME_VARIANT = re.compile(r'(?:(?<=\s|】)(?:第?\d+巻|第?\d+話)|（[０-９0-9]+）|【第?\d+[巻話]】|#\d+).*$')


def public_api(host, path, query):
    if host not in HOSTS:
        return False
    pairs = parse_qsl(query)
    args = dict(pairs)
    if len(pairs) != len(args):
        return False
    if path == '/viewerapi/auth/':
        return ({'cid'} <= set(args) <= {'cid', 'lin'} and re.fullmatch(CID, args['cid'])
                and len(args.get('lin', '')) <= 200)
    if args.pop('shop_name', '') != HOSTS[host] or args.pop('format_webp', '') != '1':
        return False
    if not re.fullmatch(KEY, args.pop('series_id', '')):
        return False
    if path == '/ajax/bff/product_volume/':
        return set(args) == {'content_id', 'device_type'} and args['device_type'] == 'sp' and bool(re.fullmatch(KEY, args['content_id']))
    return (path == '/ajax/bff/contents_book/' and set(args) == {'order', 'purchase_status', 'page', 'per_page'}
            and args['order'] == 'desc' and args['purchase_status'] == 'all' and args['per_page'] == '100'
            and bool(re.fullmatch(r'[1-9]\d{0,3}', args['page'])))


class Dmm(JsonSeries):
    cards = Cards('.m-boxListBookProduct2__item, .m-boxSearchBookProduct__item', 'a[href*="/product/"]',
                  '.m-boxListBookProduct2Tmb__ttl, .m-boxSearchListTmb__ttl', 'img.m-bookImage__img',
                  'a.m-boxPaging:-soup-contains(">")')

    def __init__(self, identity):
        super().__init__(identity, TITLE, CHAPTER, interval=.45)
        self.shop = HOSTS[urlsplit(self.ROOT).netloc]

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.ROOT + '/product/' + key if key else ''

    def chapter_identity(self, url):
        return urlsplit(url).path.rstrip('/')

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        return self.ROOT + '/product/' + key if re.fullmatch(KEY, key) else url if self.is_title(url) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = urlsplit(url).path.strip('/')
        return title.rstrip('/') + '/' + key if self.is_title(title) and re.fullmatch(KEY, key) else url if self.is_chapter(url) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        self.origin.wait(getattr(http, 'deadline', None))
        if query:
            target = query_url(self.ROOT + '/search/', searchstr=query, page=page)
        else:
            target = query_url(self.ROOT + '/list/', sort='date' if sort == 'updated' else 'ranking',
                               page=page if page > 1 else [])
        raw, final, _ = http.document(target, headers={'Referer': self.ROOT + '/', 'User-Agent': UA})
        if urlsplit(final).netloc != urlsplit(self.ROOT).netloc or urlsplit(final).path.startswith(('/service/login', '/shelf')):
            raise SourceAccessError('Издатель ограничивает доступ к каталогу.')
        rows, more = self.card_rows(BeautifulSoup(raw, 'html.parser'), final, self.cards)
        for row in rows:
            row['title'] = NAME_VARIANT.sub('', row['title']).strip() or row['title']
        return rows, more

    def api(self, http, route, title, **params):
        value = query_url(self.ROOT + '/ajax/bff/' + route + '/', shop_name=self.shop,
                          series_id=self.title_key(title), format_webp=1, **params)
        return self.json(http, value, title)

    def volumes(self, http, url):
        result = {}
        for page in range(1, 81):
            data = self.api(http, 'contents_book', url, order='desc', purchase_status='all', page=page, per_page=100)
            for item in entries(data.get('volume_books')):
                if isinstance(cid := item.get('content_id'), str) and re.fullmatch(KEY, cid):
                    result[cid] = item
            if page * 100 >= (number((data.get('pager') or {}).get('total_count')) or 0):
                break
        return result

    def series(self, http, url):
        volumes = self.volumes(http, url)
        if not volumes:
            raise SourceError('Издатель не предоставил выпуски этой серии.')
        details = self.api(http, 'product_volume', url, device_type='sp', content_id=next(iter(volumes)))
        summary = details.get('series') or {}
        volume = details.get('volumes') or {}
        name = summary.get('title')
        if not isinstance(name, str) or not name:
            raise SourceError('Издатель не предоставил название.')
        genres = [entry['name'] for entry in entries(volume.get('genre')) if isinstance(entry.get('name'), str)]
        for field in ('publisher', 'label', 'category'):
            if isinstance(info := volume.get(field), dict) and isinstance(info.get('name'), str):
                genres.append(info['name'])
        row = self.record(url, name, image_url((volume.get('image_urls') or {}).get('pl'), url),
                          description=BeautifulSoup(str(volume.get('synopsis') or ''), 'html.parser').get_text(' ', strip=True),
                          genres=genres, authors=[e['name'] for e in entries(volume.get('author')) if isinstance(e.get('name'), str)],
                          status='completed' if (summary.get('status') or {}).get('is_completion') else 'ongoing')
        episodes = {}
        for key, item in volumes.items():
            dest = url.rstrip('/') + '/' + key
            name = str(item.get('title') or '')
            if not item.get('free_streaming_url'):
                name = name + ' · Фрагмент' if item.get('tachiyomi_url') else '🔒 ' + name
            stamp = release_date(str(item.get('content_publish_date') or '').partition('T')[0], '%Y-%m-%d')
            episodes[dest] = self.chapter(dest, name, number(item.get('volume_number')), stamp)
        return row, self.order(episodes)

    def pages(self, http, url):
        title = self.title_for(url)
        key = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)[2]
        item = self.volumes(http, title).get(key) or {}
        free = item.get('free_streaming_url')
        viewer = free[0] if isinstance(free, list) and free else item.get('tachiyomi_url')
        if not isinstance(viewer, str) or not viewer:
            raise SourceAccessError('Издатель требует покупку выпуска.')
        dest = image_url(viewer, self.ROOT + '/')
        if not dest:
            raise SourceError('Издатель вернул некорректную ссылку открытого выпуска.')
        if not param(dest, 'cid'):
            _, dest, _ = http.document(dest, headers={'Referer': title, 'User-Agent': UA})
        cid = param(dest, 'cid')
        if not re.fullmatch(CID, cid):
            raise SourceAccessError('Издатель ограничивает доступ к читалке.')
        request = query_url(self.ROOT + '/viewerapi/auth/', cid=cid, lin=param(dest, 'lin') or [])
        root_headers = urlunsplit(urlsplit(dest)._replace(query='', fragment=''))
        data = self.json(http, request, root_headers)
        base, auth = signed_content(data, url)
        return reader_pages(http, base, url, auth=auth)


SOURCES = (Dmm(('7153958782880204235', 'DMM', 'ja', 'https://book.dmm.com', False)),
           Dmm(('6425776937733405129', 'FANZA', 'ja', 'https://book.dmm.co.jp', True)))
