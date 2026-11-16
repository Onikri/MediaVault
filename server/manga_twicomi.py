"""Twicomi tweets and author archives backed by the public V2 API."""

import re
from collections import OrderedDict
from threading import Lock
from time import monotonic
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from manga_direct_payloads import items, strings
from manga_madara import image_url
from manga_series_port import MAX_CHAPTERS, MAX_PAGES, SeriesPort, number
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://twicomi.com'
HOST = 'api.twicomi.com'
API = 'https://' + HOST + '/api/v2'
USER = r'[A-Za-z0-9_]{1,32}'
TWEET = r'[1-9]\d{0,24}'
AUTHOR = rf'/author/({USER})(?:/page/[1-9]\d{{0,3}})?/?'
SINGLE = rf'/manga/({USER})/({TWEET})/?'
PAGE = r'[1-9]\d{0,3}'
LISTS = {'manga/featured/list', 'manga/list', 'author/list', 'author/manga/list'}
SORTS = {'create_time', 'retweet_count', 'good_count', 'follower_count', 'manga_tweet_count', 'latest_manga_tweet_time'}


def public_api(host, path, query):
    endpoint = path.removeprefix('/api/v2/')
    if host != HOST or not path.startswith('/api/v2/') or endpoint not in LISTS:
        return False
    pairs = parse_qsl(query)
    args = dict(pairs)
    required = {'page_no', 'page_limit'}
    optional = {'query', 'order_by', 'order', 'screen_name'}
    if (len(args) != len(pairs) or not required <= set(args) <= required | optional
            or not re.fullmatch(PAGE, args['page_no']) or args['page_limit'] not in ('12', '24', '500')):
        return False
    if 'order_by' in args and args['order_by'] not in SORTS or args.get('order', 'desc') not in ('asc', 'desc'):
        return False
    if endpoint == 'author/manga/list':
        return bool(re.fullmatch(USER, args.get('screen_name', '')) and args['page_limit'] == '500')
    return 'screen_name' not in args and len(args.get('query', '')) <= 160


class Twicomi(SeriesPort):
    def __init__(self):
        super().__init__(('4589056979500242728', 'Twicomi', 'all', ROOT, True),
                         rf'(?:{AUTHOR}|{SINGLE})', SINGLE, interval=.35)
        self.lock = Lock()
        self.records = OrderedDict()

    def title_key(self, url):
        path = urlsplit(url).path
        if match := re.fullmatch(AUTHOR, path):
            return 'author/' + match[1]
        if match := re.fullmatch(SINGLE, path):
            return 'manga/' + match[1] + '/' + match[2]
        return ''

    def is_title(self, url):
        return bool(self.title_key(url) and param(url, 'mv_twicomi_read') != '1')

    def title_for(self, url):
        parent = param(url, 'mv_twicomi_author')
        if re.fullmatch(USER, parent):
            return ROOT + '/author/' + parent
        key = self.title_key(url)
        return ROOT + '/' + key if key else ''

    def chapter_identity(self, url):
        return self.title_key(url)

    def saved_chapter_matches(self, target, title):
        key = self.title_key(target)
        parent = self.title_key(title)
        return bool(self.is_chapter(target) and (key == parent or parent == 'author/' + key.split('/')[1]))

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if not self.is_chapter(url):
            return ''
        parts = urlsplit(url)
        author = self.title_key(title).removeprefix('author/') if '/author/' in title else ''
        return query_url(urlunsplit(parts._replace(fragment='')), mv_twicomi_read=1, mv_twicomi_author=author or [])

    def api(self, http, route, page, limit, **options):
        url = query_url(API + '/' + route, page_no=page, page_limit=limit, **options)
        envelope = self.json(http, url)
        result = envelope.get('response')
        if not isinstance(result, dict):
            raise SourceError('Twicomi изменил формат публичного API.')
        return result

    def author_row(self, data):
        handle = data.get('screen_name')
        if not isinstance(handle, str) or not re.fullmatch(USER, handle):
            return None
        url = ROOT + '/author/' + handle
        name = data.get('name') or handle
        cover = image_url(data.get('profile_image'), url)
        return self.record(url, name, cover, description=str(data.get('description') or ''), authors=[name])

    def tweet(self, data):
        author, entry = data.get('author') or {}, data.get('tweet') or {}
        handle = author.get('screen_name')
        key = str(entry.get('tweet_id') or '')
        if not isinstance(handle, str) or not re.fullmatch(USER, handle) or not re.fullmatch(TWEET, key):
            return None
        url = ROOT + f'/manga/{handle}/{key}'
        pages = [src for img in strings(entry.get('attach_image_urls')) if (src := image_url(img, url))]
        if not 1 <= len(pages) <= MAX_PAGES:
            return None
        text = str(entry.get('tweet_text') or '').strip()
        label = text.splitlines()[0] if text else author.get('name') or handle
        tags = [*strings(entry.get('tags')), *strings(entry.get('hash_tags'))]
        row = self.record(url, label, pages[0], description=text, authors=[author.get('name') or handle],
                          tags=tags, status='completed')
        date = str(entry.get('tweet_create_time') or '')[:10]
        with self.lock:
            self.records[url] = (monotonic(), row, pages, date)
            self.records.move_to_end(url)
            while len(self.records) > 4096:
                self.records.popitem(last=False)
        return row, pages, date

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        params = {}
        is_author = tag == 'author'
        if query:
            params['query'] = query
        if is_author:
            path, limit = 'author/list', 12
            params['order_by'] = 'follower_count'
        elif query or sort == 'updated':
            path, limit = 'manga/list', 12 if query else 24
            params['order_by'] = 'create_time'
        else:
            path, limit = 'manga/featured/list', 24
        result = self.api(http, path, page, limit, **params)
        if is_author:
            rows = [row for data in items(result, 'author_list') if (row := self.author_row(data.get('author') or {}))]
        else:
            rows = [item[0] for data in items(result, 'manga_list') if (item := self.tweet(data))]
        return rows, page * limit < (number(result.get('total_count')) or 0)

    def archive(self, http, author):
        for page in range(1, 9):
            response = self.api(http, 'author/manga/list', page, 500, screen_name=author, order_by='create_time', order='asc')
            for item in items(response, 'manga_list'):
                if (tweet := self.tweet(item)) and self.title_key(tweet[0]['url']).startswith('manga/' + author + '/'):
                    yield item['author'], tweet
            if page * 500 >= (number(response.get('total_count')) or 0):
                return
        raise SourceError('Архив автора Twicomi превышает лимит страниц.')

    def resolve(self, http, url):
        key = self.title_key(url)
        target = ROOT + '/' + key
        with self.lock:
            item = self.records.get(target)
        if item is not None and monotonic() - item[0] < 600:
            return item[1:]
        if not key.startswith('manga/'):
            raise SourceError('Некорректная публикация Twicomi.')
        author = key.split('/')[1]
        for _, tweet in self.archive(http, author):
            if key == self.title_key(tweet[0]['url']):
                return tweet
        raise SourceError('Twicomi не предоставил указанную публикацию.')

    def details(self, http, value):
        url = self.canonical(value)
        key = self.title_key(url)
        if key.startswith('author/'):
            handle = key.split('/')[1]
            first = next(self.archive(http, handle), None)
            row = self.author_row(first[0]) if first else None
            if row:
                return row
            raise SourceError('Twicomi не предоставил открытые публикации автора.')
        return self.resolve(http, url)[0]

    def inspect(self, value, http):
        url = self.canonical(value)
        key = self.title_key(url)
        if key.startswith('author/'):
            handle = key.split('/')[1]
            result, summary = [], None
            for author, (item, _, date) in self.archive(http, handle):
                summary = summary or self.author_row(author)
                target = query_url(self.site_link(item['url']), mv_twicomi_read=1, mv_twicomi_author=handle)
                result.append(self.chapter(target, item['title'], len(result) + 1, date))
            if not summary:
                raise SourceError('Twicomi не предоставил открытые публикации автора.')
            return self.reader_result(summary, url, result[:MAX_CHAPTERS], [], len(result) > MAX_CHAPTERS)
        summary, pages, date = self.resolve(http, url)
        target = query_url(ROOT + '/' + key, mv_twicomi_read=1)
        chapters = [self.chapter(target, summary['title'], n=1, date=date)]
        return self.reader_result(summary, url, chapters, pages if param(url, 'mv_twicomi_read') == '1' else [])


SOURCES = (Twicomi(),)
