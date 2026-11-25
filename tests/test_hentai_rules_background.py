"""A new hentai source in catalog-taxonomy.json: start-up stays O(1), the
«Хентай» sets of manga and video are recomputed in the background.

Offline: temporary SQLite files, no network, no real catalogue."""
import json, os, re, sqlite3, sys, tempfile, threading, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import catalog_taxonomy, content_catalog, content_works, hentai_works, manga_catalog_index, tag_merge
from catalog_taxonomy import HENTAI
from manga_tag_policy import canonical_json

POLICY = {'schemaVersion': 1, 'includeDiscovered': True, 'hiddenTags': [], 'excludedTerms': [], 'excludedPrefixes': [], 'tags': []}
NEW = {'providers': [*HENTAI['providers'], 'fixturetube'], 'hosts': [*HENTAI['hosts'], 'fixturetube.example']}


def manga_rows(size):
    rows = []
    for n in range(size):
        rows.append({'provider': 'hentailib', 'kind': 'manga', 'title': 'Origin %d' % n, 'sourceUrl': 'https://hentailib.me/m/%d' % n})
        rows.append({'provider': 'plain', 'kind': 'manga', 'title': 'Plain %d' % n, 'sourceUrl': 'https://plain.example/m/%d' % n,
                     'genres': ['Романтика']})
        rows.append({'provider': 'fixturetube', 'kind': 'manga', 'title': 'Tube %d' % n, 'sourceUrl': 'https://fixturetube.example/m/%d' % n})
    rows.append({'provider': 'fixturetube', 'kind': 'manga', 'title': 'Tube vetoed', 'sourceUrl': 'https://fixturetube.example/m/vetoed',
                 'tags': ['Не хентай']})
    return rows


def video_rows(size):
    rows = []
    for n in range(size):
        rows.append({'id': 'h%d' % n, 'kind': 'anime', 'provider': 'hanime', 'title': 'Hanime %d' % n, 'sourceUrl': 'https://hanime.tv/v/%d' % n})
        rows.append({'id': 'p%d' % n, 'kind': 'anime', 'provider': 'plain', 'title': 'Show %d' % n, 'sourceUrl': 'https://plain.example/v/%d' % n})
        rows.append({'id': 't%d' % n, 'kind': 'anime', 'provider': 'fixturetube', 'title': 'Tube video %d' % n,
                     'sourceUrl': 'https://fixturetube.example/v/%d' % n})
    rows.append({'id': 'tv', 'kind': 'anime', 'provider': 'fixturetube', 'title': 'Tube video vetoed',
                 'sourceUrl': 'https://fixturetube.example/v/vetoed', 'tags': ['Not hentai']})
    return rows


class Fixture(unittest.TestCase):
    size = 6

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / 'manga-tag-policy.json').write_bytes(canonical_json(POLICY))
        self.env = patch.dict(os.environ, {'DATA_DIR': self.temp.name, 'MANGA_TAG_POLICY_FILE': str(root / 'manga-tag-policy.json')})
        self.env.start()
        patch.object(tag_merge, 'PAUSE', 0).start()
        self.path = self.build(root / 'catalogue.sqlite', self.size)
        self.db = self.open(self.path)
        self.store = SimpleNamespace(db=self.db, lock=threading.RLock())
        self.before = (self.manga(), self.video())

    def tearDown(self):
        patch.stopall()
        content_works._signatures.clear()
        self.db.close()
        self.env.stop()
        self.temp.cleanup()

    @staticmethod
    def open(path):
        db = sqlite3.connect(path, check_same_thread=False, timeout=5)
        manga_catalog_index.initialize(db)
        content_catalog.initialize(db)
        db.commit()
        return db

    def build(self, path, size):
        db = self.open(path)
        manga_catalog_index.upsert(db, manga_rows(size))
        content_catalog.ingest(db, video_rows(size))
        db.commit()
        db.close()
        return path

    def new_rules(self):
        """The release with the new source: same data, a new process."""
        patch.dict(HENTAI, NEW).start()
        content_works._signatures.clear()

    def restart(self):
        self.db.close()
        self.db = self.open(self.path)
        self.store.db = self.db

    def manga(self):
        result = manga_catalog_index.browse(self.db, genre='Хентай', limit=100)
        return sorted(row['workKey'] for row in result['items'])

    def video(self):
        self.assertIsNotNone(content_works.page(self.db, kind='anime', genre='Хентай'), 'materialized path')
        result = content_catalog.browse(self.db, kind='anime', genre='Хентай', limit=100, prepared=True)
        return sorted(row['title'] for row in result['items'])

    def derived(self):
        with patch.object(hentai_works, 'ready', return_value=False), patch.object(content_works, 'ready', lambda conn: False):
            manga = sorted(row['workKey'] for row in manga_catalog_index.browse(self.db, genre='Хентай', limit=100)['items'])
            video = sorted(row['title'] for row in content_catalog.browse(self.db, kind='anime', genre='Хентай', limit=100, prepared=True)['items'])
        return manga, video

    def settle(self, check=None):
        while tag_merge.step(self.store, pause=0):
            if check:
                check()


class Startup(Fixture):
    def initialize_traced(self, path):
        calls = []
        counting = lambda *args: calls.append(args) or catalog_taxonomy.hentai_origin.__wrapped__(*args)
        counting.__wrapped__ = catalog_taxonomy.hentai_origin
        statements = []
        db = sqlite3.connect(path)
        indexes = sorted(db.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall())
        db.set_trace_callback(statements.append)
        with patch.object(catalog_taxonomy, 'hentai_origin', counting):
            manga_catalog_index.initialize(db)
            content_catalog.initialize(db)
            db.commit()
        db.set_trace_callback(None)
        after = sorted(db.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall())
        db.close()
        return statements, calls, indexes, after

    def test_a_new_source_costs_the_start_up_nothing(self):
        self.db.close()
        bigger = self.build(Path(self.temp.name) / 'bigger.sqlite', self.size * 4)
        self.new_rules()
        traces = []
        for path in (self.path, bigger):
            statements, calls, indexes, after = self.initialize_traced(path)
            self.assertEqual(calls, [], 'no origin is evaluated at start-up')
            self.assertEqual(after, indexes, 'no index is built or dropped')
            heavy = [s for s in statements if re.search(r'DROP\s+INDEX|DELETE FROM (catalog|content)_tags\b|catalog_hentai_origin', s, re.I)]
            self.assertEqual(heavy, [])
            traces.append([re.sub(r"'[^']*'|\d+", '?', s) for s in statements])
        # The same statements for four times the rows: O(1).
        self.assertEqual(traces[0], traces[1])
        self.db = self.open(self.path)
        self.store.db = self.db
        self.assertEqual(hentai_works._state(self.db)['phase'], 'clear')
        self.assertEqual(content_works._state(self.db)['phase'], 'fill')
        self.assertEqual((self.manga(), self.video()), self.before, 'the previous sets answer meanwhile')

    def test_the_projection_revision_ignores_the_origin_lists(self):
        data = json.loads(json.dumps(catalog_taxonomy.DATA))
        data['sourceGenres']['hentai'].update(NEW)
        self.assertEqual(catalog_taxonomy._revision(data), catalog_taxonomy.REVISION)
        for field, value in (('kinds', ['manga']), ('excludeLabels', ['Не хентай'])):
            changed = json.loads(json.dumps(catalog_taxonomy.DATA))
            changed['sourceGenres']['hentai'][field] = value
            self.assertNotEqual(catalog_taxonomy._revision(changed), catalog_taxonomy.REVISION, field)
        stamp = catalog_taxonomy.veto_stamp()
        self.new_rules()
        self.assertEqual(catalog_taxonomy.veto_stamp(), stamp, 'the veto index depends only on excludeLabels')

    def test_the_origin_portion_reads_the_unique_index(self):
        plan = ' '.join(str(part) for row in self.db.execute(
            'EXPLAIN QUERY PLAN SELECT provider,source_url,rowid FROM catalog_titles WHERE (provider,source_url)>(?,?) '
            'ORDER BY provider,source_url LIMIT ?', ('a', 'b', 5)) for part in row)
        self.assertIn('COVERING INDEX sqlite_autoindex_catalog_titles_2', plan)
        self.assertNotIn('TEMP B-TREE', plan)


class Background(Fixture):
    def test_the_new_source_joins_both_sets_and_the_veto_holds(self):
        self.new_rules()
        self.restart()
        old_manga, old_video = self.before
        manga_after, video_after = self.derived()
        self.assertIn('tube 1', manga_after)
        self.assertNotIn('tube vetoed', manga_after)
        self.assertIn('Tube video 1', video_after)
        self.assertNotIn('Tube video vetoed', video_after)
        self.assertNotIn('Tube video 1', old_video)

        def between():
            # Never empty, never more than the old and new sets.
            manga, video = self.manga(), self.video()
            self.assertTrue(set(old_manga) & set(manga_after) <= set(manga) <= set(old_manga) | set(manga_after))
            self.assertTrue(set(old_video) & set(video_after) <= set(video) <= set(old_video) | set(video_after))

        with patch.object(hentai_works, 'SCAN', 5), patch.object(hentai_works, 'PORTION', 4), patch.object(content_works, 'PORTION', 4):
            self.settle(between)
        self.assertTrue(hentai_works.current(self.db))
        self.assertTrue(content_works.hentai_current(self.db))
        self.assertEqual((self.manga(), self.video()), (manga_after, video_after))
        self.assertEqual(self.derived(), (manga_after, video_after))

    def test_a_restart_in_the_middle_continues(self):
        self.new_rules()
        self.restart()
        expected = self.derived()
        with patch.object(hentai_works, 'SCAN', 4), patch.object(hentai_works, 'PORTION', 3), patch.object(content_works, 'PORTION', 3):
            while hentai_works._state(self.db).get('phase') != 'origin' or not hentai_works._state(self.db).get('cursor'):
                self.assertTrue(hentai_works.step(self.store))
            hentai_works.step(self.store)
            state = hentai_works._state(self.db)
            self.restart()
            self.assertEqual(hentai_works._state(self.db), state, 'the cursor survives a restart')
            while hentai_works.step(self.store):
                pass
            for _ in range(3):
                self.assertTrue(content_works.step(self.store))
            cursor = content_works._state(self.db)['cursor']
            self.assertGreater(cursor, 0)
            self.restart()
            self.assertEqual(content_works._state(self.db)['cursor'], cursor)
            self.settle()
        self.assertEqual((self.manga(), self.video()), expected)


class LegacyIndexes(Fixture):
    LEGACY = '266db1371a08'

    def setUp(self):
        super().setUp()
        # The indexes of the release before C3, as they are on the VM.
        for prefix, table, expression in (
                ('catalog_hentai_origin_', 'catalog_titles', "catalog_hentai_origin(provider,source_url,'manga')"),
                ('content_hentai_origin_', 'content_titles', catalog_taxonomy.origin_sql('t').replace('t.', '')),
                ('catalog_hentai_veto_', 'catalog_tag_facts', 'catalog_not_hentai(original),title_id'),
                ('content_hentai_veto_', 'content_tag_facts', 'catalog_not_hentai(original),title_id')):
            for (name,) in self.db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE ?", (prefix + '%',)).fetchall():
                self.db.execute('DROP INDEX "' + name + '"')
            self.db.execute('CREATE INDEX ' + prefix + self.LEGACY + ' ON ' + table + '(' + expression + ')')
        self.db.commit()

    def names(self):
        return sorted(name for (name,) in self.db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE '%hentai%'"))

    def test_kept_through_the_deploy_and_origin_ones_retired_later(self):
        legacy = self.names()
        self.new_rules()
        self.restart()
        self.assertEqual(self.names(), legacy)
        self.assertEqual(catalog_taxonomy.veto_index(self.db, True), 'catalog_hentai_veto_' + self.LEGACY)
        self.assertEqual(catalog_taxonomy.veto_index(self.db), 'content_hentai_veto_' + self.LEGACY)
        self.settle()
        self.assertEqual(self.names(), legacy, 'the rollback target still has its indexes right after the deploy')
        with patch.object(hentai_works, 'RETIRE_AFTER', 0), patch.object(content_works, 'RETIRE_AFTER', 0):
            self.settle()
        self.assertEqual(self.names(), ['catalog_hentai_veto_' + self.LEGACY, 'content_hentai_veto_' + self.LEGACY])
        self.assertEqual(self.derived(), (self.manga(), self.video()))

    def test_a_veto_index_for_other_labels_is_not_read(self):
        with patch.object(catalog_taxonomy, 'HENTAI_NEGATIVE', {'другое'}):
            self.assertIsNone(catalog_taxonomy.veto_index(self.db, True))
            sql, _ = content_works.aggregate_sql(self.db, '1', many=True)
            self.assertIn('EXISTS(SELECT 1 FROM content_tag_facts f WHERE f.title_id=t.id', sql)
            with self.db:
                while catalog_taxonomy.retire_indexes(self.db) or catalog_taxonomy.retire_indexes(self.db, True):
                    pass
        self.assertEqual(self.names(), [])


if __name__ == '__main__':
    unittest.main()
