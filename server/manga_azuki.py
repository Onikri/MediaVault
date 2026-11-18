"""Kodansha and Omoi (keiyoushi ``src/en/kodansha`` and ``src/en/omoi`` at 6f345a8).

Both stores run on the Azuki platform: one public API answers series,
volume, chapter and page requests for the organisation key of the store.
Kodansha also lists its catalogue through that API; Omoi lists it on the
``/discover`` page. Only chapters inside their free window open; the others stay listed as
paid (``locked``),
because the guest page list answers 401 for the others. Page images are
XOR-ed with one byte (174), decoded like the extensions' interceptors.
"""

from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_japanese_readers import JapanesePage, packed_refs
from manga_madara import image_url, node_text
from manga_ninth_routes import Route, register
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

API = 'https://production.api.azuki.co'
IMAGES = 'production.image-content.azuki.co'
XOR = bytes((174,))
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
SLUG = r'[a-z0-9][a-z0-9-]{0,159}'
KODANSHA_KEY = 'fff36c1f-9b3d-418e-b3a9-d2a537ddac06'
OMOI_KEY = '199e5a19-a236-49f5-81f4-43d4a541748a'
PAGE_SIZE = 24
KODANSHA_SORTS = {'popular', 'recent_series', 'alphabetical'}
KODANSHA_TAGS = (
    ('action-and-adventure', 'Action & Adventure'), ('animals', 'Animals'), ('arts-and-entertainment', 'Arts & Entertainment'),
    ('biography', 'Biography'), ('blyaoi', 'BL/Yaoi'), ('comedy', 'Comedy'), ('crafts', 'Crafts'), ('drama', 'Drama'),
    ('fantasy', 'Fantasy'), ('fiction-and-literature', 'Fiction & Literature'), ('food', 'Food'), ('games', 'Games'),
    ('glyuri', 'GL/Yuri'), ('historical', 'Historical'), ('horror', 'Horror'), ('isekai', 'Isekai'), ('lgbtq', 'LGBTQ'),
    ('made-into-anime', 'Made into Anime'), ('martial-arts', 'Martial Arts'), ('movietv-tie-in', 'Movie/TV Tie-in'),
    ('romance', 'Romance'), ('school-life', 'School Life'), ('science-fiction', 'Science-Fiction'),
    ('slice-of-life', 'Slice of Life'), ('sports', 'Sports'), ('supernatural', 'Supernatural'), ('thriller', 'Thriller'),
    ('videogame-tie-in', 'Videogame Tie-in'),
)
OMOI_TAGS = (
    ('action', 'Action'), ('adventure', 'Adventure'), ('comedy', 'Comedy'), ('drama', 'Drama'), ('ecchi', 'Ecchi'),
    ('fantasy', 'Fantasy'), ('harem', 'Harem'), ('historical', 'Historical'), ('horror', 'Horror'), ('josei', 'Josei'),
    ('martial-arts', 'Martial Arts'), ('mature', 'Mature'), ('mecha', 'Mecha'), ('mystery', 'Mystery'),
    ('psychological', 'Psychological'), ('romance', 'Romance'), ('school-life', 'School Life'), ('scifi', 'Sci-Fi'),
    ('seinen', 'Seinen'), ('shoujo', 'Shojo'), ('shounen', 'Shonen'), ('slice-of-life', 'Slice of Life'),
    ('sports', 'Sports'), ('supernatural', 'Supernatural'), ('tragedy', 'Tragedy'),
)
OMOI_TAG_KEYS = frozenset(key for key, _ in OMOI_TAGS)
LIST_KEYS = {'search_string', 'sort', 'tags', 'series_types', 'format', 'count', 'offset'}


def query_fields(query, limit=12):
    try:
        fields = parse_qsl(query, keep_blank_values=True, max_num_fields=limit, strict_parsing=bool(query))
    except ValueError:
        return None
    args = dict(fields)
    return args if len(args) == len(fields) else None


def api_path(path, query):
    args = query_fields(query)
    if args is None:
        return False
    if path == '/mangas/v1':
        offset = args.get('offset', '')
        return (set(args) <= LIST_KEYS and args.get('sort') in KODANSHA_SORTS and args.get('series_types') == 'comic'
                and args.get('format') == 'digital' and args.get('count') == str(PAGE_SIZE)
                and offset.isdigit() and int(offset) % PAGE_SIZE == 0 and int(offset) < 2000 * PAGE_SIZE
                and len(args.get('search_string', '')) <= 160
                and all(tag in {key for key, _ in KODANSHA_TAGS} for tag in args.get('tags', 'comedy').split(',')))
    if re.fullmatch(rf'/mangas/{UUID}/chapters/v4', path):
        return args == {'order': 'ascending', 'count': '1000'}
    return not args and bool(re.fullmatch(rf'/manga/(?:slug/{SLUG}|{UUID})/v0|/chapters/{UUID}/pages/v1', path))


def route(url, method, data, headers):
    if method != 'GET' or data is not None:
        return None
    key = headers.get('Azuki-Store', '')
    if url.netloc == 'production.api.azuki.co' and key in {KODANSHA_KEY, OMOI_KEY} and api_path(url.path, url.query):
        if url.path == '/mangas/v1' and key != KODANSHA_KEY:
            return None
        origin = 'https://kodansha.us' if key == KODANSHA_KEY else 'https://www.omoi.com'
        return Route(headers={'Accept': 'application/json', 'azuki-organization-key': key,
                              'Origin': origin, 'Referer': origin + '/'}, redirect=False)
    if url.netloc == 'www.omoi.com' and url.path == '/discover':
        try:
            fields = parse_qsl(url.query, keep_blank_values=True, max_num_fields=30, strict_parsing=True)
        except ValueError:
            return None
        args = dict(fields)
        tags = [value for name, value in fields if name == 'tags[]']
        single = [name for name, _ in fields if name != 'tags[]']
        if (len(single) == len(set(single)) and set(args) <= {'page', 'q', 'sort', 'tags[]'}
                and re.fullmatch(r'[1-9][0-9]{0,3}', args.get('page', '')) and len(args.get('q', '')) <= 160
                and args.get('sort') in KODANSHA_SORTS and all(tag in OMOI_TAG_KEYS for tag in tags)):
            return Route(headers={'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'}, redirect=False)
    return None


register('azuki', route)


def stamp(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None


def free_now(item, now=None):
    now = now or datetime.now(timezone.utc)
    start, end = stamp(item.get('free_published_date')), stamp(item.get('free_unpublished_date'))
    return bool(start and start <= now and (not item.get('free_unpublished_date') or end and end > now))


def best_webp(image):
    sizes = image.get('webp') if isinstance(image, dict) else None
    sizes = [size for size in sizes or [] if isinstance(size, dict) and type(size.get('width')) is int
             and isinstance(size.get('url'), str)]
    return max(sizes, key=lambda size: size['width'])['url'] if sizes else ''


class Azuki(JsonSeries):
    KEY = ''
    TAGS = ()

    def __init__(self, identity):
        super().__init__(identity, rf'/series/({SLUG})/?', rf'/series/({SLUG})/read/({UUID})', interval=.3)

    def title_for(self, url):
        return f'{self.ROOT}/series/{self.chapter_key(url)}'

    def chapter_identity(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return match[2] if match else ''

    def api(self, http, path, **args):
        self.origin.wait(getattr(http, 'deadline', None))
        target = query_url(API + path, **args) if args else API + path
        raw, _, _ = http.document(target, headers={'Azuki-Store': self.KEY}, action='n9:azuki')
        try:
            return json.loads(raw)
        except ValueError:
            raise SourceError('Azuki изменил формат API.') from None

    def title_url(self, slug):
        return f'{self.ROOT}/series/{slug}'

    def record_from(self, item):
        if not isinstance(item, dict) or not isinstance(item.get('slug'), str) or not re.fullmatch(SLUG, item['slug']):
            return None
        if not isinstance(item.get('name'), str) or not item['name'].strip():
            return None
        names = lambda key: [row['name'] for row in item.get(key) or [] if isinstance(row, dict) and isinstance(row.get('name'), str)]
        tags = [tag for tag in item.get('tags') or [] if isinstance(tag, str)]
        description = str(item.get('short_description') or '')
        if item.get('credits'):
            description += '\n\n' + str(item['credits'])
        return self.record(self.title_url(item['slug']), item['name'].strip(), best_webp(item.get('image')),
                           aliases=names('alt_titles'), description=description.strip(), genres=tags,
                           authors=names('creators'), status='completed' if item.get('is_complete') else 'ongoing')

    def saved_title_url(self, value):
        target = self.canonical(value)
        if self.is_title(target):
            return target
        # Suwayomi stored "slug#uuid" (Omoi) or the bare series UUID (Kodansha).
        parts = urlsplit(target)
        slug = parts.path.strip('/')
        if re.fullmatch(SLUG, slug) and (not parts.fragment or re.fullmatch(UUID, parts.fragment)):
            return self.title_url(slug)
        return ''

    def saved_chapter(self, row, root, title):
        value = str(row.get('realUrl') or row.get('url') or '')
        target = self.canonical(value)
        if self.is_chapter(target):
            return target
        found = re.fullmatch(rf'/?({UUID})(?:#{SLUG})?', value) or re.search(rf'/({UUID})(?:#{SLUG})?$', value)
        slug = self.title_key(title)
        return f'{self.ROOT}/series/{slug}/read/{found[1]}' if found and slug else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.chapter_key(target) == self.title_key(title)

    def vocabulary(self, http):
        return [{'key': key, 'label': label, 'kind': 'genre'} for key, label in self.TAGS]

    def series(self, http, url):
        key = self.title_key(url)
        if not key:
            raise SourceError('Некорректная ссылка на тайтл Azuki.')
        item = self.api(http, f'/manga/{key}/v0' if re.fullmatch(UUID, key) else f'/manga/slug/{key}/v0')
        row = self.record_from(item)
        uuid = item.get('uuid') if isinstance(item, dict) else None
        if not row or not isinstance(uuid, str) or not re.fullmatch(UUID, uuid):
            raise SourceError('Azuki не предоставил карточку тайтла.')
        slug = self.title_key(row['url'])
        data = self.api(http, f'/mangas/{uuid}/chapters/v4', order='ascending', count='1000')
        items = data.get('chapters') if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SourceError('Azuki не предоставил список глав.')
        now = datetime.now(timezone.utc)
        chapters = {}
        for item in items:
            if not isinstance(item, dict) or not re.fullmatch(UUID, str(item.get('uuid', ''))):
                continue
            label = str(item.get('label') or '').strip()
            name = f'Chapter {label}' if label else str(item.get('short_name') or 'Chapter')
            if item.get('title'):
                name += ' - ' + str(item['title'])
            n = float(label) if re.fullmatch(r'[0-9]{1,5}(?:\.[0-9]{1,3})?', label) else None
            date = (stamp(item.get('release_date')) or now).date().isoformat() if item.get('release_date') else ''
            target = f'{self.ROOT}/series/{slug}/read/{item["uuid"]}'
            # Chapters outside their free window stay listed as paid.
            chapters[target] = {**self.chapter(target, name, n, date), 'locked': not free_now(item, now)}
        return row, self.order(chapters)

    def pages(self, http, url):
        uuid = self.chapter_identity(url)
        try:
            data = self.api(http, f'/chapters/{uuid}/pages/v1')
        except SourceAccessError:
            raise SourceAccessError('Глава Azuki доступна только после покупки.') from None
        pages = ((data.get('data') or {}).get('pages') if isinstance(data, dict) else None) or []
        rows = []
        for page in pages:
            link = best_webp(page.get('image') if isinstance(page, dict) else None)
            target = urlsplit(link)
            if target.scheme != 'https' or target.netloc != IMAGES or target.query:
                raise SourceError('Azuki изменил адрес изображений.')
            rows.append(JapanesePage(link + self.IMAGE_SUFFIX, XOR))
        return packed_refs(rows, url)


class Kodansha(Azuki):
    KEY = KODANSHA_KEY
    TAGS = KODANSHA_TAGS
    IMAGE_SUFFIX = ''

    def __init__(self):
        super().__init__(('8879500923091081231', 'Kodansha', 'en', 'https://kodansha.us', True))

    def saved_title_url(self, value):
        target = self.canonical(value)
        # Suwayomi stored the series UUID; the API resolves it to its slug.
        uuid = urlsplit(target).path.strip('/')
        if re.fullmatch(UUID, uuid):
            return self.title_url(uuid)
        return super().saved_title_url(value)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and tag not in {key for key, _ in KODANSHA_TAGS}:
            return [], False
        args = {'search_string': query} if query else {}
        if tag:
            args['tags'] = tag
        data = self.api(http, '/mangas/v1', **args, sort='recent_series' if sort == 'updated' else 'popular',
                        series_types='comic', format='digital', count=str(PAGE_SIZE), offset=str((page - 1) * PAGE_SIZE))
        items = data.get('mangas') if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SourceError('Kodansha изменил формат каталога.')
        rows = [row for row in map(self.record_from, items) if row]
        total = str(data.get('total_count', '0'))
        return rows, total.isdigit() and page * PAGE_SIZE < int(total)


class Omoi(Azuki):
    KEY = OMOI_KEY
    TAGS = OMOI_TAGS
    # The extension marks page requests with the DRM query.
    IMAGE_SUFFIX = '?drm=1'

    def __init__(self):
        super().__init__(('8195282477201261072', 'Omoi', 'en', 'https://www.omoi.com', True))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and tag not in OMOI_TAG_KEYS:
            return [], False
        args = {'page': str(page), 'sort': 'recent_series' if sort == 'updated' else 'popular'}
        if query:
            args['q'] = query
        target = query_url(self.ROOT + '/discover', **args)
        if tag:
            target += '&tags%5B%5D=' + tag
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(target, headers={'Referer': self.ROOT + '/'}, action='n9:azuki')
        doc = BeautifulSoup(raw, 'html.parser')
        rows = {}
        for node in doc.select('ol.o-series-card-list li'):
            link = node.select_one('a.a-card-link[href]')
            url = self.site_link(link['href'], final) if link else ''
            if not url or not self.is_title(url):
                continue
            cover = node.select_one('img')
            row = self.record(self.title_url(self.title_key(url)), node_text(link),
                              image_url(cover.get('src'), final) if cover else '')
            rows[row['id']] = row
        return list(rows.values()), bool(doc.select_one('a[rel=next]'))



SOURCES = (Kodansha(), Omoi())
