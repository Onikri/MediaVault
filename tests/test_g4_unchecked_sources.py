"""G4: cards of sources behind a browser check get their declared solver budget.

No network. Live finding (G4, 2026-11-26, oracle-importer-1): a HentaiRead and a
Toonz card opened at the same time both failed with "Решатель не успел пройти
проверку браузера" after 28 s, while each passed alone in 18-20 s. A card
(manga_sources.inspect without a caller's client) had a fixed 32 s deadline, so
Byparr got ~21 s; search and catalogue requests of the same sources already used
source_transport.solver_budget (45 s by default). The site, Byparr and the
TLS-impersonating client are fakes; fixtures hentairead-title.html and
hentairead-reader.html follow the adapter's selectors. The path is index row ->
reader dispatch -> card -> chapter -> pages -> first image bytes
(manga_readability.verify, the client's verifyPages path).
"""
import json
import os
import sys
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))

import requests

import manga_readability
import manga_sources
import source_transport as transport
from source_parser import PublicHttp
from title_identity import match_title

FIXTURES = Path(__file__).parent / 'fixtures'
JPEG = b'\xff\xd8\xff\xe0\x00\x10JFIF' + b'\x00' * 64
UA = 'Mozilla/5.0 (X11; Linux aarch64; rv:140.0) Gecko/20100101 Firefox/140.0'
CHALLENGE = (b'<html><head><title>Just a moment...</title></head><body>'
             b'<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script></body></html>')

HENTAIREAD = '2299981010822511979'
TOONZ = '225310046014902430'
ROW = {'provider': 'suwayomi:' + HENTAIREAD, 'title': 'Yoiko to Ikenai Houkago',
       'sourceUrl': 'https://hentairead.com/hentai/yoiko-to-ikenai-houkago/?mv_manga_source=' + HENTAIREAD}
TITLE = 'https://hentairead.com/hentai/yoiko-to-ikenai-houkago/'
READER = TITLE + 'english/p/1/'
CDN = 'https://cdn-ht.hentairead.io/galleries/129139/'


def fixture(name):
    return (FIXTURES / name).read_bytes()


class CurlAnswer:
    def __init__(self, status, body, ctype):
        self.status_code, self.content, self.headers = status, body, {'Content-Type': ctype}
        self.cookies, self.reason = {}, 'OK'
        if status == 403:
            self.headers.update({'Server': 'cloudflare', 'cf-mitigated': 'challenge'})


class HentaiReadSite:
    """curl_cffi stand-in for hentairead.com: Cloudflare until Byparr's cookies and agent arrive."""

    def __init__(self):
        self.calls = []

    def request(self, method, url, headers=None, cookies=None, **_):
        self.calls.append((method, url))
        assert method == 'GET', method
        if (cookies or {}).get('cf_clearance') != 'ok' or (headers or {}).get('User-Agent') != UA:
            return CurlAnswer(403, CHALLENGE, 'text/html; charset=UTF-8')
        if url == TITLE:
            return CurlAnswer(200, fixture('hentairead-title.html'), 'text/html; charset=utf-8')
        if url == READER:
            return CurlAnswer(200, fixture('hentairead-reader.html'), 'text/html; charset=utf-8')
        return CurlAnswer(404, b'', 'text/html')


class Byparr:
    def __init__(self):
        self.budgets = []

    def __call__(self, endpoint, json=None, headers=None, timeout=None, allow_redirects=None):
        assert json['cmd'] == 'request.get', json
        self.budgets.append(json['maxTimeout'])
        payload = {'status': 'ok', 'solution': {
            'url': json['url'], 'status': 200, 'userAgent': UA, 'response': '',
            'cookies': [{'name': 'cf_clearance', 'value': 'ok', 'domain': '.hentairead.com', 'path': '/'}]}}
        value = requests.Response()
        value.status_code = 200
        value._content = __import__('json').dumps(payload).encode()
        return value


def cdn_image(self, method, url, **_):
    assert method == 'GET' and url.startswith(CDN), url
    value = requests.Response()
    value.status_code = 200
    value.headers['Content-Type'] = 'image/jpeg'
    value.raw = BytesIO(JPEG)
    value.url = url
    return value


def offline_http(**options):
    # The default client of a card, minus the DNS check of the public-host guard.
    return PublicHttp(validate=lambda value: value, **options)


class SolverCardBudget(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'DATA_DIR': self.temp.name, 'SOURCE_SOLVER_SLOTS': self.temp.name})
        self.env.start()
        transport._declared.update(key=None, value={})
        transport.sessions.clear()

    def tearDown(self):
        self.env.stop()
        transport._declared.update(key=None, value={})
        transport.sessions.clear()
        self.temp.cleanup()

    def test_cards_behind_a_browser_check_use_the_declared_solver_budget(self):
        self.assertEqual(manga_sources.card_deadline(ROW['sourceUrl']), 45)
        self.assertEqual(manga_sources.card_deadline(
            'https://toonz.to/manhwa/wang-you-zhi-zui-qiang-lie-ren?mv_manga_source=' + TOONZ), 45)
        # Sources without a solver route keep the plain card deadline.
        self.assertEqual(manga_sources.card_deadline(
            'https://comic.naver.com/challenge/list?titleId=666409&mv_manga_source=4487676425355815867'), 32)
        self.assertEqual(manga_sources.card_deadline('https://mangalib.me/ru/595--vampire-juuji-kai'), 32)
        self.assertEqual(manga_sources.card_deadline('not a url'), 32)

    def test_index_row_opens_card_chapter_and_a_page_after_the_browser_check(self):
        site, solver = HentaiReadSite(), Byparr()
        with patch.object(transport, '_impersonating_session', return_value=site), \
                patch.object(transport.requests, 'post', side_effect=solver), \
                patch.object(manga_sources, 'PublicHttp', offline_http), \
                patch.object(requests.Session, 'request', cdn_image):
            self.assertEqual(manga_sources.site_for(ROW['sourceUrl']).id, ROW['provider'])
            card = manga_sources.inspect(ROW['sourceUrl'])
            self.assertTrue(match_title({'title': ROW['title'], 'aliases': [ROW['title']], 'kind': 'manga'},
                                        {'title': card['title'], 'aliases': card.get('aliases') or [], 'kind': 'manga'})[0])
            self.assertEqual([e['url'] for e in card['episodes']], [TITLE + '?mv_hr=1&mv_manga_source=' + HENTAIREAD])
            with patch.object(manga_readability, 'PublicHttp', offline_http), \
                    patch.dict(manga_readability._cache, {}, clear=True):
                result = manga_readability.verify(card)
        self.assertTrue(result['readable'], result)
        # One browser check for the card; the chapter reuses its session.
        self.assertEqual(len(solver.budgets), 1)
        # Byparr may take ~35 s now; with the old fixed 32 s card it got under 22 s.
        self.assertGreaterEqual(solver.budgets[0], 30000)
        self.assertLessEqual(solver.budgets[0], 60000)
        self.assertTrue(all(method == 'GET' and url.startswith('https://hentairead.com/') for method, url in site.calls))
        self.assertEqual(site.calls[:2], [('GET', TITLE)] * 2)
        self.assertIn(('GET', READER), site.calls)

    def test_a_caller_client_keeps_its_own_deadline(self):
        http = offline_http(timeout=(3, 6), deadline=time.monotonic() + 20)
        seen = []

        def fake(self, url, given):
            seen.append(given.deadline)
            return {'title': 'x', 'episodes': [], 'pages': []}

        adapter = manga_sources.site_for(ROW['sourceUrl'])
        self.assertEqual(adapter.family, 'native')
        import manga_native_sources
        native = manga_native_sources.for_url(ROW['sourceUrl'])
        with patch.object(type(native), 'inspect', fake):
            manga_sources.inspect(ROW['sourceUrl'], http)
        self.assertEqual(seen, [http.deadline])


if __name__ == '__main__':
    unittest.main()
