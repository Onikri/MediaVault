import json
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from manga_iken import SOURCES
from manga_native_sources import saved_reader_url
from source_parser import SourceAccessError, SourceError, public_url


ADAPTER = next(adapter for adapter in SOURCES if adapter.NAME == 'Magus Manga')
TITLE = '/series/example%27s-quest%21'
POST = {'id': 1, 'slug': "example's-quest!", 'postTitle': "Example's Quest!",
        'seriesType': 'MANHWA', 'genres': [{'name': 'Adventure'}]}
OPEN = {'id': 31, 'slug': 'chapter-1.5', 'number': '1.5'}
PAID = {'id': 32, 'slug': 'chapter-2', 'number': '2', 'price': 7}


class Http:
    def __init__(self):
        self.calls = []

    def document(self, url, **options):
        public_url(url, resolve_dns=False)
        self.calls.append(url)
        path = urlsplit(url).path
        query = parse_qs(urlsplit(url).query, keep_blank_values=True)
        if path == '/api/query':
            assert query['genreIds'] == ['29']
            result = {'posts': [POST, {**POST, 'slug': 'novel', 'isNovel': True}], 'totalCount': 81}
        elif path == '/api/post':
            assert query['postSlug'] == ["example's-quest!"]
            result = {'post': {**POST, 'chapters': [PAID]}, 'totalChapterCount': 2}
        elif path == '/api/chapters':
            assert query['postId'] == ['1']
            result = {'post': {'chapters': [OPEN, PAID]}}
        elif path == '/api/chapter':
            assert query['chapterId'] == ['31']
            result = {'chapter': {'images': [{'url': '/page-10.jpg', 'order': 0}, {'url': '/page-2.jpg', 'order': 1}]}}
        else:
            raise AssertionError(url)
        return json.dumps(result), url, {}


class IkenMigration(TestCase):
    def test_punctuation_filter_complete_chapter_list_and_filename_order(self):
        http = Http()
        rows, more = ADAPTER.catalogue(http, page=2, tag='29')
        row, = rows
        self.assertTrue(more)
        self.assertEqual(row['url'], ADAPTER.ROOT + TITLE)
        self.assertEqual(row['format'], 'manhwa')
        self.assertEqual(ADAPTER.saved_title_url(ADAPTER.site_link("/example's-quest!#1")), row['url'])
        title = ADAPTER.inspect(row['url'], http)
        chapter, = title['episodes']
        self.assertEqual(chapter['number'], 1.5)
        self.assertEqual(ADAPTER.inspect(chapter['url'], http)['pages'],
                         [ADAPTER.ROOT + '/page-2.jpg', ADAPTER.ROOT + '/page-10.jpg'])
        with self.assertRaises(SourceAccessError):
            ADAPTER.inspect(row['url'] + '/chapter-2', http)
        self.assertEqual(sum('/api/chapter?' in url for url in http.calls), 1)

    def test_transport_rejects_unrelated_apis_duplicates_and_path_injection(self):
        for target in ('/api/analytics/updateViews', '/api/chapter?chapterId=2&chapterId=3',
                       '/api/post?postSlug=..%2Fadmin', '/api/post?postSlug=.%2E',
                       '/api/query?page=1&perPage=500&searchTerm=',
                       '/api/posts?page=1&perPage=100'):
            with self.subTest(target=target), self.assertRaises(SourceError):
                public_url(ADAPTER.api_root + target, resolve_dns=False)
        self.assertEqual(ADAPTER.site_link(ADAPTER.ROOT + '/series/title%2Fchapter'), '')

    def test_duplicate_slugs_keep_their_ids_on_reader_and_saved_links(self):
        alternate = {**OPEN, 'id': 34}

        def api(http, endpoint, **params):
            if endpoint == 'post':
                return {'post': {**POST, 'chapters': [OPEN, alternate]}}
            return {'chapter': {'images': [{'url': f"/{params['chapterId']}.jpg"}]}}

        bridge = Mock()
        bridge.get.return_value = [{'index': 8, 'url': TITLE + '/chapter-1.5#34',
                                   'realUrl': ADAPTER.ROOT + TITLE + '/chapter-1.5'}]
        with patch.object(ADAPTER, 'api', side_effect=api):
            episodes = ADAPTER.inspect(ADAPTER.ROOT + TITLE, None)['episodes']
            self.assertEqual([row['url'].split('=')[-1] for row in episodes], ['31', '34'])
            saved = saved_reader_url(ADAPTER, bridge, {'baseUrl': ADAPTER.ROOT}, ADAPTER.ROOT + TITLE, 42, 8)
            self.assertEqual(saved, episodes[1]['url'])
            self.assertEqual(ADAPTER.inspect(saved, None)['pages'], [ADAPTER.ROOT + '/34.jpg'])
            self.assertEqual(ADAPTER.page_headers(saved), {'Referer': saved.partition('?')[0]})
            with self.assertRaises(SourceError):
                ADAPTER.inspect(episodes[0]['url'].replace('=31', '=99'), None)
