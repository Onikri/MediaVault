"""Pixiv Comic serial chapters and published store previews."""

from datetime import datetime
from hashlib import sha256
import re
from urllib.parse import parse_qsl, quote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_clipstudio import json_data
from manga_clipstudio_sources import flight_item
from manga_direct_payloads import JsonSeries
from manga_dynasty import entries
from manga_madara import image_url
from manga_publus_reader import reader_pages, signed_content
from manga_publus_sources import CID, KEY
from manga_rayuba import uploaded
from manga_series_port import SeriesPort
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://comic.pixiv.net'
API = ROOT + '/api/app'
STORE = 'https://comic-store-viewer.pixiv.net'
API_HOST = 'comic.pixiv.net'
ID = r'[1-9]\d{0,12}'
TITLE = rf'/(?:works|store/products)/({KEY})/?'
CHAPTER = rf'/(?:viewer/stories/({ID})|store/viewers/({KEY})/master)/?'
CLIENT_HASH = re.compile(r'[a-f0-9]{64}')
CLIENT_TIME = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[-+]\d{2}:\d{2})')


def public_api(host, path, query):
    pairs = parse_qsl(query)
    args = dict(pairs)
    if len(pairs) != len(args):
        return False
    if host == 'comic-store-viewer.pixiv.net':
        return (path == '/api/c' and {'cid'} <= set(args) <= {'cid', 'u1', 'u2'}
                and bool(re.fullmatch(CID, args['cid'])) and all(len(val) <= 2000 for val in args.values()))
    if host != API_HOST or not path.startswith('/api/app/'):
        return False
    path = path.removeprefix('/api/app')
    no_args = rf'/categories|/works/v5/{ID}|/store/products/v2/{KEY}|/episodes/{ID}/read_v4'
    if re.fullmatch(no_args, path):
        return not query
    if path == '/rankings/popularity':
        return set(args) == {'label', 'count'} and args['label'] == '総合' and bool(re.fullmatch(r'[1-9]\d{0,3}', args['count']))
    if re.fullmatch(rf'/works/{ID}/episodes/v2', path):
        return args == {'order': 'desc'}
    if re.fullmatch(rf'/store/products/{KEY}/variants/v3', path):
        return args == {'order': 'desc', 'view_type': 'product_detail'}
    endpoints = (r'/works/recent_updates/v2|/(?:works|store)/search/v2/[^/?#]{1,4000}|'
                 r'/tags/[^/?#]{1,900}/works/v2|/categories/[^/?#]{1,900}/works')
    return bool(re.fullmatch(endpoints, path) and set(args) == {'page'} and re.fullmatch(r'[1-9]\d{0,3}', args['page']))


def image_path(value, *, strip_prefix=False):
    target = image_url(value, ROOT + '/')
    parts = urlsplit(target)
    if strip_prefix and parts.path.startswith('/c/'):
        path = parts.path.strip('/').split('/')
        if len(path) >= 4:
            return urlunsplit(parts._replace(path='/' + '/'.join(path[2:])))
    return target


class PixivComic(JsonSeries):
    def __init__(self):
        super().__init__(('2937751339618832603', 'Pixivコミック', 'ja', ROOT, True), TITLE, CHAPTER, interval=.35)

    def chapter_key(self, url):
        found = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return (found[1] or found[2]) if found else ''

    def chapter_identity(self, url):
        return self.chapter_key(url)

    def title_for(self, url):
        key = param(url, 'mv_pixiv_title')
        if not re.fullmatch(KEY, key):
            return ''
        prefix = '/store/products/' if param(url, 'mv_pixiv_store') == '1' else '/works/'
        return ROOT + prefix + key

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        key = urlsplit(url).path.strip('/')
        if re.fullmatch(KEY, key):
            return ROOT + ('/works/' if re.fullmatch(ID, key) else '/store/products/') + key
        return self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = self.chapter_key(url) or urlsplit(url).path.strip('/')
        if not self.is_title(title) or not re.fullmatch(KEY, key):
            return ''
        return self.chapter_url(title, key, not re.fullmatch(ID, key))

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and self.title_for(target) == title.rstrip('/'))

    def chapter_url(self, title, key, store):
        path = f'/store/viewers/{key}/master' if store else '/viewer/stories/' + key
        return query_url(ROOT + path, mv_pixiv_title=self.title_key(title),
                         mv_pixiv_store='1' if urlsplit(title).path.startswith('/store/') else [])

    def request(self, http, target, extra=None):
        self.origin.wait(getattr(http, 'deadline', None))
        headers = {'Referer': ROOT + '/', **(extra or {})}
        raw, final, _ = http.document(target, headers=headers, action='pixivcomic-public')
        if final != target:
            raise SourceError('Pixiv Comic перенаправил запрос каталога.')
        obj = json_data(raw)
        body = obj if urlsplit(target).netloc != API_HOST else obj.get('data')
        if not isinstance(body, dict):
            raise SourceError('Pixiv Comic не предоставил данные открытого выпуска.')
        return body

    def row_for(self, data, kind):
        sid = str(data.get('official_work_id') or data.get('id') or '')
        key = sid or str(data.get('key') or '')
        name = data.get('name') if kind == 'work' else data.get('title')
        if not re.fullmatch(KEY, key) or not isinstance(name, str) or not name:
            return None
        url = ROOT + ('/works/' if sid else '/store/products/') + key
        if kind == 'work':
            cover = (data.get('image') or {}).get('main_big')
        else:
            cover = data.get('main_image_url' if kind == 'ranking' else 'image_url')
        source = data.get('description') or data.get('explanation')
        summary = BeautifulSoup(str(source or ''), 'html.parser').get_text(' ', strip=True)
        genres = [item['name'] for item in entries(data.get('categories')) if isinstance(item.get('name'), str)]
        tags = [item['name'] for item in entries(data.get('tags')) if isinstance(item.get('name'), str)]
        return self.record(url, name, image_path(cover, strip_prefix=kind != 'work'), description=summary,
                           genres=genres, tags=tags, authors=[data.get('author') or data.get('author_name') or ''])

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        rows, more = {}, False
        if query:
            lookups = [(query_url(API + route + quote(query, safe=''), page=page), field, kind)
                       for route, field, kind in (('/works/search/v2/', 'official_works', 'work'),
                                                  ('/store/search/v2/', 'products', 'store'))]
        elif tag:
            if tag.startswith('category:'):
                route = '/categories/' + quote(tag.removeprefix('category:')[:160], safe='') + '/works'
            else:
                route = '/tags/' + quote(tag.lstrip('#')[:160], safe='') + '/works/v2'
            lookups = [(query_url(API + route, page=page), 'official_works', 'work')]
        elif sort == 'updated':
            lookups = [(query_url(API + '/works/recent_updates/v2', page=page), 'official_works', 'work')]
        else:
            if page > 300:
                return [], False
            lookups = [(query_url(API + '/rankings/popularity', label='総合', count=page * 30), 'ranking', 'ranking')]
        for url, field, kind in lookups:
            data = self.request(http, url)
            items = list(entries(data.get(field)))
            if kind == 'ranking':
                more |= len(items) >= page * 30
                items = items[(page - 1) * 30:]
            else:
                more |= bool(data.get('next_page_number') or data.get('next_url'))
            for item in items:
                if row := self.row_for(item, kind):
                    rows.setdefault(row['url'], row)
        return list(rows.values()), more

    def vocabulary(self, http):
        body = self.request(http, API + '/categories')
        return [{'key': 'category:' + item['name'], 'label': item['name'], 'kind': 'genre'}
                for item in entries(body.get('categories')) if isinstance(item.get('name'), str) and item['name']]

    def series(self, http, url):
        key = self.title_key(url)
        store = urlsplit(url).path.startswith('/store/')
        if store:
            data = self.request(http, API + '/store/products/v2/' + key)
            details, kind = data.get('product') or {}, 'store'
            variants = data.get('variants')
            episodes = ()
        else:
            details = self.request(http, API + '/works/v5/' + key).get('official_work') or {}
            if str(details.get('id') or '') != key:
                raise SourceError('Pixiv Comic вернул другой тайтл.')
            kind = 'work'
            episodes = self.request(http, query_url(API + f'/works/{key}/episodes/v2', order='desc')).get('episodes')
            variants = ()
            if re.fullmatch(KEY, product_key := str(details.get('store_product_key') or '')):
                try:
                    variants = self.request(http, query_url(API + f'/store/products/{product_key}/variants/v3',
                                                          order='desc', view_type='product_detail')).get('variants')
                except SourceAccessError:
                    pass
        row = self.row_for(details, kind)
        if not row:
            raise SourceError('Pixiv Comic не предоставил карточку.')
        out = {}
        for item in entries(episodes):
            episode = item.get('episode')
            if not isinstance(episode, dict) or not re.fullmatch(ID, code := str(episode.get('id') or '')):
                continue
            label = ': '.join(str(episode[k]) for k in ('numbering_title', 'sub_title') if episode.get(k))
            target = self.chapter_url(url, code, False)
            if episode.get('state') != 'readable':
                label = '🔒 ' + label
                target = query_url(target, mv_pixiv_locked='1')
            out[target] = self.chapter(target, label, date=uploaded(episode.get('read_start_at')))
        for item in entries(variants):
            if not isinstance(code := item.get('sku'), str) or not re.fullmatch(KEY, code):
                continue
            target = self.chapter_url(url, code, True)
            free = (item.get('price') or {}).get('value') == 0
            label = str(item.get('name') or '') + ('' if free else ' · Фрагмент')
            out[target] = self.chapter(target, label, date=uploaded(item.get('permit_start_on')), season=2)
        return row, self.order(out)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            return SeriesPort.inspect(self, url, http)
        return super().inspect(url, http)

    def pages(self, http, url):
        if param(url, 'mv_pixiv_locked'):
            raise SourceAccessError('Pixiv Comic ограничивает доступ к выпуску.')
        chapter = self.chapter_key(url)
        target = ROOT + urlsplit(url).path.rstrip('/')
        self.origin.wait(getattr(http, 'deadline', None))
        if urlsplit(url).path.startswith('/store/'):
            response, final = http._open(target, headers={'Referer': ROOT + '/'}, action='pixivcomic-store')
            try:
                final = urljoin(final, response.headers.get('Location') or final)
            finally:
                response.close()
            opts = {key: value for key in ('cid', 'u1', 'u2') if (value := param(final, key))}
            if not re.fullmatch(CID, opts.get('cid', '')):
                raise SourceAccessError('Pixiv Comic не предоставил открытый том.')
            base, auth = signed_content(self.request(http, query_url(STORE + '/api/c', **opts)), url)
            return reader_pages(http, base, url, auth=auth, hash_filenames=False)
        raw, final, _ = http.document(target, headers={'Referer': ROOT + '/'})
        if final != target:
            raise SourceAccessError('Pixiv Comic перенаправил читалку.')
        salt = flight_item(raw, ('salt',)).get('salt') or ''
        now = datetime.now().astimezone().isoformat(timespec='seconds').replace('+00:00', 'Z')
        digest = sha256((now + str(salt)).encode()).hexdigest()
        data = self.request(http, API + f'/episodes/{chapter}/read_v4', {'X-Client-Time': now, 'X-Client-Hash': digest})
        return [page for item in entries((data.get('reading_episode') or {}).get('pages'))
                if (page := image_path(item.get('url'), strip_prefix=True))]


SOURCES = (PixivComic(),)
