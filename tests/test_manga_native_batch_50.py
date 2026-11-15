import csv
import importlib.util
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

import manga_madara
import manga_themesia
from manga_native_sources import saved_reader_url
from manga_source_urls import reader_url, split_reader_url
from manga_webcomics import adapters
from source_parser import PublicHttp, SourceError, public_url


ROOT = Path(__file__).resolve().parents[1]
SOURCES = {x.SOURCE_ID: x for x in (*adapters(), *manga_madara.SOURCES, *manga_themesia.SOURCES)}


def setup_http(routes):
    def document(url, **_):
        value = routes[url]
        return (json.dumps(value) if not isinstance(value, str) else value, url, {})
    return Mock(deadline=None, document=Mock(side_effect=document))


class NativeBatchTests(TestCase):
    def test_snapshot_and_live_candidate_registry_cover_50_packages(self):
        with (ROOT / 'docs/native-source-inventory.csv').open(encoding='utf-8') as file:
            rows = [row for row in csv.DictReader(file)
                    if row['evidence'] == 'native-source-verification.md#партия-из-50-apk']
        self.assertEqual(len({r['package'] for r in rows}), 50)
        self.assertEqual(len(rows), 52)
        spec = importlib.util.spec_from_file_location('native_batch_probe', ROOT / 'scripts/probe-native-source-batch.py')
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)
        candidates, active = probe.candidates()
        for row in rows:
            source_id = row['source_id']
            self.assertNotIn(source_id, active)
            source = candidates[source_id]
            self.assertEqual((source.NAME, source.LANGUAGE), (row['source'], row['language']))
            self.assertTrue(callable(source.catalogue) and callable(source.inspect))
            self.assertTrue(source.TITLE_PATH.groups and source.CHAPTER_PATH.groups)

    def test_query_based_chapter_keeps_legacy_link_and_page_order(self):
        source = SOURCES['4006397036545425884']
        title = source.ROOT + '/index.php'
        chapter = title + '?nro=20'
        http = setup_http({
            title: '<select class="fall"><option>First</option><option value="20">The dune</option></select>',
            chapter: '<div class="comic_title">The dune</div><img src="/images/page.png">',
        })
        cards, _ = source.catalogue(http, query='blastwave')
        self.assertEqual(len(cards), 1)
        reading = source.inspect(cards[0]['url'], http)
        self.assertEqual(reading['episodes'][0]['number'], 20)
        bridge = Mock()
        bridge.get.return_value = [{'index': 2, 'url': '/index.php?nro=20'}]
        legacy = saved_reader_url(source, bridge, {'baseUrl': source.ROOT}, title, 21, 2)
        self.assertEqual(split_reader_url(legacy), (source.SOURCE_ID, chapter))
        self.assertEqual(source.inspect(legacy, http)['pages'], [source.ROOT + '/images/page.png'])
        self.assertFalse(source.site_link(reader_url(chapter, '123')))

    def test_enrichment_uses_one_html_response_and_leaves_foreign_links_out(self):
        source = SOURCES['2796812439185810666']
        title, episode = source.ROOT + '/', source.ROOT + '/manga/ruridragon-chapter-10/'
        http = setup_http({
            title: '<meta property="og:image" content="/cover.webp"><a href="/manga/ruridragon-chapter-10/">Chapter 10</a>'
                   '<a href="https://other.example/manga/ruridragon-chapter-9/">Foreign Chapter</a>',
            episode: '<div class="entry-content"><img src="https://img.ruridragon.com/cropped-logo.png">'
                     '<img data-src="https://img.ruridragon.com/002.png" src="/placeholder.jpg">'
                     '<img src="https://blogger.googleusercontent.com/p/001.png"></div>',
        })
        info = source.inspect(source.reader_url(title), http)
        self.assertEqual(info['cover'], source.ROOT + '/cover.webp')
        self.assertEqual(http.document.call_count, 1)
        self.assertEqual(len(info['episodes']), 1)
        chapter = source.inspect(info['episodes'][0]['url'], http)
        self.assertEqual(chapter['pages'], ['https://img.ruridragon.com/002.png', 'https://blogger.googleusercontent.com/p/001.png'])

    def test_arknights_rejects_a_foreign_chapter_even_if_api_returns_it(self):
        source = SOURCES['5973713386239249589']
        index = source.ROOT + '/api/resource/comic/list'
        chapters = source.ROOT + '/api/resource/comic/details?name=Our+Comic&index=1&size=9999'
        story = {'name': 'Our Comic', 'chapter': 3, 'detailsName': 'Third', 'detailsContent': ['/p/2.png', '/p/1.png']}
        other = {**story, 'name': 'Other Comic', 'detailsContent': ['/unrelated.png']}
        http = setup_http({
            index: {'data': {'rows': [{'name': 'Our Comic', 'smallImage': ['/cover.png']}]}},
            chapters: {'data': {'rows': [other, story]}},
            chapters + '&chapter=3': {'data': {'rows': [other, story]}},
        })
        cards, _ = source.catalogue(http, query='our comic')
        title = source.inspect(cards[0]['url'], http)
        chapter = source.inspect(title['episodes'][0]['url'], http)
        self.assertEqual(chapter['id'], title['id'])
        self.assertEqual(chapter['pages'], [source.ROOT + '/p/2.png', source.ROOT + '/p/1.png'])
        self.assertEqual(http.document.call_args.kwargs['action'], 'webcomic-json')

    def test_vagabond_fragment_is_kept_out_of_http_but_selects_correct_title(self):
        source = SOURCES['5300358436613908601']
        index = source.ROOT + '/api/mihon/mangas'
        item = {'number': 7, 'mangaId': 5, 'volume': 2, 'title': 'Seventh', 'pageCount': 2}
        http = setup_http({
            index: [{'id': 5, 'title': 'Vagabond'}, {'id': 8, 'title': 'Other'}],
            index + '/5/chapters': [item],
            index + '/5/chapters/7': item,
        })
        title = source.inspect(source.reader_url(source.ROOT + '/#5'), http)
        chapter = source.inspect(title['episodes'][0]['url'], http)
        self.assertEqual(urlsplit(title['episodes'][0]['url']).fragment, '5')
        self.assertEqual(chapter['id'], title['id'])
        self.assertEqual(chapter['pages'], ['https://pub.moleve.net/chapter-7/page-1.png', 'https://pub.moleve.net/chapter-7/page-2.png'])
        self.assertNotIn('#', http.document.call_args.args[0])

    def test_new_public_api_restricts_routes_and_attaches_json_headers(self):
        http = PublicHttp(session=Mock(), validate=lambda url: public_url(url, resolve_dns=False))
        http.session.request.return_value = Mock(status_code=200)
        root = 'https://arknights.global'
        http._open(root + '/api/resource/comic/list', action='webcomic-json')
        self.assertEqual(http.session.request.call_args.kwargs['headers']['Accept'], 'application/json')
        for target in (root + '/api/resource/comic/details?name=a&index=1&size=1',
                       root + '/api/private', 'https://external.example/path',
                       'https://readbagabondo.com/api/mihon/mangas?q=a&page=1&extra=2'):
            with self.assertRaises(SourceError):
                http._open(target, action='webcomic-json')

    def test_madara_json_chapter_list_preserves_fraction_and_cdn_referer(self):
        source = SOURCES['7947062020376654174']
        info = source.ROOT + '/manga/a/'
        api = source.ROOT + '/api/comics/a/chapters?'
        http = setup_http({
            api + 'page=1&per_page=50&order=desc': {'data': {'chapters': [{
                'chapter_slug': 'chapter-7-5', 'chapter_name': 'Chapter 7.5', 'updated_at': '2026-01-01',
            }], 'last_page': 2}},
            api + 'page=2&per_page=50&order=desc': {'data': {'chapters': [{
                'chapter_slug': 'chapter-7', 'chapter_name': 'Chapter 7',
            }], 'last_page': 2}},
        })
        original = source.origin.interval
        self.addCleanup(setattr, source.origin, 'interval', original)
        source.origin.interval = 0
        chapters, truncated = source.chapters(http, None, info, 'a')
        self.assertEqual([entry['number'] for entry in chapters], [7, 7.5])
        self.assertFalse(truncated)
        self.assertEqual(source.page_headers(info), {'Referer': source.ROOT + '/'})
        doc = BeautifulSoup('<div class="page-break"><img src="/thumb/1.webp" data-backup="https://cdn.example/1.webp"></div>', 'html.parser')
        self.assertEqual(source.page_images(doc, info), ['https://cdn.example/1.webp'])

    def test_themesia_scope_and_locked_chapters(self):
        es, pt = SOURCES['2886862669347225416'], SOURCES['6705370418823255358']
        path, _, _ = pt.catalogue_route(1, '', 'popular', '12')
        self.assertEqual(parse_qs(urlsplit(path).query)['genre[]'], ['12', '307'])
        self.assertFalse(es.site_link(pt.reader_url(pt.ROOT + '/manga/series/')))
        eva = SOURCES['1911019612901009263']
        doc = BeautifulSoup('<div id="chapterlist"><ul><li><a href="/free"><span class="chapternum">Chapter 4</span></a></li>'
                            '<li><a href="/paid" data-coin="10">Chapter 5</a></li></ul></div>', 'html.parser')
        self.assertEqual([x['number'] for x in eva.chapters(doc, eva.ROOT + '/series/sample/')], [4])
