"""Alpha Manga catalogue and the published viewer's tile layout."""

import base64
import binascii
from io import BytesIO
import json
import re
from struct import iter_unpack
from urllib.parse import urlsplit
import warnings

from PIL import Image

from manga_direct_payloads import JsonSeries, items
from manga_madara import image_url, release_date
from manga_series_port import MAX_PAGES, Meta, number
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


ROOT = 'https://www.alpha-manga.com'
ID = r'[1-9]\d{0,10}'
GENRES = {'1001': 'Shonen', '1002': 'Shojo', '1033': 'Romance', '1003': 'Action', '1037': 'Villainess',
          '1005': 'Reincarnation', '1057': 'Slice of Life', '1041': 'Anime'}
ROTATE = (None, Image.Transpose.ROTATE_90, Image.Transpose.ROTATE_180, Image.Transpose.ROTATE_270)


class AlphaTileLayout:
    def __init__(self, key):
        self.key = key

    def decode(self, raw):
        if not self.key:
            return raw
        coordinates = list(iter_unpack('<II', self.key))
        first, second = coordinates[0]
        tile, padding = second >> 24, first >> 27 & 7
        if not tile:
            return raw
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as image:
                    return self.restore(image, tile, padding, coordinates)
        except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
            raise SourceError('Alpha Manga вернул повреждённую страницу или карту плиток.') from None

    @staticmethod
    def restore(image, tile, padding, coordinates):
        raw_width, raw_height = image.size
        cols, rows = (raw_width + tile - 1) // tile, (raw_height + tile - 1) // tile
        bleed, step = 2 * padding, tile - 2 * padding
        width, height = raw_width - cols * bleed, raw_height - rows * bleed
        if (min(step, width, height) <= 0 or raw_width * raw_height > 24_000_000
                or not 1 <= len(coordinates) <= cols * rows * 2):
            raise ValueError('Invalid tile count')
        with image.convert('RGB') as source, Image.new('RGB', (width, height)) as output:
            for columns, slots in coordinates:
                if slots >> 24 not in (0, tile):
                    raise ValueError('Invalid tile size')
                flip, rotation = bool(columns & 1), columns >> 1 & 3
                x, y = columns >> 15 & 4095, columns >> 3 & 4095
                sx, sy = (slots >> 16 & 255) * tile, (slots >> 8 & 255) * tile
                tile_w = (width - x if x // step == cols - 1 else step) + bleed
                tile_h = (height - y if y // step == rows - 1 else step) + bleed
                dw, dh = (tile_h, tile_w) if rotation % 2 else (tile_w, tile_h)
                cw, ch = min(dw, raw_width - sx), min(dh, raw_height - sy)
                if min(cw, ch) <= 0 or x >= width or y >= height:
                    raise ValueError('Tile bounds')
                with source.crop((sx, sy, sx + cw, sy + ch)) as crop:
                    piece = crop
                    if flip:
                        piece = piece.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    if rotation:
                        rotated = piece.transpose(ROTATE[rotation])
                        if piece is not crop:
                            piece.close()
                        piece = rotated
                    try:
                        output.paste(piece, (x - padding + (dw - piece.width) // 2,
                                             y - padding + (dh - piece.height) // 2))
                    finally:
                        if piece is not crop:
                            piece.close()
            data = BytesIO()
            output.save(data, 'WEBP', lossless=True)
            return data.getvalue()


def keys(value):
    _, separator, payload = str(value).partition('base64,')
    if not separator or len(payload) > 1_500_000:
        raise ValueError('Invalid placeholder')
    body = base64.b64decode(payload, validate=True)
    if not body.startswith(b'\x89PNG\r\n\x1a\n') or len(body) < 33:
        raise ValueError('Missing PNG header')
    result = []
    pos = 33
    while pos + 2 <= len(body) and len(result) < MAX_PAGES:
        n = int.from_bytes(body[pos:pos + 2], 'little') * 8
        end = pos + 2 + n
        if end > len(body):
            break
        result.append(body[pos + 2:end])
        pos = end
    return result


class AlphaManga(JsonSeries):
    meta = Meta('h1.c-h1', 'img.p-manga-detail__banner-image', 'p.p-manga-detail__about-overview-text',
                tags='.p-manga-detail__tags .c-tag', author='h3.p-manga-detail__about-label:-soup-contains("Author")',
                status='.p-manga-detail__status p')

    def __init__(self):
        super().__init__(('370653027333714265', 'Alpha Manga', 'en', ROOT, False),
                         rf'/manga/({ID})/?', rf'/manga/({ID})/({ID})/?', interval=.35)

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = self.title_key(url) or urlsplit(url).path.strip('/')
        return self.ROOT + '/manga/' + key if re.fullmatch(ID, key) else ''

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.ROOT + '/manga/' + key if key else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return query_url(url.split('?')[0], mode='vertical')
        key = urlsplit(url).path.strip('/')
        return query_url(title.rstrip('/') + '/' + key, mode='vertical') if (
            self.is_title(title) and re.fullmatch(ID, key)) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        data = self.json(http, query_url(self.ROOT + '/manga/search.json', query=query, genre=tag if tag in GENRES else '', page=page))
        result = []
        for entry in items(data, 'data'):
            key = str(entry.get('manga_sele_id') or '') if isinstance(entry, dict) else ''
            title = entry.get('title') if key else ''
            if re.fullmatch(ID, key) and isinstance(title, str) and title:
                link = self.ROOT + '/manga/' + key
                result.append(self.record(link, title, image_url(entry.get('banner_image_url'), link)))
        return result, bool(data.get('has_more'))

    def vocabulary(self, http):
        return [{'label': label, 'sourceId': key, 'category': 'genre'} for key, label in GENRES.items()]

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        row = self.metadata(doc, final, self.meta)
        data = self.json(http, final.rstrip('/') + '/episodes.json', final)
        rows = {}
        for episode in items(data, 'episodes'):
            key = str(episode.get('episode_no') or '') if isinstance(episode, dict) else ''
            if not re.fullmatch(ID, key):
                continue
            if episode.get('status') != 'free' and not (episode.get('is_purchased') or episode.get('is_on_rental')):
                continue
            target = query_url(final.rstrip('/') + '/' + key, mode='vertical')
            date = release_date(episode.get('update_date') or '', '%b %d, %Y %H:%M')
            rows[target] = self.chapter(target, episode.get('title') or 'Chapter ' + key, number(episode.get('story_no')), date)
        return row, self.order(rows)

    def pages(self, http, url):
        target = query_url(url.split('?')[0], mode='vertical')
        doc, final = self.page_document(http, target)
        viewer = doc.select_one('viewer-manga-vertical[placeholder]')
        if viewer is None:
            raise SourceAccessError('Alpha Manga не предоставил открытую версию главы.')
        try:
            data = json.loads(viewer['v-bind:pages'])
            if not isinstance(data, list):
                raise ValueError('Invalid page list')
            urls = [image_url(value, final) for value in data if value not in ('first', 'last')]
            layout = keys(viewer['placeholder'])
            if not 1 <= len(urls) <= MAX_PAGES or not all(urls) or len(urls) > len(layout):
                raise ValueError('Incomplete page list')
            return remember([(value, AlphaTileLayout(key)) for value, key in zip(urls, layout)], final)
        except (KeyError, TypeError, ValueError, RecursionError, binascii.Error):
            raise SourceError('Alpha Manga изменил данные открытой главы.') from None


def public_api(host, path, query):
    if host != 'www.alpha-manga.com':
        return False
    if path == '/manga/search.json':
        from urllib.parse import parse_qsl
        fields = parse_qsl(query, keep_blank_values=True)
        params = dict(fields)
        return (len(fields) == 3 and set(params) == {'query', 'genre', 'page'} and len(params['query']) <= 160
                and params['genre'] in ('', *GENRES) and bool(re.fullmatch(ID, params['page'])))
    return not query and bool(re.fullmatch(rf'/manga/{ID}/episodes\.json', path))


SOURCES = (AlphaManga(),)
