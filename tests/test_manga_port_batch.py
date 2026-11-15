import json
from unittest import TestCase
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from manga_bakkin import SOURCES as BAKKIN
from manga_madara import SOURCES as MADARA, ajax_form
from manga_multichan import SOURCES as MULTICHAN
from manga_native_sources import saved_reader_url
from manga_page_media import fetch_page, page_reference
from source_parser import SourceAccessError, SourceError


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

class LeagueOfLegendsPortTests(TestCase):
    def test_localized_index_releases_one_shot_and_saved_links(self):
        from manga_loluniverse import SOURCES

        source = next(item for item in SOURCES if item.LANGUAGE == 'ru')
        series = '/ru_ru/comic/lux'
        issue = series + '/issue-1'
        one_shot = '/ru_ru/comic/ziggs/paint'
        documents = {
            '/v1/ru_ru/comics/index.json': {'sections': {
                'series': {'data': [{'title': 'Люкс', 'url': series, 'description': '<p>Серия</p>',
                                     'featured-champions': [{'name': 'Люкс'}]}]},
                'one-shots': {'data': [{'title': 'Краски', 'url': one_shot}]},
            }},
            '/v1/ru_ru/comics/lux/index.json': {'issues': [{'url': issue, 'title': 'Выпуск', 'index': 1}]},
            '/comics/ru_ru/lux/issue-1/index.json': {
                'desktop-pages': [[{'uri': 'https://cdn.example/1.jpg'}, {'uri': 'https://cdn.example/2.jpg'}]],
                'staging-date': '2019-05-08T12:00:00Z',
            },
        }

        def document(url, **options):
            self.assertEqual(options['headers']['Origin'], 'https://universe.leagueoflegends.com')
            return json.dumps(documents[urlsplit(url).path]), url, {}

        http = Mock()
        http.document.side_effect = document
        cards, more = source.catalogue(http, query='люкс')
        self.assertFalse(more)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['tags'], ['Люкс'])
        chapter, = source.inspect(cards[0]['url'], http)['episodes']
        self.assertEqual(chapter['number'], 1)
        reading = source.inspect(chapter['url'], http)
        self.assertEqual(reading['pages'], ['https://cdn.example/1.jpg', 'https://cdn.example/2.jpg'])
        self.assertEqual(reading['episodes'][0]['publishedAt'], '2019-05-08')
        bridge = Mock()
        bridge.get.return_value = [{'index': 1, 'url': 'lux/issue-1'}]
        self.assertEqual(saved_reader_url(source, bridge, {'baseUrl': source.ROOT}, cards[0]['url'], 5, 1),
                         chapter['url'])
        self.assertFalse(source.site_link('https://universe.leagueoflegends.com/en_us/comic/lux'))
        title, = source.catalogue(http, query='Краски')[0]
        reading = source.inspect(title['url'], http)
        self.assertFalse(reading['pages'])
        self.assertEqual(reading['episodes'][0]['number'], 0)
        self.assertEqual(urlsplit(reading['episodes'][0]['url']).path, one_shot)


class MangaDexPortTests(TestCase):
    manga_id = '68112dc1-2b80-4f20-beb8-2f2a8716a430'
    chapter_id = '04724242-b32c-435a-8b6c-ab65d0d85b38'

    def setUp(self):
        from unittest.mock import patch

        from manga_mangadex_native import PACE, SOURCES, _leases

        self.source = next(item for item in SOURCES if item.LANGUAGE == 'pt-BR')
        self.http = Mock(deadline=None)
        mocked = patch('manga_mangadex_native.get')
        self.get = mocked.start()
        self.addCleanup(mocked.stop)
        self.addCleanup(_leases.clear)
        self.addCleanup(setattr, PACE, 'interval', PACE.interval)
        PACE.interval = 0

    def manga(self):
        return {'id': self.manga_id, 'type': 'manga', 'attributes': {
            'title': {'en': 'Story'}, 'altTitles': [{'pt-br': 'História'}], 'originalLanguage': 'ko',
            'tags': [{'attributes': {'group': 'genre', 'name': {'en': 'Fantasy'}}},
                     {'attributes': {'group': 'format', 'name': {'en': 'Long Strip'}}}],
        }, 'relationships': [{'type': 'cover_art', 'attributes': {'fileName': 'cover.png'}}]}

    def chapter(self, language='pt-br', **attributes):
        return {'id': self.chapter_id, 'type': 'chapter',
                'attributes': {'translatedLanguage': language, 'chapter': '7.5', 'volume': '2', 'pages': 2, **attributes},
                'relationships': [{'type': 'manga', 'id': self.manga_id},
                                  {'type': 'scanlation_group', 'attributes': {'name': 'Group'}}]}

    def test_language_search_metadata_and_stored_chapter(self):
        self.get.return_value = {'total': 99, 'data': [self.manga()]}
        cards, more = self.source.catalogue(self.http, page=2, query='História')
        self.assertTrue(more)
        self.assertEqual(parse_qs(urlsplit(self.get.call_args.args[0]).query)['availableTranslatedLanguage[]'], ['pt-br'])
        card, = cards
        self.assertEqual(card['title'], 'História')
        self.assertEqual(card['genres'], ['Fantasy'])
        self.assertEqual(card['tags'], ['Long Strip'])
        self.assertEqual(card['readingMode'], 'scroll')
        self.get.side_effect = [{'total': 2, 'data': [self.chapter(language='en'), self.chapter()]}, {'data': self.manga()}]
        reading = self.source.inspect(card['url'], self.http)
        chapter, = reading['episodes']
        self.assertEqual((chapter['number'], chapter['season'], chapter['translator']), (7.5, 2, 'Group'))
        self.assertEqual(parse_qs(urlsplit(chapter['url']).query)['manga'], [self.manga_id])
        bridge = Mock()
        bridge.get.return_value = [{'index': 1, 'url': '/chapter/' + self.chapter_id}]
        self.assertEqual(saved_reader_url(self.source, bridge, {'baseUrl': self.source.ROOT},
                                         self.source.ROOT + '/manga/' + self.manga_id, 5, 1), chapter['url'])
        self.get.side_effect = [{'data': self.chapter()}]
        with self.assertRaises(SourceError):
            self.source.inspect(chapter['url'].replace(self.manga_id, '4178439a-46d4-4285-8a33-e029e47678ff'), self.http)

    def test_chapter_images_keep_order_and_refresh_cdn_lease(self):
        from manga_mangadex_native import page_urls

        files = {'hash': 'ab'*16, 'data': ['01.png', '02.png']}
        first = {'baseUrl': 'https://old.example/token', 'chapter': files}
        second = {'baseUrl': 'https://new.example/token', 'chapter': files}
        self.get.side_effect = [first, second]
        pages = page_urls(self.http, self.chapter_id)
        self.assertEqual([urlsplit(url).path.rsplit('/', 1)[-1] for url in pages], ['01.png', '02.png'])
        response = Mock()
        response.iter_content.return_value = [b'\x89PNG\r\n\x1a\n']
        self.http._open.side_effect = [SourceAccessError('Недоступный сервер страниц.'), (response, 'https://new.example')]
        raw, mime = fetch_page(self.http, page_reference(pages[1]), {})
        self.assertEqual((raw, mime), (b'\x89PNG\r\n\x1a\n', 'image/png'))
        self.assertEqual(urlsplit(self.http._open.call_args.args[0]).hostname, 'new.example')
        self.assertEqual(self.get.call_count, 2)

    def test_user_lookup_tags_and_host_allowlist(self):
        from unittest.mock import patch

        from manga_catalog_adapters import api_url

        tag = '046b646a-6159-4ab5-9640-1b66566d5ddf'
        self.get.side_effect = [
            {'total': 1, 'data': [self.chapter()]}, {'data': [self.manga()]},
            {'data': [{'id': tag, 'attributes': {'group': 'genre', 'name': {'en': 'Fantasy'}}}]},
        ]
        cards, _ = self.source.catalogue(self.http, query='usr:' + tag)
        self.assertEqual(cards[0]['title'], 'História')
        self.assertEqual(parse_qs(urlsplit(self.get.call_args_list[0].args[0]).query)['uploader'], [tag])
        self.assertEqual(self.source.vocabulary(self.http), [{'label': 'Fantasy', 'sourceId': tag, 'category': 'genre'}])
        with patch('manga_catalog_adapters.public_url', side_effect=lambda url, **_kw: url):
            for uri in ('/manga/tag', '/chapter', '/list/' + tag):
                target = 'https://api.mangadex.org' + uri
                self.assertEqual(api_url(target), target)
            with self.assertRaises(SourceError):
                api_url('https://api.mangadex.org/list/restricted')

class FoolSlidePortTests(TestCase):
    def test_source_search_form_and_reader_page_order(self):
        from manga_foolslide import SOURCES

        source = SOURCES[0]
        title = '<div class="group"><a href="/series/story/" title="Story">Story</a><img src="/thumb_cover.jpg"></div>'
        work = ('<div class="title">Story</div><div class="info"><b>Author:</b> Writer</div>'
                '<div class="list"><div class="element"><a title="Read" href="/read/story/en/2/4.5/">'
                'Vol. 2 Chapter 4.5</a><div class="meta_r">Monday, 23rd October, 2023</div></div></div>')
        chapter = '<script>var pages = [{"url":"/image/p01.jpg"},{"url":"/image/p02.jpg"}];</script>'
        http = Mock()

        def document(url, **options):
            path = urlsplit(url).path
            if path == '/search/':
                self.assertEqual(options['data'], {'search': 'Story'})
                return title, url, {}
            self.assertEqual((options['method'], options['data']), ('POST', {'adult': 'true'}))
            return (work if path.startswith('/series/') else chapter), url, {}

        http.document.side_effect = document
        card, = source.catalogue(http, query='Story')[0]
        self.assertEqual(card['cover'], source.ROOT + '/cover.jpg')
        detail = source.inspect(card['url'], http)
        self.assertEqual(detail['authors'], ['Writer'])
        episode, = detail['episodes']
        self.assertEqual((episode['number'], episode['season'], episode['publishedAt']), (4.5, 2, '2023-10-23'))
        self.assertEqual(source.inspect(episode['url'], http)['pages'],
                         [source.ROOT + '/image/p01.jpg', source.ROOT + '/image/p02.jpg'])
