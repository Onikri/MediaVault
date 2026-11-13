"""Offline HManga adapter regression tests with neutral generated HTML."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))

from source_parser import SourceError
import manga_hmanga as hmanga
from manga_sources import site_for, inspect
import manga_discovery

WORK = hmanga.ROOT + '/manga/garden-world/'
CHAPTER = WORK + 'chapter-1.5/'
SEARCH = hmanga.ROOT + '/?' + urlencode({'post_type': 'wp-manga', 's': 'Garden World'})


class FakeHttp:
    def __init__(self, docs):
        self.docs = docs
        self.calls = []

    def document(self, url, **kwargs):
        self.calls.append(url)
        if url not in self.docs:
            raise AssertionError('Unexpected URL ' + url)
        return self.docs[url], url, {}


CARD = '''<div class="c-tabs-item__content"><div class="post-title">
<h3><a href="/manga/garden-world/">Мир садов — Garden World [777]</a></h3></div>
<img data-src="https://cdn.example.org/cover.webp"></div>
<div class="c-tabs-item__content"><h3 class="post-title"><a href="https://bad.invalid/manga/evil/">Bad</a></h3></div>
<div class="c-tabs-item__content"><h3 class="post-title"><a href="/manga/garden-world/chapter-3/">Chapter</a></h3></div>'''
TITLE = '''<html><h1>Мир садов — Garden World [777]</h1>
<div class="post-content_item"><div class="summary-heading">Type</div><div class="summary-content">Manhwa</div></div>
<div class="post-content_item"><div class="summary-heading">Alternative</div><div class="summary-content">Garden World, Садовый мир</div></div>
<div class="post-content_item"><div class="summary-heading">Tag(s)</div><div class="summary-content"><a>Фэнтези</a><a>Романтика</a></div></div>
<div class="listing-chapters_wrap"><ul><li class="wp-manga-chapter"><a href="/manga/garden-world/chapter-1.5/">Глава 1.5</a></li>
<li class="wp-manga-chapter"><a href="/manga/garden-world/chapter-2/">Глава 2</a></li></ul></div>
<a href="/manga/unrelated/chapter-3/">Глава 3</a></html>'''
READER = '''<html><h1>Мир садов - Chapter 1.5</h1><div class="reading-content">
<div class="page-break"><img data-src="https://kagis.cc/images/001.webp"></div>
<div class="page-break"><img src="https://kagis.cc/images/002.jpg"></div>
<img src="javascript:alert(1)"><img src="https://kagis.cc/images/002.jpg"></div>
<div class="unrelated"><img src="https://kagis.cc/images/third.jpg"></div></html>'''


class HMangaTests(unittest.TestCase):
    def test_site_allowlist_and_search(self):
        self.assertEqual(site_for(WORK).id, 'hmanga')
        self.assertEqual(site_for('https://hmanga.su/manga/garden-world/').id, 'hmanga')
        http = FakeHttp({SEARCH: CARD})
        found = hmanga.search('Garden World', http)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['url'], WORK)
        self.assertIn('Garden World', found[0]['aliases'])
        self.assertTrue(found[0]['adult'])
        self.assertEqual(http.calls, [SEARCH])

    def test_reader_and_metadata_contract(self):
        http = FakeHttp({WORK: TITLE, CHAPTER: READER})
        meta = inspect(WORK, http)
        self.assertEqual(meta['format'], 'manhwa')
        self.assertEqual(meta['readingMode'], 'scroll')
        self.assertEqual(meta['tags'], ['Фэнтези', 'Романтика'])
        self.assertEqual([c['number'] for c in meta['episodes']], [1.5, 2])
        self.assertFalse(meta['truncated'])
        self.assertEqual(meta['pages'], [])
        self.assertEqual(http.calls, [WORK], 'listing should not download chapter readers')
        chapter = inspect(CHAPTER, http)
        self.assertEqual(chapter['episodes'][0]['number'], 1.5)
        self.assertEqual(chapter['pages'], [
            'https://kagis.cc/images/001.webp', 'https://kagis.cc/images/002.jpg'])

    def test_partial_list_and_invalid_pages(self):
        partial = '''<h1>Garden World</h1><a href="/manga/garden-world/chapter-1/">Read First</a>
        <a href="/manga/garden-world/chapter-10/">Read Last</a>'''
        meta = hmanga.inspect(WORK, FakeHttp({WORK: partial}))
        self.assertTrue(meta['truncated'])
        self.assertEqual(len(meta['episodes']), 2)
        with self.assertRaises(SourceError):
            hmanga.inspect(CHAPTER, FakeHttp({CHAPTER: '<h1>Chapter 1.5</h1><div class="reading-content"><img src="/icon.svg"></div>'}))
        self.assertFalse(hmanga._work_url('https://bad.invalid/manga/garden-world/', WORK))
        self.assertFalse(hmanga._work_url('/manga/garden-world/chapter-1/', WORK))

    def test_global_discovery_uses_native_adapter(self):
        with patch.object(manga_discovery.bridge, 'sources', return_value=[]), \
             patch('manga_source_health.states', return_value={}):
            names = [x['name'] for x in manga_discovery.source_list('ru', 'HManga')['sources']]
        self.assertEqual(names, ['HManga'])
        item = hmanga.parse_search(CARD)[0]
        with patch('manga_hmanga.search', return_value=[item]) as run:
            rows = manga_discovery.search_source(hmanga.SOURCE, 'Garden World')
        self.assertEqual(rows, [item])
        run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
