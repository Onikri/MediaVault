"""Contract tests for different protocols in the seventh source migration batch."""

import csv
import json
from pathlib import Path
from runpy import run_path
from unittest import TestCase
from unittest.mock import Mock
from urllib.parse import urlsplit

import manga_comic_grast
import manga_comics_kingdom
import manga_ksbd
import manga_nexus_reader
import manga_rayuba
import manga_seventh_data
import manga_seventh_html
import manga_zerosum
from manga_speedbinb import grant
from manga_webcomics import query_url
from source_parser import PublicHttp, SourceError, public_url

ROOT = Path(__file__).resolve().parents[1]
MODULES = (manga_seventh_data, manga_seventh_html, manga_rayuba, manga_zerosum, manga_nexus_reader,
           manga_comics_kingdom, manga_comic_grast, manga_ksbd)
PROFILES = tuple(adapter for module in MODULES for adapter in module.SOURCES)


def mock_site(routes):
    def document(url, **kwargs):
        data = routes[url]
        return data if isinstance(data, str) else json.dumps(data), url, {}

    return Mock(document=Mock(side_effect=document), deadline=None)


class SeventhBatchTests(TestCase):
    def test_inventory_and_endpoint_registration(self):
        candidates, active = run_path(str(ROOT / 'scripts/probe-native-source-batch.py'))['candidates']()
        with (ROOT / 'docs/native-source-inventory.csv').open(encoding='utf-8', newline='') as file:
            rows = {row['source_id']: row for row in csv.DictReader(file)}
        self.assertEqual(len(PROFILES), 11)
        self.assertEqual(len({rows[profile.SOURCE_ID]['package'] for profile in PROFILES}), 10)
        for profile in PROFILES:
            with self.subTest(profile=profile.SOURCE_ID):
                self.assertNotIn(profile.SOURCE_ID, active)
                self.assertIs(type(candidates[profile.SOURCE_ID]), type(profile))
                row = rows[profile.SOURCE_ID]
                self.assertEqual((profile.NAME, profile.LANGUAGE), (row['source'], row['language']))
                self.assertTrue(row['evidence'].endswith('#седьмая-партия'))

    def test_qwik_reference_resolution(self):
        objs = [
            {'loaders': '1'}, {'result': '2'}, {'chapters': '3', 'unused': '4'},
            ['5'], '\x01', '\x02Example',
        ]
        self.assertEqual(manga_seventh_data.qwik_load({'_entry': '0', '_objs': objs}),
                         {'chapters': ['Example'], 'unused': None})
        with self.assertRaises(SourceError):
            manga_seventh_data.qwik_load({'_entry': '0', '_objs': [['0']]})

    def test_zerosum_post_accepts_only_empty_viewer_body(self):
        viewer = manga_zerosum.API + '/viewer?chapter_id=12'
        result = Mock(status_code=200, headers={'Content-Type': 'application/x-protobuf'})
        http = PublicHttp()
        try:
            http.validate = lambda url: public_url(url, resolve_dns=False)
            http.session.request = Mock(return_value=result)
            http._open(viewer, method='POST', data=b'', action='zerosum-proto')
            args = http.session.request.call_args.kwargs
            self.assertIn('application/x-protobuf', args['headers']['Accept'])
            self.assertEqual(args['data'], b'')
            with self.assertRaises(SourceError):
                http._open(viewer, method='POST', data=b'other', action='zerosum-proto')
        finally:
            http.close()

    def test_guest_cookies_on_public_documents_are_host_bound(self):
        result = Mock(status_code=200, headers={'Content-Type': 'text/html'})
        http = PublicHttp()
        try:
            http.validate = lambda url: public_url(url, resolve_dns=False)
            http.session.request = Mock(return_value=result)
            http.session.cookies.set('wnx_series', 'series', domain='webnex.cc')
            http._open('https://webnex.cc/read/example', action='webnex-doc')
            self.assertEqual(http.session.cookies.get('wnx_series'), 'series')
            self.assertNotIn('Cookie', http.session.request.call_args.kwargs['headers'])
            with self.assertRaises(SourceError):
                http._open('https://example.org/', action='webnex-doc')
            http._open('https://hotcomics.io/en', action='hotcomics-doc')
            self.assertEqual(http.session.request.call_args.kwargs['headers']['Cookie'], 'hc_vfs=Y')
            with self.assertRaises(SourceError):
                http._open('https://hotcomics.io/account', action='hotcomics-doc')
        finally:
            http.close()

    def test_comic_grast_tile_order_and_reader_manifest(self):
        profile = manga_comic_grast.ComicGrast()
        profile.origin.interval = 0
        origin = 'https://novema.jp'
        reader = origin + '/comic/serial/n11/n1/1'
        directory = origin + '/img/serial-comic/11/1/content/'
        http = mock_site({
            reader: '<script id="comic-data" type="application/json">{"serial_comic_id":11,"story_number":1}</script>',
            directory + 'index.json': [{'name': 'test.jpg', 'seed': 'hello.', 'size': 4}],
        })
        pages = profile.pages(http, reader)
        target, referer, transform = grant(pages[0])
        self.assertEqual(target, query_url(directory + 'test.jpg', seed='hello.', size=4))
        self.assertEqual(referer, reader)
        self.assertEqual(transform.size, 4)
        self.assertAlmostEqual(manga_comic_grast.SeedRandom('hello.').next(), 0.9282578795792454)
        blocks = list(manga_comic_grast.regions(80, 100, 4, 'hello.'))
        self.assertEqual(len(blocks), 16)
        self.assertEqual(len({(x, y) for _, _, _, _, x, y in blocks}), 16)

    def test_rayuba_chapter_uses_published_cubari_proxy_path(self):
        profile = manga_rayuba.WarForRayuba()
        profile.origin.interval = 0
        title = 'https://raw.githubusercontent.com/xrabohrok/WarMap/main/tools/example.json'
        chapter_path = '/proxy/api/imgur/chapter/example/'
        chapter = 'https://cubari.moe' + chapter_path
        http = mock_site({
            title: {'title': 'Example', 'chapters': {'1': {'title': 'First', 'groups': {'primary': chapter_path}}}},
            chapter: [{'src': 'https://i.imgur.com/example.png'}],
        })
        episodes = profile.inspect(title, http)['episodes']
        self.assertEqual(len(episodes), 1)
        self.assertEqual(urlsplit(profile.canonical(episodes[0]['url'])).path, chapter_path)
        self.assertEqual(profile.inspect(episodes[0]['url'], http)['pages'], ['https://i.imgur.com/example.png'])
        self.assertEqual(public_url(chapter, resolve_dns=False), chapter)
