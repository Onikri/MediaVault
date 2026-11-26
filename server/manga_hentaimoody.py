"""HentaiMoody (online.hentaimoody.com) public reader.

A title page is one DLE news entry. Its inline ``FOCUS_FLOW_TITLE`` names the
work's chapter manifest on json.imghmd.link: every chapter is its own news
entry read at ``/<news id>/mangaonline``, and the work's container entry stands
for a single-chapter work. A reader page names its image manifest
(``READER_IMAGE_MANIFEST``), a JSON list of page images on img.hreadme.org.
Only these public documents are read; no JavaScript, login or session state.
"""
import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from manga_source_tags import unique
from source_parser import SourceAuthError, SourceError, public_url

HOST = 'online.hentaimoody.com'
ROOT = 'https://' + HOST
PROVIDER = HOST
NAME = 'HentaiMoody'
ID = r'[1-9]\d{0,11}'
TITLE = re.compile(rf'/({ID})-[^/?#]{{1,1024}}\.html')
READER = re.compile(rf'/({ID})/mangaonline/?')
MANIFEST_HOST = 'json.imghmd.link'
CHAPTERS = re.compile(r'/json-fullstory/[A-Za-z0-9_./-]{1,300}\.json')
IMAGES = re.compile(r'/images/[A-Za-z0-9_./-]{1,300}/images\.json')
IMAGE_HOSTS = ('hreadme.org', 'imghmd.link')
# The site reader prefixes relative manifest entries with its image CDN.
CDN = 'https://2img.imghmd.link'
IMAGE = re.compile(r'/[A-Za-z0-9_./%-]{1,600}\.(?:jpe?g|png|webp|gif|avif)', re.I)
MAX_PAGES = 1500


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:500]


def reader_url(news):
    return f'{ROOT}/{news}/mangaonline'


def own_url(value, base=ROOT):
    url = public_url(urljoin(base, value or ''), resolve_dns=False)
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname != HOST or parts.username or parts.password:
        raise SourceError('HentaiMoody вернул ссылку вне своей читалки.')
    path = parts.path
    if TITLE.fullmatch(path) or READER.fullmatch(path):
        return ROOT + path
    raise SourceError('HentaiMoody вернул ссылку вне своей читалки.')


def manifest_url(value, pattern):
    url = public_url(value, resolve_dns=False)
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname != MANIFEST_HOST or not pattern.fullmatch(parts.path):
        raise SourceError('HentaiMoody указал список глав или страниц на постороннем сервере.')
    return url


def image_url(value):
    if not isinstance(value, str):
        return ''
    if value.startswith('/') and not value.startswith('//'):
        value = CDN + value
    try:
        url = public_url(value, resolve_dns=False)
    except SourceError:
        return ''
    parts = urlsplit(url)
    host = parts.hostname or ''
    if (parts.scheme != 'https' or parts.username or parts.password
            or not any(host == d or host.endswith('.' + d) for d in IMAGE_HOSTS) or not IMAGE.fullmatch(parts.path)):
        return ''
    return url


def js_string(text, pattern):
    match = re.search(pattern + r'\s*[:=]\s*"((?:[^"\\]|\\.){1,2000})"', text)
    if not match:
        return ''
    try:
        return json.loads('"' + match[1] + '"')
    except ValueError:
        return ''


def document(http, url, referer=None):
    text, final, _ = http.document(url, headers={'Referer': referer} if referer else None)
    if urlsplit(final).hostname != HOST:
        raise SourceError('HentaiMoody перенаправил запрос на другой сайт.')
    return text, final


def manifest(http, url, referer):
    raw, final, _ = http.document(url, headers={'Referer': referer})
    if urlsplit(final).hostname != MANIFEST_HOST:
        raise SourceError('HentaiMoody перенаправил список на другой сервер.')
    try:
        return json.loads(raw)
    except ValueError:
        raise SourceError('HentaiMoody вернул повреждённый список.') from None


def number(value):
    return float(value) if type(value) in (int, float) and 0 <= value < 100000 else None


def is_container(entry, count):
    # The work's own entry (category 4, no chapter link) stands next to its chapters.
    return count > 1 and not str(entry.get('chapter_value_link') or '').strip() and not number(entry.get('chapter'))


def chapters(data):
    """Chapter rows of a chapter manifest {news id: [entry]}; a lone container is a one-shot."""
    if not isinstance(data, dict):
        raise SourceError('HentaiMoody изменил формат списка глав.')
    entries = []
    for news, items in data.items():
        if not re.fullmatch(ID, str(news)) or not isinstance(items, list) or not items or not isinstance(items[0], dict):
            continue
        entries.append((str(news), items[0]))
    rows, container = [], ''
    for news, entry in entries:
        if is_container(entry, len(entries)):
            container = clean(entry.get('title'))
            continue
        volume = number(entry.get('volume'))
        n = number(entry.get('chapter'))
        title = clean(entry.get('title')) or f'Глава {n or 1:g}'
        rows.append({'number': n if n else 1.0, 'season': int(volume) if volume and volume >= 1 else 1,
                     'url': reader_url(news), 'title': title, 'translator': clean(entry.get('translation')),
                     'language': 'ru', 'publishedAt': str(entry.get('date') or '')[:10]})
    rows = sorted({r['url']: r for r in rows}.values(), key=lambda r: (r['season'], r['number'], r['url']))
    return rows, container


def result(title, url, episodes, pages, *, aliases=(), cover='', genres=()):
    return {'provider': PROVIDER, 'providerName': NAME, 'title': title, 'url': url, 'kind': 'manga',
            'language': 'ru', 'adult': True, 'age': 18, 'cover': cover,
            'aliases': unique([title, *aliases]), 'genres': list(genres), 'tags': [],
            'episodes': episodes, 'pages': pages, 'available': bool(episodes),
            'seasons': [{'number': n, 'name': 'Том ' + str(n)} for n in sorted({e['season'] for e in episodes})],
            'translations': sorted({e['translator'] for e in episodes if e.get('translator')}),
            'dubs': [], 'releases': [], 'truncated': False}


def login_wall(soup):
    text = soup.get_text(' ', strip=True)
    return bool(re.search(r'(?:только|необходимо|нужно)\s+(?:для\s+)?(?:зарегистрирован|авториз|войти)', text, re.I))


def inspect_title(url, http):
    text, final = document(http, url)
    soup = BeautifulSoup(text, 'html.parser')
    heading = soup.select_one('.title-hero__body h1, h1')
    if not heading:
        raise SourceError('HentaiMoody не предоставил карточку тайтла.')
    title = clean(heading.get_text(' ', strip=True))
    news = TITLE.fullmatch(urlsplit(final).path)[1]
    chapter_list = js_string(text, r'chapterManifest')
    if chapter_list:
        rows, container = chapters(manifest(http, manifest_url(chapter_list, CHAPTERS), final))
    else:
        rows, container = [], ''
    if not rows:
        # A work without a published manifest is read on its own reader page.
        reader = js_string(text, r'readerUrl') or (soup.select_one('a.title-primary-action[href]') or {}).get('href')
        target = own_url(reader, final) if reader else reader_url(news)
        if not READER.fullmatch(urlsplit(target).path):
            raise SourceError('HentaiMoody не указал читалку тайтла.')
        rows = [{'number': 1.0, 'season': 1, 'url': target, 'title': title, 'translator': '', 'language': 'ru',
                 'publishedAt': ''}]
    original = soup.select_one('.title-hero__original')
    genres = soup.select('.title-hero__genres a[href]')
    cover = soup.select_one('img.title-hero__cover[src]')
    return result(title, final, rows, [], aliases=[original.get_text(' ', strip=True) if original else '', container],
                  cover=image_cover(cover['src'] if cover else ''),
                  genres=unique(a.get_text(' ', strip=True) for a in genres))


def image_cover(value):
    try:
        url = public_url(value, resolve_dns=False) if value else ''
    except SourceError:
        return ''
    return url if urlsplit(url).hostname and urlsplit(url).hostname.endswith('.imghmd.link') else ''


def inspect_reader(url, http):
    news = READER.fullmatch(urlsplit(url).path)[1]
    target = reader_url(news)
    text, final = document(http, target)
    if READER.fullmatch(urlsplit(final).path) is None or READER.fullmatch(urlsplit(final).path)[1] != news:
        raise SourceError('HentaiMoody открыл другую главу.')
    images = js_string(text, r'window\.READER_IMAGE_MANIFEST')
    soup = BeautifulSoup(text, 'html.parser')
    if not images:
        if login_wall(soup):
            raise SourceAuthError('HentaiMoody показывает эту главу только вошедшим читателям.')
        raise SourceError('HentaiMoody не указал страницы главы.')
    try:
        data = manifest(http, manifest_url(images, IMAGES), target)
    except SourceError as error:
        # The site reader shows «Глава ещё не загружена на сервер» for this answer.
        if getattr(error, 'http_status', None) in {404, 410}:
            raise SourceError('HentaiMoody ещё не выложил страницы этой главы.') from None
        raise
    if not isinstance(data, list):
        raise SourceError('HentaiMoody изменил формат списка страниц.')
    pages = []
    for entry in data[:MAX_PAGES]:
        page = image_url(entry.get('url') or entry.get('src') if isinstance(entry, dict) else entry)
        if not page:
            raise SourceError('HentaiMoody указал страницу на постороннем сервере.')
        pages.append(page)
    if not pages:
        raise SourceError('HentaiMoody не предоставил страницы главы.')
    title = clean(js_string(text, r'window\.READER_TITLE')) or 'Глава 1'
    main = js_string(text, r'window\.READER_MAIN_LINK')
    try:
        card = own_url(main) if main else ''
    except SourceError:
        card = ''
    chapter = {'number': 1.0, 'season': 1, 'url': target, 'title': title, 'translator': '', 'language': 'ru',
               'publishedAt': ''}
    value = result(title, target, [chapter], pages)
    if card:
        value['titleUrl'] = card
    return value


def inspect(url, http):
    target = own_url(url)
    if READER.fullmatch(urlsplit(target).path):
        return inspect_reader(target, http)
    return inspect_title(target, http)
