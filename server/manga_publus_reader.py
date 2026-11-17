"""Shared Publus manifest and page transport for public publisher previews."""

from dataclasses import dataclass
from io import BytesIO
import re
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from PIL import Image

from manga_clipstudio import endpoint, json_data
from manga_publus_pack import decode_pack, image_path
from manga_publus_tiles import keyed_moves, plain_moves
from manga_speedbinb import remember
from manga_webcomics import query_url
from source_parser import SourceError

FILENAME = re.compile(r'[A-Za-z0-9_.~-]{1,180}')
SIGNATURE_FIELDS = {'hti', 'cfg', 'BID', 'uuid', 'pfCd', 'Policy', 'Signature', 'Key-Pair-Id'}
IMAGE_EXT = re.compile(r'\.(?:jpe?g|png|webp|gif|avif)$', re.I)


def permitted(value, action):
    parts = urlsplit(value)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if len(dict(pairs)) != len(pairs) or any(key not in SIGNATURE_FIELDS or len(val) > 4096 for key, val in pairs):
        return False
    if action == 'publus-config':
        return parts.path.endswith(('/configuration_pack.json', '/content.json'))
    return bool(IMAGE_EXT.search(parts.path))


def signed_content(value, episode):
    content = value.get('url')
    if not isinstance(content, str) or not content:
        raise SourceError('Издатель не предоставил открытый адрес издательского пакета.')
    base = endpoint(content, episode).rstrip('/') + '/'
    if urlsplit(base).query:
        raise SourceError('Publus вернул неподдерживаемую ссылку на выпуск.')
    data = value.get('auth_info')
    if not isinstance(data, dict):
        return base, {}
    return base, {key: val for key in SIGNATURE_FIELDS if type(val := data.get(key)) in (str, int)}


def numeric(mapping, key, minimum, maximum, default=0):
    val = mapping.get(key, default)
    if type(val) is not int or not minimum <= val <= maximum:
        raise SourceError('Publus вернул неверный параметр страницы.')
    return val


@dataclass(frozen=True)
class PublusPage:
    target: str
    name: str
    number: int
    content_size: tuple
    block: tuple
    keys: tuple
    seeds: tuple
    scrambled: bool

    def decode(self, value):
        if not self.scrambled:
            return value
        try:
            with Image.open(BytesIO(value)) as image:
                if image.width * image.height > 35_000_000:
                    raise SourceError('Publus вернул слишком большое изображение.')
                bitmap = image.convert('RGB')
            width, height = bitmap.size
            block_w, block_h = self.block
            content_w, content_h = self.content_size
            if content_w > width or content_h > height:
                raise SourceError('Размер области Publus превышает границы страницы.')
            if self.keys and block_w and block_h:
                moves = keyed_moves(self.name, self.number, width, height,
                                    block_w, block_h, self.keys, self.seeds)
            else:
                moves = plain_moves(width, height, sum(ord(c) for c in f'{self.name}/{self.number}') % 4 + 1)
            canvas = Image.new('RGB', bitmap.size, 'white')
            for sx, sy, dx, dy, w, h in moves:
                if min(sx, sy, dx, dy) < 0 or max(sx, dx) + w > width or max(sy, dy) + h > height:
                    raise SourceError('Publus вернул некорректную раскладку плиток.')
                canvas.paste(bitmap.crop((sx, sy, sx + w, sy + h)), (dx, dy))
            if content_w and content_h:
                canvas = canvas.crop((0, 0, content_w, content_h))
            out = BytesIO()
            canvas.save(out, format='PNG')
            return out.getvalue()
        except (OSError, ValueError, Image.DecompressionBombError):
            raise SourceError('Publus вернул повреждённое изображение.') from None

    def fetch(self, http, referer):
        from manga_page_media import read_image

        response, _ = http._open(self.target, headers={'Referer': referer}, action='publus-image')
        return self.decode(read_image(http, response))


def pages_from_manifest(content, config, keys, auth, hash_filenames):
    info = config.get('configuration')
    items = info.get('contents') if isinstance(info, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= 1500:
        raise SourceError('Publus не предоставил список страниц выпуска.')
    entries = []
    for item in items:
        name = item.get('file') if isinstance(item, dict) else None
        if not isinstance(name, str) or not 1 <= len(name) <= 500 or any(
                not FILENAME.fullmatch(part) or part in ('.', '..') for part in name.split('/')):
            raise SourceError('Publus вернул неверное имя страницы.')
        try:
            page = config[name]['FileLinkInfo']['PageLinkInfoList'][0]['Page']
            size = page['Size']
            number = numeric(page, 'No', 0, 100000)
            dimensions = (numeric(size, 'Width', 0, 16000), numeric(size, 'Height', 0, 16000))
            block = (numeric(page, 'BlockWidth', 0, 4096), numeric(page, 'BlockHeight', 0, 4096))
            seeds = tuple(numeric(page, key, -(2**63), 2**63 - 1) for key in ('NS', 'PS', 'RS'))
            scrambled = page.get('DummyWidth') is not None
        except (KeyError, TypeError, IndexError, AttributeError):
            raise SourceError('Publus вернул неполную конфигурацию страницы.') from None
        path = image_path(name, number, keys if hash_filenames else ())
        target = query_url(content + path, **auth)
        entries.append(PublusPage(target, name, number, dimensions, block, keys, seeds, scrambled))
    return entries


def reader_pages(http, content, episode, *, auth=None, hash_filenames=True):
    base = endpoint(content, episode)
    if urlsplit(base).query:
        raise SourceError('Publus вернул неподдерживаемую ссылку на выпуск.')
    base = base.rstrip('/') + '/'
    auth = auth or {}
    if not set(auth) <= SIGNATURE_FIELDS:
        raise SourceError('Publus вернул неподдерживаемые параметры доступа к выпуску.')
    address = query_url(base + 'configuration_pack.json', **auth)
    payload, final, _ = http.document(address, headers={'Referer': episode}, action='publus-config')
    if final != address:
        raise SourceError('Publus перенаправил конфигурацию выпуска.')
    config = json_data(payload)
    keys = ()
    if isinstance(config.get('data'), str):
        config, keys = decode_pack(config['data'])
    pages = pages_from_manifest(base, config, keys, auth, hash_filenames)
    public = urlunsplit(urlsplit(episode)._replace(fragment=''))
    return remember([(query_url(public, mv_publus=index), page) for index, page in enumerate(pages)], public)


def plain_content_pack(http, content, episode, auth):
    import json

    url = query_url(content + 'content.json', **auth)
    raw, final, _ = http.document(url, headers={'Referer': episode}, action='publus-config')
    if final != url:
        raise SourceError('Издатель перенаправил манифест выпуска.')
    try:
        data = json.loads(raw)
    except ValueError:
        raise SourceError('Издатель изменил формат манифеста.') from None
    if not isinstance(data, list):
        raise SourceError('Издатель изменил формат манифеста.')
    pages = []
    for group in data:
        if not isinstance(group, list):
            continue
        for row in group:
            if not isinstance(row, dict) or not isinstance(links := row.get('effectTargetImgs'), list):
                continue
            for value in links:
                if (not isinstance(value, str) or value.startswith('/') or not IMAGE_EXT.search(value)
                        or any(part in ('', '.', '..') for part in unquote(value).split('/'))):
                    raise SourceError('Некорректный адрес страницы в открытом манифесте.')
                image = endpoint(value, content)
                if not image.startswith(content) or urlsplit(image).query:
                    raise SourceError('Некорректный адрес страницы в открытом манифесте.')
                pages.append(PublusPage(query_url(image, **auth), '', 0, (0, 0), (0, 0), (), (), False))
    stable = urlunsplit(urlsplit(episode)._replace(fragment=''))
    return remember([(query_url(stable, mv_publus=index), page) for index, page in enumerate(pages)], stable)
