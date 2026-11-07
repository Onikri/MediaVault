"""Episode background music (OST) from WTAS.moe — "What's this Anime Soundtrack?".

WTAS publishes, per anime episode, the soundtrack pieces its music recognition
heard: title, album, the seconds in the episode, the offset inside the track,
a confidence and the official Spotify track id. Pages are SvelteKit; their
data file is JavaScript, so it is *parsed as data* here and never executed.

Requests are few and cached on disk: one index pass (sitemap + episode 1 of
each title), then one request per episode, kept for a week.
"""
import json
import os
import re
import threading
import time
from pathlib import Path

from fastapi import HTTPException

BASE = 'https://www.wtas.moe'
SITEMAP = 'https://wtas.moe/sitemap.xml'
USER_AGENT = 'MediaVault/1.0 (+https://onikri.github.io/MediaVault; cached OST lookups)'
CONFIDENT = 0.01            # WTAS hides matches below this as "uncertain"
INDEX_TTL = 3 * 86400
EPISODE_TTL = 7 * 86400
SLUG = re.compile(r'^[a-z0-9][a-z0-9-]{0,120}$')


# ---------------------------------------------------------------------------
# A small reader for SvelteKit's `__sveltekit_data = (function(a,b,..){return
# {...}}(v1,v2,..))` payload: literals and references only, nothing executed.
class Unparsable(ValueError):
    pass


class _Reader:
    def __init__(self, text):
        self.s, self.i = text, 0

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in ' \t\r\n':
            self.i += 1

    def peek(self):
        self.ws()
        return self.s[self.i] if self.i < len(self.s) else ''

    def take(self, token):
        self.ws()
        if not self.s.startswith(token, self.i):
            raise Unparsable('expected ' + token + ' at ' + str(self.i))
        self.i += len(token)

    def name(self):
        self.ws()
        match = re.compile(r'[A-Za-z_$][\w$]*').match(self.s, self.i)
        if not match:
            raise Unparsable('expected identifier at ' + str(self.i))
        self.i = match.end()
        return match.group(0)

    def string(self):
        self.ws()
        quote = self.s[self.i]
        j = self.i + 1
        while j < len(self.s) and self.s[j] != quote:
            j += 2 if self.s[j] == '\\' else 1
        raw = self.s[self.i + 1:j]
        self.i = j + 1
        raw = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: '\\u00' + m.group(1), raw)
        if quote == "'":
            raw = raw.replace("\\'", "'").replace('"', '\\"')
        try:
            return json.loads('"' + raw + '"')
        except ValueError:
            raise Unparsable('bad string') from None

    def number(self):
        self.ws()
        match = re.compile(r'-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?').match(self.s, self.i)
        if not match:
            raise Unparsable('expected number at ' + str(self.i))
        self.i = match.end()
        text = match.group(0)
        return float(text) if any(c in text for c in '.eE') else int(text)

    def value(self, scope):
        c = self.peek()
        if c == '{':
            self.take('{')
            result = {}
            while self.peek() != '}':
                key = self.string() if self.peek() in '"\'' else str(self.number()) if self.peek().isdigit() else self.name()
                self.take(':')
                result[key] = self.value(scope)
                if self.peek() == ',':
                    self.take(',')
            self.take('}')
            return result
        if c == '[':
            self.take('[')
            result = []
            while self.peek() != ']':
                result.append(None if self.peek() == ',' else self.value(scope))
                if self.peek() == ',':
                    self.take(',')
            self.take(']')
            return result
        if c in '"\'':
            return self.string()
        if c == '-' or c == '.' or c.isdigit():
            return self.number()
        word = self.name()
        if word == 'void':
            self.number()
            return None
        if word in ('true', 'false'):
            return word == 'true'
        if word in ('null', 'undefined', 'NaN', 'Infinity'):
            return None
        if scope is None:
            raise Unparsable('reference outside the body: ' + word)
        if word not in scope:
            raise Unparsable('unknown reference: ' + word)
        return scope[word]


def parse_sveltekit_data(text):
    """Return the merged `data` of all page nodes in a SvelteKit __data.js."""
    start = text.find('(function(')
    if start < 0:
        raise Unparsable('not a SvelteKit data payload')
    reader = _Reader(text)
    reader.i = start + len('(function(')
    params = []
    while reader.peek() != ')':
        params.append(reader.name())
        if reader.peek() == ',':
            reader.take(',')
    reader.take(')')
    reader.take('{')
    reader.take('return')
    body_at = reader.i
    # Skip the body (balanced braces, strings respected) to read the arguments first.
    depth, j, quote = 0, reader.i, ''
    while j < len(text):
        ch = text[j]
        if quote:
            if ch == '\\':
                j += 2
                continue
            if ch == quote:
                quote = ''
        elif ch in '"\'':
            quote = ch
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                break
        j += 1
    reader.i = j + 1
    reader.take('}')
    reader.take('(')
    args = []
    while reader.peek() != ')':
        args.append(reader.value(None))
        if reader.peek() == ',':
            reader.take(',')
    scope = {name: (args[k] if k < len(args) else None) for k, name in enumerate(params)}
    reader.i = body_at
    root = reader.value(scope)
    merged = {}
    for node in root.get('nodes') or []:
        if isinstance(node, dict) and isinstance(node.get('data'), dict):
            merged.update(node['data'])
    return merged


# ---------------------------------------------------------------------------
def tracks_from(data):
    mapping = data.get('spotifyTrackMapping') or {}
    rows = []
    for row in data.get('printData') or []:
        try:
            start, end = float(row['fromSeconds']), float(row['toSeconds'])
        except (KeyError, TypeError, ValueError):
            continue
        title = str(row.get('title') or '').strip()
        if not title or end <= start:
            continue
        spotify = mapping.get(title)
        rows.append({'title': title, 'album': str(row.get('album') or ''), 'start': round(start, 2), 'end': round(end, 2),
                     'offset': row.get('fromSecondsMatch'), 'length': row.get('trackLength'),
                     'confidence': round(float(row.get('confidence') or 0), 4),
                     'uncertain': float(row.get('confidence') or 0) < CONFIDENT,
                     'spotify': spotify if isinstance(spotify, str) and re.fullmatch(r'[A-Za-z0-9]{22}', spotify) else None})
    return sorted(rows, key=lambda r: r['start'])


class WtasOst:
    def __init__(self, directory, fetch=None, clock=time.time):
        self.dir = Path(directory)
        self.fetch = fetch or self._fetch
        self.clock = clock
        self.lock = threading.Lock()
        self.building = None
        self.memory = {}

    @staticmethod
    def _fetch(url):
        import requests
        response = requests.get(url, headers={'User-Agent': USER_AGENT, 'Accept': '*/*'}, timeout=(5, 20))
        if response.status_code == 404:
            raise LookupError(url)
        response.raise_for_status()
        return response.text

    # -- disk cache ----------------------------------------------------------
    def _read(self, name, ttl):
        path = self.dir / name
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if self.clock() - float(value.get('savedAt', 0)) < ttl:
                return value
        except (OSError, ValueError):
            pass
        return None

    def _write(self, name, value):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / (name + '.tmp')
            tmp.write_text(json.dumps({**value, 'savedAt': self.clock()}, ensure_ascii=False), encoding='utf-8')
            os.replace(tmp, self.dir / name)
        except OSError:
            pass

    def _data(self, slug, episode):
        return parse_sveltekit_data(self.fetch(BASE + '/ost/' + slug + '/' + str(int(episode)) + '/__data.js?__invalid=nyy&__id=1'))

    # -- index ---------------------------------------------------------------
    def build_index(self):
        sitemap = self.fetch(SITEMAP)
        episodes = {}
        for slug, number in re.findall(r'<loc>https?://(?:www\.)?wtas\.moe/ost/([a-z0-9-]+)/(\d+)</loc>', sitemap):
            episodes.setdefault(slug, set()).add(int(number))
        previous = (self._read('index.json', 10 ** 9) or {}).get('titles', {})
        titles = {}
        for slug, numbers in episodes.items():
            if not SLUG.match(slug):
                continue
            known = next((v for v in previous.values() if v.get('slug') == slug), None)
            if known:
                titles[str(known['mal'])] = {**known, 'episodes': sorted(numbers)}
                continue
            try:
                data = self._data(slug, min(numbers))
                mal = int(data.get('mal'))
            except (LookupError, Unparsable, TypeError, ValueError, OSError):
                continue
            except Exception:
                continue
            titles[str(mal)] = {'slug': slug, 'mal': mal, 'name': data.get('animeName') or slug, 'altName': data.get('animeAltName') or '',
                                'episodes': sorted(numbers),
                                'albums': [{'name': a.get('name'), 'url': a.get('link')} for a in (data.get('spotify') or []) if isinstance(a, dict) and str(a.get('link', '')).startswith('https://open.spotify.com/')]}
            time.sleep(0.4)  # be gentle: one pass, one request at a time
        value = {'titles': titles}
        if titles:
            self._write('index.json', value)
        return value

    def index(self, wait=False):
        value = self._read('index.json', INDEX_TTL)
        if value:
            return value
        with self.lock:
            if self.building is None or not self.building.is_alive():
                def run():
                    try:
                        self.build_index()
                    except Exception:
                        pass
                self.building = threading.Thread(target=run, daemon=True, name='wtas-index')
                self.building.start()
            thread = self.building
        if wait:
            thread.join()
            return self._read('index.json', 10 ** 9) or {'titles': {}}
        stale = self._read('index.json', 10 ** 9)
        return stale or None

    def title(self, mal):
        index = self.index()
        if index is None:
            return None, True
        return index['titles'].get(str(mal)), False

    def episode(self, mal, episode):
        title, pending = self.title(mal)
        if pending:
            return {'available': False, 'pending': True, 'tracks': []}
        if not title or int(episode) not in title['episodes']:
            return {'available': False, 'pending': False, 'tracks': []}
        key = title['slug'] + '-' + str(int(episode)) + '.json'
        cached = self.memory.get(key)
        if cached and self.clock() - cached['savedAt'] < EPISODE_TTL:
            return cached
        value = self._read(key, EPISODE_TTL)
        if not value:
            data = self._data(title['slug'], episode)
            value = {'available': True, 'pending': False, 'tracks': tracks_from(data),
                     'episodeDuration': data.get('episodeDuration'),
                     'title': {'name': title['name'], 'altName': title['altName'], 'slug': title['slug'], 'episodes': title['episodes'], 'albums': title['albums']},
                     'source': 'WTAS.moe', 'url': BASE + '/ost/' + title['slug'] + '/' + str(int(episode))}
            self._write(key, value)
            value = {**value, 'savedAt': self.clock()}
        if len(self.memory) > 256:
            self.memory.clear()
        self.memory[key] = value
        return value


def install(app, data_dir):
    service = WtasOst(Path(data_dir) / 'wtas')

    @app.get('/music/ost/{mal}')
    def ost_title(mal: int):
        if not 1 <= mal <= 10 ** 7:
            raise HTTPException(422, 'Некорректный ID тайтла.')
        title, pending = service.title(mal)
        if pending:
            return {'available': False, 'pending': True}
        if not title:
            return {'available': False, 'pending': False}
        return {'available': True, 'pending': False, 'name': title['name'], 'altName': title['altName'], 'episodes': title['episodes'],
                'albums': title['albums'], 'source': 'WTAS.moe', 'url': BASE + '/ost/' + title['slug'] + '/' + str(title['episodes'][0])}

    @app.get('/music/ost/{mal}/{episode}')
    def ost_episode(mal: int, episode: int):
        if not 1 <= mal <= 10 ** 7 or not 1 <= episode <= 5000:
            raise HTTPException(422, 'Некорректная серия.')
        try:
            value = service.episode(mal, episode)
        except (LookupError, Unparsable):
            return {'available': False, 'pending': False, 'tracks': []}
        except Exception:
            raise HTTPException(502, 'WTAS.moe сейчас не отвечает. Повтори немного позже.') from None
        return {k: v for k, v in value.items() if k != 'savedAt'}

    return service
