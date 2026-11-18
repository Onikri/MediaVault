"""K Manga (keiyoushi ``src/en/kmanga`` at 6f345a8).

Every request to ``api.kmanga.kodansha.com`` carries the web client's
``X-Kmanga-Hash``: SHA-512 over the SHA-256 of the sorted, individually
hashed parameters plus the hashed birthday cookie, for the guest client 0
(the extension's logged-out default). Only episodes without a point price
(or marked free by the site) open; the others stay listed as paid. Viewer pages are 4x4 tile puzzles
whose order derives from the response's scramble seed, recomposed like the
extension's ``ImageInterceptor``.
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
from io import BytesIO
import json
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

from PIL import Image

from manga_direct_payloads import JsonSeries
from manga_japanese_readers import JapanesePage, packed_refs
from manga_ninth_routes import Route, register
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://kmanga.kodansha.com'
API = 'https://api.kmanga.kodansha.com'
ID = r'[1-9][0-9]{0,9}'
LIMIT = 25
BIRTHDAY = '2000-01'
GRID = 4
CHARSETS = ('we7ru3ty8i', 'h4xm9bqz1p')
GENRES = (
    ('1', 'Romance･Romcom'), ('2', 'Horror･Mystery･Suspense'), ('3', 'Gag･Comedy･Slice-of-Life'), ('4', 'SF･Fantasy'),
    ('5', 'Sports'), ('6', 'Drama'), ('7', 'Outlaws･Underworld･Punks'), ('8', 'Action･Battle'),
    ('9', 'Isekai･Super Powers'), ('10', 'One-off Books'), ('11', 'Shojo/josei'), ('12', 'Yaoi/BL'), ('13', 'LGBTQ'),
    ('14', 'Yuri/GL'), ('15', 'Anime'), ('16', 'Award Winner'),
)
GENRE_KEYS = frozenset(key for key, _ in GENRES)
HASH = re.compile(r'[0-9a-f]{128}')
IDS = re.compile(rf'{ID}(?:,{ID}){{0,4999}}')


def hashed(key, value):
    return hashlib.sha256(key.encode()).hexdigest() + '_' + hashlib.sha512(value.encode()).hexdigest()


def request_hash(params, expires):
    joined = ','.join(hashed(key, params[key]) for key in sorted(params))
    return hashlib.sha512((hashlib.sha256(joined.encode()).hexdigest() + hashed(BIRTHDAY, expires)).encode()).hexdigest()


def accepted(path, args):
    if path == '/ranking/all':
        offset = args.get('offset', '')
        return (set(args) == {'ranking_id', 'offset', 'limit'} and args['ranking_id'] == '12' and offset.isdigit()
                and int(offset) % LIMIT == 0 and int(offset) < 2000 * LIMIT and args['limit'] == str(LIMIT + 1))
    if path == '/title/list':
        return set(args) == {'title_id_list'} and bool(re.fullmatch(rf'{ID}(?:,{ID}){{0,{LIMIT - 1}}}', args['title_id_list']))
    if path == '/title/weekly':
        return not args
    if path == '/search/title':
        return ((set(args) == {'keyword', 'limit'} and 1 <= len(args['keyword']) <= 160
                 or set(args) == {'genre_id', 'limit'} and args['genre_id'] in GENRE_KEYS) and args['limit'] == '99999')
    if path == '/web/title/detail':
        return set(args) == {'title_id'} and bool(re.fullmatch(ID, args['title_id']))
    if path == '/genre/list':
        return set(args) == {'genre_id_list'} and bool(re.fullmatch(r'[0-9]{1,4}(?:, [0-9]{1,4}){0,40}', args['genre_id_list']))
    if path == '/web/episode/viewer':
        return set(args) == {'episode_id'} and bool(re.fullmatch(ID, args['episode_id']))
    if path == '/episode/list':
        return set(args) == {'episode_id_list'} and bool(IDS.fullmatch(args['episode_id_list']))
    return False


def form(data):
    if not isinstance(data, (bytes, str)) or len(data) > 65536:
        return None
    try:
        rows = parse_qsl(data.decode() if isinstance(data, bytes) else data, keep_blank_values=True, strict_parsing=True)
    except (UnicodeDecodeError, ValueError):
        return None
    return dict(rows) if len(rows) == len(dict(rows)) else None


def route(url, method, data, headers):
    if url.netloc != 'api.kmanga.kodansha.com':
        return None
    expires = headers.get('Kmanga-Expires', '')
    signature = headers.get('X-Kmanga-Hash', '')
    if not re.fullmatch(r'[0-9]{10}', expires) or not HASH.fullmatch(signature):
        return None
    if method == 'POST':
        args = form(data)
        if url.query or url.path != '/episode/list' or args is None:
            return None
    else:
        if data is not None:
            return None
        try:
            rows = parse_qsl(url.query, keep_blank_values=True, strict_parsing=bool(url.query), max_num_fields=4)
        except ValueError:
            return None
        args = dict(rows)
        if len(rows) != len(args) or url.path == '/episode/list':
            return None
    if not accepted(url.path, args) or request_hash(args, expires) != signature:
        return None
    headers = {'Accept': 'application/json', 'X-Kmanga-Platform': '3', 'x-kmanga-client-id': '0',
               'x-kmanga-is-crawler': 'false', 'X-Kmanga-Hash': signature, 'Origin': ROOT, 'Referer': ROOT + '/',
               'Cookie': 'birthday=' + json.dumps({'value': BIRTHDAY, 'expires': int(expires)}, separators=(',', ':'))}
    if method == 'POST':
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        return Route(headers=headers, post=True, data=urlencode(args).encode(), redirect=False)
    return Route(headers=headers, redirect=False)


register('kmanga', route)


def xorshift(value):
    value ^= (value << 13) & 0xFFFFFFFF
    value ^= value >> 17
    value ^= (value << 5) & 0xFFFFFFFF
    return value & 0xFFFFFFFF


def tile_order(seed, title, episode):
    charset = CHARSETS[0] if title % 2 == 0 else CHARSETS[1]
    parsed = 0
    for char in seed:
        index = charset.find(char)
        if index < 0:
            break
        parsed = (parsed * 10 + index) & 0xFFFFFFFFFFFFFFFF
    state = (parsed & 0xFFFFFFFF) ^ ((title + episode) & 0xFFFFFFFF)
    pairs = []
    for index in range(GRID * GRID):
        state = xorshift(state)
        pairs.append((state, index))
    pairs.sort(key=lambda pair: pair[0])
    # Destination tile → source tile.
    return tuple(source for _, source in pairs)


def unscramble(data, order):
    try:
        with Image.open(BytesIO(data)) as image, image.convert('RGB') as source:
            width, height = source.size
            block_w, block_h = (width // 8 * 8) // GRID, (height // 8 * 8) // GRID
            result = source.copy()
            for dest, origin in enumerate(order):
                sx, sy = origin % GRID * block_w, origin // GRID * block_h
                dx, dy = dest % GRID * block_w, dest // GRID * block_h
                with source.crop((sx, sy, sx + block_w, sy + block_h)) as tile:
                    result.paste(tile, (dx, dy))
            output = BytesIO()
            result.save(output, 'JPEG', quality=90)
            return output.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise SourceError('K Manga вернул повреждённое изображение.') from None


@dataclass(frozen=True)
class KMangaPage(JapanesePage):
    order: tuple = ()

    def fetch(self, http, referer):
        from manga_page_media import read_image

        response, _ = http._open(self.url, headers={'Referer': ROOT + '/'})
        return unscramble(read_image(http, response), self.order)


class KManga(JsonSeries):
    def __init__(self):
        super().__init__(('8143442163119480220', 'K Manga', 'en', ROOT, False), rf'/title/({ID})',
                         rf'/title/({ID})/episode/({ID})', interval=.3)

    def title_for(self, url):
        return f'{ROOT}/title/{self.chapter_key(url)}'

    def chapter_identity(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return match.groups() if match else ()

    def call(self, http, path, post=False, **args):
        expires = str(int(time.time()) + 315360000)
        headers = {'Kmanga-Expires': expires, 'X-Kmanga-Hash': request_hash(args, expires)}
        self.origin.wait(getattr(http, 'deadline', None))
        if post:
            raw, _, _ = http.document(API + path, method='POST', data=urlencode(args).encode(), headers=headers,
                                      action='n9:kmanga')
        else:
            raw, _, _ = http.document(query_url(API + path, **args) if args else API + path, headers=headers,
                                      action='n9:kmanga')
        try:
            data = json.loads(raw)
        except ValueError:
            raise SourceError('K Manga изменил формат API.') from None
        if not isinstance(data, dict) or data.get('status') != 'success':
            raise SourceError('K Manga отклонил запрос API.')
        return data

    def title_row(self, item, **extra):
        if not isinstance(item, dict) or type(item.get('title_id')) is not int or not isinstance(item.get('title_name'), str):
            return None
        cover = item.get('thumbnail_image_url') or item.get('banner_image_url') or item.get('thumbnail_rect_image_url') or ''
        return self.record(f'{ROOT}/title/{item["title_id"]}', item['title_name'].strip(), cover, **extra)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and tag not in GENRE_KEYS:
            return [], False
        if query or tag:
            if page > 1:
                return [], False
            args = {'keyword': query} if query else {'genre_id': tag}
            data = self.call(http, '/search/title', **args, limit='99999')
            return [row for item in data.get('title_list') or [] if (row := self.title_row(item))], False
        if sort == 'updated':
            if page > 1:
                return [], False
            data = self.call(http, '/title/weekly')
            today = next((day for day in data.get('weekly_list') or []
                          if isinstance(day, dict) and day.get('weekday_index') == data.get('today_weekday_index')), {})
            titles = {item.get('title_id'): item for item in data.get('title_list') or [] if isinstance(item, dict)}
            return [row for key in today.get('title_id_list') or [] if (row := self.title_row(titles.get(key)))], False
        data = self.call(http, '/ranking/all', ranking_id='12', offset=str((page - 1) * LIMIT), limit=str(LIMIT + 1))
        ids = [str(item['id']) for item in data.get('ranking_title_list') or []
               if isinstance(item, dict) and type(item.get('id')) is int]
        if not ids:
            return [], False
        more = len(ids) > LIMIT
        listed = self.call(http, '/title/list', title_id_list=','.join(ids[:LIMIT]))
        return [row for item in listed.get('title_list') or [] if (row := self.title_row(item))], more

    def vocabulary(self, http):
        return [{'key': key, 'label': label, 'kind': 'genre'} for key, label in GENRES]

    def series(self, http, url):
        key = self.title_key(url)
        detail = self.call(http, '/web/title/detail', title_id=key).get('web_title')
        if not isinstance(detail, dict) or not isinstance(detail.get('episode_id_list'), list):
            raise SourceError('K Manga не предоставил карточку тайтла.')
        genres = []
        genre_ids = [value for value in detail.get('genre_id_list') or [] if type(value) is int][:40]
        if genre_ids:
            listed = self.call(http, '/genre/list', genre_id_list=', '.join(map(str, genre_ids)))
            genres = [item.get('genre_name') for item in listed.get('genre_list') or [] if isinstance(item, dict)]
        description = str(detail.get('introduction_text') or '')
        if detail.get('next_updated_text'):
            description += '\n\n' + str(detail['next_updated_text'])
        row = self.title_row({**detail, 'title_id': int(key)}, description=description.strip(), genres=genres,
                             authors=[detail.get('author_text') or ''])
        if row is None:
            raise SourceError('K Manga не предоставил карточку тайтла.')
        episodes = [str(value) for value in detail['episode_id_list'] if type(value) is int]
        chapters = {}
        if episodes:
            data = self.call(http, '/episode/list', post=True, episode_id_list=','.join(episodes[:5000]))
            for item in data.get('episode_list') or []:
                if not isinstance(item, dict) or type(item.get('episode_id')) is not int or item.get('title_id') != int(key):
                    continue
                point = item.get('point')
                if type(point) is not int:
                    continue
                date = ''
                try:
                    date = datetime.strptime(str(item.get('start_time') or ''), '%Y-%m-%d %H:%M:%S').date().isoformat()
                except ValueError:
                    pass
                target = f'{ROOT}/title/{key}/episode/{item["episode_id"]}'
                name = ' '.join(str(item.get('episode_name') or '').split()) or f'Episode {item.get("index")}'
                n = item.get('index') if type(item.get('index')) is int else None
                chapters[target] = {**self.chapter(target, name, float(n) if n is not None else None, date), 'season': 1,
                                    'locked': point > 0 and item.get('badge') != 3 and item.get('rental_finish_time') is None}
        return row, self.order(chapters)

    def pages(self, http, url):
        title, episode = self.chapter_identity(url)
        try:
            data = self.call(http, '/web/episode/viewer', episode_id=episode)
        except SourceError as error:
            if 'HTTP 400' in str(error):
                raise SourceAccessError('Эпизод K Manga доступен только после покупки или аренды.') from None
            raise
        seed = data.get('scramble_seed')
        if not isinstance(seed, str) or data.get('title_id') != int(title) or data.get('episode_id') != int(episode):
            raise SourceError('K Manga вернул другой эпизод.')
        order = tile_order(seed, int(title), int(episode))
        rows = []
        for link in data.get('page_list') or []:
            target = urlsplit(link if isinstance(link, str) else '')
            if target.scheme != 'https' or target.netloc != 'cdn.kmanga.kodansha.com':
                raise SourceError('K Manga изменил адрес страниц.')
            rows.append(KMangaPage(link, order=order))
        return packed_refs(rows, url)


SOURCES = (KManga(),)
