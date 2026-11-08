"""Light-novel (ranobe) text sources with public JSON APIs.

RanobeHub (Russian), Zenko and Smakolyky (Ukrainian fan translations).
Endpoints follow the MIT LNReader plugins (plugins/russian/ranobehub.ts,
plugins/ukrainian/smakolykytl.ts) and the Keiyoushi Zenko extension. Chapters
are returned as plain paragraphs: no scripts, links, ads or site markup reach
the reader. Paid or draft chapters are skipped, never presented as readable.
"""
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
SOURCES = (('ranobehub', 'RanobeHub', 'ru'), ('zenko-novel', 'Zenko · UA', 'uk'), ('smakolyky', 'Смаколики · UA', 'uk'))
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


SEARCH = {'ranobehub': _hub_search, 'zenko-novel': _zenko_search, 'smakolyky': _smak_search}


def search(title, language='all'):
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
                for candidate in SEARCH[identity](query, http):
                    if any(r['url'] == candidate['url'] for r in results): continue
                    accepted, evidence = match_title(wanted, candidate)
                    if accepted: results.append({**candidate, 'kind': 'ranobe', 'matchEvidence': evidence})
                if results: break
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
    selected = parse_qs(parts.query).get('mv_chapter', [''])[0]
    if selected and not selected.isdigit(): raise SourceError('Некорректная ссылка на главу.')
    for identity, pattern, hosts in (('ranobehub', r'/ranobe/(\d{1,9})(?:-[^/]*)?/?', {'ranobehub.org'}),
                                     ('zenko-novel', r'/titles/(\d{1,9})/?', {'zenko.online'}),
                                     ('smakolyky', r'/projects/(\d{1,9})/?', {'smakolykytl.site'})):
        match = re.fullmatch(pattern, parts.path)
        if host in hosts and match and parts.scheme == 'https': return identity, match[1], selected
    raise SourceError('Эта ссылка не относится к поддерживаемому источнику ранобэ.')


def _chapter_url(identity, book, chapter):
    base = {'ranobehub': HUB + '/ranobe/', 'zenko-novel': ZENKO + '/titles/', 'smakolyky': SMAK + '/projects/'}[identity]
    return base + book + '?' + urlencode({'mv_chapter': chapter})


def inspect(url, http=None):
    """Book and its free chapter list (volume, number, title, url)."""
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
        else:
            data = _json(http, SMAK_API + '/chapters/' + selected).get('chapter') or {}
            title, paragraphs = data.get('title') or '', tiptap_paragraphs(data.get('content'))
        if not paragraphs: raise SourceError('Глава пуста или доступна только на сайте источника.')
        return {'provider': identity, 'url': url, 'title': ' '.join(str(title).split())[:200], 'language': 'ru' if identity == 'ranobehub' else 'uk',
                'paragraphs': paragraphs[:MAX_PARAGRAPHS]}
    finally:
        if own: http.close()
