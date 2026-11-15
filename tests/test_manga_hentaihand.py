import json
from unittest import TestCase
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from manga_hentaihand import HentaiHand, SOURCES, public_api
from manga_native_sources import saved_reader_url
from manga_source_urls import split_reader_url
from source_parser import SourceError, public_url


SOURCE = next(adapter for adapter in SOURCES if adapter.LANGUAGE == 'ru')
TITLE = SOURCE.ROOT + '/en/comic/story'
CARD = {'slug': 'story', 'title': 'Story', 'alternative_title': 'Alternate',
        'category': {'name': 'Genre'}, 'tags': [{'name': 'Tag'}], 'artists': [{'name': 'Artist'}]}


class HentaiHandTests(TestCase):
    def test_language_profile_and_single_chapter_keep_original_identity(self):
        source = HentaiHand(SOURCE.ROOT, SOURCE.NAME, SOURCE.SOURCE_ID, SOURCE.LANGUAGE, SOURCE.languages, Mock())
        http = Mock()

        def fetch(url, *, action, headers):
            self.assertEqual(action, 'hentaihand-json')
            self.assertEqual(headers['Referer'], source.ROOT + '/')
            public_url(url, resolve_dns=False)
            request = urlsplit(url)
            if request.path == '/api/comics':
                self.assertEqual(parse_qs(request.query)['languages[-1]'], ['31'])
                payload = {'data': [CARD], 'next_page_url': '/api/comics?page=2'}
            elif request.path.endswith('/images'):
                payload = {'images': [{'page': 2, 'source_url': '/page-2.png'},
                                      {'page': 1, 'source_url': '/page-1.png'}]}
            else:
                payload = CARD
            return json.dumps(payload), url, {}

        http.document.side_effect = fetch
        rows, more = source.catalogue(http, query='Story')
        self.assertTrue(more)
        self.assertEqual(split_reader_url(rows[0]['url']), (source.SOURCE_ID, TITLE))
        detail = source.inspect(rows[0]['url'], http)
        self.assertEqual(http.document.call_count, 2)
        self.assertEqual((detail['pages'], detail['genres'], detail['tags']), ([], ['Genre'], ['Tag']))
        episode, = detail['episodes']
        self.assertEqual(source.inspect(episode['url'], http)['pages'],
                         [source.ROOT + '/page-1.png', source.ROOT + '/page-2.png'])
        self.assertEqual(source.page_headers(episode['url']), {'Referer': TITLE})

        old = Mock()
        old.get.return_value = [{'url': 'story', 'index': 1}]
        self.assertEqual(saved_reader_url(source, old, {'baseUrl': source.ROOT}, '/en/comic/story', 5, 1),
                         episode['url'])
        with self.assertRaises(SourceError):
            source.inspect(TITLE + '?mv_manga_source=999', http)

    def test_public_get_endpoints_allow_only_expected_parameters(self):
        self.assertTrue(public_api(SOURCE.host, '/api/comics', 'page=1&languages%5B-1%5D=31'))
        self.assertTrue(public_api(SOURCE.host, '/api/comics/' + 'a' * 255, ''))
        self.assertFalse(public_api(SOURCE.host, '/api/comics/' + 'a' * 256, ''))
        for host, path, query in (
            ('unknown.example', '/api/comics', 'page=1'),
            (SOURCE.host, '/api/comics', 'page=1&page=2'),
            (SOURCE.host, '/api/comics/story/images', 'token=secret'),
            (SOURCE.host, '/api/login', ''),
        ):
            with self.subTest(path=path, query=query):
                self.assertFalse(public_api(host, path, query))
