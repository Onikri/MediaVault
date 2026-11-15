"""The selected MangaBall chapter's public primary and reserve image addresses."""

import json
import re
import threading
import time
from urllib.parse import urlencode, urlsplit

from source_parser import PublicHttp, SourceError, SourceRateLimitError, public_url


ROOT = 'https://mangaball.com'
API = ROOT + '/api/v1'
ID = re.compile(r'[a-f0-9]{24}')
_cache = {}
_lock = threading.Lock()


def api_only(endpoint):
    def check(url):
        if url != endpoint:
            raise SourceError('Manga Ball перенаправил запрос на другой адрес.')
        return public_url(url, allow_api=True)
    return check


def chapter_data(chapter_id, http=None):
    if not ID.fullmatch(chapter_id):
        raise SourceError('Некорректный ID главы Manga Ball.')
    with _lock:
        hit = _cache.get(chapter_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    endpoint = API + '/chapter-detail?' + urlencode({'chapter_id': chapter_id})
    client = PublicHttp(validate=api_only(endpoint), timeout=getattr(http, 'timeout', (3, 8)),
                        deadline=getattr(http, 'deadline', None))
    try:
        text, _, _ = client.document(endpoint)
        data = json.loads(text).get('data', {}).get('chapter', {})
        if not isinstance(data, dict) or data.get('id') != chapter_id:
            raise SourceError('Manga Ball вернул другую главу.')
    except (ValueError, AttributeError, RecursionError):
        raise SourceError('Manga Ball вернул некорректные данные главы.') from None
    finally:
        client.close()
    with _lock:
        if len(_cache) >= 128:
            _cache.pop(next(iter(_cache)))
        _cache[chapter_id] = time.monotonic() + 180, data
    return data


def page_targets(data):
    pages = data.get('pages')
    if not isinstance(pages, list) or not 1 <= len(pages) <= 500:
        raise SourceError('Manga Ball не предоставил страницы главы.')
    return [public_url(url, resolve_dns=False) for url in pages]


def reserve_image(chapter_id, index, parent, *, expected='', http=None):
    data = chapter_data(chapter_id, http)
    if data.get('title_id') != parent or data.get('status') not in (None, 'published'):
        raise SourceError('Manga Ball вернул другую главу или закрыл доступ.')
    pages = page_targets(data)
    if not 0 <= index < len(pages) or expected and pages[index] != expected:
        raise SourceError('Страница отсутствует в выбранной главе Manga Ball.')
    target = public_url(pages[index])
    endpoint = API + '/image-proxy?' + urlencode({'url': target})
    deadline = getattr(http, 'deadline', None)
    client = PublicHttp(validate=api_only(endpoint), timeout=(3, 15), deadline=deadline)
    response = None
    try:
        response, _ = client._open(endpoint, headers={'Referer': ROOT + '/chapter-detail/' + chapter_id})
        raw = bytearray()
        for block in response.iter_content(65536):
            raw.extend(block)
            if len(raw) > 30 * 1024 * 1024 or deadline and time.monotonic() >= deadline:
                raise SourceError('Страница превышает допустимый размер или срок ожидания.')
        from manga_download import image_extension
        extension = image_extension(raw[:32])
        if not extension:
            raise SourceError('Резервный сервер Manga Ball вернул заглушку вместо страницы.')
        return bytes(raw), 'image/' + ('jpeg' if extension == 'jpg' else extension)
    except SourceRateLimitError:
        raise
    except SourceError:
        raise SourceError('Manga Ball временно не отдаёт страницу через резервный сервер.') from None
    finally:
        if response is not None:
            response.close()
        client.close()


def page(client, saved, source, manga, chapter, index):
    stored = urlsplit(saved.get('realUrl', ''))
    title = re.fullmatch(r'/title-detail/([a-f0-9]{24})', stored.path)
    if stored.scheme != 'https' or stored.hostname != 'mangaball.com' or not title:
        raise SourceError('Manga Ball не подтвердил исходный тайтл.')
    rows = client.get(f'/manga/{manga}/chapters', {'onlineFetch': 'false'}, timeout=6)
    row = next((r for r in rows if r.get('index') == chapter), {})
    identity = str(row.get('url', ''))
    data = chapter_data(identity)
    language = data.get('lang') or data.get('language')
    if (data.get('title_id') != title[1]
            or {'jp': 'ja', 'kr': 'ko'}.get(language, language) != source.get('lang')):
        raise SourceError('Manga Ball вернул другую главу или язык.')
    return reserve_image(identity, index, title[1])
