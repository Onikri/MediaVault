import json
from unittest import TestCase
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from manga_bakkin import SOURCES as BAKKIN
from manga_madara import SOURCES as MADARA, ajax_form
from manga_multichan import SOURCES as MULTICHAN
from manga_native_sources import saved_reader_url
from manga_page_media import fetch_page, page_reference
from source_parser import SourceError


class SourcePortTests(TestCase):
    def test_multichan_reuses_full_image_data_and_keeps_saved_episode(self):
        source = MULTICHAN[1]
        source.pace.interval = 0
        self.addCleanup(setattr, source.pace, 'interval', 0.5)
        title = source.ROOT + '/manga/12-story.html'
        chapter = source.ROOT + '/online/13-first.html'
        catalogue = '<div class="content_row" title="Story"><h2><a href="/manga/12-story.html">Story</a></h2></div>'
        work = '''<title>Story » Site</title><div class="sidetags"><ul><li><a>Adventure</a></li></ul></div>
            <table class="table_cha"><tr><td><a href="/online/13-first.html">Глава 1.5</a></td></tr></table>'''
        reader = '<h1>Глава 1.5</h1><script>let images = {"fullimg":["/01.jpg","/02.jpg",]};</script>'
        docs = {urlsplit(title).path: work, urlsplit(chapter).path: reader}
        http = Mock(deadline=None)
        http.document.side_effect = lambda url, **_kw: (docs.get(urlsplit(url).path, catalogue), url, {})
        cards, _ = source.catalogue(http, query='Story', page=2)
        self.assertEqual([row['url'] for row in cards], [title])
        self.assertEqual(parse_qs(urlsplit(http.document.call_args.args[0]).query)['search_start'], ['2'])
        detail = source.inspect(title, http)
        self.assertEqual(detail['tags'], ['Adventure'])
        self.assertEqual([(entry['url'], entry['number']) for entry in detail['episodes']], [(chapter, 1.5)])
        self.assertEqual(source.inspect(chapter, http)['pages'], [source.ROOT + '/01.jpg', source.ROOT + '/02.jpg'])
        bridge = Mock()
        bridge.get.return_value = [{'index': 1, 'url': '/online/13-first.html'}]
        self.assertEqual(saved_reader_url(source, bridge, {'baseUrl': source.ROOT}, title, 5, 1), chapter)

    def test_bakkin_restores_fragment_links_and_chapter_order(self):
        source = BAKKIN[0]
        data = {'a': {'dir': 'story', 'name': 'Story', 'volumes': [{
            'dir': 'v1', 'name': 'Volume 1', 'chapters': [{
                'dir': 'c2.5', 'name': 'Chapter 2.5', 'pages': ['pages/p 1.jpg', 'pages/p2.jpg']}]}]}}
        http = Mock()
        http.document.return_value = json.dumps(data), source.ROOT + 'main.php', {}
        cards, _ = source.catalogue(http, query='Story')
        title, = cards
        detail = source.inspect(title['url'], http)
        entry, = detail['episodes']
        self.assertEqual(entry['number'], 2.5)
        legacy = source.ROOT + '#m=story&v=v1&c=c2.5'
        direct = source.inspect(legacy, http)
        self.assertEqual(direct['pages'], [source.ROOT + 'pages/p%201.jpg', source.ROOT + 'pages/p2.jpg'])
        bridge = Mock()
        bridge.get.return_value = [{'index': 1, 'realUrl': legacy}]
        self.assertEqual(saved_reader_url(source, bridge, {'baseUrl': source.ROOT}, source.ROOT+'#m=story', 5, 1),
                         entry['url'])
        self.assertEqual(http.document.call_count, 1)
        self.assertFalse(source.asset('../example.jpg'))

    def test_goodtoon_uses_korean_catalogue_and_chapter_protocol(self):
        source = next(item for item in MADARA if item.NAME == 'GoodToon')
        http = Mock(deadline=None)
        catalogue = '<a class="card" href="/manga/story/"><div class="subject">Story</div></a>'
        title = '<h1 class="summary-title">Story</h1><div class="manga-summary-genres">코미디, 모험</div>'
        toc = '<li class="wp-manga-chapter"><a href="/manga/story/episode-7/">7.5화</a></li>'

        def request(url, **options):
            path = urlsplit(url).path
            if path.endswith('/ajax/chapters/'):
                self.assertTrue(ajax_form(url, options['data'], options['headers']['Referer']))
                return toc, url, {}
            return (title if path == '/manga/story/' else catalogue), url, {}

        http.document.side_effect = request
        rows, _ = source.catalogue(http, page=2, query='Story')
        params = parse_qs(urlsplit(http.document.call_args.args[0]).query)
        self.assertEqual(params, {'pg': ['2'], 'q': ['Story']})
        work = source.inspect(rows[0]['url'], http)
        self.assertEqual(work['genres'], ['코미디', '모험'])
        self.assertEqual((work['episodes'][0]['number'], work['episodes'][0]['language']), (7.5, 'ko'))

    def test_setsu_retries_only_known_image_status_and_parameters(self):
        source = next(item for item in MADARA if item.NAME == 'Setsu Scans')
        chapter = source.ROOT + '/manga/story/chapter-1/'
        image = 'https://i0.wp.com/setsuscans.com/page.jpg?fit=640%2C720'
        html = f'<div class="page-break"><img src="{image}"></div>'
        http = Mock(deadline=None)
        http.document.return_value = html, chapter, {}
        urls, _ = source.pages(http, chapter, urlsplit(chapter).path)
        response = Mock()
        response.iter_content.return_value = [b'\xff\xd8\xfffixture']
        http._open.side_effect = [SourceError('Источник вернул HTTP 404.'), (response, image)]
        _, mime = fetch_page(http, page_reference(urls[0]), {})
        self.assertEqual(mime, 'image/jpeg')
        self.assertEqual([parse_qs(urlsplit(call.args[0]).query) for call in http._open.call_args_list],
                         [{}, {'ssl': ['0']}])
