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


def container_args(network, config):
    return ['docker', 'run', '-d', '--name', NAME, '--network', network,
            '--network-alias', 'flaresolverr', '--restart', 'unless-stopped',
            '--memory', '1536m', '--memory-swap', '1536m', '--cpus', '1.0',
            '--pids-limit', '256', '--shm-size', '256m',
            '--security-opt', 'no-new-privileges:true', '--cap-drop', 'ALL',
            '--log-opt', 'max-size=5m', '--log-opt', 'max-file=2',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=512m,mode=1777',
            '-v', str(config) + ':/config', '-e', 'LOG_LEVEL=info',
            '-e', 'LOG_HTML=false', '-e', 'TZ=Etc/UTC', IMAGE]


def validate_solver(container, network):
    if (container['Config']['Image'] != IMAGE
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
    owner = 'codex-private-source-solver-' + str(os.getpid())
    fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'owner': owner, 'time': time.time(), 'purpose': 'Enable private solver without restarting the indexer'}, stream)
    try:
        activate()
    finally:
        if json.loads(LOCK.read_text()).get('owner') == owner:
            LOCK.unlink()


def activate():
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
            existing = get(['docker', 'ps', '-aq', '--filter', 'name=^' + NAME + '$'])
            if existing:
                validate_solver(json.loads(get(['docker', 'inspect', existing]))[0], network)
                run(['docker', 'start', existing], stdout=log)
            else:
                run(['docker', 'pull', IMAGE], stdout=log)
                run(container_args(network, config), stdout=log)
                created = True
            for _ in range(45):
                try:
                    ready = execute("import requests,json;r=requests.get('http://flaresolverr:8191/health',timeout=5);r.raise_for_status();print(json.dumps({'ready':r.status_code==200}))")
                    if ready['ready']:
                        break
                except (ValueError, subprocess.CalledProcessError):
                    pass
                time.sleep(2)
            else:
                raise RuntimeError('Private solver did not become ready')
            if execute(runtime_code(SETTINGS)) != SETTINGS or execute(runtime_code()) != SETTINGS:
                raise RuntimeError('Solver settings did not persist')
            # Native Suwayomi settings updates persist immediately; prove it,
            # rather than restarting the service and interrupting source work.
            persisted = (source_root / 'server.conf').read_text()
            for field, value in SETTINGS.items():
                import re
                line = re.search(r'(?m)^server\.' + field + r'\s*=([^\n]*)', persisted)
                if not line or json.loads(line[1].split('#', 1)[0].strip()) != value:
                    raise RuntimeError('Solver setting was not written to server.conf')
        except Exception:
            execute(runtime_code(original))
            if created:
                run(['docker', 'rm', '-f', NAME], stdout=log)
            raise
        record = {'enabled': True, 'image': IMAGE, 'privateOnly': True, 'backup': str(backup),
                  'importerRestarted': False, 'suwayomiRestarted': False,
                  'importerRevision': importer['Config']['Labels'].get('org.opencontainers.image.revision')}
        (ROOT / 'installed.json').write_text(json.dumps(record, indent=2))
        print(json.dumps(record))


if __name__ == '__main__':
    main()
