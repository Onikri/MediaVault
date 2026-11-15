import base64
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch
from zipfile import ZipFile

from catalogue_sources import base_sources, fetch
from manga_discovery import search_source
from manga_download import download_chapter
import manga_native_sources as native
from manga_sources import inspect
from manga_themesia import ACTIVE_SOURCES
from source_parser import SourceError
from suwayomi_bridge import native_reader_url


ADAPTER = next(adapter for adapter in ACTIVE_SOURCES if adapter.NAME == 'Lagoon Scans')
TITLE = ADAPTER.ROOT + '/manga/example/'
CHAPTER = ADAPTER.ROOT + '/example-chapter-15-5/'
SOURCE = {'id': ADAPTER.SOURCE_ID, 'baseUrl': ADAPTER.ROOT, 'lang': 'en', 'name': ADAPTER.NAME}
CATALOGUE = '''
<div class="listupd"><div class="bs"><div class="bsx">
  <a title="Example Story" href="/manga/example/"><img data-lazy-src="/cover.jpg"></a>
</div></div></div>
<div class="pagination"><a class="next" href="?page=2"></a></div>
<ul class="genrez"><li><input type="checkbox" value="42"><label>Space Travel</label></li></ul>
'''
DETAILS = '''
<div class="bigcontent">
  <h1 class="entry-title">Example Story</h1>
  <div class="alternative">Alt Name; Второе имя</div>
  <div class="mgen"><a>Space Travel</a></div>
  <div class="desc">A synopsis.</div>
</div>
<div class="listinfo"><time itemprop="dateModified" datetime="2026-11-09"></time></div>
<div id="chapterlist"><ul>
  <li><a href="/example-chapter-15-5/"><span class="chapternum">Vol. 2 Chapter 15.5</span></a></li>
  <li><a href="/example-chapter-15-5">Duplicate</a></li>
</ul></div>
'''
READER = '<h1 class="entry-title">Chapter 15.5</h1><div class="allc"><a href="/manga/example/">Example Story</a></div>'


class Http:
    def document(self, url, **options):
        if url == TITLE:
            return DETAILS, url, {}
        if url == CHAPTER:
            script = base64.b64encode(b'ts_reader.run({"sources":[{"images":["/001.jpg","/002.png"]}]})').decode()
            return READER + f'<script src="data:text/javascript;base64,{script}"></script>', url, {}
        if urlsplit(url).path == '/manga/':
            return CATALOGUE, url, {}
        raise AssertionError(url)

    def download(self, url, target, *, headers, maximum):
        assert headers['Referer'] == CHAPTER
        target.write_bytes(b'\xff\xd8\xfffixture' if url.endswith('.jpg') else b'\x89PNG\r\n\x1a\nfixture')

    def close(self):
        pass


class MangaThemesiaMigration(unittest.TestCase):
    def test_search_catalogue_filter_and_download_use_the_exact_source(self):
        http = Mock(wraps=Http(), deadline=None)
        with patch('manga_native_sources.PublicHttp', return_value=http), patch('suwayomi_bridge.Client') as bridge:
            hit, = search_source(SOURCE, 'Example Story')
            self.assertEqual(parse_qs(urlsplit(http.document.call_args.args[0]).query), {'title': ['Example Story'], 'page': ['1']})
            job = next(job for job in base_sources([SOURCE]) if job.get('source', {}).get('id') == ADAPTER.SOURCE_ID)
            term, = ADAPTER.vocabulary(http)
            result = fetch({**job, 'term': term}, {'page': 2})
            self.assertEqual(parse_qs(urlsplit(http.document.call_args.args[0]).query), {'genre[]': ['42'], 'page': ['2']})
            self.assertEqual(result['next'], {'page': 3})
            details = fetch(result['details'][0], {'page': 1})['rows'][0]
        bridge.assert_not_called()
        self.assertEqual((details['id'], details['genres'], details['description']), (hit['id'], ['Space Travel'], 'A synopsis.'))
        chapter, = inspect(TITLE, Http())['episodes']
        self.assertEqual((chapter['number'], chapter['season'], chapter['publishedAt']), (15.5, 2, '2026-11-09'))
        with TemporaryDirectory() as directory:
            with ZipFile(download_chapter(CHAPTER, directory, Http())) as archive:
                self.assertEqual(archive.namelist(), ['0001.jpg', '0002.png'])
                self.assertIsNone(archive.testzip())

    def test_saved_link_requires_the_actual_series_parent_and_survives_bridge_outage(self):
        bridge = Mock()
        bridge.get.return_value = [{'index': 8, 'url': '/example-chapter-15-5/'}]
        with TemporaryDirectory() as directory, patch('manga_themesia.PublicHttp', return_value=Http()), \
                patch.object(native, 'legacy_links_path', return_value=Path(directory) / 'links.sqlite'):
            self.assertEqual(native_reader_url(bridge, {'url': '/manga/example/'}, SOURCE, 15, 8), CHAPTER)
            native.record_reader_url(15, 8, ADAPTER, CHAPTER)
            self.assertEqual(native.recorded_reader_url(15, 8), CHAPTER)
            with self.assertRaises(SourceError):
                native_reader_url(bridge, {'url': '/manga/another/'}, SOURCE, 15, 8)
