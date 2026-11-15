from io import BytesIO
import json
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from manga_comici import SOURCES, decode_page, page_reference
from manga_native_sources import saved_reader_url
from online_sessions import Session
from source_parser import PublicHttp, SourceAccessError, SourceError, public_url


SOURCE = next(x for x in SOURCES if x.host == 'comicpash.jp')
TITLE = SOURCE.ROOT + '/series/story'
CHAPTER = SOURCE.ROOT + '/episodes/episode1'
STORY = {'id': 'story', 'name': '作品', 'description': '[{"children":[{"text":"概要"}]}]', 'tag': [{'name': '漫画'}]}
SUMMARY = {'id': 'episode1', 'title': '第1話'}
FREE = {'episodeId': 'episode1', 'hasAccess': True, 'accessType': 'free'}
LOCKED = {'episodeId': 'episode2', 'hasAccess': False, 'accessType': 'memberOnlyFree'}


class ComiciTests(TestCase):
    def test_public_chapter_uses_source_permission_and_exact_episode_identity(self):
        http = Mock()
        episode = {'id': 'episode1', 'summary': SUMMARY, 'access': FREE, 'series': STORY, 'contentId': 14,
                   'content': [{'type': 'viewer', 'viewerId': 'viewer'}], 'seriesEpisodeNumber': 1}

        def response(url, **options):
            name = urlsplit(url).path
            args = parse_qs(urlsplit(url).query)
            public_url(url, resolve_dns=False)
            if name == '/api/episodes':
                payload = {'series': {'summary': STORY, 'episodes': [{'id': 'episode2', 'title': '第2話'}, SUMMARY]}}
            elif name == '/api/series/access':
                payload = {'seriesAccess': {'seriesId': 'story', 'episodeAccesses': [FREE, LOCKED]}}
            elif name == '/api/episodes/episode1':
                payload = {'episode': episode}
            elif args['page-to'] == ['0']:
                payload = {'totalPages': 2}
            else:
                payload = {'result': [{'imageUrl': f'https://viewer.comicpash.jp/images/{n}.jpg',
                                       'scramble': json.dumps(list(range(16))), 'sort': n} for n in (1, 0)]}
            return json.dumps(payload), url, {}

        http.document.side_effect = response
        title = SOURCE.inspect(TITLE, http)
        self.assertEqual((title['description'], title['tags'], title['pages']), ('概要', ['漫画'], []))
        self.assertEqual([item['available'] for item in title['episodes']], [True, False])
        urls = SOURCE.inspect(CHAPTER, http)['pages']
        self.assertEqual([page_reference(url)[0] for url in urls],
                         [f'https://viewer.comicpash.jp/images/{n}.jpg' for n in (0, 1)])
        for access in ({**FREE, 'hasAccess': False}, {**FREE, 'episodeId': 'sibling'}):
            episode['access'] = access
            http.document.reset_mock()
            with self.assertRaises(SourceAccessError if access['episodeId'] == 'episode1' else SourceError):
                SOURCE.inspect(CHAPTER, http)
            self.assertEqual(http.document.call_count, 1)

        client = Mock()
        client.get.return_value = [{'url': 'episode1', 'index': 3}]
        self.assertEqual(saved_reader_url(SOURCE, client, {'baseUrl': SOURCE.ROOT}, 'story', 7, 3), CHAPTER)

    def test_tile_mapping_keeps_remainders_and_never_sends_marker(self):
        source = BytesIO()
        with Image.new('RGB', (67, 66), 'white') as image:
            for pos in range(16):
                x, y = (pos // 4) * 16, (pos % 4) * 16
                image.paste((pos * 12,) * 3, (x, y, x + 16, y + 16))
            image.save(source, 'PNG')
        tiles = list(range(15, -1, -1))
        url = SOURCE.page_url('https://viewer.comicpash.jp/page.jpg?sig=a', tiles)
        bare, decoded = page_reference(url)
        self.assertEqual((bare, decoded), ('https://viewer.comicpash.jp/page.jpg?sig=a', tiles))
        session = Session('owner', {}, 100, kind='manga')
        self.assertEqual(session.resources[session.resource(url)], url)
        with Image.open(BytesIO(decode_page(source.getvalue(), decoded))) as result:
            self.assertEqual(result.size, (67, 66))
            self.assertAlmostEqual(result.getpixel((8, 8))[0], 180, delta=2)
            self.assertAlmostEqual(result.getpixel((56, 56))[0], 0, delta=2)
            self.assertAlmostEqual(result.getpixel((65, 65))[0], 255, delta=2)
        with self.assertRaises(SourceError):
            page_reference('https://unrelated.example/page.jpg#mv_comici_tiles=')

    def test_regional_proxy_is_fixed_and_only_used_for_comici_routes(self):
        session = Mock()
        redirect, success = Mock(status_code=307), Mock(status_code=200)
        redirect.headers = {'Location': '/ranking/manga?_rsc'}
        session.request.side_effect = [redirect, success, success]
        routes = {'hosts': [SOURCE.host], 'httpProxy': 'http://suwayomi-jp-router:8080'}
        with patch('manga_network_routes.configuration', return_value=routes), patch('source_parser.pace'):
            http = PublicHttp(session=session, validate=lambda url: public_url(url, resolve_dns=False))
            http._open(SOURCE.ROOT + '/ranking/manga', action='comici-rsc')
            http._open('https://unrelated.example/')
        self.assertEqual([call.kwargs.get('proxies') for call in session.request.call_args_list],
                         [{'https': routes['httpProxy']}, {'https': routes['httpProxy']}, None])
        with self.assertRaises(SourceError):
            public_url(SOURCE.ROOT + '/api/search?q=a&page=1&page=&size=24', resolve_dns=False)
