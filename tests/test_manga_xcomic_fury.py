import json
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

import manga_comicfury as fury
import manga_xcomic as xcomic
from manga_native_sources import saved_reader_url
from manga_xcomic_queries import BROWSE, EDITION, FULL, PAGER, PAGES, PROBE, QUERIES, TITLE, UNIQUE
from source_parser import PublicHttp, SourceError, public_url


class XComicTests(TestCase):
    def setUp(self):
        self.http = Mock(deadline=None)
        self.source = next(profile for profile in xcomic.SOURCES if profile.LANGUAGE == 'pt-BR')
        pace = patch.object(xcomic.PACE, 'interval', 0)
        pace.start()
        self.addCleanup(pace.stop)

    def test_browse_selects_language_and_separates_edition_labels(self):
        card = {'id': 'canonical', 'title': 'The &amp; Story', 'comic_ids': ['a', 'b', 'c'],
                'translated_languages': ['pt_br', 'en'], 'genre_ids': ['action']}
        editions = {'a': 'pt_br', 'b': 'pt_br', 'c': 'en'}

        def gql(_http, operation, variables):
            if operation == BROWSE:
                self.assertEqual(variables['select']['incTLangs'], ['pt_br'])
                self.assertEqual(variables['select']['incGenres'], ['action'])
                return [{'id': 'canonical', 'data': card}]
            if operation == PAGER:
                return {'next': 2, 'total': 13}
            if operation == TITLE:
                return {'id': 'canonical', 'data': card}
            if operation in {PROBE, EDITION}:
                key = variables['id']
                return {'id': key, 'data': {'translatedLanguage': editions[key], 'isPublic': True, 'subName': 'Scan'}}
            self.assertEqual(operation, UNIQUE)
            key = variables['select']['comic_id']
            self.assertIn(key, 'ab')
            entry = {'id': 'chapter_' + key, 'chaNum': 7, 'volNum': 2}
            return {'paging': {'next': 0, 'total': 1}, 'items': [{'id': entry['id'], 'data': entry}]}

        with patch.object(xcomic, 'gql', side_effect=gql):
            cards, more = self.source.catalogue(self.http, query='The Story', tag='action')
            self.assertTrue(more)
            self.assertEqual(cards[0]['title'], 'The & Story')
            reading = self.source.inspect(cards[0]['url'], self.http)
            self.assertEqual([item['translator'] for item in reading['episodes']], ['Scan [a]', 'Scan [b]'])
            self.assertEqual([item['season'] for item in reading['episodes']], [2, 2])

    def test_legacy_title_pair_and_original_duplicate_chapter_still_open(self):
        source = self.source
        record = {'id': 'newTitle', 'title': 'Restored', 'comic_ids': ['edition']}
        bridge = Mock()
        bridge.get.return_value = [{'index': 2, 'url': 'oldChapter', 'memo': {'comicId': 'edition'}}]
        saved = saved_reader_url(source, bridge, {'baseUrl': source.ROOT},
                                 source.ROOT + '/oldTitle:edition', 111, 2)
        self.assertEqual(parse_qs(urlsplit(saved).query)['legacy_id'], ['edition'])

        def gql(_http, operation, variables):
            if operation == TITLE:
                key = variables['id']
                return None if key == 'oldTitle' else {'id': key, 'data': record}
            if operation in {PROBE, EDITION}:
                self.assertEqual(variables['id'], 'edition')
                return {'id': 'edition', 'data': {'translatedLanguage': 'pt_br', 'title_titleNode': {'id': 'newTitle',
                                                    'data': record}, 'isPublic': True}}
            if operation == UNIQUE:
                return {'paging': {'next': None, 'total': 1}, 'items': [{'id': 'other', 'data': {'id': 'other'}}]}
            if operation == FULL:
                return {'paging': {'next': None, 'total': 1}, 'items': [{'id': 'oldChapter', 'data': {'id': 'oldChapter'}}]}
            self.assertEqual(operation, PAGES)
            return {'id': 'oldChapter', 'data': {'imageUrls': ['/cdn/page2.jpg', '/cdn/page1.jpg']}}

        with patch.object(xcomic, 'gql', side_effect=gql):
            info = source.inspect(saved, self.http)
            self.assertEqual(info['pages'], [source.ROOT + '/cdn/page2.jpg', source.ROOT + '/cdn/page1.jpg'])
            with self.assertRaises(SourceError):
                source.inspect(saved.replace('edition=edition', 'edition=unrelated'), self.http)

    def test_transport_only_accepts_fixed_public_queries(self):
        client = PublicHttp(session=Mock(), validate=lambda url: public_url(url, resolve_dns=False))
        client.session.request.return_value = Mock(status_code=200)
        correct = json.dumps({'query': QUERIES[TITLE], 'variables': {'id': 'work_1'}}).encode()
        client._open(xcomic.ENDPOINT, method='POST', data=correct, action='xcomic-graphql')
        self.assertEqual(client.session.request.call_args.kwargs['headers']['Content-Type'], 'application/json')
        blocked = json.dumps({'query': 'mutation { clear }', 'variables': {}}).encode()
        with self.assertRaises(SourceError):
            client._open(xcomic.ENDPOINT, method='POST', data=blocked, action='xcomic-graphql')
        for root in ('https://outside.example/query/', xcomic.ROOT+'/query/?demo=1'):
            self.assertFalse(xcomic.graphql_form(root, correct))

    def test_vocabulary_separates_format_and_genre(self):
        raw = ('<details class="group"><summary>Genres</summary><div><div :="action"><span>Action</span></div></div>'
               '<div>Formats</div><div><div :="long_strip"><span>Long Strip</span></div></div></details>')
        self.http.document.return_value = raw, xcomic.ROOT + '/search', {}
        self.assertEqual([(row['sourceId'], row['category']) for row in self.source.vocabulary(self.http)],
                         [('action', 'genre'), ('long_strip', 'tag')])


class ComicFuryTests(TestCase):
    def setUp(self):
        self.http = Mock(deadline=None)
        self.http.fork.return_value = self.http
        self.source = next(profile for profile in fury.SOURCES if profile.NAME.endswith('(No Text)'))

    def test_custom_and_main_archives_keep_stable_chapters(self):
        archive = fury.ROOT + '/read/Story/archive'
        profile = '<div class="username-and-title"><div class="authorname">Story</div><em>Summary</em></div>'
        work = '<div class="archive-chapter"><span class="archive-chapter-title">S1</span></div>'
        tree = f'<a href="{archive}/chapter/7">{work}</a>'
        section = ('<a href="/read/Story/comics/42"><div class="archive-comic"><span class="archive-comic-title">Page</span>'
                   '<span class="archive-comic-date">18th Nov 2012, 1:01 PM</span></div></a>')
        main = '<div class="is--comic-page"><div class="is--image-segment"><div><img src="/image.png"></div></div></div>'
        custom = '<img id="comicimage" src="https://cdn.example/full.png">'
        search = ('<div class="webcomic-result"><div class="webcomic-result-avatar">'
                  '<a href="/comicprofile.php?url=Story"><img src="/cover.jpg"></a></div>'
                  '<div class="webcomic-result-title" title="Story">Story</div></div>')

        def document(http, url):
            parts = urlsplit(url)
            if parts.path == '/search.php':
                self.assertEqual(parse_qs(parts.query)['language'], ['notext'])
                return BeautifulSoup(search, 'html.parser'), url
            values = {'/comicprofile.php': profile, '/read/Story/archive': tree,
                      '/read/Story/archive/chapter/7': section, '/read/Story/comics/42': main,
                      '/comics/42': custom}
            return BeautifulSoup(values[parts.path], 'html.parser'), url

        solo = 'https://story.webcomic.ws/comics/42'
        with patch.object(fury, 'document', side_effect=document):
            card, = self.source.catalogue(self.http, query='Story')[0]
            ep, = self.source.inspect(card['url'], self.http)['episodes']
            self.assertEqual(ep['publishedAt'], '2012-11-18')
            self.assertEqual(ep['title'], 'S1 — Page')
            self.assertEqual(self.source.inspect(ep['url'], self.http)['pages'], [fury.ROOT + '/image.png'])
            bridge = Mock()
            bridge.get.return_value = [{'index': 2, 'url': solo}]
            saved = saved_reader_url(self.source, bridge, {'baseUrl': fury.ROOT}, card['url'], 7, 2)
            self.assertEqual(self.source.inspect(saved, self.http)['pages'], ['https://cdn.example/full.png'])

    def test_warning_form_follows_only_same_page(self):
        client = PublicHttp(session=Mock(), validate=lambda url: public_url(url, resolve_dns=False))
        target = fury.ROOT + '/read/Story/comics/5'
        form = {'token': 'exampletoken', 'proceed': 'View Webcomic'}
        redirect = Mock(status_code=302, headers={'Location': target})
        result = Mock(status_code=200)
        client.session.request.side_effect = [redirect, result]
        response, final = client._open(target, method='POST', data=form, action='comicfury-warning')
        self.assertIs(response, result)
        self.assertEqual(final, target)
        follow = client.session.request.call_args
        self.assertEqual(follow.args[0], 'GET')
        self.assertIsNone(follow.kwargs['data'])
        client.session.request.side_effect = [Mock(status_code=302, headers={'Location': target+'/other'})]
        with self.assertRaises(SourceError):
            client._open(target, method='POST', data=form, action='comicfury-warning')
