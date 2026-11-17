"""DreComi+ public catalogue and AES-protected free reader sessions."""

from base64 import b64decode
import re
from urllib.parse import parse_qsl, urlsplit

from manga_clipstudio import json_data
from manga_direct_payloads import JsonSeries
from manga_dynasty import entries
from manga_japanese_next import AesCbcPage
from manga_madara import image_url, release_date
from manga_series_port import number
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://drecomi-plus.jp'
HOST = 'api.drecomi-plus.jp'
API_PATH = '/api/v1/app'
API = 'https://' + HOST + API_PATH
ID = r'[A-Za-z0-9_-]{1,80}'
TYPE = r'(?:episodes|volumes)'
TITLE = rf'/series/({ID})/?'
CHAPTER = rf'/series/({ID})/({TYPE})/({ID})(/trial)?/?'
VIEWER = rf'/viewer/{TYPE}/{ID}/(?:session|trial-session)'


def public_api(host, path, query):
    if host != HOST or not path.startswith(API_PATH + '/'):
        return False
    path = path.removeprefix(API_PATH)
    pairs = parse_qsl(query, keep_blank_values=True)
    args = dict(pairs)
    if len(args) != len(pairs):
        return False
    if re.fullmatch(VIEWER, path) or path != '/series/ranking' and re.fullmatch(rf'/series/{ID}', path):
        return not query
    if not re.fullmatch(r'[1-9]\d{0,3}', args.get('page', '')):
        return False
    if path == '/series/ranking':
        return set(args) == {'page', 'limit'} and args['limit'] == '10'
    if path == '/series' and args.get('limit') == '18':
        return (set(args) == {'page', 'limit', 'keyword'} and 1 <= len(args['keyword']) <= 160
                or set(args) == {'page', 'limit', 'sort', 'order'}
                and args['sort'] == 'latest_published_at' and args['order'] == 'desc')
    return (path in ('/episodes', '/volumes') and set(args) == {'page', 'limit', 'sort', 'order', 'series_code'}
            and bool(re.fullmatch(ID, args['series_code'])) and args['limit'] == '200' and args['order'] == 'desc'
            and args['sort'] == ('episode_number' if path == '/episodes' else 'volume_number'))


def viewer_form(value, data):
    parts = urlsplit(value)
    return bool(public_api(parts.netloc, parts.path, parts.query)
                and re.fullmatch(VIEWER, parts.path.removeprefix(API_PATH)) and data == b'')


def released(value):
    return release_date(str(value or '').partition('T')[0], '%Y-%m-%d')


def next_page(value, page):
    paging = value.get('pagination') or {}
    total = number(paging.get('total_pages')) or page
    current = number(paging.get('current_page')) or page
    return current < total


class DreComics(JsonSeries):
    def __init__(self):
        super().__init__(('8766832343449907432', 'DreComi+', 'ja', ROOT, True), TITLE, CHAPTER,
                         hosts=('www.drecomi-plus.jp',), interval=.35)

    def title_for(self, url):
        return ROOT + '/series/' + self.chapter_key(url)

    def chapter_identity(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return match.group(1, 2, 3) if match else ('', '', '')

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        return ROOT + '/series/' + key if re.fullmatch(ID, key) else url if self.is_title(url) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        key = urlsplit(url).path.strip('/')
        if not self.is_title(title) or not re.fullmatch(ID, key):
            return ''
        from source_parser import PublicHttp

        http = PublicHttp(timeout=(3, 6))
        try:
            matches = [self.site_link(chapter['url']) for chapter in self.series(http, title)[1]
                       if self.chapter_identity(self.site_link(chapter['url']))[2] == key]
            return matches[0] if len(matches) == 1 else ''
        finally:
            http.close()

    def row_for(self, entry):
        key, title = entry.get('code'), entry.get('name')
        if not isinstance(key, str) or not re.fullmatch(ID, key) or not isinstance(title, str) or not title:
            return None
        thumbnail = (entry.get('thumbnail') or {}).get('cdn_url')
        description = '\n\n'.join(str(entry[field]) for field in ('summary', 'update_interval', 'next_update_schedule')
                                  if entry.get(field))
        return self.record(ROOT + '/series/' + key, title, image_url(thumbnail, ROOT), description=description,
                           authors=[label['name'] for label in entries(entry.get('authors')) if isinstance(label.get('name'), str)],
                           genres=[label['name'] for label in entries(entry.get('genres')) if isinstance(label.get('name'), str)],
                           status={'ongoing': 'ongoing', 'completed': 'completed'}.get(entry.get('status'), ''))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        ranking = not query and sort != 'updated'
        if ranking:
            url = query_url(API + '/series/ranking', page=page, limit=10)
        else:
            opts = {'keyword': query} if query else {'sort': 'latest_published_at', 'order': 'desc'}
            url = query_url(API + '/series', page=page, limit=18, **opts)
        data = self.json(http, url)
        rows = {}
        for entry in entries(data.get('items')):
            item = entry.get('series') if ranking else entry
            if isinstance(item, dict) and (row := self.row_for(item)):
                rows[row['url']] = row
        return list(rows.values()), next_page(data, page)

    def series(self, http, url):
        key = self.title_key(url)
        summary = self.row_for(self.json(http, API + '/series/' + key))
        if not summary or self.title_key(summary['url']) != key:
            raise SourceError('DreComi+ вернул данные другого тайтла.')
        result = {}
        for category in ('episodes', 'volumes'):
            for page in range(1, 41):
                data = self.json(http, query_url(API + '/' + category, series_code=key, page=page, limit=200,
                                                 sort='episode_number' if category == 'episodes' else 'volume_number',
                                                 order='desc'))
                for item in entries(data.get('items')):
                    identity = item.get('code')
                    if not isinstance(identity, str) or not re.fullmatch(ID, identity):
                        continue
                    paid = item.get('actual_price') != 0
                    preview = paid and item.get('has_trial_read_pages') is True
                    target = ROOT + f'/series/{key}/{category}/{identity}' + ('/trial' if preview else '')
                    if paid and not preview:
                        target = query_url(target, mv_dre_locked=1)
                    title = str(item.get('name') or '')
                    title = title + ' · Фрагмент' if preview else '🔒 ' + title if paid else title
                    n = number(item.get('episode_number') or item.get('volume_number'))
                    result[target] = self.chapter(target, title, n, released(item.get('publish_at')))
                if not next_page(data, page):
                    break
        return summary, self.order(result)

    def pages(self, http, url):
        if param(url, 'mv_dre_locked'):
            raise SourceAccessError('DreComi+ требует покупку выпуска.')
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        mode = 'trial-session' if match[4] else 'session'
        target = API + f'/viewer/{match[2]}/{match[3]}/{mode}'
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(target, headers={'Referer': ROOT + '/'}, method='POST', data=b'', action='drecomics-viewer')
        if final != target:
            raise SourceError('DreComi+ перенаправил запрос открытой читалки.')
        obj = json_data(raw)
        refs = []
        try:
            key = b64decode(obj.get('session_key') or '', validate=True)
            for entry in entries(obj.get('pages')):
                iv = b64decode(entry.get('iv') or '', validate=True)
                link = image_url(entry.get('image_url'), ROOT)
                if len(key) not in (16, 24, 32) or len(iv) != 16 or not link:
                    raise ValueError('Invalid page')
                refs.append((number(entry.get('page_number')) or len(refs), link, AesCbcPage(key, iv)))
        except (TypeError, ValueError):
            raise SourceError('DreComi+ не предоставил полный набор открытых страниц.') from None
        return remember([(link, transform) for _, link, transform in sorted(refs, key=lambda row: row[0])], url)


SOURCES = (DreComics(),)
