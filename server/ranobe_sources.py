"""Light-novel (ranobe) text sources with public JSON APIs.

RanobeHub (Russian), Zenko and Smakolyky (Ukrainian fan translations).
Endpoints follow the MIT LNReader plugins (plugins/russian/ranobehub.ts,
plugins/ukrainian/smakolykytl.ts) and the Keiyoushi Zenko extension. Chapters
are returned as plain paragraphs: no scripts, links, ads or site markup reach
the reader. Paid or draft chapters are skipped, never presented as readable.
"""
import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlencode, urlsplit

from bs4 import BeautifulSoup
from source_parser import PublicHttp, SourceError
from title_identity import aliases, match_title

HUB = 'https://ranobehub.org'
ZENKO = 'https://zenko.online'
ZENKO_API = 'https://api.zenko.online'
SMAK = 'https://smakolykytl.site'
SMAK_API = 'https://api.smakolykytl.site/api/user'
SOURCES = (('ranobehub', 'RanobeHub', 'ru'), ('ranobelib', 'RanobeLib', 'ru'), ('jaomix', 'Jaomix', 'ru'), ('rulate', 'Rulate', 'ru'), ('zenko-novel', 'Zenko · UA', 'uk'), ('smakolyky', 'Смаколики · UA', 'uk'), ('baka', 'Бака · UA', 'uk'))
BAKA = 'https://baka.in.ua'
HIKKA = 'https://api.hikka.io'
MAX_CHAPTERS = 3000
MAX_PARAGRAPHS = 4000
_cache = {}
_lock = threading.RLock()


def _json(http, url):
    text, _, _ = http.document(url, headers={'Accept': 'application/json'}, action='ranobe')
    try:
        return json.loads(text)
    except ValueError:
        raise SourceError('Источник ранобэ вернул неизвестный формат.') from None


def _names(*values):
    names = []
    for value in values:
        for part in re.split(r'\s+/\s+|\n', str(value or '')):
            part = ' '.join(part.split())[:300]
            if part and part not in names: names.append(part)
    return names


def _number(value, fallback):
    match = re.search(r'\d+(?:[.,]\d+)?', str(value or ''))
    if not match: return fallback
    number = float(match.group().replace(',', '.'))
    return int(number) if number.is_integer() else number


def html_paragraphs(html):
    """Readable paragraphs from chapter HTML; drops scripts, styles, links to channels and empty lines."""
    soup = BeautifulSoup(str(html or ''), 'html.parser')
    for node in soup.select('script,style,iframe,form,button,noscript,.ads,.social-share'): node.decompose()
    for br in soup.find_all('br'): br.replace_with('\n')
    blocks = soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'blockquote', 'li', 'div'])
    texts = []
    if blocks:
        for block in blocks:
            if block.find(['p', 'div', 'li', 'blockquote']): continue  # keep leaves only
            texts.extend(block.get_text('').split('\n'))
    else:
        texts = soup.get_text('').split('\n')
    result = []
    for text in texts:
        text = re.sub(r'[ \t ]+', ' ', text).strip()
        if not text or re.fullmatch(r'[=\-_*~·.]{3,}', text): continue
        result.append(text[:4000])
        if len(result) >= MAX_PARAGRAPHS: break
    return result


def tiptap_paragraphs(document):
    """Smakolyky stores chapters as a TipTap/ProseMirror JSON document."""
    if isinstance(document, str):
        try: document = json.loads(document)
        except ValueError: return html_paragraphs(document)
    result = []

    def text_of(node):
        if not isinstance(node, dict): return ''
        if node.get('type') == 'text': return str(node.get('text') or '')
        if node.get('type') == 'hardBreak': return '\n'
        return ''.join(text_of(child) for child in node.get('content') or [])

    def walk(nodes):
        for node in nodes or []:
            if not isinstance(node, dict): continue
            if node.get('type') in {'paragraph', 'heading', 'blockquote', 'listItem'}:
                for line in text_of(node).split('\n'):
                    line = ' '.join(line.split())
                    if line: result.append(line[:4000])
            else:
                walk(node.get('content'))

    walk(document if isinstance(document, list) else (document or {}).get('content') or [])
    return result[:MAX_PARAGRAPHS]


# ------------------------------------------------------------ search per source

def _hub_search(query, http):
    data = _json(http, HUB + '/api/search?' + urlencode({'q': query[:160]}))
    for item in (data.get('books') if isinstance(data, dict) else None) or []:
        if not isinstance(item, dict) or not str(item.get('id', '')).isdigit(): continue
        yield {'provider': 'ranobehub', 'providerName': 'RanobeHub', 'language': 'ru',
               'title': ' '.join(str(item.get('title') or '').split()), 'aliases': _names(item.get('title'), item.get('originalTitle')),
               'url': HUB + '/ranobe/' + str(item['id']), 'description': str(item.get('description') or '')[:1200],
               'cover': ((item.get('poster') or {}).get('medium') if isinstance(item.get('poster'), dict) else '') or ''}


def _zenko_search(query, http):
    from manga_ukrainian import zenko_titles, ZENKO_IMAGES
    for item in zenko_titles(query, http, novels=True):
        cover = str(item.get('coverImg') or '')
        yield {'provider': 'zenko-novel', 'providerName': 'Zenko · UA', 'language': 'uk',
               'title': ' '.join(str(item.get('name') or '').split()), 'aliases': _names(item.get('name'), item.get('engName'), item.get('originalName')),
               'url': ZENKO + '/titles/' + str(item['id']), 'description': str(item.get('description') or '')[:1200],
               'cover': ZENKO_IMAGES + cover if re.fullmatch(r'[0-9a-f-]{36}', cover) else ''}


def _smak_projects(http):
    with _lock:
        hit = _cache.get('smak-projects')
        if hit and hit[0] > time.monotonic(): return hit[1]
    data = _json(http, SMAK_API + '/projects')
    rows = [p for p in (data.get('projects') if isinstance(data, dict) else None) or [] if isinstance(p, dict) and str(p.get('id', '')).isdigit()]
    with _lock: _cache['smak-projects'] = (time.monotonic() + 1800, rows)
    return rows


def _smak_search(query, http):
    for item in _smak_projects(http):
        names = _names(item.get('title'), item.get('alternatives'))
        image = item.get('image') if isinstance(item.get('image'), dict) else {}
        yield {'provider': 'smakolyky', 'providerName': 'Смаколики · UA', 'language': 'uk', 'title': names[0] if names else '',
               'aliases': names, 'url': SMAK + '/projects/' + str(item['id']), 'description': str(item.get('description') or '')[:1200],
               'translator': ' '.join(str(item.get('translator') or '').split())[:120],
               'cover': str(image.get('url') or '') if str(image.get('url') or '').startswith('https://') else ''}


def _hikka_reads(query, http, title=None):
    """Ukrainian 'where to read' links Hikka publishes for a novel, matched by MAL ID or exact title."""
    text, _, _ = http.document(HIKKA + '/novel?page=1&size=10', method='POST', data=json.dumps({'query': query[:120]}).encode(),
                               headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, action='hikka-search')
    try:
        rows = json.loads(text).get('list') or []
    except (ValueError, AttributeError):
        raise SourceError('Hikka вернула неизвестный формат.') from None
    mal = str(((title or {}).get('ids') or {}).get('mal') or '')
    for item in rows[:10]:
        if not isinstance(item, dict) or not re.fullmatch(r'[a-z0-9-]{1,120}', str(item.get('slug', ''))): continue
        names = _names(item.get('title_ua'), item.get('title_en'), item.get('title_original'))
        if mal and str(item.get('mal_id') or '') != mal: continue
        if not mal and title and not match_title({**title, 'kind': None}, {'title': names[0] if names else '', 'aliases': names})[0]: continue
        detail = _json(http, HIKKA + '/novel/' + item['slug'])
        for link in detail.get('external') or []:
            url = str((link or {}).get('url') or '')
            route = re.fullmatch(r'https://baka\.in\.ua/fictions/([A-Za-z0-9_-]{1,160})/?', url)
            if (link or {}).get('type') == 'read' and route:
                yield names, BAKA + '/fictions/' + route[1]


def _baka_search(query, http, title=None):
    """Hikka's links can be stale or redirect to the same book: open each once,
    keep only live pages, de-duplicate by the final address and use its heading."""
    seen = set()
    for names, url in list(_hikka_reads(query, http, title))[:6]:
        try:
            text, final, _ = http.document(url, action='ranobe')
        except SourceError:
            continue
        route = re.fullmatch(r'/fictions/([A-Za-z0-9_-]{1,160})/?', urlsplit(final).path)
        if urlsplit(final).hostname != 'baka.in.ua' or not route or route[1] in seen: continue
        seen.add(route[1])
        heading = BeautifulSoup(text, 'html.parser').find('h1')
        yield {'provider': 'baka', 'providerName': 'Бака · UA', 'language': 'uk',
               'title': heading.get_text(' ', strip=True)[:300] if heading else (names[0] if names else route[1]),
               'aliases': names, 'url': BAKA + '/fictions/' + route[1], 'description': '', 'cover': ''}


import ranobe_ru
SEARCH = {'ranobehub': _hub_search, 'zenko-novel': _zenko_search, 'smakolyky': _smak_search, 'baka': _baka_search, **ranobe_ru.SEARCH}


def search(title, language='all'):
    if isinstance(title, dict) and title.get('kind') == 'book':
        import book_sources
        return book_sources.search(title, language)
    if not isinstance(title, dict) or not aliases(title): raise SourceError('Выбери конкретное ранобэ из каталога.')
    if language not in {'all', 'ru', 'uk'}: raise SourceError('Выбери язык: все, русский или украинский.')
    key = json.dumps([language, aliases(title), title.get('ids')], ensure_ascii=False, sort_keys=True)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.monotonic(): return hit[1]
    wanted = {**title, 'kind': None}

    def work(source):
        identity, name, source_language = source
        http = PublicHttp(timeout=(3, 8), deadline=time.monotonic() + 20)
        results, status, message = [], 'empty', 'Точное совпадение не найдено.'
        try:
            for query in aliases(title)[:3]:
                found = SEARCH[identity](query, http, title) if identity == 'baka' else SEARCH[identity](query, http)
                for candidate in found:
                    if any(r['url'] == candidate['url'] for r in results): continue
                    # Baka links come from Hikka, already matched by MAL ID or exact title.
                    accepted, evidence = (True, 'hikka') if identity == 'baka' else match_title(wanted, candidate)
                    if accepted: results.append({**candidate, 'kind': 'ranobe', 'matchEvidence': evidence})
                if results: break
            # Exact titles first; sites list many fan-fics that only share the headline.
            strong = [r for r in results if r['matchEvidence'] in {'external_id', 'exact_title', 'title_and_season', 'hikka'}]
            results = (strong or results)[:3]
            if results: status, message = 'ok', 'Найдено: ' + str(len(results))
        except SourceError as error:
            status, message = 'unavailable', str(error)
        except (ValueError, TypeError, KeyError, AttributeError):
            status, message = 'unavailable', 'Формат источника изменился; адаптер требует проверки.'
        finally:
            http.close()
        return {'provider': identity, 'name': name, 'language': source_language, 'status': status, 'message': message, 'results': results}

    sources = [s for s in SOURCES if language == 'all' or s[2] == language]
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        providers = list(pool.map(work, sources))
    value = {'results': [r for p in providers for r in p['results']],
             'providers': [{k: p[k] for k in ('provider', 'name', 'language', 'status', 'message')} for p in providers],
             'language': language, 'checkedAt': int(time.time())}
    with _lock:
        if len(_cache) > 120: _cache.clear()
        _cache[key] = (time.monotonic() + 300, value)
    return value


# ------------------------------------------------------------ chapters and text

def _route(url):
    parts = urlsplit(url)
    host = (parts.hostname or '').lower()
    if host == 'baka.in.ua' and parts.scheme == 'https':
        book = re.fullmatch(r'/fictions/([A-Za-z0-9_-]{1,160})/?', parts.path)
        chapter = re.fullmatch(r'/chapters/([A-Za-z0-9_-]{1,200})/?', parts.path)
        if book: return 'baka', book[1], ''
        if chapter: return 'baka', parse_qs(parts.query).get('mv_book', [''])[0], chapter[1]
    selected = parse_qs(parts.query).get('mv_chapter', [''])[0]
    if selected and not selected.isdigit(): raise SourceError('Некорректная ссылка на главу.')
    for identity, pattern, hosts in (('ranobehub', r'/ranobe/(\d{1,9})(?:-[^/]*)?/?', {'ranobehub.org'}),
                                     ('zenko-novel', r'/titles/(\d{1,9})/?', {'zenko.online'}),
                                     ('smakolyky', r'/projects/(\d{1,9})/?', {'smakolykytl.site'})):
        match = re.fullmatch(pattern, parts.path)
        if host in hosts and match and parts.scheme == 'https': return identity, match[1], selected
    raise SourceError('Эта ссылка не относится к поддерживаемому источнику ранобэ.')


def _baka_book(book, http):
    """Baka lists chapters per volume section (Turbo frames); free chapters link to /chapters/."""
    text, final, _ = http.document(BAKA + '/fictions/' + book + '?order=asc', action='ranobe')
    route = re.fullmatch(r'/fictions/([A-Za-z0-9_-]{1,160})/?', urlsplit(final).path)
    if urlsplit(final).hostname != 'baka.in.ua' or not route: raise SourceError('Бака перенаправила на іншу сторінку.')
    book = route[1]
    soup = BeautifulSoup(text, 'html.parser')
    heading = soup.find('h1')
    title = (heading.get_text(' ', strip=True) if heading else book)[:300]
    sections = sorted(set(re.findall(r'section=(v-\d{1,4}(?:\.\d{1,3})?)', html.unescape(text))), key=lambda v: float(v[2:]))
    chapters, seen = [], set()

    def collect(page, volume):
        for link in BeautifulSoup(page, 'html.parser').select('a[href^="/chapters/"]'):
            slug = re.fullmatch(r'/chapters/([A-Za-z0-9_-]{1,200})', link.get('href', ''))
            if not slug or slug[1] in seen: continue
            label = ' '.join(link.get_text(' ', strip=True).split())
            number = re.search(r'Розділ\s+(\d+(?:[.,]\d+)?)', label)
            if not number: continue
            seen.add(slug[1])
            name = label.split('—', 1)[1].strip() if '—' in label else ''
            chapters.append({'number': _number(number[1], len(chapters) + 1), 'season': volume, 'title': name[:200],
                             'url': BAKA + '/chapters/' + slug[1] + '?' + urlencode({'mv_book': book})})

    for section in sections[:60]:
        page, _, _ = http.document(BAKA + '/fictions/' + book + '/chapter_section?' + urlencode({'order': 'asc', 'section': section}),
                                   headers={'Accept': 'text/vnd.turbo-stream.html, text/html'}, action='ranobe')
        collect(page, _number(section[2:], 1))
    if not sections: collect(text, 1)
    return title, chapters


def _chapter_url(identity, book, chapter):
    base = {'ranobehub': HUB + '/ranobe/', 'zenko-novel': ZENKO + '/titles/', 'smakolyky': SMAK + '/projects/'}[identity]
    return base + book + '?' + urlencode({'mv_chapter': chapter})


def _inspect_ru(url, http=None):
    own = http is None
    http = http or PublicHttp(timeout=(3, 10), deadline=time.monotonic() + 60)
    try:
        identity, base, title, names, chapters = ranobe_ru.book(url, http)
    finally:
        if own: http.close()
    chapters.sort(key=lambda c: (c['season'], c['number']))
    for c in chapters:
        c['language'] = 'ru'; c['title'] = c['title'] or 'Глава ' + str(c['number'])
    return {'provider': identity, 'providerName': dict((s[0], s[1]) for s in SOURCES)[identity], 'kind': 'ranobe',
            'title': title, 'aliases': names, 'url': base, 'language': 'ru', 'episodes': chapters,
            'seasons': [{'number': n, 'name': 'Том ' + str(n)} for n in sorted({c['season'] for c in chapters})]}


def inspect(url, http=None):
    """Book and its free chapter list (volume, number, title, url)."""
    import book_sources
    if book_sources.route(url): return book_sources.inspect(url)
    if ranobe_ru.route(url): return _inspect_ru(url, http)
    identity, book, _ = _route(url)
    own = http is None
    http = http or PublicHttp(timeout=(3, 10), deadline=time.monotonic() + 40)
    try:
        chapters, title, names, language = [], '', [], 'ru' if identity == 'ranobehub' else 'uk'
        if identity == 'ranobehub':
            offset = 0
            while offset < MAX_CHAPTERS:
                data = _json(http, HUB + '/api/books/' + book + '/chapters?' + urlencode({'limit': 100, 'offset': offset}))
                rows = data.get('items') if isinstance(data, dict) else None
                if not isinstance(rows, list) or not rows: break
                for row in rows:
                    if not isinstance(row, dict) or row.get('isDraft') or not str(row.get('id', '')).isdigit(): continue
                    chapters.append({'number': _number(row.get('number'), len(chapters) + 1), 'season': _number(row.get('volume'), 1),
                                     'title': ' '.join(str(row.get('title') or '').split())[:200], 'url': _chapter_url(identity, book, str(row['id']))})
                if len(rows) < 100: break
                offset += 100
            title = 'RanobeHub ' + book
            if chapters:
                # The public API has no book endpoint; each chapter names its book.
                first = re.search(r'mv_chapter=(\d+)', chapters[0]['url'])
                info = _json(http, HUB + '/api/chapters/' + first[1]).get('chapter') or {}
                if str(info.get('bookId')) == book and info.get('bookTitle'):
                    title = ' '.join(str(info['bookTitle']).split())[:300]; names = [title]
        elif identity == 'zenko-novel':
            from manga_ukrainian import zenko_chapter
            item = _json(http, ZENKO_API + '/titles/' + book)
            if str(item.get('category') or '').upper() != 'RANOBE': raise SourceError('Это не ранобэ: открой его в разделе «Манга».')
            names = _names(item.get('name'), item.get('engName'), item.get('originalName'))
            title = names[0] if names else book
            for row in _json(http, ZENKO_API + '/titles/' + book + '/chapters') or []:
                if not isinstance(row, dict) or not str(row.get('id', '')).isdigit() or row.get('isPublished') is False: continue
                volume, number, name = zenko_chapter(row.get('name'))
                chapters.append({'number': _number(number, len(chapters) + 1), 'season': volume, 'title': name,
                                 'translator': ' '.join(str((row.get('publisher') or {}).get('name') or '').split())[:120] if isinstance(row.get('publisher'), dict) else '',
                                 'url': _chapter_url(identity, book, str(row['id']))})
        elif identity == 'baka':
            title, chapters = _baka_book(book, http)
            names = [title]
        else:
            project = next((p for p in _smak_projects(http) if str(p.get('id')) == book), None)
            if not project: raise SourceError('Проєкт Смаколиків не знайдено.')
            names = _names(project.get('title'), project.get('alternatives'))
            title = names[0] if names else book
            data = _json(http, SMAK_API + '/projects/' + book + '/books')
            for volume in (data.get('books') if isinstance(data, dict) else None) or []:
                for row in (volume.get('chapters') if isinstance(volume, dict) else None) or []:
                    if not isinstance(row, dict) or not str(row.get('id', '')).isdigit(): continue
                    chapters.append({'number': _number(row.get('rank'), len(chapters) + 1), 'season': _number(volume.get('rank'), 1),
                                     'title': ' '.join(str(row.get('title') or '').split())[:200],
                                     'translator': ' '.join(str(project.get('translator') or '').split())[:120], 'url': _chapter_url(identity, book, str(row['id']))})
        chapters = chapters[:MAX_CHAPTERS]
        chapters.sort(key=lambda c: (c['season'], c['number']))
        for c in chapters:
            c.setdefault('translator', ''); c['language'] = language
            c['title'] = c['title'] or 'Глава ' + str(c['number'])
        return {'provider': identity, 'providerName': dict((s[0], s[1]) for s in SOURCES)[identity], 'kind': 'ranobe',
                'title': title, 'aliases': names, 'url': url, 'language': language, 'episodes': chapters,
                'seasons': [{'number': n, 'name': 'Том ' + str(n)} for n in sorted({c['season'] for c in chapters})]}
    finally:
        if own: http.close()


def chapter(url, http=None):
    """Plain paragraphs of one chapter."""
    import book_sources
    if book_sources.route(url): return book_sources.chapter(url)
    if ranobe_ru.route(url):
        own = http is None
        http = http or PublicHttp(timeout=(3, 10), deadline=time.monotonic() + 25)
        try:
            title, paragraphs = ranobe_ru.chapter(url, http)
        finally:
            if own: http.close()
        if not paragraphs: raise SourceError('Глава пуста или доступна только на сайте источника.')
        return {'provider': ranobe_ru.route(url)[0], 'url': url, 'title': title[:200], 'language': 'ru', 'paragraphs': paragraphs[:MAX_PARAGRAPHS]}
    identity, book, selected = _route(url)
    if not selected: raise SourceError('Выбери конкретную главу.')
    own = http is None
    http = http or PublicHttp(timeout=(3, 10), deadline=time.monotonic() + 25)
    try:
        if identity == 'ranobehub':
            data = _json(http, HUB + '/api/chapters/' + selected).get('chapter') or {}
            if str(data.get('bookId') or book) != book: raise SourceError('Глава относится к другой книге.')
            title, paragraphs = data.get('title') or '', html_paragraphs(data.get('html'))
        elif identity == 'zenko-novel':
            data = _json(http, ZENKO_API + '/chapters/' + selected)
            if str(data.get('titleId')) != book: raise SourceError('Глава относится к другой книге.')
            from manga_ukrainian import zenko_chapter
            title = zenko_chapter(data.get('name'))[2]
            pages = sorted((p for p in data.get('pages') or [] if isinstance(p, dict)), key=lambda p: p.get('order', 0))
            paragraphs = [line for page in pages for line in html_paragraphs(page.get('content'))]
        elif identity == 'baka':
            text, final, _ = http.document(BAKA + '/chapters/' + selected, action='ranobe')
            if urlsplit(final).hostname != 'baka.in.ua' or urlsplit(final).path.startswith('/login'):
                raise SourceError('Розділ доступний лише після входу на сайті Бака.')
            soup = BeautifulSoup(text, 'html.parser')
            body = soup.select_one('div.prose') or soup.select_one('.trix-content')
            heading = soup.find('h1')
            title, paragraphs = (heading.get_text(' ', strip=True) if heading else ''), html_paragraphs(str(body) if body else '')
        else:
            data = _json(http, SMAK_API + '/chapters/' + selected).get('chapter') or {}
            title, paragraphs = data.get('title') or '', tiptap_paragraphs(data.get('content'))
        if not paragraphs: raise SourceError('Глава пуста или доступна только на сайте источника.')
        return {'provider': identity, 'url': url, 'title': ' '.join(str(title).split())[:200], 'language': 'ru' if identity == 'ranobehub' else 'uk',
                'paragraphs': paragraphs[:MAX_PARAGRAPHS]}
    finally:
        if own: http.close()
