"""HentaiChan's public video catalogue and its Uppod episode pages."""
import json
import re
import threading
import time
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup
from source_parser import Page, SourceError, public_url

ROOT = 'https://hentaichan.live'
HOSTS = ('hentaichan.live', 'x17.h-chan.me')
DETAIL = re.compile(r'/video/\d+-[^/]+\.html', re.I)
WATCH = re.compile(r'/video/online/\d+-[^/]+\.html', re.I)
CATALOG = '/video'
_cache = (0, ())
_cache_lock = threading.Lock()


def video_page(url):
    parts = urlsplit(url)
    return parts.hostname in HOSTS and bool(DETAIL.fullmatch(parts.path) or WATCH.fullmatch(parts.path))


def clean(value):
    return ' '.join(value.split())[:500]


def document(http, url, referer=None):
    kwargs = {'headers': {'Referer': referer}} if referer else {}
    text, final, _ = http.document(url, **kwargs)
    if urlsplit(final).hostname not in HOSTS:
        raise SourceError('HentaiChan перенаправил запрос на другой сайт.')
    return text, final


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


def search(query, http):
    # The public site search can return manga without any video matches.
    # Search a small cached window of the video catalogue itself.
    global _cache
    tokens = set(re.findall(r'\w+', query.casefold()))
    if not tokens:
        return []
    with _cache_lock:
        expires, cached = _cache
    if expires <= time.monotonic():
        try:
            first, base = document(http, ROOT + CATALOG)
        except SourceError:
            first, base = document(http, 'https://x17.h-chan.me' + CATALOG)
        rows = list(catalog_cards(first, base))
        if not rows:
            raise SourceError('HentaiChan не вернул карточки видео.')
        # Follow only the exact pagination pattern published on the catalogue.
        soup = BeautifulSoup(first, 'html.parser')
        offsets = sorted({int(m[1]) for a in soup.select('a[href]')
                          if (m := re.fullmatch(r'/video/new\?offset=([1-9]\d{0,4})', a['href']))})[:2]
        for offset in offsets:
            try:
                text, final = document(http, urljoin(base, f'/video/new?offset={offset}'))
                rows.extend(catalog_cards(text, final))
            except SourceError:
                break
        cached = tuple({row['url']: row for row in rows}.values())
        with _cache_lock:
            _cache = (time.monotonic() + 300, cached)
    return [dict(row) for row in cached if tokens <= set(re.findall(r'\w+', row['title'].casefold()))]


def parse_episodes(text, base):
    soup = BeautifulSoup(text, 'html.parser')
    heading = soup.select_one('.title_top_a, h1') or soup.title
    title = clean(heading.get_text(' ', strip=True)) if heading else 'HentaiChan'
    root = urlsplit(base)
    target = root.path.replace('/video/online/', '/video/', 1)
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
        episodes[number] = {'number': number, 'season': 1, 'url': public_url(url, resolve_dns=False), 'title': f'Серия {number}'}
    return title, sorted(episodes.values(), key=lambda episode: episode['number'])


def inspect(url, http, *, dub_url=None, state=None):
    from player_catalog import choice

    if dub_url and dub_url != url:
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
        values = parse_qs(urlsplit(final).query).get('episode', ['1'])
        if len(values) != 1 or not re.fullmatch(r'[1-9]\d{0,3}', values[0]):
            raise SourceError('Неверный номер эпизода HentaiChan.')
        number = int(values[0])
        episodes = [{'number': number, 'season': 1, 'url': final, 'title': f'Серия {number}'}]
    dubs = [choice('Дорожка источника', url, player='HentaiChan · Uppod', episodes=episodes)] if episodes else []
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
        parts = urlsplit(media)
        if parts.hostname not in HOSTS or not parts.path.startswith('/uploads/files/video/') or not parts.path.lower().endswith('.mp4'):
            continue
        stream = {'url': media, 'type': 'mp4', 'quality': None, 'headers': {'Referer': final}}
        check_mp4(http, stream)
        return Page(title=title, streams=[stream], episodes=episodes)
    raise SourceError('Плеер HentaiChan не опубликовал доступный MP4.')

