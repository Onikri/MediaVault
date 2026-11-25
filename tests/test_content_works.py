"""content_works: materialized works answer content_catalog.browse exactly as
the grouped query over content_titles did (offline, temporary SQLite)."""
import json, os, random, sqlite3, sys, tempfile, threading, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import content_catalog
import content_works
import manga_catalog_index
from catalog_taxonomy import HENTAI

KINDS = content_works.KINDS
NOT_HENTAI = HENTAI['excludeLabels'][0]


def rows(seed=7, works=45):
    rng = random.Random(seed)
    now = int(time.time())
    result = []
    for kind in KINDS:
        for number in range(works):
            ids = rng.choice([{}, {'mal': str(number % 31)}, {'imdb': 'tt%d' % (number % 23)}])
            for copy in range(rng.choice([1, 1, 1, 2, 3])):
                provider = rng.choice(['fixture', 'other', 'hanime' if kind == 'anime' else 'third'])
                row = {'id': '%s-%d-%d' % (kind, number, copy), 'provider': provider, 'kind': kind,
                       'title': rng.choice(['Alpha', 'Beta', 'Gamma', 'Дельта']) + ' %d' % (number % 9), 'ids': ids,
                       'year': rng.choice([None, None, 1999, 2010, 2024, int(time.strftime('%Y')), 2099]),
                       'status': rng.choice(['', '', 'released', 'ongoing', 'anons', 'FINISHED', 'RELEASING', 'NOT_YET_RELEASED']),
                       'genres': rng.sample(['Fantasy', 'Comedy', 'Drama', 'Хентай', NOT_HENTAI], rng.choice([0, 1, 2])),
                       'tags': rng.sample(['Robots', 'Dragons', 'School'], rng.choice([0, 1, 2]))}
                for field, values in (('score', [None, 7, 7.5, 8, 9.1]), ('popularity', [None, 10, 10, 500, 90000]),
                                      ('startDate', [None, '2001-02-03', '2099-01-01', time.strftime('%Y-%m'), '2020']),
                                      ('firstAiringAt', [None, now - 86400, now + 86400]), ('episodesAired', [None, 0, 3])):
                    if (value := rng.choice(values)) is not None:
                        row[field] = value
                if rng.random() < .3:
                    row['trending'] = rng.choice([0, 5, 40, 40])
                    row['trendingAt'] = rng.choice([now - 60, now - 9000])
                result.append(row)
    return result


def join():
    for thread in threading.enumerate():
        if thread.name == 'catalog-total':
            thread.join(10)


def ingest(db, values):
    for start in range(0, len(values), 100):
        content_catalog.ingest(db, values[start:start + 100])
    db.commit()


FILTERS = [{}, {'genre': 'Fantasy'}, {'tag': 'Robots'}, {'excludeGenre': 'Comedy'}, {'genre': 'Хентай'},
           {'excludeGenre': 'Хентай'}, {'genre': 'Fantasy,Хентай'}, {'genre': 'Drama', 'tag': 'Robots,Dragons'},
           {'excludeTag': 'School', 'genre': 'Comedy'}, {'tag': 'Nothing at all'}]
STATUSES = ['', 'available', 'released', 'ongoing', 'anons']
SORTS = ['trending', 'score', 'new', 'old', 'title', 'updated', 'unknown']


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        policy = Path(self.tmp.name) / 'policy.json'
        policy.write_text(json.dumps({'schemaVersion': 1, 'tags': [], 'includeDiscovered': True, 'excludedTerms': [],
                                      'excludedPrefixes': [], 'hiddenTags': []}), encoding='utf-8')
        self.env = patch.dict(os.environ, {'MANGA_TAG_POLICY_FILE': str(policy)})
        self.env.start()
        self.path = Path(self.tmp.name) / 'catalogue.sqlite'
        self.db = self.open()

    def open(self):
        db = sqlite3.connect(self.path, timeout=5)
        content_catalog.initialize(db)
        db.commit()
        return db

    def tearDown(self):
        for thread in threading.enumerate():
            if thread.name == 'catalog-total':
                thread.join(10)
        self.db.close()
        self.env.stop()
        self.tmp.cleanup()

    def old(self, **args):
        with patch.object(content_works, 'ready', lambda conn: False):
            return content_catalog.browse(self.db, prepared=True, **args)

    def new(self, **args):
        self.assertTrue(content_works.ready(self.db))
        return content_catalog.browse(self.db, prepared=True, **args)

    def same(self, **args):
        old, new = self.old(**args), self.new(**args)
        if not set(args) & {'q', 'year', 'format', 'age'}:
            # The materialized path answered (no fallback to the grouped query).
            self.assertIsNotNone(content_works.page(self.db, **args))
        label = json.dumps(args, ensure_ascii=False)
        self.assertEqual([item['workKey'] for item in new['items']], [item['workKey'] for item in old['items']], label)
        self.assertEqual(new['items'], old['items'], label)
        if new.get('totalExact', True) is False:
            # A lower bound until the background count lands.
            self.assertLessEqual(new['total'], old['total'], label)
            join()
            new = self.new(**args)
        self.assertEqual((new['total'], new.get('totalExact', True)), (old['total'], True), label)


class Equivalence(Base):
    def setUp(self):
        super().setUp()
        ingest(self.db, rows())
        self.assertTrue(content_works.hentai_ready(self.db))

    def test_key_and_aggregates_equal_the_grouped_expressions(self):
        work = content_catalog.work_sql('t')
        kinds = ','.join("'" + kind + "'" for kind in KINDS)
        expected = {tuple(row) for row in self.db.execute(
            'SELECT ' + work + ',t.kind,MAX(t.updated),' + content_catalog.RELEASE_YEAR + ",MIN(t.search),"
            "MAX(CAST(json_extract(t.raw,'$.score') AS REAL)),MAX(CAST(json_extract(t.raw,'$.popularity') AS INTEGER)) "
            'FROM content_titles t WHERE t.kind IN (' + kinds + ') GROUP BY ' + work)}
        stored = {tuple(row) for row in self.db.execute('SELECT work_key,kind,updated,year,search,score,popularity FROM content_works')}
        self.assertEqual(stored, expected)
        self.assertGreater(len(stored), 100)
        counted = dict(self.db.execute('SELECT kind,SUM(works) FROM content_work_stats GROUP BY kind').fetchall())
        self.assertEqual(counted, dict(self.db.execute('SELECT kind,COUNT(*) FROM content_works GROUP BY kind').fetchall()))
        # Index-read sets and row probes give the same hentai flags.
        kinds_only = 't.kind IN (' + kinds + ')'
        both = [sorted(tuple(row) for row in self.db.execute(sql, args))
                for sql, args in (content_works.aggregate_sql(self.db, kinds_only, many=many) for many in (True, False))]
        self.assertEqual(both[0], both[1])
        self.assertEqual(both[0], sorted(tuple(row) for row in self.db.execute('SELECT * FROM content_works')))
        # The flags take every value in this fixture.
        self.assertEqual({row[0] for row in self.db.execute('SELECT DISTINCT avail FROM content_works')}, {0, 1, 2})
        self.assertEqual({row[0] for row in self.db.execute('SELECT DISTINCT hentai FROM content_works')}, {0, 1})

    def test_first_pages_match_the_old_path_for_every_kind_sort_status_and_filter(self):
        for kind in KINDS:
            for sort in SORTS:
                for status in STATUSES:
                    for filters in FILTERS if sort in ('trending', 'new') else FILTERS[:4]:
                        for offset in (0, 7):
                            self.same(kind=kind, sort=sort, status=status, limit=7, offset=offset, **filters)

    def test_deep_pages_and_both_tag_plans(self):
        for scan in (0, 10 ** 9):
            with patch.object(content_works, 'STREAM_SCAN', scan):
                for kind in ('anime', 'movie'):
                    for sort in ('trending', 'old', 'title'):
                        for offset in (0, 5, 30, 60, 500):
                            self.same(kind=kind, sort=sort, limit=5, offset=offset, tag='Robots')
                            self.same(kind=kind, sort=sort, limit=5, offset=offset, genre='Drama', status='available')

    def test_trending_with_values_below_zero_or_missing(self):
        # Rows written before trending was bounded: a fresh time without a
        # value (NULL) and a negative value sort after every 0.
        keys = []
        for value in ("json_remove(raw,'$.trending')", "json_set(raw,'$.trending',-3)"):
            identity, key = self.db.execute('SELECT id,' + content_catalog.work_sql('') + " FROM content_titles WHERE kind='anime' AND json_extract(raw,'$.trending')>0 "
                                            'AND ' + content_catalog.work_sql('') + ' NOT IN (' + ','.join('?' * len(keys)) + ') LIMIT 1', keys).fetchone()
            self.db.execute("UPDATE content_titles SET raw=json_set(" + value + ",'$.trendingAt',unixepoch()) WHERE " + content_catalog.work_sql('') + '=?', (key,))
            keys.append(key)
        content_works.refresh(self.db, keys)
        self.db.commit()
        total = self.new(kind='anime')['total']
        for offset in (0, 10, total - 6, total - 2):
            self.same(kind='anime', sort='trending', limit=5, offset=max(0, offset))
            self.same(kind='anime', sort='trending', limit=5, offset=max(0, offset), genre='Fantasy')

    def test_search_and_row_filters_keep_the_grouped_query_with_the_available_flag(self):
        for args in ({'q': 'alpha'}, {'q': 'дельта', 'status': 'available'}, {'q': 'beta', 'status': 'available', 'genre': 'Fantasy'},
                     {'year': '2010', 'status': 'available'}):
            for kind in KINDS:
                self.same(kind=kind, sort='trending', limit=10, **args)

    def test_page_hydration_equals_one_work_at_a_time(self):
        from manga_tag_policy import current
        keys = [row[0] for row in self.db.execute('SELECT work_key FROM content_works ORDER BY work_key LIMIT 80')]
        self.assertEqual(content_catalog.read_works(self.db, keys, current()), [content_catalog.read_work(self.db, key, current()) for key in keys])


class Maintenance(Base):
    def test_a_new_record_is_visible_at_once_and_counts(self):
        ingest(self.db, rows(works=10))
        before = self.new(kind='movie', sort='updated', limit=3)
        content_catalog.ingest(self.db, [{'id': 'fresh', 'provider': 'fixture', 'kind': 'movie', 'title': 'Brand New', 'year': 2001, 'genres': ['Fantasy']}])
        self.db.commit()
        after = self.new(kind='movie', sort='updated', limit=3)
        self.assertEqual(after['items'][0]['title'], 'Brand New')
        self.assertEqual(after['total'], before['total'] + 1)
        self.assertEqual(self.new(kind='movie', sort='updated', limit=3, status='available')['items'][0]['title'], 'Brand New')
        # A second provider joins the work; an unchanged row moves it up again.
        content_catalog.ingest(self.db, [{'id': 'old-1', 'provider': 'other', 'kind': 'movie', 'title': 'Older', 'ids': {'imdb': 'tt900'}, 'year': 1990}])
        content_catalog.ingest(self.db, [{'id': 'old-2', 'provider': 'third', 'kind': 'movie', 'title': 'Older too', 'ids': {'imdb': 'tt900'}, 'year': 1995}])
        self.db.execute('UPDATE content_titles SET updated=updated-100')
        self.db.execute('UPDATE content_works SET updated=updated-100')
        content_catalog.ingest(self.db, [{'id': 'old-1', 'provider': 'other', 'kind': 'movie', 'title': 'Older', 'ids': {'imdb': 'tt900'}, 'year': 1990}])
        self.db.commit()
        top = self.new(kind='movie', sort='updated', limit=1)['items'][0]
        self.assertEqual((top['workKey'], top['providerCount'], top['year']), ('movie:imdb:tt900', 2, 1990))
        self.assertEqual(self.db.execute("SELECT year FROM content_works WHERE work_key='movie:imdb:tt900'").fetchone()[0], 1995)
        for sort in SORTS:
            self.same(kind='movie', sort=sort, limit=4)

    def test_fill_resumes_after_an_interruption_and_keeps_the_old_path_meanwhile(self):
        values = rows(seed=3, works=20)
        ingest(self.db, values)
        expected = sorted(tuple(row) for row in self.db.execute('SELECT * FROM content_works'))
        # The catalogue as it was before this module.
        self.db.execute('DROP TABLE content_works')
        self.db.execute('DROP TABLE content_work_stats')
        self.db.execute("DELETE FROM content_catalog_state WHERE name='content-works'")
        content_catalog.initialize(self.db)
        self.db.commit()
        self.assertFalse(content_works.ready(self.db))
        store = SimpleNamespace(lock=threading.RLock(), db=self.db)
        with patch.object(content_works, 'PORTION', 9):
            self.assertTrue(content_works.step(store))
            self.assertTrue(content_works.step(store))
            cursor = content_works.progress(self.db)['cursor']
            self.assertGreater(cursor, 0)
            # Pages are served by the grouped query until the fill completes.
            old = content_catalog.browse(self.db, kind='anime', sort='trending', status='available', limit=5, prepared=True)
            self.assertNotIn('totalExact', old)
            # A write during the fill: a changed row of a visited work and a new one.
            content_catalog.ingest(self.db, [{**values[0], 'popularity': 123456789}, {'id': 'late', 'provider': 'fixture', 'kind': 'tv', 'title': 'Late'}])
            self.db.commit()
            self.db.close()
            self.db = self.open()
            self.assertEqual(content_works.progress(self.db)['cursor'], cursor)
            store.db = self.db
            steps = 0
            while content_works.step(store):
                steps += 1
            self.assertGreater(steps, 3)
        state = content_works.progress(self.db)
        self.assertTrue(state['ready'] and state['hentaiReady'])
        self.assertGreaterEqual(state['rows'], len(values))
        stored = sorted(tuple(row) for row in self.db.execute('SELECT * FROM content_works'))
        self.assertEqual(len(stored), len(expected) + 1)
        keys = [row[0] for row in stored]
        fresh = sorted(content_works._aggregate(self.db, keys))
        self.assertEqual(stored, fresh)
        self.assertIn('Late', [item['title'] for item in self.new(kind='tv', sort='updated', limit=100)['items']])
        for kind in KINDS:
            self.same(kind=kind, sort='trending', status='available', limit=6)

    def test_rows_written_without_this_module_are_filled_before_serving(self):
        ingest(self.db, rows(works=5))
        self.db.execute("INSERT INTO content_titles VALUES('legacy','anime','legacy',?,?)",
                        (json.dumps({'id': 'legacy', 'kind': 'anime', 'provider': 'old', 'title': 'Legacy', 'year': 2000}), int(time.time()) + 5))
        content_catalog.initialize(self.db)
        self.assertFalse(content_works.ready(self.db))
        store = SimpleNamespace(lock=threading.RLock(), db=self.db)
        while content_works.step(store):
            pass
        self.assertEqual(self.new(kind='anime', sort='updated', limit=1)['items'][0]['title'], 'Legacy')

    def test_a_full_reindex_refills_only_the_hentai_flag(self):
        ingest(self.db, rows(works=8))
        content_catalog.reindex(self.db, __import__('manga_tag_policy').current())
        self.assertTrue(content_works.ready(self.db))
        self.assertFalse(content_works.hentai_current(self.db))
        # Every filter, «Хентай» too (the previous flags), stays on the
        # materialized path meanwhile.
        self.assertTrue(content_works.hentai_ready(self.db))
        self.assertIsNotNone(content_works.page(self.db, kind='anime', genre='Fantasy'))
        self.assertIsNotNone(content_works.page(self.db, kind='anime', genre='Хентай'))
        store = SimpleNamespace(lock=threading.RLock(), db=self.db)
        while content_works.step(store):
            pass
        self.assertTrue(content_works.hentai_current(self.db))
        self.same(kind='anime', genre='Хентай', sort='trending', limit=5)


class Totals(Base):
    def test_counters_answer_plain_pages_and_a_single_tag_exactly(self):
        ingest(self.db, rows())
        with patch.object(manga_catalog_index, '_total', side_effect=AssertionError('counted')):
            for kind in KINDS:
                self.assertEqual(self.new(kind=kind)['total'], self.old(kind=kind)['total'])
                self.assertEqual(self.new(kind=kind, genre='Хентай')['total'], self.old(kind=kind, genre='Хентай')['total'])
                self.assertEqual(self.new(kind=kind, tag='Robots')['total'], self.old(kind=kind, tag='Robots')['total'])

    def test_slow_counts_report_a_lower_bound_then_the_exact_total(self):
        ingest(self.db, rows())
        args = {'kind': 'anime', 'sort': 'trending', 'status': 'available', 'limit': 5}
        exact = self.old(**args)['total']
        self.assertTrue(self.db.execute("SELECT works FROM content_work_stats WHERE kind='anime' AND avail=2").fetchall())
        with patch.object(manga_catalog_index, 'TOTAL_BUDGET', 0):
            manga_catalog_index._totals.clear()
            first = self.new(**args)
            self.assertIs(first['totalExact'], False)
            available = self.db.execute("SELECT SUM(works) FROM content_work_stats WHERE kind='anime' AND avail=1").fetchone()[0]
            self.assertEqual(first['total'], max(available, 6))
            self.assertLessEqual(first['total'], exact)
            for thread in threading.enumerate():
                if thread.name == 'catalog-total':
                    thread.join(10)
            second = self.new(**args)
        self.assertNotIn('totalExact', second)
        self.assertEqual(second['total'], exact)
        self.assertEqual([item['workKey'] for item in first['items']], [item['workKey'] for item in second['items']])

    def test_plans_read_the_order_index_without_grouping(self):
        ingest(self.db, rows(works=10))
        plans = []
        real = self.db.execute

        class Spy:
            def __getattr__(self, name):
                return getattr(real.__self__, name)

            def execute(self, sql, args=()):
                if 'FROM content_works w' in sql and 'LIMIT' in sql:
                    plans.append(' | '.join(row[3] for row in real('EXPLAIN QUERY PLAN ' + sql, args)))
                return real(sql, args)

        for sort in SORTS:
            content_works.page(Spy(), kind='movie', sort=sort, status='available')
        self.assertTrue(plans)
        for plan in plans:
            self.assertIn('USING COVERING INDEX content_works_', plan)
            self.assertNotIn('TEMP B-TREE', plan)
        plans.clear()
        with patch.object(content_works, 'STREAM_SCAN', 0):
            content_works.page(Spy(), kind='movie', sort='new', tag='Robots')
        self.assertIn('PRIMARY KEY', plans[0])


if __name__ == '__main__':
    unittest.main()
