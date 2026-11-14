import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from manga_solver import source_timeout, configure


class VerifiedSolverBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'DATA_DIR': str(self.root), 'DISCOVERY_CACHE_DIR': str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_only_verified_source_gets_extra_cold_start_time(self):
        self.assertEqual(source_timeout('123', 12), 12)
        configure({'engine': 'byparr', 'sourceIds': ['123'], 'requestTimeout': 60})
        self.assertEqual(source_timeout('123', 12), 60)
        self.assertEqual(source_timeout(123, 90), 90)
        self.assertEqual(source_timeout('999', 12), 12)
        self.assertEqual(source_timeout('https://untrusted.example', 12), 12)

    def test_invalid_or_unbounded_manifest_keeps_normal_timeout(self):
        for value in [{'engine': 'byparr', 'sourceIds': ['123'], 'requestTimeout': 99999},
                      {'engine': 'untrusted', 'sourceIds': ['123'], 'requestTimeout': 60},
                      {'engine': 'byparr', 'sourceIds': ['123 OR 1=1'], 'requestTimeout': 60}, None]:
            (self.root / 'manga-source-solver.json').write_text(json.dumps(value))
            self.assertEqual(source_timeout('123', 12), 12)
            with self.assertRaises(ValueError): configure(value)

    def test_recovery_preserves_other_failures_successful_jobs_cards_and_cursors(self):
        path = self.root / 'manga-discovery.sqlite'
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("CREATE TABLE reachability(source_id TEXT,failures INT); CREATE TABLE jobs(id TEXT,state TEXT); CREATE TABLE work(job TEXT,source_id TEXT,state TEXT); CREATE TABLE catalogue_jobs(id TEXT,spec TEXT,state TEXT,due REAL,cursor TEXT); CREATE TABLE catalog_titles(id TEXT);")
            db.executemany('INSERT INTO reachability VALUES(?,?)', [('123', 6), ('999', 6), ('123', 0)])
            db.executemany('INSERT INTO jobs VALUES(?,?)', [('bad', 'done'), ('good', 'done'), ('other', 'done'), ('live', 'running')])
            db.executemany('INSERT INTO work VALUES(?,?,?)', [('bad', '123', 'skipped'), ('good', '123', 'done'), ('other', '999', 'unavailable'), ('live', '123', 'unavailable')])
            for identity in ['123', '999']:
                db.execute('INSERT INTO catalogue_jobs VALUES(?,?,?,?,?)', (identity, json.dumps({'source': {'id': identity}}), 'retry', 9999999999, '{"page":17}'))
            db.execute("INSERT INTO catalog_titles VALUES('retained')")
        result = configure({'engine': 'byparr', 'sourceIds': ['123'], 'requestTimeout': 60})
        self.assertEqual(result, {'resetSearchFailures': 1, 'invalidatedSnapshots': 1, 'queuedCatalogueJobs': 1})
        with closing(sqlite3.connect(path)) as db, db:
            self.assertEqual(dict(db.execute('SELECT id,state FROM jobs')), {'bad': 'interrupted', 'good': 'done', 'other': 'done', 'live': 'running'})
            self.assertEqual(db.execute('SELECT * FROM reachability').fetchall(), [('999', 6), ('123', 0)])
            self.assertEqual(db.execute('SELECT id,cursor FROM catalogue_jobs ORDER BY id').fetchall(), [('123', '{"page":17}'), ('999', '{"page":17}')])
            self.assertEqual(db.execute("SELECT due FROM catalogue_jobs WHERE id='999'").fetchone()[0], 9999999999)
            self.assertEqual(db.execute('SELECT * FROM catalog_titles').fetchall(), [('retained',)])
        with self.assertRaises(ValueError): configure({'engine': 'byparr', 'sourceIds': ['123'], 'requestTimeout': 60}, ['999'])
