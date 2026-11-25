"""E1: a metadata card (AniList, OMDb …) first gets the playable rows of its work from the index; no network.

Manga: an AniList card whose name is only an alias of an indexed edition
("Sol-tank Talchulgi" / «Побег соло танка») gets that edition from the first
answer of /discovery/manga/search, before any live source request. Video: an
AniList anime card finds the OHentai series row of the same work by name and
year and the player opens that page without a title search. Ranobe: an AniList
card gets its RanobeLib book from the index at once; the live search continues
in the background and its answer keeps the old form. A row with the same name
but another year or kind is never taken.
"""
import json, os, sqlite3, sys, tempfile, threading, time, unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import catalogue_ohentai as oh
import content_catalog
import content_names
import manga_discovery as discovery
import ranobe_sources
import source_discovery
from site_adapters import BY_ID
from source_parser import SourceError

FIXTURES = Path(__file__).parent / 'fixtures'
SERIES = (FIXTURES / 'ohentai-series.html').read_text(encoding='utf-8')
INGRID = 'https://ohentai.org/sery_video.php?seryid=MjIz'
POLICY = {'schemaVersion': 1, 'tags': [], 'includeDiscovered': True, 'excludedTerms': [], 'excludedPrefixes': [], 'hiddenTags': []}
ENV = {'PUBLIC_URL': 'https://media.example', 'SUWAYOMI_URL': 'http://suwayomi:4567', 'SUWAYOMI_AUTH_FILE': '/private/auth'}
LIB = 'https://ranobelib.me/ru/book/'


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


class ContentIndex(unittest.TestCase):
    """content_titles in a temporary SQLite file, read through the catalogue reader."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        policy = Path(self.tmp.name) / 'policy.json'; policy.write_text(json.dumps(POLICY), encoding='utf-8')
        env = patch.dict(os.environ, {'MANGA_TAG_POLICY_FILE': str(policy), 'DATA_DIR': self.tmp.name}); env.start(); self.addCleanup(env.stop)
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        reader = contextmanager(lambda _store: (yield self.db))
        for guard in (patch('manga_discovery.manager'), patch('manga_discovery.catalogue_reader', reader)):
            guard.start(); self.addCleanup(guard.stop)

    def ingest(self, rows):
        with self.db:
            content_catalog.ingest(self.db, rows)


class VideoCardFindsTheIndexedSeries(ContentIndex):
    def setUp(self):
        super().setUp()
        self.row = oh.series_row(SERIES, INGRID)
        self.card = {'id': 'anilist:1', 'kind': 'anime', 'title': self.row['title'], 'aliases': [self.row['title']],
                     'year': self.row['year'], 'ids': {'anilist': '1', 'mal': '2'}}
        self.ingest([self.row,
                     {**self.row, 'id': 'ohentai:other-year', 'sourceUrl': 'https://ohentai.org/sery_video.php?seryid=MjI0', 'url': '', 'year': self.row['year'] + 7},
                     {'id': 'anilist:1', 'provider': 'anilist', 'kind': 'anime', 'title': self.row['title'], 'year': self.row['year'],
                      'ids': {'anilist': '1', 'mal': '2'}, 'sourceUrl': 'https://anilist.co/anime/1'}])

    def test_card_gets_the_series_page_of_its_work_and_not_the_other_year(self):
        self.assertEqual(source_discovery.index_anchors(self.card), {'ohentai': [INGRID]})

    def test_same_name_with_another_year_kind_or_no_year_is_not_taken(self):
        self.assertEqual(source_discovery.index_anchors({**self.card, 'year': 1990}), {})
        self.assertEqual(source_discovery.index_anchors({**self.card, 'kind': 'movie'}), {})
        self.assertEqual(content_names.lookup(self.db, 'ranobe', [self.row['title']]), [])
        undated = {**self.row, 'year': None}
        self.assertEqual(content_names.same_work(self.card, undated, year_required=True), (False, 'unverified_year'))

    def test_player_opens_the_indexed_page_first_without_a_title_search(self):
        searched = []
        from site_adapters import inspect_source
        guards = [patch.object(source_discovery, 'SITES', [BY_ID['eneyida'], BY_ID['ohentai']]),
                  patch('kodik_api.discover', return_value={'provider': 'kodik', 'name': 'Kodik', 'status': 'empty', 'complete': True, 'sources': []}),
                  patch('kinobox_source.discover', return_value={'provider': 'kinobox', 'name': 'Kinobox', 'status': 'empty', 'complete': True, 'sources': []}),
                  patch('source_index.save'), patch.dict(source_discovery._cache, {}, clear=True),
                  patch.object(source_discovery, 'PublicHttp', lambda **_: Http({INGRID: SERIES})),
                  patch.object(source_discovery, 'search_site', lambda site, q, http=None: searched.append(site.id) or {'status': 'empty', 'results': []}),
                  patch.object(source_discovery, 'inspect_source', lambda url, http=None, **kw: inspect_source(url, http=Http({INGRID: SERIES}), **kw))]
        for guard in guards:
            guard.start(); self.addCleanup(guard.stop)
        result = source_discovery._discover(self.card, refresh=True)
        [source] = result['sources']
        self.assertEqual((source['provider'], source['url'], source['matchEvidence']), ('ohentai', INGRID, 'catalogue_source'))
        self.assertEqual(len(source['episodes']), self.row['episodes'])
        self.assertNotIn('ohentai', searched)
        # The client's response keys are unchanged.
        self.assertEqual(set(result), {'title', 'voices', 'sources', 'providers', 'progress', 'pending', 'complete', 'checkedAt'})


class NamesIndexFill(ContentIndex):
    def test_existing_catalogue_is_filled_once_and_ingest_keeps_it(self):
        book = {'id': 'ranobelib:' + LIB + '1--book', 'provider': 'ranobelib', 'kind': 'ranobe', 'title': 'Книга', 'aliases': ['Kniga'],
                'sourceUrl': LIB + '1--book', 'url': LIB + '1--book'}
        self.ingest([book, {'id': 'anilist:9', 'provider': 'anilist', 'kind': 'ranobe', 'title': 'Kniga'}])
        # As an image without this module left it: rows, no names.
        with self.db:
            self.db.execute('DROP TABLE content_names'); self.db.execute("DELETE FROM content_catalog_state WHERE name='content-names'")
            content_names.initialize(self.db)
        self.assertEqual(content_names.pending(self.db), ['anime', 'ranobe'])
        self.assertEqual(content_names.lookup(self.db, 'ranobe', ['Kniga']), [])
        store = SimpleNamespace(lock=threading.RLock(), db=self.db)
        while content_names.step(store):
            pass
        self.assertTrue(content_names.ready(self.db))
        self.assertEqual([r['title'] for r in content_names.lookup(self.db, 'ranobe', ['kniga'])], ['Книга'])
        self.ingest([{**book, 'id': 'ranobelib:' + LIB + '2--other', 'sourceUrl': LIB + '2--other', 'url': LIB + '2--other', 'title': 'Другая'}])
        self.assertEqual([r['title'] for r in content_names.lookup(self.db, 'ranobe', ['Другая'])], ['Другая'])


class RanobeCardOpensTheIndexedBook(ContentIndex):
    def setUp(self):
        super().setUp()
        self.book = {'id': 'ranobelib:' + LIB + '267220--mob', 'provider': 'ranobelib', 'providerName': 'RanobeLib', 'kind': 'ranobe',
                     'title': 'Я всего лишь моб', 'aliases': ['Я всего лишь моб', 'Mob Shisai Dakedo'], 'language': 'ru',
                     'sourceUrl': LIB + '267220--mob', 'url': LIB + '267220--mob', 'year': 2021}
        self.ingest([self.book, {**self.book, 'id': 'ranobelib:' + LIB + '1--old', 'sourceUrl': LIB + '1--old', 'url': LIB + '1--old', 'year': 1999}])
        self.card = {'id': 'anilist:5', 'kind': 'ranobe', 'title': 'Mob Shisai Dakedo', 'aliases': ['Mob Shisai Dakedo'], 'year': 2021, 'ids': {'anilist': '5'}}
        self.release = threading.Event(); self.live = []
        def site(query, http, *_):
            self.live.append(query); self.release.wait(3)
            return iter([{'provider': 'ranobehub', 'providerName': 'RanobeHub', 'language': 'ru', 'title': query, 'url': 'https://ranobehub.org/ranobe/7'}]) if http.name == 'ranobehub' else iter([])
        searches = {identity: (lambda identity: lambda q, http, *a: site(q, SimpleNamespace(name=identity)))(identity) for identity in ranobe_sources.SEARCH}
        for guard in (patch.dict(ranobe_sources.SEARCH, searches), patch('ranobe_jp.search', return_value=[]),
                      patch.object(ranobe_sources, 'PublicHttp', lambda **_: Http({})), patch.dict(ranobe_sources._cache, {}, clear=True)):
            guard.start(); self.addCleanup(guard.stop)
        self.addCleanup(self.release.set)

    def wait(self):
        deadline = time.monotonic() + 5
        while ranobe_sources._running and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(ranobe_sources._running)

    def test_indexed_book_is_answered_at_once_and_the_live_answer_merges_it(self):
        started = time.monotonic()
        first = ranobe_sources.search(self.card, 'all')
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(first['pending'])
        self.assertEqual([(r['provider'], r['url'], r['matchEvidence']) for r in first['results']], [('ranobelib', LIB + '267220--mob', 'exact_title')])
        self.assertEqual({p['provider']: p['status'] for p in first['providers']}['ranobelib'], 'ok')
        self.release.set(); self.wait()
        final = ranobe_sources.search(self.card, 'all')
        self.assertEqual(set(final), {'results', 'providers', 'language', 'checkedAt'})
        self.assertEqual([r['url'] for r in final['results']], [LIB + '267220--mob', 'https://ranobehub.org/ranobe/7'])

    def test_without_an_indexed_book_the_live_search_answers_as_before(self):
        self.release.set()
        value = ranobe_sources.search({**self.card, 'title': 'Unknown Book', 'aliases': ['Unknown Book']}, 'all')
        self.assertEqual(set(value), {'results', 'providers', 'language', 'checkedAt'})
        self.assertEqual([r['url'] for r in value['results']], ['https://ranobehub.org/ranobe/7'])
        self.assertTrue(self.live)

    def test_same_name_of_another_year_or_language_is_not_taken(self):
        self.assertEqual(ranobe_sources.indexed_results({**self.card, 'year': 2005}), [])
        self.assertEqual([r['url'] for r in ranobe_sources.indexed_results(self.card)], [LIB + '267220--mob'])
        self.release.set()
        self.assertNotIn('pending', ranobe_sources.search(self.card, 'uk'))


class MangaCardGetsAnAliasEdition(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, ENV); env.start(); self.addCleanup(env.stop)

    def test_first_answer_lists_the_indexed_edition_before_any_source_request(self):
        from manga_catalog_index import upsert
        card = {'kind': 'manga', 'title': 'Sol-tank Talchulgi', 'aliases': ['Sol-tank Talchulgi'], 'year': 2026, 'ids': {'anilist': '220059'}}
        source = {'id': '1', 'name': 'Fixture', 'lang': 'ru', 'baseUrl': 'https://source.example', 'isNsfw': False}
        edition = {'kind': 'manga', 'title': 'Побег соло танка', 'aliases': ['Побег соло танка', 'Sol-tank Talchulgi'], 'year': 2026, 'language': 'ru'}
        fetched = []
        with tempfile.TemporaryDirectory() as directory, patch.object(discovery, 'installed_sources', return_value=[source]):
            manager = discovery.Discovery(directory, start_workers=False, fetch=lambda *a: fetched.append(a) or [])
            try:
                with manager.db:
                    upsert(manager.db, [{**edition, 'id': 'edition', 'provider': 'fixture', 'url': 'https://source.example/solo'},
                                        {**edition, 'id': 'other-year', 'provider': 'fixture', 'url': 'https://source.example/old', 'year': 2010}],
                           source_id='1')
                with discovery.catalogue_reader(manager) as reader:
                    # Per-source index searches keep the title-only lookup.
                    self.assertEqual(discovery.indexed_title_sources(reader, card, [source]), {})
                result = manager.start('owner', 'Sol-tank Talchulgi', 'all', title=card)
                self.assertEqual([(r['id'], r['url'], r['indexed']) for r in result['results']], [('edition', 'https://source.example/solo', True)])
                self.assertEqual(fetched, [])
            finally:
                manager.close()


if __name__ == '__main__':
    unittest.main()
