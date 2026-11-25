"""G1: an index card opens and plays/reads through the client's own path; no network.

Video: an indexed OHentai series (with its year) used to be turned down by the
discovery year rule because the site's search cards publish no year. The card
now sends its own index row, discovery inspects that page and the player gets
the episode's MP4. Manga: a source page whose heading differs from its index
card ("Naturalia" vs "Elena B in Met Art set Naturalia") is still the card's
source, so /manga/inspect accepts it.
"""
import json, os, sqlite3, sys, tempfile, threading, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import catalogue_ohentai as oh
import content_catalog
import hentai_video_sites as sites
import source_discovery
from dynamic_video_sources import CATALOGUED, catalogued_source, provider_for, resolve_dynamic
from site_adapters import BY_ID
from source_parser import SourceError

FIXTURES = Path(__file__).parent / 'fixtures'
read = lambda name: (FIXTURES / f'ohentai-{name}.html').read_text(encoding='utf-8')
SERIES, EPISODE, SEARCH = read('series'), read('episode'), read('search')
ROOT = 'https://ohentai.org/'
INGRID = ROOT + 'sery_video.php?seryid=MjIz'
EP1 = ROOT + 'detail.php?vid=NDgz'
BUNNY = 'https://openload.b-cdn.net/Old%20Anime/Makai%20Kishi%20Ingrid/Makai%20Kishi%20Ingrid_ep3_en.mp4?token=FIXTURE&expires=1795608063'


class Http:
    def __init__(self, pages):
        self.pages = pages; self.calls = []; self.deadline = None
    def document(self, url, headers=None, **_):
        self.calls.append(url)
        if url not in self.pages:
            raise SourceError('Источник вернул HTTP 404.')
        return self.pages[url], url, {}
    def close(self):
        pass


def card(row):
    """The discovery title the client sends for an index card (use-source-discovery.js)."""
    title = {k: row[k] for k in ('id', 'title', 'aliases', 'year', 'kind') if k in row}
    title.update(provider=row['provider'], sourceURL=row['sourceUrl'])
    return title


class IndexedVideoCardPlays(unittest.TestCase):
    def setUp(self):
        # The search hit is the series' fourth episode page (detail.php?vid=NDg2).
        self.pages = {INGRID: SERIES, ROOT + 'search.php?k=Makai+Kishi+Ingrid': SEARCH, ROOT + 'detail.php?vid=NDg2': EPISODE}
        guards = [patch.object(source_discovery, 'SITES', [BY_ID['ohentai']]),
                  patch('kodik_api.discover', return_value={'provider': 'kodik', 'name': 'Kodik', 'status': 'empty', 'complete': True, 'sources': []}),
                  patch('kinobox_source.discover', return_value={'provider': 'kinobox', 'name': 'Kinobox', 'status': 'empty', 'complete': True, 'sources': []}),
                  patch('source_index.save'),
                  patch.object(source_discovery, 'PublicHttp', lambda **_: Http(self.pages)),
                  patch.dict(source_discovery._cache, {}, clear=True)]
        for guard in guards:
            guard.start(); self.addCleanup(guard.stop)
        # The site's search is real fixture HTML: its cards carry no year.
        from site_adapters import inspect_source, search_site
        patch.object(source_discovery, 'search_site', lambda site, q, http=None: search_site(site, q, http=Http(self.pages))).start()
        patch.object(source_discovery, 'inspect_source', lambda url, http=None, **kw: inspect_source(url, http=Http(self.pages), **kw)).start()
        self.addCleanup(patch.stopall)
        self.row = oh.series_row(SERIES, INGRID)

    def test_index_row_has_a_year_and_its_own_series_page(self):
        self.assertEqual((self.row['provider'], self.row['year'], self.row['sourceUrl']), ('ohentai', 2009, INGRID))
        self.assertEqual(catalogued_source('ohentai', self.row['sourceUrl']), INGRID)

    def test_title_search_alone_turns_the_dated_card_down(self):
        selected = {k: v for k, v in card(self.row).items() if k not in ('provider', 'sourceURL')}
        result = source_discovery._discover(selected, refresh=True)
        self.assertEqual(result['sources'], [])
        self.assertEqual([p['status'] for p in result['providers'] if p['provider'] == 'ohentai'], ['unverified'])

    def test_card_opens_its_series_and_plays_the_first_episode_in_our_player(self):
        result = source_discovery._discover(card(self.row), refresh=True)
        [source] = result['sources']
        self.assertEqual((source['provider'], source['url'], source['matchEvidence']), ('ohentai', INGRID, 'catalogue_source'))
        self.assertEqual(len(source['episodes']), self.row['episodes'])
        self.assertEqual(source['episodes'][0]['url'], EP1)
        self.assertEqual([p['status'] for p in result['providers'] if p['provider'] == 'ohentai'], ['ok'])
        # First episode -> the site's direct MP4 in our player (1 KiB range check mocked).
        third = source['episodes'][2]['url']
        with patch('dynamic_video_sources.check_mp4', side_effect=lambda _h, s, **__: None if s['url'] == BUNNY else (_ for _ in ()).throw(SourceError('expired'))):
            page = resolve_dynamic(Http({third: EPISODE}), third, None, 'OHentai · EN', 'ohentai')
        self.assertEqual([s['url'] for s in page.streams], [BUNNY])

    def test_merged_work_sends_every_catalogued_row_and_rejects_foreign_addresses(self):
        found = source_discovery.indexed_sources({'provider': 'anilist', 'sourceURL': 'https://anilist.co/anime/1',
                                                  'indexedSources': [{'provider': 'ohentai', 'url': INGRID},
                                                                     {'provider': 'ohentai', 'url': 'https://evil.net/sery_video.php?seryid=MjIz'},
                                                                     {'provider': 'hentaimama', 'url': INGRID},
                                                                     {'provider': 'watchhentai', 'url': 'http://watchhentai.net/series/x/'},
                                                                     {'provider': 'hentaimama', 'url': 'https://hentaimama.io/tvshows/15-bishoujo-hyouryuuki/'}]})
        self.assertEqual(found, {'ohentai': [INGRID], 'hentaimama': ['https://hentaimama.io/tvshows/15-bishoujo-hyouryuuki/']})
        self.assertEqual(CATALOGUED, {'hanime', 'hanime1', 'hentaimama', 'watchhentai', 'ohentai'})
        for provider, url in [('hanime1', 'https://hanime1.me/watch?v=27938'), ('hanime', 'https://hanime.tv/videos/hentai/zutto-suki-datta-1'),
                              ('watchhentai', 'https://watchhentai.net/series/ikusa-otome-valkyrie-shinshou-id-01/')]:
            self.assertEqual(catalogued_source(provider, url), url)
        self.assertEqual(catalogued_source('anilist', 'https://anilist.co/anime/1'), '')
        # Distinct anchors are distinct discovery cache entries.
        self.assertNotEqual(source_discovery._key(card(self.row)), source_discovery._key({**card(self.row), 'sourceURL': ''}))

    def test_content_card_lists_its_catalogued_video_rows(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        policy = Path(tmp.name) / 'policy.json'
        policy.write_text(json.dumps({'schemaVersion': 1, 'tags': [], 'includeDiscovered': True, 'excludedTerms': [], 'excludedPrefixes': [], 'hiddenTags': []}), encoding='utf-8')
        with patch.dict(os.environ, {'MANGA_TAG_POLICY_FILE': str(policy), 'DATA_DIR': tmp.name}):
            from manga_tag_policy import current
            records = [('a', {'provider': 'anilist', 'kind': 'anime', 'title': 'Makai Kishi Ingrid', 'sourceUrl': 'https://anilist.co/anime/1'}),
                       ('b', {**self.row})]
            row = content_catalog._work_row('k', records, False, current())
        self.assertEqual(row['indexedSources'], [{'provider': 'ohentai', 'url': INGRID}])


class IndexedMangaCardReads(unittest.TestCase):
    def test_source_page_with_its_own_heading_is_still_the_cards_source(self):
        from manga_catalog_index import initialize, source_names, upsert
        from title_identity import match_title
        db = sqlite3.connect(':memory:'); initialize(db)
        url = 'https://www.metarthunter.com/elena-b-naturalia/'
        provider = 'suwayomi:3567512546321944475'
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        policy = Path(tmp.name) / 'policy.json'
        policy.write_text(json.dumps({'schemaVersion': 1, 'tags': [], 'includeDiscovered': True, 'excludedTerms': [], 'excludedPrefixes': [], 'hiddenTags': []}), encoding='utf-8')
        with patch.dict(os.environ, {'MANGA_TAG_POLICY_FILE': str(policy), 'DATA_DIR': tmp.name}):
            upsert(db, [{'provider': provider, 'sourceId': '3567512546321944475', 'url': url, 'sourceUrl': url, 'title': 'Naturalia',
                         'aliases': ['Naturalia'], 'kind': 'manga', 'language': 'all'}])
        work = {'title': 'Naturalia', 'aliases': ['Naturalia'], 'kind': 'manga'}
        page = {'title': 'Elena B in Met Art set Naturalia', 'aliases': ['Elena B in Met Art set Naturalia'], 'kind': 'manga'}
        self.assertFalse(match_title(work, page)[0])
        rows = source_names(db, provider, [url + '?mv_manga_source=3567512546321944475', url])
        self.assertEqual([r['title'] for r in rows], ['Naturalia'])
        self.assertTrue(any(match_title(work, r)[0] for r in rows))
        # Another work, another provider or another page is not admitted.
        self.assertFalse(any(match_title({'title': 'Other Work', 'kind': 'manga'}, r)[0] for r in rows))
        self.assertEqual(source_names(db, 'suwayomi:1', [url]), [])
        self.assertEqual(source_names(db, provider, ['https://www.metarthunter.com/other/']), [])
        # The endpoint's check reads the same index through the catalogue reader.
        import api
        from contextlib import contextmanager
        reader = contextmanager(lambda _store: (yield db))
        with patch('manga_discovery.manager'), patch('manga_discovery.catalogue_reader', reader):
            self.assertTrue(api.indexed_card_matches(work, {'provider': provider, 'url': url + '?mv_gallery=1'}, url))
            self.assertFalse(api.indexed_card_matches({'title': 'Other Work', 'kind': 'manga'}, {'provider': provider, 'url': url}, url))

    def test_inspect_endpoint_accepts_the_indexed_page_and_still_refuses_others(self):
        import api
        from fastapi import HTTPException
        value = {'provider': 'suwayomi:3567512546321944475', 'providerName': 'Metart Hunter', 'title': 'Elena B in Met Art set Naturalia',
                 'url': 'https://www.metarthunter.com/elena-b-naturalia/', 'kind': 'manga', 'language': 'all',
                 'episodes': [{'number': 1, 'season': 1, 'url': 'https://www.metarthunter.com/elena-b-naturalia/?mv_gallery=1', 'language': 'all'}], 'pages': []}
        body = SimpleNamespace(url=value['url'], title={'title': 'Naturalia', 'aliases': ['Naturalia'], 'kind': 'manga'}, verifyPages=False, refresh=False)
        subject = {'role': 'owner'}
        with patch('manga_inspection.inspect', return_value=dict(value)), patch.object(api, 'guest_may_open'), \
             patch.object(api, 'indexed_card_matches', return_value=True) as card, \
             patch('manga_discovery.manager', return_value=SimpleNamespace(lock=threading.Lock(), db=sqlite3.connect(':memory:'))),              patch('manga_catalog_index.upsert') as indexed:
            result = api.manga_inspect(body, subject)
        self.assertEqual(result['title'], value['title']); card.assert_called_once(); indexed.assert_called_once()
        with patch('manga_inspection.inspect', return_value=dict(value)), patch.object(api, 'guest_may_open'), \
             patch.object(api, 'indexed_card_matches', return_value=False), patch('manga_discovery.manager', side_effect=RuntimeError):
            with self.assertRaises(HTTPException) as refused:
                api.manga_inspect(body, subject)
        self.assertEqual(refused.exception.status_code, 422)


if __name__ == '__main__':
    unittest.main()
