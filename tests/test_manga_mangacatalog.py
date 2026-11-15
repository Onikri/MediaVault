from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from zipfile import ZipFile
from bs4 import BeautifulSoup

from manga_download import download_chapter
from manga_mangacatalog import SOURCES
import manga_native_sources as native
from manga_sources import inspect
from source_parser import SourceError


ADAPTER = next(source for source in SOURCES if source.SOURCE_ID == '1061544757733451419')
TITLE = ADAPTER.ROOT + '/manga/one-piece/'
CHAPTER = ADAPTER.ROOT + '/chapter/one-piece-chapter-5.5/'
DETAILS = '''
<div class="container"><h1>One Piece</h1></div>
<div class="flex"><img src="/cover.png"></div>
<div class="w-full"><div class="bg-bg-secondary">
  <div class="px-6"><div class="flex-col">Description A voyage.</div></div>
  <div class="grid"><div class="col-span-4">
    <a href="/chapter/one-piece-chapter-5.5/">Chapter 5.5</a><div class="text-xs">Prologue</div>
  </div></div>
  <div class="grid"><div class="col-span-4">
    <a href="/chapter/one-piece-party-chapter-5.5/">Other series</a>
  </div></div>
</div></div>
'''


class Http:
    def document(self, url, **options):
        if url == TITLE:
            return DETAILS, url, {}
        if url == CHAPTER:
            return '''<img class="js-page" src="/page1.jpg">
                 <img class="js-page" data-src="/page2.jpg" src="/placeholder.gif">
                 <noscript><img class="js-page" src="/page2.jpg"></noscript>''', url, {}
        raise AssertionError(url)

    def download(self, url, target, *, headers, maximum):
        assert headers['Referer'] == CHAPTER
        target.write_bytes(b'\xff\xd8\xfffixture')

    def close(self):
        pass


class MangaCatalogMigration(TestCase):
    def test_one_shot_and_inline_loading_pixel_keep_the_actual_pages(self):
        other = next(source for source in SOURCES if source.SOURCE_ID == '7952360835727640966')
        self.assertEqual(other.work_path('/chapter/meng-wu-and-chu-zi-one-shot/'), '/manga/meng-wu-and-chu-zi-one-shot')
        doc = BeautifulSoup('''
            <img class="js-page" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">
            <img class="js-page" data-src="/pages/1.jpg">
        ''', 'html.parser')
        self.assertEqual(ADAPTER.pages(doc, CHAPTER), [ADAPTER.ROOT + '/pages/1.jpg'])

    def test_catalogue_search_preserves_edition_and_aliases_without_http(self):
        rows, more = ADAPTER.catalogue(None, query='one piece digital colored comics')
        row, = rows
        self.assertEqual(row['title'], 'Colored')
        self.assertIn('one piece digital colored comics', row['aliases'])
        self.assertFalse(more)
        self.assertEqual(ADAPTER.catalogue(None, page=2), ([], False))
        self.assertEqual(len(SOURCES), 13)

    def test_reader_archive_and_saved_chapter_keep_the_work(self):
        with patch.dict(native.ADAPTERS, {ADAPTER.SOURCE_ID: ADAPTER}), \
                patch.dict(native.HOSTS, {ADAPTER.host: ADAPTER}), \
                patch('manga_mangacatalog.PublicHttp', return_value=Http()):
            title = inspect(TITLE, Http())
            chapter, = title['episodes']
            self.assertEqual((title['description'], chapter['number'], chapter['url']), ('A voyage.', 5.5, CHAPTER))
            bridge = Mock()
            bridge.get.return_value = [{'index': 8, 'url': CHAPTER}]
            self.assertEqual(native.saved_reader_url(ADAPTER, bridge, {}, TITLE, 17, 8), CHAPTER)
            bridge.get.return_value = [{'index': 8, 'url': '/chapter/one-piece-party-chapter-5.5/'}]
            with self.assertRaises(SourceError):
                native.saved_reader_url(ADAPTER, bridge, {}, TITLE, 17, 8)
            with TemporaryDirectory() as directory:
                with ZipFile(download_chapter(CHAPTER, directory, Http())) as chapter_file:
                    self.assertEqual(chapter_file.namelist(), ['0001.jpg', '0002.jpg'])
