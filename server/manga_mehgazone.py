"""Mehgazone webcomics (keiyoushi ``src/en/mehgazone`` at 6f345a8).

Every comic is its own WordPress site on a ``*.mehgazone.com`` subdomain.
The hub's sidebar lists the comics; a comic's posts come from the public
WordPress REST API, one post per chapter. Patreon-locked posts are left out
exactly like in the extension, and the optional WordPress app password of the
extension is not carried over.
"""

from datetime import datetime
import json
import re
from urllib.parse import parse_qsl, urljoin, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_madara import image_url, node_text
from manga_ninth_routes import register_api
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://mehgazone.com'
HOST = re.compile(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)?mehgazone\.com')
COMIC_HOST = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.mehgazone\.com')
PER_PAGE = 100
MAX_PAGES = 60
LOCKED = 'Unlock with Patreon'
LIST_FIELDS = 'id,title,date_gmt,excerpt'
POST_FIELDS = 'link,content,excerpt,date,title'


class Hosts:
    """Reader hosts: the hub and every comic subdomain."""

    def __contains__(self, host):
        return isinstance(host, str) and bool(HOST.fullmatch(host)) and host != 'www.mehgazone.com'


def public_api(host, path, query):
    if not COMIC_HOST.fullmatch(host or '') or path != '/wp-json/wp/v2/posts':
        return False
    try:
        fields = parse_qsl(query, keep_blank_values=True, max_num_fields=6, strict_parsing=True)
    except ValueError:
        return False
    args = dict(fields)
    if len(args) != len(fields):
        return False
    if set(args) == {'per_page', 'page', '_fields'}:
        return (args['per_page'] == str(PER_PAGE) and args['_fields'] == LIST_FIELDS
                and bool(re.fullmatch(r'[1-9][0-9]?', args['page'])))
    return (set(args) == {'per_page', 'include', '_fields'} and args['per_page'] == '1'
            and args['_fields'] == POST_FIELDS and bool(re.fullmatch(r'[1-9][0-9]{0,9}', args['include'])))


register_api(public_api)


def rendered(value):
    return value.get('rendered', '') if isinstance(value, dict) and isinstance(value.get('rendered'), str) else ''


class Mehgazone(JsonSeries):
    def __init__(self):
        super().__init__(('2698265163169248715', 'Mehgazone', 'en', ROOT, False), r'(/)', r'(/)', interval=.3)
        self.reader_hosts = Hosts()

    def comic_host(self, url):
        host = urlsplit(url).hostname or ''
        return host if COMIC_HOST.fullmatch(host) and host != 'www.mehgazone.com' else ''

    def is_title(self, url):
        parts = urlsplit(url)
        return bool(self.comic_host(url)) and parts.path == '/' and not parts.query and not parts.fragment

    def is_chapter(self, url):
        parts = urlsplit(url)
        return (bool(self.comic_host(url)) and parts.path == '/' and not parts.fragment
                and bool(re.fullmatch(r'p=[1-9][0-9]{0,9}', parts.query)))

    def title_identity(self, value):
        return self.comic_host(value) + '/'

    def title_key(self, url):
        return self.comic_host(url)

    def chapter_key(self, url):
        return self.comic_host(url)

    def chapter_identity(self, url):
        return self.comic_host(url) + '?p=' + param(url, 'p')

    def title_for(self, url):
        host = self.comic_host(url)
        return f'https://{host}/' if host else ''

    def saved_title_url(self, url):
        target = self.canonical(url)
        host = self.comic_host(target)
        return f'https://{host}/' if host else ''

    def saved_chapter(self, row, root, title):
        # Suwayomi stored the absolute "https://<comic>.mehgazone.com/?p=<post>".
        target = self.canonical(str(row.get('realUrl') or row.get('url') or ''))
        return target if self.is_chapter(target) else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.comic_host(target) == self.comic_host(title)

    def comics(self, http):
        doc, final = self.document(http, ROOT + '/')
        group = doc.select_one('#main aside.primary-sidebar .sidebar-group')
        if group is None:
            raise SourceError('Mehgazone изменил главную страницу.')
        rows = {}
        for heading in group.select('h2'):
            label = node_text(heading)
            if 'latest' not in label.casefold() or label.count('"') < 2:
                continue
            title = label.split('"')[1].strip()
            feed = image = None
            for sibling in heading.find_next_siblings():
                feed = feed or (sibling if sibling.name == 'a' and '/feed' in sibling.get('href', '')
                                else sibling.select_one("a[href*='/feed']"))
                image = image or (sibling if sibling.name == 'img' else sibling.select_one('img'))
                if feed and image:
                    break
            host = urlsplit(urljoin(final, feed.get('href', ''))).hostname if feed else ''
            url = self.saved_title_url(f'https://{host}/') if host else ''
            if title and url:
                cover = image_url(image.get('src'), final) if image else ''
                rows[url] = self.record(url, title, cover, authors=('Patricia Barton',), status='ongoing')
                rows[url]['format'] = 'comic'
        if not rows:
            raise SourceError('Mehgazone не предоставил список комиксов.')
        return list(rows.values())

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1 or tag:
            return [], False
        rows = self.comics(http)
        if query:
            rows = [row for row in rows if query.casefold() in row['title'].casefold()]
        return rows, False

    def posts(self, http, url, **args):
        target = query_url(url.rstrip('/') + '/wp-json/wp/v2/posts', **args)
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, headers = http.document(target, headers={'Referer': url}, action='native-series-json')
        if final != target:
            raise SourceError('Mehgazone перенаправил запрос на другой адрес.')
        try:
            data = json.loads(raw)
        except ValueError:
            raise SourceError('Mehgazone изменил формат ответа.') from None
        if not isinstance(data, list):
            raise SourceError('Mehgazone изменил формат ответа.')
        return data, headers

    def series(self, http, url):
        url = self.saved_title_url(url)
        if not url:
            raise SourceError('Некорректная ссылка на комикс Mehgazone.')
        doc, _ = self.document(http, url)
        title_node = doc.select_one('head title')
        title = node_text(title_node) if title_node else ''
        if not title:
            raise SourceError('Mehgazone не предоставил карточку комикса.')
        cover = ''
        for node in doc.select("#content img[src*='.png']"):
            match = re.search(r'/[^/]+-([0-9]+\.png)$', node.get('src', ''), re.I)
            if match:
                cover = image_url(re.sub(r'/[^/]+-([0-9]+\.png)$', r'/\1', node['src'], flags=re.I), url)
                break
        row = self.record(url, title, cover, authors=('Patricia Barton',), status='ongoing')
        row['format'] = 'comic'
        posts, seen = [], set()
        for page in range(1, MAX_PAGES + 1):
            data, headers = self.posts(http, url, per_page=PER_PAGE, page=page, _fields=LIST_FIELDS)
            for item in data:
                if isinstance(item, dict) and type(item.get('id')) is int and item['id'] not in seen:
                    seen.add(item['id'])
                    posts.append(item)
            total = {key.lower(): value for key, value in headers.items()}.get('x-wp-totalpages', '')
            if (page >= int(total) if str(total).isdigit() else len(data) < PER_PAGE):
                break
        posts = [item for item in posts if LOCKED not in rendered(item.get('excerpt'))]
        posts.sort(key=lambda item: str(item.get('date_gmt') or ''))
        chapters = []
        for index, item in enumerate(posts):
            date = str(item.get('date_gmt') or '')
            try:
                date = datetime.fromisoformat(date).date().isoformat()
            except ValueError:
                date = ''
            name = BeautifulSoup(rendered(item.get('title')), 'html.parser').get_text(' ', strip=True) or date
            target = f'{url}?p={item["id"]}'
            chapters.append({**self.chapter(target, name, float(index), date), 'season': 1})
        return row, chapters

    def pages(self, http, url):
        host, post = self.comic_host(url), param(url, 'p')
        data, _ = self.posts(http, f'https://{host}/', per_page=1, include=post, _fields=POST_FIELDS)
        item = data[0] if data and isinstance(data[0], dict) else None
        if item is None:
            raise SourceAccessError('Mehgazone больше не публикует эту страницу.')
        if LOCKED in rendered(item.get('excerpt')):
            raise SourceAccessError('Страница доступна только подписчикам Patreon.')
        link = item.get('link') if isinstance(item.get('link'), str) else url
        body = BeautifulSoup(rendered(item.get('content')), 'html.parser')
        return [found for node in body.select('img') if (found := image_url(node.get('src'), link))]


SOURCES = (Mehgazone(),)
