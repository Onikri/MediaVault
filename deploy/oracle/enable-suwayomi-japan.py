#!/usr/bin/env python3
"""Install a private, publisher-scoped Japanese route on the existing VM."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('jp_gateway', HERE / 'japan-egress/gateway.py')
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


def overlay(original, root):
    changed = copy.deepcopy(original)
    source = changed['services']['suwayomi']
    if not source.get('image', '').startswith('ghcr.io/suwayomi/suwayomi-server@sha256:') or source.get('ports') or source.get('network_mode') == 'host':
        raise RuntimeError('Expected the existing private pinned Suwayomi service')
    shared = {
        'image': 'mediavault-suwayomi-japan:' + hashlib.sha256(
            (HERE / 'japan-egress/Dockerfile').read_bytes() + (HERE / 'japan-egress/gateway.py').read_bytes()
        ).hexdigest()[:12], 'restart': 'unless-stopped',
        'read_only': True, 'security_opt': ['no-new-privileges:true'], 'cap_drop': ['ALL'],
        'pids_limit': 64, 'cpus': 0.3, 'mem_limit': '128m',
        'logging': {'driver': 'json-file', 'options': {'max-size': '5m', 'max-file': '2'}},
    }
    changed['services']['suwayomi-jp-vpn'] = {
        **shared, 'build': {'context': str(root / 'app')},
        'cap_add': ['NET_ADMIN', 'SETUID', 'SETGID', 'KILL'],
        'devices': ['/dev/net/tun:/dev/net/tun'], 'dns': ['1.1.1.1'],
        'volumes': [str(root / '.codex-local/state') + ':/state'],
        'tmpfs': ['/tmp:size=16m', '/run:size=4m'],
        'healthcheck': {'test': ['CMD', 'python', '-c', "import json,time;v=json.load(open('/state/status.json'));assert v['ready'] and time.time()-v['time']<120"],
                        'interval': '30s', 'timeout': '5s', 'start_period': '120s', 'retries': 3},
    }
    changed['services']['suwayomi-jp-router'] = {
        **shared, 'user': '65534:65534', 'mem_limit': '64m',
        'environment': {'HOME': '/tmp'}, 'tmpfs': ['/tmp:size=4m,uid=65534,gid=65534,mode=0700'],
        'command': ['/usr/local/bin/gost', '-C', '/app/router.json'],
        'volumes': [str(root / 'app/router.json') + ':/app/router.json:ro'],
    }
    source.setdefault('depends_on', {})['suwayomi-jp-router'] = {'condition': 'service_started'}
    return changed


def settings(text):
    values = {'Enabled': True, 'Version': 5, 'Host': 'suwayomi-jp-router', 'Port': '1080', 'Username': '', 'Password': ''}
    for key, value in values.items():
        name = 'server.socksProxy' + key
        line = name + ' = ' + json.dumps(value)
        pattern = r'(?m)^' + re.escape(name) + r'\s*=.*$'
        existing = re.search(pattern, text)
        if existing:
            try:
                if json.loads(existing[0].split('=', 1)[1].split('#', 1)[0].strip()) == value:
                    continue
            except ValueError:
                pass
        text = re.sub(pattern, lambda _: line, text) if re.search(pattern, text) else text.rstrip() + '\n' + line + '\n'
    return text


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo on the existing VM')
    root = Path('/opt/mediavault-suwayomi/japan-egress')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = root / '.codex-local/backups' / time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    backup.mkdir(parents=True, mode=0o700)
    log = (backup / 'operation.log').open('a')
    def get(args):
        return subprocess.check_output(args, text=True, stderr=log).strip()
    def run(args):
        subprocess.run(args, check=True, stdout=log, stderr=log)
    containers = json.loads(get(['docker', 'inspect', *get(['docker', 'ps', '-q']).split()]))
    def one(name):
        rows = [c for c in containers if c['Config'].get('Labels', {}).get('com.docker.compose.service') == name]
        if len(rows) != 1:
            raise RuntimeError('Expected one ' + name)
        return rows[0]
    importer, source = one('importer'), one('suwayomi')
    labels = source['Config']['Labels']
    work = Path(labels['com.docker.compose.project.working_dir'])
    files = labels['com.docker.compose.project.config_files'].split(',')
    target = work / 'suwayomi.yaml'
    config = Path('/opt/mediavault-suwayomi/data/server.conf')
    if str(target) not in files:
        raise RuntimeError('Existing Suwayomi overlay not found')
    data = Path(next(m['Source'] for m in importer['Mounts'] if m['Destination'] == '/data'))
    with sqlite3.connect('file:' + str(data / 'tasks.sqlite') + '?mode=ro', uri=True) as db:
        if db.execute("SELECT count(*) FROM tasks WHERE status IN ('queued','running','cancelling')").fetchone()[0]:
            raise RuntimeError('Wait for active imports before restarting sources')
    private = [work / '.env', data / 'service.key', data / 'suwayomi-auth.json']
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in private}
    previous = json.loads(target.read_text())
    had_gateway = 'suwayomi-jp-vpn' in previous['services']
    for path in (target, config):
        shutil.copy2(path, backup / path.name)
    app = root / 'app'
    app.mkdir(exist_ok=True, mode=0o755)
    for name in ('Dockerfile', 'gateway.py'):
        shutil.copy2(HERE / 'japan-egress' / name, app / name)
    (app / 'router.json').write_text(json.dumps(gateway.routing_config()))
    (app / 'router.json').chmod(0o644)
    state = root / '.codex-local/state'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Optional tested public VPN Gate seed. No personal certificates are accepted.
    seed = HERE / '.codex-local/japan-seed.ovpn'
    if seed.exists() and not (state / 'last-good.ovpn').exists():
        (state / 'last-good.ovpn').write_text(gateway.profile(seed.read_text()))
        (state / 'last-good.ovpn').chmod(0o600)
    base = ['docker', 'compose', '--project-directory', str(work), '-p', labels['com.docker.compose.project']]
    for file in files:
        base += ['-f', file]
    try:
        target.write_text(json.dumps(overlay(previous, root), indent=2) + '\n')
        target.chmod(0o600)
        run([*base, 'config', '--quiet'])
        run([*base, 'build', 'suwayomi-jp-vpn'])
        activated = time.time()
        run([*base, 'up', '-d', '--no-deps', 'suwayomi-jp-vpn', 'suwayomi-jp-router'])
        for _ in range(75):
            try:
                status = json.loads((state / 'status.json').read_text())
                if status['ready'] and time.time() - status['time'] < 100 and status['time'] >= activated:
                    break
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(2)
        else:
            raise RuntimeError('Japanese gateway failed readiness; source configuration preserved')
        current = config.read_text()
        desired = settings(current)
        if current != desired:
            config.write_text(desired)
            run([*base, 'up', '-d', '--no-deps', '--force-recreate', 'suwayomi'])
        probe = "from suwayomi_bridge import Client;c=Client();v=c.get('/source/list',timeout=5);c.close();assert v;print(len(v))"
        for _ in range(60):
            try:
                count = int(get(['docker', 'exec', importer['Id'], 'python', '-c', probe]))
                break
            except (ValueError, subprocess.CalledProcessError):
                time.sleep(2)
        else:
            raise RuntimeError('Suwayomi failed readiness')
        if {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in private} != before:
            raise RuntimeError('Private configuration changed unexpectedly')
    except Exception:
        if not had_gateway:
            run([*base, 'rm', '--stop', '--force', 'suwayomi-jp-vpn', 'suwayomi-jp-router'])
        for path in (target, config):
            shutil.copy2(backup / path.name, path)
        if had_gateway:
            run([*base, 'up', '-d', '--no-deps', 'suwayomi-jp-vpn', 'suwayomi-jp-router'])
        run([*base, 'up', '-d', '--no-deps', '--force-recreate', 'suwayomi'])
        raise
    print(json.dumps({'japaneseRoute': True, 'privateOnly': True, 'sources': count, 'backup': str(backup), 'accountConfigurationPreserved': True}))


if __name__ == '__main__':
    main()
