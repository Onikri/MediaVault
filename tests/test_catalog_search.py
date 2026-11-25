"""Full-text title search (FTS5 trigram) and the index paths of catalogue filters.

Offline fixtures only; no network and no real catalogue. Every new path is
compared with the previous one (LIKE scan, IN-set grouping) on the same rows."""
import os, sqlite3, sys, tempfile, threading, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import catalog_search, catalog_taxonomy, catalogue_indexer, manga_catalog_index, tag_merge
from manga_catalog_index import browse, initialize, upsert
from manga_tag_policy import canonical_json

POLICY = {'schemaVersion': 1, 'includeDiscovered': True, 'hiddenTags': [], 'excludedTerms': [], 'excludedPrefixes': [], 'tags': []}
QUERIES = ['naruto', 'НАРУТО', 'наруто', 'ван пис', 'one piece', 'ежик', 'ёжик', 'Ёлки', 'berserk', 'BERSERK', 'shippuden',
           'нару', 'uto', 'xyzqwv', 'хроники', 'alpha', 'ван', 'пис', 'сезон', 'сезон 2', 'on', 'на', 'ナルト', 'ruto next']


class Fixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / 'manga-tag-policy.json').write_bytes(canonical_json(POLICY))
        self.env = patch.dict(os.environ, {'DATA_DIR': self.temp.name, 'MANGA_TAG_POLICY_FILE': str(root / 'manga-tag-policy.json')})
        self.env.start()
        patch.object(tag_merge, 'PAUSE', 0).start()
        manga_catalog_index._totals.clear(); manga_catalog_index._slow.clear()
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        initialize(self.db)
        self.store = SimpleNamespace(db=self.db, lock=threading.RLock())
        upsert(self.db, self.rows())
        self.db.commit()

    def tearDown(self):
        patch.stopall()
        self.db.close()
        self.env.stop()
        self.temp.cleanup()

    @staticmethod
    def row(name, title, aliases=(), year=2000, host='fixture.example', tags=(), genres=(), chapters=3, language='ru'):
        return {'provider': host.split('.')[0], 'kind': 'manga', 'title': title, 'aliases': list(aliases), 'year': year,
                'language': language, 'sourceUrl': 'https://' + host + '/manga/' + name, 'tags': list(tags),
                'genres': list(genres), 'episodes': [{'number': n} for n in range(chapters)]}

    def rows(self):
        r = self.row
        rows = [
            r('n1', 'Naruto', ['Наруто'], 1999, genres=['Романтика']),
            r('n2', 'Naruto', [], 2001, host='mirror.example', language='en'),
            r('n3', 'Наруто', ['Naruto', 'ナルト'], 2002, tags=['Школа']),
            r('n4', 'Naruto Shippuden', ['Наруто: Ураганные хроники'], 2007, genres=['Романтика'], tags=['Школа']),
            r('n5', 'Сакура и Чараске', ['Naruto'], 2015, genres=['Хентай']),
            r('n6', 'Boruto', ['Boruto: Naruto Next Generations'], 2016, tags=['Большая грудь']),
            r('o1', 'Ван Пис', ['One Piece'], 1997, genres=['Романтика'], tags=['Школа']),
            r('o2', 'One piece of cake', [], 2010, genres=['Романтика']),
            r('o3', 'Ван-Пис: фильм', [], None, tags=['Школа'], chapters=0),
            r('e1', 'Ёжик в тумане', [], 1975),
            r('e2', 'ЁЛКИ', ['Елки 2'], 2011, genres=['Романтика']),
            r('b1', 'BERSERK', ['Берсерк'], 1989, tags=['Большая грудь']),
            # One work, two sources: «ван» and «пис» never meet in one row.
            r('a1', 'Alpha', ['Ван'], 2005, genres=['Романтика']),
            r('a2', 'Alpha', ['Пис'], 2006, host='mirror.example', tags=['Школа']),
            r('s1', 'Сезон 2', [], 2020, genres=['Романтика'], tags=['Школа']),
            r('s2', 'Сезон', ['Season'], 2021),
        ]
        rows += [r('f%d' % n, 'Filler %d naruto' % n if n % 3 == 0 else 'Filler %d' % n, [], 1980 + n % 40,
                   genres=['Романтика'] if n % 2 else [], tags=['Школа'] if n % 5 == 0 else []) for n in range(40)]
        return rows

    def old(self, **kwargs):
        with patch.object(catalog_search, 'ready', return_value=False), \
                patch.object(catalog_taxonomy, 'work_filters', return_value=None):
            return browse(self.db, **kwargs)

    @staticmethod
    def keys(result):
        return [row['workKey'] for row in result['items']]

    def same(self, **kwargs):
        new, old = browse(self.db, **kwargs), self.old(**kwargs)
        self.assertEqual(self.keys(new), self.keys(old))
        self.assertEqual((new['total'], new['workTotal'], new['works']), (old['total'], old['workTotal'], old['works']))
        self.assertEqual(new.get('totalExact', True), old.get('totalExact', True))
        self.assertEqual([row['catalogId'] for row in new['items']], [row['catalogId'] for row in old['items']])
        return new


class SearchTests(Fixture, unittest.TestCase):
    def test_document_lists_names_and_keeps_older_text(self):
        data = {'title': 'Наруто', 'aliases': ['Наруто', 'Naruto', 'ナルト']}
        self.assertEqual(catalog_search.document('Наруто', data, 'наруто наруто naruto ナルト'), '|наруто|naruto|ナルト|')
        self.assertEqual(catalog_search.document('X', {'title': 'X'}, 'older text'), '|older text|')
        long = ['a%04d word' % n for n in range(600)]
        text = manga_catalog_index.normalize(' '.join(['T', 'T', *long]))[:5000]
        names = catalog_search.document('T', {'title': 'T', 'aliases': long}, text).strip('|').split('|')
        # Cut where search_text is cut: the same words, the last one partly.
        self.assertEqual(set(' '.join(names).split()), set(text.split()))
        self.assertTrue(text.rstrip().endswith(names[-1]))

    def test_index_is_complete_for_a_new_catalogue_and_answers_like_the_scan(self):
        self.assertTrue(catalog_search.ready(self.db))
        for q in QUERIES:
            for sort in ('', 'old', 'title', 'length', 'added'):
                for offset in (0, 2):
                    with self.subTest(q=q, sort=sort, offset=offset):
                        self.same(q=q, sort=sort, offset=offset, limit=3)
        for q in ('naruto', 'ван пис', 'ежик'):
            for args in ({'genre': 'Романтика'}, {'tag': 'Школа'}, {'excludeTag': 'Школа'}, {'genre': 'Хентай'},
                         {'excludeGenre': 'Хентай'}, {'status': 'available'}, {'language': 'en'}, {'year': '2002'}):
                with self.subTest(q=q, **args):
                    self.same(q=q, limit=4, **args)
        self.assertEqual(self.keys(browse(self.db, q='naruto', limit=3))[:3], ['сакура и чараске', 'наруто', 'naruto'])
        self.assertNotIn('alpha', self.keys(browse(self.db, q='ван пис', limit=50)))
        self.assertEqual(set(self.keys(browse(self.db, q='ёжик'))), {'ежик в тумане'})
        self.assertEqual(set(self.keys(browse(self.db, q='ежик'))), {'ежик в тумане'})

    def test_search_reads_the_index_not_the_catalogue(self):
        hits = 't.rowid IN (SELECT rowid FROM catalog_search WHERE catalog_search MATCH ?)'
        plan = ' '.join(str(part) for row in self.db.execute(
            'EXPLAIN QUERY PLAN SELECT t.work_key FROM catalog_search_rows t WHERE ' + hits + ' GROUP BY t.work_key', ['"naruto"'])
            for part in row)
        self.assertIn('VIRTUAL TABLE', plan)
        self.assertNotIn('catalog_titles', plan.replace('catalog_titles_', ''))
        self.assertNotIn('SCAN t', plan)

    def test_written_titles_are_found_at_once_and_retired_ones_disappear(self):
        upsert(self.db, [self.row('new', 'Новинка недели', ['Weekly Novelty'], 2024)])
        self.assertEqual(self.keys(browse(self.db, q='novelty')), ['новинка недели'])
        # A changed alias replaces the old document.
        upsert(self.db, [self.row('new', 'Новинка недели', ['Monthly Novelty'], 2024)])
        self.assertEqual(self.keys(browse(self.db, q='monthly')), ['новинка недели'])
        self.assertEqual(self.keys(browse(self.db, q='weekly')), self.keys(self.old(q='weekly')))
        catalog_search.forget(self.db, [identity for (identity,) in self.db.execute("SELECT id FROM catalog_titles WHERE title='Новинка недели'")])
        self.db.execute("DELETE FROM catalog_titles WHERE title='Новинка недели'")
        self.assertEqual(self.keys(browse(self.db, q='novelty')), [])
        self.db.execute("INSERT INTO catalog_search(catalog_search) VALUES('integrity-check')")

    def test_retired_sites_leave_the_index(self):
        import manga_source_coverage
        domain = 'retired.example'
        upsert(self.db, [self.row('gone', 'Ушедший сайт', [], 2020, host=domain)])
        self.assertEqual(self.keys(browse(self.db, q='ушедший')), ['ушедший сайт'])
        with patch.object(manga_source_coverage, 'REMOVED_DOMAINS', (domain,)):
            catalogue_indexer.retire_removed(self.db)
        self.assertEqual(self.keys(browse(self.db, q='ушедший')), [])
        self.assertFalse(self.db.execute('SELECT 1 FROM catalog_search_rows r WHERE NOT EXISTS(SELECT 1 FROM catalog_titles t WHERE t.rowid=r.id)').fetchone())

    def test_background_fill_resumes_after_a_restart_and_keeps_writes(self):
        self.db.execute("DELETE FROM catalog_policy_state WHERE name='search-index'")
        catalog_search.initialize(self.db)
        self.assertFalse(catalog_search.ready(self.db))
        self.same(q='naruto', limit=5)                     # LIKE path until the fill is done
        with patch.object(catalog_search, 'PORTION', 7):
            for _ in range(3):
                self.assertTrue(catalog_search.step(self.store))
            cursor = catalog_search._state(self.db)['cursor']
            self.assertTrue(0 < cursor < catalog_search._state(self.db)['end'])
            # Writes below the cursor, above it, and a brand-new row.
            low = self.db.execute('SELECT title FROM catalog_titles WHERE rowid<=? ORDER BY rowid LIMIT 1', (cursor,)).fetchone()[0]
            high = self.db.execute('SELECT title FROM catalog_titles WHERE rowid>? ORDER BY rowid DESC LIMIT 1', (cursor,)).fetchone()[0]
            self.assertEqual((low, high), ('Naruto', 'Filler 39 naruto'))
            upsert(self.db, [self.row('n1', 'Naruto', ['Наруто', 'Lowwrite'], 1999, genres=['Романтика']),
                             self.row('f39', 'Filler 39 naruto', ['Highwrite'], 2019, genres=['Романтика']),
                             self.row('late', 'Поздний тайтл', ['Latewrite'], 2023)])
            # A restart keeps only the state row.
            restarted = SimpleNamespace(db=self.db, lock=threading.RLock())
            while tag_merge.step(restarted, pause=0):
                pass
        self.assertTrue(catalog_search.ready(self.db))
        self.db.execute("INSERT INTO catalog_search(catalog_search) VALUES('integrity-check')")
        for q in [*QUERIES, 'lowwrite', 'highwrite', 'latewrite']:
            with self.subTest(q=q):
                self.same(q=q, limit=6)
        self.assertEqual(self.keys(browse(self.db, q='lowwrite')), ['naruto'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM catalog_search_rows').fetchone(), self.db.execute('SELECT COUNT(*) FROM catalog_titles').fetchone())

    def test_rows_written_without_the_index_are_caught_up_at_start(self):
        # An older image inserts rows without maintaining the index.
        with patch.object(catalog_search, 'update', lambda conn, changes: None):
            upsert(self.db, [self.row('old-image', 'Старый образ', ['Rollback'], 2022)])
        self.assertEqual(self.keys(browse(self.db, q='rollback')), [])
        initialize(self.db)
        self.assertFalse(catalog_search.ready(self.db))
        while catalog_search.step(self.store):
            pass
        self.assertEqual(self.keys(browse(self.db, q='rollback')), ['старый образ'])
        self.db.execute("INSERT INTO catalog_search(catalog_search) VALUES('integrity-check')")

    def test_many_hits_page_the_default_order_with_exact_names_first(self):
        old = self.old(q='naruto', limit=4)
        with patch.object(manga_catalog_index, 'HIT_LIMIT', 1):
            first = browse(self.db, q='naruto', limit=4)
            second = browse(self.db, q='naruto', limit=4, offset=4)
            available = browse(self.db, q='naruto', limit=4, status='available')
        self.assertEqual(self.keys(first), self.keys(old))
        self.assertEqual(self.keys(second), self.keys(self.old(q='naruto', limit=4, offset=4)))
        self.assertEqual(self.keys(available), self.keys(self.old(q='naruto', limit=4, status='available')))
        # The total is exact at once on an in-memory catalogue (no second connection).
        self.assertEqual((first['total'], first['workTotal']), (old['total'], old['workTotal']))


    def test_new_paths_are_taken(self):
        index = manga_catalog_index
        with patch.object(index, '_search', wraps=index._search) as search, patch.object(index, '_stream', wraps=index._stream) as stream:
            browse(self.db, q='naruto')
            self.assertEqual((search.call_count, stream.call_count), (1, 0))
            browse(self.db, q='сезон 2')                     # a short word: the substring scan
            self.assertEqual(search.call_count, 1)
            with patch.object(index, 'HIT_LIMIT', 1):
                browse(self.db, q='naruto')
            self.assertEqual((search.call_count, stream.call_count), (2, 1))
            browse(self.db, genre='Романтика', tag='Школа')
            browse(self.db, offset=30)
            self.assertEqual(stream.call_count, 3)
            browse(self.db, genre='Романтика', sort='old')
            self.assertEqual(stream.call_count, 3)


class FilterTests(Fixture, unittest.TestCase):
    CASES = [{'genre': 'Романтика'}, {'tag': 'Школа'}, {'genre': 'Романтика', 'tag': 'Школа'}, {'excludeTag': 'Школа'},
             {'genre': 'Романтика', 'excludeTag': 'Школа'}, {'tag': 'Школа,Большая грудь'}, {'tag': '["Школа","Большая грудь"]'},
             {'genre': 'Хентай'}, {'excludeGenre': 'Хентай'}, {'genre': 'Хентай,Романтика'}, {'tag': 'Нет такого'},
             {'excludeTag': 'Нет такого'}, {'genre': 'Романтика', 'excludeGenre': 'Хентай', 'tag': 'Школа'}, {}]

    def test_index_paths_match_the_grouped_sets(self):
        for args in self.CASES:
            for sort in ('', 'new', 'old', 'title', 'length', 'added'):
                for status in ('', 'available'):
                    for offset in (0, 3, 9):
                        with self.subTest(sort=sort, status=status, offset=offset, **args):
                            self.same(sort=sort, status=status, offset=offset, limit=4, **args)
            with self.subTest(language='en', **args):
                self.same(language='en', limit=4, **args)

    def test_exclusion_removes_every_edition_of_a_work(self):
        keys = self.keys(browse(self.db, excludeTag='Школа', limit=100))
        self.assertNotIn('alpha', keys)              # one edition is tagged
        self.assertNotIn('ван пис', keys)
        self.assertIn('ежик в тумане', keys)
        self.assertEqual(set(self.keys(browse(self.db, tag='Школа', genre='Романтика', limit=100))) & {'alpha', 'ван пис', 'сезон 2'},
                         {'alpha', 'ван пис', 'сезон 2'})

    def test_streams_read_the_newest_index_with_primary_key_probes(self):
        groups = catalog_taxonomy.work_filters(self.db, genre='Романтика', tag='Школа')
        conditions, values = manga_catalog_index._flatten([g['exists'] for g in groups])
        plan = ' '.join(str(part) for row in self.db.execute(
            'EXPLAIN QUERY PLAN SELECT t.work_key FROM catalog_titles t INDEXED BY catalog_titles_newest WHERE ' + ' AND '.join(conditions) +
            ' ORDER BY (t.year IS NULL),t.year DESC,t.work_key', values) for part in row)
        self.assertNotIn('TEMP B-TREE', plan)
        self.assertIn('SEARCH x USING PRIMARY KEY', plan)
        # Grouping drives from the smaller set and probes the larger one.
        within = manga_catalog_index._within(groups)
        self.assertTrue(within[0][0].startswith('EXISTS'))
        self.assertTrue(within[1][0].startswith('t.work_key IN'))

    def test_single_tag_totals_come_from_tag_stats(self):
        stats = self.db.execute("SELECT works FROM catalog_tag_stats WHERE category='tags' AND tag_key='школа'").fetchone()[0]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.sqlite'
            disk = sqlite3.connect(path)
            self.db.backup(disk)
            disk.close()
            reader = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, check_same_thread=False)
            from catalog_taxonomy import register_origin_functions
            register_origin_functions(reader)
            try:
                with patch.object(manga_catalog_index, 'TOTAL_BUDGET', -1), patch.object(manga_catalog_index, 'TOTAL_STEPS', 1):
                    first = browse(reader, tag='Школа', limit=2)
                    for thread in threading.enumerate():
                        if thread.name == 'catalog-total':
                            thread.join(10)
                    second = browse(reader, tag='Школа', limit=2)
                    combined = browse(reader, tag='Школа', genre='Романтика', limit=2)
                    searched = browse(reader, q='naruto', limit=2)
            finally:
                for thread in threading.enumerate():
                    if thread.name == 'catalog-total':
                        thread.join(10)
                reader.close()
                manga_catalog_index._totals.clear(); manga_catalog_index._slow.clear()
        self.assertIs(first['totalExact'], False)
        self.assertEqual(first['workTotal'], stats)
        self.assertNotIn('totalExact', second)
        self.assertEqual(second['workTotal'], stats)
        self.assertGreater(second['total'], stats)        # source rows, counted in the background
        self.assertIs(combined['totalExact'], False)      # no exact count for a combination yet
        self.assertEqual(combined['workTotal'], 3)
        self.assertNotIn('totalExact', searched)          # a search counts its hits exactly


if __name__ == '__main__':
    unittest.main()
