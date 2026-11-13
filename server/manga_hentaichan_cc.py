"""Public search and reader for hentaichan.cc's Next.js and TanStack pages."""
import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from source_parser import PublicHttp, SourceError, public_url
from manga_source_tags import from_api, from_html

ROOT = 'https://hentaichan.cc'
SOURCE = {'id': '990000000000000002', 'name': 'HentaiChan.cc', 'lang': 'ru',
          'baseUrl': ROOT, 'isNsfw': True}
CDN = 'cdn.hentaichan.cc'
PATH = re.compile(r'/(manga|read)/([\w-]{1,240})/?')


def cdn_image(value):
    try:
        url = public_url(value, resolve_dns=False)
        if urlsplit(url).hostname == CDN:
            return url
    except SourceError:
        pass
    return ''


def entries(query, http):
    """Raw (title, slug, row) triples from the public search box."""
    text, final, _ = http.document(ROOT + '/', method='POST', data=query, action='hentaichan-search')
    if final != ROOT + '/':
        raise SourceError('HentaiChan.cc перенаправил поиск.')
    for line in text.splitlines():
        prefix, _, payload = line.partition(':')
        if prefix != '1':
            continue
        try:
            result = json.loads(payload)
        except ValueError:
            break
        rows = result.get('data') if isinstance(result, dict) else None
        if not isinstance(rows, list):
            break
        found = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title, slug = row.get('name'), row.get('slug')
            if not isinstance(title, str) or not title.strip() or not isinstance(slug, str) or not re.fullmatch(r'[\w-]{1,240}', slug):
                continue
            found.append((title.strip()[:500], slug, row))
        return found
    raise SourceError('HentaiChan.cc изменил формат ответа поиска.')


def search(query, http):
    from manga_hentaichan import number, series_title
    grouped = {}
    for title, slug, row in entries(query, http):
        # A series split into per-chapter entries is one work; its earliest
        # entry represents it and the reader collects the sibling parts.
        series = series_title(title)
        name = series or title
        part = number(title) if series else None
        url = ROOT + '/manga/' + slug
        value = {'id': 'hentaichan-cc:' + slug, 'provider': 'hentaichan-cc', 'providerName': SOURCE['name'],
                 'sourceId': SOURCE['id'], 'url': url, 'sourceURL': url, 'sourceUrl': url,
                 'title': name, 'aliases': [name], 'cover': cdn_image(row.get('src')),
                 'kind': 'manga', 'format': 'manga', 'language': 'ru', 'sourceOnly': True, 'adult': True, 'age': 18, **from_api(row)}
        rank = (part is None, part if part is not None else 0)
        key = name.casefold()
        if key not in grouped or rank < grouped[key][0]:
            grouped[key] = (rank, value)
    return [value for _, value in grouped.values()]


def siblings(series, http):
    """Every per-chapter entry of a split series, as reader chapters."""
    from manga_hentaichan import number, series_title
    try:
        found = entries(series, http)
    except SourceError:
        return []
    result = []
    for title, slug, _ in found:
        if (series_title(title) or '').casefold() != series.casefold():
            continue
        part = number(title)
        if part is None:
            continue
        result.append({'number': part, 'season': 1, 'url': ROOT + '/read/' + slug, 'title': title,
                       'language': 'ru', 'translator': ''})
    return result


def chapter(url, slug, index):
    from manga_sources import chapter_number

    number = re.search(r'-(?:glava|chapter)-(\d+(?:[.-]\d+)?)$', slug)
    value = chapter_number(number[1].replace('-', '.')) if number else index
    return {'number': value, 'season': 1, 'url': url, 'title': f'Глава {value}', 'language': 'ru', 'translator': ''}


def inspect(url, http: PublicHttp):
    parts = urlsplit(public_url(url, resolve_dns=False))
    path = PATH.fullmatch(parts.path)
    if parts.hostname != 'hentaichan.cc' or not path:
        raise SourceError('Выбери мангу или главу HentaiChan.cc.')
    canonical = ROOT + f'/{path[1]}/{path[2]}'
    text, final, _ = http.document(canonical)
    if final.rstrip('/') != canonical:
        raise SourceError('HentaiChan.cc перенаправил на другую публикацию.')
    soup = BeautifulSoup(text, 'html.parser')
    title = soup.select_one('h1') or soup.select_one('meta[property="og:title"]') or soup.title
    name = (title.get('content') or title.get_text(' ', strip=True))[:500] if title else SOURCE['name']
    meta = soup.select_one('meta[property="og:image"]')
    cover = cdn_image(meta.get('content')) if meta else ''
    pages, chapters = [], []
    if path[1] == 'read':
        script = next((s.string for s in soup.select('script:not([src])') if '$_TSR.router=' in (s.string or '')), '')
        block = re.search(r'pages:\$R\[\d+\]=\[(.*?)\],\w+:', script, re.S)
        if block:
            pages = [cdn_image(value) for value in re.findall(r'originalSrc:"([^"\\]+)"', block[1])]
        if not pages or not all(pages) or len(pages) > 500:
            raise SourceError('HentaiChan.cc не предоставил страницы этой главы.')
        chapters = [chapter(canonical, path[2], 1)]
    else:
        seen = set()
        for link in soup.select('a[href^="/read/"]'):
            match = PATH.fullmatch(link['href'])
            if match and match[2] not in seen:
                seen.add(match[2])
                chapters.append(chapter(ROOT + '/read/' + match[2], match[2], len(chapters) + 1))
        from manga_hentaichan import series_title
        series = series_title(name)
        if series and len(chapters) <= 1:
            # A per-chapter entry shows only its own part; its siblings are
            # separate catalogue entries found by the series name.
            from manga_hentaichan import number
            parts = siblings(series, http)
            if parts:
                own = number(name)
                for entry in chapters:
                    entry['number'] = own if own is not None else entry['number']
                known = {entry['url'] for entry in parts}
                chapters = parts + [entry for entry in chapters if entry['url'] not in known]
                name = series
        chapters = list({entry['url']: entry for entry in chapters}.values())
        chapters.sort(key=lambda entry: entry['number'])
    return {'provider': 'hentaichan-cc', 'providerName': SOURCE['name'], 'url': canonical,
            'title': name, 'cover': cover, 'kind': 'manga', 'format': 'manga', 'language': 'ru',
            'adult': True, 'age': 18, **from_html(soup), 'episodes': chapters, 'pages': pages,
            'seasons': [{'number': 1, 'name': 'Том 1'}] if chapters else [], 'dubs': [],
            'releases': [], 'translations': [], 'available': bool(chapters)}
