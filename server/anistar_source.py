"""Read AniStar's published episode configuration without executing page scripts."""
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from source_parser import Page, SourceError, episode_number, playback_headers, public_url

HOSTS = {'anistar.org', 'www.anistar.org'}
SELECTOR = 'mv_anistar_id'


def is_player(url):
    parts = urlsplit(url)
    return parts.hostname in HOSTS and bool(re.fullmatch(
        r'/test/player2/videoas(?:_p2p(?:_new)?)?\.php', parts.path
    ))


def playlist(text, base):
    if not is_player(base):
        return []
    match = re.search(r'\b(?:var|let|const)\s+playlst\s*=\s*(\[[\s\S]*?\])\s*;', text)
    if not match:
        return []
    from yt_dlp.utils import js_to_json

    try:
        data = json.loads(js_to_json(match[1]))
    except (ValueError, TypeError, RecursionError):
        raise SourceError('AniStar вернул некорректный список серий.') from None
    if not isinstance(data, list) or len(data) > 10000:
        raise SourceError('AniStar вернул неподдерживаемый список серий.')
    rows = []
    seen = set()
    for value in data:
        if not isinstance(value, dict):
            continue
        identity = str(value.get('media_id', ''))
        title = str(value.get('title') or '')[:180]
        number = episode_number(title)
        if not re.fullmatch(r'\d{1,12}', identity) or number is None or identity in seen:
            continue
        streams = []
        for key, kind, suffix in (('files', 'hls', '.m3u8'), ('files_mp4', 'mp4', '.mp4')):
            files = value.get(key) or []
            if not isinstance(files, list):
                continue
            for source in files[:24]:
                if not isinstance(source, dict) or not re.fullmatch(r'\d{2,4}p?', str(source.get('title', ''))):
                    continue
                try:
                    target = public_url(source.get('file'), resolve_dns=False)
                except SourceError:
                    continue
                if not urlsplit(target).path.lower().endswith(suffix):
                    continue
                quality = int(str(source['title']).rstrip('p'))
                if 1 <= quality <= 8640:
                    streams.append({'url': target, 'type': kind, 'quality': quality,
                                    'headers': playback_headers({'Referer': base})})
        if not streams:
            continue
        seen.add(identity)
        label = re.sub(r'^(?:серия|эпизод|episode)\s*\d+\s*', '', title, flags=re.I).strip(' ·:–-')
        # Distinct declared voice types stay distinct even when captions coincide.
        rows.append({'id': identity, 'number': number, 'title': title,
                     'voice': str(value.get('type_dub') or label or 'default'),
                     'label': 'AniStar' + (' · ' + label if label else ''), 'streams': streams})
    return rows


def episode_url(base, identity):
    parts = urlsplit(base)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != SELECTOR]
    return urlunsplit(parts._replace(query=urlencode([*query, (SELECTOR, identity)]), fragment=''))


def choices(text, base):
    from player_catalog import choice

    groups = {}
    for row in playlist(text, base):
        group = groups.setdefault(row['voice'], {'label': row['label'], 'episodes': []})
        group['episodes'].append({'number': row['number'], 'season': 1, 'title': row['title'],
                                  'url': episode_url(base, row['id'])})
    return [choice(group['label'], group['episodes'][0]['url'], identity='anistar:' + identity,
                   language='ru', player='AniStar', episodes=group['episodes'])
            for identity, group in groups.items()]


def player_page(text, base):
    rows = playlist(text, base)
    if not rows:
        return None
    selectors = [v for k, v in parse_qsl(urlsplit(base).query) if k == SELECTOR]
    if len(selectors) > 1:
        raise SourceError('Неоднозначный выбор серии AniStar.')
    selected = next((row for row in rows if row['id'] == selectors[0]), None) if selectors else rows[0]
    if selected is None:
        raise SourceError('Выбранная серия AniStar больше не опубликована. Обнови список.')
    return Page(title=selected['title'], streams=selected['streams'],
                episodes=[{'number': row['number'], 'season': 1, 'title': row['title'],
                           'url': episode_url(base, row['id'])}
                          for row in rows if row['voice'] == selected['voice']])
