import json
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from manga_keyoapp import SOURCES
from manga_native_sources import saved_reader_url
from source_parser import SourceAccessError, SourceError


V1 = next(s for s in SOURCES if s.NAME == 'Kewn Scans')
V2 = next(s for s in SOURCES if s.NAME == 'Asmodeus Scans')
REDESIGN = next(s for s in SOURCES if s.NAME == 'RitharScans')


def document(value):
    return BeautifulSoup(value, 'html.parser')


class KeyoappTests(TestCase):
    def test_original_catalogue_and_chapters_keep_public_content(self):
        cards = """
            <div id="searched_series_page">
              <button tags='["Science Fiction"]'>
                <a href="/series/story" title="Example Story">Example Story</a>
              </button>
              <button data-type="novel" tags='["Science Fiction"]'>
                <a href="/series/another" title="Example Novel">Another</a>
              </button>
            </div>
            <script>initializeDropdownMenu({type: "genre",
              items: [{displayName: "Science Fiction", value: "Science Fiction"}]});</script>
        """
        metadata = """
            <div class="grid"><h1>Example Story</h1></div>
            <div id="chapters">
              <a href="/chapter/paid"><span class="text-sm">Chapter 3</span><img alt="Coin"></a>
              <a href="/chapter/soon"><span class="text-sm">Chapter 4</span><span>Upcoming</span></a>
              <div><a href="/chapter/free"><span class="text-sm">Vol. 2 Chapter 2.5</span></a></div>
            </div>
        """
        http = Mock()
        http.document.side_effect = [
            (cards, V1.ROOT + '/series/?genre=Science+Fiction', {}),
            (cards, V1.ROOT + '/series/', {}),
            (metadata, V1.ROOT + '/series/story', {}),
        ]
        rows, more = V1.catalogue(http, tag='Science Fiction')
        self.assertFalse(more)
        self.assertEqual([row['title'] for row in rows], ['Example Story'])
        self.assertEqual(V1.vocabulary(http)[0]['sourceId'], 'Science Fiction')
        chapter, = V1.inspect(rows[0]['url'], http)['episodes']
        self.assertEqual((chapter['season'], chapter['number'], chapter['url']), (2, 2.5, V1.ROOT + '/chapter/free'))

    def test_v2_pagination_and_saved_url_validate_the_exact_open_chapter(self):
        series = V2.ROOT + '/public-story'
        chapter = V2.ROOT + '/open-chapter'
        html = '<a class="group" href="/public-story"><h2>Public Story</h2></a>'
        rows = '<a class="chapter-row" href="/open-chapter" data-ch-label="Chapter 1.5"></a>'
        detail = '<h1>Public Story</h1><div data-series-uid="123"></div>'
        http = Mock()

        def response(url, **options):
            parts = urlsplit(url)
            args = parse_qs(parts.query)
            if args.get('_ajax') == ['search']:
                self.assertEqual(args.get('offset'), ['20'])
                return json.dumps({'html': html, 'has_more': True}), url, {}
            if args.get('_chapters_html') == ['1']:
                self.assertEqual(args.get('series_slug'), ['public-story'])
                return json.dumps({'rows_html': rows}), url, {}
            if url == series:
                return detail, url, {}
            self.assertEqual(url, chapter)
            return """
              <div id="sidebar-ch-list" data-series-slug="public-story"></div>
              <div id="strip-reader"><img class="reader-page" src="/a.jpg"></div>
            """, url, {}

        http.document.side_effect = response
        cards, more = V2.catalogue(http, page=2, query='Public Story')
        self.assertTrue(more)
        self.assertEqual([row['url'] for row in cards], [series])
        self.assertEqual(V2.inspect(chapter, http)['pages'], [V2.ROOT + '/a.jpg'])
        bridge = Mock()
        bridge.get.return_value = [{'index': 5, 'url': '/open-chapter'}]
        with patch('manga_keyoapp.PublicHttp', return_value=http):
            self.assertEqual(saved_reader_url(V2, bridge, {}, series, 2, 5), chapter)
            bridge.get.return_value = [{'index': 5, 'url': '/other-chapter'}]
            with self.assertRaises(SourceError):
                saved_reader_url(V2, bridge, {}, series, 2, 5)

    def test_original_vocabulary_uses_public_card_tags_when_options_are_generated(self):
        html = """
          <div id="searched_series_page">
            <button tags='["Action", "action", "Adventure"]'></button>
            <button data-type="novel" tags='["Novel only"]'></button>
          </div>
          <script>initializeDropdownMenu({type: "genre", items: loadedGenres});</script>
        """
        http = Mock()
        http.document.return_value = (html, V1.ROOT + '/series/', {})
        terms = V1.vocabulary(http)
        self.assertEqual([(term['sourceId'], term['label']) for term in terms],
                         [('Action', 'Action'), ('Adventure', 'Adventure')])

    def test_public_page_manifests_are_parsed_without_executing_scripts(self):
        reader = document("""
            <script>const realUrl = `https://cdn${number}.keyoapp.com/uploads/${uid}`;</script>
            <div id="pages"><img uid="volume/a.webp"><img uid="b.webp"></div>
        """)
        self.assertEqual(V1.pages(reader, V1.ROOT + '/chapter/chapter'), [
            'https://cdn.keyoapp.com/uploads/volume/a.webp', 'https://cdn.keyoapp.com/uploads/b.webp',
        ])
        reader.select_one('img')['uid'] = '../private'
        with self.assertRaises(SourceError):
            V1.pages(reader, V1.ROOT + '/chapter/chapter')
        alpine = document('<div></div>')
        paths = json.dumps([{'path': 'https://images.example/a.webp'}, {'path': 'https://images.example/b.webp'}])
        alpine.div['x-data'] = "immersiveReader(JSON.parse('" + json.dumps(paths)[1:-1] + "'))"
        self.assertEqual(REDESIGN.pages(alpine, REDESIGN.ROOT + '/read/chapter'), [
            'https://images.example/a.webp', 'https://images.example/b.webp',
        ])
        del alpine.div['x-data']
        with self.assertRaises(SourceAccessError):
            REDESIGN.pages(alpine, REDESIGN.ROOT + '/read/chapter')
