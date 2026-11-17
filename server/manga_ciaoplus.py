"""Ciao Plus public request digests and image layouts."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from urllib.parse import parse_qsl, urlsplit

from PIL import Image

from manga_direct_payloads import JsonSeries
from manga_madara import image_url
from manga_mangaone import TOKYO
from manga_series_port import number
from manga_speedbinb import remember
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://ciao.shogakukan.co.jp'
API = 'https://api.ciao.shogakukan.co.jp'
ID = r'\d{1,10}'
IDS = rf'{ID}(?:,{ID})*'
GENRES = dict(zip(('1', '2', '3', '4', '5', '6', '7', '8', '9', '11'),
                  ('ギャグ・エッセイ', 'ラブ', 'ホラー・ミステリー', '家族', '青春・学園', '友情',
                   'ファンタジー', 'ドリーム・サクセス', '異世界', '新人コミック大賞')))


def digest(args):
    parts = [hashlib.sha256(key.encode()).hexdigest() + '_' + hashlib.sha512(value.encode()).hexdigest()
             for key, value in sorted(args.items())]
    return hashlib.sha512(hashlib.sha256(','.join(parts).encode()).hexdigest().encode()).hexdigest()


def public_api(host, path, query):
    if host != 'api.ciao.shogakukan.co.jp':
        return False
    return path == '/episode/list' and not query or bool(transport('https://' + host + path + '?' + query, 'GET', None))


def transport(url, method, body):
    parts = urlsplit(url)
    if parts.netloc != 'api.ciao.shogakukan.co.jp':
        return None
    if method == 'POST':
        if parts.path != '/episode/list' or parts.query or not isinstance(body, dict) or set(body) != {'platform', 'episode_id_list'}:
            return None
        if (body['platform'] == '3' and isinstance(ids := body['episode_id_list'], str)
                and len(ids) <= 64_000 and re.fullmatch(IDS, ids)):
            return digest(body)
        return None
    if method != 'GET' or body is not None:
        return None
    pairs = parse_qsl(parts.query)
    args = dict(pairs)
    if len(args) != len(pairs) or args.get('platform') != '3':
        return None
    rest = set(args) - {'platform'}
    route = parts.path
    if route == '/ranking/all':
        valid = (rest == {'ranking_id', 'offset', 'limit', 'is_top'} and args['ranking_id'] in '1234567'
                 and len(args['ranking_id']) == 1 and re.fullmatch(r'\d{1,6}', args['offset'])
                 and args['limit'] == '26' and args['is_top'] == '0')
    elif route == '/title/weekly':
        valid = not rest
    elif route == '/search/title':
        valid = (args.get('limit') == '99999' and (rest == {'limit', 'keyword'} and 1 <= len(args['keyword']) <= 160
                                                  or rest == {'limit', 'genre_id'} and args['genre_id'] in GENRES))
    else:
        field = {'/title/list': 'title_id_list', '/genre/list': 'genre_id_list', '/web/episode/viewer': 'episode_id'}.get(route)
        valid = (field is not None and rest == {field} and len(args[field]) < 1000
                 and re.fullmatch(ID if field == 'episode_id' else IDS, args[field]))
    return digest(args) if valid else None


def tile_order(seed):
    n = seed & 0xffffffff
    pairs = []
    for index in range(16):
        n ^= (n << 13) & 0xffffffff
        n ^= n >> 17
        n ^= (n << 5) & 0xffffffff
        pairs.append((n, index))
    return [index for _, index in sorted(pairs)]


@dataclass(frozen=True)
class CiaoPage:
    seed: int
    version: int

    def decode(self, raw):
        try:
            with Image.open(BytesIO(raw)) as image:
                if image.width * image.height > 35_000_000:
                    raise SourceError('Ciao Plus превысил лимит размера страницы.')
                bitmap = image.convert('RGB')
            divider = 32 if self.version == 2 else 8
            tile_w, tile_h = (length // divider * (divider // 4) for length in bitmap.size)
            result = bitmap.copy()
            if tile_w and tile_h:
                for target, source in enumerate(tile_order(self.seed)):
                    x, y = source % 4 * tile_w, source // 4 * tile_h
                    result.paste(bitmap.crop((x, y, x + tile_w, y + tile_h)),
                                 (target % 4 * tile_w, target // 4 * tile_h))
            out = BytesIO()
            result.save(out, format='PNG')
            return out.getvalue()
        except (OSError, ValueError, Image.DecompressionBombError):
            raise SourceError('Ciao Plus вернул повреждённое изображение.') from None


class CiaoPlus(JsonSeries):
    def __init__(self):
        super().__init__(('1585589665574145721', 'Ciao Plus', 'ja', ROOT, False),
                         rf'/comics/title/({ID})/?', rf'/comics/title/({ID})/episode/({ID})/?', interval=.35)

    def title_for(self, url):
        return ROOT + '/comics/title/' + self.chapter_key(url)

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = self.title_key(url) or urlsplit(url).path.strip('/').rsplit('/', 1)[-1]
        return ROOT + '/comics/title/' + key.zfill(5) if re.fullmatch(ID, key) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = urlsplit(url).path.strip('/').rsplit('/', 1)[-1]
        return title.rstrip('/') + '/episode/' + key if self.is_title(title) and re.fullmatch(ID, key) else ''

    def api(self, http, path, *, body=None, **args):
        self.origin.wait(getattr(http, 'deadline', None))
        url = query_url(API + path, platform='3', **args) if body is None else API + path
        options = {'method': 'POST', 'data': {'platform': '3', **body}} if body is not None else {}
        payload, final, _ = http.document(url, headers={'Referer': ROOT + '/'}, action='ciaoplus-json', **options)
        if final != url:
            raise SourceError('Ciao Plus перенаправил запрос.')
        try:
            obj = json.loads(payload)
        except ValueError:
            raise SourceError('Ciao Plus не предоставил доступные данные.') from None
        if not isinstance(obj, dict):
            raise SourceError('Ciao Plus изменил формат выдачи.')
        return obj

    def row_for(self, data, **extra):
        key, name = str(data.get('title_id', '')), data.get('title_name')
        if not re.fullmatch(ID, key) or not isinstance(name, str) or not name:
            return None
        url = ROOT + '/comics/title/' + key.zfill(5)
        return self.record(url, name, image_url(data.get('thumbnail_image_url'), url), **extra)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        more = False
        if query or tag in GENRES or sort == 'updated':
            if page != 1:
                return [], False
            if query or tag in GENRES:
                args = {'keyword': query} if query else {'genre_id': tag}
                obj = self.api(http, '/search/title', limit=99999, **args)
            else:
                obj = self.api(http, '/title/weekly')
        else:
            data = self.api(http, '/ranking/all', ranking_id=1, offset=(page - 1) * 25, limit=26, is_top=0)
            ids = [key.zfill(5) for row in data.get('ranking_title_list') or []
                   if isinstance(row, dict) and re.fullmatch(ID, key := str(row.get('id', '')))]
            more = len(ids) > 25
            obj = self.api(http, '/title/list', title_id_list=','.join(ids[:25])) if ids else {}
        rows = [row for item in obj.get('title_list') or [] if isinstance(item, dict) and (row := self.row_for(item))]
        return rows, more

    def vocabulary(self, http):
        return [{'key': key, 'label': label, 'kind': 'genre'} for key, label in GENRES.items()]

    def series(self, http, url):
        key = self.title_key(url).zfill(5)
        details = self.api(http, '/title/list', title_id_list=key)
        item = next((entry for entry in details.get('title_list') or [] if isinstance(entry, dict)
                     and str(entry.get('title_id', '')).zfill(5) == key), None)
        if not item:
            raise SourceError('Ciao Plus не вернул карточку выбранной серии.')
        row = self.row_for(item, genres=[GENRES[g] for code in item.get('genre_id_list') or []
                                         if (g := str(code)) in GENRES],
                           authors=[item.get('author_text') or ''],
                           description='\n\n'.join(str(item[k]) for k in ('introduction_text', 'new_episode_update_cycle_text')
                                                   if item.get(k)))
        if not row:
            raise SourceError('Ciao Plus не вернул название произведения.')
        ids = [str(code) for code in item.get('episode_id_list') or [] if re.fullmatch(ID, str(code))]
        result = self.api(http, '/episode/list', body={'episode_id_list': ','.join(ids[:5000])}) if ids else {}
        episodes = {}
        for entry in result.get('episode_list') or []:
            if not isinstance(entry, dict) or not re.fullmatch(ID, identifier := str(entry.get('episode_id', ''))):
                continue
            if str(entry.get('title_id', '')).zfill(5) != key:
                continue
            target = ROOT + '/comics/title/' + key + '/episode/' + identifier
            title = str(entry.get('episode_name') or '').strip()
            n = number(entry.get('index'))
            if n is not None and title.startswith(row['title'].strip()):
                title = f'【第{n:g}話】 {title}'
            try:
                date = datetime.fromisoformat(entry.get('start_time') or '').replace(tzinfo=TOKYO).date().isoformat()
            except (TypeError, ValueError):
                date = ''
            episodes[target] = self.chapter(target, title, n, date)
        return row, self.order(episodes)

    def pages(self, http, url):
        identifier = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)[2]
        data = self.api(http, '/web/episode/viewer', episode_id=identifier)
        seed = data.get('scramble_seed')
        version = 2 if data.get('scramble_ver') == 2 else 1
        if type(seed) is not int:
            raise SourceAccessError('Ciao Plus не предоставил открытый выпуск.')
        decoder = CiaoPage(seed, version)
        return remember([(value, decoder) for page in data.get('page_list') or []
                         if (value := image_url(page, url))], url)


SOURCES = (CiaoPlus(),)
