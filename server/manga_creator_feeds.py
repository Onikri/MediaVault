"""Native creator and post feeds for the two Kemono-family extensions."""

import json
import re
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_madara import node_text
from manga_series_port import MAX_PAGES
from manga_source_tags import unique
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceError


SERVICES = {
    'kemono.cr': ('patreon', 'fanbox', 'fantia', 'afdian', 'boosty', 'gumroad', 'subscribestar', 'dlsite'),
    'coomer.st': ('onlyfans', 'fansly', 'candfans'),
}
PLATFORM = {'fanbox': 'Pixiv Fanbox', 'onlyfans': 'OnlyFans', 'subscribestar': 'SubscribeStar', 'dlsite': 'DLsite'}
PICTURE = re.compile(r'/(?:[a-f0-9]{2}/){2}[a-f0-9]{64}\.(?:png|jpg|gif|jpeg|webp)', re.I)
KEY = r'[A-Za-z0-9_-]{1,128}'
CREATORS_PAGE = 50
POSTS_PAGE = 50
MAX_POSTS_PAGES = 5


def path_patterns(host):
    platform = '|'.join(SERVICES[host])
    creator = rf'((?:{platform})/user/{KEY})'
    return re.compile(rf'/{creator}/?'), re.compile(rf'/{creator}/post/({KEY})/?')


def public_api(host, path, query):
    if host not in SERVICES:
        return False
    if path == '/api/v1/creators':
        return not query
    creator, post = path_patterns(host)
    route = path.removeprefix('/api/v1')
    if route == path:
        return False
    if route.endswith('/profile'):
        return not query and bool(creator.fullmatch(route.removesuffix('/profile')))
    if route.endswith('/posts') and creator.fullmatch(route.removesuffix('/posts')):
        return bool(re.fullmatch(r'o=(?:0|[1-9]\d{0,3})', query)) and int(query[2:]) % POSTS_PAGE == 0
    return not query and bool(post.fullmatch(route))


class CreatorFeed(JsonSeries):
    def __init__(self, identity):
        root = urlsplit(identity[3]).hostname
        creator, post = path_patterns(root)
        super().__init__(identity, creator.pattern, post.pattern, interval=1)
        self.post_path = post
        self.icons = f'https://img.{self.hostname}/icons/'
        self._directory = ([], 0)
        self._directory_lock = Lock()

    def data(self, http, route):
        endpoint = self.ROOT + '/api/v1' + route
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(endpoint, headers={'Referer': self.ROOT + '/'}, action='creator-feed-json')
        if final != endpoint:
            raise SourceError('Источник перенаправил запрос на другой маршрут.')
        try:
            return json.loads(raw)
        except ValueError:
            raise SourceError('Источник изменил формат каталога авторов.') from None

    def creators(self, http):
        with self._directory_lock:
            rows, expiry = self._directory
            if expiry > monotonic():
                return rows
            data = self.data(http, '/creators')
            if not isinstance(data, list):
                raise SourceError('Источник изменил формат каталога авторов.')
            rows = [row for row in data if isinstance(row, dict) and self.creator_key(row)]
            self._directory = rows, monotonic() + 1800
            return rows

    def creator_key(self, row):
        key = f"{row.get('service')}/user/{row.get('id')}"
        return key if self.TITLE_PATH.fullmatch('/' + key) else ''

    def creator(self, row):
        key = self.creator_key(row)
        service = key.split('/')[0]
        return self.record(self.ROOT + '/' + key, row.get('name') or key.rsplit('/', 1)[-1], self.icons + key.replace('/user/', '/'),
                           authors=[PLATFORM.get(service, service.title())])

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        rows = [creator for creator in self.creators(http) if query in str(creator.get('name', '')).casefold()
                and (not tag or creator.get('service') == tag)]
        if sort == 'updated':
            rows.sort(key=lambda row: str(row.get('updated', '')), reverse=True)
        else:
            rows.sort(key=lambda row: row.get('favorited') if type(row.get('favorited')) is int else 0, reverse=True)
        start = (page - 1) * CREATORS_PAGE
        return [self.creator(row) for row in rows[start:start + CREATORS_PAGE]], start + CREATORS_PAGE < len(rows)

    def vocabulary(self, http):
        return [{'label': PLATFORM.get(service, service.title()), 'sourceId': service, 'category': 'tag'}
                for service in SERVICES[self.hostname]]

    def title_for(self, url):
        key = self.chapter_key(url)
        return f'{self.ROOT}/{key}' if key else ''

    def files(self, post):
        attachments = post.get('attachments')
        files = [post.get('file'), *(attachments if isinstance(attachments, list) else ())]
        urls = []
        for item in files:
            if not isinstance(item, dict) or not isinstance(path := item.get('path'), str) or not PICTURE.fullmatch(path):
                continue
            url = self.ROOT + '/data' + path
            name = item.get('name')
            if isinstance(name, str) and len(name) <= 160:
                url = query_url(url, f=name)
            urls.append(url)
        by_path = {urlsplit(url).path: url for url in reversed(urls)}
        return list(reversed(by_path.values()))

    def profile_data(self, http, key):
        row = self.data(http, '/' + key + '/profile')
        if not isinstance(row, dict) or self.creator_key(row) != key:
            raise SourceError('Источник вернул профиль другого автора.')
        return self.creator(row)

    def details(self, http, url):
        target = self.saved_title_url(url)
        key = self.title_key(target)
        if key:
            return self.profile_data(http, key)
        if self.is_chapter(target):
            return self.post(http, target)[0]
        raise SourceError('Некорректная ссылка на автора или публикацию.')

    def chapter_data(self, post, key):
        if not isinstance(post, dict) or self.creator_key({'id': post.get('user'), 'service': post.get('service')}) != key:
            return '', '', ''
        post_id = post.get('id')
        if not isinstance(post_id, str) or not re.fullmatch(KEY, post_id):
            return '', '', ''
        date = str(post.get('edited') or post.get('published') or post.get('added') or '')[:10]
        title = str(post.get('title') or '').strip() or ('Публикация ' + date if date else 'Публикация')
        return self.ROOT + f'/{key}/post/{post_id}', title, date

    def post(self, http, url):
        path = urlsplit(url).path.rstrip('/')
        key = self.chapter_key(url)
        body = self.data(http, path)
        post = body.get('post') if isinstance(body, dict) else None
        target, title, date = self.chapter_data(post, key)
        if urlsplit(target).path != path:
            raise SourceError('Источник вернул другую публикацию.')
        pages = self.files(post)
        if not 1 <= len(pages) <= MAX_PAGES:
            raise SourceAccessError('Источник не предоставил изображения этой публикации.')
        cover = f'https://img.{self.hostname}/thumbnail' + urlsplit(pages[0]).path
        description = node_text(BeautifulSoup(str(post.get('content') or ''), 'html.parser'))
        tags = post.get('tags')
        row = self.record(target, title, cover, description=description, tags=unique(tags) if isinstance(tags, list) else ())
        return row, self.chapter(target, title, 1, date), pages

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url):
            row, chapter, pages = self.post(http, url)
            return self.reader_result(row, url, [chapter], pages)
        key = self.title_key(url)
        if not key:
            raise SourceError('Некорректная ссылка на профиль автора.')
        row = self.profile_data(http, key)
        chapters, more = {}, False
        for page in range(MAX_POSTS_PAGES):
            posts = self.data(http, f'/{key}/posts?o={page * POSTS_PAGE}')
            if not isinstance(posts, list):
                raise SourceError('Источник изменил формат списка публикаций.')
            for post in posts:
                target, title, when = self.chapter_data(post, key)
                if target and self.files(post):
                    chapters[target] = self.chapter(target, title, date=when)
            more = len(posts) == POSTS_PAGE
            if not more:
                break
        return self.reader_result(row, url, self.order(chapters), [], more)

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        parts = urlsplit(target)
        prefix = '/api/v1'
        if parts.path.startswith(prefix + '/'):
            return self.site_link(self.ROOT + parts.path.removeprefix(prefix))
        return target
