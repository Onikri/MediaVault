import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('network_install', ROOT / 'deploy/oracle/install-network-services.py')
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)
gateway = install.gateway
PEM = '-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----'
PROFILE = 'client\ndev tun\nproto tcp\nremote 119.240.163.125 1270\n' + '\n'.join(f'<{k}>\n{PEM}\n</{k}>' for k in ('ca', 'cert', 'key'))


class Proc:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code

    def terminate(self):
        self.code = 0

    def wait(self, *_):
        return self.code

    def kill(self):
        self.code = -9


class ProfileTests(unittest.TestCase):
    def test_public_profile_is_rebuilt_with_tls_verification_and_is_restartable(self):
        result = gateway.profile(PROFILE)
        self.assertIn('remote-cert-tls server', result)
        self.assertIn('verify-x509-name opengw.net name', result)
        self.assertIn('tls-version-min 1.2', result)
        self.assertEqual(gateway.profile(result), result)
        self.assertEqual(gateway.endpoint(result), '119.240.163.125:1270/tcp')

    def test_feed_cannot_supply_executable_directives_or_private_endpoints(self):
        for bad in ['up /tmp/payload', 'plugin /tmp/plugin.so', 'config /etc/passwd', 'management 0.0.0.0 1234']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                gateway.profile(PROFILE + '\n' + bad)
        for bad in ['127.0.0.1', '169.254.169.254', '10.0.0.1', '::1']:
            with self.subTest(address=bad), self.assertRaises(ValueError):
                gateway.profile(PROFILE.replace('119.240.163.125', bad))

    def test_feed_uses_only_japanese_valid_profiles(self):
        good = base64.b64encode(PROFILE.encode()).decode()
        feed = ('*vpn_servers\n#HostName,CountryShort,Speed,OpenVPN_ConfigData_Base64\n'
                f'a,JP,20,{good}\nb,US,100,{good}\nc,JP,100,invalid\n*\n')
        self.assertEqual(gateway.candidates(feed.encode()), [gateway.profile(PROFILE)])
        with self.assertRaises(ValueError):
            gateway.candidates(b'x' * (4 * 1024 * 1024 + 1))

    def test_trace_parsing_rejects_garbage(self):
        self.assertEqual(gateway.parse_trace('fl=1\nip=219.100.37.233\nloc=JP\n')['loc'], 'JP')
        with self.assertRaises(gateway.Failure):
            gateway.parse_trace('<html>blocked</html>')


class RoutingTests(unittest.TestCase):
    def test_routing_is_scoped_to_publishers_in_a_chain_not_a_global_proxy(self):
        config = gateway.routing_config()
        self.assertTrue(config['bypasses'][0]['whitelist'])
        self.assertEqual(config['chains'][0]['hops'][0]['bypass'], 'publishers')
        self.assertNotIn('bypass', config['services'][0])
        self.assertNotIn('*', config['bypasses'][0]['matchers'])
        self.assertNotIn('.google.com', config['bypasses'][0]['matchers'])
        self.assertEqual(config['chains'][0]['hops'][0]['nodes'][0]['addr'], 'jp-vpn:1081')
        self.assertEqual(sorted(s['addr'] for s in config['services']), [':1080', ':8080'])

    def test_transport_manifest_matches_the_router_and_is_written_once(self):
        value = install.transport_manifest()
        self.assertEqual(value['version'], 1)
        self.assertEqual(value['japan']['hosts'], list(gateway.HOSTS))
        for url in (value['japan']['httpProxy'], value['japan']['status'], value['solver']['url']):
            self.assertRegex(url, r'^http://[a-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9/_-]*)?$')
        self.assertEqual(value['warp'], {'proxy': 'socks5h://warp:1080'})
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'source-transport.json'
            with mock.patch.object(install.os, 'chown', create=True):
                self.assertTrue(install.publish(target, value, 0o644))
                self.assertFalse(install.publish(target, value, 0o644))
            self.assertEqual(json.loads(target.read_text()), value)

    def test_manifest_keeps_the_proxy_name_the_importer_accepts(self):
        manifest = install.route_manifest()
        self.assertEqual(manifest['httpProxy'], 'http://suwayomi-jp-router:8080')
        self.assertRegex(manifest['revision'], r'^[a-f0-9]{64}$')
        for host in ('manga.fod.fujitv.co.jp', 'manga.line.me', 'sokuyomi.jp', 'soraraw.com'):
            self.assertIn(host, manifest['hosts'])

    def test_detach_removes_only_gateway_services_and_dependencies(self):
        overlay = {'services': {
            'suwayomi': {'image': 'pinned', 'volumes': ['/private:/data'],
                         'depends_on': {'suwayomi-jp-router': {'condition': 'service_started'}}},
            'importer': {'environment': {'TOKEN_FILE': '/data/token'}, 'depends_on': ['suwayomi']},
            'suwayomi-jp-vpn': {'image': 'x'}, 'suwayomi-jp-router': {'image': 'x'}}}
        changed = install.detach(overlay)
        self.assertEqual(sorted(changed['services']), ['importer', 'suwayomi'])
        self.assertNotIn('depends_on', changed['services']['suwayomi'])
        self.assertEqual(changed['services']['importer'], overlay['services']['importer'])
        self.assertEqual(changed['services']['suwayomi']['volumes'], ['/private:/data'])
        self.assertIn('suwayomi-jp-vpn', overlay['services'])
        self.assertEqual(install.detach(changed), changed)


class ComposeTests(unittest.TestCase):
    def setUp(self):
        try:
            import yaml
        except ImportError:
            self.skipTest('PyYAML not installed')
        self.compose = yaml.safe_load((ROOT / 'deploy/oracle/network/compose.yaml').read_text())

    def test_services_are_private_and_independent_of_suwayomi(self):
        services = self.compose['services']
        self.assertEqual(sorted(services), ['byparr', 'jp-router', 'jp-vpn', 'warp'])
        for name, service in services.items():
            with self.subTest(service=name):
                self.assertNotIn('ports', service)
                self.assertNotIn('network_mode', service)
                self.assertNotIn('depends_on', service)
                self.assertNotIn('suwayomi', json.dumps(service.get('volumes', [])))
                if name == 'warp':
                    # The WARP image needs sudo for its daemon; it adds only NET_ADMIN.
                    self.assertEqual(service['cap_add'], ['NET_ADMIN'])
                    self.assertRegex(service['image'], r'@sha256:[a-f0-9]{64}$')
                else:
                    self.assertEqual(service['cap_drop'], ['ALL'])
                self.assertIn('healthcheck', service)
        self.assertTrue(self.compose['networks']['sources']['external'])

    def test_legacy_names_stay_reachable_and_solver_is_pinned(self):
        services = self.compose['services']
        self.assertIn('suwayomi-jp-router', services['jp-router']['networks']['sources']['aliases'])
        self.assertIn('suwayomi-jp-vpn', services['jp-vpn']['networks']['sources']['aliases'])
        self.assertEqual(services['byparr']['networks']['sources']['aliases'], ['byparr'])
        self.assertEqual(services['byparr']['image'], install.BYPARR_IMAGE)
        self.assertNotIn('/health', json.dumps(services['byparr']['healthcheck']))
        self.assertEqual(services['jp-router']['user'], '65534:65534')


class GatewayPolicyTests(unittest.TestCase):
    """The reconnect policy, driven by fake processes and checks."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {name: getattr(gateway, name) for name in
                      ('STATE', 'connect', 'accept', 'tunnel_trace', 'resolves', 'pause', 'log', 'tun_up')}
        self.saved_popen = gateway.subprocess.Popen
        gateway.STATE = Path(self.tmp.name)
        gateway.STOP = False
        gateway.ROTATE.clear()
        gateway.connect = lambda config: Proc()
        gateway.accept = lambda vpn: {'ip': '203.0.113.5', 'loc': 'JP'}
        gateway.subprocess.Popen = lambda *a, **k: Proc()
        gateway.resolves = lambda host: True
        gateway.tun_up = lambda: True
        gateway.log = lambda *a, **k: None
        self.checks = []

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(gateway, name, value)
        gateway.subprocess.Popen = self.saved_popen
        gateway.STOP = False
        gateway.ROTATE.clear()
        self.tmp.cleanup()

    def drive(self, results, after=None):
        """Each pause consumes one scripted check result; then stop."""
        queue = list(results)

        def pause(seconds, children=(), tunnel=False):
            if not queue:
                gateway.STOP = True
                return
            item = queue.pop(0)
            if item == 'rotate':
                gateway.ROTATE.set()
            self.checks.append(item)

        def trace():
            item = self.checks[-1]
            if item == 'fail':
                raise subprocess.CalledProcessError(28, 'curl', stderr='timeout')
            return {'ip': item if item not in ('ok', 'rotate') else '203.0.113.5', 'loc': 'JP'}

        gateway.pause = pause
        gateway.tunnel_trace = trace
        return gateway.session(gateway.profile(PROFILE))

    def test_two_failed_checks_keep_the_tunnel(self):
        self.assertEqual(self.drive(['fail', 'fail', 'ok', 'fail', 'fail', 'ok']), 'stopped')
        status = json.loads((gateway.STATE / 'status.json').read_text())
        self.assertTrue(status['ready'])
        self.assertEqual(status['exit'], '203.0.113.5')

    def test_three_consecutive_failures_reconnect_explicitly(self):
        outcome = self.drive(['ok', 'fail', 'fail', 'fail'])
        self.assertEqual(outcome, 'failed')  # a short session is quarantined
        status = json.loads((gateway.STATE / 'status.json').read_text())
        self.assertFalse(status['ready'])
        self.assertEqual(status['state'], 'reconnecting')
        self.assertEqual(status['reason'], 'tunnel')

    def test_exit_change_bumps_generation_and_rotation_is_reported(self):
        self.assertEqual(self.drive(['ok', '198.51.100.7', 'rotate']), 'rotated')
        self.assertEqual(gateway.current_generation(), 2)
        status = json.loads((gateway.STATE / 'status.json').read_text())
        self.assertEqual((status['ready'], status['reason'], status['lastExit']), (False, 'rotate', '198.51.100.7'))

    def test_lost_tun_device_is_not_ready_and_reconnects(self):
        gateway.tun_up = lambda: False
        self.addCleanup(setattr, gateway, 'TUN_RESTORE_SECONDS', gateway.TUN_RESTORE_SECONDS)
        gateway.TUN_RESTORE_SECONDS = 0
        self.assertEqual(self.drive(['ok']), 'failed')
        status = json.loads((gateway.STATE / 'status.json').read_text())
        self.assertEqual((status['ready'], status['reason']), (False, 'tunnel'))

    def test_health_endpoint_reflects_readiness(self):
        gateway.STATUS_PORT = 0
        server = gateway.serve_status()
        port = server.server_address[1]
        try:
            gateway.status(False, 'reconnecting', reason='tunnel')
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=5)
            self.assertEqual(caught.exception.code, 503)
            gateway.status(True, 'ready', exit='203.0.113.5', generation=4)
            value = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=5).read())
            self.assertEqual((value['exit'], value['generation'], value['fresh']), ('203.0.113.5', 4, True))
            self.assertEqual(urllib.request.urlopen(f'http://127.0.0.1:{port}/status', timeout=5).status, 200)
        finally:
            server.shutdown()
            server.server_close()
            gateway.STATUS_PORT = 8090


if __name__ == '__main__':
    unittest.main()
