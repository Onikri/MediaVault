import unittest
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from zipfile import ZipFile

from catalogue_sources import base_sources, fetch
from manga_discovery import search_source
from manga_download import download_chapter
import manga_madara as madara
from manga_sources import inspect
from source_parser import PublicHttp, SourceAccessError, SourceError
from suwayomi_bridge import native_reader_url


ACTIVE = next(s for s in madara.ACTIVE_SOURCES if s.NAME == 'LHTranslation')
PAGED = next(s for s in madara.SOURCES if s.NAME == 'Lovesjane Scans')
NO_AJAX = next(s for s in madara.SOURCES if s.NAME == 'AllPornComic')
ADMIN = next(s for s in madara.SOURCES if s.NAME == 'Mangaforfree.com')
SOURCE = {'id': ACTIVE.SOURCE_ID, 'name': ACTIVE.NAME, 'lang': ACTIVE.LANGUAGE, 'baseUrl': ACTIVE.ROOT}
TITLE = ACTIVE.ROOT + '/manga/example/'
CHAPTER = TITLE + 'chapter-15-5/'
JPG = b'\xff\xd8\xff' + b'fixture'
GIF = b'GIF89a' + b'fixture'
CARDS = '<div class="page-item-detail"><div class="post-title"><a href="/manga/example/">Example Story</a></div></div>'
DETAILS = """
<div class="post-title"><h1>Example Story</h1></div>
<div class="genres-content"><a>Science Fiction</a></div>
<div class="tags-content"><a>Time Travel</a></div>
<div class="summary_image"><img data-lazy-src="/cover.jpg"></div>
<div class="description-summary"><div class="summary__content"><p>A synopsis.</p></div></div>
<div id="manga-chapters-holder" data-id="45"></div>
"""
CHAPTER_ENTRY = """
<li class="wp-manga-chapter">
  <a href="/manga/example/chapter-15-5/">Vol. 2 Chapter 15.5</a>
  <span class="chapter-release-date">November 9, 2026</span>
</li>
"""


class Http:
    def document(self, url, **options):
        data = options.get('data')
        if data and data.get('action') == 'madara_load_more':
            return CARDS, url, {}
        if url == ACTIVE.ROOT + '/?p=45':
            return DETAILS, TITLE, {}
        if url == ACTIVE.ROOT + '/manga/':
            return '<div class="genres"><a href="/manga-genre/scifi/">Science Fiction <span class="count">(12)</span></a></div>', url, {}
        if url == TITLE:
            return DETAILS, url, {}
        if url == TITLE + 'ajax/chapters/' and data == {}:
            return CHAPTER_ENTRY, url, {}
        if url == CHAPTER:
            return '<div id="single-pager"></div>', url, {}
        if url == CHAPTER + '?style=list':
            return '''
            <div class="reading-content">
              <div class="page-break"><img src="/placeholder.jpg" data-lzl-src="http://lhtranslation.net/wp-content/uploads/page-1.jpg"></div>
              <div class="page-break"><img srcset="/low.gif 1x, /page-2.gif 2x"></div>
            </div>''', url, {}
        raise AssertionError((url, options))

    def download(self, url, target, *, headers, maximum):
        assert headers['Referer'] == CHAPTER + '?style=list'
        target.write_bytes(JPG if url.endswith('/page-1.jpg') else GIF)

    def close(self):
        pass


class MadaraMigration(unittest.TestCase):
    def test_active_profile_search_catalogue_reader_and_cbz_share_identity(self):
        with patch('manga_native_sources.PublicHttp', return_value=Http()), patch('suwayomi_bridge.Client') as bridge:
            hit, = search_source(SOURCE, 'Example Story')
            job = next(job for job in base_sources([SOURCE]) if job.get('source', {}).get('id') == ACTIVE.SOURCE_ID)
            indexed = fetch(job, {'page': 1})
            details = fetch(indexed['details'][0], {'page': 1})['rows'][0]
        bridge.assert_not_called()
        self.assertEqual(hit['id'], details['id'])
        self.assertEqual(details['genres'], ['Science Fiction'])
        self.assertEqual(details['tags'], ['Time Travel'])
        self.assertEqual(details['description'], 'A synopsis.')
        title = inspect(TITLE, Http())
        chapter, = title['episodes']
        self.assertEqual((chapter['season'], chapter['number'], chapter['publishedAt']), (2, 15.5, '2026-11-09'))
        with TemporaryDirectory() as temp:
            output = download_chapter(CHAPTER, temp, Http())
            with ZipFile(output) as archive:
                self.assertEqual(archive.namelist(), ['0001.jpg', '0002.gif'])
                self.assertIsNone(archive.testzip())

    def test_legacy_numeric_post_and_relative_chapter_keep_canonical_work(self):
        bridge = Mock()
        bridge.get.return_value = [{'index': 8, 'url': 'chapter-15-5'}]
        with patch('manga_madara.PublicHttp', return_value=Http()):
            self.assertEqual(native_reader_url(bridge, {'url': '45'}, SOURCE, 11), TITLE)
            self.assertEqual(native_reader_url(bridge, {'url': '45'}, SOURCE, 11, 8), CHAPTER)
            bridge.get.return_value = [{'index': 8, 'url': '/manga/other/chapter-15-5/'}]
            with self.assertRaises(SourceError):
                native_reader_url(bridge, {'url': '45'}, SOURCE, 11, 8)

    def test_legacy_filter_with_count_reuses_the_stable_genre_and_cursor(self):
        job = {'type': 'bridge', 'source': SOURCE, 'domain': ACTIVE.host,
               'term': {'label': 'Science Fiction (12)', 'sourceId': {'position': 4}, 'category': 'genre'}}
        http = Mock(wraps=Http())
        with patch('manga_native_sources.PublicHttp', return_value=http):
            result = fetch(job, {'page': 3})
        self.assertEqual(result['rows'][0]['genres'], ['Science Fiction'])
        form = http.document.call_args.kwargs['data']
        self.assertEqual((form['page'], form['vars[tax_query][0][terms][0]']), ('2', 'scifi'))

    def test_chapter_pagination_stops_on_a_repeated_page(self):
        root = PAGED.ROOT + '/manga/example/'
        http = Mock()
        http.document.side_effect = [
            (DETAILS, root, {}),
            (CHAPTER_ENTRY, root + 'ajax/chapters/?t=1', {}),
            (CHAPTER_ENTRY, root + 'ajax/chapters/?t=2', {}),
        ]
        result = PAGED.inspect(root, http)
        self.assertEqual([e['number'] for e in result['episodes']], [15.5])
        self.assertFalse(result['truncated'])
        self.assertEqual(http.document.call_count, 3)

    def test_source_specific_date_does_not_swap_day_and_month(self):
        profile = next(s for s in madara.SOURCES if s.NAME == 'Petrotechsociety')
        path = profile.ROOT + '/manga/example/'
        http = Mock()
        http.document.return_value = (DETAILS + CHAPTER_ENTRY.replace('November 9, 2026', '02/11/2026'), path, {})
        self.assertEqual(profile.inspect(path, http)['episodes'][0]['publishedAt'], '2026-11-02')

    def test_html_catalogue_uses_the_source_specific_section_and_pagination(self):
        http = Mock()
        root = NO_AJAX.ROOT + '/porncomic/page/2/'
        html = CARDS.replace('/manga/', '/porncomic/') + '<a class="nextpostslink" href="/porncomic/page/3/">Next</a>'
        http.document.return_value = (html, root, {})
        rows, more = NO_AJAX.catalogue(http, page=2)
        self.assertTrue(more)
        self.assertEqual(rows[0]['url'], NO_AJAX.ROOT + '/porncomic/example/')
        self.assertIn(root, http.document.call_args.args[0])
        self.assertNotIn('method', http.document.call_args.kwargs)

    def test_transport_only_allows_pinned_read_actions(self):
        session = Mock()
        session.request.return_value.status_code = 200
        http = PublicHttp(session=session, validate=lambda url: url)
        args = {'method': 'POST', 'action': 'madara-read', 'headers': {'Referer': TITLE}}
        data = ACTIVE.catalogue_data(3, 'a & b', 'popular', 'science-fiction')
        http._open(ACTIVE.ROOT + madara.FORM, data=data, **args)
        self.assertEqual(session.request.call_args.kwargs['headers']['X-Requested-With'], 'XMLHttpRequest')
        self.assertFalse(madara.ajax_form('https://unknown.example' + madara.FORM, data, TITLE))
        self.assertFalse(madara.ajax_form(ACTIVE.ROOT + madara.FORM, {**data, 'action': 'delete_post'}, TITLE))
        self.assertFalse(madara.ajax_form(ACTIVE.ROOT + '/manga/%2e%2e/ajax/chapters/', {}, ACTIVE.ROOT + '/manga/%2e%2e/'))
        self.assertTrue(madara.ajax_form(ADMIN.ROOT + madara.FORM, {'action': 'manga_get_chapters', 'manga': '45'}, ADMIN.ROOT + '/manga/example/'))
        self.assertFalse(madara.ajax_form(ADMIN.ROOT + madara.FORM, {'action': 'manga_get_chapters', 'manga': '45'}, ADMIN.ROOT))
        session.request.return_value.status_code = 307
        session.request.return_value.headers = {'Location': '/wp-admin/edit.php'}
        with self.assertRaises(SourceError):
            http._open(ACTIVE.ROOT + madara.FORM, data=data, **args)
        self.assertEqual(session.request.call_count, 2)

    def test_locked_chapter_stops_before_decoding_public_reader_data(self):
        http = Mock()
        http.document.return_value = (
            '<div class="chapter-locked"></div><script id="chapter-protector-data">bad</script>',
            CHAPTER, {},
        )
        with self.assertRaises(SourceAccessError):
            ACTIVE.inspect(CHAPTER, http)

    def test_public_madara_reader_payload_preserves_pages_in_order(self):
        raw = """
            <script id="chapter-protector-data">let wpmangaprotectornonce='fixture';
            let chapter_data='{"s":"0001020304050607","ct":"WhoklPGLbmAnSUrVSRHYIDO3oeUHdgBuKi2wMuviLQzZar9KAmDKwiuZ+K3v3xjd588gOQhDzy51gorUsvrgfcxQmp84z/I1SNARxUXc8AE="}';</script>
        """
        http = Mock()
        http.document.return_value = (raw, CHAPTER, {})
        self.assertEqual(ACTIVE.inspect(CHAPTER, http)['pages'], ['https://cdn.example/1.jpg', 'https://cdn.example/2.jpg'])
