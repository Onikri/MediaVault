import csv
import json
import runpy
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import manga_fifth_batch_profiles
import manga_initmanga
import manga_madara
import manga_madaradex_guest
import manga_mangataro
from manga_russian_direct import svelte_value
from manga_series_port import public_form
from manga_source_urls import split_reader_url
from source_parser import SourceError, public_url


ROOT = Path(__file__).resolve().parents[1]


def fixture(routes):
    def document(url, **options):
        value = routes[url]
        return value if isinstance(value, str) else json.dumps(value), url, {}

    return Mock(document=Mock(side_effect=document), deadline=None)


def svelte(data):
    pool = []

    def slot(value):
        index = len(pool)
        pool.append(None)
        if isinstance(value, dict):
            pool[index] = {key: slot(item) for key, item in value.items()}
        elif isinstance(value, list):
            pool[index] = [slot(item) for item in value]
        else:
            pool[index] = value
        return index

    slot(data)
    return {'nodes': [{'type': 'skip'}, {'type': 'data', 'data': pool}]}


class FifthBatchTests(TestCase):
    def source(self, name, language=None):
        adapter = next(adapter for adapter in manga_fifth_batch_profiles.sources()
                       if adapter.NAME == name and (language is None or adapter.LANGUAGE == language))
        if hasattr(adapter, 'origin'):
            adapter.origin.interval = 0
        return adapter

    def test_profiles_are_staged_and_match_the_inventory(self):
        historical = [adapter for adapter in manga_madara.SOURCES if adapter.NAME in {'Anisa Scans', 'MadaraDex'}]
        selected = {adapter.SOURCE_ID: adapter for adapter in (*manga_fifth_batch_profiles.sources(), *historical)}
        candidates, active = runpy.run_path(str(ROOT / 'scripts/probe-native-source-batch.py'))['candidates']()
        with (ROOT / 'docs/native-source-inventory.csv').open(encoding='utf-8', newline='') as file:
            rows = [row for row in csv.DictReader(file) if row['source_id'] in selected]
        self.assertEqual(len(selected), 82)
        self.assertEqual(len({row['package'] for row in rows}), 50)
        self.assertEqual(set(selected), {row['source_id'] for row in rows})
        for row in rows:
            source = candidates[row['source_id']]
            self.assertEqual((source.NAME, source.LANGUAGE), (row['source'], row['language']))
            self.assertIs(type(source), type(selected[source.SOURCE_ID]))
            # Checked profiles go live through manga_native_activation.json.
            self.assertTrue(source.SOURCE_ID not in active or source.SOURCE_ID in __import__('manga_native_sources').activated_profiles())
            self.assertEqual(row['evidence'], 'native-source-verification.md#пятая-партия')

    def test_wamanga_reads_fractions_and_sorts_pages(self):
        source = self.source('WaManga')
        url = source.ROOT + '/manhwa/story'
        chapter = url + '/glava-1.5'
        suffix = '/__data.json?x-sveltekit-invalidated=001'
        http = fixture({
            url + suffix: svelte({'manga': {'type': 'manhwa', 'slug': 'story', 'title': 'История', 'titleEnglish': 'Story',
                                           'genres': ['Фэнтези'], 'tags': ['Регрессия'],
                                           'chapters': [{'position': '1.5', 'createdAt': '2026-01-01'}]}}),
            chapter + suffix: svelte({'chapter': {'files': [{'position': '2.000000000', 'diskFile': '/2.webp'},
                                                           {'position': '1.000000000', 'diskFile': '/1.webp'}]}}),
        })
        title = source.inspect(url, http)
        self.assertEqual((title['genres'], title['tags']), (['Фэнтези'], ['Регрессия']))
        episode = title['episodes'][0]
        self.assertEqual((episode['number'], split_reader_url(episode['url'])[1]), (1.5, chapter))
        self.assertEqual(source.inspect(episode['url'], http)['pages'], [source.ROOT + '/1.webp', source.ROOT + '/2.webp'])
        self.assertEqual(source.saved_chapter({'url': '/manhwa/story/1.5'}, source.ROOT, url), chapter)
        with self.assertRaises(ValueError):
            svelte_value([{'loop': 0}])

    def test_inkrush_uses_profile_language_and_keeps_hash_links(self):
        source = self.source('INKRUSH', 'id')
        title = source.ROOT + '/#title/a7'
        chapter = source.ROOT + '/#read/a7/ee15'
        api = source.ROOT + '/api/library?'
        http = fixture({
            api + 'action=detail&id=a7&language=id&compact=1':
                {'id': 'a7', 'title': 'Story', 'chapters': [{'id': 'ee15', 'chapterNumber': 1.5, 'name': 'Bab 1.5'}]},
            api + 'action=pages&id=ee15': {'pages': [{'src': '/page1.webp'}, {'src': '/page2.webp'}]},
        })
        episode = source.inspect(title, http)['episodes'][0]
        self.assertEqual(split_reader_url(episode['url'])[1], chapter)
        self.assertEqual(source.inspect(episode['url'], http)['pages'], [source.ROOT + '/page1.webp', source.ROOT + '/page2.webp'])
        with self.assertRaises(SourceError):
            public_url(api + 'action=account&language=id', resolve_dns=False)

    def test_astramanga_preserves_branches_volumes_and_array_order(self):
        source = self.source('AstraManga')
        root, api = source.ROOT, 'https://api.astramanga.org/api/v1'
        title = root + '/manga/example'
        http = fixture({
            api + '/titles/example': {'data': {'id': 72, 'slug': 'example', 'name': 'Example',
                                              'genres': [{'name': 'Фэнтези'}], 'tags': [{'name': 'Магия'}]}},
            api + '/titles/72/branches': {'data': {'branches': [{'id': 18, 'name': 'Team'}]}},
            api + '/branches/18/chapters?page=1&page_size=5000':
                {'data': {'items': [{'id': 981, 'number': 3.5, 'volume_number': 2}]}},
            api + '/chapters/981/pages': {'data': {'pages': [{'image_url': '/b.webp', 'page_number': 5},
                                                           {'image_url': '/a.webp', 'page_number': 4}]}},
        })
        episode = source.inspect(title, http)['episodes'][0]
        self.assertEqual((episode['number'], episode['season'], episode['translator']), (3.5, 2, 'Team'))
        self.assertEqual(source.inspect(episode['url'], http)['pages'], [root + '/b.webp', root + '/a.webp'])
        saved = source.saved_chapter({'url': 'example/3.5/981'}, root, title)
        self.assertEqual(saved, split_reader_url(episode['url'])[1])

    def test_rizz_uses_the_site_search_form(self):
        source = self.source('Rizz Comic')
        endpoint = source.ROOT + '/Index/live_search'
        http = fixture({endpoint: [{'id': '137', 'title': 'An Example', 'genre_id': '3,20', 'image_url': 'face.webp'}]})
        rows, more = source.catalogue(http, query='Example')
        fields = {'search_value': 'Example'}
        http.document.assert_called_once_with(endpoint, method='POST', action='native-series-form',
                                              headers={'Referer': source.ROOT + '/'}, data=fields)
        self.assertTrue(public_form(endpoint, fields, {}))
        self.assertFalse(public_form(endpoint, {'action': 'login'}, {}))
        self.assertEqual(rows[0]['genres'], ['Action', 'Fantasy'])
        self.assertFalse(more)

    def test_rawkuma_batches_wordpress_slugs_without_losing_order(self):
        source = self.source('Rawkuma', 'ja')
        root = source.ROOT

        def request(url, **options):
            parts = urlsplit(url)
            if 'get_nonce' in parts.query:
                data = '<input name="search_nonce" value="aabbcc123">'
            elif 'advanced_search' in parts.query:
                self.assertEqual(options['action'], 'natsuid-search')
                self.assertEqual(options['data']['nonce'], 'aabbcc123')
                data = ('<div><a href="/manga/zeta/"><img src="/z.webp"></a>'
                        '<a href="/manga/alpha/"><img src="/a.webp"></a></div><button><svg></svg></button>')
            else:
                self.assertEqual(parse_qs(parts.query, keep_blank_values=True)['slug[]'], ['zeta', 'alpha'])
                data = [{'slug': 'alpha', 'id': 11, 'title': {'rendered': 'Alpha'}},
                        {'slug': 'zeta', 'id': 12, 'title': {'rendered': 'Zeta'}}]
            return data if isinstance(data, str) else json.dumps(data), url, {}

        rows, more = source.catalogue(Mock(document=Mock(side_effect=request), deadline=None), query='字')
        self.assertEqual([row['title'] for row in rows], ['Zeta', 'Alpha'])
        self.assertTrue(more)
        self.assertEqual(source.saved_title_url('{"id":12,"slug":"zeta"}'), root + '/manga/zeta/?mv_id=12')

    def test_duck_groups_archived_pages_and_keeps_latest_pages_separate(self):
        source = self.source('The Duck Webcomics')
        root = source.ROOT
        title = root + '/Example/'
        menu = ('<select id="page_dropdown"><option value="4">- continued</option><option value="3">Chapter 2</option>'
                '<option value="2">- continued</option><option value="1">Chapter 1</option></select>')
        http = fixture({title: menu, title + '1/': menu + '<img class="page-image" src="/p1.webp">',
                        title + '2/': '<img class="page-image" src="/p2.webp">'})
        episodes = source.inspect(title, http)['episodes']
        self.assertEqual([split_reader_url(row['url'])[1] for row in episodes], [title + part for part in ('1/', '3/', '4/')])
        self.assertEqual(source.inspect(episodes[0]['url'], http)['pages'], [root + '/p1.webp', root + '/p2.webp'])

    def test_madaradex_refreshes_guest_only_for_its_routes(self):
        guest = manga_madaradex_guest.GuestSession()
        root = manga_madaradex_guest.ROOT
        header = manga_madaradex_guest.COOKIE_HEADER
        guest.fingerprint = 'mdx_fp=' + 'a' * 32

        def document(url, **options):
            if url.endswith('admin-ajax.php'):
                self.assertEqual(options['headers'][header], guest.fingerprint)
                self.assertEqual(options['data'], {'action': 'mdx_auth_refresh'})
                return '', url, {'Set-Cookie': 'mdx_auth=testing-token; Max-Age=500; Path=/'}
            self.assertEqual(options['headers'][header], guest.fingerprint + '; mdx_auth=testing-token')
            return '<html/>', url, {}

        http = Mock(document=Mock(side_effect=document))
        self.assertEqual(guest.request(http, root + '/title/example/', headers={})[0], '<html/>')
        self.assertEqual(guest.request(http, root + '/title/other/', headers={})[0], '<html/>')
        self.assertEqual(http.document.call_count, 3)
        self.assertFalse(manga_madaradex_guest.transport_mode('https://example.com/page', 'GET', None, 'madaradex-cdn',
                                                            {header: guest.cookie}))

    def test_mangataro_signs_outline_and_preserves_the_reader_id(self):
        source = self.source('MangaTaro')
        root = source.ROOT
        title = root + '/manga/work?mv_id=77'
        chapter = root + '/read/work/chapter-5-782'

        def handler(url, **options):
            parts = urlsplit(url)
            self.assertTrue(manga_mangataro.public_api(parts.netloc, parts.path, parts.query))
            if parts.path == manga_mangataro.OUTLINE:
                args = parse_qs(parts.query)
                self.assertEqual(args['manga_id'], ['77'])
                self.assertEqual(args['_t'][0], manga_mangataro.chapter_token(int(args['_ts'][0])))
                row = {'chapters': [{'url': chapter, 'chapter': '5', 'language': 'en', 'group_name': 'Team'}]}
            elif parts.path.startswith(manga_mangataro.DETAILS):
                row = {'id': 77, 'slug': 'work', 'title': {'rendered': 'Work'}, '_embedded': {}}
            elif parts.path == manga_mangataro.PAGES:
                self.assertEqual(parts.query, 'chapter_id=782')
                row = {'images': ['/1.png', '/2.png']}
            else:
                self.fail(f'Unexpected request {parts.path}')
            return json.dumps(row), url, {}

        http = Mock(document=Mock(side_effect=handler), deadline=None)
        episodes = source.inspect(title, http)['episodes']
        self.assertEqual([(split_reader_url(episode['url'])[1], episode['translator']) for episode in episodes], [(chapter, 'Team')])
        http.document.side_effect = lambda url, **options: (
            ('<body data-manga-id="77"></body>', url, {}) if url == root + '/manga/work' else handler(url, **options))
        self.assertEqual(source.inspect(episodes[0]['url'], http)['pages'], [root + '/1.png', root + '/2.png'])

    def test_initmanga_catalogue_skips_locked_chapters(self):
        source = self.source('Mgread.io')
        root = source.ROOT
        title = root + '/manga/work/'
        url = title + 'chapter-2/'
        http = fixture({
            title: '<body class="postid-72"><h1>Work</h1></body>',
            root + manga_initmanga.OUTLINE + '?manga_id=72&per_page=50&paged=1': {
                'total_pages': 1,
                'items': [{'slug': 'chapter-1', 'number': 1, 'lock_type': 'coins', 'is_purchased': False},
                          {'slug': 'chapter-2', 'number': 2, 'lock_type': 'none', 'is_purchased': False}],
            },
            url: '<div id="chapter-content"><img data-src="/2.webp"></div>',
        })
        episodes = source.inspect(title, http)['episodes']
        self.assertEqual([split_reader_url(row['url'])[1] for row in episodes], [url])
        self.assertEqual(source.inspect(episodes[0]['url'], http)['pages'], [root + '/2.webp'])
        self.assertEqual(manga_initmanga.public_form(root + manga_initmanga.VAULT_API,
                         {'action': 'imip_gate_unlock', 'cid': '7', 'nonce': 'valid_nonce'}, {'Referer': url}), 'vault')
        self.assertFalse(manga_initmanga.public_form(root + manga_initmanga.VAULT_API,
                         {'action': 'imip_gate_unlock', 'cid': '7', 'nonce': 'valid_nonce'},
                         {'Referer': 'https://example.com/manga/work/chapter-2/'}))
