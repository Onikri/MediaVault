"""Manga One's published Protobuf catalogue and open chapters."""

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_japanese_next import AesCbcPage, HEX_IV, HEX_KEY
from manga_madara import image_url, node_text, release_date
from manga_mangaplus import protobuf
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://manga-one.com'
HOST = 'manga-one.com'
API = ROOT + '/api/client'
ID = r'[1-9]\d{0,9}'
TITLE = rf'/title/({ID})/?'
CHAPTER = rf'/manga/({ID})/chapter/({ID})/?'
TOKYO = timezone(timedelta(hours=9))


def public_api(host, path, query):
    if host != HOST or path != '/api/client':
        return False
    pairs = parse_qsl(query)
    args = dict(pairs)
    if len(args) != len(pairs):
        return False
    rq = args.pop('rq', '')
    if rq in ('ranking', 'rensai'):
        return not args
    if rq == 'title/search':
        return (not args or set(args) == {'query'} and 1 <= len(args['query']) <= 160
                or set(args) == {'tag_id'} and bool(re.fullmatch(ID, args['tag_id'])))
    if not re.fullmatch(ID, args.get('title_id', '')):
        return False
    if rq == 'viewer_v2':
        return set(args) == {'title_id'} or (set(args) == {'title_id', 'chapter_id'} and bool(re.fullmatch(ID, args['chapter_id'])))
    return rq == 'viewer/chapter_list' and args == {
        'title_id': args['title_id'], 'page': '1', 'limit': '9999', 'sort_type': 'desc', 'type': 'chapter'}


def transport(url, method, data):
    parsed = urlsplit(url)
    if not public_api(parsed.netloc, parsed.path, parsed.query):
        return False
    route = param(url, 'rq')
    if route == 'viewer_v2' or route == 'title/search' and (param(url, 'query') or param(url, 'tag_id')):
        return method == 'POST' and data == b''
    if route == 'title/search' and method == 'POST':
        return data == b''
    return method == 'GET' and data is None


class MangaOne(JsonSeries):
    def __init__(self):
        super().__init__(('7948822981386785924', 'Manga One', 'ja', ROOT, False),
                         TITLE, CHAPTER, interval=.35)

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + '/title/' + key if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        key = urlsplit(url).path.strip('/')
        return ROOT + '/title/' + key if re.fullmatch(ID, key) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        code = urlsplit(url).path.strip('/')
        parent = self.title_key(title)
        return ROOT + f'/manga/{parent}/chapter/{code}' if re.fullmatch(ID, code) and re.fullmatch(ID, parent) else ''

    def api(self, http, rq, post=False, **params):
        self.origin.wait(getattr(http, 'deadline', None))
        url = query_url(API, rq=rq, **params)
        return protobuf(http, url, self.NAME, {'Referer': ROOT + '/'}, 'mangaone-proto', empty_post=post)

    def row_for(self, entry):
        key = str(entry.integer(1))
        title = entry.string(2)
        if not re.fullmatch(ID, key) or not title:
            return None
        url = ROOT + '/title/' + key
        return self.record(url, title, image_url(entry.string(16) or entry.string(6), url))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1:
            return [], False
        if query or re.fullmatch(ID, tag):
            args = {'query': query} if query else {'tag_id': tag}
            response = self.api(http, 'title/search', post=True, **args)
            entries = [item.message(1).message(1) for item in response.messages(3)]
        elif sort == 'updated':
            groups = list(self.api(http, 'rensai').messages(1))
            index = datetime.now(TOKYO).weekday()
            entries = [item.message(1).message(1) for item in groups[index].messages(3)] if index < len(groups) else []
        else:
            response = self.api(http, 'ranking')
            groups = [item for category in response.messages(1) for item in category.messages(3)]
            entries = [item.message(1) for group in groups if group.string(2) == 'すべて' for item in group.messages(3)]
        return [row for entry in entries if (row := self.row_for(entry))], False

    def vocabulary(self, http):
        return [{'key': str(item.integer(1)), 'label': item.string(2), 'kind': 'genre'}
                for item in self.api(http, 'title/search').messages(2) if item.integer(1) > 0 and item.string(2)]

    def series(self, http, url):
        identity = self.title_key(url)
        data = self.api(http, 'viewer_v2', post=True, title_id=identity).message(5).message(1)
        name = data.string(2)
        if not name:
            raise SourceError('Manga One не предоставил карточку тайтла.')
        thumb = next(data.messages(22), None)
        description = node_text(BeautifulSoup(data.string(4), 'html.parser'))
        row = self.record(url, name, image_url(thumb.string(3), url) if thumb else '',
                          description=description, authors=re.split('[,、]', data.string(5)))
        items = self.api(http, 'viewer/chapter_list', title_id=identity, page=1, limit=9999,
                         sort_type='desc', type='chapter').message(1)
        chapters = {}
        for entry in items.messages(1):
            chapter = str(entry.integer(1))
            if not re.fullmatch(ID, chapter):
                continue
            title = ' - '.join(filter(None, (entry.string(2), entry.string(3))))
            points = next(entry.messages(16), None)
            locked = bool(points and any(field in points.fields for field in (1, 2, 3)))
            target = ROOT + f'/manga/{identity}/chapter/{chapter}'
            stamp = release_date(entry.string(5), '%Y/%m/%d')
            item = self.chapter(target, ('🔒 ' if locked else '') + title, date=stamp)
            if locked:
                item['available'] = False
            chapters[target] = item
        return row, self.order(chapters)

    def pages(self, http, url):
        parent, chapter = self.CHAPTER_PATH.fullmatch(urlsplit(url).path).groups()
        viewer = self.api(http, 'viewer_v2', post=True, title_id=parent, chapter_id=chapter)
        key, iv = viewer.string(3), viewer.string(4)
        if not HEX_KEY.fullmatch(key) or not HEX_IV.fullmatch(iv):
            raise SourceAccessError('Manga One не предоставил открытые страницы главы.')
        cipher = AesCbcPage(bytes.fromhex(key), bytes.fromhex(iv))
        refs = []
        for item in viewer.messages(1):
            page = next(item.messages(1), None)
            if page and (src := image_url(page.string(1), url)):
                refs.append((src, cipher))
        return remember(refs, url)


SOURCES = (MangaOne(),)
