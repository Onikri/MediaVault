"""G2: index rows of HentaiMoody, Hentaros, Yaoi.me and AllHentai open in the reader.

No network. Fixtures are trimmed copies of the live pages fetched from the
Oracle importer on 2026-11-26 (tests/fixtures/hentaimoody-*, hentaros-*,
yaoime-series.html, allhentai-title.html); the upstream sites, Byparr and the
TLS-impersonating client are fake objects. Each source goes index row ->
reader dispatch -> card -> chapters -> chapter pages -> first image bytes
(manga_readability.verify, the client's verifyPages path).
"""
import base64
from contextlib import closing
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import manga_hentaimoody as moody
import manga_hentaros as ros
import manga_native_sources
import manga_readability
import manga_ru_families
import manga_sources
import manga_yaoime
import source_transport as transport
import suwayomi_legacy
from source_parser import PublicHttp, SourceAuthError, SourceError
from title_identity import match_title

FIXTURES = Path(__file__).parent / 'fixtures'
JPEG = b'\xff\xd8\xff\xe0\x00\x10JFIF' + b'\x00' * 64


def fixture(name):
    return (FIXTURES / name).read_text(encoding='utf-8')


def image_response(url):
    value = requests.Response()
    value.status_code = 200
    value.headers['Content-Type'] = 'image/jpeg'
    value.raw = BytesIO(JPEG)
    value.url = url
    return value


class Http:
    """PublicHttp stand-in for the HTML adapters: answers by exact URL."""

    def __init__(self, pages, images=()):
        self.pages, self.images = pages, set(images)
        self.calls, self.opened = [], []
        self.deadline = time.monotonic() + 30

    def document(self, url, headers=None, **_):
        self.calls.append(url)
        if url not in self.pages:
            error = SourceError('Источник вернул HTTP 404.')
            error.http_status = 404
            raise error
        return self.pages[url], url, {}

    def _open(self, url, headers=None, **_):
        self.opened.append((url, dict(headers or {})))
        if url not in self.images:
            raise SourceError('Источник вернул HTTP 404.')
        return image_response(url), url

    def close(self):
        pass


def same_work(row, value):
    card = {'title': row['title'], 'aliases': [row['title']], 'kind': 'manga'}
    page = {'title': value['title'], 'aliases': value.get('aliases') or [value['title']], 'kind': 'manga'}
    return match_title(card, page)[0]


def verify(value, http):
    with patch.object(manga_readability, 'PublicHttp', lambda **_: http), \
            patch.dict(manga_readability._cache, {}, clear=True):
        return manga_readability.verify(value)


# ---------------------------------------------------------------- HentaiMoody

MOODY_TITLE = 'https://online.hentaimoody.com/312452-shiiku-hime.html'
MOODY_CHAPTERS = 'https://json.imghmd.link/json-fullstory/m3/shiiku-hime.json?v=6jh6s'
MOODY_READER = 'https://online.hentaimoody.com/312453/mangaonline'
MOODY_IMAGES = 'https://json.imghmd.link/images/manga3/2484/v1/c1/images.json?v=6jh6s'
MOODY_ROW = {'provider': 'online.hentaimoody.com', 'sourceUrl': MOODY_TITLE, 'title': 'Госпожа хозяйка'}


class HentaiMoodyReads(unittest.TestCase):
    def setUp(self):
        self.pages = {MOODY_TITLE: fixture('hentaimoody-title.html'),
                      MOODY_CHAPTERS: fixture('hentaimoody-chapters.json'),
                      MOODY_READER: fixture('hentaimoody-reader.html'),
                      MOODY_IMAGES: fixture('hentaimoody-images.json')}
        self.first_page = json.loads(self.pages[MOODY_IMAGES])[0]['url']

    def test_index_row_opens_card_chapters_and_a_page(self):
        site = manga_sources.site_for(MOODY_ROW['sourceUrl'])
        self.assertEqual((site.family, site.id), ('hentaimoody', MOODY_ROW['provider']))
        http = Http(self.pages, [self.first_page])
        card = manga_sources.inspect(MOODY_ROW['sourceUrl'], http)
        self.assertEqual(card['provider'], MOODY_ROW['provider'])
        self.assertEqual(card['title'], 'Госпожа хозяйка')
        self.assertTrue(same_work(MOODY_ROW, card))
        self.assertIn('Shiiku Hime', card['aliases'])
        self.assertEqual(card['pages'], [])
        # The work's container entry (312452, all 189 pages) is not a chapter.
        self.assertEqual([(e['url'], e['season'], e['number']) for e in card['episodes']], [
            ('https://online.hentaimoody.com/312453/mangaonline', 1, 1.0),
            ('https://online.hentaimoody.com/312454/mangaonline', 1, 2.0),
            ('https://online.hentaimoody.com/312455/mangaonline', 1, 3.0),
            ('https://online.hentaimoody.com/312456/mangaonline', 1, 3.5)])
        self.assertEqual(http.calls, [MOODY_TITLE, MOODY_CHAPTERS])

        chapter = manga_sources.inspect(card['episodes'][0]['url'], http)
        self.assertEqual(chapter['title'], 'Госпожа хозяйка Том - 1 Глава - 1')
        self.assertEqual(chapter['titleUrl'], 'https://online.hentaimoody.com/312453-shiiku-hime-tom-1-glava-1.html')
        self.assertEqual(len(chapter['pages']), 3)
        for page in chapter['pages']:
            self.assertRegex(page, r'^https://img\.hreadme\.org/media/[0-9a-f]{2}/[0-9a-f]{64}\.jpg$')

        result = verify(card, Http(self.pages, [self.first_page]))
        self.assertEqual((result['readable'], result['verifiedPages'], result['verifiedChapterUrl']),
                         (True, 1, MOODY_READER))

    def test_page_image_is_requested_with_its_reader_as_referer(self):
        http = Http(self.pages, [self.first_page])
        verify(manga_sources.inspect(MOODY_TITLE, http), http)
        self.assertEqual(http.opened, [(self.first_page, {'Referer': MOODY_READER})])

    def test_hosts_and_paths_are_strict(self):
        for url in ('https://evil.example/312452-shiiku-hime.html', 'http://online.hentaimoody.com/312452-x.html',
                    'https://online.hentaimoody.com/page/2/', 'https://online.hentaimoody.com/index.php?do=register'):
            with self.assertRaises(SourceError, msg=url):
                moody.own_url(url)
        foreign = self.pages[MOODY_TITLE].replace(MOODY_CHAPTERS, 'https://evil.example/json-fullstory/m3/x.json')
        with self.assertRaises(SourceError):
            moody.inspect(MOODY_TITLE, Http({**self.pages, MOODY_TITLE: foreign}))
        images = json.loads(self.pages[MOODY_IMAGES])
        images[1]['url'] = 'https://tracker.example/media/aa/' + 'a' * 64 + '.jpg'
        with self.assertRaises(SourceError):
            moody.inspect(MOODY_READER, Http({**self.pages, MOODY_IMAGES: json.dumps(images)}))
        self.assertEqual(moody.image_url('https://img.hreadme.org/media/25/x.php'), '')
        # Relative entries live on the reader's CDN, like the site's reader.bundle.js reads them.
        self.assertEqual(moody.image_url('/online/manga3/1/c1/001.webp'), 'https://2img.imghmd.link/online/manga3/1/c1/001.webp')
        self.assertEqual(moody.image_url('//evil.example/a.jpg'), '')

    def test_chapter_without_uploaded_pages_says_so(self):
        # Live 2026-11-26: images.json of all three first chapters of one work answered 404.
        with self.assertRaisesRegex(SourceError, 'ещё не выложил страницы'):
            moody.inspect(MOODY_READER, Http({MOODY_READER: self.pages[MOODY_READER]}))

    def test_single_chapter_work_and_login_wall(self):
        lone = {'316624': [{'title': 'Гарем', 'volume': 0.0, 'chapter': 0.0, 'category': 4, 'chapter_value_link': ''}]}
        rows, container = moody.chapters(lone)
        self.assertEqual([(r['url'], r['number']) for r in rows], [('https://online.hentaimoody.com/316624/mangaonline', 1.0)])
        self.assertEqual(container, '')
        wall = '<html><body><p>Читать мангу могут только зарегистрированные пользователи.</p></body></html>'
        with self.assertRaises(SourceAuthError):
            moody.inspect(MOODY_READER, Http({MOODY_READER: wall}))


# ---------------------------------------------------------------- Hentaros

ROS_GALLERY = 'https://hentaros.com/comin-home'
ROS_ROW = {'provider': 'hentaros.com', 'sourceUrl': ROS_GALLERY, 'title': 'Возвращение домой'}


class HentarosReads(unittest.TestCase):
    def setUp(self):
        self.pages = {ROS_GALLERY: fixture('hentaros-gallery.html')}

    def test_index_row_opens_gallery_as_one_chapter_with_pages(self):
        site = manga_sources.site_for(ROS_ROW['sourceUrl'])
        self.assertEqual((site.family, site.id), ('hentaros', ROS_ROW['provider']))
        card = manga_sources.inspect(ROS_ROW['sourceUrl'], Http(self.pages))
        self.assertEqual(card['provider'], ROS_ROW['provider'])
        self.assertTrue(same_work(ROS_ROW, card))
        self.assertIn("Comin' Home", card['aliases'])
        self.assertIn('Эротика', card['tags'])
        self.assertEqual([e['url'] for e in card['episodes']], [ROS_GALLERY])
        self.assertEqual(card['pages'], [f'https://hentaros.com/img/img2971_{n}.jpg' for n in range(3)])
        self.assertEqual(card['cover'], 'https://hentaros.com/img/img2971_0.jpg')
        http = Http(self.pages, [card['pages'][0]])
        result = verify(card, http)
        self.assertEqual((result['readable'], result['verifiedChapterUrl']), (True, ROS_GALLERY))
        self.assertEqual(http.opened, [(card['pages'][0], {'Referer': ROS_GALLERY})])

    def test_hosts_and_paths_are_strict(self):
        for url in ('https://hentaros.com/tag', 'https://hentaros.com/tag/milf', 'https://hentaros.com/',
                    'https://evil.example/comin-home', 'http://hentaros.com/comin-home'):
            with self.assertRaises(SourceError, msg=url):
                ros.gallery_url(url)
        foreign = self.pages[ROS_GALLERY].replace('https://hentaros.com/img/img2971_1.jpg',
                                                  'https://cdn.evil.example/img/img2971_1.jpg')
        with self.assertRaises(SourceError):
            ros.inspect(ROS_GALLERY, Http({ROS_GALLERY: foreign}))

    def test_card_readers_stay_out_of_title_search_and_tag_crawls(self):
        searched = [s for s in manga_sources.SITES if s.family not in manga_sources.INDEX_ONLY]
        self.assertFalse({'hentaimoody', 'hentaros'} & {s.family for s in searched})
        from content_sources import html_titles
        from catalogue_sources import html_rows
        listing = b'<a class="card" href="https://hentaros.com/omanko"><span class="t">x</span></a>'
        self.assertEqual(html_titles(listing, 'https://hentaros.com/tag/milf', 'Милф', 'tag'), [])
        self.assertEqual(html_rows(listing.decode(), 'https://online.hentaimoody.com/page/2/'), [])


# ---------------------------------------------------------------- Yaoi.me

YAOI_EN = '3681435886557602253'
YAOI_ROW = {'provider': 'suwayomi:' + YAOI_EN, 'title': 'Nemu is Drunk - Hidoku Shinaide dj',
            'sourceUrl': 'https://yaoi.me/series/62284?mv_manga_source=' + YAOI_EN}
UA = 'Mozilla/5.0 (X11; Linux aarch64; rv:140.0) Gecko/20100101 Firefox/140.0'
CHALLENGE = (b'<html><head><title>Just a moment...</title></head><body>'
             b'<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script></body></html>')
HASHES = ['0ym_lZZGWcy6cGDDl7GNxRGjnQlGHAF3g_qWVWHXod5i', '8vKl3_2DR54LzWBV_QFjZKfimMsfSR0b4y63MX9Uggu']


def sealed(hashes):
    salt, nonce = b's' * 16, b'n' * 12
    key = hashlib.sha256(manga_yaoime.SEAL_KEY + salt).digest()
    data = salt + nonce + AESGCM(key).encrypt(nonce, json.dumps({'p': hashes}).encode(), None)
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


class CurlAnswer:
    def __init__(self, status, body, ctype):
        self.status_code, self.content, self.headers = status, body, {'Content-Type': ctype}
        self.cookies, self.reason = {}, 'OK'
        if status == 403:
            self.headers.update({'Server': 'cloudflare', 'cf-mitigated': 'challenge'})


class YaoiSite:
    """curl_cffi stand-in for yaoi.me: Cloudflare until Byparr's cookies and agent arrive."""

    def __init__(self):
        self.calls = []

    def request(self, method, url, headers=None, cookies=None, **_):
        self.calls.append((method, url))
        assert method == 'GET', method
        if (cookies or {}).get('cf_clearance') != 'ok' or (headers or {}).get('User-Agent') != UA:
            return CurlAnswer(403, CHALLENGE, 'text/html; charset=UTF-8')
        if url == 'https://yaoi.me/series/62284':
            return CurlAnswer(200, fixture('yaoime-series.html').encode(), 'text/html; charset=utf-8')
        if url == 'https://yaoi.me/api/reader/chapter?s=62284&c=2503362':
            assert headers.get('x-yf-s') and headers.get('x-yf-t'), headers
            body = {'chapter': {'pages': [{'ord': 0, 'w': 744}, {'ord': 1, 'w': 736}], 'sealed': sealed(HASHES)}}
            return CurlAnswer(200, json.dumps(body).encode(), 'application/json')
        if url.startswith('https://yaoi.me/i/p/'):
            return CurlAnswer(200, JPEG, 'image/jpeg')
        return CurlAnswer(404, b'', 'text/html')


def byparr(endpoint, json=None, headers=None, timeout=None, allow_redirects=None):
    assert json['cmd'] == 'request.get', json
    payload = {'status': 'ok', 'solution': {
        'url': json['url'], 'status': 200, 'userAgent': UA, 'response': '',
        'cookies': [{'name': 'cf_clearance', 'value': 'ok', 'domain': '.yaoi.me', 'path': '/'}]}}
    value = requests.Response()
    value.status_code = 200
    value._content = __import__('json').dumps(payload).encode()
    return value


class YaoiMeReads(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [patch.dict(os.environ, {'DATA_DIR': self.temp.name, 'SOURCE_SOLVER_SLOTS': self.temp.name})]
        for item in self.patches:
            item.start()
        transport._declared.update(key=None, value={})
        transport.sessions.clear()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        transport._declared.update(key=None, value={})
        transport.sessions.clear()
        self.temp.cleanup()

    def test_every_language_reads_through_the_solver_but_crawls_unchanged(self):
        shipped = transport.parse(json.loads(Path(transport.__file__).with_name('manga_source_transport.json')
                                             .read_text(encoding='utf-8')))
        self.assertEqual(len(manga_yaoime.LANGUAGES), 23)
        for sid, lang in manga_yaoime.LANGUAGES:
            entry = shipped[sid]
            for operation in ('chapters', 'pages', 'images'):
                rule = entry.rule('yaoi.me', operation)
                self.assertTrue(rule.solver and rule.exit == 'direct' and rule.tls == 'firefox', (lang, operation))
            for operation in ('catalogue', 'search', 'details'):
                self.assertIsNone(entry.rule('yaoi.me', operation), (lang, operation))
            self.assertIsNone(entry.rule('evil.example', 'pages'))

    def test_index_row_opens_card_chapters_and_a_page_after_the_browser_check(self):
        site = YaoiSite()
        http = PublicHttp(validate=lambda value: value, timeout=(3, 6), deadline=time.monotonic() + 60)
        with patch.object(transport, '_impersonating_session', return_value=site), \
                patch.object(transport.requests, 'post', side_effect=byparr) as solver:
            card = manga_sources.inspect(YAOI_ROW['sourceUrl'], http)
            self.assertEqual(manga_sources.site_for(YAOI_ROW['sourceUrl']).id, YAOI_ROW['provider'])
            self.assertTrue(same_work(YAOI_ROW, card))
            self.assertEqual([e['url'] for e in card['episodes']],
                             ['https://yaoi.me/chapter/62284/2503362?mv_series=62284&mv_manga_source=' + YAOI_EN])
            chapter = manga_sources.inspect(card['episodes'][0]['url'], http)
            self.assertEqual(chapter['pages'], [f'https://yaoi.me/i/p/{HASHES[0]}?w=1000',
                                                f'https://yaoi.me/i/p/{HASHES[1]}?w=1000'])
            result = verify(card, PublicHttp(validate=lambda value: value, timeout=(3, 6),
                                             deadline=time.monotonic() + 60))
        self.assertTrue(result['readable'], result)
        self.assertEqual(solver.call_count, 1)
        self.assertEqual(solver.call_args.kwargs['json']['url'], 'https://yaoi.me/series/62284')
        self.assertTrue(all(method == 'GET' and url.startswith('https://yaoi.me/') for method, url in site.calls))
        self.assertEqual(site.calls[:2], [('GET', 'https://yaoi.me/series/62284')] * 2)


# ---------------------------------------------------------------- AllHentai

ALLHENTAI = '1809051393403180443'
AH_TITLE = 'https://20.allhen.online/slujebnyi_dolg'


def allhentai():
    return next(s for s in manga_ru_families.SOURCES if s.SOURCE_ID == ALLHENTAI)


class AllHentaiLinks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.map = Path(self.temp.name) / suwayomi_legacy.MAP_NAME
        with closing(sqlite3.connect(self.map)) as db, db:
            db.executescript(suwayomi_legacy.SCHEMA)
            db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)', (ALLHENTAI, 'AllHentai', 'ru',
                       'https://20.allhen.online', 1, 'eu.kanade.tachiyomi.extension.ru.allhentai', 'AllHentai', 0))
            db.execute('INSERT INTO manga VALUES (?,?,?,?,?,?,?)', (173027, ALLHENTAI, '/slujebnyi_dolg', AH_TITLE,
                       'Служебный долг', '', 0))
            db.execute('INSERT INTO chapters VALUES (?,?,?,?,?,?,?,?,?,?)', (173027, 1, 9, '/slujebnyi_dolg/vol1/1?d=ab12',
                       '', 'Сингл', 1.0, 'Neversleep', None, 0))

    def tearDown(self):
        self.temp.cleanup()

    def activated(self):
        adapter = allhentai()
        return [patch.dict(manga_native_sources.ADAPTERS, {ALLHENTAI: adapter}),
                patch.dict(manga_native_sources.HOSTS, {'20.allhen.online': adapter})]

    def test_bridge_link_turns_into_the_native_title_and_chapter(self):
        self.assertEqual(suwayomi_legacy.explain(173027, path=self.map), (None, 'no-direct-reader'))
        guards = self.activated()
        for guard in guards:
            guard.start()
        try:
            target, reason = suwayomi_legacy.explain(173027, path=self.map)
            self.assertEqual(reason, 'ok')
            self.assertEqual(target.split('?')[0], AH_TITLE)
            self.assertEqual(manga_sources.site_for(target).id, 'suwayomi:' + ALLHENTAI)
            chapter, reason = suwayomi_legacy.explain(173027, 1, path=self.map)
            self.assertEqual(reason, 'ok')
            self.assertTrue(chapter.startswith(AH_TITLE + '/vol1/1?mtr=true'), chapter)
            self.assertNotIn('d=ab12', chapter)  # the account hash of the old extension URL is dropped
        finally:
            for guard in reversed(guards):
                guard.stop()

    def test_native_card_lists_chapters_and_guest_chapter_is_a_login_wall(self):
        adapter = allhentai()
        http = Http({AH_TITLE: fixture('allhentai-title.html')})
        card = adapter.inspect(AH_TITLE, http)
        self.assertEqual(card['title'], 'Служебный долг')
        self.assertEqual(len(card['episodes']), 1)
        episode = card['episodes'][0]
        self.assertTrue(episode['url'].startswith(AH_TITLE + '/vol1/1?mtr=true'), episode['url'])
        self.assertEqual(episode['translator'], 'Neversleep')
        # Live: /vol1/1?mtr=true -> 302 -> 404 with /static/deleted1.png placeholders for guests.
        with self.assertRaises(SourceAuthError):
            adapter.inspect(episode['url'], http)


if __name__ == '__main__':
    unittest.main()
