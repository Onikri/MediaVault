"""BookWalker Japan catalogue, series releases and public Publus samples."""

import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_dynasty import entries
from manga_madara import image_url, node_text
from manga_publus_reader import reader_pages, signed_content
from manga_publus_sources import CID
from manga_series_port import picture
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://bookwalker.jp'
MEMBER = 'https://member.bookwalker.jp/api/books/updates'
VIEWERS = {'viewer-trial.bookwalker.jp': '/trial-page/c', 'viewer-df.bookwalker.jp': '/browserWebApi4/c',
           'viewer.bookwalker.jp': '/browserWebApi/c'}
VIEWER_HOSTS = {'bookwalker.jp', 'www.bookwalker.jp', *VIEWERS}
SERIES = r'[1-9]\d{0,10}'
UUID = r'[a-fA-F\d]{8}(?:-[a-fA-F\d]{4}){3}-[a-fA-F\d]{12}'
TITLE = rf'/(?:series/)?({SERIES}|de{UUID})(?:/list)?/?'
CHAPTER = rf'/series/({SERIES})/read/({UUID})/?'
NEXT = '.o-pager-next a:not(.o-pager-box-btn_hidden), a[data-action-label="次のページへ"]:not(.o-pager-box-btn_hidden)'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36')


def public_api(host, path, query):
    pairs = parse_qsl(query)
    args = dict(pairs)
    if len(pairs) != len(args):
        return False
    if host == 'member.bookwalker.jp' and path == '/api/books/updates':
        kind = args.pop('fileType', '')
        return kind == 'EPUB' and len(args) == 1 and any(re.fullmatch(UUID, key) and value == '0' for key, value in args.items())
    if VIEWERS.get(host) != path or host not in VIEWERS:
        return False
    return ({'cid', 'BID'} <= set(args) <= {'cid', 'BID', 'cr', 'u1', 'u2'} and args['BID'] == '0'
            and (host != 'viewer-trial.bookwalker.jp' or set(args) == {'cid', 'BID'})
            and bool(re.fullmatch(CID, args['cid'])) and all(len(value) <= 2048 for value in args.values()))


class BookWalkerJapan(JsonSeries):
    def __init__(self):
        super().__init__(('7753308828123873766', 'BookWalker Japan', 'ja', ROOT, True),
                         TITLE, CHAPTER, hosts=('www.bookwalker.jp',), interval=.45)

    def index_url(self, key):
        return ROOT + f'/series/{key}/'

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.index_url(key) if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = self.title_key(url)
        if key.startswith('de'):
            return ROOT + '/' + key + '/'
        return self.index_url(key) if key else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        key = urlsplit(url).path.strip('/').removeprefix('de')
        series = self.title_key(title)
        return self.index_url(series) + 'read/' + key if re.fullmatch(SERIES, series) and re.fullmatch(UUID, key) else ''

    def document(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': ROOT + '/', 'User-Agent': UA})
        dest = self.site_link(final)
        if not dest or urlsplit(dest).path.startswith('/app/03/login'):
            raise SourceAccessError('BookWalker ограничивает доступ к странице.')
        return BeautifulSoup(raw, 'html.parser'), dest

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            url = query_url(ROOT + '/search/', word=query, order='score', wa='0', np='0', page=page)
        else:
            url = query_url(ROOT + '/category/2/', order='release' if sort == 'updated' else 'rank', np='0', page=page)
        doc, final = self.document(http, url)
        rows = {}
        for el in doc.select('.m-tile, .o-tile--series'):
            link = el.select_one('a.m-book-item__title[href], .o-tile-ttl a[href]')
            address = self.site_link(link['href'], final) if link else ''
            target = self.saved_title_url(address)
            title = node_text(link)
            if self.is_title(target) and title:
                cover = picture(el.select_one('.m-thumb__image img, .o-tile-book-img img'), final, ('data-original',))
                rows[target] = self.record(target, title, cover)
        return list(rows.values()), bool(rows and doc.select_one(NEXT))

    def book_details(self, http, uid):
        if not re.fullmatch(UUID, uid):
            raise SourceError('BookWalker не предоставил идентификатор книги.')
        reply = self.json(http, query_url(MEMBER, fileType='EPUB', **{uid: '0'}))
        details = next(entries(reply), None)
        if not details or not re.fullmatch(SERIES, str(details.get('seriesId') or '')) or not details.get('seriesName'):
            raise SourceError('BookWalker не предоставил карточку серии.')
        return details

    def list_page(self, http, key, page):
        return self.document(http, query_url(self.index_url(key) + 'list/', order='title', detail='0', page=page))[0]

    def options(self, doc):
        for node in doc.select('.p-episode__list a[data-book-uuid]'):
            uid = node['data-book-uuid']
            access = node.get('href') if node.get('data-is-free') == '1' else ''
            label = node_text(node.select_one('.o-ttsk-list-item__title'))
            if re.fullmatch(UUID, uid):
                yield uid, label, access or '', ''

    def volumes(self, http, key, first=None):
        for page in range(1, 81):
            doc = first if page == 1 and first is not None else self.list_page(http, key, page)
            for node in doc.select('.m-tile-list .m-book-item'):
                link = node.select_one('a.m-book-item__title[data-uuid]')
                if not link or not re.fullmatch(UUID, uid := link['data-uuid']):
                    continue
                read = node.select_one('.a-icon-btn--read[href], .a-icon-btn--free[href]')
                sample = node.select_one('.a-icon-btn--trial[href]')
                yield uid, node_text(link), read['href'] if read else '', sample['href'] if sample else ''
            if not doc.select_one(NEXT):
                break

    def series(self, http, url):
        key = self.title_key(url)
        if key.startswith('de'):
            data = self.book_details(http, key[2:])
            key = str(data['seriesId'])
            source, first = self.document(http, self.index_url(key))[0], None
        else:
            source, first = self.document(http, self.index_url(key))[0], None
            first_chapter = source.select_one('.p-episode__list a[data-book-uuid]')
            if first_chapter:
                uuid = first_chapter['data-book-uuid']
            else:
                first = self.list_page(http, key, 1)
                first_book = first.select_one('.m-tile-list .m-book-item a.m-book-item__title[data-uuid]')
                uuid = first_book['data-uuid'] if first_book else ''
            data = self.book_details(http, uuid)
            if str(data['seriesId']) != key:
                raise SourceError('BookWalker вернул данные другой серии.')
        base = self.index_url(key)
        summary = '\n\n'.join(BeautifulSoup(str(data[field]), 'html.parser').get_text(' ', strip=True)
                                for field in ('productExplanationShort', 'productExplanationDetails',
                                              'companyName', 'labelName', 'copyRightString') if data.get(field))
        record = self.record(base, data['seriesName'], image_url(data.get('coverImageUrl'), base),
                             description=summary, aliases=[data.get('seriesNameKana') or ''],
                             authors=[row['authorName'] for row in entries(data.get('authors')) if row.get('authorName')])
        mode = source.select_one('.p-episode__list') is not None
        docs = self.options(source) if mode else self.volumes(http, key, first)
        rows = {}
        for uid, label, read, trial in docs:
            target = base + 'read/' + uid
            visible = '🔒 ' + label if not read and not trial else label + ' · Фрагмент' if not read and trial else label
            rows[target] = self.chapter(target, visible)
        return record, self.order(rows)

    def public_view(self, http, value, referer):
        target = self.site_link(value, referer) or image_url(value, referer)
        host = urlsplit(target).netloc
        if not target or host not in VIEWER_HOSTS:
            raise SourceAccessError('BookWalker не предоставил ссылку открытого чтения.')
        self.origin.wait(getattr(http, 'deadline', None))
        _, final, _ = http.document(target, headers={'Referer': referer, 'User-Agent': UA}, action='bookwalker-public-view')
        host = urlsplit(final).netloc
        cid, content_type = param(final, 'cid'), param(final, 'cty')
        if host not in VIEWERS or not re.fullmatch(CID, cid) or content_type not in ('', '1', '2'):
            raise SourceAccessError('BookWalker ограничивает доступ к открытому выпуску.')
        args = {'cid': cid, 'BID': '0'}
        if host != 'viewer-trial.bookwalker.jp':
            for key in ('cr', 'u1', 'u2'):
                if value := param(final, key):
                    args[key] = value
        view = urlunsplit(urlsplit(final)._replace(query='', fragment=''))
        reply = self.json(http, query_url('https://' + host + VIEWERS[host], **args), view)
        if reply.get('cty') not in (1, 2):
            raise SourceAccessError('BookWalker не предоставил открытые изображения этого выпуска.')
        base, auth = signed_content(reply, referer)
        if host == 'viewer-trial.bookwalker.jp':
            auth = {key: value for key, value in auth.items() if key in {'pfCd', 'Policy', 'Signature', 'Key-Pair-Id'}}
        elif auth:
            auth['BID'] = '0'
        return base, auth

    def pages(self, http, url):
        series = self.chapter_key(url)
        uid = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)[2]
        title = self.index_url(series)
        doc, _ = self.document(http, title)
        options = self.options(doc) if doc.select_one('.p-episode__list') else self.volumes(http, series)
        issue = next((entry for entry in options if entry[0] == uid), None)
        if not issue:
            raise SourceError('BookWalker не предоставил выбранный выпуск.')
        _, _, read, trial = issue
        for candidate in (read, trial):
            if candidate:
                try:
                    content, auth = self.public_view(http, candidate, title)
                    return reader_pages(http, content, url, auth=auth)
                except SourceAccessError:
                    continue
        raise SourceAccessError('BookWalker не предоставил открытый том или фрагмент.')


SOURCES = (BookWalkerJapan(),)
