#!/usr/bin/env python3
"""Install or migrate MediaVault's source network services on the Oracle VM.

Runs the Japan VPN gateway (`mediavault-jp-vpn`), its domain router
(`mediavault-jp-router`) and the Byparr solver (`mediavault-byparr`) as the
standalone Compose project `mediavault-network` under /opt/mediavault-network.
They no longer belong to Suwayomi's Compose project or its directories.

Migration from the Suwayomi overlay keeps the network names the importer and
Suwayomi already use (`suwayomi-jp-router`, `suwayomi-jp-vpn`, `byparr`) as
aliases. Order: the new gateway must be ready before the old router and VPN
are removed; a failed route check restores the old services. Takes the shared
deploy lock. Does not stop, restart or reconfigure Suwayomi.

    sudo python3 deploy/oracle/install-network-services.py [--allow-active]
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'network'
ROOT = Path('/opt/mediavault-network')
LOCK = Path('/opt/mediavault/deploy.lock')
PROJECT = 'mediavault-network'
OLD_STATE = Path('/opt/mediavault-suwayomi/japan-egress/.codex-local/state')
LEGACY = ('suwayomi-jp-vpn', 'suwayomi-jp-router')
ROUTE_PROXY = 'http://suwayomi-jp-router:8080'
BYPARR = 'mediavault-byparr'
BYPARR_IMAGE = 'ghcr.io/thephaseless/byparr@sha256:c66fa161187b8fa527bfad7eefa2647ea1c553f77df68cbffd6fe83366d1787b'
# Cloudflare-fronted hosts: /cdn-cgi/trace reports the exit seen by the site.
ROUTED_TRACE = 'https://soraraw.com/cdn-cgi/trace'
DIRECT_TRACE = 'https://www.cloudflare.com/cdn-cgi/trace'

spec = importlib.util.spec_from_file_location('jp_gateway', SOURCE / 'jp-gateway/gateway.py')
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


def image_tag():
    digest = hashlib.sha256()
    for name in ('Dockerfile', 'gateway.py'):
        digest.update((SOURCE / 'jp-gateway' / name).read_bytes())
    return digest.hexdigest()[:12]


def route_manifest():
    revision = hashlib.sha256(json.dumps(gateway.routing_config(), sort_keys=True).encode()).hexdigest()
    return {'revision': revision, 'hosts': list(gateway.HOSTS), 'httpProxy': ROUTE_PROXY}


def detach(overlay):
    """Suwayomi's overlay without the gateway services or dependencies on them."""
    changed = copy.deepcopy(overlay)
    services = changed.get('services', {})
    for name in LEGACY:
        services.pop(name, None)
    for service in services.values():
        depends = service.get('depends_on')
        if isinstance(depends, dict):
            for name in LEGACY:
                depends.pop(name, None)
            if not depends:
                service.pop('depends_on')
        elif isinstance(depends, list):
            service['depends_on'] = [name for name in depends if name not in LEGACY]
            if not service['depends_on']:
                service.pop('depends_on')
    return changed


def env_text(tag, network):
    return f'JP_GATEWAY_TAG={tag}\nSOURCES_NETWORK={network}\n'


def trace_code(url, proxy):
    return ('import json,requests\n'
            f'r=requests.get({url!r},proxies={{"https":{proxy!r}}},timeout=(5,20))\n'
            'r.raise_for_status()\n'
            'v=dict(l.split("=",1) for l in r.text.splitlines() if "=" in l)\n'
            'print(json.dumps({"ip":v.get("ip"),"loc":v.get("loc")}))\n')


class Installer:
    def __init__(self, allow_active=False):
        self.allow_active = allow_active
        self.backup = ROOT / 'backups' / time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        self.backup.mkdir(parents=True, mode=0o700)
        self.log = (self.backup / 'operation.log').open('a')
        self.compose = ['docker', 'compose', '--project-directory', str(ROOT), '-p', PROJECT, '-f', str(ROOT / 'compose.yaml')]

    def run(self, args, **options):
        self.log.write('$ ' + ' '.join(map(str, args)) + '\n')
        self.log.flush()
        return subprocess.run(args, check=True, stdout=self.log, stderr=self.log, timeout=1800, **options)

    def get(self, args, **options):
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=120, **options).stdout.strip()

    def containers(self):
        ids = self.get(['docker', 'ps', '-aq']).split()
        return json.loads(self.get(['docker', 'inspect', *ids])) if ids else []

    def exec_importer(self, code, timeout=60):
        return subprocess.run(['docker', 'exec', '-i', self.importer['Id'], 'python', '-'], input=code, check=True,
                              capture_output=True, text=True, timeout=timeout).stdout.strip()

    def stage(self, network, data):
        for path in (ROOT, ROOT / 'jp-gateway', ROOT / 'state', ROOT / 'state/jp'):
            path.mkdir(exist_ok=True, mode=0o700 if 'state' in path.parts else 0o755)
        (ROOT / 'state/jp').chmod(0o700)
        byparr = ROOT / 'byparr'
        byparr.mkdir(exist_ok=True, mode=0o700)
        os.chown(byparr, 1000, 1000)
        shutil.copy2(SOURCE / 'compose.yaml', ROOT / 'compose.yaml')
        for name in ('Dockerfile', 'gateway.py'):
            shutil.copy2(SOURCE / 'jp-gateway' / name, ROOT / 'jp-gateway' / name)
        router = ROOT / 'jp-gateway/router.json'
        router.write_text(json.dumps(gateway.routing_config()))
        router.chmod(0o644)
        (ROOT / '.env').write_text(env_text(image_tag(), network))
        saved = ROOT / 'state/jp/last-good.ovpn'
        if not saved.exists() and (OLD_STATE / 'last-good.ovpn').exists():
            saved.write_text(gateway.profile((OLD_STATE / 'last-good.ovpn').read_text()))
            saved.chmod(0o600)

    def wait_gateway(self, since, limit=900):
        status = ROOT / 'state/jp/status.json'
        deadline = time.time() + limit
        while time.time() < deadline:
            try:
                value = json.loads(status.read_text())
                if value.get('ready') and value['time'] >= since and time.time() - value['time'] < 100:
                    health = json.loads(self.exec_importer(
                        'import json,urllib.request\n'
                        'print(urllib.request.urlopen("http://jp-vpn:8090/health",timeout=5).read().decode())\n'))
                    if health.get('ready') and health.get('exit'):
                        return health
            except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                pass
            time.sleep(5)
        raise RuntimeError('Japan gateway did not become ready')

    def verify_route(self):
        last = None
        for _ in range(6):
            try:
                routed = json.loads(self.exec_importer(trace_code(ROUTED_TRACE, ROUTE_PROXY)))
                direct = json.loads(self.exec_importer(trace_code(DIRECT_TRACE, ROUTE_PROXY)))
                if routed['loc'] == 'JP' and direct['loc'] != 'JP':
                    return {'routed': routed, 'direct': direct}
                last = {'routed': routed, 'direct': direct}
            except (ValueError, KeyError, subprocess.SubprocessError) as error:
                last = type(error).__name__
            time.sleep(5)
        raise RuntimeError(f'Route check failed: {last}')

    def wait_byparr(self):
        for _ in range(30):
            try:
                if self.exec_importer('import urllib.request\n'
                                      'print(urllib.request.urlopen("http://byparr:8191/docs",timeout=5).status)\n') == '200':
                    return
            except subprocess.SubprocessError:
                pass
            time.sleep(3)
        raise RuntimeError('Byparr did not answer /docs')

    def install(self):
        containers = self.containers()

        def service(name, project=None):
            return [c for c in containers if c['Config'].get('Labels', {}).get('com.docker.compose.service') == name
                    and (project is None or c['Config']['Labels'].get('com.docker.compose.project') == project)]

        importers = [c for c in service('importer') if c['State']['Running']]
        if len(importers) != 1:
            raise RuntimeError('Expected one running importer')
        self.importer = importers[0]
        labels = self.importer['Config']['Labels']
        project = labels['com.docker.compose.project']
        networks = list(self.importer['NetworkSettings']['Networks'])
        if len(networks) != 1:
            raise RuntimeError('Expected the importer on one private network')
        network = networks[0]
        data = Path(next(m['Source'] for m in self.importer['Mounts'] if m['Destination'] == '/data'))
        with sqlite3.connect('file:' + str(data / 'tasks.sqlite') + '?mode=ro', uri=True) as db:
            active = db.execute("SELECT count(*) FROM tasks WHERE status IN ('queued','running','cancelling')").fetchone()[0]
        if active and not self.allow_active:
            raise RuntimeError(f'{active} active imports; wait or pass --allow-active')

        self.stage(network, data)
        self.run([*self.compose, 'config', '--quiet'])
        self.run([*self.compose, 'build', 'jp-vpn'])

        legacy = [c for name in LEGACY for c in service(name, project)]
        work = Path(labels['com.docker.compose.project.working_dir'])
        files = labels['com.docker.compose.project.config_files'].split(',')
        overlay_path = work / 'suwayomi.yaml'
        overlay = json.loads(overlay_path.read_text()) if str(overlay_path) in files and overlay_path.exists() else None
        legacy_compose = ['docker', 'compose', '--project-directory', str(work), '-p', project]
        for file in files:
            legacy_compose += ['-f', file]

        # 1. New gateway beside the old one (alias suwayomi-jp-vpn resolves to both).
        started = time.time()
        self.run([*self.compose, 'up', '-d', '--no-deps', 'jp-vpn'])
        try:
            health = self.wait_gateway(started)
        except Exception:
            if legacy:
                self.run([*self.compose, 'rm', '--stop', '--force', 'jp-vpn'])
            raise

        # 2. Swap the router: remove the Suwayomi-owned services, start ours.
        detached = overlay is not None and detach(overlay) != overlay
        if detached:
            shutil.copy2(overlay_path, self.backup / 'suwayomi.yaml')
            overlay_path.write_text(json.dumps(detach(overlay), indent=2) + '\n')
            overlay_path.chmod(0o600)
        try:
            if detached:
                self.run([*legacy_compose, 'config', '--quiet'])
            for container in legacy:
                self.run(['docker', 'rm', '--force', container['Id']])
            self.run([*self.compose, 'up', '-d', '--no-deps', 'jp-router'])
            route = self.verify_route()
        except Exception:
            self.run([*self.compose, 'rm', '--stop', '--force', 'jp-router'])
            if detached:
                shutil.copy2(self.backup / 'suwayomi.yaml', overlay_path)
            if legacy:
                self.run([*legacy_compose, 'up', '-d', '--no-deps', *LEGACY])
            raise

        # 3. Byparr: adopt the same pinned image under this project.
        existing = [c for c in containers if c['Name'] == '/' + BYPARR]
        previous = None
        if existing and existing[0]['Config']['Labels'].get('com.docker.compose.project') != PROJECT:
            if existing[0]['Config']['Image'] != BYPARR_IMAGE:
                raise RuntimeError('Existing Byparr runs another image; inspect it before replacing')
            previous = BYPARR + '-before-network'
            self.run(['docker', 'rename', BYPARR, previous])
            self.run(['docker', 'stop', previous])
        try:
            self.run([*self.compose, 'up', '-d', '--no-deps', 'byparr'])
            self.wait_byparr()
        except Exception:
            if previous:
                self.run([*self.compose, 'rm', '--stop', '--force', 'byparr'])
                self.run(['docker', 'rename', previous, BYPARR])
                self.run(['docker', 'start', BYPARR])
            raise
        if previous:
            self.run(['docker', 'rm', previous])

        # 4. Route manifest for the importer; a new revision resets stale quarantines.
        manifest = route_manifest()
        target = data / 'manga-source-routes.json'
        try:
            current = json.loads(target.read_text())
        except (OSError, ValueError):
            current = None
        if current != manifest:
            temporary = data / '.manga-source-routes.json.tmp'
            temporary.write_text(json.dumps(manifest))
            temporary.chmod(0o600)
            os.chown(temporary, 1000, 1000)
            temporary.replace(target)

        record = {'project': PROJECT, 'root': str(ROOT), 'network': network, 'gatewayImage': 'mediavault-jp-gateway:' + image_tag(),
                  'byparrImage': BYPARR_IMAGE, 'exit': health.get('exit'), 'generation': health.get('generation'),
                  'route': route, 'legacyRemoved': [c['Name'].lstrip('/') for c in legacy], 'overlayDetached': detached,
                  'routeRevision': manifest['revision'], 'backup': str(self.backup), 'suwayomiTouched': False}
        (ROOT / 'installed.json').write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--allow-active', action='store_true', help='Proceed while imports are queued or running')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo on the VM')
    owner = 'install-network-services-' + str(os.getpid())
    try:
        fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit('Deploy lock held: ' + LOCK.read_text()[:300]) from None
    with os.fdopen(fd, 'w') as stream:
        json.dump({'owner': owner, 'name': 'claude-network-services', 'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                   'purpose': 'Move JP gateway + Byparr out of the Suwayomi project'}, stream)
    try:
        ROOT.mkdir(exist_ok=True, mode=0o755)
        Installer(args.allow_active).install()
    finally:
        try:
            if json.loads(LOCK.read_text()).get('owner') == owner:
                LOCK.unlink()
        except (OSError, ValueError):
            pass


if __name__ == '__main__':
    main()
