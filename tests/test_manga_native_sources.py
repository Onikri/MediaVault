"""Local contracts for native migration. Live origin parity is tracked separately."""

import os
import unittest
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

from catalogue_sources import fetch
from manga_discovery import installed_sources, search_source
from manga_download import download_chapter
import manga_mangashi
from manga_mangashi import ROOT, SOURCE_ID
from manga_mangahub import ONE_MANGA_CO, MangaHub, OneManga
from manga_native_sources import record_reader_url
from manga_sources import inspect
from source_parser import SourceError
from suwayomi_bridge import native_reader_url, page_image, PREFIX


SOURCE = {'id': SOURCE_ID, 'name': 'Manga-shi', 'lang': 'ru', 'baseUrl': ROOT}
TITLE = ROOT + '/manga/bluelock/'
FIRST = TITLE + 'glava-1/'
SECOND = TITLE + 'glava-1,5/'
PAGE = ROOT + '/media/example.png'
PNG = b'\x89PNG\r\n\x1a\n'
CATALOGUE = """
    <div id="manga-grid">
      <a href="/manga/bluelock/"><h3>Синяя тюрьма / Blue Lock</h3></a>
      <a href="https://other.example/manga/bluelock/"><h3>Blue Lock</h3></a>
    </div>
"""
TABLE = """
    <h1>Синяя тюрьма / Blue Lock</h1>
    <div id="chapters-list">
      <a href="/manga/bluelock/glava-1/"><span class="chapter-title">Глава 1</span></a>
      <a href="/manga/another/glava-8/"><span class="chapter-title">Похожий тайтл</span></a>
    </div>
    <div id="chapters-load-more"><a hx-get="/manga/bluelock/chapters/?page=2">Дальше</a></div>
"""


class Http:
    def document(self, url, **options):
        if '/catalog/' in url:
            fields = parse_qs(urlsplit(url).query)
            if 'q' in fields:
                assert fields['q'] == ['Blue Lock']
            else:
                assert fields['tag'] == ['42']
            return CATALOGUE, url, {}
        if url == TITLE:
            return TABLE, url, {}
        if url == TITLE + 'chapters/?page=2':
            return '<a href="' + SECOND + '"><span class="chapter-title">Том 2. Глава 1,5</span></a>', url, {}
        if url == SECOND:
            return f'<img class="reader-image" data-src="{PAGE}">', url, {}
        raise AssertionError(url)

    def close(self):
        pass

    def download(self, url, target, *, headers, maximum):
        assert url == PAGE and headers['Referer'] == SECOND
        target.write_bytes(PNG)


class NativeMigrationTest(unittest.TestCase):
    def setUp(self):
        pause = patch('manga_mangashi.time.sleep')
        self.addCleanup(pause.stop)
        pause.start()

    def test_search_and_filtered_catalogue_keep_the_same_source_identity(self):
        job = {'type': 'bridge', 'source': SOURCE, 'domain': 'manga-shi.org',
               'term': {'sourceId': '42', 'label': 'Спорт', 'category': 'genre'}}
        with patch('manga_native_sources.PublicHttp', return_value=Http()), patch('suwayomi_bridge.Client') as bridge:
            rows = search_source(SOURCE, 'Blue Lock')
            result = fetch(job, {'page': 1})
        bridge.assert_not_called()
        self.assertEqual([row['url'] for row in rows], [TITLE])
        self.assertEqual(result['rows'][0]['id'], rows[0]['id'])
        self.assertEqual(result['rows'][0]['genres'], ['Спорт'])
        self.assertEqual(result['details'][0]['url'], TITLE)

    def test_native_source_is_listed_during_bridge_outage(self):
        with patch('suwayomi_bridge.configured', return_value=True), patch('suwayomi_bridge.sources', side_effect=SourceError('offline')):
            sources = installed_sources()
        self.assertEqual([source['baseUrl'] for source in sources if source['id'] == SOURCE_ID], [ROOT])

    def test_reader_keeps_paginated_fractional_chapter_and_downloads_through_same_adapter(self):
        http = Http()
        title = inspect(TITLE, http)
        self.assertEqual([(item['season'], item['number']) for item in title['episodes']], [(1, 1), (2, 1.5)])
        self.assertEqual(inspect(SECOND, http)['pages'], [PAGE])
        with TemporaryDirectory() as directory:
            path = download_chapter(SECOND, directory, http)
            with ZipFile(path) as archive:
                self.assertEqual(archive.read('0001.png'), PNG)

    def test_an_invalid_image_does_not_produce_a_partial_chapter(self):
        raw = f'<img class="reader-image" src="{PAGE}"><img class="reader-image" src="file:///private.png">'
        with patch.object(Http, 'document', return_value=(raw, SECOND, {})):
            with self.assertRaises(SourceError):
                inspect(SECOND, Http())

    def test_stored_chapter_cannot_redirect_to_a_different_work(self):
        class Bridge:
            def get(self, *_args, **_options):
                return [{'index': 2, 'url': '/manga/another/glava-1/'}]

        with self.assertRaises(SourceError):
            native_reader_url(Bridge(), {'url': '/manga/bluelock/'}, SOURCE, 17, 2)

    def test_recorded_link_opens_without_bridge_configuration(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {
                'DATA_DIR': directory, 'PUBLIC_URL': 'https://vault.example', 'SUWAYOMI_URL': '',
        }), patch('suwayomi_bridge.Client', side_effect=AssertionError('Bridge must stay offline')):
            record_reader_url(75, 2, manga_mangashi, SECOND)
            legacy = 'https://vault.example' + PREFIX + 'm/75/c/2'
            with patch('manga_sources.PublicHttp', return_value=Http()):
                self.assertEqual(inspect(legacy)['pages'], [PAGE])
            with patch('suwayomi_bridge.native_page_image', return_value=(PNG, 'image/png')) as image:
                self.assertEqual(page_image(legacy + '/p/0'), (PNG, 'image/png'))
                image.assert_called_once_with(SECOND, 0)

    def test_mangahub_relative_saved_links_retain_the_host_and_chapter(self):
        self.assertEqual(ONE_MANGA_CO.saved_chapter_url('/test/chapter-3.5', 'test', ONE_MANGA_CO.ROOT),
                         'https://1manga.co/chapter/test/chapter-3.5')
        self.assertEqual(ONE_MANGA_CO.saved_chapter_url('https://outside.example/test/chapter-3.5', 'test', ONE_MANGA_CO.ROOT), '')

    def test_mangahub_accepts_the_guest_cookie_on_the_readers_redirect(self):
        reader = MangaHub('1', 'MangaHub', 'mangahub.io', 'm01')
        route = '/chapter/example/chapter-1'
        with patch.object(reader, 'request') as request:
            reply = request.return_value.__enter__.return_value
            reply.status_code = 302
            reply.cookies = {'mhub_access': 'sample-guest-cookie'}
            previous = reader.guest
            reader.refresh_guest(None, route)
        request.assert_called_once_with(None, route, previous, refresh=True, referer='https://mangahub.io/manga/example')
        self.assertTrue(reader.page_guest_ready)
        self.assertEqual(reader.guest, 'sample-guest-cookie')

    def test_onemanga_follows_only_its_published_redirect_for_the_same_chapter(self):
        reader = MangaHub('1', '1Manga.co', '1manga.co', 'mn03')
        mirror = OneManga('2', 'OneManga.info', 'onemanga.info', 'mn02', reader)

        def response(status, location=''):
            context = MagicMock()
            context.__enter__.return_value.status_code = status
            context.__enter__.return_value.headers = {'Location': location}
            return context

        number = Decimal(1)
        path = '/chapter/example_12/chapter-1'
        with patch.object(MangaHub, 'pages', side_effect=SourceError('missing')), patch.object(mirror, 'request',
                return_value=response(301, 'https://1manga.co/chapter/example/chapter-1')):
            with patch.object(reader, 'request', side_effect=[
                    response(301, 'https://1manga.co/chapter/example_4/chapter-1'), response(200),
            ]), patch.object(reader, 'pages', return_value=[PAGE]) as pages:
                self.assertEqual(mirror.pages(None, 'example_12', number, path), [PAGE])
                pages.assert_called_once_with(None, 'example_4', number, '/chapter/example_4/chapter-1')
        with patch.object(MangaHub, 'pages', side_effect=SourceError('missing')), patch.object(mirror, 'request',
                return_value=response(301, 'https://1manga.co/chapter/different/chapter-1')):
            with self.assertRaisesRegex(SourceError, 'другую главу'):
                mirror.pages(None, 'example_12', number, path)
