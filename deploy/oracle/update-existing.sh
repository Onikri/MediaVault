#!/usr/bin/env bash
# Existing VM only. Discover its Compose installation; never provision resources.
set -euo pipefail
umask 077
revision="${1:?Pass the reviewed 40-character Git commit}"
[[ "$revision" =~ ^[a-f0-9]{40}$ ]] || { echo 'Expected an immutable commit SHA.' >&2; exit 2; }
python3 - "$@" <<'PY'
import contextlib, hashlib, json, os, shutil, sqlite3, subprocess, sys, tarfile, time
from pathlib import Path
revision=sys.argv[1]
resume_active=len(sys.argv)==3 and sys.argv[2]=='--resume-active-jobs'
if len(sys.argv)>2 and not resume_active:raise SystemExit('Unknown update option.')
def command(args, **kwargs):return subprocess.check_output(args,text=True,**kwargs).strip()
def execute(args, **kwargs):subprocess.run(args,check=True,**kwargs)
ids=command(['docker','ps','-q']).split()
containers=json.loads(command(['docker','inspect',*ids])) if ids else []
matches=[c for c in containers if (c.get('Config',{}).get('Labels') or {}).get('com.docker.compose.service')=='importer']
if len(matches)!=1:raise SystemExit('Expected one running Compose importer. Inspect the installation first.')
old=matches[0];labels=old['Config']['Labels']
work=Path(labels['com.docker.compose.project.working_dir']).resolve()
files=[Path(p).resolve() for p in labels['com.docker.compose.project.config_files'].split(',')]
mounts=[m for m in old['Mounts'] if m['Destination']=='/data']
if len(mounts)!=1 or mounts[0]['Type']!='bind':raise SystemExit('Expected one existing /data bind mount; refusing to create a replacement.')
data=Path(mounts[0]['Source']).resolve()
env=work/'.env';key=data/'service.key';database=data/'tasks.sqlite'
if not all(p.is_file() for p in [*files,env,key,database]):raise SystemExit('Existing installation files are missing; no changes made.')
base=['docker','compose','--project-directory',str(work),'-p',labels['com.docker.compose.project']]
for path in files:base+=['-f',str(path)]
health_code='import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen("http://127.0.0.1:7860/health",timeout=3))))'
before_health=json.loads(command(['docker','exec',old['Id'],'python','-c',health_code]))
if before_health.get('application')!='MediaVault':raise SystemExit('The selected importer is not MediaVault.')
def state():
    with contextlib.closing(sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True)) as db:
        active=db.execute("SELECT count(*) FROM tasks WHERE status IN ('queued','running','cancelling')").fetchone()[0]
        tasks=db.execute('SELECT count(*) FROM tasks').fetchone()[0]
        cancelling=db.execute("SELECT count(*) FROM tasks WHERE status='cancelling'").fetchone()[0]
        payloads={identity:hashlib.sha256(payload).hexdigest() for identity,payload in db.execute('SELECT id,data FROM tasks')}
        settings=db.execute('SELECT name,value FROM settings ORDER BY name').fetchall()
    return {'active':active,'tasks':tasks,'cancelling':cancelling,'payloads':payloads,'settings':hashlib.sha256(repr(settings).encode()).hexdigest(),
            'env':hashlib.sha256(env.read_bytes()).hexdigest(),'key':hashlib.sha256(key.read_bytes()).hexdigest()}
initial=state()
if initial['cancelling'] or initial['active'] and not resume_active:raise SystemExit('Wait for current imports to finish before updating.')
release=Path('/opt/mediavault-releases')/revision
release.mkdir(parents=True,exist_ok=True)
log=work/'.codex-local'/'logs'/('mediavault-update-'+revision[:12]+'.log')
log.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
image='mediavault-importer:'+revision[:12]
with log.open('w') as output:
    if not (release/'.git').exists():
        execute(['git','init','-q',str(release)],stdout=output,stderr=output)
        execute(['git','-C',str(release),'remote','add','origin','https://github.com/Onikri/MediaVault.git'],stdout=output,stderr=output)
    if command(['git','-C',str(release),'remote','get-url','origin'])!='https://github.com/Onikri/MediaVault.git':raise SystemExit('Unexpected release repository.')
    if command(['git','-C',str(release),'status','--porcelain']):raise SystemExit('Release checkout has local changes; preserve them first.')
    execute(['git','-C',str(release),'fetch','--depth=1','origin',revision],stdout=output,stderr=output)
    execute(['git','-C',str(release),'checkout','--detach','FETCH_HEAD'],stdout=output,stderr=output)
    if command(['git','-C',str(release),'rev-parse','HEAD'])!=revision:raise SystemExit('Release SHA mismatch.')
    execute(['docker','build','--label','org.opencontainers.image.revision='+revision,'-t',image,str(release/'server')],stdout=output,stderr=output)
expected_version=int(command(['docker','run','--rm','--network','none','--entrypoint','python',image,'-c','import api; print(api.health()["version"])']))
if expected_version<6:raise SystemExit('The release does not support voice discovery; no replacement made.')
override=work/('release-'+revision[:12]+'.yaml')
if override.exists():raise SystemExit('Release override already exists. Inspect the previous attempt before retrying.')
override.write_text('services:\n  importer:\n    image: '+image+'\n')
updated=[*base,'-f',str(override)]
maintenance=work/('maintenance-'+revision[:12]+'.yaml')
maintenance.write_text('services:\n  importer:\n    environment:\n      MEDIA_VAULT_DISABLE_WORKER: "1"\n')
paused=[*updated,'-f',str(maintenance)]
backup=Path('/opt/mediavault-backups')/(time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+revision[:12])
backup.mkdir(parents=True,mode=0o700);os.chmod(backup.parent,0o700)
stopped=False
try:
    now=state()
    if now['cancelling'] or now['active'] and not resume_active:raise RuntimeError('Imports became active during build; update postponed.')
    execute([*base,'stop','importer'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);stopped=True
    before=state()
    needed=sum(p.stat().st_size for p in data.rglob('*') if p.is_file())
    if shutil.disk_usage(backup).free<needed+512*1024**2:raise RuntimeError('Insufficient disk space for a complete private backup.')
    with tarfile.open(backup/'private-data.tar.gz','w:gz') as archive:
        archive.add(data,arcname='data')
        for i,path in enumerate(dict.fromkeys([env,*files,work/'Caddyfile'])):
            if path.exists():archive.add(path,arcname='configuration/'+str(i)+'-'+path.name)
    os.chmod(backup/'private-data.tar.gz',0o600)
    with tarfile.open(backup/'private-data.tar.gz') as archive:
        if 'data/service.key' not in archive.getnames() or 'data/tasks.sqlite' not in archive.getnames():raise RuntimeError('Private backup verification failed.')
    (backup/'rollback.json').write_text(json.dumps({'compose':base,'image':old['Image'],'data':str(data),'revision':revision}))
    # Validate the retained queue before allowing the new worker to change it.
    execute([*paused,'up','-d','--no-deps','--no-build','--force-recreate','importer'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for attempt in range(45):
        try:
            current=json.loads(command([*paused,'exec','-T','importer','python','-c',health_code],stderr=subprocess.DEVNULL))
            if current.get('version')==expected_version and current.get('voiceDiscovery'):break
        except (subprocess.CalledProcessError,ValueError):pass
        time.sleep(2)
    else:raise RuntimeError('Release backend health check failed.')
    if expected_version>=23:
        # Public application identifiers, fetched from checksummed upstream
        # source once and retained in the existing private data volume.
        execute([*paused,'exec','-T','importer','python','-m','novelcool_client'],stdout=subprocess.DEVNULL)
    cid=command([*paused,'ps','-q','importer']);new=json.loads(command(['docker','inspect',cid]))[0]
    mount=next(m for m in new['Mounts'] if m['Destination']=='/data');after=state()
    if Path(mount['Source']).resolve()!=data or any(before[k]!=after[k] for k in ['settings','env','key']) or any(after['payloads'].get(k)!=v for k,v in before['payloads'].items()):raise RuntimeError('Preservation check failed.')
    if current.get('oauthConfigured')!=before_health.get('oauthConfigured'):raise RuntimeError('OAuth readiness changed.')
    execute([*updated,'up','-d','--no-deps','--no-build','--force-recreate','importer'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for attempt in range(45):
        try:
            current=json.loads(command([*updated,'exec','-T','importer','python','-c',health_code],stderr=subprocess.DEVNULL))
            if current.get('version')==expected_version and current.get('voiceDiscovery') and current.get('oauthConfigured')==before_health.get('oauthConfigured'):break
        except (subprocess.CalledProcessError,ValueError):pass
        time.sleep(2)
    else:raise RuntimeError('Worker-enabled backend health check failed.')
    print('health version '+str(expected_version)+' confirmed; revision '+revision)
    print('Compose: '+str(work)+'; retained data: '+str(data))
    print('Private backup: '+str(backup)+'; tasks/settings/OAuth/service key preserved.')
    print('Worker resumed; interrupted jobs recover from their saved cursor and Drive manifests.')
except BaseException:
    if stopped:
        execute([*base,'up','-d','--no-deps','--no-build','--force-recreate','importer'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for attempt in range(30):
            try:
                restored=json.loads(command([*base,'exec','-T','importer','python','-c',health_code],stderr=subprocess.DEVNULL))
                if restored==before_health:
                    print('Previous importer health confirmed; data/configuration retained.',file=sys.stderr)
                    break
            except (subprocess.CalledProcessError,ValueError):pass
            time.sleep(2)
        else:print('Rollback health could not be confirmed; inspect the existing importer.',file=sys.stderr)
    raise
PY
