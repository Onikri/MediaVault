"""HanimeTV catalogue search: the site's own public catalogue feed, grouped into series.

hanime.tv filters its catalogue in the browser from one JSON feed, so the server keeps
that feed cached and searches it. Each video is an episode ("Kotowari 1", "Kotowari 2");
episodes of one series are grouped by name without the trailing number.
"""
import difflib
import json
import re
import threading
import time

from source_parser import SourceError

CATALOG = 'https://guest.freeanimehentai.net/api/v11/search_hvs'
VIDEO = 'https://hanime.tv/videos/hentai/'
MAX_CATALOG = 10 * 1024 * 1024
TTL = 6 * 3600
# Series names must match closely: this source is only for titles that really are on it.
MIN_SCORE = 0.78

_cache = {'until': 0.0, 'rows': []}
_lock = threading.Lock()


def _normalize(value):
    return re.sub(r'[^\w]+', ' ', str(value or '').casefold()).strip()


def series_name(name):
    return re.sub(r'\s+(?:season\s+)?\d{1,3}$', '', str(name or '').strip(), flags=re.I)


def episode_number(name):
    match = re.search(r'\s(?:season\s+)?(\d{1,3})$', str(name or '').strip(), re.I)
    return int(match[1]) if match else 1


def load_catalog(http):
    with _lock:
        if _cache['rows'] and _cache['until'] > time.monotonic():
            return _cache['rows']
    response, _ = http._open(CATALOG, headers={'Origin': 'https://hanime.tv', 'Referer': 'https://hanime.tv/',
                                               'Accept': 'application/json'})
    try:
        parts, size = [], 0
        for block in response.iter_content(65536):
            size += len(block)
            if size > MAX_CATALOG:
                raise SourceError('Каталог HanimeTV слишком большой.')
            parts.append(block)
    finally:
        response.close()
    try:
        data = json.loads(b''.join(parts).decode('utf-8'))
        rows = [row for row in data['data'] if isinstance(row, dict) and row.get('slug') and row.get('name')]
    except (ValueError, KeyError, TypeError) as error:
        raise SourceError('HanimeTV вернул каталог в неожиданном формате.') from error
    with _lock:
        _cache.update(until=time.monotonic() + TTL, rows=rows)
    return rows


def group_series(rows):
    groups = {}
    for row in rows:
        groups.setdefault(series_name(row['name']), []).append(row)
    for name in groups:
        groups[name].sort(key=lambda row: episode_number(row['name']))
    return groups


def _score(query, name, titles):
    target, series = _normalize(query), _normalize(name)
    best = difflib.SequenceMatcher(None, target, series).ratio()
    # A full catalogue title ("Kuroinu: Kedakaki Seijo...") listed among the alternatives,
    # or a series name that the full title starts with ("Kuroinu").
    if len(target) >= 14 and re.search(r'(?:^| )' + re.escape(target) + r'(?: |$)', _normalize(titles)):
        best = max(best, .95)
    if len(series) >= 5 and (target + ' ').startswith(series + ' '):
        best = max(best, .9)
    # search_titles holds the English, Japanese and other alternative titles in one string.
    for chunk in re.split(r'\s{2,}|\s[-/|]\s', str(titles or '')):
        if chunk:
            best = max(best, difflib.SequenceMatcher(None, target, _normalize(series_name(chunk))).ratio())
    return best


def search(query, http, limit=8):
    rows = load_catalog(http)
    results = []
    for name, episodes in group_series(rows).items():
        score = _score(query, name, episodes[0].get('search_titles'))
        if score < MIN_SCORE:
            continue
        first = episodes[0]
        year = re.match(r'(\d{4})', str(first.get('released_at') or ''))
        results.append((score, {
            'provider': 'hanime', 'providerName': 'HanimeTV', 'url': VIDEO + first['slug'], 'title': name,
            'kind': 'anime', 'dubs': [], 'releaseDates': [], 'year': int(year[1]) if year else None,
            'cover': first.get('cover_url') or first.get('poster_url'), 'episodes': len(episodes),
        }))
    results.sort(key=lambda item: item[0], reverse=True)
    return [result for _, result in results[:limit]]


def episodes_for(url, http):
    slug = re.search(r'/videos/hentai/([^/?#]+)', url)
    if not slug:
        return []
    rows = load_catalog(http)
    current = next((row for row in rows if row['slug'] == slug[1]), None)
    if not current:
        return []
    series = group_series(rows).get(series_name(current['name']), [current])
    return [{'number': episode_number(row['name']), 'season': 1, 'url': VIDEO + row['slug'], 'title': row['name']}
            for row in series]
