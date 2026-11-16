import base64
import csv
import importlib.util
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from manga_archive_ports import SOURCES as ARCHIVES
from manga_html_families import SOURCES as FAMILIES
from manga_individual_catalogues import SOURCES as INDIVIDUAL
from manga_json_families import sources as api_sources
from manga_ru_families import SOURCES as RUSSIAN
from manga_source_urls import split_reader_url
from source_parser import PublicHttp, SourceAccessError, SourceError, public_url


ROOT = Path(__file__).resolve().parents[1]
INDEX = {x.SOURCE_ID: x for x in (*ARCHIVES, *FAMILIES, *INDIVIDUAL, *api_sources(), *RUSSIAN)}


def fake_http(routes):
    def document(url, **_kwargs):
        value = routes[url]
        return (value if isinstance(value, str) else json.dumps(value), url, {})

    return Mock(deadline=None, document=Mock(side_effect=document))


class NativeBatchSecondTests(TestCase):
    def source(self, identity):
        source = INDEX[identity]
        if hasattr(source, 'origin'):
            pace = patch.object(source.origin, 'interval', 0)
            pace.start()
            self.addCleanup(pace.stop)
        return source

    def test_second_batch_counts_packages_and_keeps_routes_staged(self):
        with (ROOT / 'docs/native-source-inventory.csv').open(encoding='utf-8') as file:
            rows = [r for r in csv.DictReader(file)
                    if r['evidence'] == 'native-source-verification.md#вторая-партия-из-50-apk']
        self.assertEqual(len({r['package'] for r in rows}), 50)
        self.assertEqual(len(rows), 60)
        spec = importlib.util.spec_from_file_location('batch_probe_second', ROOT / 'scripts/probe-native-source-batch.py')
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)
        candidates, active = probe.candidates()
        for row in rows:
            identity = row['source_id']
            adapter = candidates[identity]
            self.assertEqual((adapter.NAME, adapter.LANGUAGE), (row['source'], row['language']))
            self.assertNotIn(identity, active)
            self.assertIn(identity, INDEX)

    def test_mangabox_uses_slug_and_keeps_fraction_and_image_order(self):
        source = self.source('1024627298672457456')
        root = source.ROOT
        title, chapter = root + '/manga/work', root + '/manga/work/chapter-1-5'
        http = fake_http({
            title: '<h1>Work</h1>',
            root + '/api/manga/work/chapters?limit=-1': {'success': True, 'data': {'chapters': [
                {'chapter_slug': 'chapter-1-5', 'chapter_num': 1.5, 'chapter_name': 'Chapter 1.5'},
            ]}},
            chapter: '<script>const cdns = ["https://cdn.example"]; const chapterImages = ["2.webp","1.webp"];</script>',
        })
        info = source.inspect(title, http)
        episode = info['episodes'][0]
        self.assertEqual(episode['number'], 1.5)
        self.assertEqual(split_reader_url(episode['url'])[1], chapter)
        self.assertEqual(source.inspect(episode['url'], http)['pages'],
                         ['https://cdn.example/2.webp', 'https://cdn.example/1.webp'])

    def test_fmreader_reads_base64_image_lists(self):
        source = self.source('7595224096258102519')
        link = source.ROOT + '/read/comic/chapter-12.html'
        page_url = 'https://cdn.example/01.png'
        content = base64.b64encode(page_url.encode()).decode()
        self.assertEqual(source.inspect(link, fake_http({link: f'<img class="chapter-img" data-img="{content}">'}))['pages'], [page_url])

    def test_mangareader_uses_the_id_attached_to_each_chapter(self):
        source = self.source('7370546749583817262')
        root = source.ROOT
        title = root + '/raw-manga/title'
        chapter = root + '/read/title/chapter-2'
        http = fake_http({
            title: '<div id="ani_detail"><h1 class="manga-name">Title</h1></div>'
                   '<ul id="ja-chaps"><li class="chapter-item" data-id="123"><a href="/read/title/chapter-2"><span class="name">Chapter 2</span></a></li></ul>',
            root + '/json/chapter?mode=vertical&id=123': {'html': '<div class="container-reader-chapter"><div><img data-url="/pages/01.jpg"></div></div>'},
        })
        episode = source.inspect(title, http)['episodes'][0]
        self.assertEqual(split_reader_url(episode['url'])[1], chapter + '#123')
        self.assertEqual(source.inspect(episode['url'], http)['pages'], [root + '/pages/01.jpg'])

    def test_group_le_does_not_forward_account_hashes_in_saved_chapters(self):
        source = self.source('5')
        root = source.ROOT
        title, chapter = root + '/comic', root + '/comic/vol1/1.5?mtr=true'
        script = '''<script>var chapterInfo = {}; rm_h.readerInit([["https://img.example","","/page1.jpg"]]);</script>'''
        # GroupLe encodes normal pages as tuples (file prefix, CDN prefix, file suffix).
        script = script.replace('["https://img.example","","/page1.jpg"]', '["","https://img.example","/page1.jpg"]')
        http = fake_http({
            title: '<h1 class="cr-hero-names__main">Comic</h1><table><tr class="item-row"><td class="item-title" data-num="15">'
                   '<a class="chapter-link" href="/comic/vol1/1.5">Глава 1.5</a></td><td class="date">15</td></tr></table>',
            chapter: script,
        })
        from manga_native_sources import saved_reader_url

        bridge = Mock()
        bridge.get.return_value = [{'index': 3, 'realUrl': root + '/comic/vol1/1.5?d=private_test_value'}]
        found = saved_reader_url(source, bridge, {'baseUrl': root}, title, 8, 3)
        self.assertEqual(split_reader_url(found)[1], chapter)
        self.assertEqual(source.inspect(title, http)['episodes'][0]['number'], 1.5)
        self.assertEqual(source.inspect(found, http)['pages'], ['https://img.example/page1.jpg'])

    def test_ezmanhwa_lists_only_readable_chapters_and_rejects_paid_requests(self):
        source = self.source('3317136566565343717')
        title = source.ROOT + '/series/series-a'
        http = fake_http({
            source.api + '/series/series-a': {'title': 'Series A', 'slug': 'series-a', 'genres': [{'name': 'Action'}]},
            source.api + '/series/series-a/chapters?page=1&perPage=100&sort=desc': {
                'data': [{'slug': 'chapter-one', 'number': 1}, {'slug': 'chapter-two', 'requiresPurchase': True}], 'totalPages': 1},
            source.api + '/series/series-a/chapters/chapter-one': {'images': [{'url': 'https://cdn.example/one.jpg'}]},
            source.api + '/series/series-a/chapters/chapter-two': {'requiresPurchase': True},
        })
        result = source.inspect(title, http)
        self.assertEqual(result['genres'], ['Action'])
        self.assertEqual(len(result['episodes']), 1)
        self.assertEqual(source.inspect(result['episodes'][0]['url'], http)['pages'], ['https://cdn.example/one.jpg'])
        with self.assertRaises(SourceAccessError):
            source.inspect(title + '/chapter-two', http)

    def test_libraries_keep_site_and_legacy_branch(self):
        source = self.source('2730544188738947015')
        title = source.ROOT + '/ru/example'
        target = source.saved_chapter({'url': '/example/chapter?volume=2&number=5.5&branch_id=123'}, source.ROOT, title)
        self.assertEqual(target, title + '/read/v2/c5.5?bid=123')
        self.assertTrue(source.saved_chapter_matches(target, title))
        with patch('manga_ru_families.get_lib') as api:
            api.return_value = {'data': [{'slug_url': 'example', 'rus_name': 'Название', 'tags': [{'name': 'Тег'}]}],
                                'meta': {'last_page': 2}}
            entries, more = source.catalogue(Mock(timeout=(3, 7), deadline=None))
        self.assertTrue(more)
        self.assertEqual(entries[0]['tags'], ['Тег'])
        self.assertIn('site_id%5B%5D=2', api.call_args.args[0])
        self.assertEqual(api.call_args.args[1].lib_site_id, 2)

    def test_forms_and_read_apis_are_bounded(self):
        http = PublicHttp(session=Mock(), validate=lambda url: public_url(url, resolve_dns=False))
        http.session.request.return_value = Mock(status_code=200)
        http._open('https://www.natomanga.com/api/manga/title/chapters?limit=-1', action='native-series-json')
        self.assertEqual(http.session.request.call_args.kwargs['headers']['Accept'], 'application/json')
        token = 'public-csrf-quoted-token-123'
        headers = {'Referer': 'https://mangabuff.ru/manga/title', 'X-CSRF-TOKEN': token}
        target = 'https://mangabuff.ru/chapters/load'
        http._open(target, method='POST', data={'manga_id': '123'}, headers=headers, action='native-series-form')
        self.assertEqual(http.session.request.call_args.kwargs['headers']['X-CSRF-TOKEN'], token)
        for url in ('https://www.natomanga.com/api/manga/title/chapters?limit=100',
                    'https://api.omegascans.org/login',
                    'https://api.qimanga.com/api/v1/series/a/chapters/a?account=1'):
            with self.assertRaises(SourceError):
                http._open(url, action='native-series-json')
        with self.assertRaises(SourceError):
            http._open(target, method='POST', data={'manga_id': 'not-a-number'}, headers=headers, action='native-series-form')

    def test_mayo_keeps_the_language_of_an_existing_chapter_url(self):
        source = self.source('6644592287307303034')
        root = source.ROOT
        http = fake_http({
            root + '/': '<p class="text-lg">Story</p>',
            root + '/api/raw/chapters': [{'id': 'a', 'number': 3.5}],
            root + '/api/raw/chapters?id=a&number=3.5': {'id': 'a', 'pageCount': 2},
        })
        title = source.inspect(root + '/', http)
        url = title['episodes'][0]['url']
        self.assertEqual(urlsplit(url).path, '/raw/chapter/a')
        self.assertEqual(source.inspect(url, http)['pages'], [root + '/api/manga/a/1', root + '/api/manga/a/2'])

    def test_twokinds_grouped_chapter_reads_from_stored_start_page(self):
        source = self.source('3133607736276627986')
        root = source.ROOT
        http = fake_http({
            root + '/archive/': '<div class="chapter-links"><a href="/comic/1/"><span>1</span></a><a href="/comic/2/"><span>2</span></a></div>',
            root + '/comic/1/': '<div id="content"><article><img src="/page1.png"></article></div>',
            root + '/comic/2/': '<div id="content"><article><img src="/page2.png"></article></div>',
        })
        chapters = source.inspect(root + '/20', http)['episodes']
        self.assertEqual(len(chapters), 1)
        self.assertEqual(source.inspect(chapters[0]['url'], http)['pages'], [root + '/page1.png', root + '/page2.png'])
