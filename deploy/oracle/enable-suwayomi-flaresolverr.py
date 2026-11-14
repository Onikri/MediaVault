#!/usr/bin/env python3
"""Enable the private solver through Suwayomi's live, persisted settings API.

No package upgrades, public ports, importer rebuild, or source restart. Existing
source routing, authentication, extensions and crawl queues remain in place.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import argparse
import re

IMAGE = 'ghcr.io/flaresolverr/flaresolverr@sha256:c80ae007ce2ccdcd217a12426e4f039ef763ff90738c808d38810c3e59323767'
NAME = 'mediavault-flaresolverr'
ROOT = Path('/opt/mediavault-suwayomi/.codex-local/flaresolverr')
LOCK = Path('/opt/mediavault/deploy.lock')
SETTINGS = {
    'flareSolverrEnabled': True,
    'flareSolverrUrl': 'http://flaresolverr:8191',
    'flareSolverrTimeout': 20,
    'flareSolverrSessionName': 'suwayomi',
    'flareSolverrSessionTtl': 30,
    'flareSolverrAsResponseFallback': True,
}
ENGINES = {
    'flaresolverr': {'image': IMAGE, 'memory': '1536m', 'pids': '512', 'shm': '256m', 'tmp': '512m', 'health': '/health'},
    'byparr': {'image': 'ghcr.io/thephaseless/byparr@sha256:c66fa161187b8fa527bfad7eefa2647ea1c553f77df68cbffd6fe83366d1787b',
               'memory': '2560m', 'pids': '1024', 'shm': '512m', 'tmp': '1g', 'health': '/docs'},
}


def engine_settings(engine):
    return {**SETTINGS, 'flareSolverrUrl': 'http://' + engine + ':8191', 'flareSolverrTimeout': 45 if engine == 'byparr' else 20}


def container_args(network, config, engine='flaresolverr'):
    selected = ENGINES[engine]
    args = ['docker', 'run', '-d', '--name', 'mediavault-' + engine, '--network', network,
            '--network-alias', engine, '--restart', 'unless-stopped',
            '--memory', selected['memory'], '--memory-swap', selected['memory'], '--cpus', '1.0',
            '--pids-limit', selected['pids'], '--shm-size', selected['shm'],
            '--security-opt', 'no-new-privileges:true', '--cap-drop', 'ALL',
            '--log-opt', 'max-size=5m', '--log-opt', 'max-file=2',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=' + selected['tmp'] + ',mode=1777',
            '-v', str(config) + ':/config', '-e', 'LOG_LEVEL=info',
            '-e', 'LOG_HTML=false', '-e', 'TZ=Etc/UTC']
    if engine == 'byparr':
        args += ['-e', 'BROWSER_TIMEZONE=Europe/Berlin', '-e', 'BROWSER_LOCALE=en-US']
    return args + [selected['image']]


def validate_solver(container, network, engine='flaresolverr'):
    if (container['Config']['Image'] != ENGINES[engine]['image']
            or network not in container['NetworkSettings']['Networks']
            or container['HostConfig'].get('NetworkMode') == 'host'
            or container['HostConfig'].get('PortBindings')
            or any(container['NetworkSettings'].get('Ports', {}).values())):
        raise RuntimeError('Existing solver differs; inspect it before replacing anything')


def runtime_code(settings=None):
    # Use only the existing private adapter's authenticated session. Do not add
    # a generic settings/proxy endpoint to the public MediaVault API.
    fields = ' '.join(SETTINGS)
    query = 'query { settings { ' + fields + ' } }'
    variables = {}
    if settings is not None:
        if set(settings) != set(SETTINGS):
            raise ValueError('Only solver settings may be changed')
        query = 'mutation($input: SetSettingsInput!) { setSettings(input:$input) { settings { ' + fields + ' } } }'
        variables = {'input': {'settings': settings}}
    return '''import json
from suwayomi_bridge import Client
c=Client()
try:
 r=c.session.post(c.root+'/api/graphql',json=%r,timeout=(3,15))
 r.raise_for_status();v=r.json()
 if v.get('errors'):raise RuntimeError('Suwayomi rejected the solver settings')
 data=v['data'];print(json.dumps(data.get('setSettings',data)['settings']))
finally:c.close()
''' % {'query': query, 'variables': variables}


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo on the existing VM')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=ENGINES, default='flaresolverr')
    parser.add_argument('--source-id', action='append', default=[], help='Source ID verified by a separate real search test')
    parser.add_argument('--reader-source-id', action='append', default=[], help='Subset also verified through a chapter and image')
    args = parser.parse_args()
    if (len(args.source_id) > 128 or any(not re.fullmatch(r'\d{1,20}', s) for s in [*args.source_id, *args.reader_source_id])
            or not set(args.reader_source_id).issubset(args.source_id)):
        parser.error('Use verified numeric source IDs; reader IDs must be a subset')
    owner = 'codex-private-source-solver-' + str(os.getpid())
    fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'owner': owner, 'time': time.time(), 'purpose': 'Enable private solver without restarting the indexer'}, stream)
    try:
        activate(args.engine, args.source_id, args.reader_source_id)
    finally:
        if json.loads(LOCK.read_text()).get('owner') == owner:
            LOCK.unlink()


def activate(engine='flaresolverr', source_ids=(), reader_ids=()):
    selected = ENGINES[engine]
    name = 'mediavault-' + engine
    desired = engine_settings(engine)
    backup = ROOT / 'backups' / time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    backup.mkdir(parents=True, mode=0o700)
    with (backup / 'operation.log').open('a') as log:
        def run(args, **options):
            return subprocess.run(args, check=True, stderr=log, timeout=600, **options)

        def get(args):
            return run(args, stdout=subprocess.PIPE, text=True).stdout.strip()

        def execute(code):
            return json.loads(run(['docker', 'exec', '-i', importer['Id'], 'python', '-'], input=code,
                                  stdout=subprocess.PIPE, text=True).stdout)

        containers = json.loads(get(['docker', 'inspect', *get(['docker', 'ps', '-q']).split()]))
        def one(service):
            found = [c for c in containers if c['Config'].get('Labels', {}).get('com.docker.compose.service') == service]
            if len(found) != 1:
                raise RuntimeError('Expected one running ' + service)
            return found[0]
        importer, source = one('importer'), one('suwayomi')
        shared = set(importer['NetworkSettings']['Networks']) & set(source['NetworkSettings']['Networks'])
        if len(shared) != 1:
            raise RuntimeError('Expected one shared private network')
        network = shared.pop()
        config = ROOT / 'config'
        config.mkdir(exist_ok=True, mode=0o700)
        os.chown(config, 1000, 1000)
        original = execute(runtime_code())
        (backup / 'settings.json').write_text(json.dumps(original))
        source_root = Path(next(m['Source'] for m in source['Mounts'] if m['Destination'].endswith('/Tachidesk') and (Path(m['Source']) / 'server.conf').is_file()))
        shutil.copy2(source_root / 'server.conf', backup / 'server.conf')
        created = False
        try:
            existing = get(['docker', 'ps', '-aq', '--filter', 'name=^' + name + '$'])
            if existing:
                validate_solver(json.loads(get(['docker', 'inspect', existing]))[0], network, engine)
                run(['docker', 'update', '--pids-limit', selected['pids'], existing], stdout=log)
                run(['docker', 'start', existing], stdout=log)
            else:
                run(['docker', 'pull', selected['image']], stdout=log)
                run(container_args(network, config, engine), stdout=log)
                created = True
            for _ in range(45):
                try:
                    ready = execute("import requests,json;r=requests.get(" + repr('http://' + engine + ':8191' + selected['health']) + ",timeout=5);r.raise_for_status();print(json.dumps({'ready':r.status_code==200}))")
                    if ready['ready']:
                        break
                except (ValueError, subprocess.CalledProcessError):
                    pass
                time.sleep(2)
            else:
                raise RuntimeError('Private solver did not become ready')
            if execute(runtime_code(desired)) != desired or execute(runtime_code()) != desired:
                raise RuntimeError('Solver settings did not persist')
            # Native Suwayomi settings updates persist immediately; prove it,
            # rather than restarting the service and interrupting source work.
            persisted = (source_root / 'server.conf').read_text()
            for field, value in desired.items():
                line = re.search(r'(?m)^server\.' + field + r'\s*=([^\n]*)', persisted)
                if not line or json.loads(line[1].split('#', 1)[0].strip()) != value:
                    raise RuntimeError('Solver setting was not written to server.conf')
            if source_ids:
                manifest = {'engine': engine, 'requestTimeout': 60, 'sourceIds': sorted(set(source_ids))}
                code = "import json;from manga_solver import configure;print(json.dumps(configure(" + repr(manifest) + ',' + repr(list(reader_ids)) + ")))"
                recovered = execute(code)
            else:
                recovered = {}
        except Exception:
            execute(runtime_code(original))
            if created:
                run(['docker', 'rm', '-f', name], stdout=log)
            raise
        record = {'enabled': True, 'engine': engine, 'image': selected['image'], 'privateOnly': True, 'backup': str(backup), 'recovered': recovered,
                  'importerRestarted': False, 'suwayomiRestarted': False,
                  'importerRevision': importer['Config']['Labels'].get('org.opencontainers.image.revision')}
        (ROOT / 'installed.json').write_text(json.dumps(record, indent=2))
        print(json.dumps(record))


if __name__ == '__main__':
    main()
