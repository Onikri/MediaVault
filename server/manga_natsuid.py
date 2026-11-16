"""Public Rawkuma catalogue, WordPress metadata and chapter reader."""

import json
import re
from html import unescape
from threading import Lock
from time import monotonic
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

from bs4 import BeautifulSoup

from manga_direct_catalogues import MANGA
from manga_direct_payloads import JsonSeries, segment
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import picture
from manga_webcomics import query_url
from source_parser import SourceError


ROOT = 'https://rawkuma.net'
AJAX = '/wp-admin/admin-ajax.php'
WP = '/wp-json/wp/v2/'
NONCE = re.compile(r'[A-Za-z0-9_-]{6,80}')
KEY = re.compile(r'[1-9]\d{0,13}')
CHAPTER = rf'/({SEGMENT}(?:/{SEGMENT}){{0,3}})/?'
STATUS = {'Ongoing': 'ongoing', 'Completed': 'completed', 'Cancelled': 'cancelled', 'On Hiatus': 'hiatus'}
DEFAULT_FORM = dict(inclusion='OR', exclusion='OR', genre_exclude='[]', author='[]', artist='[]', project='0',
                    type='[]', status='[]', order='desc')


def rawkuma_url(slug):
    return ROOT + f'/manga/{slug}/'


def slug_param(url):
    return next(iter(parse_qs(urlsplit(url).query).get('mv_id', [])), '')


class Rawkuma(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, MANGA, CHAPTER, interval=.35)
        self._nonce = ('', 0)
        self._nonce_lock = Lock()

    def is_chapter(self, url):
        parent = self.parent_path(url)
        return (super().is_chapter(url) and re.fullmatch(MANGA, parent) is not None
                and urlsplit(url).path.rstrip('/') != parent.rstrip('/'))

    @staticmethod
    def parent_path(url):
        return next(iter(parse_qs(urlsplit(url).query).get('mv_parent', [])), '')

    def title_for(self, url):
        return self.ROOT + self.parent_path(url)

    def saved_title_url(self, value):
        if isinstance(value, str) and value.startswith('{') and len(value) <= 640:
            try:
                row = json.loads(value)
                key, slug = str(row['id']), segment(row['slug'])
                if key and KEY.fullmatch(key) and slug:
                    return query_url(rawkuma_url(slug), mv_id=key)
            except (KeyError, TypeError, ValueError):
                return ''
        return super().saved_title_url(value)

    def ajax(self, http, url, form=None):
        self.origin.wait(getattr(http, 'deadline', None))
        kwargs = {'method': 'POST', 'data': form, 'action': 'natsuid-search'} if form is not None else {
            'action': 'native-series-html-api'
        }
        body, final, _ = http.document(self.ROOT + url, headers={'Referer': self.ROOT + '/'}, **kwargs)
        if final != self.ROOT + url:
            raise SourceError('Источник перенаправил запрос каталога.')
        return BeautifulSoup(body, 'html.parser')

    def nonce(self, http, rejected=''):
        with self._nonce_lock:
            value, expires = self._nonce
            if expires > monotonic() and value != rejected:
                return value
            doc = self.ajax(http, AJAX + '?type=search_form&action=get_nonce')
            node = doc.select_one('input[name=search_nonce][value]')
            value = node.get('value', '') if node else ''
            if not NONCE.fullmatch(value):
                raise SourceError('Источник не предоставил параметры поиска.')
            self._nonce = value, monotonic() + 1800
            return value

    def from_wp(self, data):
        if not isinstance(data, dict):
            return None
        slug, key = segment(data.get('slug')), str(data.get('id', ''))
        title = unescape((data.get('title') or {}).get('rendered') or '')
        if not slug or not KEY.fullmatch(key) or not title:
            return None
        embedded = data.get('_embedded') or {}
        taxonomy = {}
        for group in embedded.get('wp:term') or []:
            for row in group if isinstance(group, list) else []:
                if isinstance(row, dict) and row.get('name') and row.get('taxonomy'):
                    taxonomy.setdefault(row['taxonomy'], []).append(unescape(row['name']))
        if 'Novel' in taxonomy.get('type', ()):
            return None
        wp_cover = embedded.get('wp:featuredmedia') or []
        yoast = (data.get('yoast_head_json') or {}).get('og_image') or []
        cover = (wp_cover[0].get('source_url', '') if wp_cover else '') or (yoast[0].get('url', '') if yoast else '')
        description = node_text(BeautifulSoup((data.get('content') or {}).get('rendered') or '', 'html.parser'))
        meta = (data.get('meta') or data.get('metadata') or {}).get('meta') or {}
        aliases = [unescape(item.strip()) for item in str(meta.get('alternative_title') or '').split(',') if item.strip()]
        record = self.record(query_url(rawkuma_url(slug), mv_id=key), title, image_url(cover, self.ROOT),
                             description=description, aliases=aliases, genres=taxonomy.get('genre', ()),
                             tags=taxonomy.get('post_tag', ()), authors=taxonomy.get('series-author', ()),
                             status=next((STATUS[item] for item in taxonomy.get('status', ()) if item in STATUS), ''))
        record['artists'] = taxonomy.get('artist', [])
        return record

    def metadata_by_slugs(self, http, slugs):
        encoded = urlencode([('slug[]', unquote(slug)) for slug in slugs] + [('per_page', len(slugs) + 1), ('_embed', '')]).rstrip('=')
        records = self.json(http, self.ROOT + WP + 'manga?' + encoded)
        if not isinstance(records, list):
            raise SourceError('Источник изменил формат каталога WordPress.')
        rows = {segment(item.get('slug')): self.from_wp(item) for item in records if isinstance(item, dict)}
        return [rows[key] for key in slugs if rows.get(key)]

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and not re.fullmatch(SEGMENT, tag):
            raise SourceError('Некорректный жанр каталога Rawkuma.')
        nonce = self.nonce(http)
        params = {**DEFAULT_FORM, 'page': str(page), 'orderby': 'updated' if sort == 'updated' else 'popular',
                  'query': query, 'genre': json.dumps([tag] if tag else [], ensure_ascii=False)}
        doc = self.ajax(http, AJAX + '?action=advanced_search', {**params, 'nonce': nonce})
        if doc.get_text(strip=True) == '-1':
            doc = self.ajax(http, AJAX + '?action=advanced_search', {**params, 'nonce': self.nonce(http, rejected=nonce)})
        slugs = {}
        for anchor in doc.select('div > a[href*="/manga/"]:has(> img)'):
            url = self.site_link(anchor['href'])
            if key := self.title_key(url):
                slugs[key] = None
        keys = list(slugs)
        rows = [item for offset in range(0, len(keys), 50) for item in self.metadata_by_slugs(http, keys[offset:offset + 50])]
        return rows, bool(keys and doc.select_one('button:has(svg)'))

    def vocabulary(self, http):
        url = self.ROOT + WP + 'genre?per_page=100&page=1&orderby=count&order=desc'
        data = self.json(http, url)
        if not isinstance(data, list):
            raise SourceError('Источник изменил формат справочника жанров.')
        return [{'label': unescape(row['name']), 'sourceId': row['slug'], 'category': 'genre'} for row in data
                if isinstance(row, dict) and isinstance(row.get('name'), str)
                and isinstance(row.get('slug'), str) and re.fullmatch(SEGMENT, row['slug'])]

    def details(self, http, url):
        target = self.saved_title_url(url)
        key = slug_param(target)
        slug = self.title_key(target)
        if not slug:
            raise SourceError('Некорректная ссылка на карточку Rawkuma.')
        if KEY.fullmatch(key):
            item = self.json(http, self.ROOT + WP + 'manga/' + key + '?_embed')
            row = self.from_wp(item)
            if row and self.title_key(row['sourceUrl']) == slug:
                return row
        rows = self.metadata_by_slugs(http, [slug])
        if not rows:
            raise SourceError('Источник не предоставил карточку тайтла.')
        return rows[0]

    def series(self, http, url):
        row = self.details(http, url)
        canonical = self.site_link(row['sourceUrl'])
        parent = urlsplit(canonical).path
        key = slug_param(canonical)
        target = f'{AJAX}?manga_id={key}&page=99&action=chapter_list'
        doc = self.ajax(http, target)
        chapters = {}
        for anchor in doc.select('div a[href]:has(time)'):
            url = self.site_link(anchor['href'], self.ROOT)
            label = node_text(anchor.select_one('span'))
            date = anchor.select_one('time[datetime]')
            if not url or not label:
                continue
            url = query_url(url, mv_parent=parent)
            if self.is_chapter(url):
                chapters[url] = self.chapter(url, label, date=date['datetime'][:10] if date else '')
        return row, self.order(chapters)

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_title(title) and re.fullmatch(self.CHAPTER_PATH, urlsplit(target).path):
            return query_url(target.split('?')[0], mv_parent=urlsplit(title).path)
        return ''

    def saved_chapter_matches(self, target, title):
        slug = self.title_key(title)
        return bool(slug and slug == self.title_key(self.title_for(target)))

    def pages(self, http, url):
        url = url.split('?')[0]
        doc, final = self.document(http, url)
        if urlsplit(final).path.rstrip('/') != urlsplit(url).path.rstrip('/'):
            raise SourceError('Источник перенаправил запрос на другой выпуск.')
        return [picture(node, final) for node in doc.select('section[data-image-data] img[src]')]


def public_api(host, path, query):
    if host != 'rawkuma.net':
        return False
    if path == AJAX:
        return query in {'type=search_form&action=get_nonce', 'action=advanced_search'} or bool(re.fullmatch(
            r'manga_id=[1-9]\d{0,13}&page=99&action=chapter_list', query))
    if path == WP + 'genre':
        return query == 'per_page=100&page=1&orderby=count&order=desc'
    if re.fullmatch(r'/wp-json/wp/v2/manga/[1-9]\d{0,13}', path):
        return query == '_embed'
    if path != WP + 'manga':
        return False
    args = parse_qs(query, keep_blank_values=True)
    slugs = args.get('slug[]', ())
    return (set(args) == {'slug[]', 'per_page', '_embed'} and 1 <= len(slugs) <= 50
            and args['per_page'] == [str(len(slugs) + 1)] and args['_embed'] == ['']
            and all(segment(slug) for slug in slugs))


def public_form(url, data):
    if url != ROOT + AJAX + '?action=advanced_search' or not isinstance(data, dict):
        return False
    fields = {'nonce', 'page', 'orderby', 'query', 'genre'}
    if set(data) != fields | set(DEFAULT_FORM) or not all(isinstance(item, str) for item in data.values()):
        return False
    try:
        genres = json.loads(data['genre'])
    except (ValueError, RecursionError):
        return False
    return (all(data[key] == value for key, value in DEFAULT_FORM.items())
            and bool(NONCE.fullmatch(data['nonce'])) and bool(re.fullmatch(r'[1-9]\d{0,3}', data['page']))
            and data['orderby'] in ('updated', 'popular') and len(data['query']) <= 160
            and isinstance(genres, list) and len(genres) <= 1
            and all(isinstance(genre, str) and re.fullmatch(SEGMENT, genre) for genre in genres))
