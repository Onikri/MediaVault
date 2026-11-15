"""Manga-shi's public HTML catalogue and reader.

Protocol reference: Apache-2.0 Keiyoushi extension src/ru/mangashi, v1.6.53.
"""

import re
import threading
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from manga_source_tags import unique
from source_parser import SourceError, public_url


ROOT = 'https://manga-shi.org'
SOURCE_ID = '735260312965788798'
NAME = 'Manga-shi'
LANGUAGE = 'ru'
IS_NSFW = True  # The extension declares a mixed catalogue.
TITLE_PATH = re.compile(r'/manga/([\w-]{1,180})/?')
CHAPTER_PATH = re.compile(r'/manga/([\w-]{1,180})/glava[-_](\d{1,4}(?:[,.]\d{1,3})?)(?:[-_][\w.-]*)?/?')
PACE = threading.Lock()
NEXT_REQUEST = 0.0


def site_link(value, base=ROOT):
    if not value:
        return ''
    candidate = urljoin(base, value)
    parsed = urlsplit(candidate)
    if parsed.scheme != 'https' or parsed.netloc != 'manga-shi.org':
        return ''
    return public_url(candidate, resolve_dns=False)


def saved_chapter_url(value, title, root):
    return site_link(value, root)


def document(http, url):
    global NEXT_REQUEST
    with PACE:
        now = time.monotonic()
        scheduled = max(now, NEXT_REQUEST)
        deadline = getattr(http, 'deadline', None)
        if deadline is not None and scheduled >= deadline:
            raise SourceError('Manga-shi: достигнут лимит времени запроса.')
        NEXT_REQUEST = scheduled + 0.5
    if scheduled > now:
        time.sleep(scheduled - now)
    raw, final, _ = http.document(url, headers={'Referer': ROOT + '/'})
    if not site_link(final) or urlsplit(final).path.rstrip('/') != urlsplit(url).path.rstrip('/'):
        raise SourceError('Manga-shi перенаправил запрос на другую страницу.')
    soup = BeautifulSoup(raw, 'html.parser')
    from manga_sources import guard
    guard(soup)
    return soup, final


def text_of(node):
    return node.get_text(' ', strip=True) if node else ''


def link_to_image(value, base):
    try:
        return public_url(urljoin(base, value), resolve_dns=False) if value else ''
    except SourceError:
        return ''


def row(title, url, cover=''):
    from manga_sources import title_aliases
    return {
        'id': f'suwayomi:{SOURCE_ID}:native:{TITLE_PATH.fullmatch(urlsplit(url).path)[1]}',
        'provider': 'suwayomi:' + SOURCE_ID, 'providerName': NAME,
        'sourceId': SOURCE_ID, 'sourceUrl': url, 'sourceURL': url, 'url': url,
        'kind': 'manga', 'language': 'ru', 'title': title,
        'aliases': title_aliases(title), 'cover': cover, 'sourceOnly': True, 'ids': {},
    }


def catalogue(http, page=1, *, query='', sort='popular', tag='', exclude_tag=''):
    params = [('sort', sort), ('status', ''), ('type', ''), ('age_rating', ''), ('year', ''),
              ('chapters_min', ''), ('chapters_max', ''), ('q', query), ('page', page)]
    if tag:
        params.append(('tag', tag))
    if exclude_tag:
        params.append(('exclude_tag', exclude_tag))
    soup, final = document(http, ROOT + '/catalog/?' + urlencode(params))
    grid = soup.select_one('#manga-grid')
    if grid is None:
        raise SourceError('Manga-shi изменил разметку каталога.')
    found = {}
    for anchor in grid.select(':scope > a[href]'):
        url = site_link(anchor['href'], final)
        title = text_of(anchor.select_one('h3,h4,.title')) or text_of(anchor)
        if not url or not TITLE_PATH.fullmatch(urlsplit(url).path) or not title:
            continue
        image = anchor.select_one('img')
        cover = link_to_image(image.get('data-src') or image.get('src'), final) if image else ''
        found[url] = row(title[:500], url, cover)
    return list(found.values()), len(found) >= 20


def vocabulary(http):
    soup, _ = document(http, ROOT + '/catalog/')
    filters = {}
    for group in soup.select('.genre-flyout .group'):
        field = group.select_one('input[name=tag][value]')
        label = text_of(group.select_one('span')).lstrip('#')
        if field and label and re.fullmatch(r'[\w-]{1,80}', field['value']):
            # The catalogue combines genres and tags; title pages distinguish them.
            filters[field['value']] = {'label': label, 'category': 'tag', 'sourceId': field['value']}
    return list(filters.values())


def metadata(soup, url):
    title = text_of(soup.select_one('h1'))
    if not title:
        raise SourceError('Manga-shi не вернул название произведения.')
    cover = soup.select_one('meta[property="og:image"]')
    result = row(title[:500], url, link_to_image(cover.get('content'), url) if cover else '')
    badges = [text_of(x).casefold() for x in soup.select('span.tracking-widest')]
    formats = {'манга': 'manga', 'манхва': 'manhwa', 'маньхуа': 'manhua', 'западный комикс': 'comic'}
    result['format'] = next((formats[b] for b in badges if b in formats), '')
    if result['format'] == 'manhwa':
        result['readingMode'] = 'scroll'
    result['genres'] = unique(text_of(x).lstrip('#') for x in soup.select('a[href*="manga-genre"]'))
    result['tags'] = unique(text_of(x).lstrip('#') for x in soup.select('a[href*="?tag="]'))
    result['description'] = text_of(soup.select_one('div.leading-relaxed[x-ref*="descDesktop"]'))[:12000]
    result['author'] = text_of(soup.select_one('a[href*="?author="]'))
    return result


def chapter(url, label):
    match = CHAPTER_PATH.fullmatch(urlsplit(url).path)
    number = float(match[2].replace(',', '.'))
    volume = re.search(r'(?:Том|Vol\.?|Volume)\s*(\d+)', label, re.I)
    return {'number': int(number) if number.is_integer() else number,
            'season': int(volume[1]) if volume else 1, 'url': url,
            'title': label or f'Глава {number:g}', 'language': 'ru', 'translator': ''}


def chapters(http, soup, final, slug):
    found = {}
    seen = set()
    next_url = ''
    while True:
        selector = 'a[href*="/glava"]' if seen else '#chapters-list > a[href*="/glava"]'
        for anchor in soup.select(selector):
            url = site_link(anchor['href'], final)
            match = CHAPTER_PATH.fullmatch(urlsplit(url).path)
            label = text_of(anchor.select_one('.chapter-title'))
            if match and match[1] == slug and label and len(found) < 1500:
                found[url] = chapter(url, label)
        if seen:
            next_link = next((item for item in soup.select('nav.flex a[href]') if 'Дальше' in text_of(item)), None)
        else:
            next_link = soup.select_one('#chapters-load-more a')
        if next_link is None:
            break
        next_url = site_link(next_link.get('hx-get') or next_link.get('href'), final)
        parsed = urlsplit(next_url)
        if parsed.path.rstrip('/') != f'/manga/{slug}/chapters' or not parse_qs(parsed.query).get('page'):
            raise SourceError('Manga-shi изменил адрес следующей страницы глав.')
        if next_url in seen:
            raise SourceError('Manga-shi повторил страницу списка глав.')
        if len(found) >= 1500 or len(seen) >= 39:
            return list(found.values()), True
        seen.add(next_url)
        soup, final = document(http, next_url)
    return list(found.values()), False


def details(http, url):
    url = site_link(url)
    if not TITLE_PATH.fullmatch(urlsplit(url).path):
        raise SourceError('Некорректная ссылка на тайтл Manga-shi.')
    soup, final = document(http, url)
    return metadata(soup, final)


def inspect(url, http):
    url = site_link(url)
    path = urlsplit(url).path
    title_match = TITLE_PATH.fullmatch(path)
    chapter_match = CHAPTER_PATH.fullmatch(path)
    if not (title_match or chapter_match):
        raise SourceError('Некорректная ссылка на тайтл или главу Manga-shi.')
    soup, final = document(http, url)
    pages = []
    truncated = False
    if chapter_match:
        pages = [link_to_image(image.get('data-src') or image.get('src'), final)
                 for image in soup.select('img.reader-image')]
        if not pages or len(pages) > 500 or not all(pages):
            raise SourceError('Manga-shi не вернул изображения открытой главы.')
        entry = chapter(final, '')
        title = text_of(soup.select_one('h1')) or text_of(soup.title).split(' читать онлайн')[0]
        result = row(title or chapter_match[1], f'{ROOT}/manga/{chapter_match[1]}/')
        episodes = [entry]
    else:
        result = metadata(soup, final)
        episodes, truncated = chapters(http, soup, final, title_match[1])
    episodes.sort(key=lambda item: (item['season'], item['number']))
    return {**result, 'url': final, 'pages': pages, 'episodes': episodes,
            'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({e['season'] for e in episodes})],
            'dubs': [], 'releases': [], 'translations': [], 'available': bool(episodes),
            'truncated': truncated}
