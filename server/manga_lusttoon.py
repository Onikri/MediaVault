"""LustToon catalogue API and Next.js reader."""

import json
import re
from urllib.parse import parse_qsl, urlsplit

from manga_additional_catalogues import flight_objects
from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, image_url, release_date
from manga_series_port import number
from manga_webcomics import query_url
from source_parser import SourceError

ROOT = 'https://lustoon.com'
API = 'https://back.lustoon.com'
TITLE = rf'/comic/({SEGMENT})/?'
CHAPTER = rf'/comic/({SEGMENT})/({SEGMENT})/?'
PAGE_URL = re.compile(r"""https?://media\.lustoon\.com/file/[^"\s'<>]+\.(?:jpe?g|png|webp|avif)""", re.I)
STATES = {'en emision': 'ongoing', 'ongoing': 'ongoing', 'finalizado': 'completed', 'completado': 'completed',
          'completed': 'completed', 'cancelado': 'cancelled', 'cancelled': 'cancelled',
          'pausado': 'hiatus', 'hiatus': 'hiatus', 'paused': 'hiatus'}


def public_api(host, path, query):
    pairs = parse_qsl(query, keep_blank_values=True)
    args = dict(pairs)
    if len(pairs) != len(args):
        return False
    if host == 'lustoon.com':
        return not query and (path == '/' or bool(re.fullmatch(TITLE, path)))
    if host != 'back.lustoon.com':
        return False
    if path == '/home/buscar':
        return set(args) == {'query'} and 1 <= len(args['query']) <= 160
    return (path == '/filtrar' and set(args) == {'page', 'limit', 'orderBy', 'sort', 'gendersId', 'origin', 'state', 'loading'}
            and bool(re.fullmatch(r'[1-9]\d{0,3}', args['page'])) and args['limit'] == '24'
            and args['orderBy'] in ('3', '6') and args['sort'] == 'desc' and args['loading'] == 'true'
            and bool(re.fullmatch(r'\d{0,3}', args['gendersId'])) and args['origin'] == args['state'] == '')


class LustToon(JsonSeries):
    def __init__(self):
        super().__init__(('5466172882050312169', 'LustToon', 'en', ROOT, True),
                         TITLE, CHAPTER, hosts=('www.lustoon.com',), interval=.35)

    def title_for(self, url):
        return ROOT + '/comic/' + self.chapter_key(url)

    def canonical(self, value):
        target = super().canonical(value)
        if urlsplit(target).netloc == 'www.lustoon.com':
            return ROOT + target.split('www.lustoon.com', 1)[1]
        return target

    def rsc(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': ROOT + '/'}, action='native-series-rsc')
        if final != url:
            raise SourceError('LustToon перенаправил запрос каталога.')
        return flight_objects(raw)

    def make_row(self, entry, **info):
        if not isinstance(entry, dict) or not isinstance(entry.get('slug'), str):
            return None
        url = self.site_link('/comic/' + entry['slug'])
        title = entry.get('name')
        if self.is_title(url) and isinstance(title, str) and title.strip():
            return self.record(url, title, image_url(entry.get('urlImg'), url), **info)
        return None

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            if page != 1:
                return [], False
            data = self.json(http, query_url(API + '/home/buscar', query=query))
            return [row for item in data if (row := self.make_row(item))], False
        if sort == 'updated' and not tag and page == 1:
            data = next((node['comics'] for node in self.rsc(http, ROOT + '/')
                         if isinstance(node.get('comics'), list) and node['comics']), ())
            if data:
                return [row for item in data if (row := self.make_row(item))], True
        # The homepage is the first updated batch. The API cursor starts after it.
        index = page - 1 if sort == 'updated' and not tag and page > 1 else page
        result = self.json(http, query_url(API + '/filtrar', page=index, limit=24,
                                           orderBy=3 if sort == 'updated' else 6, sort='desc',
                                           gendersId=tag if re.fullmatch(r'\d{1,3}', tag) else '',
                                           origin='', state='', loading='true'))
        meta = result.get('meta') or {}
        rows = [row for item in result.get('data') or [] if (row := self.make_row(item))]
        return rows, bool(rows and (number(meta.get('current_page')) or index) < (number(meta.get('last_page')) or index))

    def series(self, http, url):
        key = self.title_key(url)
        target = ROOT + '/comic/' + key
        series = next((data for data in self.rsc(http, target)
                       if data.get('slug') == key and isinstance(data.get('chapters'), list)), None)
        if not series:
            raise SourceError('LustToon не вернул карточку выбранного тайтла.')
        state = series.get('state') or {}
        genres = [gen['name'] for gen in series.get('genders') or []
                  if isinstance(gen, dict) and isinstance(gen.get('name'), str)]
        row = self.make_row(series, description=series.get('sinopsis') or '', genres=genres,
                            status=STATES.get(str(state.get('estado', '')).casefold(), ''))
        episodes = {}
        for item in series['chapters']:
            if not isinstance(item, dict) or not re.fullmatch(SEGMENT, str(item.get('slug') or '')):
                continue
            chapter = target + '/' + item['slug']
            n = number(item.get('num'))
            title = str(item.get('name') or '')
            if not re.search(r'\d', title) and n is not None:
                title = f'Chapter {n:g}'
            date = release_date(str(item.get('createdAt') or '').partition('T')[0], '%Y-%m-%d')
            episodes[chapter] = self.chapter(chapter, title, n, date)
        if not row:
            raise SourceError('LustToon не вернул название произведения.')
        return row, self.order(episodes)

    def pages(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': ROOT + '/'})
        if not self.is_chapter(final) or self.chapter_identity(final) != self.chapter_identity(url):
            raise SourceError('LustToon перенаправил на другую главу.')
        ref = next((data['urlImg'] for data in flight_objects(raw)
                    if data.get('chapterId') and isinstance(data.get('urlImg'), str)), '[]')
        try:
            files = json.loads(ref)
        except ValueError:
            files = []
        if not isinstance(files, list) or not files:
            files = [match.group() for match in PAGE_URL.finditer(raw) if '/serie/' in match.group()]
        return list(dict.fromkeys(image_url(item, final) for item in files if isinstance(item, str)
                                  and PAGE_URL.fullmatch(item) and 'brakeout' not in item))


SOURCES = (LustToon(),)
