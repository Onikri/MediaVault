import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import api
import reading_places


class ReadingPlaces(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'DATA_DIR': self.directory.name, 'MEDIA_VAULT_DISABLE_WORKER': '1'})
        self.environment.start()
        self.client = TestClient(api.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.environment.stop()
        self.directory.cleanup()

    def sync(self, subject, since=0, entries=(), status=200):
        headers = {'Authorization': 'Bearer ' + api.session_token(subject)} if subject else {}
        response = self.client.post('/places', json={'since': since, 'entries': list(entries)}, headers=headers)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def test_place_from_one_device_reaches_another_and_newest_wins(self):
        now = int(time.time() * 1000)
        book = 'r:https://ranobe.example/book/1'
        computer = self.sync('owner-a', 0, [{'k': book, 'at': now, 'v': {'chapter': 'https://ranobe.example/book/1/12', 'paragraph': 41, 'updatedAt': now}}])
        self.assertEqual(computer['entries'][0]['v']['paragraph'], 41)
        phone = self.sync('owner-a')
        self.assertEqual([(e['k'], e['v']['paragraph']) for e in phone['entries']], [(book, 41)])
        # An older save (a phone that was offline) never overwrites a newer place.
        stale = self.sync('owner-a', phone['clock'], [{'k': book, 'at': now - 5000, 'v': {'chapter': 'old', 'paragraph': 2}}])
        self.assertEqual(stale['entries'], [])
        self.assertEqual(self.sync('owner-a')['entries'][0]['v']['paragraph'], 41)
        # A newer place replaces it and reaches the device that asks from its clock.
        self.sync('owner-a', 0, [{'k': book, 'at': now + 1000, 'v': {'chapter': 'https://ranobe.example/book/1/13', 'paragraph': 0}}])
        later = self.sync('owner-a', phone['clock'])
        self.assertEqual([e['v']['chapter'] for e in later['entries']], ['https://ranobe.example/book/1/13'])
        self.assertEqual(self.sync('owner-a', later['clock'])['entries'], [])

    def test_removed_place_stays_removed_and_profiles_are_separate(self):
        now = int(time.time() * 1000)
        row = {'id': 'ranobe:owner-a:42', 'label': 'Книга, глава 12', 'kind': 'reader', 'route': '#watch=42', 'at': now}
        self.sync('owner-a', 0, [{'k': 'h:ranobe:owner-a:42', 'at': now, 'v': row}])
        self.assertEqual(self.sync('owner-b')['entries'], [])
        gone = self.sync('owner-a', 0, [{'k': 'h:ranobe:owner-a:42', 'at': now + 1, 'v': None}])
        self.assertEqual(gone['entries'], [{'k': 'h:ranobe:owner-a:42', 'at': now + 1, 'v': None}])
        self.sync('owner-a', 0, [{'k': 'h:ranobe:owner-a:42', 'at': now, 'v': row}])
        self.assertIsNone(self.sync('owner-a')['entries'][0]['v'])

    def test_sessions_and_input_are_checked(self):
        self.sync('', status=401)
        self.client.post('/places', json={'since': 0, 'entries': [{'k': 'x:bad', 'at': 1, 'v': None}]}, headers={'Authorization': 'Bearer ' + api.session_token('owner-a')})
        self.assertEqual(self.client.post('/places', json={'since': 0, 'entries': [{'k': 'x:bad', 'at': 1, 'v': None}]}, headers={'Authorization': 'Bearer ' + api.session_token('owner-a')}).status_code, 422)
        now = int(time.time() * 1000)
        result = self.sync('owner-a', 0, [{'k': 'r:big', 'at': now, 'v': {'text': 'x' * 5000}}, {'k': 'r:future', 'at': now + 86400000, 'v': {'paragraph': 1}}])
        self.assertEqual([e['k'] for e in result['entries']], ['r:future'])
        self.assertLessEqual(result['entries'][0]['at'], now + reading_places.FUTURE + 5000)
        self.assertTrue(api.app.state.reading_places is not None)
        self.assertTrue(api.health()['readingPlaces'])

    def test_rows_are_sealed_and_paged(self):
        now = int(time.time() * 1000)
        entries = [{'k': 'm:online%3Ahttps%3A%2F%2Fmanga.example%2Fc' + str(i), 'at': now + i, 'v': {'page': i, 'pages': 900}} for i in range(reading_places.PAGE)]
        self.sync('owner-a', 0, entries)
        self.sync('owner-a', 0, [{'k': 'r:https://ranobe.example/secret-book', 'at': now, 'v': {'chapter': 'secret-chapter', 'paragraph': 3}}])
        first = self.sync('owner-a')
        self.assertTrue(first['more'])
        self.assertEqual(len(first['entries']), reading_places.PAGE)
        rest = self.sync('owner-a', first['clock'])
        self.assertFalse(rest['more'])
        self.assertEqual([e['k'] for e in rest['entries']], ['r:https://ranobe.example/secret-book'])
        raw = Path(self.directory.name, 'places.sqlite').read_bytes()
        for secret in (b'secret-book', b'secret-chapter', b'owner-a'):
            self.assertNotIn(secret, raw)
        with sqlite3.connect(Path(self.directory.name, 'places.sqlite')) as database:
            self.assertEqual(database.execute('SELECT count(*) FROM places').fetchone()[0], reading_places.PAGE + 1)

    def test_restored_server_sends_everything_again(self):
        now = int(time.time() * 1000)
        self.sync('owner-a', 0, [{'k': 'w:12345', 'at': now, 'v': {'episode': 5, 'season': 1}}])
        far = self.sync('owner-a', 10 ** 18)
        self.assertEqual([e['k'] for e in far['entries']], ['w:12345'])


if __name__ == '__main__':
    unittest.main()
