from html import escape
from io import BytesIO
import json
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from manga_gigaviewer import SOURCES, SEARCH, graphql_form, group_query, relay_id
from manga_native_sources import saved_reader_url
from manga_page_media import decode_page, page_reference
from source_parser import PublicHttp, SourceAccessError, SourceError, public_url


SOURCE = next(adapter for adapter in SOURCES if adapter.NAME == 'Comic Action')
ROOT = SOURCE.ROOT
STORY = ROOT + '/series/12'
FIRST = ROOT + '/episode/34'


class GigaViewerTests(TestCase):
    def test_series_paginates_by_id_and_opens_only_public_image_pages(self):
        http = Mock()
        info = {'databaseId': '12', 'title': '作品', 'firstEpisode': {'permalink': FIRST},
                'episodes': {'totalCount': 2}, 'volumes': {'totalCount': 0}}
        product = {'id': '34', 'isPublic': True, 'title': '第1話', 'series': {'id': '12', 'title': '作品'},
                   'pageStructure': {'choJuGiga': 'baku', 'pages': [{'type': 'advertisement'},
                       {'type': 'main', 'src': 'https://cdn-img.comic-action.com/page.jpg'}]}}

        def fetch(url, **options):
            args = urlsplit(url)
            public_url(url, resolve_dns=False)
            if args.path == '/graphql':
                self.assertTrue(graphql_form(SOURCE.host, options['data']))
                body = json.dumps({'data': {'series': info}})
            elif args.path.startswith('/api/'):
                offset = parse_qs(args.query)['offset'][0]
                identity = '35' if offset == '0' else '34'
                body = json.dumps([{'readable_product_id': identity, 'title': '話', 'viewer_uri': ROOT + '/episode/' + identity,
                                    'purchase_info': {'can_read': identity == '34', 'unavailable': False}}])
            else:
                value = escape(json.dumps({'readableProduct': product}), quote=True)
                body = f'<script class="js-valve" data-giga_series="12"></script><script id="episode-json" data-value="{value}"></script>'
            return body, url, {}

        http.document.side_effect = fetch
        title = SOURCE.inspect(STORY, http)
        self.assertEqual([row['available'] for row in title['episodes']], [True, False])
        self.assertEqual(http.document.call_count, 3)
        page, = SOURCE.inspect(FIRST, http)['pages']
        self.assertEqual(page_reference(page)[2:], (8, 'giga-image'))
        product['isPublic'] = False
        with self.assertRaises(SourceAccessError):
            SOURCE.inspect(FIRST, http)
        product['isPublic'] = True
        product['id'] = '35'
        with self.assertRaisesRegex(SourceError, 'другую главу'):
            SOURCE.inspect(FIRST, http)

        saved = Mock()
        saved.get.return_value = [{'realUrl': FIRST, 'index': 1}]
        self.assertEqual(saved_reader_url(SOURCE, saved, {'baseUrl': ROOT}, FIRST, 1, 1, {'url': '12'}), FIRST)

    def test_graphql_allows_only_fixed_public_operations_on_publisher_domains(self):
        body = json.dumps({'query': SEARCH, 'variables': {'keyword': '犬'}}).encode()
        session = Mock()
        session.request.return_value = Mock(status_code=200)
        with patch('source_parser.pace'):
            http = PublicHttp(session=session, validate=lambda url: public_url(url, resolve_dns=False))
            http._open(ROOT + '/graphql', method='POST', action='giga-graphql', data=body)
            self.assertEqual(session.request.call_args.kwargs['headers']['Content-Type'], 'application/json')
            for query, args in (('mutation { test }', {}), (group_query(1), {'id0': relay_id('42')})):
                with self.assertRaises(SourceError):
                    http._open(ROOT + '/graphql', method='POST', action='giga-graphql',
                               data=json.dumps({'query': query, 'variables': args}).encode())
        self.assertEqual(session.request.call_count, 1)

    def test_giga_uses_aligned_transpose_and_preserves_edges(self):
        url = 'https://cdn-img.comic-action.com/page.jpg#mv_giga_page=baku'
        _, tiles, alignment, _ = page_reference(url)
        raw = BytesIO()
        with Image.new('RGB', (77, 87), 'white') as image:
            image.paste((32, 32, 32), (16, 0, 32, 16))
            image.paste((160, 160, 160), (0, 16, 16, 32))
            image.save(raw, 'PNG')
        with Image.open(BytesIO(decode_page(raw.getvalue(), tiles, alignment))) as result:
            self.assertAlmostEqual(result.getpixel((24, 8))[0], 160, delta=2)
            self.assertAlmostEqual(result.getpixel((8, 24))[0], 32, delta=2)
            self.assertAlmostEqual(result.getpixel((72, 82))[0], 255, delta=2)
