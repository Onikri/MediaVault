"""Token-free film/serial players for an exact IMDb or Kinopoisk ID.

The public Kinobox player balancer (the JSON that site widgets call) lists the
players that host a title: Alloha and Collaps with their dub names (LostFilm,
Ukrainian studios, authors). Only Alloha and Collaps are expanded: both already
play through the VM. Other players in the answer are reported as unsupported,
never guessed. No API keys are used.
"""
import hashlib
import json
import re
import threading
import time
from urllib.parse import urlencode

from source_parser import PublicHttp, SourceError, SourceRateLimitError, public_url, is_alloha_player

API = 'https://fbphdplay.top/api/players'
SEARCH = 'https://fbphdplay.top/api/movies/search'
_cache = {}
_lock = threading.RLock()
_api_lock = threading.Lock()
_retry_at = 0.0


def _ids(selected):
    ids = selected.get('ids') or {}
    imdb = str(ids.get('imdb') or '').strip()
    kinopoisk = str(ids.get('kinopoisk') or ids.get('kp') or '').strip()
    query = {}
    if re.fullmatch(r'tt\d{5,10}', imdb): query['imdb'] = imdb
    if re.fullmatch(r'\d{1,9}', kinopoisk): query['kinopoisk'] = kinopoisk
    return query


def _search(query, http):
    global _retry_at
    with _api_lock:
        if _retry_at > time.monotonic():
            raise SourceError('Балансер Kinobox временно ограничил запросы. Проверяем другие источники.')
        try:
            text, _, _ = http.document(SEARCH + '?' + urlencode({'query': query}), headers={'Accept': 'application/json'})
        except SourceRateLimitError as error:
            _retry_at = time.monotonic() + error.retry_after
            raise
    try:
        rows = (json.loads(text).get('data') or {}).get('items')
    except (ValueError, AttributeError):
        raise SourceError('Каталог Kinobox вернул неизвестный формат.') from None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def anime_kinopoisk(selected, http):
    """Kinopoisk ID for a MAL/Shikimori anime card, only on an unambiguous match.

    Anime cards carry no IMDb/Kinopoisk ID, so Kinobox (Collaps, Alloha) would
    never be asked. A Kinobox search hit counts only when it is marked «аниме»,
    started the same year, has the same film/series type and one of its titles
    equals one of the card's titles. Two different hits mean no ID at all.
    """
    from title_identity import aliases, normalized
    names = aliases(selected)
    wanted = {normalized(name) for name in names if len(normalized(name)) >= 2}
    year = str(selected.get('year') or selected.get('startDate') or '')[:4]
    if not wanted or not re.fullmatch(r'(?:19|20)\d\d', year):
        return None
    form = str(selected.get('format') or '').casefold()
    kind = 'Film' if re.search(r'movie|фильм', form) else None if not form else 'Series'
    queries = [next((n for n in names if re.search('[А-Яа-яЁё]', n)), None), next((n for n in names if re.search('[A-Za-z]', n)), None)]
    found = {}
    for query in dict.fromkeys(q for q in queries if q):
        for row in _search(query[:160], http):
            titles = row.get('title') or {}
            genres = {str(g.get('name') or '').casefold() for g in row.get('genres') or [] if isinstance(g, dict)}
            if ('аниме' in genres and str(row.get('year') or '') == year and (kind is None or row.get('type') == kind)
                    and re.fullmatch(r'\d{1,12}', str(row.get('id') or ''))
                    and {normalized(titles.get('russian')), normalized(titles.get('original'))} & wanted):
                found[str(row['id'])] = row
        if found:
            break
    return next(iter(found)) if len(found) == 1 else None


def players(selected, http):
    global _retry_at
    query = _ids(selected)
    if not query: return None
    with _api_lock:
        if _retry_at > time.monotonic():
            raise SourceError('Балансер Kinobox временно ограничил запросы. Проверяем другие источники.')
        try:
            text, _, _ = http.document(API + '?' + urlencode(query), headers={'Accept': 'application/json'})
        except SourceRateLimitError as error:
            _retry_at = time.monotonic() + error.retry_after
            raise
    try:
        value = json.loads(text)
    except ValueError:
        raise SourceError('Балансер плееров вернул неизвестный формат.') from None
    rows = value.get('data') if isinstance(value, dict) else None
    if not isinstance(rows, list): raise SourceError('Балансер плееров вернул неизвестный формат.')
    return [r for r in rows if isinstance(r, dict)]


def _movie_alloha(row):
    from player_catalog import alloha_voice_language, choice
    result = []
    for item in row.get('translations') or []:
        if not isinstance(item, dict) or not item.get('name') or not item.get('iframeUrl'): continue
        name = ' '.join(str(item['name']).split())[:120]
        language = alloha_voice_language(name)
        try:
            url = public_url(item['iframeUrl'], resolve_dns=False)
        except SourceError:
            continue
        result.append(choice(name, url, identity='alloha:' + str(item.get('id') or name), player='Alloha', language=language,
                             kind='subtitles' if re.search(r'субтит', name, re.I) else '',
                             episodes=[{'number': 1, 'season': 1, 'url': url, 'title': 'Фильм'}]))
    return result


def inspect_player(row, kind, http):
    """Dubs and episodes of one balancer player, or None when it is unsupported."""
    from ua_players import collaps_choices, is_collaps
    from player_catalog import alloha_choices
    kind_name = str(row.get('type') or '')
    try:
        iframe = public_url(str(row.get('iframeUrl') or ''), resolve_dns=False)
    except SourceError:
        return None
    if kind_name.casefold() == 'collaps' and is_collaps(iframe):
        text, final, _ = http.document(iframe, headers={'Referer': iframe})
        return {'url': iframe, 'player': 'Collaps', 'dubs': collaps_choices(iframe, text)}
    if kind_name.casefold() == 'alloha' and is_alloha_player(iframe):
        if kind == 'movie':
            return {'url': iframe, 'player': 'Alloha', 'dubs': _movie_alloha(row)}
        text, final, _ = http.document(iframe, headers={'Referer': iframe})
        dubs, seasons = alloha_choices(text, final)
        return {'url': iframe, 'player': 'Alloha', 'dubs': dubs, 'seasons': seasons}
    return None


def aliases_key(selected):
    from title_identity import aliases
    return tuple(aliases(selected))


def discover(selected):
    name = 'Kinobox · Alloha, Collaps'
    kind = selected.get('kind', 'anime')
    if not _ids(selected) and kind == 'anime':
        signature = hashlib.sha256(repr(('anime-kp', aliases_key(selected), selected.get('year'), selected.get('format'))).encode()).hexdigest()
        with _lock:
            cached = _cache.get(signature)
        if cached and cached[0] > time.monotonic():
            kinopoisk = cached[1]
        else:
            http = PublicHttp(timeout=(3, 8), deadline=time.monotonic() + 15)
            try:
                kinopoisk = anime_kinopoisk(selected, http)
            except (SourceError, OSError):
                kinopoisk = None
            finally:
                http.close()
            with _lock:
                if len(_cache) >= 100: _cache.pop(next(iter(_cache)))
                _cache[signature] = (time.monotonic() + (86400 if kinopoisk else 3600), kinopoisk)
        if kinopoisk:
            selected = {**selected, 'ids': {**(selected.get('ids') or {}), 'kinopoisk': kinopoisk}}
    if not _ids(selected):
        return {'provider': 'kinobox', 'name': name, 'status': 'no_match', 'message': 'Нужен точный ID IMDb или Кинопоиска.', 'sources': [], 'complete': True}
    signature = hashlib.sha256(repr((_ids(selected), kind)).encode()).hexdigest()
    with _lock:
        cached = _cache.get(signature)
        if cached and cached[0] > time.monotonic(): return cached[1]
    http = PublicHttp(timeout=(3, 8), deadline=time.monotonic() + 25)
    try:
        rows = players(selected, http) or []
        sources, unsupported = [], []
        for row in rows:
            try:
                found = inspect_player(row, kind, http)
            except SourceError:
                found = None
            if not found:
                unsupported.append(str(row.get('type') or 'плеер'))
                continue
            if not found['dubs']: continue
            episodes = [e for dub in found['dubs'] for e in dub.get('episodes', [])]
            sources.append({'url': found['url'], 'title': selected.get('title') or '', 'kind': kind, 'provider': 'kinobox',
                            'providerName': found['player'] + ' · Kinobox', 'ids': selected.get('ids') or {},
                            'dubs': found['dubs'], 'episodes': episodes[:1] if kind == 'movie' else [],
                            'seasons': found.get('seasons') or [], 'complete': True, 'pending': False, 'scannedPages': 1})
        # Alloha plays through browser profiles with a use limit; when all are
        # spent it refuses every title, so its voices are not offered then.
        from alloha_profiles import playback_available
        paused = not playback_available() and any(is_alloha_player(s['url']) for s in sources)
        if paused: sources = [s for s in sources if not is_alloha_player(s['url'])]
        # Collaps plays over plain HTTP: offer it first.
        sources.sort(key=lambda s: 0 if s['providerName'].startswith('Collaps') else 1)
        count = sum(len(s['dubs']) for s in sources)
        message = ('Найдено озвучек: ' + str(count) + '. ' if count else 'Поддерживаемых плееров для этого ID нет. ') + \
                  ('Плееры без поддержки: ' + ', '.join(sorted(set(unsupported))) + '. ' if unsupported else '') + \
                  ('Alloha временно недоступна: исчерпан лимит браузерных профилей.' if paused else '')
        value = {'provider': 'kinobox', 'name': name, 'status': 'ok' if count else 'no_players' if rows else 'no_match',
                 'message': message.strip(), 'sources': sources, 'complete': True}
    except (SourceError, OSError) as error:
        value = {'provider': 'kinobox', 'name': name, 'status': 'unavailable', 'message': str(error) or 'Балансер плееров временно недоступен.', 'sources': [], 'complete': False}
    finally:
        http.close()
    with _lock:
        if len(_cache) >= 100: _cache.pop(next(iter(_cache)))
        _cache[signature] = (time.monotonic() + (600 if value['sources'] else 60), value)
    return value
