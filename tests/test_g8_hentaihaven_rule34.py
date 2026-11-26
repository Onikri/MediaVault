"""G8: HentaiHaven's Rule 34 section in the index and our player; no network.

Fixtures are live public answers of 2026-11-26 (G8 recon), trimmed:
hentaihaven-rule34-list.json — five rule34-video posts of the REST list (the
three oldest and two of the newest page; «Alien Tentacles Attack Bartender»
names no master, as ~10 % of the newest page), the fields the walk asks for;
hentaihaven-rule34-terms.json — the category/tag/artist terms of those posts
found in the 100 most used of each dictionary (the others stay unnamed, which
the walk tolerates); hentaihaven-rule34-master.m3u8 — the HLS master of
«Screw It – MLP HMV» (no subtitle renditions).
"""
import contextlib, json, sqlite3, sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import catalogue_hentaihaven_rule34 as rule34, catalogue_indexer, catalogue_sources, content_names, hentai_video_sites as sites, source_discovery
from dynamic_video_sources import CATALOGUED, catalogued_source, provider_for, resolve_dynamic
from site_adapters import BY_ID, SITES
from source_parser import SourceError, SourceListingEnd

FIXTURES = Path(__file__).parent / 'fixtures'
read = lambda name: (FIXTURES / name).read_text(encoding='utf-8')
CMS = 'https://cms.hentaihaven.xxx/wp-json/wp/v2/'
LIST = CMS + 'rule34-video?per_page=100&page='
BY_SLUG = CMS + 'rule34-video?slug='
CLIP = 'https://hentaihaven.xxx/rule34/video/screw-it-mlp-hmv/'
MASTER = 'https://octopusmanifest.org/7e76fd56-9a06-44e8-9ad5-111d4ff3e340/playlist.m3u8'
SPEC = {'type': 'hentaihaven-rule34', 'kind': 'anime', 'domain': 'hentaihaven.xxx', 'name': 'Хентай · HentaiHaven · Rule 34'}


class Http:
    """Answers by URL prefix (longest first); records every request."""
    def __init__(self, pages):
        self.pages = pages; self.calls = []; self.deadline = None
    def document(self, url, headers=None, **_):
        self.calls.append(url)
        for prefix in sorted(self.pages, key=len, reverse=True):
            if url.startswith(prefix):
                value = self.pages[prefix]
                if isinstance(value, Exception):
                    raise value
                text, extra = value if isinstance(value, tuple) else (value, {})
                return text, url, extra
        error = SourceError('Источник вернул HTTP 404.'); error.http_status = 404
        raise error
    def close(self):
        pass


def posts():
    return json.loads(read('hentaihaven-rule34-list.json'))


def slug_answer(slug):
    return json.dumps([{k: p[k] for k in ('id', 'slug', 'type', 'title', 'link', 'date', 'manifest_url')} for p in posts() if p['slug'] == slug])


def walk_pages(listing=None, tag_pages=1):
    terms = json.loads(read('hentaihaven-rule34-terms.json'))
    tags = terms['rule34-video-tag']
    half = len(tags) // 2
    found = {CMS + 'rule34-video-category?per_page=100&page=1&': (json.dumps(terms['rule34-video-category']), {'X-WP-TotalPages': '1'}),
             CMS + 'rule34-video-artist?per_page=100&page=1&': (json.dumps(terms['rule34-video-artist']), {'X-WP-TotalPages': '1'}),
             LIST + '1&': (json.dumps(listing if listing is not None else posts()), {'X-WP-Total': '5', 'X-WP-TotalPages': '1'})}
    if tag_pages == 1:
        found[CMS + 'rule34-video-tag?per_page=100&page=1&'] = (json.dumps(tags), {'X-WP-TotalPages': '1'})
    else:
        found[CMS + 'rule34-video-tag?per_page=100&page=1&'] = (json.dumps(tags[:half]), {'X-WP-TotalPages': '2'})
        found[CMS + 'rule34-video-tag?per_page=100&page=2&'] = (json.dumps(tags[half:]), {'X-WP-TotalPages': '2'})
    return found


def walk(http, cursor=None):
    step = rule34.catalogue(SPEC, cursor or {'page': 1}, http)
    rows, vocabulary, calls = list(step['rows']), list(step.get('vocabulary') or []), 1
    while step['next'] and calls < 20:
        # The indexer stores the cursor as JSON between calls.
        step = rule34.catalogue(SPEC, json.loads(json.dumps(step['next'])), http)
        rows.extend(step['rows']); vocabulary.extend(step.get('vocabulary') or []); calls += 1
    return rows, vocabulary, calls


class Fresh(unittest.TestCase):
    def setUp(self):
        sites._rule34_posts.clear()


class Index(Fresh):
    def test_walk_rows(self):
        http = Http(walk_pages(tag_pages=2))
        rows, vocabulary, calls = walk(http)
        # category, 2 tag pages, artist, 1 list page: one request a call.
        self.assertEqual((calls, len(http.calls)), (5, 5))
        # The clip without a master gives no row.
        self.assertEqual([r['url'].rsplit('/', 2)[-2] for r in rows],
                         ['d-va-fan-service-rule-34-lvl3toaster', '9s-fucks-bunny-2b-rule-34-exga', 'mercy-takes-in-the-ass-rule-34-kallenz', 'screw-it-mlp-hmv'])
        row = rows[0]
        url = 'https://hentaihaven.xxx/rule34/video/d-va-fan-service-rule-34-lvl3toaster/'
        self.assertEqual({k: row[k] for k in ('id', 'provider', 'kind', 'title', 'url', 'sourceUrl', 'year', 'genres', 'cover', 'age', 'episodes')},
                         {'id': 'hentaihaven-rule34:' + url, 'provider': 'hentaihaven-rule34', 'kind': 'anime',
                          'title': 'D.Va Fan Service – Rule 34 – Lvl3toaster', 'url': url, 'sourceUrl': url, 'year': 2023,
                          'genres': ['Rule 34'], 'cover': 'https://cdnr-octopus.hhpanel.org/rule34video/2026/07/16/2def88dc1582509c12ca2dba259f31b8/thumbnails/thumb_001.webp',
                          'age': 18, 'episodes': 1})
        # The site's categories and tags, as named, in the post's order; artists as studios.
        self.assertEqual(row['tags'][:3], ['3D', 'Overwatch', 'cowgirl position'])
        self.assertIn('d.va (overwatch)', row['tags'])
        self.assertIn('MP4 720p', row['tags'])
        self.assertEqual(rows[1]['studios'], ['Exga'])
        self.assertEqual(rows[3]['year'], 2024)
        self.assertFalse(any(r.get('ids') for r in rows))
        # The section label and the site's tags reach the vocabulary; artists do not.
        self.assertEqual(vocabulary[0], {'category': 'genre', 'label': 'Rule 34'})
        labels = {v['label'] for v in vocabulary}
        self.assertTrue({'Overwatch', 'futanari', 'd.va (overwatch)'} <= labels)
        self.assertNotIn('Exga', labels)
        self.assertEqual({v['category'] for v in vocabulary[1:]}, {'tag'})
        # Every row opens as its own catalogued page and is never a name anchor.
        for value in rows:
            self.assertEqual(catalogued_source('hentaihaven-rule34', value['url']), value['url'])
            self.assertEqual(catalogued_source('hentaihaven', value['url']), '')
            self.assertFalse(content_names.playable(value))
            self.assertLessEqual(len(value['id']), 200)

    def test_rows_that_do_not_play_or_are_not_clips(self):
        bad = posts()[:1] * 5
        bad = [dict(p) for p in bad]
        bad[0]['manifest_url'] = 'https://evil.example/cf42c7bc-ee1e-4d43-ac46-2e598a5e4b4d/playlist.m3u8'
        bad[1]['manifest_url'] = 'https://octopusmanifest.org/cf42c7bc/playlist.m3u8?token=1'
        bad[2]['type'] = 'wp-manga'
        bad[3]['link'] = 'https://cms.hentaihaven.xxx/channels/d-va-fan-service-rule-34-lvl3toaster/'
        bad[4]['manifest_url'] = 'http://octopusmanifest.org/cf42c7bc-ee1e-4d43-ac46-2e598a5e4b4d/playlist.m3u8'
        rows, _, _ = walk(Http(walk_pages(listing=bad)))
        self.assertEqual(rows, [])
        # A cover only from the player's thumbnail host.
        self.assertEqual(rule34.cover({'thumbnail_url': 'https://cms.hentaihaven.xxx/www/2024/07/x.png'}), '')
        self.assertEqual(rule34.cover({'thumbnail_url': 'http://cdnr-octopus.hhpanel.org/x/thumb_001.webp'}), '')

    def test_walk_ends_and_resumes(self):
        gone = SourceError('Источник вернул HTTP 400.'); gone.http_status = 400
        with self.assertRaises(SourceListingEnd):
            rule34.catalogue(SPEC, {'step': 'clips', 'page': 3, 'terms': {}}, Http({LIST: gone}))
        # A dictionary past its end goes on to the next one.
        step = rule34.catalogue(SPEC, {'step': 'terms', 'taxonomy': 1, 'page': 2, 'terms': {}}, Http({CMS + 'rule34-video-tag?': gone}))
        self.assertEqual((step['next']['step'], step['next']['taxonomy'], step['next']['page']), ('terms', 2, 1))
        # An empty list page holds no row but the walk continues.
        empty = [dict(posts()[3])]
        step = rule34.catalogue(SPEC, {'step': 'clips', 'page': 1, 'terms': {}},
                                Http({LIST + '1&': (json.dumps(empty), {'X-WP-TotalPages': '3'})}))
        self.assertEqual((step['rows'], step['emptySpan'], step['next']['page'], step['next']['last']), ([], True, 2, 3))
        self.assertEqual(rule34.unpack(rule34.pack({'7': 'tag'})), {'7': 'tag'})
        self.assertEqual(rule34.unpack('not base64'), {})

    def test_job_and_host(self):
        jobs = [j for j in catalogue_sources.base_sources([]) if str(j['type']).startswith('hentaihaven')]
        self.assertEqual({j['type'] for j in jobs}, {'hentaihaven', 'hentaihaven-rule34'})
        self.assertEqual(catalogue_indexer.refresh_interval(SPEC), 7 * 86400)
        self.assertIn('hentaihaven-rule34', catalogue_indexer.BASE_KINDS)
        # Both HentaiHaven jobs share one host: its pace and one request slot.
        self.assertEqual(catalogue_indexer.host_of(SPEC), catalogue_indexer.host_of({**SPEC, 'type': 'hentaihaven'}))
        self.assertEqual(catalogue_indexer.SLOTS['hentaihaven.xxx'], 1)
        with patch('catalogue_hentaihaven_rule34.catalogue', return_value={'rows': [], 'next': None}) as run:
            catalogue_sources.fetch(SPEC, {'page': 1})
        self.assertEqual(run.call_args.args[:2], (SPEC, {'page': 1}))


class Player(Fresh):
    def test_addresses(self):
        self.assertEqual(provider_for(CLIP), ('hentaihaven-rule34', 'HentaiHaven · Rule 34'))
        self.assertIn('hentaihaven-rule34', CATALOGUED)
        for url in ('https://hentaihaven.xxx/channels/x/', 'https://hentaihaven.xxx/porn-sites/x/', 'https://hentaihaven.xxx/rule34/video/',
                    'https://hentaihaven.xxx/rule34/video/a/b/', 'https://hentaihaven.xxx/rule34/video/clip/?x=1',
                    'http://hentaihaven.xxx/rule34/video/clip/', 'https://evil.example/rule34/video/clip/',
                    'https://hentaihaven.xxx/rule34/channels/clip/', 'https://hentaihaven.xxx/rule34/video/Clip/',
                    'https://hentaihaven.xxx/rule34/video/' + 'a' * 121 + '/'):
            self.assertIsNone(sites.provider_for(url), url)
        self.assertEqual(sites.rule34_master(MASTER), MASTER)
        for value in ('https://evil.example/7e76fd56-9a06-44e8-9ad5-111d4ff3e340/playlist.m3u8',
                      'https://octopusmanifest.org/7e76fd56-9a06-44e8-9ad5-111d4ff3e340/v.m3u8',
                      'https://octopusmanifest.org/../playlist.m3u8', MASTER + '?t=1', MASTER.replace('https', 'http'), ''):
            self.assertEqual(sites.rule34_master(value), '', value)

    def test_episodes_and_stream(self):
        http = Http({BY_SLUG + 'screw-it-mlp-hmv&': slug_answer('screw-it-mlp-hmv'), MASTER: read('hentaihaven-rule34-master.m3u8')})
        title, episodes, about = sites.episodes('hentaihaven-rule34', CLIP, http)
        self.assertEqual((title, about), ('Screw It – MLP HMV', {'year': 2024}))
        self.assertEqual(episodes, [{'number': 1, 'season': 1, 'url': CLIP, 'title': 'Screw It – MLP HMV'}])
        page = resolve_dynamic(http, CLIP, None, title, 'hentaihaven-rule34')
        self.assertEqual([(s['url'], s['type']) for s in page.streams], [(MASTER, 'hls')])
        self.assertEqual(page.streams[0]['headers']['Referer'], 'https://hentaihaven.xxx/')
        self.assertEqual(page.subtitles, [])
        # The post is read once for the inspection and its playback; then the master.
        self.assertEqual(sum(c.startswith(BY_SLUG) for c in http.calls), 1)
        self.assertEqual(http.calls[-1], MASTER)
        # No title search exists for clips.
        self.assertEqual(sites.search('hentaihaven-rule34', 'Screw It', http), [])

    def test_clip_without_stream(self):
        http = Http({BY_SLUG: slug_answer('alien-tentacles-attack-bartender')})
        url = 'https://hentaihaven.xxx/rule34/video/alien-tentacles-attack-bartender/'
        with self.assertRaises(SourceError):
            sites.episodes('hentaihaven-rule34', url, http)
        with self.assertRaises(SourceError):
            sites.streams('hentaihaven-rule34', url, http)
        # Another clip's answer for this slug is not this clip.
        with self.assertRaises(SourceError):
            sites.episodes('hentaihaven-rule34', CLIP, Http({BY_SLUG: slug_answer('d-va-fan-service-rule-34-lvl3toaster')}))

    def test_own_row_opens_only_its_clip(self):
        http = Http({BY_SLUG + 'screw-it-mlp-hmv&': slug_answer('screw-it-mlp-hmv'), MASTER: read('hentaihaven-rule34-master.m3u8')})
        card = {'id': 'x', 'kind': 'anime', 'title': 'Screw It – MLP HMV', 'aliases': ['Screw It – MLP HMV'], 'year': 2024,
                'provider': 'hentaihaven-rule34', 'sourceURL': CLIP}
        with patch('site_adapters.PublicHttp', lambda **_: http), patch.object(source_discovery, '_discover', side_effect=AssertionError('title search')):
            result = source_discovery.discover(card)
        self.assertEqual(set(result), {'title', 'voices', 'sources', 'providers', 'progress', 'pending', 'complete', 'checkedAt'})
        self.assertEqual([(s['provider'], s['url'], s['providerName'], s['matchEvidence']) for s in result['sources']],
                         [('hentaihaven-rule34', CLIP, 'HentaiHaven · Rule 34', 'catalogue_source')])
        self.assertEqual(result['providers'], [{'provider': 'hentaihaven-rule34', 'name': 'HentaiHaven · Rule 34', 'status': 'ok', 'complete': True}])
        self.assertTrue(result['voices'])
        self.assertEqual(http.calls, [BY_SLUG + 'screw-it-mlp-hmv&_fields=' + 'id%2Cslug%2Ctype%2Ctitle%2Clink%2Cdate%2Cmanifest_url'])
        # A Rule 34 card with another page is refused, never searched by its title.
        for other in ('https://hentaihaven.xxx/watch/overflow/', 'https://evil.example/rule34/video/screw-it-mlp-hmv/', None):
            with self.assertRaises(ValueError):
                source_discovery.discover({**card, 'sourceURL': other})
        # A clip that stopped playing answers «unavailable», not another work.
        gone = SourceError('Источник вернул HTTP 404.'); gone.http_status = 404
        sites._rule34_posts.clear()
        with patch('site_adapters.PublicHttp', lambda **_: Http({BY_SLUG: gone})):
            result = source_discovery.discover(card)
        self.assertEqual((result['sources'], result['providers'][0]['status']), ([], 'unavailable'))


class NoFalseMerges(Fresh):
    ROW = {'id': 'hentaihaven-rule34:https://hentaihaven.xxx/rule34/video/overflow/', 'provider': 'hentaihaven-rule34', 'kind': 'anime',
           'title': 'Overflow', 'aliases': ['Overflow'], 'year': 2020, 'url': 'https://hentaihaven.xxx/rule34/video/overflow/',
           'sourceUrl': 'https://hentaihaven.xxx/rule34/video/overflow/'}
    SERIES = {'id': 'hentaihaven:https://hentaihaven.xxx/watch/overflow/', 'provider': 'hentaihaven', 'kind': 'anime', 'title': 'Overflow',
              'aliases': ['Overflow'], 'year': 2020, 'url': 'https://hentaihaven.xxx/watch/overflow/', 'sourceUrl': 'https://hentaihaven.xxx/watch/overflow/'}
    CARD = {'id': 'anilist:110209', 'kind': 'anime', 'year': 2020, 'format': 'ONA', 'title': 'Overflow', 'aliases': ['Overflow'], 'adult': True}

    def test_names_table_skips_clips(self):
        db = sqlite3.connect(':memory:')
        db.execute('CREATE TABLE content_catalog_state(name TEXT PRIMARY KEY,value TEXT)')
        db.execute('CREATE TABLE content_titles(id TEXT PRIMARY KEY,kind TEXT,search TEXT,raw TEXT,updated INTEGER)')
        content_names.initialize(db)
        for identity, row in (('clip', self.ROW), ('series', self.SERIES)):
            db.execute('INSERT INTO content_titles VALUES(?,?,?,?,0)', (identity, 'anime', '', json.dumps(row)))
            content_names.update(db, identity, row)
        self.assertEqual({r for (r,) in db.execute('SELECT title_id FROM content_names')}, {'series'})
        self.assertEqual([r['provider'] for r in content_names.lookup(db, 'anime', ['Overflow'])], ['hentaihaven'])

    def test_anchors_skip_clips(self):
        # Even a clip row that reached the lookup is no anchor of a card of that name.
        with patch('manga_discovery.manager', return_value=None), patch('manga_discovery.catalogue_reader', lambda store: contextlib.nullcontext(None)), \
             patch('content_names.lookup', return_value=[self.ROW, self.SERIES]):
            anchors = source_discovery.index_anchors(self.CARD)
        self.assertEqual(anchors, {'hentaihaven': ['https://hentaihaven.xxx/watch/overflow/']})

    def test_discover_of_an_anime_card_never_gets_clips(self):
        self.assertNotIn('hentaihaven-rule34', BY_ID)
        self.assertFalse(any(s.id == 'hentaihaven-rule34' for s in SITES))
        sites_for_card = source_discovery.discovery_sites('anime', True, {'hentaihaven-rule34': [self.ROW['url']]})
        self.assertFalse(any(s.id == 'hentaihaven-rule34' for s in sites_for_card))
        # The series search answers a rule34-video post of the same name: not a result.
        search = json.dumps([{'id': 1, 'slug': 'overflow', 'type': 'rule34-video', 'title': {'rendered': 'Overflow'},
                              'link': 'https://cms.hentaihaven.xxx/rule34/video/overflow/', 'wp-manga-release': []}])
        http = Http({CMS + 'wp-manga?search=': search, CMS + 'wp-manga-release?': '[]'})
        sites._haven_years.update(at=0.0, years={}); sites._haven_titles.clear()
        guards = [patch.object(source_discovery, 'SITES', (BY_ID['hentaihaven'],)),
                  patch.object(source_discovery, 'PublicHttp', lambda **_: http),
                  patch('kinobox_source.discover', return_value={'provider': 'kinobox', 'name': 'Kinobox', 'status': 'empty', 'complete': True, 'sources': []}),
                  patch('source_index.save'), patch.dict(source_discovery._cache, {}, clear=True),
                  patch('content_names.matches', return_value=[self.ROW])]
        for guard in guards:
            guard.start()
        try:
            result = source_discovery._discover(self.CARD, refresh=True)
        finally:
            for guard in reversed(guards):
                guard.stop()
        self.assertEqual(result['sources'], [])
        self.assertFalse(any('rule34' in c for c in http.calls if 'wp-manga' not in c))
        self.assertNotIn('hentaihaven-rule34', {p['provider'] for p in result['providers']})


if __name__ == '__main__':
    unittest.main()
