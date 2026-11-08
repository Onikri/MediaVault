"""Public Playerjs players used by Ukrainian sites (Ashdi, HDVB-UA, Tortuga) and
the Collaps balancer player.

Playerjs publishes either one HLS file (films) or a playlist
`[{title: voice, folder: [{title: season, folder: [{title: episode, file}]}]}]`.
Collaps publishes one HLS master with every dub as an audio rendition, named in
the order of `audio.names`. Episode links stored in discovery are the public
embed URL plus mv_* selectors; signed media URLs are re-read at playback time
and never stored.
"""
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PLAYERJS_HOSTS = ('ashdi.vip', 'hdvbua.pro', 'tortuga.tw', 'tortuga.wtf')
COLLAPS_HOSTS = ('api.nextembed.ws', 'api.bhcesh.me', 'api.namy.ws', 'api.delivembd.ws')
SELECTORS = ('mv_voice', 'mv_season', 'mv_episode', 'mv_audio')


def _host_in(url, hosts):
    host = (urlsplit(url).hostname or '').lower()
    return any(host == h or host.endswith('.' + h) for h in hosts)


def is_playerjs(url):
    parts = urlsplit(url)
    trailer = dict(parse_qsl(parts.query)).get('tr') == '1'  # HDVB-UA trailers reuse /vid/
    return _host_in(url, PLAYERJS_HOSTS) and not trailer and bool(re.match(r'^/(?:vod|serial|embd|embed|vid|video)/', parts.path))


def is_ua_trailer(url):
    """Trailer iframes on the same player hosts are not episodes."""
    return _host_in(url, PLAYERJS_HOSTS) and not is_playerjs(url)


def is_collaps(url):
    return _host_in(url, COLLAPS_HOSTS) and urlsplit(url).path.startswith('/embed/')


def player_label(url):
    host = (urlsplit(url).hostname or '').lower()
    if 'ashdi' in host: return 'Ashdi'
    if 'hdvbua' in host: return 'HDVB UA'
    if 'tortuga' in host: return 'Tortuga'
    if _host_in(url, COLLAPS_HOSTS): return 'Collaps'
    return host


def selector_url(base, **values):
    parts = urlsplit(base)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in SELECTORS]
    query += [(k, str(v)) for k, v in values.items() if v is not None]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))


def split_selectors(url):
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query)
    chosen = {k: v for k, v in pairs if k in SELECTORS}
    clean = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode([(k, v) for k, v in pairs if k not in SELECTORS]), ''))
    return clean, chosen


def _number(text):
    match = re.search(r'\d+(?:[.,]\d+)?', str(text or ''))
    if not match: return None
    value = float(match.group().replace(',', '.'))
    return int(value) if value.is_integer() else value


def playerjs_file(text):
    """Return the published `file` value: an HLS URL string or a playlist list."""
    match = re.search(r'''\bfile\s*:\s*(['"])(.*?)\1\s*[,}\n]''', text, re.S)
    if not match: return None
    raw = match.group(2).strip()
    if raw.startswith('['):
        for candidate in (raw, raw.replace("\\'", "'"), bytes(raw, 'utf-8').decode('unicode_escape', 'ignore') if '\\u' in raw else raw):
            try:
                value = json.loads(candidate)
                if isinstance(value, list): return value
            except ValueError:
                continue
        return None
    return raw.replace('\\/', '/')


def _clean_media(url):
    url = str(url or '').strip()
    # Playerjs may list qualities as "[720p]https://…,[1080p]https://…"; take the last.
    if url.startswith('['):
        found = re.findall(r'\[[^\]]*\](https?://[^,\s]+)', url)
        url = found[-1] if found else ''
    return url if url.startswith('https://') else ''


def playerjs_entries(text):
    """Flatten a Playerjs page into [{voice, season, episode, title, file, poster}]."""
    value = playerjs_file(text)
    if isinstance(value, str):
        media = _clean_media(value)
        return [{'voice': '', 'season': 1, 'episode': 1, 'title': 'Фильм', 'file': media, 'poster': ''}] if media else []
    rows = []

    def walk(items, voice, season):
        for item in items or []:
            if not isinstance(item, dict): continue
            title = ' '.join(str(item.get('title') or '').split())[:120]
            if isinstance(item.get('folder'), list):
                looks_season = re.search(r'сезон|season|\bs\d', title, re.I) and _number(title) is not None
                if voice is None and not looks_season: walk(item['folder'], title, season)
                else: walk(item['folder'], voice if voice is not None else '', _number(title) or season or 1)
                continue
            media = _clean_media(item.get('file'))
            if not media: continue
            rows.append({'voice': voice or '', 'season': season or 1, 'episode': _number(title) or len(rows) + 1,
                         'title': title or 'Серия', 'file': media,
                         'poster': item.get('poster') if str(item.get('poster') or '').startswith('https://') else ''})

    walk(value or [], None, None)
    return rows


def playerjs_choices(embed_url, text, *, language='uk'):
    """Translation choices for discovery; episode URLs are embed selectors."""
    from player_catalog import choice
    rows = playerjs_entries(text)
    groups = {}
    for row in rows:
        groups.setdefault(row['voice'], []).append(row)
    choices = []
    for voice, entries in groups.items():
        episodes = []
        for row in entries:
            url = selector_url(embed_url, mv_voice=voice, mv_season=row['season'], mv_episode=row['episode'])
            episode = {'number': row['episode'], 'season': row['season'], 'url': url, 'title': row['title'] if row['title'] != 'Фильм' else 'Фильм'}
            if row['poster']: episode['thumbnail'] = row['poster']
            episodes.append(episode)
        label = voice or 'Украинский'
        choices.append(choice(label, episodes[0]['url'], identity=player_label(embed_url) + ':' + embed_url + ':' + label,
                              player=player_label(embed_url), language=language, episodes=episodes))
    return choices


def playerjs_stream(embed_url, text, selected):
    """Pick the HLS file named by mv_* selectors from a freshly read embed."""
    rows = playerjs_entries(text)
    if not rows: return None
    voice, season, episode = selected.get('mv_voice'), _number(selected.get('mv_season')), _number(selected.get('mv_episode'))
    for row in rows:
        if (voice is None or row['voice'] == voice) and (season is None or row['season'] == season) and (episode is None or row['episode'] == episode):
            return row['file']
    return None if selected else rows[0]['file']


# ---------------------------------------------------------------- Collaps

def _js_value(text, key, opener):
    """Read a JSON object/array that follows `key:` in a player script."""
    match = re.search(r'\b' + re.escape(key) + r'\s*:\s*' + re.escape(opener), text)
    if not match: return None
    start = match.end() - 1
    closer = ']' if opener == '[' else '}'
    depth, quote, escape = 0, '', False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escape: escape = False
            elif char == '\\': escape = True
            elif char == quote: quote = ''
            continue
        if char == '"': quote = char
        elif char == opener: depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                try: return json.loads(text[start:index + 1])
                except ValueError: return None
    return None


def _audio_names(value):
    if isinstance(value, str):
        try: value = json.loads(value.replace("'", '"'))
        except ValueError: return []
    names = value.get('names') if isinstance(value, dict) else None
    return [' '.join(str(n).split())[:120] for n in names] if isinstance(names, list) else []


def collaps_data(text):
    """{'movie': {...}} or {'seasons': [...]} with hls, audio names and episodes."""
    seasons = _js_value(text, 'seasons', '[')
    if isinstance(seasons, list) and seasons:
        result = []
        for season in seasons:
            if not isinstance(season, dict) or season.get('blocked'): continue
            episodes = []
            for row in season.get('episodes') or []:
                if not isinstance(row, dict) or not str(row.get('hls') or '').startswith('https://'): continue
                episodes.append({'number': _number(row.get('episode')) or len(episodes) + 1, 'hls': row['hls'], 'names': _audio_names(row.get('audio'))})
            if episodes: result.append({'number': _number(season.get('season')) or len(result) + 1, 'episodes': episodes})
        return {'seasons': result}
    hls = re.search(r'\bhls\s*:\s*"(https://[^"]+)"', text)
    audio = _js_value(text, 'audio', '{')
    return {'movie': {'hls': hls.group(1), 'names': _audio_names(audio or {})}} if hls else {}


def collaps_choices(embed_url, text):
    from player_catalog import choice, voice_language
    data = collaps_data(text)
    by_name = {}
    if data.get('movie'):
        for index, name in enumerate(data['movie']['names']):
            url = selector_url(embed_url, mv_audio=index)
            by_name.setdefault(name, []).append({'number': 1, 'season': 1, 'url': url, 'title': 'Фильм'})
    for season in data.get('seasons', []):
        for episode in season['episodes']:
            for index, name in enumerate(episode['names']):
                url = selector_url(embed_url, mv_audio=index, mv_season=season['number'], mv_episode=episode['number'])
                by_name.setdefault(name, []).append({'number': episode['number'], 'season': season['number'], 'url': url, 'title': 'Серия ' + str(episode['number'])})
    choices = []
    for name, episodes in by_name.items():
        if re.search(r'\beng\b|original|оригинал', name, re.I): language = 'en'
        else: language = voice_language(name, 'ru')
        choices.append(choice(name, episodes[0]['url'], identity='collaps:' + embed_url + ':' + name, player='Collaps', language=language, episodes=episodes))
    return choices


def collaps_stream(text, selected):
    """Return (hls_url, audio_index) for the selection, or (None, None)."""
    data = collaps_data(text)
    audio = _number(selected.get('mv_audio'))
    if data.get('movie'):
        return data['movie']['hls'], audio
    season, episode = _number(selected.get('mv_season')), _number(selected.get('mv_episode'))
    for row in data.get('seasons', []):
        if season is not None and row['number'] != season: continue
        for item in row['episodes']:
            if episode is None or item['number'] == episode:
                return item['hls'], audio
    return None, None


def prefer_audio(manifest, index):
    """Make rendition #index the default audio of an HLS master, keeping the rest selectable."""
    if index is None or '#EXT-X-MEDIA' not in manifest: return manifest
    names = []
    for line in manifest.splitlines():
        if line.startswith('#EXT-X-MEDIA') and 'TYPE=AUDIO' in line:
            name = re.search(r'NAME="([^"]*)"', line)
            if name and name.group(1) not in names: names.append(name.group(1))
    if not 0 <= index < len(names): return manifest
    target = names[index]

    def mark(line):
        if not (line.startswith('#EXT-X-MEDIA') and 'TYPE=AUDIO' in line): return line
        chosen = re.search(r'NAME="([^"]*)"', line).group(1) == target
        line = re.sub(r'DEFAULT=(YES|NO)', 'DEFAULT=' + ('YES' if chosen else 'NO'), line)
        return re.sub(r'AUTOSELECT=(YES|NO)', 'AUTOSELECT=' + ('YES' if chosen else 'NO'), line)

    return '\n'.join(mark(line) for line in manifest.splitlines()) + ('\n' if manifest.endswith('\n') else '')
