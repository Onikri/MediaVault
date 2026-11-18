"""One network transport for every direct source adapter.

``PublicHttp._open`` asks this module, for every request (and every redirect
hop), which exit the request takes and whether a browser challenge may be
handed to the private solver. Nothing here is hardcoded per adapter: routes
are declared per source ID in ``manga_source_transport.json`` (shipped with
the code) and may be overridden by the administrator in
``/data/manga-source-transport.json``. The infrastructure side (Japan gateway,
Byparr) is described by ``/data/source-transport.json``, which the Oracle
installer writes; without it the legacy Suwayomi gateway manifest is used.

A route rule matches by source ID + operation + domain:

    {"hosts": ["manga.line.me"], "operations": ["*"], "exit": "japan"}
    {"hosts": ["natomanga.com"], "operations": ["search", "chapters"],
     "exit": "direct", "solver": true, "format": "html"}

Solver sessions (guest cookies + the solver's User-Agent) are bound to
(source, host, exit identity). Concurrent requests for one key wait on a
single solver run. A change of the Japan exit drops every session bound to
the previous exit. The solver and the retried request use the same exit.
Logins and paid chapters are never bypassed; they get their own statuses.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

import requests

from source_parser import (SourceAuthError, SourceChallengeError, SourceError, SourcePaidError,
                           SourceRegionError, SourceRouteError)

DECLARATIONS = Path(__file__).with_name('manga_source_transport.json')
OPERATIONS = frozenset({'search', 'catalogue', 'details', 'chapters', 'pages', 'images'})
FORMATS = frozenset({'html', 'json', 'image', 'cbz', 'any'})
EXITS = frozenset({'direct', 'japan'})
DEFAULT_SOLVER = 'http://byparr:8191/v1'
LEGACY_PROXY = 'http://suwayomi-jp-router:8080'
SESSION_TTL = 25 * 60
FAILURE_COOLDOWN = 90
PAGE_REUSE = 60
RETRY_RESERVE = 10
STATUS_TTL = 10
MAX_SOLVES = 2
HOST = re.compile(r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}')
SERVICE = re.compile(r'http://[a-z0-9](?:[a-z0-9.-]{0,61}[a-z0-9])?(?::[0-9]{2,5})?(?:/[a-z0-9/_-]{0,64})?')

# Browser challenges (solvable), as opposed to bans, logins and paywalls.
CHALLENGE = re.compile(
    r'/cdn-cgi/challenge-platform(?!/scripts/jsd/)|cf-chl-|__cf_chl_|checking your browser|'
    r'enable javascript and cookies to continue|verify (?:that )?you are human|'
    r'<title[^>]*>\s*just a moment|ddos-guard\.net/[^"\']*check|<title[^>]*>\s*ddos-guard',
    re.I)
REGION = re.compile(r'error code:?\s*1009\b|has banned the (?:country|region)|'
                    r'not available in your (?:country|region)|geo.?blocked|'
                    r'only available (?:in|from) japan|日本国内でのみ', re.I)
PAID = re.compile(r'["\'](?:subscription_required|requires_subscription|requires_purchase|is_paid_locked)["\']\s*:\s*true',
                  re.I)
AUTH = re.compile(r'["\'](?:requires_authentication|login_required)["\']\s*:\s*true', re.I)

_scope = contextvars.ContextVar('mediavault_source_scope', default=(None, None))


# ------------------------------------------------------------------ declarations

@dataclass(frozen=True)
class Rule:
    hosts: tuple
    operations: frozenset
    exit: str = 'direct'
    solver: bool = False
    format: str = 'any'

    def matches(self, host, operation):
        if not any(host == domain or host.endswith('.' + domain) for domain in self.hosts):
            return False
        return operation is None or '*' in self.operations or operation in self.operations


@dataclass(frozen=True)
class Declaration:
    source: str
    name: str
    rules: tuple
    solver_budget: int = 0

    def rule(self, host, operation):
        return next((rule for rule in self.rules if rule.matches(host, operation)), None)


def parse_rule(value):
    if not isinstance(value, dict) or not set(value) <= {'hosts', 'operations', 'exit', 'solver', 'format'}:
        raise ValueError('Unknown route field')
    hosts = value.get('hosts')
    if (not isinstance(hosts, list) or not 1 <= len(hosts) <= 32
            or any(not isinstance(h, str) or len(h) > 253 or not HOST.fullmatch(h) for h in hosts)):
        raise ValueError('Route hosts must be public domain names')
    operations = value.get('operations', ['*'])
    if (not isinstance(operations, list) or not operations
            or any(op != '*' and op not in OPERATIONS for op in operations)):
        raise ValueError('Unknown route operation')
    exit_name = value.get('exit', 'direct')
    solver = value.get('solver', False)
    fmt = value.get('format', 'any')
    if exit_name not in EXITS or type(solver) is not bool or fmt not in FORMATS:
        raise ValueError('Invalid route exit, solver or format')
    return Rule(tuple(hosts), frozenset(operations), exit_name, solver, fmt)


def parse(value):
    """Validate a declaration document; raise ValueError on any unknown shape."""
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('sources'), dict):
        raise ValueError('Declaration document must be {"version": 1, "sources": {...}}')
    result = {}
    for source, entry in value['sources'].items():
        if not re.fullmatch(r'-?[0-9]{1,20}', source) or not isinstance(entry, dict):
            raise ValueError('Source IDs must be numeric strings')
        if not set(entry) <= {'name', 'routes', 'solverBudget'}:
            raise ValueError('Unknown source field')
        routes = entry.get('routes')
        budget = entry.get('solverBudget', 0)
        if not isinstance(routes, list) or not 1 <= len(routes) <= 32:
            raise ValueError('A source declares 1..32 routes')
        if type(budget) is not int or not 0 <= budget <= 75:
            raise ValueError('solverBudget is 0..75 seconds')
        result[source] = Declaration(source, str(entry.get('name', ''))[:80], tuple(parse_rule(r) for r in routes), budget)
    return result


_declared = {'key': None, 'value': {}}
_declared_lock = threading.Lock()


def _stamp(path):
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


def override_path():
    return Path(os.getenv('DATA_DIR', '/data')) / 'manga-source-transport.json'


def declarations():
    """Shipped declarations, with whole-source replacements from the admin override."""
    override = override_path()
    key = (_stamp(DECLARATIONS), _stamp(override))
    with _declared_lock:
        if _declared['key'] == key:
            return _declared['value']
        value = parse(json.loads(DECLARATIONS.read_text(encoding='utf-8')))
        if key[1] is not None and key[1][1] <= 65536:
            try:
                value = {**value, **parse(json.loads(override.read_text(encoding='utf-8')))}
            except (OSError, ValueError):
                # An invalid override must not take every source offline.
                pass
        _declared.update(key=key, value=value)
        return value


def declared(source):
    return declarations().get(str(source)) if source is not None else None


def declared_host(host):
    return any(rule.matches(host, None) for entry in declarations().values() for rule in entry.rules)


def solver_budget(source, normal):
    """Request budget for a dispatcher: the declared solver budget for solver sources."""
    entry = declared(source)
    if entry and any(rule.solver for rule in entry.rules):
        return max(normal, entry.solver_budget or 45)
    return normal


# ------------------------------------------------------------------ scope

class scope:
    """``with scope(http, source_id, operation):`` — which source an adapter call serves."""

    def __init__(self, http, source, operation):
        self.http, self.value = http, (None if source is None else str(source), operation)

    def __enter__(self):
        self.saved = (getattr(self.http, 'source', None), getattr(self.http, 'operation', None))
        self._set(self.value)
        self.token = _scope.set(self.value)
        return self.http

    def __exit__(self, *_):
        self._set(self.saved)
        _scope.reset(self.token)

    def _set(self, value):
        try:
            self.http.source, self.http.operation = value
        except AttributeError:
            # A foreign client (slots/proxy object) still gets the context scope.
            pass


def current():
    return _scope.get()


def operation_for(adapter, url):
    """'pages' for a chapter reader URL of the adapter, otherwise 'chapters' (a title card)."""
    try:
        check = getattr(adapter, 'is_chapter', None)
        if check is not None:
            return 'pages' if check(url) else 'chapters'
        from manga_source_urls import split_reader_url
        pattern = getattr(adapter, 'CHAPTER_PATH', None)
        path = urlsplit(split_reader_url(url)[1]).path
        return 'pages' if pattern is not None and pattern.fullmatch(path) else 'chapters'
    except Exception:  # noqa: BLE001 - an unknown URL shape is still a title request
        return 'chapters'


def resolve(http, url, headers, expect):
    """(source ID, operation) of a request, or (None, None) for undeclared traffic."""
    source = getattr(http, 'source', None)
    operation = getattr(http, 'operation', None)
    if source is None:
        source, operation = current()
    host = urlsplit(url).hostname or ''
    if source is None and declared_host(host):
        # Page images travel through the playback proxy without an adapter
        # scope; the chapter Referer names the source that owns them.
        referer = (headers or {}).get('Referer')
        if isinstance(referer, str):
            try:
                from manga_native_sources import for_url
                adapter = for_url(referer)
            except Exception:  # noqa: BLE001 - inference only; never break a request
                adapter = None
            if adapter is not None and declared(adapter.SOURCE_ID):
                source = adapter.SOURCE_ID
                operation = operation or ('pages' if expect == 'page' else 'images')
    return (str(source) if source is not None else None), operation


# ------------------------------------------------------------------ infrastructure

def infra_path():
    return Path(os.getenv('DATA_DIR', '/data')) / 'source-transport.json'


def infrastructure():
    """The gateway/solver contract written by the Oracle installer, else the legacy one."""
    path = infra_path()
    try:
        if path.stat().st_size <= 16384:
            value = json.loads(path.read_text())
            japan, solver = value.get('japan') or {}, value.get('solver') or {}
            if value.get('version') != 1 or not isinstance(japan, dict) or not isinstance(solver, dict):
                raise ValueError
            proxy, status, url = japan.get('httpProxy'), japan.get('status'), solver.get('url', DEFAULT_SOLVER)
            hosts = japan.get('hosts')
            japan_url = solver.get('japanUrl')
            for item in (proxy, status, url, japan_url):
                if item is not None and (not isinstance(item, str) or not SERVICE.fullmatch(item)):
                    raise ValueError
            if hosts is not None and (not isinstance(hosts, list)
                                      or any(not isinstance(h, str) or not HOST.fullmatch(h) for h in hosts)):
                raise ValueError
            timeout = solver.get('maxTimeout', 60)
            if type(timeout) is not int or not 10 <= timeout <= 120:
                raise ValueError
            return {'mode': 'gateway', 'proxy': proxy, 'status': status, 'hosts': hosts,
                    'solver': url, 'solverJapan': japan_url, 'solverTimeout': timeout}
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    from manga_network_routes import configuration
    legacy = configuration()
    return {'mode': 'legacy', 'proxy': legacy.get('httpProxy'), 'status': None, 'hosts': legacy.get('hosts', []),
            'solver': DEFAULT_SOLVER, 'solverJapan': None, 'solverTimeout': 60}


_status = {'time': 0.0, 'value': None}
_status_lock = threading.Lock()


def japan_exit(infra, *, fresh=False):
    """Current Japan exit identity; raise SourceRouteError when the tunnel is down."""
    if not infra.get('proxy'):
        raise SourceRouteError('Японский маршрут не настроен на сервере.')
    if not infra.get('status'):
        return 'japan:legacy'
    with _status_lock:
        if fresh or time.monotonic() - _status['time'] > STATUS_TTL:
            try:
                response = requests.get(infra['status'], timeout=(1.5, 2.5), allow_redirects=False)
                value = response.json() if response.status_code == 200 else {}
            except (requests.RequestException, ValueError):
                value = {}
            _status.update(time=time.monotonic(), value=value if isinstance(value, dict) else {})
        value = _status['value'] or {}
    if value.get('ready') is not True or value.get('fresh') is False or value.get('country', 'JP') != 'JP':
        raise SourceRouteError('Японский шлюз сейчас недоступен. Повтори позже.')
    # The gateway reports the exit IP and a generation that grows on every
    # reconnect: the same IP after a reconnect is still a new exit session.
    identity = value.get('exitId') or value.get('exit')
    generation = value.get('generation')
    if isinstance(identity, str) and type(generation) is int and not value.get('exitId'):
        identity = f'{generation}-{identity}'
    if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9.:_-]{1,80}', identity):
        raise SourceRouteError('Японский шлюз не сообщил текущий выход.')
    exit_id = 'japan:' + identity
    sessions.observe_exit(exit_id)
    return exit_id


def route_down():
    """A proxied request failed at the gateway: forget the cached status and its sessions."""
    with _status_lock:
        _status.update(time=0.0, value=None)
    sessions.drop_exit('japan:')


@dataclass(frozen=True)
class Decision:
    source: str
    operation: str | None
    host: str
    rule: Rule
    exit_id: str
    proxy: str | None
    infra: dict = field(compare=False, default_factory=dict)

    @property
    def solver(self):
        return self.rule.solver

    def solver_url(self):
        if self.rule.exit == 'japan' and self.infra.get('solverJapan'):
            return self.infra['solverJapan']
        return self.infra.get('solver') or DEFAULT_SOLVER

    def solver_proxy(self):
        # Byparr takes a per-request proxy header; a dedicated Japan solver needs none.
        return self.proxy if self.rule.exit == 'japan' and not self.infra.get('solverJapan') else None

    def page_allowed(self, method, accept, expect):
        """Solver HTML replaces a response only where the adapter expects a page."""
        if expect != 'page' or method != 'GET' or self.rule.format not in {'html', 'any'}:
            return False
        accept = (accept or '').lower()
        return not any(kind in accept for kind in ('json', 'protobuf', 'x-component', 'image/', 'octet-stream'))


def decide(source, operation, url):
    """The declared route of this request, or None for undeclared traffic (legacy path)."""
    entry = declared(source)
    host = (urlsplit(url).hostname or '').lower()
    rule = entry.rule(host, operation) if entry else None
    if rule is None:
        return None
    infra = infrastructure()
    if rule.exit == 'direct':
        return Decision(entry.source, operation, host, rule, 'direct', None, infra)
    if not infra.get('proxy'):
        raise SourceRouteError('Японский маршрут не настроен на сервере.')
    allowed = infra.get('hosts')
    if allowed is not None and not any(host == d or host.endswith('.' + d) for d in allowed):
        # The legacy router sends unlisted hosts out through Oracle without an
        # error; never let a Japan-only request silently leave elsewhere.
        raise SourceError(f'Японский шлюз не обслуживает домен {host}; добавь его в маршруты шлюза.')
    return Decision(entry.source, operation, host, rule, japan_exit(infra), infra['proxy'], infra)


# ------------------------------------------------------------------ solver sessions

@dataclass
class Session:
    cookies: dict
    user_agent: str
    created: float
    exit_id: str
    url: str = ''
    html: str = ''
    final: str = ''
    cookies_work: bool | None = None

    def alive(self):
        return time.time() - self.created < SESSION_TTL


@dataclass
class Attempt:
    time: float
    session: Session | None = None
    error: str = ''


class Sessions:
    def __init__(self):
        self.lock = threading.Lock()
        self.keys = {}
        self.attempts = {}
        self.exits = set()
        self.slots = threading.BoundedSemaphore(MAX_SOLVES)

    def key_lock(self, key):
        with self.lock:
            return self.keys.setdefault(key, threading.Lock())

    def get(self, key):
        with self.lock:
            attempt = self.attempts.get(key)
        if attempt and attempt.session and attempt.session.alive():
            return attempt.session
        return None

    def latest(self, key):
        with self.lock:
            return self.attempts.get(key)

    def put(self, key, attempt):
        with self.lock:
            self.attempts[key] = attempt

    def forget(self, key):
        with self.lock:
            self.attempts.pop(key, None)

    def observe_exit(self, exit_id):
        prefix = exit_id.split(':', 1)[0] + ':'
        with self.lock:
            stale = {e for e in self.exits if e.startswith(prefix) and e != exit_id}
            self.exits = (self.exits - stale) | {exit_id}
            if stale:
                for key in [k for k in self.attempts if k[2] in stale]:
                    del self.attempts[key]

    def drop_exit(self, prefix):
        with self.lock:
            for key in [k for k in self.attempts if k[2].startswith(prefix)]:
                del self.attempts[key]
            self.exits = {e for e in self.exits if not e.startswith(prefix)}

    def clear(self):
        with self.lock:
            self.attempts.clear()
            self.exits.clear()


sessions = Sessions()


def session_key(decision):
    return (decision.source, decision.host, decision.exit_id)


def apply(session, outgoing, cookies):
    """Send the solved guest cookies and the solver's User-Agent with a request."""
    outgoing['User-Agent'] = session.user_agent
    if 'Cookie' in outgoing:
        present = {part.split('=', 1)[0].strip() for part in outgoing['Cookie'].split(';')}
        extra = '; '.join(f'{k}={v}' for k, v in session.cookies.items() if k not in present)
        if extra:
            outgoing['Cookie'] = outgoing['Cookie'] + '; ' + extra
    else:
        cookies.update(session.cookies)


def _clean_cookies(values, host):
    result = {}
    for cookie in values if isinstance(values, list) else []:
        if not isinstance(cookie, dict):
            continue
        name, value, domain = cookie.get('name'), cookie.get('value'), str(cookie.get('domain') or host).lstrip('.')
        if (isinstance(name, str) and isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', name)
                and len(value) <= 4096 and not re.search(r'[;\r\n\s]', value)
                and (host == domain or host.endswith('.' + domain))):
            result[name] = value
    return result


def solve(decision, url, deadline, started, *, fetch_page=False):
    """Run the solver once per (source, host, exit); concurrent callers share the run.

    ``started`` is when the caller's failed request began: a session or failure
    recorded after it belongs to a run the caller waited on, so it is reused
    instead of starting another browser.
    """
    key = session_key(decision)
    with sessions.key_lock(key):
        latest = sessions.latest(key)
        if (fetch_page and latest and latest.session and latest.session.url == url and latest.session.html
                and time.time() - latest.session.created < PAGE_REUSE):
            # The run that just failed with cookies already rendered this page.
            return latest.session
        if latest and latest.time >= started:
            if latest.session and (not fetch_page or latest.session.url == url):
                return latest.session
            if not latest.session:
                raise SourceChallengeError('Решатель проверки браузера не справился с источником.', solver='failed')
        if latest and latest.error and time.time() - latest.time < FAILURE_COOLDOWN:
            raise SourceChallengeError('Решатель недавно не справился с этим источником. Повтори позже.',
                                       solver='cooldown')
        remaining = (deadline - time.monotonic()) if deadline else decision.infra.get('solverTimeout', 60)
        # Byparr waits for network idle until maxTimeout: leave the retried
        # request its own share of the caller's budget.
        budget = min(decision.infra.get('solverTimeout', 60), remaining - RETRY_RESERVE)
        if budget < 6:
            raise SourceChallengeError('Источнику нужна проверка браузера, но время запроса уже истекло.',
                                       solver='budget')
        release = acquire_slot(max(0.1, budget - 5))
        if release is None:
            raise SourceChallengeError('Решатель проверки браузера занят. Повтори позже.', solver='busy')
        try:
            if deadline:
                # Waiting for a free browser spent part of the caller's budget.
                budget = min(budget, deadline - time.monotonic() - RETRY_RESERVE)
                if budget < 6:
                    raise SourceChallengeError('Решатель был занят, и время запроса истекло.', solver='busy')
            # The solver and the retried request must leave through one exit:
            # recheck it right before the run.
            if decision.rule.exit == 'japan' and decision.infra.get('status'):
                if japan_exit(decision.infra, fresh=True) != decision.exit_id:
                    raise SourceRouteError('Японский выход сменился во время запроса. Повтори.')
            session = call_solver(decision, url, budget)
        except SourceChallengeError as error:
            sessions.put(key, Attempt(time.time(), None, str(error)))
            raise
        finally:
            release()
        sessions.put(key, Attempt(time.time(), session))
        return session


def slot_dir():
    return Path(os.getenv('SOURCE_SOLVER_SLOTS', '/tmp'))


def acquire_slot(timeout):
    """One of MAX_SOLVES Byparr slots shared by every process of the container.

    The importer's workers and side processes (probes, live checks) all call
    the same single-CPU Byparr; a per-process limit alone let three browsers
    run at once and each solve take over a minute. Returns a release
    callable, or None when no slot frees up within ``timeout``."""
    if not sessions.slots.acquire(timeout=timeout):
        return None
    try:
        import fcntl
    except ImportError:  # Windows development checkout: the process limit only
        return sessions.slots.release
    end = time.monotonic() + timeout
    while True:
        for index in range(MAX_SOLVES):
            try:
                handle = os.open(slot_dir() / f'mediavault-solver-{index}.lock', os.O_RDWR | os.O_CREAT, 0o600)
            except OSError:
                return sessions.slots.release
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(handle)
                continue

            def release(handle=handle):
                try:
                    fcntl.flock(handle, fcntl.LOCK_UN)
                finally:
                    os.close(handle)
                    sessions.slots.release()
            return release
        if time.monotonic() >= end:
            sessions.slots.release()
            return None
        time.sleep(0.25)


def call_solver(decision, url, budget):
    headers = {'Content-Type': 'application/json'}
    if proxy := decision.solver_proxy():
        headers['X-Proxy-Server'] = proxy
    body = {'cmd': 'request.get', 'url': url, 'maxTimeout': int(budget * 1000)}
    try:
        response = requests.post(decision.solver_url(), json=body, headers=headers,
                                 timeout=(3, budget + 5), allow_redirects=False)
    except requests.Timeout:
        # Byparr is shared and solves one browser per CPU: a slow run is a
        # timeout, not a missing service.
        raise SourceChallengeError('Решатель не успел пройти проверку браузера.', solver='timeout') from None
    except requests.RequestException:
        raise SourceChallengeError('Решатель проверки браузера недоступен.', solver='unavailable') from None
    try:
        value = response.json() if len(response.content) <= 8 * 1024 * 1024 else {}
    except ValueError:
        value = {}
    solution = value.get('solution') if isinstance(value, dict) else None
    if response.status_code == 408:
        raise SourceChallengeError('Решатель не успел пройти проверку браузера.', solver='timeout')
    if response.status_code != 200 or value.get('status') != 'ok' or not isinstance(solution, dict):
        raise SourceChallengeError('Решатель проверки браузера не справился с источником.', solver='failed')
    agent = solution.get('userAgent')
    final = solution.get('url') if isinstance(solution.get('url'), str) else ''
    if (not isinstance(agent, str) or not 20 <= len(agent) <= 512 or re.search(r'[\r\n\x00]', agent)
            or (urlsplit(final).hostname or '').lower() != decision.host):
        raise SourceChallengeError('Решатель вернул ответ другого сайта.', solver='failed')
    html = solution.get('response') if isinstance(solution.get('response'), str) else ''
    return Session(_clean_cookies(solution.get('cookies'), decision.host), agent, time.time(), decision.exit_id,
                   url, html, final)


# ------------------------------------------------------------------ classification

def classify(status, headers, text):
    """The precise error of an upstream answer, or None when it is an ordinary one."""
    headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    server = headers.get('server', '').lower()
    if headers.get('cf-mitigated', '').lower() == 'challenge' or CHALLENGE.search(text or ''):
        if status in {200, 403, 429, 503} or 'cloudflare' in server or 'ddos-guard' in server:
            return 'challenge'
    if status == 451 or not 200 <= status < 300 and REGION.search(text or ''):
        return 'region_blocked'
    if PAID.search(text or ''):
        return 'paid_chapter'
    if status == 401 or AUTH.search(text or ''):
        return 'auth_required'
    return None


def error_for(kind, url=''):
    host = urlsplit(url).hostname or 'источник'
    if kind == 'challenge':
        return SourceChallengeError(f'{host} требует проверку браузера.', solver='none')
    if kind == 'region_blocked':
        return SourceRegionError(f'{host} не открывается из региона этого выхода.')
    if kind == 'paid_chapter':
        return SourcePaidError('Глава платная или доступна только по подписке.')
    if kind == 'auth_required':
        return SourceAuthError('Источник требует вход в аккаунт.')
    return None


def solver_page(decision, url, deadline):
    """The solver's own rendering of a page the adapter expects as HTML."""
    page = solve(decision, url, deadline, time.time(), fetch_page=True)
    if not page.html or CHALLENGE.search(page.html[:65536]) or len(page.html) > 4 * 1024 * 1024:
        raise SourceChallengeError('Решатель не смог открыть страницу источника.', solver='rejected')
    return html_response(page, url)


def html_response(session, url):
    """A synthetic page response built from the solver's rendered HTML."""
    response = requests.Response()
    response.status_code = 200
    response._content = session.html.encode('utf-8')
    response._content_consumed = True
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['X-MediaVault-Solver'] = '1'
    response.encoding = 'utf-8'
    response.url = url
    return response


def describe():
    """Diagnostics for the control panel and the live check (no cookies)."""
    infra = infrastructure()
    with sessions.lock:
        keys = [{'source': k[0], 'host': k[1], 'exit': k[2], 'solved': bool(a.session),
                 'age': round(time.time() - a.time)} for k, a in sessions.attempts.items()]
    return {'mode': infra['mode'], 'japanProxy': bool(infra.get('proxy')), 'japanStatus': bool(infra.get('status')),
            'solver': infra.get('solver'), 'declaredSources': len(declarations()), 'sessions': keys}
