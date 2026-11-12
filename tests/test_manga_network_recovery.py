"""Real SQLite recovery; network responses and administrator routing are fixtures."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import manga_discovery as discovery
import manga_network_routes as routes
import suwayomi_bridge as bridge

ROUTE = {'revision': 'a' * 64, 'hosts': ['comic-ryu.jp'], 'httpProxy': 'http://suwayomi-jp-router:8080'}
SOURCES = [{'id': '1', 'name': 'Comic Ryu', 'lang': 'ja', 'baseUrl': 'https://comic-ryu.jp'},
           {'id': '2', 'name': 'Other', 'lang': 'en', 'baseUrl': 'https://other.example'}]


def done(manager, identity):
    for _ in range(400):
        state = manager.status('owner', identity)
        if state['state'] != 'running':
            return state
        time.sleep(.01)
    raise AssertionError('Job did not complete')


class NetworkRecoveryTests(unittest.TestCase):
    def test_japanese_query_keeps_native_and_latin_alias_not_russian_display_name(self):
        values = ['Бродяга', 'Vagabond', 'バガボンド', 'Bagabondo', '배가본드']
        self.assertEqual(discovery.language_queries(values, 'ja'), ['バガボンド', 'Vagabond'])
        self.assertEqual(discovery.language_queries(values, 'ko'), ['배가본드', 'Vagabond'])
        self.assertEqual(discovery.language_queries(values, 'ru'), ['Бродяга', 'Vagabond', 'Bagabondo'])

    def test_route_revision_recovers_old_pause_and_snapshots_only_for_affected_source(self):
        route = {}
        fail = True
        calls = []
        def fetch(source, query):
            calls.append(source['id'])
            if fail:
                raise bridge.BridgeError('upstream', 'HTTP 500')
            return []
        with tempfile.TemporaryDirectory() as directory, patch.object(discovery, 'installed_sources', return_value=SOURCES), patch.object(routes, 'configuration', side_effect=lambda: route), patch('manga_source_health.reset_failures') as reset:
            manager = discovery.Discovery(directory, fetch=fetch, workers=1, cache_ttl=900)
            try:
                for query in ['query one', 'query two']:
                    done(manager, manager.start('owner', query)['id'])
                before = done(manager, manager.start('owner', 'same query')['id'])
                self.assertTrue(all(p['state'] == 'skipped' for p in before['providers']))
                fail = False
                route = dict(ROUTE)
                after = done(manager, manager.start('owner', 'same query')['id'])
                self.assertNotEqual(before['id'], after['id'])
                by_id = {p['id']: p for p in after['providers']}
                self.assertEqual(by_id['1']['state'], 'done')
                self.assertEqual(by_id['2']['state'], 'skipped')
                self.assertEqual([v['source_id'] for v in manager.reachability()], ['2'])
                reset.assert_called_once_with(['1'])
                self.assertEqual(calls.count('1'), 3)
                self.assertEqual(calls.count('2'), 2)
            finally:
                manager.close()

    def test_changed_aliases_do_not_reuse_an_old_empty_query_cache(self):
        base = {'_title': {'title': 'Бродяга'}, '_queries': ['バガボンド', 'Бродяга']}
        fixed = {**base, '_queries': ['バガボンド', 'Vagabond']}
        self.assertNotEqual(discovery.Discovery._cache_key('бродяга', base), discovery.Discovery._cache_key('бродяга', fixed))

    def test_bad_query_can_try_another_alias_without_quarantining_the_source(self):
        source = {**SOURCES[0], '_queries': ['バガボンド', 'Vagabond']}
        with patch.object(bridge, 'Client') as client:
            client.return_value.get.side_effect = [bridge.BridgeError('query', 'bad query'), {'mangaList': []}]
            self.assertEqual(discovery.search_source(source, 'Бродяга'), [])
            self.assertEqual(client.return_value.get.call_count, 2)
        with tempfile.TemporaryDirectory() as directory:
            manager = discovery.Discovery(directory, start_workers=False)
            try:
                for _ in range(5):
                    with manager.db:
                        manager._reachability(SOURCES[0], '1', False, {'code': 'query'}, time.time())
                self.assertEqual(manager.reachability(), [])
            finally:
                manager.close()

    def test_manifest_accepts_only_fixed_private_connector_and_valid_hostnames(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'DATA_DIR': directory}):
            path = Path(directory) / 'manga-source-routes.json'
            path.write_text(json.dumps(ROUTE))
            self.assertEqual(routes.configuration(), ROUTE)
            self.assertTrue(routes.routed('https://cdn.comic-ryu.jp/a.jpg', ROUTE))
            self.assertFalse(routes.routed('https://comic-ryu.jp.evil.example/', ROUTE))
            for bad in [{**ROUTE, 'httpProxy': 'http://169.254.169.254'}, {**ROUTE, 'hosts': ['localhost']}, {**ROUTE, 'revision': ''}]:
                path.write_text(json.dumps(bad))
                self.assertEqual(routes.configuration(), {})

    def test_rawuwu_missing_empty_pagination_is_not_a_broken_source(self):
        from manga_search_recovery import rawuwu_empty
        class Http:
            def __init__(self, data, final='https://rawuwu.net/spa/search'):
                self.data, self.final, self.closed = data, final, False
            def document(self, url):
                self.url = url
                return json.dumps(self.data), self.final, {}
            def close(self):
                self.closed = True
        source = {'name': 'Raw UwU', 'baseUrl': 'https://rawuwu.net'}
        empty = {'manga_list': [], 'pagi': {'current': 1, 'offset': 0}}
        for data, final, expected in [(empty, 'https://rawuwu.net/spa/search', True),
                                       ({**empty, 'manga_list': [{'name': 'other'}]}, 'https://rawuwu.net/spa/search', False),
                                       (empty, 'https://other.example/', False), ({}, 'https://rawuwu.net/spa/search', False)]:
            http = Http(data, final)
            self.assertEqual(rawuwu_empty(source, 'Vagabond', lambda **_: http), expected)
            self.assertTrue(http.closed)
        error = bridge.bridge_error(400, "kotlinx.serialization.MissingFieldException: Field 'button' is required")
        self.assertEqual(error.code, 'format')
        with patch.object(bridge, 'Client') as client, patch('manga_search_recovery.rawuwu_empty', return_value=True) as recover:
            client.return_value.get.side_effect = error
            self.assertEqual(discovery.search_source({**source, 'id': '3', 'lang': 'ja', '_queries': ['バガボンド', 'Vagabond']}, 'Бродяга'), [])
            self.assertEqual(recover.call_count, 2)

    def test_origin_diagnostics_use_the_same_route_and_drop_old_cached_regional_result(self):
        class Reply:
            status_code = 200
            def iter_content(self, _):
                yield b'<html>publisher</html>'
            def close(self):
                pass
        bridge._origins.clear()
        with patch.object(routes, 'configuration', return_value=ROUTE), patch.object(bridge, 'public_url', side_effect=lambda u, **_: u), patch.object(bridge.requests, 'get', return_value=Reply()) as get:
            self.assertIsNone(bridge.origin_block('https://comic-ryu.jp'))
            self.assertEqual(get.call_args.kwargs['proxies'], {'http': ROUTE['httpProxy'], 'https': ROUTE['httpProxy']})
            self.assertIsNone(bridge.origin_block('https://other.example'))
            self.assertNotIn('proxies', get.call_args.kwargs)
        bridge._origins.clear()


if __name__ == '__main__':
    unittest.main()
