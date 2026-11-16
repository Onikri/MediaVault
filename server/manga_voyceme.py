"""VoyceMe public read-only GraphQL queries for catalogue and episodes."""

import json
import re
from html import unescape
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries, items
from manga_madara import SEGMENT, image_url, node_text
from source_parser import SourceError

ROOT = 'https://www.voyce.me'
HOST = 'hasura.voyce.me'
GRAPHQL = 'https://' + HOST + '/v1/graphql'
STATIC = 'https://dlkfxmdtxtzpb.cloudfront.net/'
IDS = r'[1-9]\d{0,9}'
SERIES = rf'/series/({SEGMENT})/?'
CHAPTER = rf'/series/({SEGMENT})/({IDS})/?'
LIMIT = 10
BASE_FILTER = 'publish: {_eq: 1}, type: {id: {_in: [2, 4]}}'
SUMMARY = 'id slug thumbnail title'
BY_VIEWS = 'views_counts: {count: desc_nulls_last}'


def listing(name, condition, sort):
    query_type = '$limit: Int, $offset: Int' + (', $searchTerm: String!' if condition else '')
    filters = BASE_FILTER + (', ' + condition if condition else '')
    return (f'query {name}({query_type}) {{ voyce_series(where: {{{filters}}}, order_by: [{{{sort}}}], '
            f'limit: $limit, offset: $offset) {{ {SUMMARY} }} }}')


QUERIES = {
    'Catalogue': listing('Catalogue', '', BY_VIEWS),
    'Latest': listing('Latest', '', 'updated_at: desc'),
    'Search': listing('Search', 'title: {_ilike: $searchTerm}', BY_VIEWS),
    'Series': ('query Series($slug: String!) { voyce_series(where: {' + BASE_FILTER + ', slug: {_eq: $slug}}, limit: 1) { '
               + SUMMARY + ' description status author { username } genres(order_by: [{genre: {title: asc}}]) { genre { title } } '
               'chapters(order_by: [{created_at: desc}]) { id title created_at } } }'),
    'Pages': ('query Pages($chapterId: Int!) { voyce_chapter_images(where: {chapter_id: {_eq: $chapterId}}, '
              'order_by: {sort_order: asc}) { image } }'),
}


def public_api(host, path, query):
    return host == HOST and path == '/v1/graphql' and not query


def public_form(value, raw):
    if value != GRAPHQL or not isinstance(raw, bytes) or len(raw) > 4096:
        return False
    try:
        data = json.loads(raw)
        name = data['operationName']
        args = data['variables']
        if set(data) != {'operationName', 'query', 'variables'} or data['query'] != QUERIES.get(name) or not isinstance(args, dict):
            return False
        if name in ('Catalogue', 'Latest', 'Search'):
            fields = {'limit', 'offset'} | ({'searchTerm'} if name == 'Search' else set())
            query = args.get('searchTerm', '%%')
            return (set(args) == fields and type(args['limit']) is int and args['limit'] == LIMIT
                    and type(args['offset']) is int and 0 <= args['offset'] < LIMIT * 2000 and args['offset'] % LIMIT == 0
                    and isinstance(query, str) and 2 <= len(query) <= 162 and query.startswith('%') and query.endswith('%'))
        if name == 'Series':
            return set(args) == {'slug'} and isinstance(args['slug'], str) and bool(re.fullmatch(SEGMENT, args['slug']))
        return (name == 'Pages' and set(args) == {'chapterId'} and type(args['chapterId']) is int
                and 0 < args['chapterId'] <= 2_147_483_647)
    except (AttributeError, TypeError, KeyError, ValueError):
        return False


def static(value):
    if not isinstance(value, str) or value.startswith(('http:', 'https:', '//')):
        return ''
    return image_url(STATIC + value.lstrip('/'), STATIC) if value else ''


class VoyceMe(JsonSeries):
    def __init__(self):
        super().__init__(('4815322300278778429', 'VoyceMe', 'en', ROOT, False),
                         SERIES, CHAPTER, hosts=('voyce.me',), interval=1)

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + '/series/' + key if key else ''

    def build(self, data):
        slug, title = data.get('slug', ''), data.get('title')
        if not isinstance(title, str) or not title or not re.fullmatch(SEGMENT, slug):
            raise SourceError('VoyceMe не предоставил данные тайтла.')
        author = (data.get('author') or {}).get('username')
        labels = [(item.get('genre') or {}).get('title') for item in data.get('genres') or [] if isinstance(item, dict)]
        description = node_text(BeautifulSoup(unescape(data.get('description') or ''), 'html.parser'))
        return self.record(ROOT + '/series/' + slug, title, static(data.get('thumbnail')),
                           authors=[author], genres=labels, status=data.get('status') or '', description=description)

    def api(self, http, op, **args):
        self.origin.wait(getattr(http, 'deadline', None))
        data = json.dumps({'operationName': op, 'query': QUERIES[op], 'variables': args}, separators=(',', ':')).encode()
        raw, final, _ = http.document(GRAPHQL, method='POST', data=data,
                                     headers={'Referer': ROOT + '/'}, action='voyceme-graphql')
        if final != GRAPHQL:
            raise SourceError('VoyceMe перенаправил публичный запрос.')
        obj = json.loads(raw)
        if obj.get('errors') or not isinstance(obj.get('data'), dict):
            raise SourceError('VoyceMe отклонил публичный запрос.')
        return obj['data']

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'limit': LIMIT, 'offset': (page - 1) * LIMIT}
        if query:
            args['searchTerm'] = '%' + query + '%'
        op = 'Search' if query else 'Latest' if sort == 'updated' else 'Catalogue'
        data = items(self.api(http, op, **args), 'voyce_series')
        return [self.build(row) for row in data], len(data) == LIMIT

    def series(self, http, url):
        key = self.title_key(url)
        matches = items(self.api(http, 'Series', slug=key), 'voyce_series')
        if len(matches) != 1 or matches[0].get('slug') != key:
            raise SourceError('VoyceMe не предоставил выбранное произведение.')
        data = matches[0]
        rows = {}
        for entry in items(data, 'chapters'):
            identity = str(entry.get('id') or '')
            if not re.fullmatch(IDS, identity):
                continue
            target = ROOT + '/series/' + key + '/' + identity
            rows[target] = self.chapter(target, str(entry.get('title') or ''), date=str(entry.get('created_at') or '')[:10])
        return self.build(data), self.order(rows)

    def pages(self, http, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        result = self.api(http, 'Pages', chapterId=int(match[2]))
        return [src for item in items(result, 'voyce_chapter_images') if (src := static(item.get('image')))]


SOURCES = (VoyceMe(),)
