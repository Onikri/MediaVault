"""Russian ranobe sources: RanobeLib (LibGroup API), Jaomix and Rulate.

Same shape as ranobe_sources: search(query, http) yields candidates,
book(...) returns the free chapter list, chapter(...) plain paragraphs.
Only public, free chapters are listed: Rulate's paid chapters (no "читать"
button) and LibGroup chapters closed to guests are skipped, never presented
as readable. Sites behind DDoS-Guard/Cloudflare or geo-blocks (Renovels,
Ranobes, Novel.tl) are not used.
"""
import json
import re
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from bs4 import BeautifulSoup
from source_parser import SourceError

LIB_API = 'https://api.cdnlibs.org'
LIB_ROOT = 'https://ranobelib.me'
LIB_SITE = 3
JAOMIX = 'https://jaomix.ru'
RULATE = 'https://tl.rulate.ru'
SOURCES = (('ranobelib', 'RanobeLib', 'ru'), ('jaomix', 'Jaomix', 'ru'), ('rulate', 'Rulate', 'ru'))
MAX_CHAPTERS = 3000


def _clean(text):
    return ' '.join(str(text or '').replace('\xa0', ' ').split())


def _number(value, fallback):
    match = re.search(r'\d+(?:[.,]\d+)?', str(value or ''))
    if not match: return fallback
    number = float(match.group().replace(',', '.'))
    return int(number) if number.is_integer() else number


# ------------------------------------------------------------------ RanobeLib

def _lib(path, http, params=None):
    from manga_catalog_adapters import get
    context = SimpleNamespace(timeout=getattr(http, 'timeout', (3, 8)), deadline=getattr(http, 'deadline', None) or time.monotonic() + 30, lib_site_id=LIB_SITE)
    return get(LIB_API + path + ('?' + urlencode(params, doseq=True) if params else ''), context)


def lib_search(query, http):
    for item in _lib('/api/manga', http, {'q': query[:160], 'site_id[]': LIB_SITE}).get('data') or []:
        slug = str(item.get('slug_url') or '')
        if not re.fullmatch(r'[\w-]{1,250}', slug): continue
        names = [n for n in (_clean(item.get('rus_name')), _clean(item.get('eng_name')), _clean(item.get('name'))) if n]
        if not names: continue
        cover = (item.get('cover') or {}).get('default') if isinstance(item.get('cover'), dict) else ''
        yield {'provider': 'ranobelib', 'providerName': 'RanobeLib', 'language': 'ru', 'title': names[0], 'aliases': names,
               'url': LIB_ROOT + '/ru/book/' + slug, 'cover': cover or '', 'licensed': bool(item.get('is_licensed'))}


def lib_book(slug, http):
    detail = _lib('/api/manga/' + slug, http).get('data') or {}
    names = [n for n in (_clean(detail.get('rus_name')), _clean(detail.get('eng_name')), _clean(detail.get('name'))) if n]
    chapters = []
    for row in _lib('/api/manga/' + slug + '/chapters', http).get('data') or []:
        branches = [b for b in row.get('branches') or [] if isinstance(b, dict)]
        branch = branches[0] if branches else {}
        teams = ', '.join(_clean(t.get('name')) for t in branch.get('teams') or [] if isinstance(t, dict))[:120]
        query = {'mv_volume': str(row.get('volume') or '1'), 'mv_number': str(row.get('number') or '')}
        if branch.get('branch_id'): query['mv_branch'] = str(branch['branch_id'])
        if not re.fullmatch(r'[\d.]{1,12}', query['mv_number']) or not re.fullmatch(r'[\d.]{1,12}', query['mv_volume']): continue
        chapters.append({'number': _number(row.get('number'), len(chapters) + 1), 'season': _number(row.get('volume'), 1),
                         'title': _clean(row.get('name'))[:200], 'translator': teams, 'url': LIB_ROOT + '/ru/book/' + slug + '?' + urlencode(query)})
    return (names[0] if names else slug), names, chapters


def lib_chapter(slug, query, http):
    from ranobe_sources import html_paragraphs, tiptap_paragraphs
    params = {'number': query['mv_number'], 'volume': query['mv_volume']}
    if query.get('mv_branch'): params['branch_id'] = query['mv_branch']
    data = _lib('/api/manga/' + slug + '/chapter', http, params).get('data') or {}
    content = data.get('content')
    paragraphs = tiptap_paragraphs(content) if isinstance(content, dict) else html_paragraphs(content or '')
    return _clean(data.get('name')), paragraphs


# ------------------------------------------------------------------ Jaomix

def jaomix_search(query, http):
    text, _, _ = http.document(JAOMIX + '/?' + urlencode({'searchrn': query[:120]}), action='ranobe')
    for block in BeautifulSoup(text, 'html.parser').select('div.block-home div.one'):
        link = block.select_one('div.img-home a[href]') or block.select_one('a[href]')
        href = str(link.get('href') or '') if link else ''
        path = urlsplit(href).path
        if urlsplit(href).hostname != 'jaomix.ru' or not re.fullmatch(r'/[\w%-]{1,200}/', path): continue
        heading = block.select_one('.title-home')
        title = _clean(heading.get_text(' ') if heading else link.get('title') or link.get_text(' '))
        english = block.select_one('.en-title-home')
        names = [n for n in (title, _clean(english.get_text(' ')) if english else '') if n]
        if names:
            yield {'provider': 'jaomix', 'providerName': 'Jaomix', 'language': 'ru', 'title': names[0], 'aliases': names, 'url': JAOMIX + path}


def _jaomix_rows(html, slug):
    rows = []
    for link in BeautifulSoup(html, 'html.parser').select('div.flex-dow-txt div.title a[href]'):
        path = urlsplit(link.get('href') or '').path
        if urlsplit(link.get('href') or '').hostname != 'jaomix.ru' or not re.fullmatch(r'/' + re.escape(slug) + r'/[\w%-]{1,240}/', path): continue
        rows.append((_clean(link.get('title') or link.get_text(' ')), JAOMIX + path))
    return rows


def jaomix_book(slug, http):
    url = JAOMIX + '/' + slug + '/'
    text, final, _ = http.document(url, action='ranobe')
    if urlsplit(final).hostname != 'jaomix.ru': raise SourceError('Jaomix перенаправил на другой сайт.')
    soup = BeautifulSoup(text, 'html.parser')
    heading = soup.select_one('h1')
    title = _clean(heading.get_text(' ') if heading else slug)[:300]
    pages = sorted({int(o.get('value')) for o in soup.select('select.sel-toc option') if str(o.get('value') or '').isdigit()})
    rows = []
    if len(pages) > 1:
        # Table of contents pages (newest first); the site identifies the book by Referer.
        for page in pages[:60]:
            html, _, _ = http.document(JAOMIX + '/wp-admin/admin-ajax.php', method='POST', data={'action': 'loadpagenavchapstt', 'page': str(page)},
                                       headers={'Referer': url}, action='ranobe')
            rows += _jaomix_rows(html, slug)
    else:
        rows = _jaomix_rows(text, slug)
    seen, chapters = set(), []
    for position, (name, link) in enumerate(reversed(rows)):
        if link in seen: continue
        seen.add(link)
        volume = re.search(r'Том\s*(\d+(?:[.,]\d+)?)', name, re.I)
        number = re.search(r'Глава\s*№?\s*(\d+(?:[.,]\d+)?)', name, re.I)
        chapters.append({'number': _number(number.group(1), position + 1) if number else position + 1,
                         'season': _number(volume.group(1), 1) if volume else 1, 'title': name[:200], 'translator': '', 'url': link})
    return title, [title], chapters[:MAX_CHAPTERS]


def jaomix_chapter(path, http):
    from ranobe_sources import html_paragraphs
    text, final, _ = http.document(JAOMIX + path, action='ranobe')
    if urlsplit(final).hostname != 'jaomix.ru': raise SourceError('Jaomix перенаправил на другой сайт.')
    soup = BeautifulSoup(text, 'html.parser')
    body = soup.select_one('div.entry-content')
    if not body: raise SourceError('Jaomix не показал текст главы (возможно, просит пройти проверку).')
    for node in body.select('.adblock-service,.lazyblock,script,style,ins,iframe,.but-captcha'): node.decompose()
    paragraphs = html_paragraphs(str(body))
    heading = soup.select_one('h1')
    title = _clean(heading.get_text(' ') if heading else '')
    if paragraphs and title and paragraphs[0].startswith(title.split(':')[0]): paragraphs = paragraphs[1:] or paragraphs
    return title, paragraphs


# ------------------------------------------------------------------ Rulate

def rulate_search(query, http):
    text, _, _ = http.document(RULATE + '/search?' + urlencode({'t': query[:120], 'cat': '12', 's_lang': '', 't_lang': '', 'type': '0', 'sort': '6', 'atmosphere': '', 'adult': '0'}), action='ranobe')
    soup = BeautifulSoup(text, 'html.parser')
    for item in soup.select('ul.search-results li'):
        link = item.select_one('p a[href^="/book/"]')
        match = re.match(r'/book/(\d{1,9})', link.get('href') or '') if link else None
        if not match: continue
        original = item.select_one('p small')
        names = [n for n in (_clean(link.get_text(' ')), _clean(original.get_text(' ')) if original else '') if n]
        yield {'provider': 'rulate', 'providerName': 'Rulate', 'language': 'ru', 'title': names[0], 'aliases': names, 'url': RULATE + '/book/' + match.group(1)}


def rulate_book(book, http):
    text, final, _ = http.document(RULATE + '/book/' + book, action='ranobe')
    if urlsplit(final).hostname != 'tl.rulate.ru' or not urlsplit(final).path.startswith('/book/' + book):
        raise SourceError('Rulate просит подтвердить возраст или вход: такая книга не открывается без аккаунта.')
    soup = BeautifulSoup(text, 'html.parser')
    heading = soup.select_one('h1')
    full = _clean(heading.get_text(' ') if heading else '')
    names = [n.strip() for n in full.split(' / ') if n.strip()][::-1] or ['Rulate ' + book]
    chapters, volume = [], 1
    for row in soup.select('#Chapters tr, table tr'):
        strong = row.select_one('strong')
        if strong and 'chapter_row' not in (row.get('class') or []):
            volume = _number(strong.get_text(' '), volume); continue
        if 'chapter_row' not in (row.get('class') or []): continue
        read = row.select_one('a.btn-info[href$="/ready_new"]')  # free, ready translation
        if not read: continue
        match = re.fullmatch(r'/book/' + book + r'/(\d{1,12})/ready_new', read.get('href') or '')
        if not match: continue
        name = _clean((row.select_one('td.t a') or read).get_text(' '))
        chapters.append({'number': _number(re.search(r'(?:Глава|Chapter)\s*([\d.]+)', name).group(1) if re.search(r'(?:Глава|Chapter)\s*[\d.]+', name) else '', len(chapters) + 1),
                         'season': volume, 'title': name[:200], 'translator': '', 'url': RULATE + '/book/' + book + '/' + match.group(1) + '/ready_new'})
    return names[0], names, chapters[:MAX_CHAPTERS]


def rulate_chapter(book, chapter, http):
    from ranobe_sources import html_paragraphs
    text, final, _ = http.document(RULATE + '/book/' + book + '/' + chapter + '/ready_new', action='ranobe')
    if not urlsplit(final).path.endswith('/ready_new'): raise SourceError('Эта глава Rulate платная или требует входа.')
    soup = BeautifulSoup(text, 'html.parser')
    body = soup.select_one('div.content-text')
    if not body: raise SourceError('Эта глава Rulate платная или требует входа.')
    heading = soup.select_one('#text-container h1')
    title = _clean(heading.get_text(' ')).split(': ', 1)[-1] if heading else ''
    return title, html_paragraphs(str(body))


# ------------------------------------------------------------------ routing

SEARCH = {'ranobelib': lib_search, 'jaomix': jaomix_search, 'rulate': rulate_search}


def route(url):
    parts = urlsplit(str(url or ''))
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https': return None
    if host == 'ranobelib.me':
        match = re.fullmatch(r'/ru/book/([\w-]{1,250})/?', parts.path)
        if not match: raise SourceError('Открой страницу ранобэ на RanobeLib.')
        query = {k: v[0] for k, v in parse_qs(parts.query).items() if k in {'mv_volume', 'mv_number', 'mv_branch'}}
        if any(not re.fullmatch(r'[\d.]{1,12}', v) for v in query.values()): raise SourceError('Некорректная ссылка на главу.')
        return 'ranobelib', match.group(1), query if 'mv_number' in query else {}
    if host == 'jaomix.ru':
        match = re.fullmatch(r'/([\w%-]{1,200})/(?:([\w%-]{1,240})/)?', parts.path)
        if not match: raise SourceError('Открой страницу ранобэ на Jaomix.')
        return 'jaomix', match.group(1), (parts.path if match.group(2) else {})
    if host == 'tl.rulate.ru':
        match = re.fullmatch(r'/book/(\d{1,9})(?:/(\d{1,12})/ready_new)?/?', parts.path)
        if not match: raise SourceError('Открой страницу книги на Rulate.')
        return 'rulate', match.group(1), (match.group(2) or {})
    return None


def book(url, http):
    identity, key, _ = route(url)
    if identity == 'ranobelib': title, names, chapters = lib_book(key, http); base = LIB_ROOT + '/ru/book/' + key
    elif identity == 'jaomix': title, names, chapters = jaomix_book(key, http); base = JAOMIX + '/' + key + '/'
    else: title, names, chapters = rulate_book(key, http); base = RULATE + '/book/' + key
    return identity, base, title, names, chapters


def chapter(url, http):
    identity, key, selected = route(url)
    if not selected: raise SourceError('Выбери конкретную главу.')
    if identity == 'ranobelib': return lib_chapter(key, selected, http)
    if identity == 'jaomix': return jaomix_chapter(selected, http)
    return rulate_chapter(key, selected, http)
