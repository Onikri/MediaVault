import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('solver_runtime', Path(__file__).resolve().parents[1] / 'deploy/oracle/enable-suwayomi-flaresolverr.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class PrivateSolverTests(unittest.TestCase):
    def test_pinned_private_bounded_runtime(self):
        args = runtime.container_args('private_network', Path('/private/config'))
        self.assertTrue(args[-1].startswith('ghcr.io/flaresolverr/flaresolverr@sha256:'))
        self.assertNotIn('-p', args)
        self.assertNotIn('--publish', args)
        self.assertNotIn('--privileged', args)
        self.assertEqual(args[args.index('--network') + 1], 'private_network')
        self.assertEqual(args[args.index('--memory') + 1], '1536m')
        self.assertIn('LOG_HTML=false', args)

    def test_runtime_uses_only_private_authenticated_partial_settings(self):
        code = runtime.runtime_code(runtime.SETTINGS)
        compile(code, '<solver settings>', 'exec')
        self.assertIn('setSettings', code)
        self.assertIn('c.session.post', code)
        self.assertNotIn('resetSettings', code)
        self.assertNotIn('password', code)
        self.assertEqual(runtime.SETTINGS['flareSolverrUrl'], 'http://flaresolverr:8191')
        with self.assertRaises(ValueError):
            runtime.runtime_code({**runtime.SETTINGS, 'authMode': 'none'})

    def test_foreign_exposed_or_host_network_solver_is_not_adopted(self):
        base = {'Config': {'Image': runtime.IMAGE}, 'NetworkSettings': {'Networks': {'private': {}}, 'Ports': {'8191/tcp': None}}, 'HostConfig': {'NetworkMode': 'private', 'PortBindings': {}}}
        runtime.validate_solver(base, 'private')
        for field in ['image', 'host', 'port', 'network']:
            value = json.loads(json.dumps(base))
            if field == 'image': value['Config']['Image'] = 'untrusted:latest'
            if field == 'host': value['HostConfig']['NetworkMode'] = 'host'
            if field == 'port': value['HostConfig']['PortBindings'] = {'8191/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8191'}]}
            if field == 'network': value['NetworkSettings']['Networks'] = {'other': {}}
            with self.assertRaises(RuntimeError): runtime.validate_solver(value, 'private')

    def test_compatible_engine_has_pinned_arm_runtime_and_sufficient_browser_threads(self):
        args = runtime.container_args('private_network', Path('/private/config'), 'byparr')
        self.assertTrue(args[-1].startswith('ghcr.io/thephaseless/byparr@sha256:'))
        self.assertEqual(args[args.index('--pids-limit') + 1], '1024')
        self.assertIn('BROWSER_TIMEZONE=Europe/Berlin', args)
        self.assertNotIn('-p', args)
        self.assertEqual(runtime.engine_settings('byparr')['flareSolverrUrl'], 'http://byparr:8191')
