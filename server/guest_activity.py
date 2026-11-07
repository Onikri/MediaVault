"""What guest profiles do on the owner's server.

Only guest sessions are recorded (never the owner): the address and browser
they come from, the titles they open, what they start playing or reading and
how many bytes the server relays to them. An ASGI middleware attributes every
request and response body to a guest; viewing endpoints add the title.

State lives in memory and is sealed into the settings table at most every
``FLUSH_SECONDS`` per guest, so a restart loses at most that much activity.
"""
import contextvars
import ipaddress
import re
import threading
import time
from datetime import datetime, timezone

FLUSH_SECONDS = 30
EVENTS = 400
ADDRESSES = 60
TITLES = 200
DAYS = 45
LIVE_SECONDS = 75
REPEAT_SECONDS = 600

client = contextvars.ContextVar('guest_activity_client', default=('', ''))


def client_address(scope):
    """The browser's address. Caddy (on the private Docker network) writes the
    address it saw into X-Forwarded-For; anything a direct caller sends is ignored."""
    peer = (scope.get('client') or ('', 0))[0] or ''
    try:
        trusted = ipaddress.ip_address(peer).is_private or ipaddress.ip_address(peer).is_loopback
    except ValueError:
        trusted = False
    if trusted:
        for name, value in scope.get('headers') or []:
            if name == b'x-forwarded-for':
                candidate = value.decode('latin-1').split(',')[-1].strip()
                try:
                    return str(ipaddress.ip_address(candidate))
                except ValueError:
                    break
    return peer


def request_address(request):
    return client_address(request.scope) if request is not None else ''


def header(scope, wanted):
    for name, value in scope.get('headers') or []:
        if name == wanted:
            return value.decode('latin-1')
    return ''


def day(at):
    return datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%d')


def title_key(title):
    title = title or {}
    kind = str(title.get('kind') or 'anime').lower()
    group = 'manga' if kind in {'manga', 'ranobe', 'book', 'manhwa', 'manhua', 'novel', 'one_shot', 'doujin'} else 'anime'
    ids = title.get('ids') or {}
    mal = str(ids.get('mal') or '').strip()
    reference = 'mal' + mal if mal.isdigit() else str(title.get('id') or title.get('title') or '')[:120]
    return group + ':' + reference, group


def title_name(title):
    title = title or {}
    titles = title.get('titles') if isinstance(title.get('titles'), dict) else {}
    for value in (title.get('title'), titles.get('ru'), titles.get('en'), titles.get('native')):
        value = str(value or '').strip()
        # The title page asks for sources before its metadata arrives.
        if value and not PLACEHOLDER.match(value):
            return value[:300]
    return ''


PLACEHOLDER = re.compile(r'^(Загружаем|Загрузка|Loading)\b', re.I)


def empty():
    return {'requests': 0, 'bytes': 0, 'categories': {}, 'days': {}, 'addresses': {}, 'titles': {}, 'events': [],
            'current': None, 'live': None}


class Activity:
    def __init__(self, get_store, clock=time.time):
        self.get_store, self.clock = get_store, clock
        self.lock = threading.RLock()
        self.values, self.dirty, self.saved = {}, set(), {}

    # ---- storage ---------------------------------------------------------
    def state(self, identity):
        value = self.values.get(identity)
        if value is None:
            stored = None
            store = self.get_store()
            if store is not None:
                stored = store.setting('guest-activity:' + identity)
            value = {**empty(), **(stored if isinstance(stored, dict) else {})}
            self.values[identity] = value
        return value

    def touch(self, identity, force=False):
        self.dirty.add(identity)
        now = self.clock()
        if force or now - self.saved.get(identity, 0) >= FLUSH_SECONDS:
            self.flush(identity)

    def flush(self, identity=None):
        store = self.get_store()
        if store is None:
            return
        with self.lock:
            targets = [identity] if identity else list(self.dirty)
            for target in targets:
                if target in self.dirty and target in self.values:
                    value = self.values[target]
                    store.setting('guest-activity:' + target, {k: v for k, v in value.items() if k != 'live'})
                    self.dirty.discard(target)
                    self.saved[target] = self.clock()

    def forget(self, identity):
        with self.lock:
            self.values.pop(identity, None)
            self.dirty.discard(identity)
            store = self.get_store()
            if store is not None:
                store.consume('guest-activity:' + identity)

    # ---- recording -------------------------------------------------------
    def address_row(self, value, address, agent, now):
        rows = value['addresses']
        row = rows.get(address)
        fresh = row is None
        if fresh:
            if rows:
                self.add_event(value, now, 'Новый IP-адрес', address, detail=agent)
            if len(rows) >= ADDRESSES:
                oldest = min(rows, key=lambda key: rows[key]['last'])
                rows.pop(oldest, None)
            row = rows[address] = {'first': now, 'last': now, 'requests': 0, 'bytes': 0, 'agent': ''}
        row['last'] = now
        if agent:
            row['agent'] = agent[:300]
        return row, fresh

    def add_event(self, value, now, action, address='', title=None, detail='', key=''):
        value['events'].append({'t': now, 'action': action, 'ip': address, 'title': title or '', 'detail': str(detail or '')[:300],
                                **({'key': key} if key else {})})
        if len(value['events']) > EVENTS:
            del value['events'][:len(value['events']) - EVENTS]

    def request(self, identity, address, agent, category='api', size=0, path=''):
        """One request (and its response size) made by a guest."""
        if not identity:
            return
        now = int(self.clock())
        with self.lock:
            value = self.state(identity)
            value['requests'] += 1
            value['bytes'] += size
            value['categories'][category] = value['categories'].get(category, 0) + size
            bucket = value['days'].setdefault(day(now), {'bytes': 0, 'requests': 0})
            bucket['bytes'] += size
            bucket['requests'] += 1
            if len(value['days']) > DAYS:
                for name in sorted(value['days'])[:len(value['days']) - DAYS]:
                    value['days'].pop(name, None)
            if address:
                row, _ = self.address_row(value, address, agent, now)
                row['requests'] += 1
                row['bytes'] += size
            if category in {'video', 'manga', 'music'} and size:
                current = value.get('current')
                if current and current.get('key') in value['titles']:
                    value['titles'][current['key']]['bytes'] += size
                live = value.get('live') or {}
                value['live'] = {'at': now, 'category': category,
                                 'since': live.get('since', now) if now - live.get('at', 0) <= LIVE_SECONDS else now}
            self.touch(identity)

    def event(self, identity, action, title=None, detail='', address=None, force=False):
        if not identity:
            return
        now = int(self.clock())
        current_address, agent = client.get()
        address = current_address if address is None else address
        with self.lock:
            value = self.state(identity)
            if address:
                self.address_row(value, address, agent, now)
            self.add_event(value, now, action, address, title_name(title) if isinstance(title, dict) else title, detail)
            self.touch(identity, force)

    def opened(self, identity, title, action=None):
        """A guest opened a title page (discovery or a manga source). Repeats of
        the same title within ten minutes are one visit."""
        if not identity or not isinstance(title, dict):
            return
        key, group = title_key(title)
        now = int(self.clock())
        address, agent = client.get()
        with self.lock:
            value = self.state(identity)
            rows = value['titles']
            row = rows.get(key)
            if row is None:
                if len(rows) >= TITLES:
                    rows.pop(min(rows, key=lambda name: rows[name]['last']), None)
                row = rows[key] = {'title': title_name(title), 'kind': group, 'mal': str((title.get('ids') or {}).get('mal') or ''),
                                   'cover': '', 'first': now, 'last': 0, 'opens': 0, 'plays': 0, 'bytes': 0}
            cover = str(title.get('cover') or title.get('poster') or '')
            if cover.startswith('https://') and len(cover) < 600:
                row['cover'] = cover
            if title_name(title) and row['title'] != title_name(title):
                row['title'] = title_name(title)
                for event in value['events'][-40:]:
                    if event.get('key') == key and not event.get('title'):
                        event['title'] = row['title']
            repeat = now - row['last'] < REPEAT_SECONDS and (value.get('current') or {}).get('key') == key
            row['last'] = now
            value['current'] = {'key': key, 'at': now}
            if not repeat:
                row['opens'] += 1
                self.add_event(value, now, action or ('Открыл мангу' if group == 'manga' else 'Открыл тайтл'), address, row['title'], key=key)
            if address:
                self.address_row(value, address, agent, now)
            self.touch(identity)

    def started(self, identity, kind, detail=''):
        """Playback or reading began (not hover previews)."""
        if not identity:
            return
        now = int(self.clock())
        address, agent = client.get()
        with self.lock:
            value = self.state(identity)
            current = value.get('current') or {}
            row = value['titles'].get(current.get('key'))
            if row:
                row['plays'] += 1
                row['last'] = now
            self.add_event(value, now, 'Открыл главу' if kind == 'manga' else 'Запустил просмотр', address,
                           row['title'] if row else '', detail, key=current.get('key', '') if row else '')
            self.touch(identity)

    # ---- reading ---------------------------------------------------------
    def summary(self, identity):
        now = int(self.clock())
        with self.lock:
            value = self.state(identity)
            today = day(now)
            week = {day(now - offset * 86400) for offset in range(7)}
            month = {day(now - offset * 86400) for offset in range(30)}
            live = value.get('live') or {}
            current = value.get('current') or {}
            watching = None
            if live and now - live.get('at', 0) <= LIVE_SECONDS:
                row = value['titles'].get(current.get('key')) or {}
                watching = {'title': row.get('title') or '', 'cover': row.get('cover') or '', 'category': live.get('category'),
                            'since': live.get('since')}
            last_address = max(value['addresses'].items(), key=lambda item: item[1]['last'], default=(None, None))
            return {'requests': value['requests'], 'bytes': value['bytes'],
                    'bytesToday': value['days'].get(today, {}).get('bytes', 0),
                    'bytesWeek': sum(v['bytes'] for k, v in value['days'].items() if k in week),
                    'bytesMonth': sum(v['bytes'] for k, v in value['days'].items() if k in month),
                    'addresses': len(value['addresses']), 'titles': len(value['titles']),
                    'lastAddress': last_address[0] or '', 'lastAgent': (last_address[1] or {}).get('agent', ''),
                    'lastActive': max([e['t'] for e in value['events'][-1:]] + [r['last'] for r in value['addresses'].values()] + [0]),
                    'watching': watching}

    def report(self, identity):
        now = int(self.clock())
        with self.lock:
            value = self.state(identity)
            days = []
            for offset in range(29, -1, -1):
                name = day(now - offset * 86400)
                bucket = value['days'].get(name, {})
                days.append({'day': name, 'bytes': bucket.get('bytes', 0), 'requests': bucket.get('requests', 0)})
            addresses = sorted(({'ip': ip, **row} for ip, row in value['addresses'].items()), key=lambda row: -row['last'])
            titles = sorted(({'key': key, **row} for key, row in value['titles'].items()), key=lambda row: -row['last'])
            return {'summary': self.summary(identity), 'days': days, 'categories': dict(value['categories']),
                    'addresses': addresses, 'titles': titles, 'events': list(reversed(value['events']))}


ONLINE = re.compile(r'^/online/([A-Za-z0-9_-]{8,64})/[^/]+$')
ALLOHA = re.compile(r'^/(?:hls|play)/([A-Za-z0-9_-]{8,128})(?:/|$)')
CATEGORIES = {'video': 'video', 'preview': 'video', 'manga': 'manga', 'music': 'music', 'music-file': 'music'}


def stream_owner(sessions, alloha=None):
    """Resolve capability URLs (no Authorization header) to the guest that holds them."""
    def resolve(path):
        match = ONLINE.match(path)
        if match:
            session = sessions.get(match.group(1))
            return (session.owner, CATEGORIES.get(session.kind, 'video')) if session else (None, 'api')
        match = ALLOHA.match(path)
        if match and alloha is not None:
            session = alloha().sessions.get(match.group(1))
            return (getattr(session, 'owner', None), 'video') if session else (None, 'api')
        return None, 'api'
    return resolve


class Middleware:
    """Counts requests and response bytes per guest.

    ``identify(authorization)`` returns a subject or None; ``stream_owner(path)``
    returns ``(subject, category)`` for capability URLs (no Authorization header)."""

    def __init__(self, app, activity, identify, stream_owner):
        self.app, self.activity, self.identify, self.stream_owner = app, activity, identify, stream_owner

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http':
            return await self.app(scope, receive, send)
        address, agent = client_address(scope), header(scope, b'user-agent')
        token = client.set((address, agent))
        subject, category = None, 'api'
        path = scope.get('path') or ''
        try:
            authorization = header(scope, b'authorization')
            if authorization:
                subject = self.identify(authorization)
            else:
                subject, category = self.stream_owner(path)
        except Exception:
            subject = None
        identity = str(subject)[6:] if str(subject or '').startswith('guest:') else ''
        if not identity:
            try:
                return await self.app(scope, receive, send)
            finally:
                client.reset(token)
        size = 0

        async def counted(message):
            nonlocal size
            if message.get('type') == 'http.response.body':
                size += len(message.get('body') or b'')
            await send(message)
        try:
            await self.app(scope, receive, counted)
        finally:
            client.reset(token)
            if scope.get('method') != 'OPTIONS':
                try:
                    self.activity.request(identity, address, agent, category, size, path)
                except Exception:
                    pass
