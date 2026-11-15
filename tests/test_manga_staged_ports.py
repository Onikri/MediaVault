import json
from unittest import TestCase
from unittest.mock import Mock
from urllib.parse import urlsplit

import manga_guya
import manga_mangadventure
import manga_mangak
import manga_masonry
from manga_native_sources import saved_reader_url
from manga_page_media import fetch_page, page_reference
from manga_source_urls import split_reader_url
from source_parser import SourceError, public_url


class StagedPortsTests(TestCase):
    def test_guya_preserves_language_and_saved_translator(self):
        source = manga_guya.SOURCES[1]
        index = {'Story': {'slug': 'story'}, 'Otra': {'slug': 'story-ES'}}
        data = {'slug': 'story-ES', 'title': 'Otra', 'groups': {'1': 'One', '2': 'Two'}, 'preferred_sort': ['1'],
                'chapters': {'1.5': {'title': 'First', 'folder': 'chapter-1-5', 'groups': {
                    '1': ['01.png'], '2': ['01 alt.png']}}}}
        http = Mock()

        def request(url, **_options):
            public_url(url, resolve_dns=False)
            payload = index if url.endswith('/get_all_series/') else data
            return json.dumps(payload), url, {}

        http.document.side_effect = request
        rows, _ = source.catalogue(http)
        title, = rows
        self.assertEqual(split_reader_url(title['url'])[0], source.SOURCE_ID)
        chapter, = source.inspect(title['url'], http)['episodes']
        self.assertEqual((chapter['number'], chapter['translator']), (1.5, 'One'))
        bridge = Mock()
        bridge.get.return_value = [{'index': 1, 'url': 'story-ES/1.5', 'scanlator': 'Two'}]
        saved = saved_reader_url(source, bridge, {'baseUrl': source.ROOT}, '/story-ES', 10, 1)
        resolved = source.inspect(saved, http)
        self.assertEqual(resolved['episodes'][0]['translator'], 'Two')
        self.assertEqual(resolved['pages'], [source.ROOT + '/media/manga/story-ES/chapters/chapter-1-5/2/01%20alt.png'])

    def test_mangadventure_binds_chapter_to_title_and_sorts_pages(self):
        source = manga_mangadventure.SOURCES[0]
        title = {'slug': 'book', 'title': 'Book', 'cover': '/cover.jpg', 'categories': ['Chaos;Head']}
        http = Mock()

        def request(url, **_options):
            public_url(url, resolve_dns=False)
            path = urlsplit(url).path
            if path == '/api/v2/series/book':
                payload = title
            elif path.endswith('/chapters'):
                payload = {'results': [{'id': 21, 'full_title': 'Chapter 2.5', 'number': 2.5, 'volume': 3}]}
            else:
                payload = {'results': [{'image': '/02.jpg', 'number': 2}, {'image': '/01.jpg', 'number': 1}]}
            return json.dumps(payload), url, {}

        http.document.side_effect = request
        detail = source.inspect(source.ROOT + '/reader/book', http)
        chapter, = detail['episodes']
        self.assertEqual((chapter['number'], chapter['season']), (2.5, 3))
        self.assertEqual(source.inspect(chapter['url'], http)['pages'], [source.ROOT + '/01.jpg', source.ROOT + '/02.jpg'])
        with self.assertRaises(SourceError):
            source.inspect(source.ROOT + '/reader/book/chapter/22', http)
        self.assertEqual(source.saved_chapter_url('/api/v2/chapters/21/read', 'book', source.ROOT), chapter['url'])
        with self.assertRaises(SourceError):
            public_url(source.ROOT + '/api/v2/chapters/21/pages?track=true&track=', resolve_dns=False)

    def test_masonry_separates_gallery_cards_and_pages_from_video(self):
        source = manga_masonry.SOURCES[0]
        html = '''<h1>Gallery</h1><div class="list-gallery">
        <figure><a href="/demo/gallery-name/" title="Gallery"><img src="/small.jpg"></a></figure>
        <figure><a href="/video/clip/" title="Clip"><img src="/clip.jpg"></a></figure>
        <a href="https://cdn.example/01.jpg"><img src="/small.jpg"></a></div>'''
        http = Mock()
        http.document.side_effect = lambda url, **kw: (html, url, {})
        cards, more = source.catalogue(http)
        self.assertFalse(more)
        self.assertEqual([item['title'] for item in cards], ['Gallery'])
        detail = source.inspect(cards[0]['url'], http)
        chapter, = detail['episodes']
        self.assertEqual(detail['pages'], [])
        self.assertEqual(source.inspect(chapter['url'], http)['pages'], ['https://cdn.example/01.jpg'])
        self.assertNotIn('mv_gallery', http.document.call_args.args[0])

    def test_mangak_uses_next_data_and_fixed_fallback_host(self):
        source = manga_mangak.SOURCES[0]
        sample = {'id': 'series-key', 'name': 'Book', 'url': '/book',
                  'genres': [{'name': 'Action'}], 'tags': [{'name': 'Sample tag'}]}
        http = Mock(deadline=None)

        def request(url, **_options):
            public_url(url, resolve_dns=False)
            path = urlsplit(url).path
            if path.startswith('/titles/'):
                data = {'data': {'chapters': [{'url': '/book/chapter-1', 'name': 'Chapter 1'}]}}
                return json.dumps(data), url, {}
            field, content = ('initialManga', sample) if path == '/book' else (
                'initialChapter', {'images': ['https://rx.qvzra.org/chapter/01.jpg?sig=sample']})
            data = {'props': {'pageProps': {field: content}}}
            return '<script id="__NEXT_DATA__">' + json.dumps(data) + '</script>', url, {}

        http.document.side_effect = request
        detail = source.inspect(source.ROOT + '/book/chapter-1', http)
        self.assertEqual((detail['genres'], detail['tags']), (['Action'], ['Sample tag']))
        image, = detail['pages']
        response = Mock()
        response.iter_content.return_value = [b'\xff\xd8\xffsample']
        http._open.side_effect = [SourceError('HTTP 404'), (response, 'https://rx.rzyn.net/chapter/01.jpg')]
        raw, mime = fetch_page(http, page_reference(image), {})
        self.assertEqual(mime, 'image/jpeg')
        self.assertTrue(raw.startswith(b'\xff\xd8\xff'))
        self.assertEqual(http._open.call_args.args[0], 'https://rx.rzyn.net/chapter/01.jpg?sig=sample')
