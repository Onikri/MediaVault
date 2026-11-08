"""LostFilm's public series catalogue (titles, posters, years, genres).

Only the catalogue is read: LostFilm's own player requires the viewer's account,
so episodes play in the LostFilm dub that public players (Collaps, Alloha via
the Kinobox balancer) publish. No login, cookies or LostFilm media are used.
"""
import json
import re
import threading
import time

from fastapi import Depends, HTTPException
from source_parser import PublicHttp, SourceError

ROOT = 'https://www.lostfilm.tv'
SORTS = {'new': '3', 'alpha': '2', 'rating': '1'}
_cache = {}
_lock = threading.RLock()


def parse_rows(text):
    try:
        value = json.loads(text)
    except ValueError:
        raise SourceError('LostFilm вернул неизвестный формат каталога.') from None
    rows = value.get('data') if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raise SourceError('LostFilm вернул неизвестный формат каталога.')
    items = []
    for row in rows:
        if not isinstance(row, dict) or not row.get('title') or not row.get('alias'): continue
        alias = str(row['alias'])
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', alias): continue
        image = str(row.get('img') or '')
        year = re.search(r'(?:19|20)\d{2}', str(row.get('date') or ''))
        items.append({
            'id': 'lostfilm:' + alias, 'title': ' '.join(str(row['title']).split())[:200],
            'original': ' '.join(str(row.get('title_orig') or '').split())[:200],
            'year': int(year.group()) if year else None,
            'url': ROOT + '/series/' + alias + '/',
            'cover': ROOT + image if re.fullmatch(r'/Static/Images/\d+/Posters/[A-Za-z0-9_.-]+', image) else '',
            'genres': [g.strip() for g in str(row.get('genres') or '').split(',') if g.strip()][:6],
            'rating': row.get('rating') if isinstance(row.get('rating'), (int, float)) else None,
            'upcoming': bool(row.get('not_aired')),
        })
    return items


def catalog(sort='new', offset=0, http=None):
    sort = sort if sort in SORTS else 'new'
    offset = max(0, min(int(offset), 2000))
    key = (sort, offset)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.monotonic(): return hit[1]
    own = http is None
    http = http or PublicHttp(timeout=(4, 10), deadline=time.monotonic() + 20)
    try:
        text, _, _ = http.document(ROOT + '/ajaxik.php', method='POST',
                                   data={'act': 'serial', 'type': 'search', 'o': str(offset), 's': SORTS[sort], 't': '0'},
                                   headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': ROOT + '/series/'})
        value = {'items': parse_rows(text), 'sort': sort, 'offset': offset, 'source': 'LostFilm',
                 'note': 'Смотреть — в озвучке LostFilm через публичные плееры. Собственный плеер LostFilm требует их аккаунт.'}
    finally:
        if own: http.close()
    with _lock:
        if len(_cache) > 200: _cache.clear()
        _cache[key] = (time.monotonic() + 1800, value)
    return value


def install(app, viewer):
    @app.get('/catalog/lostfilm')
    def lostfilm(sort: str = 'new', offset: int = 0, subject=Depends(viewer)):
        try:
            return catalog(sort, offset)
        except SourceError as error:
            raise HTTPException(502, str(error)) from None
