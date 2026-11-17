"""FOD, LINE Manga, Sokuyomi and SoraRaw through the Japan route (contract tests, no network)."""

import base64
from datetime import datetime, timezone
from io import BytesIO
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from PIL import Image

import manga_japan_routed as japan
import manga_japan_scramble as scramble
from manga_ninth_routes import prepare
from manga_page_media import page_reference
from manga_speedbinb import grant
from source_parser import PublicHttp, SourceError, public_url

FOD, LINE, SOKU, SORA = japan.SOURCES
ROUTES = {'hosts': ['manga.fod.fujitv.co.jp', 'manga.line.me', 'sokuyomi.jp', 'soraraw.com', 'mangarawgo.site'],
          'httpProxy': 'http://suwayomi-jp-router:8080'}
COOKIE = 'CloudFront-Policy=abc; CloudFront-Signature=d~e; CloudFront-Key-Pair-Id=K1'


def png(image):
    out = BytesIO()
    image.save(out, 'PNG')
    return out.getvalue()


def pixels(data):
    with Image.open(BytesIO(data)) as image:
        return image.convert('RGB')


def blocks(width, height, bw, bh):
    """An image whose blocks each have one distinct grey-free colour."""
    image = Image.new('RGB', (width, height), (7, 7, 7))
    for row in range(height // bh):
        for col in range(width // bw):
            index = row * (width // bw) + col
            image.paste((index * 37 % 256, index * 91 % 256, index * 13 % 256 + 1), (col * bw, row * bh, (col + 1) * bw, (row + 1) * bh))
    return image


def document(routes):
    def read(url, **options):
        for key, value in routes.items():
            if url.startswith(key):
                return (value if isinstance(value, str) else json.dumps(value)), url, {}
        raise AssertionError(url)

    http = Mock(document=Mock(side_effect=read), deadline=None)
    http.fork = Mock(return_value=http)
    return http


class RouteTests(TestCase):
    def test_fod_api_and_signed_image_routes(self):
        route = prepare('n9:fod', 'https://manga.fod.fujitv.co.jp/web/books/detail?book_id=1&episode_id=BT01', 'GET', None, {})
        self.assertTrue(route.japan)
        self.assertEqual(route.headers['Cookie'], 'sfsc=0')
        image = 'https://378783b0.manga.fod.fujitv.co.jp/books_file//browser//a//b//1.jpg'
        self.assertEqual(prepare('n9:fod', image, 'GET', None, {'Fod-Cookie': COOKIE}).headers, {'Cookie': COOKIE})
        for url, headers in ((image, {}), (image, {'Fod-Cookie': 'session=1'}),
                             ('https://manga.fod.fujitv.co.jp/web/books/detail?book_id=1', {}),
                             ('https://manga.fod.fujitv.co.jp/web/books/purchase?book_id=1&episode_id=B', {}),
                             ('https://evil.example/books_file/1.jpg', {'Fod-Cookie': COOKIE})):
            with self.assertRaises(SourceError):
                prepare('n9:fod', url, 'GET', None, headers)

    def test_line_sokuyomi_and_soraraw_routes(self):
        self.assertTrue(prepare('n9:linemanga', 'https://manga.line.me/book/viewer?id=Z0090127', 'GET', None, {}).japan)
        self.assertTrue(prepare('n9:linemanga', 'https://manga.line.me/api/book/product_list?product_id=E1', 'GET', None, {}))
        with self.assertRaises(SourceError):
            prepare('n9:linemanga', 'https://manga.line.me/api/book/purchase?id=1', 'GET', None, {})
        body = {'operationName': 'GetTitle', 'query': japan.SOKU_QUERIES['GetTitle'], 'variables': {'titleSlug': 'abcd1234'}}
        route = prepare('n9:sokuyomi', japan.SOKU_API, 'POST', body, {})
        self.assertTrue(route.post and route.japan and json.loads(route.data) == body)
        self.assertRegex(route.headers['Client-Version'], r'^20[0-9]{6}$')
        for bad in ({**body, 'query': 'mutation Signin { signin }'}, {**body, 'variables': {'titleSlug': '../x'}},
                    {**body, 'operationName': 'Signin'}):
            with self.assertRaises(SourceError):
                prepare('n9:sokuyomi', japan.SOKU_API, 'POST', bad, {})
        self.assertTrue(prepare('n9:soraraw', 'https://soraraw.com/manga/title-1/ch-2', 'GET', None, {}).japan)
        self.assertTrue(prepare('n9:soraraw', 'https://api.mangarawgo.site/1/2.json?t=1763348098000', 'GET', None, {}))
        for url in ('https://soraraw.com/api/login', 'https://api.mangarawgo.site/1/2.json',
                    'https://soraraw.com/manga/title-1?x=1'):
            with self.assertRaises(SourceError):
                prepare('n9:soraraw', url, 'GET', None, {})

    def test_japan_route_sends_only_listed_hosts_through_the_router(self):
        session = Mock()
        session.request.return_value = Mock(status_code=200, headers={}, is_redirect=False)
        with patch('manga_network_routes.configuration', return_value=ROUTES), patch('source_parser.pace'):
            http = PublicHttp(session=session, validate=lambda url: public_url(url, resolve_dns=False))
            http._open('https://manga.fod.fujitv.co.jp/web/books/genreRanking?category=0&sort_type=2&page=1',
                       action='n9:fod')
            http._open('https://cdn.sokuyomi.jp/volume/a/b.webp')
        first, second = session.request.call_args_list
        self.assertEqual(first.kwargs.get('proxies'), {'https': ROUTES['httpProxy']})
        self.assertEqual((first.kwargs['headers']['Cookie'], first.kwargs['headers']['Accept-Language'][:2]), ('sfsc=0', 'ja'))
        self.assertIsNone(second.kwargs.get('proxies'))


class ScrambleTests(TestCase):
    def setUp(self):
        # Compare exact pixels: keep the descrambled page lossless in tests.
        patcher = patch.object(scramble, '_jpeg', side_effect=png)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fod_restores_a_known_shuffle(self):
        source = blocks(96 * 3 + 10, 128 * 2 + 5, 96, 128)
        result = pixels(scramble.fod(png(source), 'aebb81'))
        colours = [source.getpixel((c * 96 + 5, r * 128 + 5)) for r in range(2) for c in range(3)]
        moved = [result.getpixel((c * 96 + 5, r * 128 + 5)) for r in range(2) for c in range(3)]
        self.assertEqual(sorted(moved), sorted(colours))
        # Regression pin of the implementation that rebuilt a live FOD page correctly.
        self.assertEqual([colours.index(value) for value in moved], [0, 1, 5, 4, 3, 2])
        self.assertEqual(result.getpixel((96 * 3 + 4, 60)), (7, 7, 7))

    def test_line_portal_and_sokuyomi_grids(self):
        source = blocks(40, 40, 20, 20)
        result = pixels(scramble.line(png(source), 2, 20, ['3', '2', '1', '0']))
        self.assertEqual(result.getpixel((5, 5)), source.getpixel((25, 25)))
        self.assertEqual(result.getpixel((25, 5)), source.getpixel((5, 25)))
        with self.assertRaises(SourceError):
            scramble.line(png(source), 2, 20, ['0', '0', '1', '2'])
        grid = blocks(80, 40, 20, 10)
        result = pixels(scramble.sokuyomi(png(grid)))
        self.assertEqual(result.getpixel((25, 5)), grid.getpixel((5, 15)))
        self.assertEqual(result.getpixel((65, 35)), grid.getpixel((65, 35)))

    def test_soraraw_canva_modes_permute_every_pixel(self):
        import numpy

        width, height = 470, 452
        values = numpy.arange(width * height, dtype=numpy.uint32)
        rgb = numpy.stack([(values >> 16) & 255, (values >> 8) & 255, values & 255], axis=-1).astype(numpy.uint8)
        source = Image.fromarray(rgb.reshape(height, width, 3), 'RGB')
        for decode in (lambda data: scramble.canva(data, '912517', 'f9739ddf-bb0c-47d9-b0fd-0b41e95833d5'),
                       lambda data: scramble.canva2(data, '912517')):
            result = numpy.asarray(pixels(decode(png(source))), dtype=numpy.uint32)
            flat = (result[..., 0] << 16) | (result[..., 1] << 8) | result[..., 2]
            self.assertEqual(sorted(flat.ravel().tolist()), values.tolist())
        result = numpy.asarray(pixels(scramble.canva2(png(source), '912517')), dtype=numpy.uint32)
        flat = ((result[..., 0] << 16) | (result[..., 1] << 8) | result[..., 2]).ravel()
        # Regression pin of the implementation that rebuilt a live SoraRaw canva2 page correctly.
        self.assertEqual(flat[:3].tolist(), PINNED_CANVA2)


PINNED_CANVA2 = [80194, 80193, 80192]


class AdapterTests(TestCase):
    def test_fod_lists_free_episodes_and_signs_page_requests(self):
        detail = {'book_detail': {'book_id': '1363368', 'book_name': 'ホタルの嫁入り', 'episode_id': 'BT01',
                                  'genres': [{'name': '女性'}], 'authors': [{'name': '作者'}]},
                  'book_series': [{'book_id': '2510805', 'episode_id': 'BT02', 'book_name': '無料版', 'is_free': True,
                                   'episode_count': 1, 'episode_price_start': '2026-11-01 00:00:00.000000'},
                                  {'book_id': '2510806', 'episode_id': 'BT03', 'book_name': '有料', 'is_free': False}]}
        http = document({'https://manga.fod.fujitv.co.jp/web/books/detail': detail})
        row, chapters = FOD.series(http, 'https://manga.fod.fujitv.co.jp/books/1363368/BT01')
        self.assertEqual((row['title'], row['genres'], [c['title'] for c in chapters]), ('ホタルの嫁入り', ['女性'], ['無料版']))
        chapter = FOD.site_link(chapters[0]['url'])
        self.assertEqual(FOD.title_for(chapter), 'https://manga.fod.fujitv.co.jp/books/1363368/BT01')
        self.assertEqual(FOD.row(SimpleNamespace(title='x', cover='', description='', author='', aliases=()),
                                 'https://manga.fod.fujitv.co.jp/books/1363368/OTHER')['id'], row['id'])
        viewer = {'GUARDIAN_SERVER': 'https://378783b0.manga.fod.fujitv.co.jp/books_file/', 'ADDITIONAL_QUERY_STRING': '',
                  'book_data': {'s3_key': 'browser\\/AB\\/CD\\/', 'imaged_reflow': False}, 'pages_data': {'keys': ['aebb81', '9e291a']}}
        http = document({'https://manga.fod.fujitv.co.jp/web/books/licenceKey': viewer})
        http.session = SimpleNamespace(cookies=[SimpleNamespace(name=n, value=v) for n, v in
                                                (('Zk-Session-Key', 'x'), ('CloudFront-Policy', 'abc'),
                                                 ('CloudFront-Signature', 'd~e'), ('CloudFront-Key-Pair-Id', 'K1'))])
        refs = FOD.pages(http, chapter)
        target, referer, page = grant(page_reference(refs[1])[0])
        self.assertEqual(target, 'https://378783b0.manga.fod.fujitv.co.jp/books_file//browser//AB//CD///2.jpg')
        self.assertEqual((page.cookie, page.scheme, page.action), (COOKIE, 'fod:9e291a', 'n9:fod'))
        http = document({'https://manga.fod.fujitv.co.jp/web/books/licenceKey': {**viewer, 'book_data': None}})
        with self.assertRaises(SourceError):
            FOD.pages(http, chapter)

    def test_line_reads_free_rows_and_both_viewer_layouts(self):
        product = {'result': {'product': {'id': 'Z0001684', 'name': 'Title', 'series_name': 'Title', 'conclusion': False},
                              'rows': [{'id': 'Z0090127', 'name': 'Title 1', 'volume': 0, 'selling_buy_price': 0},
                                       {'id': 'Z0090128', 'name': 'Title 2', 'volume': 1, 'selling_buy_price': 50},
                                       {'id': 'Z0090129', 'name': 'Title 3', 'volume': 2, 'selling_buy_price': 50,
                                        'expired_on': 1763348098}]}}
        http = document({'https://manga.line.me/api/book/product_list': product})
        row, chapters = LINE.series(http, 'https://manga.line.me/product/periodic?id=Z0001684')
        self.assertEqual(([c['title'] for c in chapters], row['status']), (['1', '3'], 'ongoing'))
        chapter = LINE.site_link(chapters[0]['url'])
        self.assertEqual(LINE.title_for(chapter), 'https://manga.line.me/product/periodic?id=Z0001684')
        plain = ("var imgs = {};\n imgs[0] = {\n 'url':    'https://cdn.example/a.jpg',\n 'height': 10\n };\n"
                 " imgs[1] = {\n 'url': 'https://cdn.example/inline_ads_banner.jpg',\n };\n isPortal:  false ,\n")
        self.assertEqual(LINE.pages(document({'https://manga.line.me/book/viewer': plain}), chapter), ['https://cdn.example/a.jpg'])
        portal = ("portal_pages[0] = {\n 'url': 'https://cdn.example/p.jpg',\n 'hc': 2,\n 'bwd': 64,\n };\n"
                  "portal_pages[0].metadata.m[0] = '1';\nportal_pages[0].metadata.m[1] = '0';\n isPortal: true,\n")
        refs = LINE.pages(document({'https://manga.line.me/book/viewer': portal}), chapter)
        self.assertEqual(grant(page_reference(refs[0])[0])[2].scheme, 'line:2:64:1:0')

    def test_sokuyomi_hides_paid_issues(self):
        edge = lambda slug, coin, campaign=None, sale=True: {'node': {'slug': slug, 'name': slug, 'chapter_number': 1,
                                                                      'consumption_coin': coin, 'is_available_for_sale': sale,
                                                                      'chapter_consumption_coin': campaign}}
        data = {'data': {'getTitle': {'name': '君を食べたい', 'is_adult': False, 'tags': [{'name': 'tag'}]},
                         'listVolume': {'edges': []},
                         'listChapter': {'edges': [edge('free0001', 0), edge('paid0001', 30),
                                                   edge('camp0001', 30, {'consumption_coin': 0})]}}}
        http = document({japan.SOKU_API: data})
        row, chapters = SOKU.series(http, 'https://sokuyomi.jp/comics/title001/detail/')
        self.assertEqual(sorted(urlsplit(c['url']).path for c in chapters),
                         ['/viewer/chapter/camp0001/', '/viewer/chapter/free0001/'])
        self.assertEqual(row['tags'], ['tag'])
        viewer = {'data': {'getChapterViewer': {'chapter_pages': [{'page_number': 2, 'key': 'c/b.webp'},
                                                                  {'page_number': 1, 'key': 'c/a.webp'}]}}}
        refs = SOKU.pages(document({japan.SOKU_API: viewer}), SOKU.site_link(chapters[0]['url']))
        first = grant(page_reference(refs[0])[0])
        self.assertEqual((first[0], first[2].scheme), ('https://cdn.sokuyomi.jp/c/a.webp', 'sokuyomi'))
        with self.assertRaises(SourceError):
            SOKU.pages(document({japan.SOKU_API: {'errors': [{'message': 'locked'}], 'data': None}}),
                       SOKU.site_link(chapters[0]['url']))

    def test_soraraw_decrypts_the_page_manifest(self):
        key = bytes(range(32))
        iv = bytes(range(16, 32))
        encryptor = Cipher(algorithms.AES(key), modes.CTR(iv)).encryptor()
        sealed = iv + encryptor.update(b'c912517/001_a.jpg') + encryptor.finalize()
        entry = base64.urlsafe_b64encode(japan.xor(sealed, japan.IMAGE_KEY)).decode().rstrip('=')
        manifest = base64.urlsafe_b64encode(japan.xor(json.dumps([{'order': 1, 'b': entry}]).encode(),
                                                      japan.MANIFEST_KEY)).decode()
        chapter = {'chapter': {'id': '912517', 'manga_id': 62411, 'mode': 'canva2', 'uuid': key.hex(),
                               'updated_at': '2026-11-17T10:14:38.000Z', '_b': 'https://lh2.rawcontent.top'}}
        page = ('<script id="__NEXT_DATA__" type="application/json">'
                + json.dumps({'props': {'pageProps': {'data': chapter}}}) + '</script>')
        SORA.cache.clear()
        http = document({'https://soraraw.com/manga/title-1/ch-7-1': page,
                         'https://soraraw.com/config.json': {'apiImage': 'https://api.mangarawgo.site', 'm': 1},
                         'https://api.mangarawgo.site/62411/912517.json': {'d': manifest}})
        refs = SORA.pages(http, 'https://soraraw.com/manga/title-1/ch-7-1')
        target, _, layout = grant(page_reference(refs[0])[0])
        self.assertEqual((target, layout.scheme), ('https://lh2.rawcontent.top/c912517/001_a.jpg', 'canva2:912517'))
        called = http.document.call_args_list[-1].args[0]
        stamp = int(datetime(2026, 11, 17, 10, 14, 38, tzinfo=timezone.utc).timestamp() * 1000)
        self.assertEqual(called, f'https://api.mangarawgo.site/62411/912517.json?t={stamp}')

    def test_soraraw_search_reads_the_site_catalogue_files(self):
        SORA.cache.clear()
        http = document({'https://soraraw.com/config.json': {'apiImage': 'https://api.mangarawgo.site', 'm': 2},
                         'https://soraraw.com/mangas_1.json': {'list': [{'name': 'ブルーロック', 'slug': 'buruu-rokku-57248',
                                                                          'views': 9, 'is_adult': 'no'}]},
                         'https://soraraw.com/mangas_2.json': {'list': [{'name': 'Other', 'slug': 'other-1', 'views': 1,
                                                                          'alt_names': 'ブルーロック 外伝', 'is_adult': 'yes'}]}})
        rows, more = SORA.catalogue(http, query='ブルーロック')
        self.assertEqual(([r['title'] for r in rows], more), (['ブルーロック', 'Other'], False))
        self.assertTrue(rows[1].get('adult'))
