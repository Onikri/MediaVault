"""Public EZManhwa and HeanCMS title, chapter and image APIs."""

from datetime import date
import re
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import SeriesPort, number
from manga_source_tags import labels
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceError


EZ = {'vapi.ezmanga.org', 'api.qimanga.com'}
HEAN = {'api.luacomic.org', 'api.omegascans.org'}
SERIES = rf'/series/({SEGMENT})/?'
CHAPTER = rf'/series/({SEGMENT})/(?:chapters/)?({SEGMENT})/?'


def allowed(query, keys):
    try:
        args = parse_qs(query, keep_blank_values=True, max_num_fields=len(keys))
    except ValueError:
        return False
    return set(args) == set(keys) and all(len(v) == 1 and len(v[0]) <= 180 for v in args.values())


def public_api(host, path, query):
    if host in EZ:
        if path == '/api/v1/series/search':
            return allowed(query, ('page', 'perPage', 'q'))
        if path == '/api/v1/series':
            return allowed(query, ('page', 'perPage', 'sort')) or allowed(query, ('page', 'perPage', 'sort', 'genre'))
        if re.fullmatch(rf'/api/v1/series/{SEGMENT}/chapters', path):
            return allowed(query, ('page', 'perPage', 'sort'))
        return not query and bool(re.fullmatch(rf'/api/v1/series/{SEGMENT}(?:/chapters/{SEGMENT})?', path))
    if host in HEAN:
        if path == '/query':
            return allowed(query, ('query_string', 'status', 'order', 'orderBy', 'series_type', 'page', 'perPage', 'tags_ids', 'adult'))
        if path == '/chapter/query':
            return allowed(query, ('page', 'perPage', 'series_id'))
        return not query and bool(re.fullmatch(rf'/(?:tags|series/{SEGMENT}|chapter/{SEGMENT}/{SEGMENT})', path))
    return False


def items(data):
    if not isinstance(data, dict) or not isinstance(data.get('data'), list):
        raise SourceError('Источник не предоставил список каталога.')
    return (v for v in data['data'] if isinstance(v, dict))


def text_content(value):
    return node_text(BeautifulSoup(value, 'html.parser')) if isinstance(value, str) else ''


def clean_date(raw):
    return release_date(str(raw or '')[:10], '%Y-%m-%d')


class SeriesAPI(SeriesPort):
    def __init__(self, identity, api, vocabulary=()):
        super().__init__(identity, SERIES, CHAPTER, interval=.5)
        self.api = api
        self.terms = vocabulary
        self.ez = urlsplit(api).hostname in EZ

    def title_for(self, url):
        return self.ROOT + '/series/' + self.chapter_key(url)

    def item(self, raw):
        if not isinstance(raw, dict) or raw.get('type') == 'NOVEL':
            return None
        slug = raw.get('slug' if self.ez else 'series_slug')
        if not isinstance(slug, str) or not re.fullmatch(SEGMENT, slug) or not raw.get('title'):
            return None
        title = self.ROOT + '/series/' + slug
        cover = image_url(raw.get('cover' if self.ez else 'thumbnail'), self.api + '/')
        names = re.split(r'\s*[|;]\s*', raw.get('alternativeTitles' if self.ez else 'alternative_names') or '')
        tags = labels(raw.get('genres' if self.ez else 'tags'))
        row = self.record(title, raw['title'], cover, aliases=names, description=text_content(raw.get('description')),
                          genres=tags if self.ez else (), tags=() if self.ez else tags,
                          authors=(raw.get('author'),), status=raw.get('status') or '')
        row['format'] = {'manga': 'manga', 'manhua': 'manhua', 'doujinshi': 'doujinshi'}.get(
            str(raw.get('type' if self.ez else 'badge') or '').casefold(), 'manhwa')
        row['artists'] = [credit for credit in (raw.get('artist' if self.ez else 'studio'),) if credit]
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if self.ez:
            args = {'page': page, 'perPage': 20}
            path = '/series/search' if query else '/series'
            if query:
                args['q'] = query
            else:
                args['sort'] = 'latest' if sort == 'updated' else 'popular'
                if tag:
                    args['genre'] = tag[:120]
        else:
            if tag and not re.fullmatch(r'\d{1,12}', tag):
                raise SourceError('Некорректный ID тега HeanCMS.')
            path = '/query'
            args = {'query_string': query, 'status': 'All', 'order': 'asc' if self.NAME == 'Lua Scans' and sort == 'updated' else 'desc',
                    'orderBy': 'latest' if sort == 'updated' else 'total_views', 'series_type': 'Comic',
                    'page': page, 'perPage': 12, 'tags_ids': f'[{tag}]', 'adult': 'true'}
        data = self.json(http, query_url(self.api + path, **args))
        result = [row for raw in items(data) if (row := self.item(raw))]
        return result, self.more(data, page)

    def more(self, data, page):
        last = data.get('totalPages') if self.ez else (data.get('meta') or {}).get('last_page')
        return type(last) is int and last > page

    def vocabulary(self, http):
        if self.ez:
            return [{'label': title, 'sourceId': slug, 'category': 'genre'} for title, slug in self.terms]
        data = self.json(http, self.api + '/tags')
        return [{'label': v['name'], 'sourceId': str(v['id']), 'category': 'tag'} for v in data
                if isinstance(v, dict) and v.get('name') and type(v.get('id')) is int] if isinstance(data, list) else []

    def entry(self, http, url):
        slug = self.title_key(url)
        if not slug:
            raise SourceError('Некорректный адрес карточки тайтла.')
        raw = self.json(http, self.api + '/series/' + slug)
        row = self.item(raw)
        if not row or self.title_key(self.site_link(row['url'])) != slug:
            raise SourceError('API вернул карточку другого тайтла.')
        return row, raw.get('id')

    def details(self, http, url):
        return self.entry(http, self.canonical(url))[0]

    def chapter_rows(self, http, slug, identity):
        if not self.ez and type(identity) is not int:
            raise SourceError('HeanCMS не предоставил ID тайтла.')
        found, more = {}, False
        for page in range(1, 81):
            if self.ez:
                api_path = query_url(self.api + f'/series/{slug}/chapters', page=page, perPage=100, sort='desc')
            else:
                api_path = query_url(self.api + '/chapter/query', page=page, perPage=1000, series_id=identity)
            data = self.json(http, api_path)
            for entry in items(data):
                chapter = entry.get('slug' if self.ez else 'chapter_slug')
                if not isinstance(chapter, str) or not re.fullmatch(SEGMENT, chapter):
                    continue
                if (self.ez and entry.get('requiresPurchase') is True) or (not self.ez and entry.get('price') != 0):
                    continue
                stamp = clean_date(entry.get('becameFreeAt') or entry.get('createdAt' if self.ez else 'created_at'))
                if stamp and stamp > date.today().isoformat():
                    continue
                href = self.ROOT + f'/series/{slug}/{chapter}'
                name = entry.get('title') if self.ez else ' — '.join(filter(None, (entry.get('chapter_name'), entry.get('chapter_title'))))
                n = number(entry.get('number')) if self.ez else None
                found[chapter] = self.chapter(href, name or chapter, n, stamp)
            more = self.more(data, page)
            if not more:
                break
        return self.order(found), more

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_title(url):
            row, identity = self.entry(http, url)
            chapters, more = self.chapter_rows(http, self.title_key(url), identity)
            return self.reader_result(row, url, chapters, [], more)
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        if not match:
            raise SourceError('Некорректный адрес главы.')
        slug, chapter = match.groups()
        path = f'/series/{slug}/chapters/{chapter}' if self.ez else f'/chapter/{slug}/{chapter}'
        data = self.json(http, self.api + path, url)
        if not isinstance(data, dict):
            raise SourceError('Источник не предоставил данные главы.')
        if self.ez:
            if data.get('requiresPurchase'):
                raise SourceAccessError('Глава доступна после покупки у источника.')
            items_raw = [entry.get('url') for entry in data.get('images') or () if isinstance(entry, dict)]
        else:
            if data.get('paywall'):
                raise SourceAccessError('Глава доступна на условиях источника.')
            items_raw = ((data.get('chapter') or {}).get('chapter_data') or {}).get('images') or []
        pages = [image_url(entry, self.api + '/') for entry in items_raw]
        if not pages or not all(pages) or len(pages) > 1500:
            raise SourceError('Источник не предоставил полный список страниц.')
        row = self.record(self.title_for(url), slug.replace('-', ' '))
        return self.reader_result(row, url, [self.chapter(url, chapter, number(chapter) or 0)], pages)

    def saved_title_url(self, target):
        slug = self.title_key(target)
        return self.ROOT + '/series/' + slug if slug else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if match := self.CHAPTER_PATH.fullmatch(urlsplit(url).path):
            return self.ROOT + f'/series/{match[1]}/{match[2]}'
        return ''


def sources():
    from manga_second_batch_profiles import GENRES

    return (
        SeriesAPI(('3317136566565343717', 'EZmanga', 'en', 'https://ezmanga.org', False), 'https://vapi.ezmanga.org/api/v1', GENRES['ezmanga']),
        SeriesAPI(('5806040666300479660', 'QiScans', 'en', 'https://qimanga.com', False), 'https://api.qimanga.com/api/v1', GENRES['qiscans']),
        SeriesAPI(('972271455406675873', 'Lua Scans', 'en', 'https://luacomic.org', False), 'https://api.luacomic.org'),
        SeriesAPI(('1534451209269193504', 'Omega Scans', 'en', 'https://omegascans.org', True), 'https://api.omegascans.org'),
    )
