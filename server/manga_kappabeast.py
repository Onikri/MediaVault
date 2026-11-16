"""Kappa Beast Strapi catalogue and chapter HTML."""

import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_direct_catalogues import SERIES, SLUG
from manga_direct_payloads import JsonSeries, items, segment
from manga_madara import SEGMENT, image_url
from manga_series_port import NUMBER, number
from manga_source_tags import labels
from manga_webcomics import query_url
from source_parser import SourceError


HOST = 'strapi.kappabeast.com'
API = 'https://' + HOST + '/api'
KEY = r'[A-Za-z0-9_-]{1,100}'
BROWSE_FIELDS = {'populate[media][populate]': '*', 'populate[category][fields][0]': 'name'}
CHAPTER_FIELDS = {'populate[chapters][fields][0]': 'number', 'populate[chapters][fields][1]': 'title',
                  'populate[chapters][fields][2]': 'createdAt', 'populate[chapters][sort][0]': 'number:desc'}
GENRES = ('Fantasy', 'Romance', 'Comedy', 'Drama', 'Thriller', 'Action', 'Psychological', 'Isekai')


def public_api(host, path, query):
    if host != HOST or path not in {'/api/mangas', '/api/chapters'}:
        return False
    args = parse_qs(query)
    if not all(len(v) == 1 and 1 <= len(v[0]) <= 180 for v in args.values()):
        return False
    values = {key: val[0] for key, val in args.items()}
    if path.endswith('/chapters'):
        return (set(values) == {'filters[manga][documentId][$eq]', 'filters[number][$eq]', 'pagination[pageSize]'}
                and values['pagination[pageSize]'] == '1' and bool(re.fullmatch(KEY, values['filters[manga][documentId][$eq]']))
                and bool(re.fullmatch(NUMBER, values['filters[number][$eq]'])))
    if not all(values.pop(key, None) == value for key, value in BROWSE_FIELDS.items()):
        return False
    if 'filters[slug][$eq]' in values:
        slug = values.pop('filters[slug][$eq]')
        return values.pop('pagination[pageSize]', None) == '1' and values in ({}, CHAPTER_FIELDS) and bool(segment(slug))
    return (values.pop('pagination[pageSize]', None) == '20' and bool(re.fullmatch(r'[1-9]\d{0,3}', values.pop('pagination[page]', '')))
            and set(values) <= {'filters[title][$containsi]', 'filters[category][name][$eq]', 'sort[0]'}
            and values.get('sort[0]', 'updatedAt:desc') == 'updatedAt:desc')


class KappaBeast(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, SERIES, rf'/reader/{SLUG}/({NUMBER})/?', interval=.35)

    def title_for(self, url):
        return self.ROOT + '/series/' + self.chapter_key(url)

    def saved_title_url(self, url):
        if isinstance(url, str) and re.fullmatch(rf'{SEGMENT}#{KEY}', url):
            return self.ROOT + '/series/' + url.partition('#')[0]
        return super().saved_title_url(url)

    def saved_chapter(self, row, root, title):
        url = row.get('url') or ''
        if isinstance(url, str) and re.fullmatch(rf'{SEGMENT}/{NUMBER}#{KEY}', url):
            return self.ROOT + '/reader/' + url
        return super().saved_chapter(row, root, title)

    def chapter_identity(self, url):
        parts = urlsplit(url)
        match = self.CHAPTER_PATH.fullmatch(parts.path)
        if match:
            return match[1], number(match[2])
        return '', None

    def data(self, http, route, fields):
        return self.json(http, query_url(API + route, **fields))

    def record_data(self, row):
        slug = segment(row.get('slug'))
        name = row.get('title')
        if not slug or not isinstance(name, str) or not name.strip():
            raise SourceError('Kappa Beast не предоставил карточку тайтла.')
        media = row.get('media') or []
        cover = (media[0].get('coverImage') or {}) if media and isinstance(media[0], dict) else {}
        result = self.record(self.ROOT + '/series/' + slug, name, image_url(cover.get('url'), 'https://' + HOST),
                             genres=labels(row.get('category')), authors=[row.get('author')],
                             status=str(row.get('manga_status') or '').casefold(), description=row.get('description') or '')
        result['artists'] = labels([row.get('artist')])
        return result

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        fields = {**BROWSE_FIELDS, 'pagination[page]': page, 'pagination[pageSize]': '20'}
        if query:
            fields['filters[title][$containsi]'] = query
        if tag:
            fields['filters[category][name][$eq]'] = tag[:120]
        if sort == 'updated':
            fields['sort[0]'] = 'updatedAt:desc'
        data = self.data(http, '/mangas', fields)
        return [self.record_data(row) for row in items(data, 'data') if isinstance(row, dict)], (
            page < (number(((data.get('meta') or {}).get('pagination') or {}).get('pageCount')) or page))

    def vocabulary(self, http):
        return [{'label': genre, 'sourceId': genre, 'category': 'genre'} for genre in GENRES]

    def lookup(self, http, url, chapters=False):
        slug = self.title_key(url)
        if not slug:
            raise SourceError('Некорректная ссылка на тайтл Kappa Beast.')
        fields = {**BROWSE_FIELDS, 'filters[slug][$eq]': slug, 'pagination[pageSize]': '1'}
        if chapters:
            fields.update(CHAPTER_FIELDS)
        rows = items(self.data(http, '/mangas', fields), 'data')
        row = rows[0] if rows else None
        if not isinstance(row, dict) or segment(row.get('slug')) != slug:
            raise SourceError('Kappa Beast вернул другой тайтл.')
        return row, slug

    def details(self, http, url):
        row, _ = self.lookup(http, self.saved_title_url(url))
        return self.record_data(row)

    def series(self, http, url):
        data, slug = self.lookup(http, url, chapters=True)
        key = data.get('documentId')
        if not isinstance(key, str) or not re.fullmatch(KEY, key):
            raise SourceError('Kappa Beast не предоставил ID оглавления.')
        rows = {}
        for chapter in items(data, 'chapters'):
            if not isinstance(chapter, dict) or (n := number(chapter.get('number'))) is None:
                continue
            dest = f'{self.ROOT}/reader/{slug}/{float(n)}#{key}'
            label = chapter.get('title') or f'Chapter {n:g}'
            rows[dest] = self.chapter(dest, label, n, str(chapter.get('createdAt') or '')[:10])
        return self.record_data(data), self.order(rows)

    def pages(self, http, url):
        parts = urlsplit(url)
        match = self.CHAPTER_PATH.fullmatch(parts.path)
        if not re.fullmatch(KEY, parts.fragment):
            raise SourceError('Обнови оглавление Kappa Beast.')
        options = {'filters[manga][documentId][$eq]': parts.fragment,
                   'filters[number][$eq]': match[2], 'pagination[pageSize]': '1'}
        rows = items(self.data(http, '/chapters', options), 'data')
        html = rows[0].get('htmlContent') if rows and isinstance(rows[0], dict) else None
        if not isinstance(html, str):
            raise SourceError('Kappa Beast не предоставил страницы главы.')
        result = []
        for node in BeautifulSoup(html, 'html.parser').select('div.separator > a[href]'):
            image = urlsplit(image_url(node['href'], self.ROOT))
            path = image.path.split('/')
            if len(path) > 5 and re.fullmatch(r's\d+(?:-[a-z]+)?', path[5]):
                path[5] = 's0'
            result.append(urlunsplit(image._replace(path='/'.join(path))))
        return result
