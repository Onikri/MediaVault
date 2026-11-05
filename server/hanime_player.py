"""Run the reviewed HanimeTV extractor with a bounded, public-only transport."""
from functools import lru_cache
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
import os
from pathlib import Path
import sys
import time
from types import ModuleType
from urllib.parse import urlsplit

import requests
from source_parser import PublicHttp, SourceError, playback_headers, public_url


PLUGIN_REVISION = '3ba2a2ff5c0e28ccd9b6c25fe31bc0698ed211cc'
PLUGIN_FILES = {
    'htv': '4e8794a20095b50b99b013e5ec8a460e86fa020c9c04eefe3e1baed8935ab632',
    'utils': 'efe938d751af4cccaa1e13f6875f66a25d10d6c642691c3a257d85bfd0c61c6f',
}
HANDSHAKE = 'https://auth.hanime.tv/api/v11/handshake'


class QuietLogger:
    def debug(self, _message):
        pass

    warning = error = debug


@lru_cache(maxsize=1)
def extractor_class():
    root = Path(os.environ.get('DATA_DIR') or Path(__file__).resolve().parents[1])
    directory = root / '.codex-local' / 'hanime-plugin'
    files = {name: directory / (name + '.py') for name in PLUGIN_FILES}
    for name, path in files.items():
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != PLUGIN_FILES[name]:
            raise SourceError('Модуль HanimeTV не установлен или не прошёл проверку.')
    package = 'mediavault_hanime_plugin'
    for namespace in (package, package + '.extractor'):
        module = ModuleType(namespace)
        module.__path__ = []
        sys.modules[namespace] = module
    for name in ('utils', 'htv'):
        qualified = package + ('.extractor.' if name == 'htv' else '.') + name
        spec = spec_from_file_location(qualified, files[name])
        module = module_from_spec(spec)
        sys.modules[qualified] = module
        spec.loader.exec_module(module)
    return module.HanimeTVIE


def extract(url):
    from yt_dlp import YoutubeDL
    from yt_dlp.networking import Response
    from yt_dlp.utils import DownloadError, ExtractorError

    url = public_url(url, resolve_dns=False)
    upstream = extractor_class()
    if not upstream.suitable(url):
        raise SourceError('Нужна ссылка на конкретный выпуск HanimeTV.')

    deadline = time.monotonic() + 12
    http = PublicHttp(timeout=(3, 5), deadline=deadline)

    class GuardedDownloader(YoutubeDL):
        def urlopen(self, request):
            if time.monotonic() >= deadline:
                raise SourceError('HanimeTV не уложился во время проверки.')
            address = request if isinstance(request, str) else request.url
            headers = {} if isinstance(request, str) else request.headers
            method = 'GET' if isinstance(request, str) else request.method
            if address == HANDSHAKE and method == 'POST':
                public_url(address, allow_api=True)
                data = request.data
                if not isinstance(data, bytes) or len(data) > 8192:
                    raise SourceError('Некорректный запрос плеера HanimeTV.')
                remaining = max(.2, deadline - time.monotonic())
                response = http.session.post(address, headers=headers, data=data, timeout=(min(3, remaining), min(5, remaining)),
                                             allow_redirects=False, stream=True)
                with response:
                    if response.status_code != 200 or not response.headers.get('X-Token'):
                        raise SourceError('HanimeTV не предоставил ответ публичного плеера.')
                    return Response(BytesIO(), address, headers={'X-Token': response.headers['X-Token']}, status=200)
            if method != 'GET' or (address != url and not urlsplit(address).path.lower().endswith('.m3u8')):
                raise SourceError('Модуль HanimeTV запросил неподдерживаемый адрес.')
            text, final, response_headers = http.document(address, headers=headers)
            return Response(BytesIO(text.encode()), final,
                            headers={'Content-Type': response_headers.get('Content-Type', 'text/plain')}, status=200)

    try:
        with GuardedDownloader({'format': 'best', 'quiet': True, 'no_warnings': True,
                                'skip_download': True, 'cachedir': False, 'noplaylist': True, 'logger': QuietLogger()},
                               auto_init=False) as downloader:
            downloader.add_info_extractor(upstream())
            result = downloader.extract_info(url, download=False, ie_key=upstream.ie_key())
        media = public_url(result['url'])
        suffix = urlsplit(media).path.lower()
        protocol = result.get('protocol', '')
        if protocol in {'m3u8', 'm3u8_native'} or suffix.endswith('.m3u8'):
            kind = 'hls'
        elif suffix.endswith('.mp4'):
            kind = 'mp4'
        else:
            raise SourceError('HanimeTV не выдал MP4 или HLS.')
        headers = playback_headers({'Referer': url, **result.get('http_headers', {})})
        return [{'url': media, 'type': kind, 'quality': result.get('height'), 'headers': headers}]
    except (DownloadError, ExtractorError, requests.RequestException, KeyError, ValueError, TypeError):
        raise SourceError('Модуль HanimeTV не смог получить публичный поток.') from None
    finally:
        http.close()
