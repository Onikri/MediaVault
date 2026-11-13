"""HManga public Madara-style catalogue and chapter reader.

Public metadata and chapter pages only. No credentials, challenges, or
JavaScript execution. hmanga.su may redirect only to the confirmed hmanga.me.
"""
import re
from urllib.parse import unquote, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup
from source_parser import SourceError, public_url

ROOT = 'https://hmanga.me'
HOSTS = frozenset({'hmanga.me', 'hmanga.su'})
SOURCE = {'id': '990000000000000003', 'name': 'HManga', 'lang': 'ru',
          'baseUrl': ROOT, 'isNsfw': True}
SLUG = re.compile(r'[a-z0-9][a-z0-9_-]{0,180}', re.I)
NUMBER = re.compile(r'(?:глава|chapter|ch\.?|часть)\s*[-:#№]*\s*(\d{1,4}(?:[.,]\d{1,3})?)', re.I)
IMAGE = re.compile(r'\.(?:jpe?g|png|webp|gif|avif)$', re.I)


def clean(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip()[:500]


def _work_url(value, base, *, chapter=False):
    try:
        target = public_url(urljoin(base, str(value or '')), resolve_dns=False)
    except (SourceError, TypeError, ValueError):
        return ''
    parsed = urlsplit(target)
    if parsed.hostname not in HOSTS:
        return ''
    parts = [unquote(x) for x in parsed.path.strip('/').split('/')]
    if len(parts) < 2 or parts[0] != 'manga' or not SLUG.fullmatch(parts[1]):
        return ''
    if chapter:
        if len(parts) != 3 or not parts[2] or len(parts[2]) > 200:
            return ''
    elif len(parts) != 2:
        return ''
    return target


def aliases(name):
    original = clean(name)
    bare = re.sub(r'\s*\[\d{2,8}\]\s*$', '', original).strip()
    values = [original, bare, *re.split(r'\s+[—–]\s+|\s+/\s+', bare)]
    return list(dict.fromkeys(x for x in map(clean, values) if len(x) > 1))


def parse_search(text, base=ROOT):
    soup = BeautifulSoup(text, 'html.parser')
    found = {}
    cards = soup.select('.c-tabs-item__content,.page-item-detail,.row.c-tabs-item__content')
    # Some Madara templates omit card wrappers. Only heading links are eligible.
    if not cards:
        cards = soup.select('h2,h3,h4')
    for card in cards[:120]:
        a = card.select_one('.post-title a[href],h2 a[href],h3 a[href],h4 a[href]')
        if not a and card.name in {'h2', 'h3', 'h4'}:
            a = card.select_one('a[href]')
        if not a:
            continue
        url = _work_url(a.get('href'), base)
        title = clean(a.get_text(' ', strip=True))
        if not url or not title:
            continue
        img = card.select_one('img')
        cover = ''
        if img:
            try:
                cover = public_url(urljoin(base, img.get('data-src') or img.get('src') or ''), resolve_dns=False)
            except SourceError:
                pass
        found[url] = {
            'id': 'hmanga:' + urlsplit(url).path.strip('/').split('/')[1],
            'provider': 'hmanga', 'providerName': SOURCE['name'],
            'sourceId': SOURCE['id'], 'sourceOnly': True,
            'url': url, 'sourceURL': url, 'sourceUrl': url,
            'title': title, 'aliases': aliases(title), 'kind': 'manga',
            'language': 'ru', 'format': '', 'adult': True,
            'age': 18, 'cover': cover, 'ids': {}, 'genres': [], 'tags': []}
        if len(found) >= 40:
            break
    return list(found.values())


def search(query, http):
    query = clean(query)[:160]
    if len(query) < 2:
        return []
    url = ROOT + '/?' + urlencode({'post_type': 'wp-manga', 's': query})
    text, final, _ = http.document(url)
    parsed = urlsplit(final)
    if parsed.hostname not in HOSTS or parsed.path not in {'', '/'}:
        raise SourceError('HManga перенаправил поиск вне каталога.')
    return parse_search(text, final)


def chapter_number(text):
    from manga_sources import chapter_number as checked_number
    m = NUMBER.search(unquote(str(text or '')).replace('-', ' '))
    return checked_number(m[1]) if m else None


def parse_chapters(soup, base, work_slug):
    found = {}
    for a in soup.select('a[href]')[:2000]:
        link = _work_url(a.get('href'), base, chapter=True)
        if not link:
            continue
        parts = [unquote(x) for x in urlsplit(link).path.strip('/').split('/')]
        if parts[1] != work_slug:
            continue
        label = clean(a.get_text(' ', strip=True))
        number = chapter_number(label)
        if number is None:
            number = chapter_number(parts[2])
        if number is None:
            continue
        found[link] = {'number': number, 'season': 1, 'url': link,
                       'title': label if chapter_number(label) is not None else 'Глава ' + str(number),
                       'translator': '', 'language': 'ru'}
        if len(found) >= 1500:
            break
    return sorted(found.values(), key=lambda x: (x['season'], x['number'], x['url']))


def parse_pages(text, base):
    soup = BeautifulSoup(text, 'html.parser')
    found = []
    for img in soup.select('.reading-content img,.page-break img,img.wp-manga-chapter-img')[:501]:
        raw = img.get('data-src') or img.get('data-lazy-src') or img.get('data-original') or img.get('src')
        if not raw:
            continue
        try:
            url = public_url(urljoin(base, raw.strip()), resolve_dns=False)
        except SourceError:
            continue
        if not IMAGE.search(urlsplit(url).path) or url in found:
            continue
        found.append(url)
    if len(found) > 500:
        raise SourceError('HManga вернул более 500 страниц.')
    return found


def _field(soup, names):
    for node in soup.select('.post-content_item'):
        heading = node.select_one('.summary-heading,h5')
        if heading and any(name in heading.get_text(' ', strip=True).casefold() for name in names):
            value = node.select_one('.summary-content')
            if value:
                return value
    return None


def inspect(url, http):
    manga = _work_url(url, url)
    chapter = _work_url(url, url, chapter=True)
    if not (manga or chapter):
        raise SourceError('Выбери публичную страницу манги или главы HManga.')
    text, final, _ = http.document(manga or chapter)
    if not (_work_url(final, final) or _work_url(final, final, chapter=True)):
        raise SourceError('HManga перенаправил на неизвестную страницу.')
    requested = [unquote(x) for x in urlsplit(manga or chapter).path.strip('/').split('/')]
    actual = [unquote(x) for x in urlsplit(final).path.strip('/').split('/')]
    if len(actual) != len(requested) or actual[:2] != requested[:2] or (chapter and actual[2] != requested[2]):
        raise SourceError('HManga перенаправил на другое произведение.')
    soup = BeautifulSoup(text, 'html.parser')
    from manga_sources import guard
    guard(soup)
    heading = soup.select_one('h1') or soup.select_one('meta[property="og:title"]')
    title = clean((heading.get('content') or heading.get_text(' ', strip=True)) if heading else '')
    if not title:
        raise SourceError('HManga не предоставил название произведения.')
    reading = bool(chapter)
    chapters = []
    pages = []
    if reading:
        pages = parse_pages(text, final)
        if not pages:
            raise SourceError('HManga не предоставил открытые страницы этой главы.')
        num = chapter_number(actual[2]) or chapter_number(title)
        if num is None:
            raise SourceError('HManga не удалось определить номер главы.')
        chapters = [{'number': num, 'season': 1, 'url': final,
                     'title': 'Глава ' + str(num), 'translator': '', 'language': 'ru'}]
    else:
        chapters = parse_chapters(soup, final, actual[1])
        if not chapters:
            raise SourceError('HManga не предоставил открытый список глав.')
    type_field = _field(soup, ('type', 'тип'))
    name_field = _field(soup, ('alternative', 'альтернатив'))
    tags_field = _field(soup, ('tag(s)', 'тег'))
    kind_text = clean(type_field.get_text(' ', strip=True)).casefold() if type_field else ''
    format_name = 'manhwa' if 'manhwa' in kind_text else 'manhua' if 'manhua' in kind_text else 'manga'
    tags = [clean(a.get_text(' ', strip=True)) for a in tags_field.select('a')][:60] if tags_field else []
    alternative = [clean(x) for x in re.split(r',\s*', name_field.get_text(' ', strip=True))][:30] if name_field else []
    cover_tag = soup.select_one('.summary_image img,meta[property="og:image"]')
    cover = ''
    if cover_tag:
        try:
            cover = public_url(urljoin(final, cover_tag.get('data-src') or cover_tag.get('content') or cover_tag.get('src') or ''), resolve_dns=False)
        except SourceError:
            pass
    full_list = bool(soup.select_one('.listing-chapters_wrap a[href],.main.version-chap a[href],.wp-manga-chapter a[href]'))
    return {'provider': 'hmanga', 'providerName': SOURCE['name'], 'title': title,
            'aliases': list(dict.fromkeys([*aliases(title), *(v for v in alternative if v)])),
            'url': final, 'kind': 'manga', 'language': 'ru', 'format': format_name,
            'readingMode': 'scroll' if format_name in {'manhwa', 'manhua'} else 'pages',
            'adult': True, 'age': 18, 'cover': cover, 'tags': list(dict.fromkeys(tags)),
            'episodes': chapters, 'pages': pages, 'available': bool(chapters),
            'seasons': [{'number': 1, 'name': 'Том 1'}], 'translations': [],
            'dubs': [], 'releases': [],
            'truncated': not reading and (not full_list or bool(soup.select_one('.chapter-list-pager,.pagination')))}
