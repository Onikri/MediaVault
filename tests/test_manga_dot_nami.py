import json
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import manga_mangadot as dot
import manga_namicomi as nami
from manga_dot_wire import route_data
from manga_native_sources import saved_reader_url
from source_parser import PublicHttp, SourceAccessError, SourceError, public_url


def flatten(value, flat):
    index = len(flat)
    flat.append(None)
    if isinstance(value, dict):
        flat[index] = {f'_{flatten(key, flat)}': flatten(item, flat) for key, item in value.items()}
    elif isinstance(value, list):
        flat[index] = [flatten(item, flat) for item in value]
    else:
        flat[index] = value
    return index


def wire(route, data):
    flat = []
    flatten({route: data}, flat)
    return json.dumps(flat)


class MangaDotTests(TestCase):
    def test_route_decodes_later_promise_and_reused_slot(self):
        raw = '[{"_1":2},"pages/ViewAllPage",["P",19]]\nP19:[{"_4":5},"data",["Z",6],"a\u2028b"]\n'
        self.assertEqual(route_data(raw, dot.BROWSE_ROUTE), {'data': 'a\u2028b'})
        with self.assertRaises(SourceError):
            route_data('[{"_1":0},"pages/ViewAllPage"]', dot.BROWSE_ROUTE)

    def test_catalogue_details_chapter_origins_and_saved_volume(self):
        http = Mock()
        source = next(item for item in dot.SOURCES if item.LANGUAGE == 'pt-BR')
        card = {'manga_id': 7, 'title': 'Story', 'photo': '/cover.jpg'}
        rows = {'results': [card], 'pagination': {'current_page': 2, 'total_pages': 3}}
        word = {'id': 7, 'title': 'Story', 'country_of_origin': 'KR', 'genres': ['Fantasy', 'Josei'],
                'alt_titles': ['História'], 'tags': [{'tags': [{'name': 'Magic'}]}]}
        content = {'mangaData': {'manga': word, 'total_volumes': 1}}
        chapters = [{'id': 17, 'language': 'pt-br', 'chapter_number': 5.5, 'source': 'user'},
                    {'id': 21, 'language': 'en', 'chapter_number': 6},
                    {'id': 22, 'language': 'pt-br', 'chapter_number': 6, 'source': 'official'}]
        volumes = [{'id': 9, 'language': 'pt-br', 'volume_number': 2, 'source': 'official'}]
        reader = {'manga': {'id': 7}, 'images': [{'url': '/p1.jpg'}, {'url': 'https://cdn.example/p2.jpg'}]}

        def document(http, host, path, params=()):
            self.assertEqual(host, dot.ROOT)
            if path == '/api/search':
                self.assertEqual(params['lang'], 'pt-br')
                return json.dumps(rows)
            if path == '/view-all/most-tracked.data':
                return wire(dot.BROWSE_ROUTE, {'data': {'data': rows}})
            if path.endswith('.data'):
                self.assertEqual(params['_routes'], dot.TITLE_ROUTE)
                return wire(dot.TITLE_ROUTE, {'data': content})
            if path.endswith('/images'):
                self.assertIn(path, ('/api/uploads/17/images', '/api/chapters/22/images', '/api/chapters/9/images'))
                return json.dumps(reader)
            self.assertEqual(params['lang'], 'pt-br')
            return json.dumps(volumes if path.endswith('/volumes') else chapters)

        with patch.object(dot, 'document', side_effect=document):
            found, _ = source.catalogue(http)
            searched, more = source.catalogue(http, page=2, query='Story')
            self.assertTrue(more)
            chosen, = searched
            self.assertEqual(chosen['id'], found[0]['id'])
            toc = source.inspect(chosen['url'], http)
            self.assertEqual(toc['genres'], ['Fantasy'])
            self.assertEqual(toc['tags'], ['Josei', 'Magic'])
            self.assertEqual([row['number'] for row in toc['episodes']], [6, 5.5, 0])
            bridge = Mock()
            bridge.get.return_value = [{'index': 3, 'url': '{"id":"9","source":"official","isVolume":true}'}]
            saved = saved_reader_url(source, bridge, {'baseUrl': source.ROOT}, source.ROOT+'/7', 3, 3)
            self.assertEqual(saved, toc['episodes'][-1]['url'])
            for target in [saved, *(row['url'] for row in toc['episodes'])]:
                self.assertEqual(source.inspect(target, http)['pages'], [dot.ROOT + '/p1.jpg', 'https://cdn.example/p2.jpg'])
            with self.assertRaisesRegex(SourceError, 'другому тайтлу'):
                source.inspect(saved.replace('title=7', 'title=5'), http)

    def test_vocabulary_keeps_terms_beyond_a_single_titles_tag_limit(self):
        terms = [{'name': 'Tag ' + str(number)} for number in range(175)]
        data = [{'facets': {'genres': [{'key': 'Adventure'}]}}, {'categories': [{'tags': terms}]}]
        with patch.object(dot, 'get', side_effect=data):
            vocabulary = dot.SOURCES[0].vocabulary(Mock())
        self.assertEqual(len(vocabulary), 176)
        self.assertTrue(any(value['sourceId'] == 'tags:Tag 174' for value in vocabulary))


class NamiComiTests(TestCase):
    def setUp(self):
        self.http = Mock(deadline=None, timeout=(3, 8))
        pace = patch.object(nami.PACE, 'interval', 0)
        pace.start()
        self.addCleanup(pace.stop)

    def test_pagination_access_check_and_saved_reader(self):
        source = next(item for item in nami.SOURCES if item.LANGUAGE == 'es')
        tag = {'type': 'tag', 'attributes': {'name': {'en': 'Drama', 'es-es': 'Drama'}, 'group': 'genre'}}
        work = {'id': 'idComic', 'attributes': {'title': {'es-es': 'Historia', 'en': 'Story'},
                'description': {'es-es': 'Resumen'}, 'originalLanguage': 'ko'}, 'relationships': [tag]}
        access = {'Open1': True, 'Locked2': False}
        chapters = [{'id': identity, 'attributes': {'chapter': '2.5', 'volume': '1', 'name': 'Story',
                      'publishAt': '2020-03-03T04:10:00Z', 'titleId': 'idComic'}} for identity in access]
        checks = []

        def document(http, host, path, params=(), body=None, action=None):
            self.assertEqual(host, nami.API)
            args = dict(params)
            if path == '/gating/check':
                self.assertEqual(action, 'namicomi-access')
                self.assertTrue(nami.public_access_form(nami.GATE, body))
                ids = [row['entityId'] for row in json.loads(body)['entities']]
                checks.append(ids)
                return json.dumps({'data': {'attributes': {'map': {key: access[key] for key in ids}}}})
            if path == '/title/search':
                self.assertEqual(args['availableTranslatedLanguages[]'], 'es-es')
                return json.dumps({'data': [work], 'meta': {'offset': 0, 'limit': 20, 'total': 300}})
            if path == '/title/idComic':
                return json.dumps({'data': work})
            if path == '/chapter':
                self.assertEqual(args['translatedLanguages[]'], 'es-es')
                offset = args['offset']
                return json.dumps({'data': [chapters[offset]], 'meta': {'offset': offset, 'limit': 1, 'total': 2}})
            self.assertEqual(path, '/images/chapter/Open1')
            return json.dumps({'data': {'baseUrl': 'https://cdn.example/store', 'hash': 'commit',
                                        'source': [{'filename': 'p2.png'}, {'filename': 'p1.png'}]}})

        with patch.object(nami, 'document', side_effect=document):
            cards, more = source.catalogue(self.http)
            self.assertTrue(more)
            card, = cards
            self.assertEqual(card['title'], 'Historia')
            self.assertEqual(card['genres'], ['Drama'])
            chapter, = source.inspect(card['url'], self.http)['episodes']
            self.assertEqual(chapter['number'], 2.5)
            bridge = Mock()
            bridge.get.return_value = [{'index': 1, 'url': 'Open1'}]
            saved = saved_reader_url(source, bridge, {'baseUrl': source.ROOT}, card['url'], 5, 1)
            self.assertEqual(saved, chapter['url'])
            pages = source.inspect(saved, self.http)['pages']
            self.assertEqual([urlsplit(url).path.rsplit('/', 1)[1] for url in pages], ['p2.png', 'p1.png'])
            with self.assertRaises(SourceAccessError):
                source.inspect(saved.replace('Open1', 'Locked2'), self.http)
        self.assertEqual(checks, [['Open1', 'Locked2'], ['Open1'], ['Locked2']])

    def test_access_form_is_scoped_to_public_chapters(self):
        client = PublicHttp(session=Mock(), validate=lambda url: public_url(url, resolve_dns=False, allow_api=True))
        client.session.request.return_value = Mock(status_code=200)
        form = b'{"entities":[{"entityId":"example1","entityType":"chapter"}]}'
        client._open(nami.GATE, method='POST', data=form, action='namicomi-access')
        self.assertEqual(client.session.request.call_args.kwargs['headers']['Content-Type'], 'application/json')
        with self.assertRaises(SourceError):
            client._open(nami.GATE, method='POST', data=form.replace(b'chapter', b'title'), action='namicomi-access')
        self.assertFalse(nami.public_access_form('https://outside.example/gating/check', form))

    def test_gate_keeps_200_id_limit_and_requires_boolean_decisions(self):
        keys = ['chapter' + str(index) for index in range(201)]
        seen = []

        def document(http, host, path, *, body, action):
            batch = [item['entityId'] for item in json.loads(body)['entities']]
            seen.append(len(batch))
            return json.dumps({'data': {'attributes': {'map': {key: True for key in batch}}}})

        with patch.object(nami, 'document', side_effect=document):
            self.assertEqual(len(nami.gate(self.http, keys)), 201)
        self.assertEqual(seen, [200, 1])
        with patch.object(nami, 'document', return_value='{"data":{"attributes":{"map":{"chapter1":1}}}}'):
            with self.assertRaises(SourceError):
                nami.gate(self.http, ['chapter1'])
