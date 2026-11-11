import base64
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('jp_deploy', ROOT / 'deploy/oracle/enable-suwayomi-japan.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)
gateway = deploy.gateway
PEM = '-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----'
PROFILE = 'client\ndev tun\nproto tcp\nremote 119.240.163.125 1270\n' + '\n'.join(f'<{k}>\n{PEM}\n</{k}>' for k in ('ca', 'cert', 'key'))


class JapaneseRouteTests(unittest.TestCase):
    def test_public_profile_is_rebuilt_with_tls_verification_and_is_restartable(self):
        result = gateway.profile(PROFILE)
        self.assertIn('remote-cert-tls server', result)
        self.assertIn('verify-x509-name opengw.net name', result)
        self.assertIn('tls-version-min 1.2', result)
        self.assertEqual(gateway.profile(result), result)

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

    def test_routing_is_scoped_to_publishers_in_a_chain_not_a_global_proxy(self):
        config = gateway.routing_config()
        self.assertTrue(config['bypasses'][0]['whitelist'])
        self.assertEqual(config['chains'][0]['hops'][0]['bypass'], 'publishers')
        self.assertNotIn('bypass', config['services'][0])
        self.assertNotIn('*', config['bypasses'][0]['matchers'])
        self.assertNotIn('.google.com', config['bypasses'][0]['matchers'])
        self.assertEqual(config['chains'][0]['hops'][0]['nodes'][0]['addr'], 'suwayomi-jp-vpn:1081')

    def test_overlay_preserves_source_data_other_services_and_exposes_no_ports(self):
        original = {'services': {'suwayomi': {'image': 'ghcr.io/suwayomi/suwayomi-server@sha256:' + 'a' * 64, 'volumes': ['/private:/data']}, 'importer': {'environment': {'TOKEN_FILE': '/data/token'}}}}
        changed = deploy.overlay(original, Path('/private/japan-egress'))
        self.assertEqual(changed['services']['importer'], original['services']['importer'])
        self.assertEqual(changed['services']['suwayomi']['volumes'], ['/private:/data'])
        for name in ['suwayomi-jp-vpn', 'suwayomi-jp-router']:
            self.assertNotIn('ports', changed['services'][name])
            self.assertNotIn('network_mode', changed['services'][name])
            self.assertTrue(changed['services'][name]['read_only'])
        self.assertNotIn('suwayomi-jp-vpn', original['services'])
        self.assertEqual(changed['services']['suwayomi-jp-router']['cap_drop'], ['ALL'])

    def test_settings_preserve_existing_account_and_are_idempotent(self):
        original = 'server.authPassword = "private"\nserver.socksProxyEnabled = false # default\nserver.socksProxyHost = ""\n'
        changed = deploy.settings(original)
        self.assertIn('server.authPassword = "private"', changed)
        self.assertIn('server.socksProxyHost = "suwayomi-jp-router"', changed)
        self.assertEqual(deploy.settings(changed), changed)
        self.assertEqual(changed.count('server.socksProxyEnabled ='), 1)
        # Suwayomi adds default comments when it saves the HOCON file.
        saved = changed.replace('server.socksProxyEnabled = true', 'server.socksProxyEnabled = true # default: false')
        self.assertEqual(deploy.settings(saved), saved)

    def test_deployment_refuses_public_or_unpinned_source(self):
        for source in [{'image': 'untrusted:latest'}, {'image': 'ghcr.io/suwayomi/suwayomi-server@sha256:a', 'ports': ['4567:4567']}, {'image': 'ghcr.io/suwayomi/suwayomi-server@sha256:a', 'network_mode': 'host'}]:
            with self.assertRaises(RuntimeError):
                deploy.overlay({'services': {'suwayomi': source}}, Path('/private'))


if __name__ == '__main__':
    unittest.main()
