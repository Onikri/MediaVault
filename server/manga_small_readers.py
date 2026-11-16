"""Small public JSON reader protocols from the installed extensions."""

import json
import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_catalogues import SLUG, MANGA
from manga_direct_payloads import JsonSeries, items
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, Meta, number
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceError


DOUJIVA = 'doujiva.com'
COMICLAND = 'api.comicland.org'
LOLOBUN = 'www.lolobun.com'
INDEX = r'\d{1,9}'
ORDINAL = rf'{INDEX}(?:\.\d{{1,4}})?'
ENTITY = r'[1-9]\d{0,13}'
LOLO_PAGES = 'https://' + LOLOBUN + '/ajax/comic.ashx?op=getChapterPic'


def public_api(host, path, query):
    if host not in {DOUJIVA, COMICLAND, LOLOBUN}:
        return False
    fields = parse_qsl(query)
    args = dict(fields)
    if len(args) != len(fields) or any(len(value) > 160 for value in args.values()):
        return False
    if host == DOUJIVA:
        if path in ('/api/v1/manga', '/api/v1/search'):
            key = 'q' if path.endswith('search') else 'sort'
            return (set(args) == {'page', 'limit', key} and args['limit'] == '24'
                    and bool(re.fullmatch(INDEX, args['page'])) and (key == 'q' or args[key] in ('newest', 'popular-today')))
        return not query and bool(re.fullmatch(rf'/api/v1/manga/{SEGMENT}(?:/chapters/{SEGMENT})?', path))
    if host == COMICLAND:
        if path in ('/api/comics', '/api/comics/official', '/api/comics/popular', '/api/comic/search'):
            base = {'offset', 'limit'}
            return (base <= set(args) <= base | {'status', 'q'} and args['limit'] == '20'
                    and bool(re.fullmatch(INDEX, args['offset'])) and args.get('status', 'ongoing') == 'ongoing'
                    and (('q' in args) == path.endswith('/search')))
        if path == '/api/comic/detail':
            return set(args) == {'slug'} and bool(re.fullmatch(SEGMENT, args['slug']))
        return (path == '/api/chapter/pages_by_index' and set(args) == {'slug', 'index'}
                and bool(re.fullmatch(SEGMENT, args['slug']) and re.fullmatch(ORDINAL, args['index'])))
    if path == '/ajax/Common.ashx':
        return (set(args) == {'op', 'q', 'type', 'pi'} and args['op'] == 'searchWorks' and args['type'] == 'comic'
                and bool(re.fullmatch(INDEX, args['pi'])))
    return False


def public_form(url, data):
    return url == LOLO_PAGES and set(data) == {'chapId'} and bool(re.fullmatch(ENTITY, str(data['chapId'])))


class SlugAPI(JsonSeries):
    def __init__(self, identity, title, chapter, prefix):
        super().__init__(identity, title, chapter, interval=.35)
        self.prefix = prefix

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.ROOT + self.prefix + key if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        key = urlsplit(url).path.strip('/')
        target = self.ROOT + self.prefix + key
        return target if re.fullmatch(SEGMENT, key) and self.is_title(target) else ''

    def entry(self, data, cover_field, genres=(), tags=(), authors=()):
        key = data.get('slug', '') if isinstance(data, dict) else ''
        label = data.get('title') if key else None
        if not isinstance(key, str) or not re.fullmatch(SEGMENT, key) or not isinstance(label, str) or not label:
            return None
        url = self.ROOT + self.prefix + key
        return self.record(url, label, image_url(data.get(cover_field), url), description=data.get('description') or '',
                           authors=authors, genres=genres, tags=tags, status=data.get('status') or '')


class Doujiva(SlugAPI):
    def __init__(self):
        super().__init__(('1868981745168096185', 'Doujiva', 'all', 'https://' + DOUJIVA, True),
                         MANGA, rf'/manga/{SLUG}/chapters?/({SEGMENT})/?', '/manga/')

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        key = urlsplit(target).path.strip('/')
        return title.rstrip('/') + '/chapter/' + key if self.is_title(title) and re.fullmatch(SEGMENT, key) else ''

    def row_for(self, data):
        types = {'PARODY': [], 'TAG': [], 'ARTIST': [], 'GROUP': []}
        if isinstance(data, dict):
            for row in items(data, 'tags'):
                if isinstance(row, dict) and isinstance(row.get('name'), str) and row.get('category') in types:
                    types[row['category']].append(row['name'])
        return self.entry(data, 'coverUrl', tags=[*types['TAG'], *types['PARODY']],
                          authors=[*types['ARTIST'], *types['GROUP']])

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'page': page, 'limit': 24}
        if query:
            target = query_url(self.ROOT + '/api/v1/search', q=query, **args)
        else:
            target = query_url(self.ROOT + '/api/v1/manga', sort='newest' if sort == 'updated' else 'popular-today', **args)
        data = self.json(http, target)
        if data.get('ok') is not True:
            raise SourceError('Doujiva отклонил запрос каталога.')
        return [row for item in items(data, 'data') if (row := self.row_for(item))], (
            number((data.get('meta') or {}).get('totalPages')) or 0) > page

    def series(self, http, url):
        key = self.title_key(url)
        data = self.json(http, self.ROOT + '/api/v1/manga/' + key, url)
        current = data.get('data')
        row = self.row_for(current)
        if not row or self.title_key(row['url']) != key:
            raise SourceError('Doujiva не предоставил карточку тайтла.')
        chapters = {}
        for entry in items(current, 'chapters'):
            cid = str(entry.get('id') or '') if isinstance(entry, dict) else ''
            if not re.fullmatch(SEGMENT, cid):
                continue
            n = number(entry.get('number'))
            label = str(entry.get('title') or (f'Chapter {n:g}' if n is not None else ''))
            target = self.ROOT + '/manga/' + key + '/chapter/' + cid
            chapters[target] = self.chapter(target, label, n, str(entry.get('createdAt') or '')[:10])
        return row, self.order(chapters)

    def pages(self, http, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        data = self.json(http, f'{self.ROOT}/api/v1/manga/{match[1]}/chapters/{match[2]}', url)
        return [image_url(row.get('imageUrl'), url) for row in items(data, 'data') if isinstance(row, dict)]


class ComicLand(SlugAPI):
    API = 'https://' + COMICLAND + '/api'

    def __init__(self):
        super().__init__(('6347123306532384776', 'ComicLand', 'en', 'https://comicland.org', True),
                         rf'/comic/{SLUG}/?', rf'/comic/{SLUG}/chapter/({ORDINAL})/?', '/comic/')

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        n = urlsplit(target).path.strip('/')
        return title.rstrip('/') + '/chapter/' + n if self.is_title(title) and re.fullmatch(ORDINAL, n) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'offset': (page - 1) * 20, 'limit': 20}
        if query:
            route = '/comic/search'
            args['q'] = query
        elif tag in ('recommended', 'ongoing') or sort == 'updated':
            route = '/comics'
            if tag == 'ongoing' or sort == 'updated':
                args['status'] = 'ongoing'
        else:
            route = '/comics/official' if tag == 'official' else '/comics/popular'
        data = self.json(http, query_url(self.API + route, **args)).get('data') or {}
        current = data.get('list') if isinstance(data.get('list'), list) else items(data, 'items')
        return [row for item in current if (row := self.entry(item, 'cover_url'))], bool(
            data.get('has_more', len(current) == 20))

    def vocabulary(self, http):
        return [{'label': label, 'sourceId': key, 'category': 'tag'} for key, label in (
            ('recommended', 'Recommended'), ('official', 'Official'), ('ongoing', 'Ongoing'))]

    def series(self, http, url):
        key = self.title_key(url)
        data = self.json(http, query_url(self.API + '/comic/detail', slug=key), url).get('data') or {}
        names = lambda field: [row['name'] for row in items(data, field) if isinstance(row, dict) and isinstance(row.get('name'), str)]
        row = self.entry(data, 'cover_url', genres=names('genres'), authors=names('authors'))
        if not row or self.title_key(row['url']) != key:
            raise SourceError('ComicLand не предоставил карточку тайтла.')
        chapters = {}
        for item in items(data, 'chapters'):
            index = number(item.get('chapter_index')) if isinstance(item, dict) else None
            if index is not None:
                target = f'{self.ROOT}/comic/{key}/chapter/{index:.4f}'.rstrip('0').rstrip('.')
                chapters[target] = self.chapter(target, item.get('title') or '', index)
        return row, self.order(chapters)

    def pages(self, http, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        target = query_url(self.API + '/chapter/pages_by_index', slug=match[1], index=match[2])
        data = self.json(http, target, url).get('data') or {}
        return [image_url(item, url) for item in items(data, 'pages')]


class LoLoBun(SlugAPI):
    cards = Cards('.section-item:has(a.name[href^="/c/"])', 'a.name', cover='img.cover')
    meta = Meta('.header-item-info .name', 'img.header-item-cover', '#comic-desc', status='.header-item-info .info')

    def __init__(self):
        super().__init__(('5291930108967632324', 'LoLoBun', 'en', 'https://' + LOLOBUN, False),
                         rf'/c/({ENTITY})/?', rf'/c/({ENTITY})/({ENTITY})/?', '/c/')

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        target = self.ROOT + '/c/' + urlsplit(target).path.strip('/')
        return target if self.is_chapter(target) and self.chapter_key(target) == self.title_key(title) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if not query:
            return (self.card_rows(*self.document(http, self.ROOT + '/'), self.cards)[0], False) if page == 1 else ([], False)
        data = self.json(http, query_url(self.ROOT + '/ajax/Common.ashx', op='searchWorks', q=query, type='comic', pi=page - 1))
        result = data.get('data') or {}
        rows = []
        for item in items(result, 'Items'):
            key = str(item.get('EntityId') or '') if isinstance(item, dict) else ''
            title = item.get('Title') if key else ''
            if re.fullmatch(ENTITY, key) and isinstance(title, str) and title:
                url = self.ROOT + '/c/' + key
                rows.append(self.record(url, title, image_url(item.get('Cover'), 'https://osrs.sfacg.com/web/comic/images/Logo/')))
        return rows, bool(result.get('HasMore'))

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        row = self.metadata(doc, final, self.meta)
        status, *genres = (value.strip() for value in row['status'].split('·'))
        row.update(status=status.lower(), genres=genres)
        chapters, previous, extra = {}, 0, 0
        date = release_date(node_text(doc.select_one('.lastest-update-time')), '%m/%d/%Y')
        nodes = doc.select('.catalog-list .catalog-item')
        for index, item in enumerate(nodes):
            anchor = item.select_one('.title a[href]')
            target = self.site_link(anchor['href'], final) if anchor else ''
            if not self.is_chapter(target) or self.chapter_key(target) != self.title_key(final):
                continue
            label = node_text(anchor)
            if match := re.fullmatch(r'chapter\s*(' + ORDINAL + ')', label, re.I):
                previous, extra = number(match[1]), 0
            else:
                extra += 1
            if not item.select_one('.icon-box img[src*="lock"]'):
                chapters[target] = self.chapter(target, label, previous + extra / 100, date if index == len(nodes) - 1 else '')
        return row, self.order(chapters)

    def pages(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        key = urlsplit(url).path.strip('/').rsplit('/', 1)[-1]
        raw, final, _ = http.document(LOLO_PAGES, method='POST', data={'chapId': key},
                                      headers={'Referer': url}, action='native-series-form')
        try:
            if final != LOLO_PAGES:
                raise ValueError('Invalid endpoint')
            data = json.loads(raw)['data']
            if not isinstance(data, list) or not data:
                raise SourceAccessError('LoLoBun не предоставил открытую версию главы.')
            return [image_url(item, url) for item in data]
        except (KeyError, TypeError, ValueError, RecursionError):
            raise SourceError('LoLoBun изменил формат списка страниц.') from None


SOURCES = (Doujiva(), ComicLand(), LoLoBun())
