"""D5: the page-item cache is compacted in resumable batches, and undated
video rows with a watch page count as «available». Temporary SQLite only; no network."""
import json, os, sqlite3, sys, tempfile, threading, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import content_catalog
import content_works
import page_cache_compact
from catalogue_indexer import Indexer
from manga_catalog_index import initialize
from manga_tag_policy import canonical_json

POLICY = {'schemaVersion': 1, 'includeDiscovered': True, 'hiddenTags': [], 'excludedTerms': [], 'excludedPrefixes': [], 'tags': []}


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        policy = Path(self.temp.name) / 'manga-tag-policy.json'
        policy.write_bytes(canonical_json(POLICY))
        self.env = patch.dict(os.environ, {'DATA_DIR': self.temp.name, 'MANGA_TAG_POLICY_FILE': str(policy), 'MEDIA_VAULT_DISABLE_WORKER': '1'})
        self.env.start()
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        initialize(self.db)
        content_catalog.initialize(self.db)
        self.db.commit()
        self.store = SimpleNamespace(db=self.db, lock=threading.RLock())
        self.now = 100000

    def tearDown(self):
        self.db.close()
        self.env.stop()
        self.temp.cleanup()

    def worker(self, fetch=None):
        return Indexer(self.store, fetch or (lambda s, c: {}), lambda: self.now, interval=0)

    def job(self, key):
        return self.db.execute('SELECT state,reason,due,pages,records FROM catalogue_jobs WHERE id=?', (key,)).fetchone()


class PageCacheCompaction(Base):
    def fill(self):
        self.worker()  # the indexer's tables
        jobs = {'done': ('done', 5), 'running': ('running', 3), 'active': ('retry', 2), 'fresh': ('queued', 0)}
        with self.db:
            for key, (state, pages) in jobs.items():
                self.db.execute("INSERT INTO catalogue_jobs(id,spec,cursor,state,priority,due,pages,updated,kind,host) VALUES(?,?,?,?,10,0,?,0,'lib','x')",
                                (key, '{"type":"lib","domain":"x"}', '{"page":3}', state, pages))
            for key in (*jobs, 'gone'):
                self.db.executemany('INSERT INTO catalogue_page_items VALUES(?,?)', ((key, 'u%d' % n) for n in range(23)))
                self.db.execute('INSERT INTO catalogue_page_fingerprints VALUES(?,?)', (key, 'digest'))

    def items(self):
        return dict(self.db.execute('SELECT job,COUNT(*) FROM catalogue_page_items GROUP BY job'))

    def pending(self):
        (Path(self.temp.name) / page_cache_compact.PENDING).write_text('{}', encoding='utf-8')

    def test_nothing_runs_without_the_owner_flag(self):
        self.fill()
        self.assertFalse(page_cache_compact.step(self.store))
        self.assertEqual(len(self.items()), 5)

    def test_only_sets_no_run_reads_are_dropped_in_batches(self):
        self.fill()
        self.pending()
        statements = []
        self.db.set_trace_callback(lambda s: statements.append(s) if s.startswith('DELETE FROM catalogue_page_items') else None)
        with patch.object(page_cache_compact, 'BATCH', 10):
            try:
                while page_cache_compact.step(self.store):
                    pass
            finally:
                self.db.set_trace_callback(None)
        self.assertEqual(self.items(), {'running': 23, 'active': 23})
        # 23 rows per job in batches of 10: three deletes each for done, fresh, gone.
        self.assertEqual(len(statements), 9)
        job = page_cache_compact.read_job()
        self.assertEqual((job['state'], job['deleted'], job['jobs'], job['kept']), ('done', 69, 3, 2))
        self.assertTrue((Path(self.temp.name) / 'page-cache-compact-accepted.json').exists())
        # Fingerprints, jobs and their counters stay.
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM catalogue_page_fingerprints').fetchone()[0], 5)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM catalogue_jobs').fetchone()[0], 4)
        self.assertFalse(page_cache_compact.step(self.store))

    def test_a_restart_continues_from_the_saved_cursor(self):
        self.fill()
        self.pending()
        with patch.object(page_cache_compact, 'BATCH', 10):
            for _ in range(4):
                page_cache_compact.step(self.store)
            saved = page_cache_compact.read_job()
            self.assertEqual(saved['state'], 'running')
            # A new process: only the job file and the table carry the progress.
            import importlib
            importlib.reload(page_cache_compact)
            with patch.object(page_cache_compact, 'BATCH', 10):
                while page_cache_compact.step(self.store):
                    pass
        self.assertEqual(self.items(), {'running': 23, 'active': 23})
        self.assertEqual(page_cache_compact.read_job()['deleted'], 69)

    def test_a_listing_in_progress_keeps_counting_and_skipping_after_compaction(self):
        def row(n):
            url = 'https://fixture.example/title/%d' % n
            return {'provider': 'fixture', 'kind': 'manga', 'title': 'Garden %d' % n, 'url': url, 'sourceUrl': url, 'language': 'en'}
        pages = {1: [row(1), row(2)], 2: [row(2), row(3)], 3: [row(1), row(2)]}
        worker = self.worker(lambda s, c: {'rows': pages[c['page']], 'next': {'page': c['page'] + 1}})
        with self.store.lock, self.db:
            key = worker.enqueue({'type': 'lib', 'domain': 'fixture.example', 'name': 'Fixture', 'site': 1})
        worker.run_once()
        self.pending()
        while page_cache_compact.step(self.store):
            pass
        self.assertEqual(self.items(), {key: 2})
        self.now += 3
        worker.run_once()
        # The kept URL set counts row 2 once: 3 unique records.
        self.assertEqual(self.job(key)[3:], (2, 3))
        self.now += 3
        worker.run_once()
        # Page 3 repeats page 1: the fingerprint still recognises it.
        state = self.db.execute('SELECT state,error FROM catalogue_jobs WHERE id=?', (key,)).fetchone()
        self.assertEqual(state[0], 'retry')
        self.assertIn('repeated-page', state[1])


def video(n, **extra):
    url = 'https://hanime1.me/watch?v=%d' % n
    return {'id': url, 'provider': 'hanime1', 'kind': 'anime', 'title': 'Clip %d' % n, 'age': '18', 'url': url, 'sourceUrl': url,
            'genres': ['Хентай'], **extra}


class UndatedVideoAvailable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        policy = Path(self.tmp.name) / 'policy.json'
        policy.write_text(json.dumps(POLICY), encoding='utf-8')
        self.env = patch.dict(os.environ, {'MANGA_TAG_POLICY_FILE': str(policy)})
        self.env.start()
        self.db = sqlite3.connect(Path(self.tmp.name) / 'catalogue.sqlite', timeout=5)
        content_catalog.initialize(self.db)
        rows = [video(1, episodes=1), video(2, episodes=24), video(3, episodes=1, status='released'), video(4),
                video(5, episodes=2, status='anons'), video(6, episodes=1, year=2099),
                {**video(7, episodes=12), 'url': '', 'provider': 'anilist', 'id': 'anilist:7', 'status': 'NOT_YET_RELEASED'},
                {**video(8, episodes=12), 'url': '', 'provider': 'anilist', 'id': 'anilist:8'},
                video(9, episodes=1, episodesAired=0)]
        content_catalog.ingest(self.db, rows)
        self.db.commit()

    def tearDown(self):
        for thread in threading.enumerate():
            if thread.name == 'catalog-total':
                thread.join(10)
        self.db.close()
        self.env.stop()
        self.tmp.cleanup()

    def titles(self, path):
        with patch.object(content_works, 'ready', (lambda conn: False) if path == 'old' else content_works.ready):
            result = content_catalog.browse(self.db, prepared=True, kind='anime', status='available', limit=60)
        return sorted(item['title'] for item in result['items']), result['total']

    def test_watch_pages_without_a_date_are_available_on_both_paths(self):
        expected = ['Clip 1', 'Clip 2', 'Clip 3']
        self.assertTrue(content_works.ready(self.db))
        self.assertEqual(self.titles('old'), (expected, 3))
        self.assertEqual(self.titles('new'), (expected, 3))
        avail = dict(self.db.execute('SELECT search,avail FROM content_works'))
        self.assertEqual(sum(value == 1 for value in avail.values()), 3)

    def test_a_new_availability_revision_refills_in_the_background(self):
        with self.db:
            self.db.execute('UPDATE content_works SET avail=0')
        store = SimpleNamespace(db=self.db, lock=threading.RLock())
        with patch.object(content_works, 'AVAILABILITY', 'next'):
            content_works._signatures.clear()
            with self.db:
                content_works.initialize(self.db)
            state = content_works._state(self.db)
            # Nothing was recomputed yet; the old values are served meanwhile.
            self.assertEqual(state['phase'], 'fill')
            self.assertTrue(content_works.ready(self.db))
            self.assertEqual(self.titles('new')[1], 0)
            while content_works.step(store):
                pass
            self.assertEqual(self.titles('new'), (['Clip 1', 'Clip 2', 'Clip 3'], 3))
        content_works._signatures.clear()


if __name__ == '__main__':
    unittest.main()
