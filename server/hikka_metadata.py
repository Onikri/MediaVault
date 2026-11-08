"""Ukrainian titles and synopses from Hikka (hikka.io) by MAL ID.

Used when the interface is Ukrainian. Only public catalogue data: the title,
the Ukrainian synopsis (markdown links reduced to their text) and the Hikka
page. Results are cached in memory for a day; a miss is cached for an hour.
"""
import json
import re
import threading
import time

from source_parser import PublicHttp, SourceError

API = 'https://api.hikka.io'
TYPES = {'anime': 'anime', 'tv': 'anime', 'movie': 'anime', 'manga': 'manga', 'ranobe': 'novel', 'novel': 'novel'}
_cache = {}
_lock = threading.RLock()


def clean_synopsis(text):
    value = str(text or '')
    value = re.sub(r'\n*\s*(?:Джерело|Source)\s*\[[^\]]*\]\([^)]*\)\s*$', '', value.strip())
    value = re.sub(r'\[([^\]]+)\]\((?:https?://)[^)]*\)', r'\1', value)
    value = re.sub(r'\*\*([^*]+)\*\*|__([^_]+)__', lambda m: m.group(1) or m.group(2), value)
    return re.sub(r'\n{3,}', '\n\n', value).strip()[:4000]


def ukrainian(kind, identity, http=None):
    content = TYPES.get(kind)
    if not content or not re.fullmatch(r'\d{1,9}', str(identity or '')): raise SourceError('Нужен MAL ID аниме, манги или ранобэ.')
    key = (content, str(identity))
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.monotonic(): return hit[1]
    own = http is None
    http = http or PublicHttp(timeout=(3, 8), deadline=time.monotonic() + 15)
    value = None
    try:
        text, _, _ = http.document(API + '/integrations/mal/' + content + '/' + str(identity), headers={'Accept': 'application/json'})
        item = json.loads(text)
        slug = str(item.get('slug') or '')
        if re.fullmatch(r'[a-z0-9-]{1,120}', slug) and item.get('title_ua'):
            detail = json.loads(http.document(API + '/' + content + '/' + slug, headers={'Accept': 'application/json'})[0])
            value = {'title': ' '.join(str(item['title_ua']).split())[:300], 'description': clean_synopsis(detail.get('synopsis_ua')),
                     'url': 'https://hikka.io/' + content + '/' + slug, 'translatedUa': bool(detail.get('translated_ua'))}
    except (SourceError, ValueError, AttributeError, TypeError):
        value = None
    finally:
        if own: http.close()
    with _lock:
        if len(_cache) > 4000: _cache.clear()
        _cache[key] = (time.monotonic() + (86400 if value else 3600), value)
    return value


def install(app):
    @app.get('/metadata/hikka')
    def hikka(kind: str = 'anime', identity: str = ''):
        try:
            return {'kind': kind, 'identity': identity, 'value': ukrainian(kind, identity)}
        except SourceError as error:
            from fastapi import HTTPException
            raise HTTPException(422, str(error)) from None
