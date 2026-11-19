"""Regression tests for direct-source port bugs found by the live audit (2026-11-19).

Each test pins one fix made after `scripts/live-audit-native-sources.py` opened
real titles and chapters on the site and failed in our code.
"""

import json
import time
from unittest import TestCase
from unittest.mock import Mock, patch

import manga_mangaball_native as ball
from source_parser import MAX_DOCUMENT, PublicHttp, SourceError, SourceTemporaryError


def streamed(blocks, headers=None):
    response = Mock(status_code=200, headers=headers or {'Content-Type': 'application/json'}, encoding='utf-8')
    response.iter_content.return_value = iter(blocks)
    return response


class DocumentLimitTests(TestCase):
    def http(self, blocks, deadline=None):
        http = PublicHttp(timeout=(3, 8), deadline=deadline)
        http._open = Mock(return_value=(streamed(blocks), 'https://example.org/api'))
        self.addCleanup(http.close)
        return http

    def test_default_limit_still_refuses_oversized_pages(self):
        blocks = [b'x' * 65536] * (MAX_DOCUMENT // 65536 + 1)
        with self.assertRaisesRegex(SourceError, 'слишком велики'):
            self.http(blocks).document('https://example.org/api')

    def test_caller_may_raise_the_limit_for_a_known_large_api(self):
        body = json.dumps({'data': ['c' * 1000] * 6000}).encode()  # ~6 MB, like One Piece's chapter list
        self.assertGreater(len(body), MAX_DOCUMENT)
        blocks = [body[i:i + 65536] for i in range(0, len(body), 65536)]
        text, _, _ = self.http(blocks).document('https://example.org/api', limit=24 * 1024 * 1024)
        self.assertEqual(len(json.loads(text)['data']), 6000)

    def test_a_slow_answer_is_a_temporary_error_not_an_oversized_page(self):
        http = self.http([b'{}', b'{}'], deadline=time.monotonic() - 1)
        with self.assertRaises(SourceTemporaryError) as caught:
            http.document('https://example.org/api')
        self.assertNotIn('велики', str(caught.exception))


class MangaBallChapterListingTests(TestCase):
    def test_api_requests_allow_long_chapter_listings(self):
        client = Mock()
        target = ball.API + '/chapter/chapter-listing-by-title-id'
        client.document.return_value = (json.dumps({'data': []}), target, {})
        with patch.object(ball, 'PublicHttp', return_value=client):
            ball.request(Mock(timeout=(3, 8), deadline=None), '/chapter/chapter-listing-by-title-id',
                         payload={'title_id': '68515540702284f8341784c8'})
        self.assertGreater(client.document.call_args.kwargs['limit'], 6 * 1024 * 1024)
        client.close.assert_called_once()


class XcomicEditionProbeTests(TestCase):
    def setUp(self):
        import manga_xcomic

        self.xcomic = manga_xcomic
        manga_xcomic._probes.clear()
        self.addCleanup(manga_xcomic._probes.clear)
        for pace in (manga_xcomic.PACE, manga_xcomic.PROBE_PACE):
            patcher = patch.object(pace, 'interval', 0)
            patcher.start()
            self.addCleanup(patcher.stop)
        import manga_native_registry

        profiles = dict(manga_native_registry.profiles()).values()
        self.fi = next(p for p in profiles if p.NAME == 'XCOMIC' and p.LANGUAGE == 'fi')
        self.en = next(p for p in profiles if p.NAME == 'XCOMIC' and p.LANGUAGE == 'en')

    def test_long_running_titles_with_hundreds_of_editions_open(self):
        ids = [f'c{i}' for i in range(340)]  # Chainsaw Man had 340 editions on 2026-11-19
        title = {'title': 'Chainsaw Man', 'comic_ids': ids}
        with patch.object(self.xcomic, 'title_node', return_value=('t1', title)):
            row, identity, data, declared = self.fi.resolve(Mock(deadline=None), 't1')
        self.assertEqual(len(declared), 340)

    def test_edition_probes_are_shared_between_language_profiles(self):
        ids = [f'c{i}' for i in range(200)]
        calls = []

        def node(http, operation, identity):
            calls.append(identity)
            index = int(identity[1:])
            return {'translatedLanguage': 'fi' if index % 50 == 0 else 'en', 'dbStatus': 'normal', 'isPublic': True,
                    'chaps_normal': index}

        with patch.object(self.xcomic, 'node', side_effect=node):
            finnish = self.fi.editions(Mock(deadline=None), ids)
            english = self.en.editions(Mock(deadline=None), ids)
        self.assertEqual([key for key, _ in finnish], ['c0', 'c50', 'c100', 'c150'])
        self.assertEqual(len(english), 196)
        self.assertEqual(len(calls), 200)  # the second profile reused every probe


class ToonLookChapterRedirectTests(TestCase):
    def setUp(self):
        import manga_native_registry

        self.source = next(p for p in dict(manga_native_registry.profiles()).values() if p.NAME == 'ToonLook')
        self.url = ('https://toonlook.com/29-chapter-1?lang=zh&mv_title=%2Fmanhwa%2Fh-mate-friends-with-benefits%2F'
                    '&mv_manga_source=' + self.source.SOURCE_ID)

    def test_chapter_moved_under_its_title_is_the_same_chapter(self):
        moved = 'https://toonlook.com/manhwa/h-mate-friends-with-benefits/29-chapter-1/?lang=zh'
        with patch.object(self.source, 'document', return_value=('<html></html>', moved)):
            _, actual = self.source.chapter_document(Mock(), self.url)
        self.assertEqual(actual, moved)

    def test_redirect_to_another_title_is_still_refused(self):
        other = 'https://toonlook.com/manhwa/another-title/29-chapter-1/?lang=zh'
        with patch.object(self.source, 'document', return_value=('<html></html>', other)):
            with self.assertRaisesRegex(SourceError, 'другую главу'):
                self.source.chapter_document(Mock(), self.url)


class ToomicsSpanishStoreTests(TestCase):
    def setUp(self):
        import manga_native_registry

        profiles = dict(manga_native_registry.profiles()).values()
        self.spain = next(p for p in profiles if p.NAME.startswith('Toomics') and p.LANGUAGE == 'es')
        self.latam = next(p for p in profiles if p.NAME.startswith('Toomics') and p.LANGUAGE == 'es-419')

    def test_spanish_profiles_read_the_merged_store_and_keep_saved_links(self):
        for profile in (self.spain, self.latam):
            self.assertEqual(profile.locale, 'esp')
            self.assertTrue(profile.parent_url('5800').startswith('https://global.toomics.com/esp/'))
            for prefix in ('esp', 'es', 'mx'):
                self.assertTrue(profile.is_title(f'https://global.toomics.com/{prefix}/webtoon/episode/toon/5800/search/Y'))
            self.assertFalse(profile.is_title('https://global.toomics.com/fr/webtoon/episode/toon/5800/search/Y'))

    def test_search_reads_the_current_answer_shape(self):
        html = ('<ul id="search-list-items"><li><a class="relative" href="/esp/webtoon/search/?toon=5800&amp;return=x">'
                '<img data-original="https://global.toomics.com/thumb.jpg"><strong>Love Factory</strong></a></li></ul>')
        http = Mock()
        target = 'https://global.toomics.com/esp/webtoon/ajax_search'
        http.document.return_value = (json.dumps({'webtoon': {'iSearchCount': 1, 'sHtml': html}, 'keyword': 'love'}), target, {})
        rows, _ = self.spain.catalogue(http, query='love')
        self.assertEqual([row['title'] for row in rows], ['Love Factory'])
        self.assertIn('/esp/webtoon/episode/toon/5800/', rows[0]['url'])


class MangaBoxHomeMirrorTests(TestCase):
    def setUp(self):
        import manga_html_families

        self.by_id = {source.SOURCE_ID: source for source in manga_html_families.SOURCES}

    def test_saved_links_on_redesigned_mirrors_read_from_the_mangabox_mirror(self):
        cases = {'1024627298672457456': ('www.manganato.gg', ('www.natomanga.com', 'www.natumanga.com', 'www.manganami.com')),
                 '2528986671771677900': ('www.mangakakalove.com', ('www.kakamanga.com', 'www.katamanga.com'))}
        for sid, (home, mirrors) in cases.items():
            source = self.by_id[sid]
            self.assertEqual(source.ROOT, 'https://' + home)
            for mirror in mirrors:
                url = source.canonical(f'https://{mirror}/manga/one-piece?mv_manga_source={sid}')
                self.assertEqual(url.split('?')[0], f'https://{home}/manga/one-piece')
                self.assertTrue(source.site_link(f'https://{mirror}/manga/one-piece'))  # redirects stay acceptable

    def test_other_mangabox_profiles_keep_their_mirror_links(self):
        source = self.by_id['4215511432986138970']  # Mangabat has no home mirror
        self.assertEqual(source.canonical('https://www.mangabats.com/manga/one-piece').split('?')[0],
                         'https://www.mangabats.com/manga/one-piece')

    def test_images_are_requested_with_the_site_origin_as_referer(self):
        source = self.by_id['1024627298672457456']
        self.assertEqual(source.page_headers('https://www.manganato.gg/manga/a/chapter-1?mv_manga_source=1'),
                         {'Referer': 'https://www.manganato.gg/'})


class MiauScanMoveTests(TestCase):
    def setUp(self):
        from bs4 import BeautifulSoup
        import manga_native_registry

        self.soup = BeautifulSoup
        self.source = dict(manga_native_registry.profiles())['6705370418823255358']

    def test_links_on_the_old_domain_open_on_the_new_one(self):
        self.assertEqual(self.source.ROOT, 'https://leer.lectovela.com')
        link = self.source.site_link('https://leemiau.com/manga/portugues-namorada-de-aluguel/')
        self.assertEqual(link, 'https://leer.lectovela.com/manga/portugues-namorada-de-aluguel/')

    def test_old_chapter_images_are_read_from_the_current_host(self):
        html = ('<div id="readerarea"><img data-src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" '
                'data-lm-orig-src="http://miauscans.com/wp-content/uploads/2023/01/01-187.jpg"></div>')
        pages = self.source.pages(self.soup(html, 'html.parser'), 'https://leer.lectovela.com/portugues-namorada-de-aluguel-24/')
        self.assertEqual(pages, ['https://leer.lectovela.com/wp-content/uploads/2023/01/01-187.jpg'])

    def test_reader_links_its_title_from_the_summary_card(self):
        html = '<a class="lm-reader-summary-mini" href="https://leer.lectovela.com/manga/condicion-matrimoni4l/">x</a>'
        self.assertEqual(self.source.series_link(self.soup(html, 'html.parser'), 'https://leer.lectovela.com/condicion-matrimoni4l-01/'),
                         'https://leer.lectovela.com/manga/condicion-matrimoni4l/')


class MangaMachinaMoveTests(TestCase):
    def setUp(self):
        import manga_rawkuma_overlay

        self.module = manga_rawkuma_overlay
        self.source = manga_rawkuma_overlay.SOURCES[0]

    def test_rawkuma_links_open_on_mangamachina(self):
        self.assertEqual(self.source.ROOT, 'https://mangamachina.com')
        self.assertTrue(self.source.canonical('https://rawkuma.me/manga/kingdom/').startswith('https://mangamachina.com/manga/kingdom'))
        self.assertTrue(self.module.public_api('mangamachina.com', '/api/series', 'lang=en&slugs=kingdom'))
        self.assertFalse(self.module.public_api('rawkuma.me', '/api/series', 'lang=en&slugs=kingdom'))

    def test_catalogue_reads_slim_cards_without_resolving_every_reference(self):
        card = {'slug': 'kingdom', 'title': 'Kingdom', 'cover': '/media/_covers/kingdom.jpg', 'langs': ['en'],
                'chapters': [{'slug': 'chapter-1', 'pages': []}]}
        refs = {str(i): ['$%d' % (i + 1)] * 2 for i in range(40)}  # references that double at every level
        stream = ''.join(f'{key}:{json.dumps(value)}\n' for key, value in refs.items()) + '41:' + json.dumps([card]) + '\n'
        raw = '<script>self.__next_f.push([1,' + json.dumps(stream) + '])</script>'
        http = Mock()
        http.document.return_value = (raw, 'https://mangamachina.com/manga?lang=en&order=popular&page=1', {})
        with patch.object(self.source.origin, 'interval', 0):
            rows, _ = self.source.catalogue(http)
        self.assertEqual([row['title'] for row in rows], ['Kingdom'])


class SpeedBinbReaderHostTests(TestCase):
    def test_yondemill_chapters_open_in_the_bricks_reader(self):
        from manga_speedbinb import reader_url

        url = 'https://binb.bricks.pub/contents/3b4a9926-e2ce-429c-8e09-6f331ccfcf1d_1728028949/speed_reader?u0=dec9&u1=redirect'
        self.assertEqual(reader_url(url), url)
        with self.assertRaises(SourceError):
            reader_url('https://binb.example.com/contents/1/speed_reader')


class E621PostsShapeTests(TestCase):
    def setUp(self):
        import manga_booru_pools

        self.source = manga_booru_pools.E621()

    def test_bare_post_list_with_files_object(self):
        current = [{'id': 1, 'flags': {'deleted': False}, 'files': {
            'original': {'url': 'https://static1.e621.net/data/61/f9/61f9.jpg'},
            'sample': {'jpg': None, 'webp': None}, 'preview': {'jpg': 'https://static1.e621.net/data/preview/61/f9/61f9.jpg'}}},
            {'id': 2, 'flags': {'deleted': False}, 'files': {'original': {'url': None}, 'sample': {'jpg': None}, 'preview': {}}}]
        with patch.object(self.source, 'json', return_value=current):
            posts = self.source.posts(Mock(), ['1', '2'])
        self.assertEqual(self.source.image(posts['1']), 'https://static1.e621.net/data/61/f9/61f9.jpg')
        self.assertEqual(self.source.image(posts['1'], cover=True), 'https://static1.e621.net/data/preview/61/f9/61f9.jpg')
        self.assertEqual(self.source.image(posts['2']), '')  # withheld from anonymous readers: not rebuilt from md5

    def test_old_wrapped_shape_still_reads(self):
        old = {'posts': [{'id': 3, 'file': {'url': 'https://static1.e621.net/data/aa/bb/aabb.png'}}]}
        with patch.object(self.source, 'json', return_value=old):
            posts = self.source.posts(Mock(), ['3'])
        self.assertEqual(self.source.image(posts['3']), 'https://static1.e621.net/data/aa/bb/aabb.png')


class GalleryDeferredPageTests(TestCase):
    def setUp(self):
        import manga_gallery_adults

        self.module = manga_gallery_adults
        self.source = next(a for a in manga_gallery_adults.sources() if a.package == 'hentaizap')

    def test_long_gallery_lists_markers_without_fetching_reader_pages(self):
        http = Mock()
        pages = self.source.reader_pages(http, '1161174', 198)
        self.assertEqual(len(pages), 198)
        http.document.assert_not_called()
        self.assertEqual(pages[0], f'{self.source.ROOT}/{self.source.layout.page_prefix}/1161174/1/#mv_gallery_page')

    def test_marker_is_resolved_and_fetched_like_any_page(self):
        from manga_page_media import fetch_page, page_reference

        marker = self.source.reader_pages(Mock(), '1161174', 3)[1]
        reference = page_reference(marker)
        self.assertEqual(reference[3], 'gallery-page')
        page = marker.split('#')[0]
        jpeg = b'\xff\xd8\xff\xe0' + b'0' * 2048
        response = Mock(status_code=200, headers={'Content-Type': 'image/jpeg'})
        response.iter_content.return_value = iter([jpeg])
        http = Mock(deadline=None)
        http._open.return_value = (response, 'https://m1.hentaizap.com/1/2.jpg')
        with patch.object(type(self.source), 'reader_image', return_value='https://m1.hentaizap.com/1/2.jpg') as image:
            raw, mime = fetch_page(http, reference, {})
        image.assert_called_once_with(http, page)
        self.assertEqual(raw, jpeg)
        self.assertEqual(http._open.call_args.kwargs['headers'], {'Referer': page})

    def test_foreign_or_malformed_markers_are_refused(self):
        from manga_page_media import page_reference

        for value in ('https://evil.example/g/1/1/#mv_gallery_page',
                      f'{self.source.ROOT}/{self.source.layout.page_prefix}/1/1/?x=1#mv_gallery_page'):
            with self.assertRaises(SourceError):
                page_reference(value)


class JNovelRscRedirectTests(TestCase):
    def test_rsc_requests_follow_the_cache_key_redirect_only(self):
        from urllib.parse import urlsplit
        from manga_jnovel import route

        for url in ('https://j-novel.club/series?type=manga&page=1',
                    'https://j-novel.club/series?type=manga&page=1&_rsc',
                    'https://j-novel.club/series?type=manga&page=1&_rsc=1x2y3',
                    'https://j-novel.club/series/ascendance-of-a-bookworm-manga?_rsc=abc'):
            found = route(urlsplit(url), 'GET', None, {})
            self.assertTrue(found and found.redirect and found.headers.get('rsc') == '1', url)
        for url in ('https://j-novel.club/series?type=manga&_rsc=%2F..%2F',
                    'https://j-novel.club/series/x?other=1',
                    'https://j-novel.club/series?type=novel'):
            self.assertIsNone(route(urlsplit(url), 'GET', None, {}), url)


class DomainMoveTests(TestCase):
    def test_profiles_point_at_the_hosts_their_old_domains_redirect_to(self):
        import manga_native_registry

        profiles = dict(manga_native_registry.profiles())
        expected = {'2738031143723682744': 'https://www.goodtoon012.com', '3967449247820755680': 'https://dokiraw.men',
                    '6596496791271983268': 'https://008.toonkor.net', '4730948540511990292': 'https://kodokustudio.com',
                    '7393909338134202317': 'https://w4.theexiledheavyknight.com', '80073424419623517': 'https://mistscans.org',
                    '3062846066388633553': 'https://webtoonscan.org', '1024627298672457456': 'https://www.manganato.gg',
                    '2528986671771677900': 'https://www.mangakakalove.com'}
        for sid, root in expected.items():
            self.assertEqual(profiles[sid].ROOT.rstrip('/'), root, sid)

    def test_kodoku_api_answers_on_the_new_host(self):
        from manga_direct_payloads import public_api

        self.assertTrue(public_api('kodokustudio.com', '/api/series', ''))


class GalleryPathMoveTests(TestCase):
    def test_hennojin_titles_under_home_manga_are_titles(self):
        import manga_native_registry

        source = dict(manga_native_registry.profiles())['2486465102799235219']
        self.assertTrue(source.is_title('https://hennojin.com/home/manga/toraisi666-gal-illya-chan-english/'))
        self.assertFalse(source.is_title('https://hennojin.com/home/page/2/'))
        self.assertFalse(source.is_title('https://hennojin.com/home/'))

    def test_holonometria_cards_linking_their_first_episode_list_the_title(self):
        from bs4 import BeautifulSoup
        import manga_archive_ports
        import manga_native_registry

        source = dict(manga_native_registry.profiles())['1334492919632049277']
        html = ('<ul><li class="manga__item"><p class="manga__title">Vesta de Cooking</p><img src="/t.jpg">'
                '<a class="manga__btn" href="https://holoearth.com/en/alt/holonometria/manga/vestadecooking/ep0/">Read</a></li></ul>')
        page = 'https://holoearth.com/en/alt/holonometria/manga/'
        with patch.object(source, 'document', return_value=(BeautifulSoup(html, 'html.parser'), page)):
            rows, _ = manga_archive_ports.hololive(source, Mock(), 1, '', 'popular', '')
        self.assertEqual([row.path for row in rows], ['https://holoearth.com/en/alt/holonometria/manga/vestadecooking/'])
