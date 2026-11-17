"""Read published ZIP/CBZ pages using bounded HTTP ranges, without extracting to disk."""

from collections import OrderedDict
from io import RawIOBase
import re
import secrets
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit, urlunsplit
import zipfile

from requests import RequestException

from source_parser import SourceAccessError, SourceError


MARKER = 'mv_public_zip='
CONTENT_RANGE = re.compile(r'bytes (\d+)-(\d+)/(\d+)')
IMAGE = re.compile(r'\.(?:png|jpe?g|webp|avif|gif|bmp)$', re.I)
ARCHIVE_LIMIT = 1024 * 1024 * 1024
PAGE_LIMIT = 30 * 1024 * 1024
DIRECTORY_LIMIT = 2 * 1024 * 1024
GRANT_LIMIT = 48
GRANTS = OrderedDict()
GRANT_LOCK = Lock()


def range_bytes(http, url, start, end, total=None, referer=None):
    headers = {'Referer': referer} if referer else {}
    response, final = http._open(url, headers=headers, byte_range=f'bytes={start}-{end}')
    try:
        range_match = CONTENT_RANGE.fullmatch(response.headers.get('Content-Range') or '')
        if response.status_code != 206 or not range_match or final != url:
            raise SourceError('Источник не поддерживает чтение частей ZIP.')
        actual_start, actual_end, actual_total = map(int, range_match.groups())
        if (actual_start, actual_end) != (start, end) or not 22 <= actual_total <= ARCHIVE_LIMIT or (
                total is not None and actual_total != total):
            raise SourceError('Источник вернул неожиданный диапазон ZIP.')
        raw = bytearray()
        for chunk in response.iter_content(65536):
            raw.extend(chunk)
            if len(raw) > end - start + 1 or http.deadline and monotonic() >= http.deadline:
                raise SourceError('Источник превысил предел загрузки части ZIP.')
        if len(raw) != end - start + 1:
            raise SourceError('Источник вернул неполную часть ZIP.')
        return bytes(raw), actual_total
    except RequestException:
        raise SourceError('Источник прервал загрузку части ZIP.') from None
    finally:
        response.close()


class RemoteZip(RawIOBase):
    def __init__(self, http, url, referer, directory=None):
        super().__init__()
        self.http, self.url, self.referer = http, url, referer
        if directory is None:
            _, total = range_bytes(http, url, 0, 0, referer=referer)
            self.directory_start = max(0, total - DIRECTORY_LIMIT)
            self.directory_data, self.total = range_bytes(http, url, self.directory_start, total - 1, total, referer)
        else:
            self.directory_start, self.directory_data, self.total = directory
        self.offset = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.offset

    def seek(self, offset, whence=0):
        if whence not in (0, 1, 2):
            raise ValueError('Invalid seek')
        target = (0, self.offset, self.total)[whence] + offset
        if not 0 <= target <= self.total:
            raise OSError('ZIP offset out of bounds')
        self.offset = target
        return target

    def read(self, size=-1):
        start = self.offset
        end = self.total if size < 0 else min(self.total, start + size)
        if start == end:
            return b''
        if end - start > PAGE_LIMIT:
            raise OSError('Public ZIP read too large')
        if start >= self.directory_start:
            result = self.directory_data[start - self.directory_start:end - self.directory_start]
        else:
            result, _ = range_bytes(self.http, self.url, start, end - 1, self.total, self.referer)
        self.offset = end
        return result

    def directory(self):
        return self.directory_start, self.directory_data, self.total


def download_refs(http, url, referer, *, order=None):
    try:
        with RemoteZip(http, url, referer) as stream, zipfile.ZipFile(stream) as archive:
            files = [item for item in archive.infolist() if not item.is_dir() and IMAGE.search(item.filename)
                     and not item.filename.startswith('__MACOSX/')]
            if order is None:
                files.sort(key=lambda info: info.filename.casefold())
            else:
                by_name = {item.filename: item for item in files}
                if len(by_name) != len(files) or any(name not in by_name for name in order):
                    raise SourceError('ZIP не содержит страницы, перечисленные в читалке.')
                files = [by_name[name] for name in order]
            if not 1 <= len(files) <= 1500 or len(files) != len({item.filename for item in files}) or any(
                    item.flag_bits & 1 or max(item.file_size, item.compress_size) > PAGE_LIMIT for item in files):
                raise SourceError('ZIP содержит недоступные страницы или превышает лимит.')
            cache = stream.directory()
    except SourceError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        raise SourceError('Источник вернул повреждённый ZIP.') from None
    token = secrets.token_urlsafe(15)
    with GRANT_LOCK:
        GRANTS[token] = (monotonic() + 900, url, referer, cache, tuple(item.filename for item in files))
        while len(GRANTS) > GRANT_LIMIT:
            GRANTS.popitem(last=False)
    return [f'{url}#{MARKER}{token}.{index}' for index in range(len(files))]


def grant(value):
    parts = urlsplit(value)
    match = re.fullmatch(re.escape(MARKER) + r'([A-Za-z0-9_-]{20})\.(\d{1,4})', parts.fragment)
    with GRANT_LOCK:
        record = GRANTS.get(match[1]) if match else None
    if not record or record[0] < monotonic() or record[1] != urlunsplit(parts._replace(fragment='')):
        raise SourceAccessError('Список страниц ZIP устарел. Открой главу заново.')
    _, url, referer, directory, files = record
    index = int(match[2])
    if index >= len(files):
        raise SourceError('Некорректный номер страницы в ZIP.')
    return url, referer, directory, files[index]


def read_member(http, value):
    url, referer, directory, name = grant(value)
    try:
        with RemoteZip(http, url, referer, directory) as stream, zipfile.ZipFile(stream) as archive:
            info = archive.getinfo(name)
            if info.flag_bits & 1 or max(info.file_size, info.compress_size) > PAGE_LIMIT:
                raise SourceError('Страница ZIP превышает лимит или зашифрована.')
            return archive.read(info)
    except SourceError:
        raise
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile):
        raise SourceError('Источник вернул повреждённую страницу ZIP.') from None
