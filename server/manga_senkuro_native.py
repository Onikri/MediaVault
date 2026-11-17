"""Public Senkuro and Senkognito catalogue and reader operations."""

import json
import re
from urllib.parse import urlsplit

from manga_direct_payloads import JsonSeries, items
from manga_madara import image_url
from manga_senkognito import ID, NAMES, SLUG, _names
from manga_series_port import number
from manga_webcomics import param, query_url
from source_parser import SourceError


APPS = {
    'api.senkuro.com': frozenset({'4026531840100'}),
    'api.senkuro.me': frozenset({'4026531840100', '5033164800100'}),
    'api.senkognito.com': frozenset({'5033164800100'}),
}
LABELS = 'id rootId slug titles{lang content}'
CARD = f'id slug {NAMES} cover{{original{{url}}}}'
QUERIES = {
    'search': ('query($query:String,$label:MangaTachiyomiSearchLabelFilter,$offset:Int,$orderBy:MangaTachiyomiOrder)'
               f'{{mangaTachiyomiSearch(query:$query,label:$label,offset:$offset,orderBy:$orderBy){{mangas{{{CARD}}}}}}}'),
    'details': (f'query($mangaId:ID!){{mangaTachiyomiInfo(mangaId:$mangaId){{{CARD} type rating status formats '
                f'translationStatus localizations{{lang description}} labels{{{LABELS}}} mainStaff{{roles person{{name}}}}}}}}'),
    'chapters': ('query($mangaId:ID!){mangaTachiyomiChapters(mangaId:$mangaId)'
                 '{chapters{id slug branchId name number volume teamIds createdAt updatedAt} teams{id name}}}'),
    'pages': 'query($mangaId:ID!,$chapterId:ID!){mangaTachiyomiChapterPages(mangaId:$mangaId,chapterId:$chapterId){pages{url}}}',
    'filters': f'query{{mangaTachiyomiSearchFilters{{labels{{{LABELS}}}}}}}',
}
KEY = {'search': 'mangaTachiyomiSearch', 'details': 'mangaTachiyomiInfo', 'chapters': 'mangaTachiyomiChapters',
       'pages': 'mangaTachiyomiChapterPages', 'filters': 'mangaTachiyomiSearchFilters'}
TYPE = {'MANGA': 'manga', 'MANHWA': 'manhwa', 'MANHUA': 'manhua', 'COMICS': 'comic', 'RU_MANGA': 'rumanga'}
STATUS = {'ONGOING': 'ongoing', 'FINISHED': 'completed', 'HIATUS': 'hiatus', 'CANCELLED': 'cancelled', 'ANNOUNCE': 'announced'}


def public_form(url, payload, app_id):
    parts = urlsplit(url)
    if parts.path != '/graphql' or parts.query or not isinstance(app_id, str) or app_id not in APPS.get(parts.netloc, ()):
        return False
    if not isinstance(payload, bytes) or len(payload) > 4096:
        return False
    try:
        data = json.loads(payload)
    except ValueError:
        return False
    return (isinstance(data, dict) and set(data) == {'query', 'variables'} and data['query'] in QUERIES.values()
            and isinstance(data['variables'], dict))


def public_api(host, path, query):
    return host in APPS and path == '/graphql' and not query


def validate_slug(value, pattern=SLUG):
    return value if isinstance(value, str) and re.fullmatch(pattern, value) else ''


class Senkuro(JsonSeries):
    def __init__(self, identity):
        profile = ('senkuro.me', 'senkognito.com') if identity[-1] else ('senkuro.me', 'senkuro.com')
        super().__init__(identity, rf'/manga/({SLUG})/?', rf'/manga/({SLUG})/chapters/{SLUG}/?',
                         hosts=profile, interval=.35)
        self.app = '5033164800100' if self.IS_NSFW else '4026531840100'

    def graphql(self, http, key, variables=None):
        self.origin.wait(getattr(http, 'deadline', None))
        url = 'https://api.' + self.hostname + '/graphql'
        payload = json.dumps({'query': QUERIES[key], 'variables': variables or {}}).encode()
        text, final, _ = http.document(url, method='POST', action='senkuro-native',
                                       headers={'Referer': self.ROOT + '/', 'App-Id': self.app}, data=payload)
        if final != url:
            raise SourceError('Каталог перенаправил запрос на другой сервер.')
        try:
            body = json.loads(text)
            if body.get('errors') or not isinstance(result := body['data'][KEY[key]], dict):
                raise ValueError('GraphQL')
            return result
        except (ValueError, KeyError, TypeError, AttributeError):
            raise SourceError('Источник не предоставил открытые данные читалки.') from None

    def title_url(self, slug, key=''):
        url = f'{self.ROOT}/manga/{slug}'
        return query_url(url, mv_id=key) if key else url

    def title_for(self, url):
        return self.title_url(self.chapter_key(url), validate_slug(param(url, 'mv_id'), ID))

    def identity(self, http, url):
        slug, key = self.title_key(url), validate_slug(param(url, 'mv_id'), ID)
        if not key:
            result = self.catalogue(http, query=slug.replace('-', ' '))[0]
            key = next((param(self.site_link(row['url']), 'mv_id') for row in result
                        if self.title_key(self.site_link(row['url'])) == slug), '')
        if not key:
            raise SourceError('Не удалось подтвердить ID тайтла.')
        return key

    def saved_title_url(self, url):
        value = self.canonical(url)
        if self.is_title(value):
            return value
        slug = re.fullmatch(rf'/?({ID}),,({SLUG})/?', urlsplit(value).path)
        return self.title_url(slug[2], slug[1]) if slug else ''

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        if self.is_chapter(value):
            return value
        key = re.fullmatch(rf'/?({ID}),,({SLUG}),,({ID}),,({SLUG})/?', urlsplit(value).path)
        if key and key[2] == self.title_key(title) and param(title, 'mv_id') in ('', key[1]):
            url = f'{self.ROOT}/manga/{key[2]}/chapters/{key[4]}'
            return query_url(url, mv_id=key[1], mv_chapter=key[3])
        return ''

    def saved_chapter_matches(self, target, title):
        return super().saved_chapter_matches(target, title) and (
            not param(title, 'mv_id') or param(target, 'mv_id') == param(title, 'mv_id'))

    def record_data(self, row):
        key, slug = validate_slug(row.get('id'), ID), validate_slug(row.get('slug'))
        names = _names(row)
        if not key or not slug or not names:
            raise SourceError('Каталог не предоставил название или ID тайтла.')
        url = self.title_url(slug, key)
        cover = ((row.get('cover') or {}).get('original') or {}).get('url')
        terms = [((entry.get('rootId') == 'TEFCRUw6NQ'), self.label(entry))
                 for entry in row.get('labels') or [] if isinstance(entry, dict)]
        description = next((entry.get('description') or '' for entry in row.get('localizations') or []
                            if isinstance(entry, dict) and entry.get('lang') == 'RU'), '')
        authors = [staff.get('person', {}).get('name', '') for staff in row.get('mainStaff') or [] if isinstance(staff, dict)]
        record = self.record(url, names[0], image_url(cover, url), aliases=names, description=description,
                             genres=[label for genre, label in terms if genre], tags=[label for genre, label in terms if not genre],
                             authors=authors, status=STATUS.get(row.get('status'), ''))
        record['format'] = TYPE.get(row.get('type'), record['format'])
        if row.get('rating') == 'EXPLICIT':
            record['adult'] = True
        return record

    @staticmethod
    def label(row):
        titles = _names(row)
        return titles[0] if titles else str(row.get('slug') or '')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        variables = {'offset': (page - 1) * 10, 'orderBy': {'direction': 'DESC', 'field': 'POPULARITY_SCORE'}}
        if query:
            variables['query'] = query
        if tag:
            if not validate_slug(tag):
                raise SourceError('Некорректная метка каталога.')
            variables['label'] = {'include': [tag], 'exclude': []}
        rows = items(self.graphql(http, 'search', variables), 'mangas')
        records, failure = [], None
        for row in rows:
            try:
                records.append(self.record_data(row))
            except (SourceError, AttributeError, TypeError) as error:
                # One malformed listing entry must not stop the whole catalogue.
                failure = failure or error
        if failure and not records:
            raise failure if isinstance(failure, SourceError) else SourceError('Каталог изменил формат тайтлов.')
        return records, len(rows) >= 10

    def vocabulary(self, http):
        return [{'label': self.label(row), 'sourceId': row['slug'],
                 'category': 'genre' if row.get('rootId') == 'TEFCRUw6NQ' else 'tag'}
                for row in items(self.graphql(http, 'filters'), 'labels')
                if isinstance(row, dict) and validate_slug(row.get('slug'))]

    def series(self, http, url):
        key, slug = self.identity(http, url), self.title_key(url)
        details = self.graphql(http, 'details', {'mangaId': key})
        if details.get('id') != key or details.get('slug') != slug:
            raise SourceError('Источник вернул другой тайтл.')
        data = self.graphql(http, 'chapters', {'mangaId': key})
        teams = {row['id']: row['name'] for row in items(data, 'teams')
                 if isinstance(row, dict) and isinstance(row.get('id'), str) and isinstance(row.get('name'), str)}
        rows = {}
        for row in items(data, 'chapters'):
            if not isinstance(row, dict):
                continue
            chapter = validate_slug(row.get('slug'))
            identity = validate_slug(row.get('id'), ID)
            n = number(row.get('number'))
            if not chapter or not identity or n is None:
                continue
            target = query_url(f'{self.ROOT}/manga/{slug}/chapters/{chapter}', mv_id=key, mv_chapter=identity)
            volume = str(row.get('volume', ''))
            rows[target] = self.chapter(target, row.get('name') or f'Глава {n:g}', n,
                                         str(row.get('updatedAt') or row.get('createdAt') or '')[:10],
                                         int(volume) if re.fullmatch(r'[1-9]\d{0,5}', volume) else 1,
                                         ', '.join(teams[team] for team in (row.get('teamIds') or []) if team in teams))
        return self.record_data(details), self.order(rows)

    def pages(self, http, url):
        key = validate_slug(param(url, 'mv_id'), ID)
        chapter = validate_slug(param(url, 'mv_chapter'), ID)
        if not key or not chapter:
            return []
        data = self.graphql(http, 'pages', {'mangaId': key, 'chapterId': chapter})
        return [image_url(row.get('url'), url) if isinstance(row, dict) else '' for row in items(data, 'pages')]
