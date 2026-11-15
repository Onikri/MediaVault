"""Public manga page transport for publishers with tile placement."""

from io import BytesIO
import json
import time
from urllib.parse import urlsplit
import warnings

from PIL import Image
from requests import RequestException

from source_parser import SourceError, public_url


TILE_FRAGMENT = 'mv_comici_tiles='
GIGA_FRAGMENT = 'mv_giga_page'
TILES = frozenset(range(16))
TRANSPOSE = tuple(index % 4 * 4 + index // 4 for index in range(16))


def read_tiles(value):
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, RecursionError):
        parsed = None
    if (not isinstance(parsed, list) or len(parsed) != 16 or any(type(n) is not int for n in parsed)
            or set(parsed) != TILES):
        raise SourceError('Comici вернул некорректный порядок плиток страницы.')
    return parsed


def page_reference(value):
    """Validate internal page markers, which never go to the upstream server."""
    parts = urlsplit(value)
    host = parts.hostname or ''
    if parts.fragment.startswith(TILE_FRAGMENT):
        from manga_comici import image_route
        if not image_route(host) or len(parts.fragment) > 86:
            raise SourceError('Некорректный адрес страницы Comici.')
        marker = parts.fragment.removeprefix(TILE_FRAGMENT)
        tiles = read_tiles('[' + marker + ']') if marker else None
        return public_url(value, resolve_dns=False), tiles, 1, 'comici-image'
    if parts.fragment in {GIGA_FRAGMENT, GIGA_FRAGMENT + '=baku'}:
        from manga_gigaviewer import image_route
        if not image_route(host):
            raise SourceError('Некорректный адрес страницы GigaViewer.')
        tiles = TRANSPOSE if parts.fragment.endswith('=baku') else None
        return public_url(value, resolve_dns=False), tiles, 8, 'giga-image'
    return None


def decode_page(raw, tiles, alignment=1):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                width, height = image.size
                if min(width, height) < 4 or width * height > 24_000_000:
                    raise ValueError('Invalid image size')
                with image.convert('RGB') as original, original.copy() as result:
                    w = width // (4 * alignment) * alignment
                    h = height // (4 * alignment) * alignment
                    if not w or not h:
                        raise ValueError('Invalid tile size')
                    for dest, src in enumerate(tiles):
                        sx, sy = (src // 4) * w, (src % 4) * h
                        with original.crop((sx, sy, sx + w, sy + h)) as tile:
                            result.paste(tile, ((dest // 4) * w, (dest % 4) * h))
                    output = BytesIO()
                    result.save(output, 'JPEG', quality=90)
                    return output.getvalue()
    except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise SourceError('Источник вернул повреждённое изображение.') from None


def fetch_page(http, reference, headers):
    """Both the online reader and CBZ use the exact same page transformation."""
    target, tiles, alignment, action = reference
    response, _ = http._open(target, headers=headers, action=action)
    try:
        raw = bytearray()
        for block in response.iter_content(65536):
            raw.extend(block)
            if len(raw) > 30 * 1024 * 1024 or http.deadline and time.monotonic() >= http.deadline:
                raise SourceError('Страница превысила лимит загрузки.')
    except RequestException:
        raise SourceError('Источник прервал загрузку страницы.') from None
    finally:
        response.close()
    if tiles is not None:
        return decode_page(raw, tiles, alignment), 'image/jpeg'
    from manga_download import image_extension
    extension = image_extension(raw[:32])
    if not extension:
        raise SourceError('Источник не предоставил изображение страницы.')
    return bytes(raw), 'image/' + ('jpeg' if extension == 'jpg' else extension)
