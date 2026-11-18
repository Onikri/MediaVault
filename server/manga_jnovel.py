"""J-Novel Club manga (keiyoushi ``src/en/jnovel`` at 6f345a8).

The series list, search and series pages are read from the site's React
Server Component stream (``rsc: 1``). Only preview parts open (the others stay listed as paid): the
site gives every guest their embedded reader, whose ``info.json`` names an
anonymous E4P manifest (``manga_e4p``). Rentals and purchased volumes need
an account and stay out of the open route.
"""

from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_additional_catalogues import flight_objects
from manga_direct_payloads import JsonSeries
from manga_e4p import decode_manifest, page_refs, plain_manifest
from manga_japanese_readers import packed_refs
from manga_ninth_routes import Route, register
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://j-novel.club'
EMBED = 'https://labs.j-novel.club/embed/v2/'
SLUG = r'[a-z0-9][a-z0-9-]{0,299}'
PART = r'PRT-[A-Z0-9]{4,20}'
STATUSES = {0: 'ongoing', 1: 'completed', 2: 'hiatus'}
MAX_MANIFEST = 4 * 1024 * 1024


def route(url, method, data, headers):
    if method != 'GET' or data is not None:
        return None
    if url.netloc == 'j-novel.club':
        if url.path == '/series':
            try:
                args = dict(parse_qsl(url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=4))
            except ValueError:
                return None
            if (args.get('type') == 'manga' and set(args) <= {'type', 'page', 'search'}
                    and re.fullmatch(r'[1-9][0-9]{0,3}', args.get('page', '1')) and len(args.get('search', '')) <= 160):
                return Route(headers={'rsc': '1', 'Accept': 'text/x-component'}, redirect=False)
            return None
        if re.fullmatch(rf'/series/{SLUG}', url.path) and not url.query:
            return Route(headers={'rsc': '1', 'Accept': 'text/x-component'}, redirect=False)
        if re.fullmatch(rf'/read/{SLUG}', url.path) and not url.query:
            return Route(headers={'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'}, redirect=False)
        return None
    if url.netloc == 'labs.j-novel.club' and re.fullmatch(rf'/embed/v2/{PART}/info\.json', url.path) and not url.query:
        return Route(headers={'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
                              'Referer': ROOT + '/'}, redirect=False)
    if url.netloc == 'flame.j-novel.club' and re.fullmatch(r'/consumer/[A-Z0-9]{2,16}/delivery/CNT-[A-Z0-9]{4,24}/manifest',
                                                            url.path):
        return Route(headers={'Accept': 'application/vnd.e4p.prpb+deflate+vnd.e4p.qst, application/vnd.e4p.prpb, */*'},
                     redirect=False)
    return None


register('jnovel', route)


def seconds(value):
    try:
        return datetime.fromtimestamp(int(value['seconds']), timezone.utc).date().isoformat()
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return ''


class JNovel(JsonSeries):
    def __init__(self):
        super().__init__(('2482510125735992610', 'J-Novel', 'en', ROOT, False), rf'/series/({SLUG})', rf'/read/({SLUG})',
                         interval=.35)

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(re.fullmatch(SLUG, self.series_of(url)))

    def series_of(self, url):
        from manga_webcomics import param

        return param(url, 'mv_series')

    def title_for(self, url):
        return f'{ROOT}/series/{self.series_of(url)}'

    def chapter_identity(self, url):
        return self.chapter_key(url)

    def saved_title_url(self, value):
        # Suwayomi stored the series slug.
        target = self.canonical(value)
        slug = urlsplit(target).path.strip('/').removeprefix('series/')
        return f'{ROOT}/series/{slug}' if re.fullmatch(SLUG, slug) else ''

    def saved_chapter(self, row, root, title):
        value = str(row.get('url') or '').strip('/').removeprefix('read/')
        key = self.title_key(title)
        return query_url(f'{ROOT}/read/{value}', mv_series=key) if re.fullmatch(SLUG, value) and key else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.series_of(target) == self.title_key(title)

    def flight(self, http, url, key):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, _ = http.document(url, headers={'Referer': ROOT + '/'}, action='n9:jnovel')
        found = next((item for item in flight_objects(raw) if key(item)), None)
        if found is None:
            raise SourceError('J-Novel изменил формат страницы.')
        return found

    def series_row(self, item, **extra):
        if not isinstance(item, dict) or not re.fullmatch(SLUG, str(item.get('slug', ''))) or not item.get('title'):
            return None
        cover = (item.get('cover') or {}).get('coverUrl') if isinstance(item.get('cover'), dict) else ''
        return self.record(f'{ROOT}/series/{item["slug"]}', str(item['title']).strip(), cover or '', **extra)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag:
            return [], False
        args = {'type': 'manga', 'page': str(page)}
        if query:
            args['search'] = query
        data = self.flight(http, query_url(ROOT + '/series', **args), lambda item: isinstance(item.get('seriesList'), dict))
        listing = data['seriesList']
        rows = [row for item in listing.get('series') or [] if (row := self.series_row(item))]
        return rows, bool(listing.get('nextPageToken'))

    def series(self, http, url):
        slug = self.title_key(url)
        data = self.flight(http, f'{ROOT}/series/{slug}',
                           lambda item: isinstance(item.get('series'), dict) and isinstance(item.get('volumes'), list))
        info = data['series']
        if info.get('slug') != slug:
            raise SourceError('J-Novel вернул карточку другой серии.')
        volumes = [volume for volume in data['volumes'] if isinstance(volume, dict)]
        creators = ((volumes[0].get('volume') or {}).get('creators') or []) if volumes else []
        banner = (info.get('banner') or {}).get('originalUrl') if isinstance(info.get('banner'), dict) else ''
        row = self.series_row(info, description=str(info.get('description') or ''),
                              genres=[tag for tag in info.get('tags') or [] if isinstance(tag, str)],
                              authors=[item.get('name') for item in creators if isinstance(item, dict) and item.get('name')],
                              status=STATUSES.get(info.get('status'), ''))
        if row is None:
            raise SourceError('J-Novel не предоставил карточку серии.')
        if banner:
            row['cover'] = banner
        title = str(info['title'])
        chapters = {}
        for volume in volumes:
            for part in volume.get('parts') or []:
                if not isinstance(part, dict) or not re.fullmatch(SLUG, str(part.get('slug', ''))):
                    continue
                name = str(part.get('title') or '')
                name = name.removeprefix(title).strip() or name
                n = part.get('number')
                target = query_url(f'{ROOT}/read/{part["slug"]}', mv_series=slug)
                chapters[target] = {**self.chapter(target, name, float(n) if type(n) is int else None,
                                                   seconds(part.get('launch'))), 'season': 1,
                                    # A guest reads only the open preview parts.
                                    'locked': part.get('preview') is not True}
        return row, self.order(chapters)

    def pages(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, _ = http.document(f'{ROOT}/read/{self.chapter_key(url)}', headers={'Referer': ROOT + '/'},
                                  action='n9:jnovel')
        frame = BeautifulSoup(raw, 'html.parser').select_one(f'iframe[src^="{EMBED}"]')
        part = re.fullmatch(rf'{re.escape(EMBED)}({PART})/?', frame.get('src', '')) if frame else None
        if not part:
            raise SourceAccessError('Часть J-Novel доступна только после покупки.')
        info, _, _ = http.document(f'{EMBED}{part[1]}/info.json', headers={'Referer': ROOT + '/'}, action='n9:jnovel')
        try:
            manifest_url = json.loads(info)['e4p-manifest']
        except (KeyError, TypeError, ValueError):
            raise SourceError('J-Novel изменил формат читалки.') from None
        if not isinstance(manifest_url, str) or urlsplit(manifest_url).netloc != 'flame.j-novel.club':
            raise SourceError('J-Novel изменил адрес манифеста.')
        response, final = http._open(manifest_url, headers={'Referer': EMBED}, action='n9:jnovel')
        try:
            kind = response.headers.get('Content-Type', '').partition(';')[0].strip()
            body = bytearray()
            for block in response.iter_content(65536):
                body.extend(block)
                if len(body) > MAX_MANIFEST:
                    raise SourceError('Манифест J-Novel слишком велик.')
        finally:
            response.close()
        manifest = plain_manifest(bytes(body)) if kind == 'application/vnd.e4p.prpb' else decode_manifest(bytes(body))
        return packed_refs(page_refs(manifest, manifest_url), url)


SOURCES = (JNovel(),)
