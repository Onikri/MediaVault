from unittest import TestCase
from unittest.mock import Mock
from urllib.parse import urlsplit

from manga_native_sources import saved_reader_url
from manga_source_urls import split_reader_url
from manga_yii import SOURCES
from source_parser import SourceError


MANGA = next(source for source in SOURCES if source.mode == 'toongod')
KOREAN = next(source for source in SOURCES if source.LANGUAGE == 'ko')
ENGLISH = next(source for source in SOURCES if source.ROOT == KOREAN.ROOT and source.LANGUAGE == 'en')


class YiiTests(TestCase):
    def test_manga_layout_preserves_card_chapter_dates_and_page_order(self):
        http = Mock(deadline=None)
        title = MANGA.ROOT + '/webtoon/story/'
        chapter = title + 'chapter-1.5/'
        catalog = '''<div class="list"><div class="list-item"><div class="item-title">
          <a href="/webtoon/story/">Test story</a></div></div></div>
          <ul id="pagination"><li class="next"><a href="/page/2/">Next</a></li></ul>'''
        details = '''<h1 class="main-info-title">Test story</h1>
          <ul class="main-info-list"><li><h5>Genres:</h5><p><a href="/genre/action/">Action</a></p></li>
          <li><h5>Alternative:</h5><p>Other name</p></li></ul>
          <ul class="chapter-list"><li><a href="/webtoon/story/chapter-1.5/">
          <span class="chapter-name">Chapter 1.5</span></a><span class="ct-update">12 Oct 26</span></li></ul>'''
        reader = '''<h1>Chapter 1.5</h1><div class="reading-content">
          <img src="/001.png"><img data-src="/002.png" src="/placeholder.png"></div>'''

        def fetch(url, **_options):
            path = urlsplit(url).path
            return {urlsplit(title).path: details, urlsplit(chapter).path: reader}.get(path, catalog), url, {}

        http.document.side_effect = fetch
        cards, more = MANGA.catalogue(http, tag='action')
        self.assertEqual(http.document.call_args.args[0], MANGA.ROOT + '/genre/action/1/')
        self.assertEqual(([row['url'] for row in cards], more), ([title], True))
        data = MANGA.inspect(title, http)
        self.assertEqual(data['genres'], ['Action'])
        self.assertIn('Other name', data['aliases'])
        row, = data['episodes']
        self.assertEqual((row['url'], row['number'], row['publishedAt']), (chapter, 1.5, '2026-10-12'))
        self.assertEqual(MANGA.inspect(chapter, http)['pages'], [MANGA.ROOT + '/001.png', MANGA.ROOT + '/002.png'])

    def test_madara_keeps_language_scope_and_saved_chapter_on_selected_title(self):
        http = Mock(deadline=None)
        fixture = '''<div class="page-item"><h3><a href="/webtoon/story">Story</a></h3></div>
          <div class="page-item"><h3><a href="/webtoon/story-raw">Story RAW</a></h3></div>'''
        http.document.side_effect = lambda url, **_options: (fixture, url, {})
        english, _ = ENGLISH.catalogue(http, query="It's a story")
        self.assertIn('It%E2%80%99s+a+story', http.document.call_args.args[0])
        korean, _ = KOREAN.catalogue(http, query='Story')
        self.assertEqual(split_reader_url(english[0]['url']), (ENGLISH.SOURCE_ID, ENGLISH.ROOT + '/webtoon/story'))
        self.assertEqual(split_reader_url(korean[0]['url']), (KOREAN.SOURCE_ID, KOREAN.ROOT + '/webtoon/story-raw'))
        with self.assertRaises(SourceError):
            ENGLISH.inspect(korean[0]['url'], http)

        client = Mock()
        client.get.return_value = [{'index': 1, 'url': 'chapter-10'}]
        saved = saved_reader_url(KOREAN, client, {'baseUrl': KOREAN.ROOT}, '/webtoon/story-raw', 2, 1)
        self.assertEqual(split_reader_url(saved), (KOREAN.SOURCE_ID, KOREAN.ROOT + '/webtoon/story-raw/chapter-10'))
