import base64
import json
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from manga_vinetheme import SOURCES, flight_data, rsc_route
from manga_native_sources import catalogue_job, saved_reader_url
from source_parser import SourceAccessError, SourceError, public_url


SOURCE = next(s for s in SOURCES if s.NAME == 'Drake Scans')
TITLE = SOURCE.ROOT + '/series/comic/story'


def model(identity, value):
    return identity + ':' + json.dumps(value, ensure_ascii=False) + '\n'


class VineThemeTests(TestCase):
    def test_inline_flight_stream_retains_utf8_text_and_resolves_outlined_paths(self):
        synopsis = 'Путешествие 🌙\nПролог'
        text = f'a:T{len(synopsis.encode()):x},' + synopsis
        text += model('b', {'chapters': [{'number': 7.5, 'publishedAt': '$D2026-11-15T00:00:00Z'}]})
        text += model('c', {'series': {'title': 'Story', 'description': '$a'}, 'chapters': '$b:chapters', 'totalPages': 2})
        split = text.index('🌙') + 1
        first = '<script>self.__next_f.push(' + json.dumps([1, text[:split]]) + ')</script>'
        rest = base64.b64encode(text[split:].encode()).decode()
        second = '<script>self.__next_f.push(' + json.dumps([3, rest]) + ');</script>'
        result = flight_data(first + second, 'series')
        self.assertEqual(result['series']['description'], synopsis)
        self.assertEqual(result['chapters'], [{'number': 7.5, 'publishedAt': '2026-11-15T00:00:00Z'}])
        self.assertEqual(result['totalPages'], 2)
        with self.assertRaises(SourceError):
            flight_data(model('a', {'series': '$a', 'chapters': []}), 'series')

    def test_catalogue_and_chapter_routes_preserve_genres_and_public_pages(self):
        card = {'title': 'Story', 'urlSlug': 'story', 'originalTitle': 'Original',
                'description': '<p>Synopsis</p>', 'type': 'Manhwa',
                'genres': [{'name': 'Adventure', 'slug': 'adventure'}],
                'tags': [{'name': 'Reincarnation', 'slug': 'reincarnation'}]}
        first = model('0', {'series': card, 'totalPages': 2, 'chapters': [{'number': 2, 'isLocked': True}]})
        second = model('0', {'series': card, 'totalPages': 2, 'chapters': [{'number': 1.5, 'title': 'Episode'}]})
        http = Mock()

        def fetch(url, **options):
            parsed = urlsplit(url)
            query = parse_qs(parsed.query)
            public_url(url, resolve_dns=False)
            if parsed.path == '/api/series':
                self.assertEqual(query['tag'], ['reincarnation'])
                self.assertEqual(options['action'], 'vine-json')
                return json.dumps({'data': [card], 'meta': {'hasMore': True}}), url, {}
            self.assertEqual(options['action'], 'vine-rsc')
            if '/chapter/' in parsed.path:
                return model('0', {'chapter': {'isLocked': parsed.path.endswith('/2'),
                            'pages': [{'imageUrl': '/a.jpg'}, {'imageUrl': '/b.jpg'}]}}), url, {}
            return second if query.get('page') == ['2'] else first, url, {}

        http.document.side_effect = fetch
        rows, more = SOURCE.catalogue(http, page=2, tag='tag:reincarnation')
        self.assertEqual((rows[0]['url'], rows[0]['genres'], rows[0]['tags'], more),
                         (TITLE, ['Adventure'], ['Reincarnation'], True))
        chapter, = SOURCE.inspect(TITLE, http)['episodes']
        self.assertEqual(chapter['number'], 1.5)
        self.assertEqual(SOURCE.inspect(chapter['url'], http)['pages'],
                         [SOURCE.ROOT + '/a.jpg', SOURCE.ROOT + '/b.jpg'])
        with self.assertRaises(SourceAccessError):
            SOURCE.inspect(TITLE + '/chapter/2', http)

    def test_transport_limits_the_catalogue_endpoint_and_flight_redirects(self):
        with self.assertRaises(SourceError):
            public_url(SOURCE.ROOT + '/api/user?target=4', resolve_dns=False)
        query = 'page=1&limit=24&contentMode=comics&tag=adventure'
        with self.assertRaises(SourceError):
            public_url(SOURCE.ROOT + '/api/series?' + query + '&tag=other', resolve_dns=False)
        self.assertTrue(rsc_route(SOURCE.host, '/series/comic/story', 'sort=desc&_rsc='))
        self.assertFalse(rsc_route(SOURCE.host, '/series/comic/story', 'sort=desc&page=1&page=2'))
        self.assertFalse(rsc_route('other.example', '/series/comic/story', 'sort=desc'))

    def test_legacy_genre_and_tag_with_the_same_label_recover_separately(self):
        options = [{'sourceId': 'genre:action', 'label': 'Action', 'category': 'genre'},
                   {'sourceId': 'tag:action', 'label': 'Action', 'category': 'tag'}]
        source = Mock(wraps=SOURCE)
        source.vocabulary.return_value = options
        source.catalogue.return_value = [], False
        http = Mock()
        with patch('manga_native_sources.PublicHttp', return_value=http):
            catalogue_job(source, {'type': 'bridge-catalogue', 'term': {
                'sourceId': {'position': 2}, 'label': 'Action (10)', 'category': 'tag',
            }}, 7)
        source.catalogue.assert_called_once_with(http, page=7, tag='tag:action')

    def test_saved_opaque_ids_resolve_to_the_same_title_and_chapter(self):
        right = {'id': 'series-12', 'title': 'Story', 'urlSlug': 'story'}
        other = {'id': 'other-series', 'title': 'Story', 'urlSlug': 'different-story'}
        result = json.dumps({'data': [other, right], 'meta': {'hasMore': False}})
        series = model('0', {'series': right, 'chapters': [
            {'id': 'paid-31', 'number': 2, 'isLocked': True},
            {'id': 'free-30', 'number': 1.5},
        ]})
        http = Mock()
        http.document.side_effect = lambda url, **_: (result if '/api/series?' in url else series, url, {})
        old_title = {'url': 'series-12', 'title': 'Story'}
        old = Mock()
        old.get.return_value = [{'index': 4, 'url': 'free-30', 'chapterNumber': 1.5}]
        with patch('manga_vinetheme.PublicHttp', return_value=http):
            url = saved_reader_url(SOURCE, old, {}, SOURCE.ROOT + '/series-12', 11, 4, data=old_title)
            self.assertEqual(url, TITLE + '/chapter/1.5')
            old.get.return_value = [{'index': 4, 'url': 'paid-31', 'chapterNumber': 1.5}]
            with self.assertRaises(SourceError):
                saved_reader_url(SOURCE, old, {}, SOURCE.ROOT + '/series-12', 11, 4, data=old_title)
