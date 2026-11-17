"""Pawchive (keiyoushi ``src/all/pawchive`` at 6f345a8).

A Kemono-family archive of Patreon and Pixiv Fanbox posts with the same
``/api/v1`` creator, profile and post routes as ``manga_creator_feeds``.
Originals live on ``file.pawchive.pw`` and answer only image-shaped
requests; a post marked preview-only has no original there, so the reader
falls back to the ``img.pawchive.pw`` thumbnail exactly like the extension's
default "low resolution fallback" setting.
"""

from dataclasses import dataclass
import json
import re
from urllib.parse import urlsplit

import requests

import manga_creator_feeds
from manga_creator_feeds import CreatorFeed
from manga_japanese_readers import JapanesePage, packed_refs
from manga_ninth_routes import Route, register
from source_parser import SourceAccessError, SourceError, SourceTemporaryError

HOST = 'pawchive.pw'
THUMBNAILS = 'https://img.pawchive.pw/thumbnail/data'
MAX_DIRECTORY = 48 * 1024 * 1024
# Pawchive shards files under a two- or three-character first directory.
FILE_HOST = re.compile(r'(?:file|n[0-9]{1,2})\.pawchive\.pw')
PICTURE = re.compile(r'/[a-f0-9]{2,3}/[a-f0-9]{2}/[a-f0-9]{64}\.(?:png|jpg|gif|jpeg|webp)', re.I)
IMAGE_HEADERS = {'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                 'Sec-Fetch-Dest': 'image', 'Sec-Fetch-Mode': 'no-cors', 'Sec-Fetch-Site': 'same-site'}

manga_creator_feeds.SERVICES[HOST] = ('patreon', 'fanbox')


def image_route(url, method, data, headers):
    if method != 'GET' or data is not None or url.query:
        return None
    if FILE_HOST.fullmatch(url.netloc) and url.path.startswith('/data/') and PICTURE.fullmatch(url.path[5:]):
        return Route(headers=IMAGE_HEADERS, redirect=False)
    if (url.netloc == 'img.pawchive.pw' and url.path.startswith('/thumbnail/data/')
            and PICTURE.fullmatch(url.path[15:])):
        return Route(headers=IMAGE_HEADERS, redirect=False)
    return None


register('pawchive-image', image_route)


@dataclass(frozen=True)
class PawchivePage(JapanesePage):
    def fetch(self, http, referer):
        from manga_page_media import read_image

        target = urlsplit(self.url)
        path = target.path.removeprefix('/data')
        try:
            response, _ = http._open(f'https://{target.netloc}/data{path}', headers={'Referer': f'https://{HOST}/'}, action='n9:pawchive-image')
        except SourceError as error:
            # A preview-only post has no original on the file host.
            if not (type(error) is SourceAccessError or type(error) is SourceError and 'HTTP 404' in str(error)):
                raise
            response, _ = http._open(THUMBNAILS + path, headers={'Referer': f'https://{HOST}/'},
                                     action='n9:pawchive-image')
        return read_image(http, response)


class Pawchive(CreatorFeed):
    def data(self, http, route):
        if route != '/creators':
            data = super().data(http, route)
            # Unlike Kemono, a post route answers with the bare post.
            if self.is_chapter(self.ROOT + route) and isinstance(data, dict) and 'post' not in data:
                return {'post': data}
            return data
        # The creator directory (about 100 000 rows, 16 MB) is larger than an
        # ordinary page, so it is streamed with its own bound.
        endpoint = self.ROOT + '/api/v1/creators'
        self.origin.wait(getattr(http, 'deadline', None))
        response, final = http._open(endpoint, headers={'Referer': self.ROOT + '/'}, action='creator-feed-json')
        try:
            if final != endpoint:
                raise SourceError('Источник перенаправил запрос на другой маршрут.')
            raw = bytearray()
            for block in response.iter_content(262144):
                raw.extend(block)
                if len(raw) > MAX_DIRECTORY:
                    raise SourceError('Каталог авторов Pawchive слишком велик.')
        except requests.RequestException:
            raise SourceTemporaryError('Соединение с источником оборвалось во время чтения ответа.') from None
        finally:
            response.close()
        try:
            return json.loads(bytes(raw))
        except ValueError:
            raise SourceError('Источник изменил формат каталога авторов.') from None

    def files(self, post):
        # The archive keeps originals on its file host, not under the site root.
        attachments = post.get('attachments')
        found = {}
        for item in (post.get('file'), *(attachments if isinstance(attachments, list) else ())):
            path = item.get('path') if isinstance(item, dict) else None
            if isinstance(path, str) and PICTURE.fullmatch(path):
                # The file host redirects to the shard named in "server".
                server = urlsplit(str(item.get('server') or ''))
                host = server.netloc if server.scheme == 'https' and FILE_HOST.fullmatch(server.netloc) else 'file.pawchive.pw'
                found.setdefault(path, f'https://{host}/data{path}')
        return list(found.values())

    def post(self, http, url):
        row, chapter, pages = super().post(http, url)
        row['cover'] = THUMBNAILS + urlsplit(pages[0]).path.removeprefix('/data')
        return row, chapter, packed_refs([PawchivePage(page) for page in pages], url)


SOURCES = (Pawchive(('4284527942812494681', 'Pawchive', 'all', 'https://pawchive.pw', True)),)
