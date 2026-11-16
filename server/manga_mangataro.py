"""MangaTaro and Rolia Scan public catalogue and reader APIs."""

import hashlib
import json
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from time import time
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from manga_direct_catalogues import MANGA, SLUG
from manga_direct_payloads import JsonSeries, items, segment
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_mangataro_terms import TERMS
from manga_series_port import MAX_CHAPTERS, number
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


HOSTS = {'mangataro.org', 'roliascan.com'}
LOAD = '/wp-json/manga/v1/load'
SEARCH = '/auth/search'
DETAILS = '/wp-json/wp/v2/manga/'
OUTLINE = '/auth/manga-chapters'
PAGES = '/auth/chapter-content'
KEY = r'[1-9]\d{0,14}'
SLICE_SIZE = 24
CHAPTER_LIMIT = 500
BROWSE_FIELDS = {'page', 'search', 'years', 'genres', 'types', 'statuses', 'sort', 'genreMatchMode'}


def chapter_token(timestamp):
    formatted = datetime.fromtimestamp(timestamp, UTC).strftime('%Y%m%d%H')
    return hashlib.md5(f'{timestamp}mng_ch_{formatted}'.encode(), usedforsecurity=False).hexdigest()[:16]


def public_form(url, data):
    parts = urlsplit(url)
    if parts.netloc not in HOSTS or parts.query or parts.path not in {LOAD, SEARCH} or not isinstance(data, bytes) or len(data) > 2500:
        return False
    try:
        value = json.loads(data)
    except (ValueError, RecursionError):
        return False
    if not isinstance(value, dict):
        return False
    if parts.path == SEARCH:
        return (parts.netloc == 'mangataro.org' and set(value) == {'limit', 'query'} and value['limit'] == 25
                and isinstance(value['query'], str) and 1 <= len(value['query']) <= 160)
    return (set(value) == BROWSE_FIELDS and type(value['page']) is int and 1 <= value['page'] <= 10000
            and isinstance(value['search'], str) and len(value['search']) <= 160
            and value['years'] == value['types'] == value['statuses'] == '[]'
            and value['sort'] in ('popular_desc', 'post_desc') and value['genreMatchMode'] == 'any'
            and isinstance(value['genres'], str) and bool(re.fullmatch(r'\[(?:[1-9]\d{0,5})?\]', value['genres'])))


def public_api(host, path, query):
    if host not in HOSTS:
        return False
    if re.fullmatch(DETAILS + KEY, path):
        return query == '_embed'
    if path == LOAD:
        return not query
    if path == OUTLINE:
        args = parse_qs(query)
        if set(args) != {'manga_id', 'offset', 'limit', 'order', '_t', '_ts'} or not all(len(v) == 1 for v in args.values()):
            return False
        stamp = args['_ts'][0]
        return (args['limit'] == ['500'] and args['order'] == ['DESC']
                and bool(re.fullmatch(KEY, args['manga_id'][0])) and bool(re.fullmatch(r'\d{1,6}', args['offset'][0]))
                and bool(re.fullmatch(r'\d{10}', stamp)) and args['_t'][0] == chapter_token(int(stamp)))
    return path == PAGES and bool(re.fullmatch(rf'chapter_id={KEY}', query))


class MangaTaro(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, MANGA, rf'/read/{SLUG}/{SEGMENT}/?', interval=.35)
        self.rolia = self.hostname == 'roliascan.com'
        self.skew = 0

    def saved_title_url(self, value):
        if isinstance(value, str) and len(value) <= 600 and value.startswith('{'):
            try:
                doc = json.loads(value)
                slug, key = segment(doc['slug']), str(doc['id'])
                if slug and re.fullmatch(KEY, key):
                    return query_url(self.ROOT + '/manga/' + slug, mv_id=key)
            except (TypeError, ValueError, KeyError):
                return ''
        return super().saved_title_url(value)

    def title_for(self, url):
        return self.ROOT + '/manga/' + self.chapter_key(url)

    def post(self, http, route, payload):
        endpoint = self.ROOT + route
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(endpoint, method='POST', headers={'Referer': self.ROOT + '/'},
                                      action='mangataro-form', data=json.dumps(payload, ensure_ascii=False).encode())
        if final != endpoint:
            raise SourceError('Источник перенаправил запрос публичного поиска.')
        try:
            return json.loads(raw)
        except (ValueError, RecursionError):
            raise SourceError('Источник изменил формат каталога.') from None

    def list_row(self, item):
        if not isinstance(item, dict) or item.get('type') == 'Novel':
            return None
        key, title = str(item.get('id', '')), item.get('title')
        slug = segment(item.get('slug'))
        if not slug:
            href = self.site_link(item.get('url'))
            slug = self.title_key(href) or self.chapter_key(href)
        if not slug or not re.fullmatch(KEY, key) or not isinstance(title, str) or not title.strip():
            return None
        target = query_url(self.ROOT + '/manga/' + slug, mv_id=key)
        row = self.record(target, unescape(title), image_url(item.get('thumbnail') or item.get('cover'), self.ROOT),
                          description=unescape(str(item.get('description') or '')), status=str(item.get('status') or '').casefold())
        if isinstance(item.get('type'), str) and item['type']:
            row['format'] = item['type'].casefold()
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query and not (tag or self.rolia):
            if page != 1:
                return [], False
            data = self.post(http, SEARCH, {'limit': 25, 'query': query})
            return [row for item in items(data, 'results') if (row := self.list_row(item))], False
        if tag and not re.fullmatch(r'[1-9]\d{0,5}', tag):
            raise SourceError('Некорректная метка каталога.')
        requests = 5 if self.rolia and (query or tag or sort == 'updated') else 1
        start = (page - 1) * requests + 1
        payload = {'search': query, 'years': '[]', 'genres': f'[{tag}]', 'types': '[]', 'statuses': '[]',
                   'sort': 'post_desc' if sort == 'updated' else 'popular_desc', 'genreMatchMode': 'any'}
        found, more = {}, False
        for n in range(start, start + requests):
            data = self.post(http, LOAD, dict(payload, page=n))
            if not isinstance(data, list):
                raise SourceError('Источник изменил формат каталога.')
            for item in data:
                if row := self.list_row(item):
                    found[row['id']] = row
            more = len(data) == SLICE_SIZE
            if not more:
                break
        return list(found.values()), more

    def vocabulary(self, http):
        return [{'label': name, 'sourceId': str(key), 'category': 'tag'} for key, name in TERMS[self.hostname]]

    def source_details(self, http, url):
        slug = self.title_key(url)
        if not slug:
            raise SourceError('Некорректная ссылка на тайтл.')
        key, status = param(url, 'mv_id'), ''
        if not re.fullmatch(KEY, key):
            doc, _ = self.title_document(http, self.ROOT + '/manga/' + slug)
            body = doc.select_one('body[data-manga-id]')
            key = body.get('data-manga-id', '') if body else ''
            statuses = [node_text(node).casefold() for node in doc.select('.capitalize')]
            status = next((value for value in statuses if value in {'ongoing', 'completed'}), '')
            if 'novel' in statuses or not re.fullmatch(KEY, key):
                raise SourceError('Источник не предоставил карточку манги.')
        item = self.json(http, self.ROOT + DETAILS + key + '?_embed')
        if not isinstance(item, dict) or str(item.get('id')) != key or segment(item.get('slug')) != slug:
            raise SourceError('Источник вернул другой тайтл.')
        embedded = item.get('_embedded') or {}
        gallery = embedded.get('wp:featuredmedia') or []
        cover = gallery[0].get('source_url') if gallery and isinstance(gallery[0], dict) else ''
        terms = {}
        for term_group in embedded.get('wp:term') or []:
            for term in term_group if isinstance(term_group, list) else []:
                if isinstance(term, dict) and isinstance(term.get('name'), str) and isinstance(term.get('taxonomy'), str):
                    terms.setdefault(term['taxonomy'], []).append(term['name'])
        title = unescape((item.get('title') or {}).get('rendered') or '')
        content = (item.get('content') or {}).get('rendered') or ''
        if not title.strip():
            raise SourceError('Источник не предоставил название тайтла.')
        row = self.record(query_url(self.ROOT + '/manga/' + slug, mv_id=key), title, image_url(cover, self.ROOT),
                          description=node_text(BeautifulSoup(content, 'html.parser')), tags=terms.get('post_tag', ()),
                          genres=terms.get('manga_genre', ()), authors=terms.get('manga_author', ()), status=status)
        if isinstance(item.get('type'), str):
            row['format'] = item['type'].casefold()
        return row, key

    def details(self, http, url):
        return self.source_details(http, self.saved_title_url(url))[0]

    def outline(self, http, key, offset):
        def endpoint():
            stamp = int(time()) + self.skew
            return query_url(self.ROOT + OUTLINE, manga_id=key, offset=offset, limit=CHAPTER_LIMIT, order='DESC',
                             _t=chapter_token(stamp), _ts=stamp)

        try:
            return self.json(http, endpoint())
        except SourceAccessError:
            _, final, headers = http.document(self.ROOT + '/', method='HEAD')
            if urlsplit(final).netloc != self.hostname:
                raise
            try:
                server = parsedate_to_datetime(headers.get('Date') or headers.get('date') or '')
                self.skew = round(server.timestamp() - time())
            except (ValueError, OverflowError):
                raise SourceAccessError('Источник не принял запрос оглавления.') from None
            if abs(self.skew) > 3600:
                raise SourceAccessError('Часы источника вне допустимого диапазона.')
            return self.json(http, endpoint())

    def series(self, http, url):
        row, key = self.source_details(http, url)
        slug = self.title_key(url)
        chapters, offset = {}, 0
        while offset < MAX_CHAPTERS:
            data = self.outline(http, key, offset)
            records = items(data, 'chapters')
            for item in records:
                if not isinstance(item, dict) or str(item.get('language') or '').casefold() != self.LANGUAGE.casefold():
                    continue
                link = self.site_link(item.get('url'))
                if not self.is_chapter(link) or self.chapter_key(link) != slug:
                    continue
                n = number(item.get('chapter'))
                title = str(item.get('title') or '').strip()
                label = f'Chapter {item.get("chapter", "")}'
                if title not in {'', 'N/A', '—'}:
                    label += ': ' + unescape(title)
                date = release_date(str(item.get('date') or ''), '%Y-%m-%d')
                translator = item.get('group_name')
                chapters[link] = self.chapter(link, label, n, date, translator=translator if translator not in (None, '', 'N/A', '—') else '')
            if not records or data.get('has_more') is not True:
                return row, self.order(chapters)
            offset += len(records)
        raise SourceError('Источник не предоставил полное оглавление.')

    def pages(self, http, url):
        key = urlsplit(url).path.rstrip('/').rsplit('-', 1)[-1]
        if not re.fullmatch(KEY, key):
            raise SourceError('Обнови оглавление источника.')
        data = self.json(http, query_url(self.ROOT + PAGES, chapter_id=key), url)
        return [image_url(value, self.ROOT) for value in items(data, 'images')]
