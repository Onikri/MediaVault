import csv
import json
import runpy
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
from urllib.parse import urlencode

import manga_fourth_batch_profiles
import manga_inkstory
import manga_senkuro_native
from manga_page_media import page_reference
from manga_source_urls import split_reader_url
from source_parser import SourceError, public_url


ROOT = Path(__file__).resolve().parents[1]


def fixture(routes):
    def document(url, **options):
        data = routes[url]
        return data if isinstance(data, str) else json.dumps(data), url, {}

    return Mock(document=Mock(side_effect=document), deadline=None)


class FourthBatchTests(TestCase):
    def source(self, name, language=None):
        source = next(source for source in manga_fourth_batch_profiles.sources()
                      if source.NAME == name and (not language or source.LANGUAGE == language))
        if hasattr(source, 'origin'):
            source.origin.interval = 0
        return source

    def test_complete_batch_is_staged_with_original_identities(self):
        sources = {source.SOURCE_ID: source for source in manga_fourth_batch_profiles.sources()}
        candidates, active = runpy.run_path(str(ROOT / 'scripts/probe-native-source-batch.py'))['candidates']()
        with (ROOT / 'docs/native-source-inventory.csv').open(encoding='utf-8', newline='') as file:
            rows = [row for row in csv.DictReader(file) if row['source_id'] in sources]
        self.assertEqual(len(sources), 54)
        self.assertEqual(len({row['package'] for row in rows}), 50)
        self.assertEqual(set(sources), {row['source_id'] for row in rows})
        for row in rows:
            source = candidates[row['source_id']]
            self.assertEqual((source.NAME, source.LANGUAGE), (row['source'], row['language']))
            self.assertIs(type(source), type(sources[source.SOURCE_ID]))
            # Checked profiles go live through manga_native_activation.json.
            self.assertTrue(source.SOURCE_ID not in active or source.SOURCE_ID in __import__('manga_native_sources').activated_profiles())
            self.assertEqual(row['evidence'], 'native-source-verification.md#четвёртая-партия-из-50-apk')

    def test_goda_chapter_ids_survive_the_reader_and_saved_urls(self):
        source = self.source('Goda')
        root = source.ROOT
        title = root + '/manga/example'
        chapter = title + '/chapter-2#123/456'
        http = fixture({
            title: '<main><div><div><h1>Example</h1></div></div><div id="mangachapters" data-mid="123"></div></main>',
            root + '/manga/get?mid=123&mode=all':
                '<div class="chapteritem"><a href="/manga/example/chapter-2" data-cs="456" data-ct="Chapter 2"></a></div>',
            root + '/chapter/getcontent?m=123&c=456':
                '<div id="chapcontent"><div><img data-src="/2.webp"><img data-src="/3.webp"></div></div>',
        })
        episodes = source.inspect(title, http)['episodes']
        self.assertEqual([split_reader_url(item['url'])[1] for item in episodes], [chapter])
        self.assertEqual(source.inspect(episodes[0]['url'], http)['pages'], [root + '/2.webp', root + '/3.webp'])
        self.assertEqual(source.saved_chapter({'realUrl': chapter.split('#')[0], 'url': chapter}, root, title), chapter)

    def test_senkuro_reads_chapter_ids_and_translation_teams(self):
        source = self.source('Senkuro')
        root = source.ROOT
        api = 'https://api.senkuro.com/graphql'
        title = root + '/manga/example?mv_id=md123'

        def request(url, **options):
            self.assertEqual(url, api)
            self.assertTrue(manga_senkuro_native.public_form(url, options['data'], options['headers']['App-Id']))
            body = json.loads(options['data'])
            self.assertEqual(body['variables']['mangaId'], 'md123')
            key = next(key for key, q in manga_senkuro_native.QUERIES.items() if q == body['query'])
            replies = {
                'details': {'slug': 'example', 'id': 'md123', 'titles': [{'lang': 'RU', 'content': 'Example'}]},
                'chapters': {'chapters': [{'id': 'ch123', 'slug': 'chapter-2', 'volume': 3, 'number': 2,
                                          'teamIds': ['team1']}], 'teams': [{'id': 'team1', 'name': 'Team'}]},
                'pages': {'pages': [{'url': '/1.webp'}]},
            }
            return json.dumps({'data': {manga_senkuro_native.KEY[key]: replies[key]}}), url, {}

        http = Mock(document=Mock(side_effect=request), deadline=None)
        episode = source.inspect(title, http)['episodes'][0]
        self.assertIn('mv_chapter=ch123', split_reader_url(episode['url'])[1])
        self.assertEqual((episode['season'], episode['translator']), (3, 'Team'))
        self.assertEqual(source.inspect(episode['url'], http)['pages'], [root + '/1.webp'])
        self.assertFalse(manga_senkuro_native.public_form(api, b'{}', '5033164800100'))

    def test_inkstory_round_trip_and_image_marker_validation(self):
        data = {'text': 'Фраза <\n"終"\\', 'items': [True, False, None, 2, {'text': '字'}]}
        root = json.loads(manga_inkstory.payload(data))['t']
        self.assertEqual(manga_inkstory.decode_result({'p': {'k': ['result'], 'v': root['p']['v']}}), data)
        blob = b'RIFF' + bytes(range(256))
        encrypted = bytes(byte ^ manga_inkstory.KEY[index % len(manga_inkstory.KEY)] for index, byte in enumerate(blob))
        self.assertEqual(manga_inkstory.decode_image(encrypted), blob)
        path = '/01234567-abcd-x012-0000-0123456789ab.webp'
        url = f'https://static.inuko.me{path}#mv_inkstory_page'
        self.assertEqual(page_reference(url), (url.split('#')[0], None, 1, 'inkstory-image'))
        with self.assertRaises(SourceError):
            page_reference(url.replace('static.inuko.me', 'example.com'))

    def test_xkcd_uses_original_numbers_and_author_notes(self):
        source = self.source('xkcd', 'en')
        root = source.ROOT
        http = fixture({root + '/archive/': '<div id="middleContainer"><a href="/42/" title="2006-01-01">Answer</a></div>',
                        root + '/42/': '<div id="comic"><img src="//imgs.xkcd.com/comics/42.png" title="Author note"></div>'})
        episode = source.inspect(root + '/', http)['episodes'][0]
        self.assertEqual(episode['number'], 42)
        pages = source.inspect(episode['url'], http)
        self.assertEqual(pages['pages'], ['https://imgs.xkcd.com/comics/42.png'])
        self.assertEqual(pages['authorNotes'], 'Author note')

    def test_manhuatop_reader_path_cannot_point_at_another_host(self):
        root = 'https://manhuatop.org/api/reader'
        query = urlencode({'resource': 'content', 'path': '/manhua/work/part-1/'})
        self.assertEqual(public_url(f'{root}?{query}', resolve_dns=False), f'{root}?{query}')
        bad = urlencode({'resource': 'content', 'path': '//example.com/manhua/work/part-1/'})
        with self.assertRaises(SourceError):
            public_url(f'{root}?{bad}', resolve_dns=False)
