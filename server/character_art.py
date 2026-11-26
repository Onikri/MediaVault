"""Character portraits from every catalogue that knows the title. Never a guess.

Shikimori stays first. A character without a real Shikimori picture takes one
from another catalogue, with one request set per title (not per character):
  1. MyAnimeList through Jikan (by the title's MAL id, which is Shikimori's id).
     MAL shares Shikimori's character ids, so the exact id is used; otherwise an
     exact normalised name with the same role, unique inside that title.
  2. AniList, one GraphQL query by the title's MAL id: an exact normalised full,
     native or alternative name, unique inside that title on both sides.
  3. Kitsu, mapped from the title's MAL id: the character's own MAL id.
Placeholders of every catalogue (missing_*, questionmark, default, no-poster …)
count as no picture. A name never matches across titles: candidates only ever
come from the same title's cast list.

Films and series: an actor Wikidata has no photo for takes Kinopoisk's photo by
the actor's exact Kinopoisk person id (Wikidata P2604), verified by its redirect.
"""
from collections import OrderedDict
import re
import threading
import time
import unicodedata
from urllib.parse import urljoin, urlsplit

from metadata_catalog import metadata, get_json
from source_parser import SourceError

LIMIT = 40
SHOWN = 18  # a title page shows the first 18 characters, main ones first
PLACEHOLDER = re.compile(r'(?:^|/)(?:missing|questionmark|default|no[_-]?(?:image|photo|poster|picture|avatar)|noimage|nopicture|placeholder|blank|404)(?:[._/-][^/]*)?$|/missing/', re.I)
ANILIST_QUERY = ('query($id:Int,$type:MediaType){Media(idMal:$id,type:$type){id idMal characters(perPage:50,sort:[ROLE,RELEVANCE,ID])'
                 '{edges{role node{id name{full native alternative} image{large}}}}}}')
_cache, _pending, _lock = OrderedDict(), {}, threading.RLock()


def placeholder(url):
    return bool(url) and bool(PLACEHOLDER.search(urlsplit(str(url)).path))


def real(url, base='https://shikimori.io'):
    """A picture the artwork proxy serves, or '' for empty, placeholder or foreign hosts."""
    if not url or not isinstance(url, str):
        return ''
    value = urljoin(base, url) if url.startswith('/') else url
    if not value.startswith('https://') or placeholder(value):
        return ''
    from artwork import allowed
    return value if allowed(value) else ''


def name_key(value):
    """Order-free name key: «Kamado, Tanjirou» = «Tanjirō Kamado» = «tanjiro kamado»."""
    text = unicodedata.normalize('NFKD', unicodedata.normalize('NFKC', str(value or '')).casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    tokens = []
    for token in re.split(r'[\W_]+', text):
        if token:
            tokens.append(re.sub('oo', 'o', re.sub('ou', 'o', re.sub('uu', 'u', token))))
    key = ' '.join(sorted(tokens))
    return key if len(key.replace(' ', '')) >= 2 and not key.replace(' ', '').isdigit() else ''


def _remember(key, loader, ttl=21600):
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        waiting = _pending.get(key)
        leader = waiting is None
        if leader:
            waiting = _pending[key] = threading.Event()
    if not leader:
        waiting.wait(20)
        with _lock:
            hit = _cache.get(key)
        if hit:
            return hit[1]
        raise SourceError('Каталог персонажей ещё отвечает.')
    try:
        value = loader()
        with _lock:
            _cache[key] = (time.monotonic() + ttl, value)
            _cache.move_to_end(key)
            while len(_cache) > 512:
                _cache.popitem(last=False)
        return value
    finally:
        with _lock:
            _pending.pop(key, None)
        waiting.set()


def _media(kind):
    return 'anime' if kind == 'anime' else 'manga'


def _jikan(kind, identity):
    from jikan_metadata import jikan_json
    rows = jikan_json(_media(kind) + '/' + identity + '/characters').get('data') or []
    out = []
    for row in rows:
        character = row.get('character') or {}
        if not character.get('mal_id'):
            continue
        images = character.get('images') or {}
        out.append({'id': str(character['mal_id']), 'names': [character.get('name')], 'main': row.get('role') == 'Main',
                    'image': real((images.get('jpg') or {}).get('image_url') or (images.get('webp') or {}).get('image_url'))})
    return out


def _anilist(kind, identity):
    body = {'query': ANILIST_QUERY, 'variables': {'id': int(identity), 'type': 'ANIME' if kind == 'anime' else 'MANGA'}}
    media = ((get_json('https://graphql.anilist.co', body=body) or {}).get('data') or {}).get('Media') or {}
    if str(media.get('idMal') or '') != identity:
        return []  # AniList answered for another title: nothing from it may be used.
    out = []
    for edge in (media.get('characters') or {}).get('edges') or []:
        node = edge.get('node') or {}
        name = node.get('name') or {}
        out.append({'id': None, 'names': [name.get('full'), name.get('native'), *(name.get('alternative') or [])], 'main': edge.get('role') == 'MAIN',
                    'image': real((node.get('image') or {}).get('large'))})
    return out


def _kitsu(kind, identity):
    media = _media(kind)
    mapping = get_json('https://kitsu.io/api/edge/mappings', params={'filter[externalSite]': 'myanimelist/' + media, 'filter[externalId]': identity, 'include': 'item'})
    item = next((value for value in mapping.get('included') or [] if value.get('type') == media and value.get('id')), None)
    if not item or not re.fullmatch(r'\d{1,12}', str(item['id'])):
        return []
    cast = get_json(f"https://kitsu.io/api/edge/{media}/{item['id']}/characters", params={'include': 'character', 'page[limit]': 20})
    out = []
    for value in cast.get('included') or []:
        attributes = value.get('attributes') or {}
        if value.get('type') == 'characters' and attributes.get('malId'):
            out.append({'id': str(attributes['malId']), 'names': [], 'main': None, 'image': real((attributes.get('image') or {}).get('original'))})
    return out


SOURCES = (('myanimelist', _jikan, True, True), ('anilist', _anilist, False, False), ('kitsu', _kitsu, True, None))


def _unique(entries):
    """name key -> the single entry carrying it (keys shared by two entries are dropped)."""
    seen, out = set(), {}
    for entry in entries:
        for key in {name_key(name) for name in entry.get('names') or [] if name} - {''}:
            if key in seen:
                out.pop(key, None)
            else:
                seen.add(key)
                out[key] = entry
    return out


def match(wanted, cast, candidates, *, by_id=True, role=False):
    """{character id: image} for wanted characters, from one source's candidates
    of the same title. cast is the whole title cast (for name uniqueness)."""
    found, used = {}, set()
    by_identity = {c['id']: c for c in candidates if c.get('id')} if by_id else {}
    for entry in wanted:
        candidate = by_identity.get(entry['id'])
        if candidate is not None:
            used.add(id(candidate))
            if candidate['image']:
                found[entry['id']] = (candidate['image'], 'id')
    names, ours = _unique(candidates), _unique(cast)
    for entry in wanted:
        if entry['id'] in found or (by_id and entry['id'] in by_identity):
            continue
        for key in {name_key(name) for name in entry.get('names') or [] if name} - {''}:
            candidate = names.get(key)
            if candidate is None or ours.get(key) is not entry or id(candidate) in used or not candidate['image']:
                continue
            if role and candidate.get('main') is not None and entry.get('main') is not None and candidate['main'] != entry['main']:
                continue
            used.add(id(candidate))
            found[entry['id']] = (candidate['image'], 'name')
            break
    return found


def cast_from_roles(roles):
    """Shikimori roles in the order a title page shows them (main characters first)."""
    rows = [r for r in roles or [] if isinstance(r, dict) and isinstance(r.get('character'), dict) and r['character'].get('id')]
    rows.sort(key=lambda r: 0 if 'Main' in (r.get('roles') or []) else 1)
    out = []
    for row in rows:
        character = row['character']
        image = character.get('image') or {}
        out.append({'id': str(character['id']), 'names': [character.get('name')], 'main': 'Main' in (row.get('roles') or []),
                    'image': real(image.get('original') or image.get('preview'))})
    return out


def portraits(kind, identity, ids=None, roles=None):
    """{'portraits': {id: {image, source, match}}, 'missing': [ids]} for the title's
    characters without a real Shikimori picture (or the requested ids)."""
    identity = str(identity or '')
    if kind not in {'anime', 'manga', 'ranobe'} or not re.fullmatch(r'[1-9]\d{0,11}', identity):
        raise SourceError('Некорректный тайтл.')
    requested = [str(v) for v in (ids or []) if re.fullmatch(r'[1-9]\d{0,11}', str(v))][:LIMIT]
    if roles is None:
        try:
            roles = metadata('shikimori', kind=_media(kind), identity=identity, part='roles')
        except SourceError:
            roles = []
    cast = cast_from_roles(roles)
    known = {entry['id']: entry for entry in cast}
    result = {}
    if requested:
        # A saved profile may hold an old placeholder that Shikimori has since replaced.
        wanted = [known.get(v) or {'id': v, 'names': [], 'main': None, 'image': ''} for v in dict.fromkeys(requested)]
        for entry in wanted:
            if entry['image']:
                result[entry['id']] = {'image': entry['image'], 'source': 'shikimori', 'match': 'id'}
    else:
        wanted = [entry for entry in cast[:SHOWN] if not entry['image']]
    for source, loader, by_id, role in SOURCES:
        rest = [entry for entry in wanted if entry['id'] not in result]
        if not rest:
            break
        try:
            candidates = _remember((source, _media(kind), identity), lambda: loader(kind, identity))
        except (SourceError, ValueError, TypeError, KeyError):
            continue
        for character, (image, how) in match(rest, cast, candidates, by_id=by_id, role=bool(role)).items():
            result[character] = {'image': image, 'source': source, 'match': how}
    return {'portraits': result, 'missing': [entry['id'] for entry in wanted if entry['id'] not in result]}


def fill(characters, kind, identity, roles=None):
    """Fill empty portraits of profile characters in place; returns them."""
    missing = [c for c in characters or [] if not real(c.get('image') or '')]
    if not missing:
        return characters
    try:
        found = portraits(kind, identity, [c.get('id') for c in missing], roles)['portraits']
    except SourceError:
        return characters
    for character in missing:
        hit = found.get(str(character.get('id')))
        character['image'] = hit['image'] if hit else ''
    return characters


KINOPOISK_PHOTO = 'https://st.kp.yandex.net/images/actor_iphone/iphone360_{}.jpg'
KINOPOISK_IMAGE = 'https://avatars.mds.yandex.net/get-kinopoisk-image/'


def _kinopoisk_photo(identity):
    import requests
    from metadata_catalog import USER_AGENT
    try:
        with requests.Session() as session:
            response = session.head(KINOPOISK_PHOTO.format(identity), allow_redirects=False, timeout=(3, 5), headers={'User-Agent': USER_AGENT})
            location = response.headers.get('Location', '') if response.status_code in {301, 302, 303, 307, 308} else ''
    except requests.RequestException:
        raise SourceError('Кинопоиск сейчас не отвечает.') from None
    # A person without a photo redirects to /images/no-poster.gif.
    return location if location.startswith(KINOPOISK_IMAGE) and re.fullmatch(r'/get-kinopoisk-image/[\w-]+/[\w-]+/\d+', urlsplit(location).path) else ''


def kinopoisk_photos(ids, budget=6.0):
    """{Kinopoisk person id: photo URL} for people Kinopoisk has a real photo of."""
    values = [str(v) for v in ids or [] if re.fullmatch(r'[1-9]\d{0,9}', str(v))]
    values = list(dict.fromkeys(values))[:24]
    deadline, out = time.monotonic() + budget, {}
    for index, identity in enumerate(values):
        with _lock:
            hit = _cache.get(('kinopoisk', identity))
        if not (hit and hit[0] > time.monotonic()):
            if time.monotonic() > deadline:
                break
            if index:
                time.sleep(.12)
        try:
            url = _remember(('kinopoisk', identity), lambda: _kinopoisk_photo(identity), ttl=7 * 86400)
        except SourceError:
            break
        if url:
            out[identity] = url
    return out


def install(app):
    from fastapi import HTTPException

    @app.get('/metadata/character-art/{kind}/{identity}')
    def character_art(kind: str, identity: str, ids: str = ''):
        if len(ids) > 600:
            raise HTTPException(422, 'Слишком много персонажей.')
        try:
            return portraits(kind, identity, [v for v in ids.split(',') if v])
        except SourceError as error:
            raise HTTPException(422, str(error)) from None

    @app.get('/metadata/person-photos/kinopoisk')
    def person_photos(ids: str = ''):
        if len(ids) > 300:
            raise HTTPException(422, 'Слишком много участников.')
        return kinopoisk_photos(ids.split(','))
