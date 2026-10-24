"""Durable import/auth boundaries. All external services are fixtures, no live accounts."""
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from catalog_search import CatalogSearch, parse_candidates
from runtime_api import create_app, OwnerAuth
from runtime_store import Store
from runtime_worker import process_one, LimitedHttp
from source_parser import PublicHttp, SourceError
from vault_drive import VaultDrive
from test_vault_drive import FakeDrive, PHRASE


def job(library='library-123'):
    return {'version': 1, 'library_id': library, 'sources': ['https://example.com/anime/series'],
            'collection': 'Anime test', 'season': 1, 'episodes': 'all', 'quality': '720', 'resume': True}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.drive = FakeDrive()
        self.vault = VaultDrive(self.drive, sleep=lambda _: None)
        self.library = self.vault.initialize(PHRASE)
        self.key = base64.b64encode(self.vault._key).decode()
        self.store.put_secret('google-oauth', {'refresh_token': 'SUPER_SECRET_REFRESH'})
        self.store.put_secret('library:' + self.library, self.key)
        self.store.put_secret('worker-heartbeat', time.time())
        self.app = create_app(store=self.store, auth=lambda token: token == 'OWNER',
            catalog=CatalogSearch(providers=[], metadata_get=lambda *args: []),
            vault_factory=lambda: VaultDrive(self.drive, sleep=lambda _: None))
        self.client = self.app.test_client()
        self.headers = {'Authorization': 'Bearer OWNER', 'Origin': 'https://onikri.github.io'}

    def tearDown(self):
        self.temp.cleanup()

    def post(self, path, value):
        return self.client.post(path, json=value, headers=self.headers)

    def test_auth_cors_and_no_secret_leaks(self):
        self.assertEqual(self.client.get('/jobs?library=' + self.library).status_code, 401)
        self.assertEqual(self.client.get('/status?library=' + self.library, headers={'Authorization': 'Bearer READER'}).status_code, 401)
        bad = {**self.headers, 'Origin': 'https://evil.example'}
        self.assertEqual(self.client.get('/status?library=' + self.library, headers=bad).status_code, 403)
        response = self.client.get('/status?library=' + self.library, headers=self.headers)
        self.assertTrue(response.json['library_connected'])
        self.assertNotIn('SUPER_SECRET_REFRESH', response.text)
        self.assertNotIn(self.key, response.text)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], self.headers['Origin'])
        self.assertEqual(self.client.options('/jobs', headers={'Origin': self.headers['Origin']}).status_code, 204)

    def test_keys_and_jobs_are_encrypted_and_restartable(self):
        identifier = self.store.enqueue(job(self.library), 'idempotency-key-123')
        raw = Path(self.store.path).read_bytes()
        self.assertNotIn(b'SUPER_SECRET_REFRESH', raw)
        self.assertNotIn(b'Anime test', raw)
        self.assertNotIn(self.key.encode(), raw)
        self.assertEqual(self.store.take()[0], identifier)
        restarted = Store(self.temp.name)
        restarted.recover()
        self.assertEqual(restarted.take(), (identifier, job(self.library)))
        self.assertEqual(restarted.secret('google-oauth')['refresh_token'], 'SUPER_SECRET_REFRESH')
        self.assertEqual(os.stat(Path(self.temp.name) / 'master.key').st_mode & 0o777, 0o600)

    def test_enqueue_idempotency_no_payload_in_status_and_cancel(self):
        payload = {'job': job(self.library), 'request_id': 'request-0000000001'}
        first = self.post('/jobs', payload)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(self.post('/jobs', payload).json, first.json)
        response = self.client.get('/jobs?library=' + self.library, headers=self.headers)
        self.assertEqual(len(response.json['jobs']), 1)
        self.assertNotIn('sources', response.text)
        identifier = first.json['id']
        self.assertEqual(self.post('/jobs/' + identifier + '/cancel', {}).status_code, 200)
        self.assertIsNone(self.store.take())
        self.assertEqual(self.store.jobs(self.library)[0]['status'], 'cancelled')

    def test_unconfigured_worker_and_credentials_reject_jobs(self):
        self.store.put_secret('worker-heartbeat', 0)
        self.assertEqual(self.post('/jobs', {'job': job(self.library), 'request_id': 'request-0000000001'}).status_code, 503)
        self.store.put_secret('worker-heartbeat', time.time())
        self.store.delete_secret('library:' + self.library)
        self.assertEqual(self.post('/jobs', {'job': job(self.library), 'request_id': 'request-0000000001'}).status_code, 400)
        self.assertEqual(self.store.jobs(self.library), [])

    def test_connect_validates_phrase_and_stores_only_derived_key(self):
        self.store.delete_secret('library:' + self.library)
        wrong = self.post('/libraries/unlock', {'library_id': self.library, 'passphrase': 'wrong-long-phrase'})
        self.assertEqual(wrong.status_code, 400)
        self.assertIsNone(self.store.secret('library:' + self.library))
        good = self.post('/libraries/unlock', {'library_id': self.library, 'passphrase': PHRASE})
        self.assertEqual(good.status_code, 200)
        self.assertEqual(self.store.secret('library:' + self.library), self.key)
        self.assertNotIn(PHRASE.encode(), Path(self.store.path).read_bytes())
        self.store.enqueue(job(self.library), 'request-0000000001')
        self.assertEqual(self.client.delete('/libraries/' + self.library, headers=self.headers).status_code, 400)

    def test_worker_uses_real_vault_key_and_reports_partial_result(self):
        identifier = self.store.enqueue(job(self.library), 'request-0000000001')
        def runner(value, vault, **options):
            self.assertEqual(vault.catalog['folderId'], self.vault.catalog['folderId'])
            self.assertNotIn('passphrase', value)
            options['event']({'phase': 'saved', 'completed': 1, 'total': 2})
            return {'saved': 1, 'skipped': 0, 'failed': 1}
        with patch('runtime_worker.shutil.disk_usage') as disk:
            disk.return_value.free = 10 * 1024**3
            self.assertTrue(process_one(self.store, vault_factory=lambda: VaultDrive(self.drive), runner=runner))
        result = self.store.jobs(self.library)[0]
        self.assertEqual(result['id'], identifier)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['progress']['completed'], 1)
        with self.store.connect() as db:
            self.assertIsNone(db.execute('SELECT payload FROM jobs').fetchone()[0])

    def test_worker_recovers_without_leaking_failures_and_queue_is_bounded(self):
        identifier = self.store.enqueue(job(self.library), 'request-0000000001')
        self.store.take()
        self.store.recover()
        def fail():
            raise RuntimeError('SUPER_SECRET_REFRESH')
        with patch('runtime_worker.shutil.disk_usage') as disk:
            disk.return_value.free = 10 * 1024**3
            process_one(self.store, vault_factory=fail)
        result = self.store.jobs(self.library)[0]
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('SUPER_SECRET_REFRESH', json.dumps(result))
        for index in range(20):
            self.store.enqueue(job(self.library), 'next-request-%016d' % index)
        with self.assertRaises(ValueError):
            self.store.enqueue(job(self.library), 'overflow-request-123')

    def test_cancellation_running_is_observed(self):
        identifier = self.store.enqueue(job(self.library), 'request-0000000001')
        def runner(value, vault, **options):
            self.store.cancel(identifier)
            self.assertTrue(options['cancelled']())
            raise InterruptedError()
        with patch('runtime_worker.shutil.disk_usage') as disk:
            disk.return_value.free = 10 * 1024**3
            process_one(self.store, vault_factory=lambda: VaultDrive(self.drive), runner=runner)
        self.assertEqual(self.store.jobs(self.library)[0]['status'], 'cancelled')

    def test_requests_reject_unexpected_credentials_private_sources_and_oversized_body(self):
        invalid = job(self.library)
        invalid['refresh_token'] = 'SECRET'
        self.assertEqual(self.post('/jobs', {'job': invalid, 'request_id': 'request-0000000001'}).status_code, 400)
        invalid = job(self.library)
        invalid['sources'] = ['https://127.0.0.1/secret']
        self.assertEqual(self.post('/jobs', {'job': invalid, 'request_id': 'request-0000000001'}).status_code, 400)
        self.assertEqual(self.post('/jobs', {'padding': 'a' * 33000}).status_code, 413)


class CatalogTests(unittest.TestCase):
    def test_search_adapters_extract_real_links_only(self):
        provider = {'id': 'animego', 'name': 'AnimeGO'}
        items = parse_candidates('''<a href="/anime/naruto-1"><img src="/cover.jpg" alt="Наруто"></a>
          <a href="/anime/naruto-1">Наруто</a><a href="https://evil.example/anime/x">Wrong</a>
          <a href="/search/anime?q=x">Поиск</a><a href="javascript:alert(1)">No</a>''',
          'https://animego.org', 'animego', provider)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['url'], 'https://animego.org/anime/naruto-1')
        items = parse_candidates('<h2><a href="/tip/tv/100-naruto.html">Наруто</a></h2>',
                                 'https://animevost.org', 'dle', {'id': 'animevost', 'name': 'AnimeVost'})
        self.assertEqual(len(items), 1)

    def test_provider_failures_are_isolated_and_metadata_is_cached(self):
        calls = []
        def metadata(path, params=None):
            calls.append((path, params))
            value = {'id': 20, 'name': 'Naruto', 'russian': 'Наруто', 'score': '8.0',
                     'image': {'original': '/cover.jpg'}, 'description_html': '<p>Story</p>'}
            return [value] if not path else value
        class Broken:
            def document(self, url):
                raise SourceError('blocked')
            def close(self):
                pass
        search = CatalogSearch(metadata_get=metadata, http_factory=Broken)
        first = search.search('Naruto')
        self.assertEqual(first, search.search('Naruto'))
        self.assertEqual(len(calls), 1)
        self.assertEqual(first['items'][0]['title'], 'Наруто')
        self.assertTrue(all(p['status'] == 'unavailable' for p in first['providers']))
        self.assertEqual(search.detail(20)['description'], 'Story')

    def test_metadata_failure_does_not_erase_working_source(self):
        class Http:
            def document(self, url):
                return '<a href="/anime/naruto-1">Naruto</a>', url, {}
            def close(self):
                pass
        def broken(*args):
            raise SourceError('Unavailable')
        search = CatalogSearch(providers=[{'id': 'animego', 'name': 'AnimeGO', 'origin': 'https://animego.org', 'adapter': 'animego'}],
            metadata_get=broken, http_factory=Http)
        result = search.search('Naruto')
        self.assertTrue(result['metadata_error'])
        self.assertEqual(result['providers'][0]['items'][0]['title'], 'Naruto')

    def test_download_limit_applies_to_total_hls_segments(self):
        http = LimitedHttp()
        with patch.dict(os.environ, {'MEDIAVAULT_MAX_FILE_BYTES': '10'}), patch.object(PublicHttp, 'download', return_value=6) as download:
            http.download('https://example.com/1', '/tmp/mediavault-episode-one/video/1.ts')
            http.download('https://example.com/2', '/tmp/mediavault-episode-one/video/2.ts')
            self.assertEqual(download.call_args.kwargs['maximum'], 4)
            with self.assertRaises(SourceError):
                http.download('https://example.com/3', '/tmp/mediavault-episode-one/video/3.ts')
            http.download('https://example.com/4', '/tmp/mediavault-episode-two/video/4.ts')
            self.assertEqual(download.call_args.kwargs['maximum'], 10)
        http.close()


class GoogleAuthTests(unittest.TestCase):
    @patch('runtime_api.requests.get')
    def test_requires_audience_verified_owner_and_unexpired_token(self, get):
        import hashlib
        owner = 'owner@example.test'
        auth = OwnerAuth('web-client-id', hashlib.sha256(owner.encode()).hexdigest())
        def responses(info, user):
            get.side_effect = None
            first, second = unittest.mock.Mock(), unittest.mock.Mock()
            first.json.return_value = info
            second.json.return_value = user
            get.side_effect = [first, second]
        correct = {'audience': 'web-client-id', 'expires_in': 100}
        user = {'email_verified': True, 'email': owner}
        responses({**correct, 'audience': 'other-client'}, user)
        self.assertFalse(auth('BAD_AUDIENCE'))
        responses(correct, {**user, 'email_verified': False})
        self.assertFalse(auth('UNVERIFIED'))
        responses(correct, {**user, 'email': 'reader@example.test'})
        self.assertFalse(auth('READER'))
        responses({**correct, 'expires_in': 0}, user)
        self.assertFalse(auth('EXPIRED'))
        responses(correct, user)
        self.assertTrue(auth('OWNER'))
        get.reset_mock()
        self.assertTrue(auth('OWNER'))
        get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
