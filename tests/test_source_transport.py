"""Source transport contracts: declared routes, Japan exit, Byparr sessions, statuses.

Everything here is MOCKED: the upstream sites are a fake requests session, the
Japan gateway status endpoint and Byparr are patched ``requests.get`` /
``requests.post`` calls. No network is used. The live check on the Oracle VM is
``scripts/check-source-transport.py``.
"""

from io import BytesIO
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import requests

import source_transport as transport
from source_parser import (PublicHttp, SourceAccessError, SourceAuthError, SourceChallengeError, SourceError,
                           SourcePaidError, SourceRateLimitError, SourceRegionError, SourceRouteError,
                           SourceTemporaryError, public_url, source_status)

MANGANATO = '1024627298672457456'
SOKUYOMI = '3115293328774708452'
LINE = '7324763859222949244'
UA = 'Mozilla/5.0 (X11; Linux aarch64) Byparr/Test Chrome/140.0'
CHALLENGE_PAGE = (b'<html><head><title>Just a moment...</title></head><body>'
                  b'<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script></body></html>')
TITLE_PAGE = b'<html><head><title>Solo Leveling</title></head><body><h1>Solo Leveling</h1></body></html>'
DECLARATIONS = {
    'version': 1,
    'sources': {
        MANGANATO: {'name': 'Manganato', 'solverBudget': 45, 'routes': [
            {'hosts': ['natomanga.com'], 'operations': ['*'], 'exit': 'direct', 'solver': True, 'format': 'html'}]},
        SOKUYOMI: {'name': 'Sokuyomi', 'routes': [
            {'hosts': ['cdn.sokuyomi.jp'], 'operations': ['*'], 'exit': 'direct', 'format': 'image'},
            {'hosts': ['sokuyomi.jp'], 'operations': ['*'], 'exit': 'japan'}]},
        LINE: {'name': 'Line Manga', 'routes': [
            {'hosts': ['manga.line.me'], 'operations': ['search', 'catalogue'], 'exit': 'japan', 'solver': True},
            {'hosts': ['manga.line.me'], 'operations': ['images'], 'exit': 'direct'}]},
    },
}


def response(status=200, body=b'', headers=None):
    value = requests.Response()
    value.status_code = status
    value.headers.update(headers or {'Content-Type': 'text/html; charset=utf-8'})
    value.raw = BytesIO(body)
    return value


class FakeSite:
    """A requests.Session stand-in: answers by URL and records every request."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()
        self.lock = threading.Lock()

    def request(self, method, url, headers=None, data=None, **options):
        with self.lock:
            self.calls.append({'method': method, 'url': url, 'headers': dict(headers or {}), 'options': options})
        return self.answer(method, url, dict(headers or {}), options)

    def close(self):
        pass


def cleared(headers, options):
    cookie = headers.get('Cookie', '') + ';' + ';'.join(f'{k}={v}' for k, v in (options.get('cookies') or {}).items())
    return 'cf_clearance=ok' in cookie and headers.get('User-Agent') == UA


def byparr(url='https://www.natomanga.com/manga/solo', html=TITLE_PAGE.decode(), status=200, delay=0.0):
    def post(endpoint, json=None, headers=None, timeout=None, allow_redirects=None):
        time.sleep(delay)
        payload = {'status': 'ok', 'message': 'Success', 'solution': {
            'url': json['url'], 'status': 200, 'userAgent': UA, 'response': html,
            'cookies': [{'name': 'cf_clearance', 'value': 'ok', 'domain': '.natomanga.com', 'path': '/'},
                        {'name': 'tracker', 'value': 'x', 'domain': '.evil.example', 'path': '/'}]}}
        value = requests.Response()
        value.status_code = status
        value._content = __import__('json').dumps(payload).encode()
        return value
    return post


class TransportCase(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.declarations = self.data / 'declarations.json'
        self.declarations.write_text(json.dumps(DECLARATIONS))
        self.patches = [patch.dict(os.environ, {'DATA_DIR': str(self.data)}),
                        patch.object(transport, 'DECLARATIONS', self.declarations)]
        for item in self.patches:
            item.start()
        transport._declared.update(key=None, value={})
        transport._status.update(time=0.0, value=None)
        transport.sessions.clear()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        transport._declared.update(key=None, value={})
        transport.sessions.clear()
        self.temp.cleanup()

    def legacy_routes(self, hosts=('sokuyomi.jp', 'manga.line.me')):
        (self.data / 'manga-source-routes.json').write_text(json.dumps(
            {'revision': 'a' * 64, 'hosts': list(hosts), 'httpProxy': 'http://suwayomi-jp-router:8080'}))

    def gateway(self, **japan):
        (self.data / 'source-transport.json').write_text(json.dumps({
            'version': 1,
            'japan': {'httpProxy': 'http://jp-gateway:8080', 'status': 'http://jp-gateway:8090/status', **japan},
            'solver': {'url': 'http://byparr:8191/v1', 'maxTimeout': 60}}))

    def http(self, site, source=None, operation=None, deadline=None):
        # URL validation has its own tests; these requests only exercise routing.
        return PublicHttp(session=site, validate=lambda value: value,
                          timeout=(3, 6), deadline=deadline, source=source, operation=operation)


class DeclarationTests(TransportCase):
    def test_shipped_declarations_parse_and_name_real_adapters(self):
        shipped = transport.parse(json.loads(Path(transport.__file__).with_name('manga_source_transport.json').read_text()))
        import manga_native_registry
        from urllib.parse import urlsplit

        profiles = manga_native_registry.profiles()
        for source, entry in shipped.items():
            self.assertIn(source, profiles, entry.name)
            root = urlsplit(profiles[source].ROOT).hostname
            self.assertTrue(any(rule.matches(root, None) for rule in entry.rules), entry.name)

    def test_invalid_declarations_are_rejected(self):
        for routes in ([{'hosts': ['10.0.0.1'], 'exit': 'direct'}], [{'hosts': ['a.jp'], 'exit': 'moon'}],
                       [{'hosts': ['a.jp'], 'operations': ['login']}], [{'hosts': ['a.jp'], 'proxy': 'http://x'}],
                       [{'hosts': ['a.jp'], 'solver': 'yes'}], [{'hosts': ['a.jp'], 'format': 'pdf'}], []):
            with self.assertRaises(ValueError, msg=routes):
                transport.parse({'version': 1, 'sources': {'1': {'routes': routes}}})
        with self.assertRaises(ValueError):
            transport.parse({'version': 1, 'sources': {'not-a-number': {'routes': [{'hosts': ['a.jp']}]}}})

    def test_admin_override_replaces_one_source_and_bad_override_is_ignored(self):
        override = self.data / 'manga-source-transport.json'
        override.write_text(json.dumps({'version': 1, 'sources': {SOKUYOMI: {'routes': [
            {'hosts': ['sokuyomi.jp'], 'exit': 'direct'}]}}}))
        self.assertEqual(transport.decide(SOKUYOMI, 'search', 'https://api.sokuyomi.jp/graphql').exit_id, 'direct')
        self.assertIsNotNone(transport.declared(MANGANATO))
        override.write_text('{"version": 1, "sources": {"1": {"routes": "everything"}}}')
        self.legacy_routes()
        self.assertEqual(transport.decide(SOKUYOMI, 'search', 'https://api.sokuyomi.jp/graphql').exit_id, 'japan:legacy')

    def test_solver_budget_only_extends_solver_sources(self):
        self.assertEqual(transport.solver_budget(MANGANATO, 18), 45)
        self.assertEqual(transport.solver_budget(SOKUYOMI, 18), 18)
        self.assertEqual(transport.solver_budget('42', 18), 18)


class RouteTests(TransportCase):
    def test_operation_and_domain_choose_the_exit(self):
        self.legacy_routes()
        site = FakeSite(lambda *_: response(200, b'{}', {'Content-Type': 'application/json'}))
        http = self.http(site, SOKUYOMI, 'chapters')
        http._open('https://api.sokuyomi.jp/graphql', action=None)[0].close()
        http._open('https://cdn.sokuyomi.jp/page/1.webp')[0].close()
        self.assertEqual(site.calls[0]['options']['proxies']['https'], 'http://suwayomi-jp-router:8080')
        self.assertNotIn('proxies', site.calls[1]['options'])
        # LINE: catalogue through Japan, page images direct on the same domain.
        with http.scope(LINE, 'catalogue'):
            http._open('https://manga.line.me/api/x')[0].close()
        with http.scope(LINE, 'images'):
            http._open('https://manga.line.me/img/1.jpg')[0].close()
        self.assertIn('proxies', site.calls[2]['options'])
        self.assertNotIn('proxies', site.calls[3]['options'])

    def test_undeclared_traffic_keeps_the_legacy_path(self):
        self.legacy_routes()
        site = FakeSite(lambda *_: response(200, b'ok'))
        http = self.http(site, '999', 'search')
        http._open('https://sokuyomi.jp/')[0].close()
        self.assertNotIn('proxies', site.calls[0]['options'])

    def test_legacy_router_never_silently_sends_an_unlisted_japan_host_direct(self):
        self.legacy_routes(hosts=('manga.line.me',))
        site = FakeSite(lambda *_: response(200, b'ok'))
        with self.assertRaises(SourceError) as caught:
            self.http(site, SOKUYOMI, 'search')._open('https://api.sokuyomi.jp/graphql')
        self.assertIn('sokuyomi.jp', str(caught.exception))
        self.assertEqual(site.calls, [])

    def test_gateway_down_is_an_explicit_temporary_failure_before_any_request(self):
        self.gateway()
        site = FakeSite(lambda *_: response(200, b'ok'))
        status = SimpleNamespace(status_code=200, json=lambda: {'ready': False, 'time': time.time()})
        with patch.object(transport.requests, 'get', return_value=status):
            with self.assertRaises(SourceRouteError) as caught:
                self.http(site, SOKUYOMI, 'search')._open('https://api.sokuyomi.jp/graphql')
        self.assertIsInstance(caught.exception, SourceTemporaryError)
        self.assertEqual(source_status(caught.exception), 'route_unavailable')
        self.assertEqual(site.calls, [])

    def test_unreachable_status_endpoint_fails_closed(self):
        self.gateway()
        with patch.object(transport.requests, 'get', side_effect=requests.ConnectionError):
            with self.assertRaises(SourceRouteError):
                transport.decide(SOKUYOMI, 'search', 'https://api.sokuyomi.jp/graphql')

    def test_proxy_refusal_maps_to_route_unavailable_and_forgets_status(self):
        self.gateway()
        status = SimpleNamespace(status_code=200, json=lambda: {'ready': True, 'country': 'JP', 'exitId': 'vpn-1'})

        def refuse(*_):
            raise requests.exceptions.ProxyError('503 tunnel down')
        with patch.object(transport.requests, 'get', return_value=status):
            with self.assertRaises(SourceRouteError):
                self.http(FakeSite(refuse), SOKUYOMI, 'search')._open('https://api.sokuyomi.jp/graphql')
        self.assertIsNone(transport._status['value'])

    def test_gateway_status_format_binds_exit_ip_and_generation(self):
        self.gateway()
        values = [{'ready': True, 'state': 'ready', 'country': 'JP', 'exit': '219.100.37.1', 'generation': 7,
                   'age': 3.0, 'fresh': True},
                  {'ready': True, 'state': 'ready', 'country': 'JP', 'exit': '219.100.37.1', 'generation': 8,
                   'age': 1.0, 'fresh': True},
                  {'ready': True, 'state': 'ready', 'country': 'JP', 'exit': '219.100.37.1', 'generation': 8,
                   'age': 200.0, 'fresh': False}]
        for expected, value in zip(('japan:7-219.100.37.1', 'japan:8-219.100.37.1', None), values):
            transport._status['time'] = 0.0
            with patch.object(transport.requests, 'get', return_value=SimpleNamespace(status_code=200, json=lambda v=value: v)):
                if expected is None:
                    with self.assertRaises(SourceRouteError):
                        transport.decide(SOKUYOMI, 'search', 'https://api.sokuyomi.jp/graphql')
                else:
                    self.assertEqual(transport.decide(SOKUYOMI, 'search', 'https://api.sokuyomi.jp/graphql').exit_id, expected)

    def test_gateway_hosts_list_is_enforced(self):
        self.gateway(hosts=['manga.line.me'])
        status = SimpleNamespace(status_code=200, json=lambda: {'ready': True, 'exitId': 'vpn-1'})
        with patch.object(transport.requests, 'get', return_value=status):
            self.assertEqual(transport.decide(LINE, 'search', 'https://manga.line.me/x').exit_id, 'japan:vpn-1')
            with self.assertRaises(SourceError):
                transport.decide(SOKUYOMI, 'search', 'https://sokuyomi.jp/')

    def test_scope_is_inherited_by_nested_and_forked_clients(self):
        outer = PublicHttp(timeout=(1, 1))
        with outer.scope(MANGANATO, 'chapters'):
            inner = PublicHttp(timeout=(1, 1))
            self.assertEqual((inner.source, inner.operation), (MANGANATO, 'chapters'))
            self.assertEqual(outer.fork().source, MANGANATO)
        self.assertIsNone(outer.source)
        self.assertIsNone(PublicHttp(timeout=(1, 1)).source)

    def test_page_images_find_their_source_by_referer(self):
        adapter = SimpleNamespace(SOURCE_ID=SOKUYOMI)
        with patch.dict(sys.modules, {'manga_native_sources': SimpleNamespace(for_url=lambda url: adapter)}):
            http = PublicHttp(timeout=(1, 1))
            self.assertEqual(transport.resolve(http, 'https://cdn.sokuyomi.jp/p.webp',
                                               {'Referer': 'https://sokuyomi.jp/comics/a/1/'}, None), (SOKUYOMI, 'images'))
            # Undeclared hosts never trigger the lookup.
            self.assertEqual(transport.resolve(http, 'https://other.example/p.webp',
                                               {'Referer': 'https://sokuyomi.jp/'}, None), (None, None))


class SolverTests(TransportCase):
    def challenged_until_cleared(self, page=TITLE_PAGE):
        def answer(method, url, headers, options):
            if cleared(headers, options):
                return response(200, page)
            return response(403, CHALLENGE_PAGE, {'Content-Type': 'text/html', 'Server': 'cloudflare',
                                                  'cf-mitigated': 'challenge'})
        return FakeSite(answer)

    def test_challenge_runs_solver_then_retries_with_cookies_and_user_agent(self):
        site = self.challenged_until_cleared()
        with patch.object(transport.requests, 'post', side_effect=byparr()) as solver:
            text, final, _ = self.http(site, MANGANATO, 'chapters').document('https://www.natomanga.com/manga/solo')
        self.assertIn('Solo Leveling', text)
        self.assertEqual(final, 'https://www.natomanga.com/manga/solo')
        self.assertEqual(solver.call_count, 1)
        body, headers = solver.call_args.kwargs['json'], solver.call_args.kwargs['headers']
        self.assertEqual(body['url'], 'https://www.natomanga.com/manga/solo')
        self.assertNotIn('X-Proxy-Server', headers)
        retry = site.calls[-1]
        self.assertEqual(retry['headers']['User-Agent'], UA)
        self.assertEqual(retry['options']['cookies'], {'cf_clearance': 'ok'})  # foreign-domain cookie dropped
        # The next request reuses the session without another solver run.
        with patch.object(transport.requests, 'post', side_effect=byparr()) as again:
            self.http(site, MANGANATO, 'search').document('https://www.natomanga.com/search/story/solo')
        again.assert_not_called()
        self.assertEqual(len(site.calls), 3)

    def test_concurrent_requests_wait_on_one_solver_run(self):
        site = self.challenged_until_cleared()
        errors, texts = [], []

        def read(index):
            try:
                texts.append(self.http(site, MANGANATO, 'chapters').document(
                    f'https://www.natomanga.com/manga/t{index}')[0])
            except Exception as error:  # pragma: no cover - reported below
                errors.append(error)
        with patch.object(transport.requests, 'post', side_effect=byparr(delay=0.3)) as solver:
            threads = [threading.Thread(target=read, args=(i,)) for i in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(len(texts), 6)
        self.assertEqual(solver.call_count, 1)

    def test_japan_solver_uses_the_same_exit_and_an_exit_change_resets_sessions(self):
        self.gateway()
        exits = ['vpn-1']

        def status(*_args, **_kw):
            current = exits[0]
            return SimpleNamespace(status_code=200, json=lambda: {'ready': True, 'country': 'JP', 'exitId': current})

        def answer(method, url, headers, options):
            if cleared(headers, options):
                return response(200, b'{"ok": true}', {'Content-Type': 'application/json'})
            return response(503, CHALLENGE_PAGE, {'Server': 'cloudflare', 'Content-Type': 'text/html'})
        site = FakeSite(answer)

        def solved(endpoint, json=None, headers=None, **_):
            value = requests.Response()
            value.status_code = 200
            value._content = __import__('json').dumps({'status': 'ok', 'solution': {
                'url': json['url'], 'userAgent': UA, 'response': '',
                'cookies': [{'name': 'cf_clearance', 'value': 'ok', 'domain': 'manga.line.me'}]}}).encode()
            return value
        with patch.object(transport.requests, 'get', side_effect=status), \
                patch.object(transport.requests, 'post', side_effect=solved) as solver:
            http = self.http(site, LINE, 'search')
            http._open('https://manga.line.me/api/search_product/list?word=a&page=1')[0].close()
            self.assertEqual(solver.call_args.kwargs['headers']['X-Proxy-Server'], 'http://jp-gateway:8080')
            self.assertTrue(all(c['options']['proxies']['https'] == 'http://jp-gateway:8080' for c in site.calls))
            key = (LINE, 'manga.line.me', 'japan:vpn-1')
            self.assertIsNotNone(transport.sessions.get(key))
            exits[0] = 'vpn-2'
            transport._status['time'] = 0.0  # status cache expired: the gateway reports a new exit
            transport.decide(LINE, 'search', 'https://manga.line.me/api/x')
            self.assertIsNone(transport.sessions.get(key))

    def test_rejected_cookies_fall_back_to_solver_html_only_for_pages(self):
        site = FakeSite(lambda *_: response(403, CHALLENGE_PAGE, {'Server': 'cloudflare', 'Content-Type': 'text/html'}))
        with patch.object(transport.requests, 'post', side_effect=byparr()) as solver:
            text, _, headers = self.http(site, MANGANATO, 'chapters').document('https://www.natomanga.com/manga/solo')
            self.assertIn('Solo Leveling', text)
            self.assertEqual(headers.get('X-MediaVault-Solver'), '1')
            # A JSON request never receives solver HTML.
            with self.assertRaises(SourceChallengeError) as caught,                     patch('manga_series_port.series_api', return_value=True):
                self.http(site, MANGANATO, 'chapters').document('https://www.natomanga.com/api/manga/solo/chapters',
                                                                 action='native-series-json')
            self.assertEqual(caught.exception.solver, 'rejected')
            # Nor does an image read through the raw stream.
            with self.assertRaises(SourceChallengeError):
                self.http(site, MANGANATO, 'images')._open('https://www.natomanga.com/img/1.jpg')
        # One solver run: its HTML served the page; later requests reuse the
        # verdict that this site refuses the cookies instead of re-solving.
        self.assertEqual(solver.call_count, 1)

    def test_challenge_without_declared_solver_is_reported_not_solved(self):
        site = FakeSite(lambda *_: response(403, CHALLENGE_PAGE, {'Server': 'cloudflare', 'Content-Type': 'text/html'}))
        with patch.object(transport.requests, 'post') as solver:
            with self.assertRaises(SourceChallengeError) as caught:
                self.http(site, None, None).document('https://example.org/title')
        solver.assert_not_called()
        self.assertIsInstance(caught.exception, SourceAccessError)
        self.assertEqual(caught.exception.solver, 'none')

    def test_solver_failure_is_cached_for_a_cooldown(self):
        site = self.challenged_until_cleared()
        with patch.object(transport.requests, 'post', side_effect=byparr(status=500)) as solver:
            for _ in range(2):
                with self.assertRaises(SourceChallengeError):
                    self.http(site, MANGANATO, 'chapters').document('https://www.natomanga.com/manga/solo')
        self.assertEqual(solver.call_count, 1)

    def test_solver_unavailable_and_short_budget_are_distinct(self):
        site = self.challenged_until_cleared()
        with patch.object(transport.requests, 'post', side_effect=requests.ConnectionError):
            with self.assertRaises(SourceChallengeError) as caught:
                self.http(site, MANGANATO, 'chapters').document('https://www.natomanga.com/manga/a')
        self.assertEqual(caught.exception.solver, 'unavailable')
        transport.sessions.clear()
        with patch.object(transport.requests, 'post', side_effect=requests.ReadTimeout):
            with self.assertRaises(SourceChallengeError) as caught:
                self.http(site, MANGANATO, 'chapters').document('https://www.natomanga.com/manga/t')
        self.assertEqual(caught.exception.solver, 'timeout')
        transport.sessions.clear()
        with patch.object(transport.requests, 'post') as solver:
            with self.assertRaises(SourceChallengeError) as caught:
                self.http(site, MANGANATO, 'chapters', deadline=time.monotonic() + 4).document(
                    'https://www.natomanga.com/manga/b')
        solver.assert_not_called()
        self.assertEqual(caught.exception.solver, 'budget')

    def test_solver_answer_for_another_site_is_rejected(self):
        site = self.challenged_until_cleared()

        def elsewhere(endpoint, json=None, **_):
            value = requests.Response()
            value.status_code = 200
            value._content = __import__('json').dumps({'status': 'ok', 'solution': {
                'url': 'https://evil.example/', 'userAgent': UA, 'cookies': []}}).encode()
            return value
        with patch.object(transport.requests, 'post', side_effect=elsewhere):
            with self.assertRaises(SourceChallengeError):
                self.http(site, MANGANATO, 'chapters').document('https://www.natomanga.com/manga/a')

    def test_solved_cookies_never_follow_a_redirect_to_another_host(self):
        def answer(method, url, headers, options):
            if url.startswith('https://www.natomanga.com/'):
                if cleared(headers, options):
                    return response(302, b'', {'Location': 'https://cdn.example.net/next'})
                return response(403, CHALLENGE_PAGE, {'Server': 'cloudflare', 'Content-Type': 'text/html'})
            return response(200, b'<html>next</html>')
        site = FakeSite(answer)
        with patch.object(transport.requests, 'post', side_effect=byparr()):
            self.http(site, MANGANATO, 'chapters').document('https://www.natomanga.com/manga/solo')
        last = site.calls[-1]
        self.assertEqual(last['url'], 'https://cdn.example.net/next')
        self.assertNotEqual(last['headers'].get('User-Agent'), UA)
        self.assertNotIn('cookies', last['options'])

    def test_post_challenge_is_solved_on_the_site_root(self):
        def answer(method, url, headers, options):
            if cleared(headers, options):
                return response(200, b'<ul class="chapters"></ul>')
            return response(403, CHALLENGE_PAGE, {'Server': 'cloudflare', 'Content-Type': 'text/html'})
        site = FakeSite(answer)
        with patch.object(transport.requests, 'post', side_effect=byparr()) as solver:
            http = self.http(site, MANGANATO, 'chapters')
            # A POST form accepted by the legacy validators (Madara's admin-ajax).
            with patch('manga_madara.ajax_form', return_value=True):
                http.document('https://www.natomanga.com/wp-admin/admin-ajax.php', method='POST',
                              data={'action': 'manga_get_chapters', 'manga': '1'}, action='madara-read')
        self.assertEqual(solver.call_args.kwargs['json']['url'], 'https://www.natomanga.com/')
        self.assertEqual(site.calls[-1]['method'], 'POST')


class SlotTests(TransportCase):
    def test_solver_slots_are_shared_through_file_locks(self):
        try:
            import fcntl  # noqa: F401
        except ImportError:
            self.skipTest('flock slots exist only on the Linux importer')
        # Separate open files conflict under flock even inside one process,
        # exactly as the importer and a side process do.
        with patch.dict(os.environ, {'SOURCE_SOLVER_SLOTS': str(self.data)}),                 patch.object(transport.sessions, 'slots', threading.BoundedSemaphore(5)):
            first, second = transport.acquire_slot(1), transport.acquire_slot(1)
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertIsNone(transport.acquire_slot(0.3))
            first()
            third = transport.acquire_slot(1)
            self.assertIsNotNone(third)
            second()
            third()

    def test_without_flock_the_process_limit_still_applies(self):
        with patch.dict(sys.modules, {'fcntl': None}),                 patch.object(transport.sessions, 'slots', threading.BoundedSemaphore(1)):
            release = transport.acquire_slot(0.1)
            self.assertIsNotNone(release)
            self.assertIsNone(transport.acquire_slot(0.1))
            release()


class StatusTests(TransportCase):
    def open(self, status, body=b'', headers=None):
        site = FakeSite(lambda *_: response(status, body, headers or {'Content-Type': 'text/html'}))
        return self.http(site).document('https://example.org/chapter/1')

    def test_distinct_statuses(self):
        cases = [
            (429, b'slow down', {'Retry-After': '30'}, SourceRateLimitError, 'rate_limited'),
            (451, b'Unavailable For Legal Reasons', None, SourceRegionError, 'region_blocked'),
            (403, b'<title>Access denied</title> error code: 1009', None, SourceRegionError, 'region_blocked'),
            (401, b'{"error": "unauthorized"}', None, SourceAuthError, 'auth_required'),
            (403, CHALLENGE_PAGE, {'Server': 'cloudflare', 'Content-Type': 'text/html'}, SourceChallengeError, 'challenge'),
            (200, b'{"requires_subscription": true}', {'Content-Type': 'application/json'}, SourcePaidError, 'paid_chapter'),
            (200, b'{"requires_authentication": true}', {'Content-Type': 'application/json'}, SourceAuthError, 'auth_required'),
        ]
        for status, body, headers, error, name in cases:
            with self.subTest(status=status, name=name):
                with self.assertRaises(error) as caught:
                    self.open(status, body, headers)
                self.assertEqual(source_status(caught.exception), name)

    def test_retry_after_date_on_service_unavailable(self):
        from email.utils import formatdate
        with self.assertRaises(SourceRateLimitError) as caught:
            self.open(503, b'wait', {'Retry-After': formatdate(time.time() + 1800, usegmt=True)})
        self.assertGreaterEqual(caught.exception.retry_after, 1798)
        self.assertLessEqual(caught.exception.retry_after, 1800)

    def test_challenge_header_prevents_successful_body_from_reaching_parser(self):
        with self.assertRaises(SourceChallengeError):
            self.open(200, b'<html>challenge</html>', {'cf-mitigated': 'challenge'})

    def test_region_words_on_an_ordinary_page_are_not_a_block(self):
        text, _, _ = self.open(200, b'<p>This manga is only available in Japan as a print edition.</p>')
        self.assertIn('only available', text)

    def test_parser_and_route_statuses(self):
        self.assertEqual(source_status(SourceError('Источник изменил формат ответа каталога.')), 'parser_error')
        self.assertEqual(source_status(ValueError('bad json')), 'parser_error')
        self.assertEqual(source_status(SourceRouteError('down')), 'route_unavailable')
        self.assertEqual(source_status(SourceTemporaryError('HTTP 502')), 'temporary')
        self.assertEqual(source_status(SourceError('Источник вернул HTTP 404.')), 'error')

    def test_ordinary_errors_keep_their_old_types_and_messages(self):
        with self.assertRaises(SourceAccessError) as caught:
            self.open(403, b'forbidden')
        self.assertEqual(type(caught.exception), SourceAccessError)
        with self.assertRaises(SourceTemporaryError):
            self.open(503, b'maintenance')
        with self.assertRaises(SourceError) as caught:
            self.open(404, b'missing')
        self.assertEqual(str(caught.exception), 'Источник вернул HTTP 404.')


class FakeCurlAnswer:
    def __init__(self, status=200, body=TITLE_PAGE, headers=None, cookies=None):
        self.status_code, self.content = status, body
        self.headers = headers or {'Content-Type': 'text/html; charset=utf-8'}
        self.cookies = cookies or {}
        self.reason = 'OK'


class FakeCurlSession:
    """curl_cffi Session stand-in: records requests, answers from a queue."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def request(self, method, url, **options):
        self.calls.append({'method': method, 'url': url, **options})
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class ImpersonatedTlsTests(TransportCase):
    NATO_TLS = {'version': 1, 'sources': {MANGANATO: {'name': 'Manganato', 'solverBudget': 45, 'routes': [
        {'hosts': ['natomanga.com'], 'operations': ['*'], 'exit': 'direct', 'solver': True, 'format': 'html',
         'tls': 'chrome'}]}}}

    def setUp(self):
        super().setUp()
        self.declarations.write_text(json.dumps(self.NATO_TLS))
        transport._declared.update(key=None, value={})

    def test_tls_profile_is_validated(self):
        rule = transport.parse_rule({'hosts': ['example.org'], 'tls': 'chrome'})
        self.assertEqual(rule.tls, 'chrome')
        self.assertEqual(transport.parse_rule({'hosts': ['example.org']}).tls, '')
        with self.assertRaises(ValueError):
            transport.parse_rule({'hosts': ['example.org'], 'tls': 'netscape'})

    def test_declared_route_sends_a_browser_fingerprint_without_our_user_agent(self):
        site = FakeSite(lambda *a: self.fail('plain requests must not be used for a TLS route'))
        curl = FakeCurlSession(FakeCurlAnswer())
        with patch.object(transport, '_impersonating_session', return_value=curl) as factory:
            text, final, _ = self.http(site, MANGANATO, 'details').document('https://www.natomanga.com/manga/solo')
        self.assertIn('Solo Leveling', text)
        self.assertEqual(final, 'https://www.natomanga.com/manga/solo')
        factory.assert_called_with('chrome')
        sent = curl.calls[0]
        self.assertFalse(sent['allow_redirects'])
        self.assertNotIn('user-agent', {k.lower() for k in sent['headers']})
        self.assertEqual(site.calls, [])

    def test_challenge_on_a_tls_route_still_goes_to_the_solver_and_replays_its_agent(self):
        curl = FakeCurlSession(FakeCurlAnswer(403, CHALLENGE_PAGE, {'Content-Type': 'text/html', 'Server': 'cloudflare'}),
                               FakeCurlAnswer())
        with patch.object(transport, '_impersonating_session', return_value=curl), \
                patch.object(transport.requests, 'post', side_effect=byparr()) as solver:
            text, _, _ = self.http(FakeSite(lambda *a: None), MANGANATO, 'chapters').document(
                'https://www.natomanga.com/manga/solo')
        self.assertIn('Solo Leveling', text)
        self.assertEqual(solver.call_count, 1)
        retry = curl.calls[-1]
        self.assertEqual(retry['headers']['User-Agent'], UA)
        self.assertEqual(retry['cookies'], {'cf_clearance': 'ok'})

    def test_curl_errors_keep_the_ordinary_temporary_failure(self):
        from curl_cffi.requests import exceptions as curl_errors

        class Broken(FakeCurlSession):
            def request(self, method, url, **options):
                raise curl_errors.Timeout('slow')

        with patch.object(transport, '_impersonating_session', return_value=Broken()):
            with self.assertRaises(SourceTemporaryError):
                self.http(FakeSite(lambda *a: None), MANGANATO, 'details').document('https://www.natomanga.com/manga/solo')

    def test_oversized_answer_is_refused(self):
        curl = FakeCurlSession(FakeCurlAnswer(body=b'x' * (transport.MAX_IMPERSONATED + 1)))
        with patch.object(transport, '_impersonating_session', return_value=curl):
            with self.assertRaises(SourceError):
                self.http(FakeSite(lambda *a: None), MANGANATO, 'details').document('https://www.natomanga.com/manga/solo')

    def test_shipped_tls_routes(self):
        shipped = transport.parse(json.loads(Path(transport.__file__).with_name('manga_source_transport.json')
                                             .read_text(encoding='utf-8')))
        for source, host in (('6384784374922886076', 'g.nude-moon.fun'), ('4306337471481207984', 'lgbtics.com'),
                             ('15083818169656208', 'mgread.io')):
            self.assertEqual(shipped[source].rule(host, 'catalogue').tls, 'chrome', source)

    def test_firefox_profile_maps_to_the_newest_firefox_target(self):
        target = transport.impersonation_target('firefox')
        self.assertRegex(target, r'^firefox[0-9]+$')
        from curl_cffi.requests.impersonate import BrowserType
        newest = max(int(b.value[7:]) for b in BrowserType if re.fullmatch(r'firefox[0-9]+', b.value))
        self.assertEqual(target, f'firefox{newest}')
        self.assertEqual(transport.impersonation_target('chrome'), 'chrome')

    def test_solver_routes_replay_cookies_with_the_solvers_browser_family(self):
        # Byparr answers as Firefox; its cookies must travel with a Firefox handshake.
        shipped = transport.parse(json.loads(Path(transport.__file__).with_name('manga_source_transport.json')
                                             .read_text(encoding='utf-8')))
        solver_rules = [rule for entry in shipped.values() for rule in entry.rules if rule.solver]
        self.assertGreater(len(solver_rules), 100)
        for rule in solver_rules:
            self.assertIn(rule.tls, {'firefox', 'chrome'}, rule.hosts)
        self.assertEqual(sum(rule.tls == 'chrome' for rule in solver_rules), 1)  # mgread.io opens with Chrome alone
