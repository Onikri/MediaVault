"""Zerosum Online public Protobuf catalogues and previews."""

import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, image_url
from manga_mangaplus import protobuf
from manga_rayuba import uploaded
from manga_webcomics import query_url
from source_parser import SourceError

ROOT = 'https://zerosumonline.com'
HOST = 'api.zerosumonline.com'
API = 'https://' + HOST + '/api/v1'
ID = r'[1-9]\d{0,9}'


def public_api(host, path, query):
    if host != HOST:
        return False
    pairs = parse_qsl(query)
    args = dict(pairs)
    if len(pairs) != len(args):
        return False
    if path == '/api/v1/list':
        return set(args) == {'category', 'sort'} and args['category'] == 'series' and args['sort'] in {'date', 'title', 'author'}
    if path == '/api/v1/search':
        return set(args) == {'keyword'} and 1 <= len(args['keyword']) <= 160
    if path == '/api/v1/title':
        return set(args) == {'tag'} and bool(re.fullmatch(SEGMENT, args['tag']))
    return path == '/api/v1/viewer' and set(args) == {'chapter_id'} and bool(re.fullmatch(ID, args['chapter_id']))


class Zerosum(JsonSeries):
    def __init__(self):
        super().__init__(('8525996702535864887', 'Zerosum Online', 'ja', ROOT, False),
                         rf'/detail/({SEGMENT})/?', rf'/detail/({SEGMENT})/{ID}/?', interval=.35)

    def api(self, http, route, **params):
        self.origin.wait(getattr(http, 'deadline', None))
        target = query_url(API + route, **params)
        return protobuf(http, target, self.NAME, {'Referer': ROOT + '/'}, 'zerosum-proto', empty_post=route == '/viewer')

    def summary(self, item):
        key, title = item.string(2), item.string(3)
        if not re.fullmatch(SEGMENT, key) or not title:
            raise SourceError('Zerosum Online не предоставил карточку.')
        url = ROOT + '/detail/' + key
        return self.record(url, title, image_url(item.string(8), url), aliases=[item.string(4)],
                           authors=[item.string(5)], description=item.string(7))

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + '/detail/' + key if key else ''

    def chapter_identity(self, url):
        return urlsplit(url).path.rstrip('/')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1:
            return [], False
        if query:
            result = self.api(http, '/search', keyword=query)
        else:
            order = tag if tag in ('title', 'author') else 'date'
            result = self.api(http, '/list', category='series', sort=order)
        return [self.summary(item) for item in result.messages(3)], False

    def series(self, http, url):
        key = self.title_key(url)
        result = self.api(http, '/title', tag=key)
        row = self.summary(result.message(2))
        if self.title_key(row['url']) != key:
            raise SourceError('Zerosum Online подменил карточку тайтла.')
        chapters = {}
        for entry in result.messages(3):
            cid = str(entry.integer(1))
            if re.fullmatch(ID, cid):
                target = ROOT + f'/detail/{key}/{cid}'
                chapters[target] = self.chapter(target, entry.string(2), date=uploaded(entry.integer(4)))
        return row, self.order(chapters)

    def pages(self, http, url):
        chapter_id = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]
        result = self.api(http, '/viewer', chapter_id=chapter_id)
        return [image for item in result.messages(5) if (image := image_url(item.string(1), url))]


SOURCES = (Zerosum(),)
