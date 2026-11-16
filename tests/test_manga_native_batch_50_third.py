import csv
import json
import runpy
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

import manga_direct_articles
import manga_direct_catalogues
import manga_direct_payloads
import manga_gallery_adults
from manga_source_urls import split_reader_url
from source_parser import PublicHttp, SourceAccessError, SourceError, public_url


ROOT = Path(__file__).resolve().parents[1]


def fixture(routes):
    def document(url, **options):
        payload = routes[url]
        if isinstance(payload, tuple):
            raw, headers = payload
        else:
            raw, headers = payload, {}
        return raw if isinstance(raw, str) else json.dumps(raw), url, headers

    return Mock(document=Mock(side_effect=document), deadline=None)


def read_url(value):
    return split_reader_url(value)[1]


class ThirdBatchTests(TestCase):
    def test_complete_package_membership_and_production_routes(self):
        modules = (manga_direct_articles, manga_direct_catalogues, manga_direct_payloads, manga_gallery_adults)
        ports = {adapter.SOURCE_ID: adapter for module in modules for adapter in module.sources()}
        candidates, active = runpy.run_path(str(ROOT / 'scripts/probe-native-source-batch.py'))['candidates']()
        with (ROOT / 'docs/native-source-inventory.csv').open(encoding='utf-8', newline='') as file:
            rows = [row for row in csv.DictReader(file) if row['source_id'] in ports]
        self.assertEqual(len(ports), 95)
        self.assertEqual(len({row['package'] for row in rows}), 50)
        self.assertEqual(set(ports), {row['source_id'] for row in rows})
        for row in rows:
            source = candidates[row['source_id']]
            self.assertEqual((source.NAME, source.LANGUAGE), (row['source'], row['language']))
            self.assertNotIn(source.SOURCE_ID, active)
            self.assertIs(type(source), type(ports[source.SOURCE_ID]))
            self.assertEqual(row['evidence'], 'native-source-verification.md#третья-партия-из-50-apk')

    def source(self, module, name, lang=None):
        source = next(adapter for adapter in module.sources() if adapter.NAME == name and (not lang or adapter.LANGUAGE == lang))
        if hasattr(source, 'origin'):
            source.origin.interval = 0
        return source

    def test_gallery_preserves_language_and_orders_page_manifest(self):
        source = self.source(manga_gallery_adults, 'HentaiFox', 'ja')
        root = source.ROOT
        catalogue = source.browse_url(1, '', 'popular', '')
        title = root + '/gallery/123/'
        wrong_title = title.replace('123', '456')
        http = fixture({
            catalogue: f'<div class="thumb" data-languages="5"><div class="inner_thumb"><a href="{title}"><img src="/a.webp"></a></div>'
                       '<span class="caption">Work</span></div>'
                       f'<div class="thumb" data-languages="1"><div class="inner_thumb"><a href="{wrong_title}"></a></div>'
                       '<span class="caption">Other work</span></div>',
            title: '<div class="gallery_top"><h1>Work</h1></div>'
                   '<input id="load_pages" value="2"><input id="load_dir" value="galleries">'
                   '<input id="load_id" value="321"><input id="load_server" value="2">'
                   """<script>pages=$.parseJSON('{"2":"p,1,1","1":"w,1,1"}');</script>""",
        })
        rows, more = source.catalogue(http)
        self.assertEqual([row['title'] for row in rows], ['Work'])
        self.assertFalse(more)
        episode = source.inspect(rows[0]['url'], http)['episodes'][0]
        expected = [f'https://m2.{source.hostname}/galleries/321/1.webp', f'https://m2.{source.hostname}/galleries/321/2.png']
        self.assertEqual(source.inspect(episode['url'], http)['pages'], expected)
        self.assertEqual(source.saved_chapter({'url': '/g/123/1/'}, root, title), read_url(episode['url']))

    def test_mangakuro_pages_are_from_requested_chapter_fragment(self):
        source = self.source(manga_direct_catalogues, 'MangaKuro')
        root = source.ROOT
        title = root + '/manga/sample'
        ch = title + '/chapter-3'
        request = root + '/ajax/image/list/chap/921'
        http = fixture({
            title: '<div class="detail_name"><h1>Sample</h1></div><div class="chapter_box">'
                   f'<div class="item"><a class="chapter_num" href="{ch}">Chapter 3</a></div></div>',
            ch: '<script>let CHAPTER_ID = 921;</script>',
            request: {'status': True, 'html': '<div class="image_story"><img src="/1.webp"><img src="/2.webp"></div>'},
        })
        episodes = source.inspect(title, http)['episodes']
        self.assertEqual([(read_url(e['url']), e['number']) for e in episodes], [(ch, 3)])
        self.assertEqual(source.inspect(episodes[0]['url'], http)['pages'], [root + '/1.webp', root + '/2.webp'])
        http.document.assert_called_with(request, headers={'Referer': ch}, action='native-series-json')

    def test_xomanga_keeps_saved_id_and_refuses_paid_chapter(self):
        source = self.source(manga_direct_payloads, 'XoManga')
        root = source.ROOT
        title = root + '/details.html?id=example'
        ch = root + '/reader.html?id=example&ch=1.5'
        http = fixture({
            root + '/index.json': {'latest': [{'title': 'Example', 'link': '/details.html?id=example', 'image': '/cover.png'}]},
            root + '/manga/example/details.json': {'title': 'Example', 'tags': ['Fantasy'], 'chapters_list': [
                {'chapter': 1.5, 'link': ch, 'date': '2026-01-01'},
                {'chapter': 2, 'link': '/reader.html?id=example&ch=2', 'is_vip': True},
            ]},
            root + '/manga/example/chapters/1.5.json': {'images': ['/p2.jpg', '/p1.jpg']},
        })
        rows, _ = source.catalogue(http, query='example')
        self.assertEqual(read_url(rows[0]['url']), title)
        episode, = source.inspect(title, http)['episodes']
        self.assertEqual(read_url(episode['url']), ch)
        self.assertEqual(episode['number'], 1.5)
        self.assertEqual(source.inspect(episode['url'], http)['pages'], [root + '/p2.jpg', root + '/p1.jpg'])
        self.assertEqual(source.saved_chapter({'url': 'example#1.5'}, root, title), ch)
        with self.assertRaises(SourceAccessError):
            source.inspect(root + '/reader.html?id=example&ch=2', http)

    def test_revival_uses_flight_references_and_filters_access_roles(self):
        source = self.source(manga_direct_payloads, 'Revival Scans')
        root = source.ROOT
        title, chapter = root + '/series/sample', root + '/read/sample/c1'
        response = {'manhwa': {'id': 'sample', 'title': 'Sample', 'chapters': '$2'}}
        http = fixture({
            title: '1:' + json.dumps(response) + '\n2:[{"id":"c1","number":1},{"id":"c2","number":2,"accessRoles":["paid"]}]\n',
            chapter: '1:{"pages":[{"url":"/p1.jpg"}]}\n',
        })
        episode, = source.inspect(title, http)['episodes']
        self.assertEqual(read_url(episode['url']), chapter)
        self.assertEqual(source.inspect(episode['url'], http)['pages'], [root + '/p1.jpg'])

    def test_jumprookie_cursors_are_scoped_to_category(self):
        source = self.source(manga_direct_catalogues, 'Jump Rookie!')
        root = source.ROOT
        api = root + '/api/media/series_list?type=popular&category=action'
        card = '<section class="series-contents"><a href="/series/work"><h2 class="series-title">Work</h2></a></section>'
        http = fixture({api: (card, {'Tky-Link-Rel-Next': '?key=next'}), api + '&key=next': card})
        _, more = source.catalogue(http, tag='action')
        self.assertTrue(more)
        self.assertEqual(source.catalogue(http, page=2, tag='horror'), ([], False))
        rows, more = source.catalogue(http, page=2, tag='action')
        self.assertEqual(rows[0]['title'], 'Work')
        self.assertFalse(more)

    def test_article_reader_uses_full_size_gallery_image(self):
        source = self.source(manga_direct_articles, 'XYZ Comics')
        url = source.ROOT + '/work/'
        http = fixture({url: '<h1 class="post-title">Work</h1><div class="pswp-gallery">'
                             '<div class="pswp-gallery__item"><a href="/full.png"><img src="/thumb.png"></a></div></div>'})
        episode, = source.inspect(url, http)['episodes']
        self.assertEqual(source.inspect(episode['url'], http)['pages'], [source.ROOT + '/full.png'])

    def test_series_api_rejects_arbitrary_endpoints_and_redirects(self):
        self.assertEqual(public_url('https://api.mangade.io/api/chapters/45/view', resolve_dns=False),
                         'https://api.mangade.io/api/chapters/45/view')
        with self.assertRaises(SourceError):
            public_url('https://api.mangade.io/api/account', resolve_dns=False)
        session = Mock()
        guard = lambda url: public_url(url, resolve_dns=False)
        http = PublicHttp(session=session, validate=guard)
        with self.assertRaises(SourceError):
            http.document('https://www.revivalscans.com/login', action='native-series-rsc')
        session.request.assert_not_called()
