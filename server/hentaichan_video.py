"""HentaiChan's public video catalogue and its Uppod episode pages."""
import json
import re
import threading
import time
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
import requests
from source_parser import Page, PublicHttp, SourceError, SourceTemporaryError, public_url

ROOT = 'https://hentaichan.live'
HOSTS = ('hentaichan.live', 'x3.h-chan.me', 'xxl.hentaichan.live', 'x17.h-chan.me')
DETAIL = re.compile(r'/video/\d+-[^/]+\.html', re.I)
WATCH = re.compile(r'/video/online/\d+-[^/]+\.html', re.I)
CATALOG = '/video/'
MAX_CATALOG_PAGES = 64
_catalog_rows = ()
_unavailable_until = {}
_cache_lock = threading.Lock()


def video_page(url):
    parts = urlsplit(url)
    return parts.hostname in HOSTS and bool(DETAIL.fullmatch(parts.path) or WATCH.fullmatch(parts.path))


def video_identity(url):
    path = urlsplit(url).path
    if not WATCH.fullmatch(path):
        return path, None
    values = parse_qs(urlsplit(url).query, keep_blank_values=True).get('episode', ['1'])
    if len(values) != 1 or not re.fullmatch(r'[1-9]\d{0,3}', values[0]):
        raise SourceError('Неверный номер эпизода HentaiChan.')
    return path, int(values[0])


def clean(value):
    return ' '.join(value.split())[:500]


def video_media(url):
    parts = urlsplit(url)
    return (parts.hostname in HOSTS and parts.path.startswith('/uploads/files/video/')
            and parts.path.lower().endswith('.mp4'))


def mirrored_request(url, request):
    url = public_url(url, resolve_dns=False)
    parts = urlsplit(url)
    if parts.hostname not in HOSTS:
        raise SourceError('Неизвестный адрес HentaiChan.')
    media = video_media(url)
    now = time.monotonic()
    hosts = [parts.hostname, *(host for host in HOSTS if host != parts.hostname)]
    with _cache_lock:
        hosts.sort(key=lambda host: _unavailable_until.get((host, media), 0) > now)
    for host, timeout in zip(hosts, ((3, 4), (3, 7))):
        try:
            return request(urlunsplit(parts._replace(netloc=host)), timeout)
        except (SourceTemporaryError, requests.RequestException):
            with _cache_lock:
                _unavailable_until[host, media] = time.monotonic() + 120
    raise SourceTemporaryError('HentaiChan временно не ответил. Повтори подключение чуть позже.')


def document(http, url, referer=None):
    headers = {'Referer': referer} if referer else None
    identity = video_identity(url) if video_page(url) else None
    text, final, _ = mirrored_request(url, lambda target, timeout: http.document(target, headers=headers, timeout=timeout))
    if urlsplit(final).hostname not in HOSTS:
        raise SourceError('HentaiChan перенаправил запрос на другой сайт.')
    if identity and video_identity(final) != identity:
        raise SourceError('HentaiChan перенаправил на другой эпизод или тайтл.')
    return text, final


def open_media(http, url, *, headers=None, byte_range=None):
    if not video_media(url):
        raise SourceError('HentaiChan не опубликовал поддерживаемый файл видео.')
    response, final = mirrored_request(url, lambda target, timeout: http._open(
        target, headers=headers, byte_range=byte_range, timeout=timeout))
    if not video_media(final) or urlsplit(final).path != urlsplit(url).path:
        response.close()
        raise SourceError('HentaiChan перенаправил на другой файл видео.')
    mime = response.headers.get('Content-Type', '').partition(';')[0].strip().lower()
    if mime not in {'video/mp4', 'application/octet-stream', 'binary/octet-stream'}:
        response.close()
        raise SourceError('HentaiChan вернул страницу вместо файла MP4.')
    if byte_range and (response.status_code != 206 or not response.headers.get('Content-Range')):
        response.close()
        raise SourceError('Файл HentaiChan не поддерживает перемотку.')
    return response, final


def catalog_cards(text, base):
    soup = BeautifulSoup(text, 'html.parser')
    for card in soup.select('.content_row'):
        anchor = card.select_one('a.title_link[href]')
        if not anchor:
            continue
        try:
            url = public_url(urljoin(base, anchor['href']), resolve_dns=False)
        except SourceError:
            continue
        if not video_page(url) or not DETAIL.fullmatch(urlsplit(url).path):
            continue
        title = clean(anchor.get_text(' ', strip=True))
        if not title:
            continue
        image = card.select_one('.manga_images img, img')
        image_url = (image.get('data-src') or image.get('src')) if image else None
        try:
            cover = public_url(urljoin(base, image_url), resolve_dns=False) if image_url else ''
        except SourceError:
            cover = ''
        year = re.search(r'(?:Год(?: выпуска)?\s*:?\s*)(19\d\d|20\d\d)', card.get_text(' ', strip=True), re.I)
        yield {'provider': 'hentaichan-video', 'providerName': 'HentaiChan · Видео',
               'url': url, 'title': title, 'cover': cover, 'kind': 'anime',
               'adult': True, 'age': 18, 'language': 'ru', 'dubs': [], 'releaseDates': [],
               'year': int(year[1]) if year else None}


def save_catalog(rows, *, complete=False):
    global _catalog_rows
    with _cache_lock:
        previous = () if complete else _catalog_rows
        _catalog_rows = tuple({urlsplit(row['url']).path: row for row in (*previous, *rows)}.values())


def catalog_page(http, url):
    text, base = document(http, url)
    rows = list(catalog_cards(text, base))
    if not rows:
        raise SourceError('HentaiChan не вернул карточки видео.')
    return text, base, rows


def refresh_catalog(stop):
    """Index the source's published pages once, shared by all searches."""
    http = PublicHttp()
    try:
        first, base, rows = catalog_page(http, ROOT + CATALOG)
        save_catalog(rows)
        offsets = sorted({int(match[1]) for anchor in BeautifulSoup(first, 'html.parser').select('a[href]')
                          if (match := re.fullmatch(r'/video/new\?offset=([1-9]\d{0,4})', anchor['href']))})
        complete = len(offsets) < MAX_CATALOG_PAGES
        for offset in offsets[:MAX_CATALOG_PAGES - 1]:
            if stop.wait(1.5):
                return False
            try:
                _, _, page_rows = catalog_page(http, urljoin(base, f'/video/new?offset={offset}'))
            except SourceTemporaryError:
                # Leave all already indexed pages available during an outage.
                return False
            save_catalog(page_rows)
            rows.extend(page_rows)
        save_catalog(rows, complete=complete)
        return True
    except SourceError:
        return False
    finally:
        http.close()


def index_catalog(stop):
    while not stop.is_set():
        if stop.wait(6 * 3600 if refresh_catalog(stop) else 300):
            return


def search(query, http):
    # The site's general search indexes manga. Video lookups use its own catalogue.
    tokens = set(re.findall(r'\w+', query.casefold()))
    if not tokens:
        return []
    with _cache_lock:
        cached = _catalog_rows
    if not cached:
        _, _, cached = catalog_page(http, ROOT + CATALOG)
        save_catalog(cached)
    return [dict(row) for row in cached if tokens <= set(re.findall(r'\w+', row['title'].casefold()))]


def parse_episodes(text, base):
    soup = BeautifulSoup(text, 'html.parser')
    heading = soup.select_one('.title_top_a, h1') or soup.title
    title = clean(heading.get_text(' ', strip=True)) if heading else 'HentaiChan'
    target = urlsplit(base).path.replace('/video/online/', '/video/', 1)
    episodes = {}
    for anchor in soup.select('a[href*="/video/online/"]'):
        url = urljoin(base, anchor['href'])
        parts = urlsplit(url)
        if parts.hostname not in HOSTS or not WATCH.fullmatch(parts.path) or parts.path.replace('/video/online/', '/video/', 1) != target:
            continue
        values = parse_qs(parts.query).get('episode', [])
        if len(values) != 1 or not re.fullmatch(r'[1-9]\d{0,3}', values[0]):
            continue
        number = int(values[0])
        try:
            episode_url = public_url(url, resolve_dns=False)
        except SourceError:
            continue
        episodes[number] = {'number': number, 'season': 1, 'url': episode_url, 'title': f'Серия {number}'}
    return title, sorted(episodes.values(), key=lambda episode: episode['number'])


def inspect(url, http, *, dub_url=None, state=None):
    from player_catalog import choice

    if dub_url and (not video_page(public_url(dub_url, resolve_dns=False)) or video_identity(dub_url) != video_identity(url)):
        raise SourceError('На HentaiChan опубликована только дорожка источника.')
    if state is not None and state.get('_root'):
        text, final = state['_root']
    else:
        text, final = document(http, url)
        if state is not None:
            state['_root'] = (text, final)
    if not video_page(final):
        raise SourceError('HentaiChan не открыл страницу видео.')
    title, episodes = parse_episodes(text, final)
    if WATCH.fullmatch(urlsplit(final).path):
        _, number = video_identity(final)
        episodes = [{'number': number, 'season': 1, 'url': final, 'title': f'Серия {number}'}]
    dubs = [choice('Дорожка источника', final, player='HentaiChan · Uppod', episodes=episodes)] if episodes else []
    return {'provider': 'hentaichan-video', 'providerName': 'HentaiChan · Видео',
            'title': title, 'url': final, 'episodes': episodes, 'dubs': dubs,
            'adult': True, 'age': 18, 'seasons': [], 'releases': [], 'complete': True,
            'available': bool(episodes), 'diagnostics': []}


def resolve(url, http):
    from dynamic_video_sources import check_mp4

    text, final = document(http, url)
    title, episodes = parse_episodes(text, final)
    if DETAIL.fullmatch(urlsplit(final).path):
        if not episodes:
            raise SourceError('На странице HentaiChan нет опубликованных эпизодов.')
        text, final = document(http, episodes[0]['url'], referer=final)
    if not video_page(final) or not WATCH.fullmatch(urlsplit(final).path):
        raise SourceError('HentaiChan не открыл плеер эпизода.')
    soup = BeautifulSoup(text, 'html.parser')
    for node in soup.select('script:not([src])'):
        script = node.string or node.get_text()
        config = re.search(r'\bUppod\s*\(\s*\{([^{}]{1,16000})\}', script, re.I)
        if not config:
            continue
        file = re.search(r'(?:\{|,)\s*["\']?file["\']?\s*:\s*("(?:[^"\\]|\\.)*")', '{'+config[1])
        if not file:
            continue
        try:
            media = public_url(urljoin(final, json.loads(file[1])), resolve_dns=False)
        except (ValueError, SourceError):
            continue
        if not video_media(media):
            continue
        stream = {'url': media, 'type': 'mp4', 'quality': None, 'headers': {'Referer': final}}
        stream['url'] = check_mp4(http, stream, open_stream=lambda target, **kwargs: open_media(http, target, **kwargs))
        return Page(title=title, streams=[stream], episodes=episodes)
    raise SourceError('Плеер HentaiChan не опубликовал доступный MP4.')

