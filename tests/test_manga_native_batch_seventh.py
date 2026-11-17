"""Contract tests for different protocols in the seventh source migration batch."""

import csv
from io import BytesIO
import json
from pathlib import Path
from runpy import run_path
from unittest import TestCase
from unittest.mock import Mock
from urllib.parse import urlsplit

from PIL import Image

import manga_comic_grast
import manga_comics_kingdom
import manga_comicklive
import manga_booru_pools
import manga_asura_native
import manga_blacktoon
import manga_ciaoplus
import manga_corocoro
import manga_dle_readers
import manga_dynasty
import manga_fourkhd
import manga_girlstop
import manga_honeytoon_native
import manga_japanese_next
import manga_jjcos
import manga_korean_seventh
import manga_ksbd
import manga_lusttoon
import manga_manhwazone
import manga_mangabox
import manga_mangameets
import manga_mangaone
import manga_mokuro
import manga_momonga
import manga_multporn
import manga_ninehentai
import manga_nicomanga
import manga_nexus_reader
import manga_ososedki
import manga_park_publisher
import manga_rawkuma_overlay
import manga_rayuba
import manga_reimanga
import manga_seventh_data
import manga_seventh_html
import manga_toon11
import manga_toomics
import manga_toonkotsu
import manga_twicomi
import manga_voyceme
import manga_vyvy
import manga_zerosum
from manga_speedbinb import grant
from manga_webcomics import query_url
from source_parser import PublicHttp, SourceError, public_url

ROOT = Path(__file__).resolve().parents[1]
MODULES = (manga_seventh_data, manga_seventh_html, manga_rayuba, manga_zerosum, manga_nexus_reader,
           manga_comics_kingdom, manga_comic_grast, manga_ksbd, manga_girlstop, manga_reimanga,
           manga_vyvy, manga_manhwazone, manga_rawkuma_overlay, manga_korean_seventh, manga_toon11, manga_ninehentai,
           manga_comicklive, manga_booru_pools, manga_jjcos, manga_twicomi, manga_ososedki,
           manga_honeytoon_native, manga_fourkhd, manga_voyceme, manga_multporn, manga_mangameets,
           manga_momonga, manga_toomics, manga_japanese_next, manga_park_publisher, manga_mangaone,
           manga_mangabox, manga_asura_native, manga_corocoro, manga_ciaoplus, manga_lusttoon,
           manga_blacktoon, manga_nicomanga, manga_dle_readers, manga_dynasty, manga_mokuro, manga_toonkotsu)
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
        self.assertEqual(len(PROFILES), 69)
        self.assertEqual(len({rows[profile.SOURCE_ID]['package'] for profile in PROFILES}), 50)
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

    def test_vyvy_replaces_expiring_links_with_stable_chapter_ids(self):
        profile = manga_vyvy.VyvyManga()
        profile.origin.interval = 0
        title = profile.ROOT + '/manga/example'
        template = '<h1>Example</h1><div class="list-group"><a href="/chapter/{token}" id="chapter-2"><span>Chapter 2</span></a></div>'
        first = mock_site({title: template.format(token='expired')})
        url = profile.inspect(title, first)['episodes'][0]['url']
        second = mock_site({title: template.format(token='current'), profile.ROOT + '/chapter/current':
                            '<img class="d-block" data-src="https://cdn.example.org/2.png">'})
        self.assertEqual(profile.inspect(url, second)['pages'], ['https://cdn.example.org/2.png'])

    def test_reimanga_pack_assigns_each_range_to_the_right_segment(self):
        root = 'https://cdn.example.org/'
        refs = manga_reimanga.pack_pages({'index': {'s': [2, 1], 'p': [[32], [64], [128]]},
                                         'urls': [root + 'a.webp', root + 'b.webp']}, root)
        self.assertEqual([(item.url, item.offset, item.size) for _, item in refs],
                         [(root + 'a.webp', 0, 32), (root + 'a.webp', 32, 64), (root + 'b.webp', 0, 128)])
        with self.assertRaises(SourceError):
            manga_reimanga.pack_pages({'index': {'s': [2], 'p': [[32]]}, 'urls': [root + 'a.webp']}, root)

    def test_rawkuma_overlay_draws_only_safe_elements(self):
        overlay = manga_rawkuma_overlay.RawkumaPage(80, 60,
            '<rect x="1" y="1" width="20" height="20" fill="#f00"/>'
            '<g style="font-size:8px;fill:black"><text x="20" y="24" textLength="22">Example</text></g>', ())
        original = BytesIO()
        Image.new('RGB', (80, 60), 'white').save(original, 'PNG')
        raw = overlay.overlay(original.getvalue(), Mock(), 'https://rawkuma.me/manga/example/chapter-1')
        with Image.open(BytesIO(raw)) as image:
            self.assertEqual(image.size, (80, 60))
            color = image.getpixel((12, 12))
            self.assertGreater(color[0], 180)
            self.assertLess(color[1], 70)
        with self.assertRaises(SourceError):
            manga_rawkuma_overlay.svg_nodes('<!DOCTYPE foo><text/>')

    def test_manhwazone_livewire_only_allows_chapter_loading(self):
        title = manga_manhwazone.ROOT + '/series/example'
        endpoint = manga_manhwazone.ROOT + '/livewire/update'
        valid = {'_token': 'T' * 30, 'components': [{'snapshot': json.dumps({'data': {}, 'memo': {}, 'checksum': 'a' * 64}),
                'updates': {}, 'calls': [{'path': '', 'method': 'bootLoad', 'params': []}]}]}
        self.assertTrue(manga_manhwazone.livewire_form(endpoint, json.dumps(valid).encode(), title))
        valid['components'][0]['calls'][0]['method'] = 'anotherAction'
        self.assertFalse(manga_manhwazone.livewire_form(endpoint, json.dumps(valid).encode(), title))

    def test_comicklive_keeps_cursors_for_each_query(self):
        profile = manga_comicklive.ComickLive()
        profile.origin.interval = 0
        target = profile.ROOT + '/api/search'
        params = {'type': 'comic', 'showAll': 'false', 'exclude_mylist': 'false', 'order_direction': 'desc'}
        routes = {}
        for query in ('first', 'other'):
            opts = {**params, 'q': query}
            routes[query_url(target, **opts, page=1)] = {'data': [{'title': query, 'slug': query}], 'next_cursor': query}
            routes[query_url(target, **opts, page=2, cursor=query)] = {'data': [{'title': query, 'slug': query}]}
        http = mock_site(routes)
        profile.catalogue(http, query='first')
        profile.catalogue(http, query='other')
        rows, more = profile.catalogue(http, 2, query='first')
        self.assertEqual(rows[0]['title'], 'first')
        self.assertFalse(more)

    def test_honeytoon_combines_strips_in_page_order(self):
        parts = []
        for ink in ('red', 'blue'):
            output = BytesIO()
            Image.new('RGB', (10, 5), ink).save(output, 'PNG')
            parts.append(output.getvalue())
        sizes = ','.join(str(len(part)) for part in parts)
        with Image.open(BytesIO(manga_honeytoon_native.merge_strips(b''.join(parts), sizes))) as image:
            self.assertEqual(image.size, (10, 10))
            self.assertEqual(image.convert('RGB').getpixel((5, 2)), (255, 0, 0))
            self.assertEqual(image.convert('RGB').getpixel((5, 7)), (0, 0, 255))
        with self.assertRaises(SourceError):
            manga_honeytoon_native.merge_strips(b''.join(parts), '1,1')

    def test_voyceme_only_accepts_declared_read_queries(self):
        url = manga_voyceme.GRAPHQL
        body = {'operationName': 'Pages', 'query': manga_voyceme.QUERIES['Pages'], 'variables': {'chapterId': 19}}
        self.assertTrue(manga_voyceme.public_form(url, json.dumps(body).encode()))
        body['query'] += ' mutation Example { no }'
        self.assertFalse(manga_voyceme.public_form(url, json.dumps(body).encode()))

    def test_corocoro_only_allows_empty_viewer_put(self):
        url = query_url(manga_corocoro.API, rq='chapter/viewer', chapter_id='123')
        ranking = query_url(manga_corocoro.API, rq='title/list/ranking')
        self.assertEqual(public_url(url, resolve_dns=False), url)
        self.assertTrue(manga_corocoro.transport(url, 'PUT', b''))
        self.assertFalse(manga_corocoro.transport(url, 'POST', b''))
        self.assertFalse(manga_corocoro.transport(url, 'PUT', b'data'))
        self.assertTrue(manga_corocoro.transport(ranking, 'GET', None))

    def test_ciaoplus_scope_and_layout(self):
        url = query_url(manga_ciaoplus.API + '/title/list', platform='3', title_id_list='00123')
        self.assertEqual(public_url(url, resolve_dns=False), url)
        expected = manga_ciaoplus.digest({'platform': '3', 'title_id_list': '00123'})
        self.assertEqual(manga_ciaoplus.transport(url, 'GET', None), expected)
        self.assertIsNone(manga_ciaoplus.transport(url + '&title_id_list=456', 'GET', None))
        self.assertIsNone(manga_ciaoplus.transport(manga_ciaoplus.API + '/login', 'POST', {}))
        self.assertEqual(sorted(manga_ciaoplus.tile_order(27)), list(range(16)))

    def test_nicomanga_keeps_original_chapter_ownership_and_titles(self):
        profile = manga_nicomanga.Nicomanga()
        profile.origin.interval = 0
        root = profile.ROOT
        title = root + '/manga82/1424bfba.html'
        chapter = root + '/manga82/1424bfba/chapter-c286i321256.html'
        payload = {'manga': {'n': 'Example', 'genres_list': [{'n': 'Action'}]},
                   'chapters_list': [{'ur': chapter, 'n': 'Chapter 2', 'chapter': '2'},
                                     {'ur': root + '/manga83/1424bfbc/chapter-c2i321257.html', 'chapter': '2'}]}
        raw = json.dumps(payload).encode()
        key = manga_nicomanga.OBFUSCATION
        encoded = ''.join(chr(19968 + (byte ^ key[i % len(key)])) for i, byte in enumerate(raw))
        http = mock_site({title: f'<script>0:Ta,</script><script>{encoded}</script>'})
        entry = profile.inspect(title, http)
        self.assertEqual(entry['title'], 'Example')
        self.assertEqual(entry['genres'], ['Action'])
        self.assertEqual([profile.canonical(row['url']) for row in entry['episodes']], [chapter])

    def test_comx_uses_page_segment_even_for_first_search_page(self):
        profile = manga_dle_readers.SOURCES[1]
        url = profile.ROOT + '/search/Example/page/1/'
        http = mock_site({url: '<div id="dle-content"><div class="readed"><div class="readed__title">'
                               '<a href="/112-example.html">Example</a></div></div></div>'})
        rows, more = profile.catalogue(http, query='Example')
        self.assertEqual(rows[0]['title'], 'Example')
        self.assertFalse(more)
