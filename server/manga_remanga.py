"""ReManga public JSON API: search, translator branches and free chapter pages.

The site's HTML front is behind a CAPTCHA, and its Suwayomi extension is no
longer published, but api.remanga.org serves the same public catalogue to
anonymous readers. Paid and unpublished chapters are skipped, never bypassed.
"""
import json
import re
from urllib.parse import quote, unquote, urlencode, urlsplit

from source_parser import SourceError, public_url

ROOT = 'https://remanga.org'
API = 'https://api.remanga.org'
SOURCE = {'id': '990000000000000020', 'name': 'ReManga', 'lang': 'ru', 'baseUrl': ROOT, 'isNsfw': False}
HOSTS = {'remanga.org', 'api.remanga.org'}
TITLE = re.compile(r'/manga/([^/]{1,200})/?')
CHAPTER = re.compile(r'/manga/([^/]{1,200})/ch([1-9]\d{0,11})/?')
FORMATS = {'манга': 'manga', 'манхва': 'manhwa', 'маньхуа': 'manhua', 'западный комикс': 'manga', 'рукомикс': 'manga', 'индонезийский комикс': 'manga'}
MAX_CHAPTER_REQUESTS = 30


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:500]


def api(path, http, **params):
    url = API + path + ('?' + urlencode(params, doseq=True) if params else '')
    text, final, _ = http.document(public_url(url, resolve_dns=False), headers={'Accept': 'application/json'})
    if urlsplit(final).hostname != 'api.remanga.org':
        raise SourceError('ReManga перенаправил запрос на другой сайт.')
    try:
        return json.loads(text)
    except ValueError:
        raise SourceError('ReManga вернул ответ не в формате каталога.') from None


def media(path):
    if not isinstance(path, str) or not path.startswith('/media/'):
        return ''
    try:
        return public_url(API + path, resolve_dns=False)
    except SourceError:
        return ''


def title_url(directory):
    return ROOT + '/manga/' + quote(directory, safe='')


def names(row):
    values = [row.get('main_name'), row.get('secondary_name')]
    values += [v for v in re.split(r'\s+/\s+', str(row.get('another_name') or '')) if len(v.strip()) > 1]
    return list(dict.fromkeys(clean(v) for v in values if clean(v)))[:40]


def kind(row):
    return FORMATS.get(str((row.get('type') or {}).get('name') or '').casefold(), 'manga')


def labels(values):
    return [clean(v.get('name')) for v in values or [] if isinstance(v, dict) and clean(v.get('name'))][:80]


def card(row):
    directory = row.get('dir')
    titles=names(row)
    if not isinstance(directory, str) or not directory.strip() or not titles:
        return None
    url = title_url(directory)
    cover = (row.get('cover') or {}) if isinstance(row.get('cover'), dict) else {}
    adult = bool(row.get('is_erotic') or row.get('is_yaoi'))
    return {'id': 'remanga:' + str(row.get('id') or directory), 'provider': 'remanga', 'providerName': 'ReManga',
            'sourceId': SOURCE['id'], 'sourceOnly': True, 'url': url, 'sourceUrl': url, 'sourceURL': url,
            'title': titles[0], 'aliases': titles, 'kind': 'manga', 'format': kind(row),
            'language': 'ru', 'year': row.get('issue_year') if isinstance(row.get('issue_year'), int) else None,
            'cover': media(cover.get('mid') or cover.get('high') or cover.get('low')), 'ids': {},
            'adult': adult, **({'age': 18} if adult else {}),
            'genres': labels(row.get('genres')), 'tags': labels(row.get('categories')),
            'chapterCount': row.get('count_chapters') if isinstance(row.get('count_chapters'), int) else None}


def search(query, http):
    query = clean(query)[:160]
    if len(query) < 2:
        return []
    data = api('/api/v2/search/', http, query=query, count=30)
    return [value for row in data.get('results') or [] if isinstance(row, dict) and (value := card(row))]


def catalogue_page(page, http, genre=None, category=None):
    """One page of the public catalogue for metadata indexing (no chapters)."""
    params = {'page': page, 'count': 30, 'ordering': '-id'}
    if genre:
        params['genres'] = genre
    if category:
        params['categories'] = category
    data = api('/api/v2/search/catalog/', http, **params)
    if not isinstance(data.get('results'),list) or 'next' not in data:
        raise SourceError('ReManga не предоставил пагинацию каталога.')
    rows = [value for row in data.get('results') or [] if isinstance(row, dict) and (value := card(row))]
    if len(rows)!=len(data['results']) or not rows and (page==1 or data.get('next')):
        raise SourceError('ReManga вернул неполную страницу каталога.')
    return {'rows': rows, 'next': {'page': page + 1} if data.get('next') and rows else None}


def vocabulary(http):
    """Genre and category names with their catalogue filter ids."""
    data = api('/api/forms/titles/', http, get=['genres', 'categories'])
    content = data.get('content') or {}
    result = []
    for field, category in (('genres', 'genre'), ('categories', 'tag')):
        for row in content.get(field) or []:
            if isinstance(row, dict) and isinstance(row.get('id'), int) and clean(row.get('name')):
                result.append({'label': clean(row['name']), 'category': category, 'sourceId': row['id']})
    return result


def chapter_entry(directory, row, team):
    from manga_sources import chapter_number
    number = chapter_number(str(row.get('chapter') or '').replace(',', '.')) if re.fullmatch(r'\d{1,5}(?:[.,]\d{1,3})?', str(row.get('chapter') or '')) else None
    if number is None:
        return None
    volume = row.get('tome') if isinstance(row.get('tome'), int) and row.get('tome') > 0 else 1
    name = clean(row.get('name'))
    return {'number': number, 'season': volume, 'url': title_url(directory) + '/ch' + str(row['id']),
            'title': 'Глава ' + str(row.get('chapter')) + (': ' + name if name else ''), 'translator': team, 'language': 'ru'}


def chapters(directory, branches, http):
    found, requests, truncated = [], 0, False
    ordered = sorted((b for b in branches or [] if isinstance(b, dict) and isinstance(b.get('id'), int)),
                     key=lambda b: -(b.get('count_chapters') or 0))
    for branch in ordered:
        team = ', '.join(clean(p.get('name')) for p in branch.get('publishers') or [] if isinstance(p, dict) and clean(p.get('name')))
        page = 1
        while True:
            if requests >= MAX_CHAPTER_REQUESTS:
                return found, True
            data = api('/api/v2/titles/chapters/', http, branch_id=branch['id'], page=page, count=50, ordering='index')
            requests += 1
            for row in data.get('results') or []:
                if not isinstance(row, dict) or not isinstance(row.get('id'), int):
                    continue
                # A paid chapter is not readable without a purchase; never bypass it.
                if row.get('is_paid') or row.get('is_published') is False:
                    continue
                if entry := chapter_entry(directory, row, team):
                    found.append(entry)
            if not data.get('next'):
                break
            page += 1
    return found, truncated


def pages(chapter, http):
    data = api('/api/v2/titles/chapters/' + chapter + '/', http)
    if data.get('is_paid') and not data.get('is_bought'):
        raise SourceError('Эта глава ReManga платная. Выбери бесплатную главу.')
    result = []
    for group in data.get('pages') or []:
        for piece in group if isinstance(group, list) else [group]:
            link = piece.get('link') if isinstance(piece, dict) else None
            try:
                url = public_url(link, resolve_dns=False)
            except SourceError:
                continue
            if re.search(r'\.(?:jpe?g|png|webp|gif|avif)$', urlsplit(url).path, re.I) and url not in result:
                result.append(url)
    if not result or len(result) > 500:
        raise SourceError('ReManga не предоставил страницы этой главы.')
    return result


def inspect(url, http):
    parts = urlsplit(public_url(url, resolve_dns=False))
    if parts.hostname not in HOSTS:
        raise SourceError('Выбери мангу или главу ReManga.')
    reader = CHAPTER.fullmatch(parts.path)
    match = reader or TITLE.fullmatch(parts.path)
    if not match:
        raise SourceError('Выбери мангу или главу ReManga.')
    directory = unquote(match[1])
    detail = api('/api/v2/titles/' + quote(directory, safe='') + '/', http)
    value = card(detail)
    if not value:
        raise SourceError('ReManga не нашёл эту мангу.')
    page_list, entries, truncated = [], [], False
    if reader:
        page_list = pages(reader[2], http)
        entries = [{'number': 1, 'season': 1, 'url': title_url(directory) + '/ch' + reader[2], 'title': value['title'], 'translator': '', 'language': 'ru'}]
    else:
        entries, truncated = chapters(directory, detail.get('branches'), http)
    entries = sorted({e['url']: e for e in entries}.values(), key=lambda e: (e['season'], e['number'], e['translator']))
    return {**value, 'description': clean(re.sub(r'<[^>]+>', ' ', str(detail.get('description') or '')))[:500],
            'episodes': entries, 'pages': page_list, 'available': bool(entries), 'truncated': truncated,
            'seasons': [{'number': n, 'name': 'Том ' + str(n)} for n in sorted({e['season'] for e in entries})],
            'translations': sorted({e['translator'] for e in entries if e['translator']}), 'dubs': [], 'releases': []}
