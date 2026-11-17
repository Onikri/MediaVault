"""Scanlation sites served from public Supabase REST views.

Ports keiyoushi ``src/en/webdexscans`` and ``src/en/schalescans`` at 6f345a8.
Both publish an anonymous (public) Supabase key in their web app; premium
Webdex chapters that are not free yet stay out of open reading.
"""

from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT
from manga_ninth_routes import Route, register
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
STATUSES = {'ongoing': 'ongoing', 'completed': 'completed', 'hiatus': 'hiatus', 'cancelled': 'cancelled'}


def iso_date(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc).date().isoformat()
    except ValueError:
        return ''


def clean_text(value):
    raw = re.sub(r'(?i)</(?:p|div|h[1-6])>', '\n', str(value or ''))
    text = BeautifulSoup(raw, 'html.parser').get_text().replace('\xa0', ' ')
    return re.sub(r'\n{3,}', '\n\n', re.sub(r'[ \t\r]*\n[ \t\r]*', '\n', text)).strip()


class SupabaseScans(JsonSeries):
    REST = ''
    KEY = ''
    BEARER = False
    TABLES = frozenset()

    def __init__(self, identity, title, chapter):
        super().__init__(identity, title, chapter, interval=.3)
        self.action = 'n9:supabase-' + urlsplit(self.REST).netloc
        register(self.action[3:], self.route, self.public_api)

    def public_api(self, host, path, query):
        rest = urlsplit(self.REST)
        if host != rest.netloc or not path.startswith(rest.path + '/') or path[len(rest.path) + 1:] not in self.TABLES:
            return False
        try:
            fields = parse_qsl(query, keep_blank_values=True, max_num_fields=16, strict_parsing=True)
        except ValueError:
            return False
        return len(fields) <= 16 and all(len(value) <= 400 for _, value in fields)

    def route(self, url, method, data, headers):
        if method != 'GET' or data is not None or not self.public_api(url.netloc, url.path, url.query):
            return None
        extra = {'apikey': self.KEY, 'Accept': 'application/json'}
        if self.BEARER:
            extra['Authorization'] = 'Bearer ' + self.KEY
        return Route(extra, redirect=False)

    def rest(self, http, table, **args):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, _ = http.document(query_url(f'{self.REST}/{table}', **args), headers={'Referer': self.ROOT + '/'},
                                  action=self.action)
        try:
            data = json.loads(raw)
        except ValueError:
            raise SourceError(f'{self.NAME} изменил формат API.') from None
        if not isinstance(data, list):
            raise SourceError(f'{self.NAME} изменил формат API.')
        return data


class WebdexScans(SupabaseScans):
    REST = 'https://apidb.webdexscans.com/rest/v1'
    KEY = ('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIiwiaWF0IjoxNzkyMzI5NzkxLCJl'
           'eHAiOjE5NTAwMDk3OTF9.ub3n4yzBgZ1madOiy7R_QE5yOLRJISh8-C_wa0Ud8mQ')
    BEARER = True
    TABLES = frozenset({'series', 'chapters', 'pages'})
    GENRES = (('Action', 'action'), ('Adventure', 'adventure'), ('Comedy', 'comedy'), ('Drama', 'drama'),
              ('Fantasy', 'fantasy'), ('Isekai', 'isekai'), ('Martial Arts', 'martial-arts'), ('Mystery', 'mystery'),
              ('Romance', 'romance'), ('Sci-Fi', 'sci-fi'), ('Seinen', 'seinen'), ('Shounen', 'shounen'),
              ('Slice of Life', 'slice-of-life'), ('Supernatural', 'supernatural'))
    ORDERS = {'popular': 'view_count.desc', 'rating': 'rating.desc', 'alphabet': 'title.asc'}

    def __init__(self):
        super().__init__(('3534396555218651855', 'Webdex Scans', 'en', 'https://webdexscans.com', False),
                         rf'/series/({SEGMENT})/?', rf'/series/({SEGMENT}/{SEGMENT})/?')

    def title_for(self, url):
        key = self.chapter_key(url)
        return f'{self.ROOT}/series/{key.split("/")[0]}' if key else ''

    def chapter_identity(self, url):
        return param(url, 'mv_chapter') or urlsplit(url).path

    def saved_title_url(self, url):
        return self.canonical(url)

    def card(self, item):
        if not isinstance(item, dict) or not isinstance(item.get('slug'), str) or not isinstance(item.get('title'), str):
            return None
        url = f'{self.ROOT}/series/{item["slug"]}'
        if not self.is_title(url):
            return None
        cover = str(item.get('cover_url') or '')
        if cover.startswith('/'):
            cover = self.ROOT + cover
        genres = [g['name'] for g in item.get('genres') or [] if isinstance(g, dict) and isinstance(g.get('name'), str)]
        authors = [a for a in (item.get('author'), item.get('artist')) if isinstance(a, str) and a]
        row = self.record(url, item['title'].strip(), cover, description=clean_text(item.get('description')),
                          genres=genres, authors=authors, status=STATUSES.get(str(item.get('status') or '').lower(), ''))
        row['seriesId'] = item.get('id')
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'select': 'id,title,slug,cover_url', 'status': 'neq.draft',
                'order': self.ORDERS.get(sort, 'updated_at.desc'), 'offset': str((page - 1) * 24), 'limit': '24'}
        if tag:
            if tag not in {key for _, key in self.GENRES}:
                return [], False
            args.update({'select': 'id,title,slug,cover_url,genres!inner(slug)', 'genres.slug': f'eq.{tag}'})
        if query:
            args['title'] = f'ilike.%{query}%'
        rows = [row for row in map(self.card, self.rest(http, 'series', **args)) if row]
        for row in rows:
            row.pop('seriesId', None)
        return rows, len(rows) == 24

    def vocabulary(self, http):
        return [{'key': key, 'label': label, 'kind': 'genre'} for label, key in self.GENRES]

    def series(self, http, url):
        slug = self.title_key(url)
        found = self.rest(http, 'series', slug=f'eq.{slug}', select='*,genres(name)')
        row = self.card(found[0]) if found else None
        if not row or not re.fullmatch(UUID, str(row.get('seriesId'))):
            raise SourceError('Webdex Scans не предоставил карточку тайтла.')
        series_id = row.pop('seriesId')
        listing = self.rest(http, 'chapters', series_id=f'eq.{series_id}', order='chapter_number.desc',
                            select='id,chapter_number,title,slug,created_at,is_premium,free_at,series(slug)')
        now = datetime.now(timezone.utc)
        chapters = []
        for item in listing:
            if not isinstance(item, dict) or not re.fullmatch(UUID, str(item.get('id'))) or not isinstance(item.get('slug'), str):
                continue
            if item.get('is_premium'):
                try:
                    free = datetime.fromisoformat(str(item.get('free_at')).replace('Z', '+00:00'))
                except ValueError:
                    continue
                if free > now:
                    continue
            number = item.get('chapter_number')
            label = f'{float(number):g}' if isinstance(number, (int, float)) else ''
            name = item.get('title') if isinstance(item.get('title'), str) and item['title'].strip() else (
                f'Chapter {label}' if label else 'Chapter')
            target = query_url(f'{self.ROOT}/series/{slug}/{item["slug"]}', mv_chapter=item['id'])
            if self.is_chapter(target):
                chapters.append(self.chapter(target, name, float(number) if label else None, iso_date(item.get('created_at'))))
        return row, self.order({c['url']: c for c in chapters})

    def pages(self, http, url):
        chapter = param(url, 'mv_chapter')
        if not re.fullmatch(UUID, chapter):
            raise SourceError('Некорректная ссылка на главу Webdex Scans.')
        data = self.rest(http, 'pages', chapter_id=f'eq.{chapter}', select='image_url,page_number', order='page_number.asc')
        return [item['image_url'] if not item['image_url'].startswith('/') else self.ROOT + item['image_url']
                for item in data if isinstance(item, dict) and isinstance(item.get('image_url'), str)]


class SchaleScans(SupabaseScans):
    REST = 'https://xqjjktixlttbqbsdpaxe.supabase.co/rest/v1'
    KEY = 'sb_publishable__ow-g4H00jio3RK5qQaJuA_87iakWRc'
    TABLES = frozenset({'series', 'chapters', 'genres'})
    HOSTS = ('www.schalescans.com', 'r18.schalescans.com')

    def __init__(self):
        super().__init__(('135437514280789093', 'Schale Scans', 'en', 'https://www.schalescans.com', True),
                         rf'/manga/({SEGMENT})/?', rf'/read/({SEGMENT}/[0-9]{{1,6}}(?:\.[0-9]{{1,3}})?)/?')
        self.reader_hosts = frozenset(self.HOSTS)

    def title_for(self, url):
        key = self.chapter_key(url)
        host = urlsplit(url).netloc or 'www.schalescans.com'
        return f'https://{host}/manga/{key.split("/")[0]}' if key else ''

    def chapter_identity(self, url):
        return param(url, 'mv_chapter') or urlsplit(url).path

    def site_root(self, adult):
        return 'https://r18.schalescans.com' if adult else self.ROOT

    def card(self, item):
        if not isinstance(item, dict) or not isinstance(item.get('slug'), str) or not isinstance(item.get('title'), str):
            return None
        adult = bool(item.get('is_r18'))
        url = f'{self.site_root(adult)}/manga/{item["slug"]}'
        if not self.is_title(url):
            return None
        genres = [g['genres']['name'] for g in item.get('series_genres') or []
                  if isinstance(g, dict) and isinstance(g.get('genres'), dict) and isinstance(g['genres'].get('name'), str)]
        aliases = [a for a in item.get('alt_titles') or [] if isinstance(a, str)]
        authors = item.get('authors') if isinstance(item.get('authors'), list) else []
        row = self.record(url, item['title'].strip(), str(item.get('cover_url') or ''), aliases=aliases,
                          description=clean_text(item.get('description')), genres=genres,
                          authors=[a for a in authors if isinstance(a, str)],
                          status=STATUSES.get(str(item.get('status') or '').lower(), ''))
        if adult:
            row['adult'] = True
        row['seriesId'] = item.get('id')
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        select = 'id,title,slug,cover_url,is_r18,created_at,chapters(published_at,created_at)'
        args = {'chapters.pages_ready': 'eq.true', 'chapters.order': 'published_at.desc.nullslast', 'chapters.limit': '1'}
        if tag:
            if not re.fullmatch(r'[\w &\'-]{1,60}', tag):
                return [], False
            select += ',series_genres!inner(genres!inner(name))'
            args['series_genres.genres.name'] = f'eq.{tag}'
        if query:
            args['title'] = f'ilike.*{query}*'
        args['order'] = 'title.asc' if sort == 'alphabet' else 'created_at.desc'
        data = self.rest(http, 'series', select=select, **args)
        rows = []
        for item in data:
            row = self.card(item)
            if row and item.get('chapters'):
                row.pop('seriesId', None)
                rows.append(row)
        # The API answers the whole catalogue at once; page it locally.
        return rows[(page - 1) * 40:page * 40], len(rows) > page * 40

    def vocabulary(self, http):
        data = self.rest(http, 'genres', select='name', order='name.asc')
        return [{'key': g['name'], 'label': g['name'], 'kind': 'genre'} for g in data
                if isinstance(g, dict) and isinstance(g.get('name'), str)]

    def series(self, http, url):
        slug = self.title_key(url)
        data = self.rest(http, 'series', slug=f'eq.{slug}', **{
            'select': 'id,title,slug,cover_url,description,status,is_r18,alt_titles,authors,series_genres(genres(name)),'
                      'chapters(id,chapter_number,volume_number,title,published_at,created_at)',
            'chapters.pages_ready': 'eq.true', 'chapters.order': 'chapter_number.desc'})
        row = self.card(data[0]) if data else None
        if not row:
            raise SourceError('Schale Scans не предоставил карточку тайтла.')
        row.pop('seriesId', None)
        root = self.site_root(bool(data[0].get('is_r18')))
        chapters = []
        for item in data[0].get('chapters') or []:
            if not isinstance(item, dict) or not re.fullmatch(UUID, str(item.get('id'))):
                continue
            number = item.get('chapter_number')
            if not isinstance(number, (int, float)):
                continue
            label = f'{float(number):g}'
            name = (f'Vol. {float(item["volume_number"]):g} ' if isinstance(item.get('volume_number'), (int, float)) else '') + f'Ch. {label}'
            if isinstance(item.get('title'), str) and item['title'].strip():
                name += ': ' + item['title'].strip()
            target = query_url(f'{root}/read/{slug}/{label}', mv_chapter=item['id'])
            chapters.append(self.chapter(target, name, float(number), iso_date(item.get('published_at') or item.get('created_at'))))
        return row, self.order({c['url']: c for c in chapters})

    def pages(self, http, url):
        chapter = param(url, 'mv_chapter')
        if not re.fullmatch(UUID, chapter):
            raise SourceError('Некорректная ссылка на главу Schale Scans.')
        data = self.rest(http, 'chapters', id=f'eq.{chapter}', select='series(is_r18),chapter_pages(object_key)',
                         **{'chapter_pages.order': 'page_number.asc'})
        if not data or not isinstance(data[0], dict):
            raise SourceAccessError('Schale Scans не открыл эту главу.')
        adult = bool((data[0].get('series') or {}).get('is_r18'))
        host = 'https://img-r18.schalescans.com' if adult else 'https://img.schalescans.com'
        return [f'{host}/{page["object_key"]}' for page in data[0].get('chapter_pages') or []
                if isinstance(page, dict) and isinstance(page.get('object_key'), str)]


SOURCES = (WebdexScans(), SchaleScans())
