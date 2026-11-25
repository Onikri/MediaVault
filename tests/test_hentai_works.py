"""Mac mojibake labels, their one-off repair, and the materialized «Хентай» work set.

Offline fixtures only; no network and no real catalogue."""
import json, os, sqlite3, sys, tempfile, threading, unicodedata, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import catalog_labels, hentai_works, label_repair, manga_catalog_index, tag_merge
from catalog_labels import mac_repair, readable_label
from manga_catalog_index import browse, initialize, upsert
from manga_tag_policy import canonical_json

POLICY = {'schemaVersion': 1, 'includeDiscovered': True, 'hiddenTags': [], 'excludedTerms': [], 'excludedPrefixes': [], 'tags': []}
WORDS = ['веб', 'в цвете', 'повседневность', 'драма', 'романтика', 'фэнтези', 'сёдзё-ай', 'сверхъестественное', 'боевые искусства']


def damaged(word, encoding='mac_roman'):
    return unicodedata.normalize('NFKC', word.encode('utf-8').decode(encoding))


class LabelTests(unittest.TestCase):
    def test_owner_examples_are_restored(self):
        self.assertEqual(readable_label('–≤–μ–±'), 'веб')
        self.assertEqual(readable_label('—Ä–æ–o–∞–Ω—Ç–∏–∫–∞'), 'романтика')
        self.assertEqual(readable_label('—Ñ—ç–Ω—Ç–μ–∑–∏'), 'фэнтези')
        # Mac Greek reading seen on the same source.
        self.assertEqual(readable_label('–≤–Β–±'), 'веб')
        self.assertEqual(readable_label('―Ä–Ψ–Φ–Α–Ϋ―2–Η–Κ–Α'), 'романтика')

    def test_all_six_words_in_every_mac_code_page(self):
        for word in WORDS:
            for encoding in catalog_labels.MAC_ENCODINGS:
                with self.subTest(word=word, encoding=encoding):
                    self.assertEqual(readable_label(damaged(word, encoding)), word)

    def test_clean_labels_are_unchanged(self):
        for value in ['романтика', 'Хентай', 'Sci‑Fi – фэнтези', 'Pokémon', 'µ-ops', 'Café', 'Ω', 'Драма — комедия',
                      'Сёдзё-ай', '±5', '日常', 'ロマンス', 'Ñandú', 'Commedia dell’arte', 'Roman d’aventure', 'Mentor–Student',
                      'Big Breasts', 'жёсткий', 'Ёжик']:
            with self.subTest(value=value):
                self.assertIsNone(mac_repair(value))
                self.assertEqual(readable_label(value), value)

    def test_older_repairs_still_work(self):
        self.assertEqual(readable_label('Криминал'.encode().decode('cp1251')), 'Криминал')
        self.assertEqual(readable_label('Фэнтези'.encode().decode('latin1')), 'Фэнтези')


class DecodeTests(unittest.TestCase):
    def test_a_stray_byte_no_longer_switches_the_page_to_a_mac_code_page(self):
        from bs4 import BeautifulSoup
        from content_sources import html_text
        raw = ('<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8" /></head>'
               '<body><a>веб</a><a>романтика</a></body></html>').encode().replace(b'</head>', b'\xff</head>')
        labels = [a.get_text() for a in BeautifulSoup(html_text(raw), 'html.parser').select('a')]
        self.assertEqual(labels, ['веб', 'романтика'])
        self.assertEqual(html_text('уже текст'), 'уже текст')


class Fixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / 'manga-tag-policy.json').write_bytes(canonical_json(POLICY))
        self.env = patch.dict(os.environ, {'DATA_DIR': self.temp.name, 'MANGA_TAG_POLICY_FILE': str(root / 'manga-tag-policy.json')})
        self.env.start()
        patch.object(tag_merge, 'PAUSE', 0).start()
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        initialize(self.db)
        self.store = SimpleNamespace(db=self.db, lock=threading.RLock())

    def tearDown(self):
        patch.stopall()
        self.db.close()
        self.env.stop()
        self.temp.cleanup()

    def row(self, name, host='fixture.example', tags=(), genres=(), year=2000, title=None, chapters=3):
        return {'provider': host.split('.')[0], 'kind': 'manga', 'title': title or 'Work ' + name, 'year': year,
                'sourceUrl': 'https://' + host + '/manga/' + name, 'tags': list(tags), 'genres': list(genres),
                'episodes': [{'number': n} for n in range(chapters)]}


class HentaiWorkTests(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        rows = []
        for n in range(30):
            kind = n % 5
            if kind == 0:
                rows.append(self.row('o%d' % n, host='hentailib.me', year=1990 + n))            # origin
            elif kind == 1:
                rows.append(self.row('e%d' % n, genres=['Хентай'], year=1990 + n))               # explicit
            elif kind == 2:
                rows.append(self.row('v%d' % n, host='hentailib.me', tags=['Не хентай'], year=1990 + n))  # vetoed
            elif kind == 3:
                rows.append(self.row('r%d' % n, genres=['Романтика'], year=1990 + n))
            else:
                rows.append(self.row('p%d' % n, year=None if n % 2 else 1990 + n, chapters=0 if n == 9 else 3))
        # One work, two sources: the plain edition inherits the work's genre.
        rows.append(self.row('mirror', title='Work o5', year=2030))
        # The veto on one source excludes the whole work.
        rows.append(self.row('veto-mirror', title='Work e6', tags=['Not hentai']))
        upsert(self.db, rows)
        self.db.commit()

    def old(self, **kwargs):
        with patch.object(hentai_works, 'ready', return_value=False):
            return browse(self.db, **kwargs)

    def keys(self, result):
        return [row['workKey'] for row in result['items']]

    def test_include_and_exclude_match_the_derived_union(self):
        self.assertTrue(hentai_works.ready(self.db, manga_catalog_index.current()))
        for field in ('genre', 'excludeGenre'):
            for sort in ('', 'new', 'old', 'title', 'length', 'added'):
                for status in ('', 'available'):
                    for offset in (0, 4, 9):
                        args = {field: 'Хентай', 'sort': sort, 'status': status, 'limit': 4, 'offset': offset}
                        with self.subTest(**args):
                            new, old = browse(self.db, **args), self.old(**args)
                            self.assertEqual(self.keys(new), self.keys(old))
                            self.assertEqual((new['total'], new['workTotal']), (old['total'], old['workTotal']))
        included = set(self.keys(browse(self.db, genre='Хентай', limit=100)))
        self.assertIn('work o5', included)
        self.assertNotIn('work e6', included)
        self.assertFalse(any(key.startswith('work v') for key in included))

    def test_streamed_pages_use_the_index_order(self):
        plan = ' '.join(str(part) for row in self.db.execute(
            'EXPLAIN QUERY PLAN SELECT t.work_key FROM catalog_titles t INDEXED BY catalog_titles_newest WHERE '
            'EXISTS(SELECT 1 FROM catalog_hentai_works h WHERE h.work_key=t.work_key) ORDER BY (t.year IS NULL),t.year DESC,t.work_key')
            for part in row)
        self.assertNotIn('TEMP B-TREE', plan)
        self.assertIn('SEARCH h USING PRIMARY KEY', plan)

    def test_writes_keep_the_set(self):
        upsert(self.db, [self.row('new', host='hentaichan.live')])
        self.assertIn(('work new',), self.db.execute('SELECT work_key FROM catalog_hentai_works').fetchall())
        upsert(self.db, [self.row('new2', title='Work new', tags=['Non-hentai'])])
        self.assertNotIn(('work new',), self.db.execute('SELECT work_key FROM catalog_hentai_works').fetchall())

    def test_background_fill_resumes_and_gives_the_same_set(self):
        expected = sorted(self.db.execute('SELECT work_key FROM catalog_hentai_works').fetchall())
        hentai_works.invalidate(self.db)
        # The previous set is served while the new one is computed.
        self.assertTrue(hentai_works.ready(self.db, manga_catalog_index.current()))
        self.assertFalse(hentai_works.current(self.db))
        self.assertEqual(self.keys(browse(self.db, genre='Хентай', limit=100)), self.keys(self.old(genre='Хентай', limit=100)))
        with patch.object(hentai_works, 'PORTION', 3), patch.object(hentai_works, 'SCAN', 4):
            for _ in range(12):
                hentai_works.step(self.store)
                self.assertEqual(self.keys(browse(self.db, genre='Хентай', limit=100)), self.keys(self.old(genre='Хентай', limit=100)))
            while tag_merge.step(self.store, pause=0):
                pass
        self.assertTrue(hentai_works.current(self.db))
        self.assertFalse(self.db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_hentai_works_next'").fetchone())
        self.assertEqual(sorted(self.db.execute('SELECT work_key FROM catalog_hentai_works').fetchall()), expected)

    def test_slow_totals_are_counted_in_the_background(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.sqlite'
            disk = sqlite3.connect(path)
            self.db.backup(disk)
            disk.close()
            reader = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
            from catalog_taxonomy import register_origin_functions
            register_origin_functions(reader)
            manga_catalog_index._totals.clear(); manga_catalog_index._slow.clear()
            self.addCleanup(reader.close)
            with patch.object(manga_catalog_index, 'TOTAL_BUDGET', -1), patch.object(manga_catalog_index, 'TOTAL_STEPS', 1):
                first = browse(reader, genre='Романтика', limit=2)
                self.assertIs(first['totalExact'], False)
                # A single counted genre pages by its exact catalog_tag_stats works.
                self.assertEqual(first['workTotal'], 6)
                for thread in threading.enumerate():
                    if thread.name == 'catalog-total':
                        thread.join(10)
                second = browse(reader, genre='Романтика', limit=2)
            self.assertNotIn('totalExact', second)
            self.assertEqual(second['workTotal'], 6)
            self.assertEqual(len(second['items']), 2)
            reader.close()
            manga_catalog_index._totals.clear(); manga_catalog_index._slow.clear()


class LabelRepairTests(Fixture, unittest.TestCase):
    def test_damaged_titles_are_reprojected_without_losing_facts(self):
        broken = [damaged('романтика'), damaged('веб', 'mac_greek')]
        catalog_labels._readable_label.cache_clear()
        with patch.object(catalog_labels, 'mac_repair', lambda value: None):
            catalog_labels._readable_label.cache_clear()
            upsert(self.db, [self.row('m1', host='im.manga-chan.me', tags=broken),
                             self.row('ok', tags=['Романтика'])])
            self.db.commit()
            catalog_labels._readable_label.cache_clear()
        facts = sorted(self.db.execute('SELECT * FROM catalog_tag_facts').fetchall())
        self.assertIn(broken[0], {row[3] for row in self.db.execute('SELECT * FROM catalog_tags')})
        (Path(self.temp.name) / label_repair.PENDING).write_text('{}', encoding='utf-8')
        with patch.object(label_repair, 'PORTION', 1):
            while tag_merge.step(self.store, pause=0):
                pass
        job = label_repair.read_job()
        self.assertEqual((job['state'], job['queued'], job['processed']), ('done', 1, 1))
        self.assertEqual(sorted(self.db.execute('SELECT * FROM catalog_tag_facts').fetchall()), facts)
        originals = {row[0] for row in self.db.execute('SELECT original FROM catalog_tags')}
        self.assertTrue({'романтика', 'веб'} <= originals)
        self.assertFalse(set(broken) & originals)
        self.assertEqual(browse(self.db, tag='веб')['total'], 1)
        self.assertEqual(browse(self.db, genre='Романтика')['workTotal'], 2)
        vocabulary = {row[0] for row in self.db.execute('SELECT label FROM catalog_vocabulary')}
        self.assertTrue({'романтика', 'веб'} <= vocabulary and set(broken) <= vocabulary)
        self.assertEqual(tag_merge.status()['labelRepair']['state'], 'done')


if __name__ == '__main__':
    unittest.main()
