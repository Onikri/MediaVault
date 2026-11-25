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
    dockerfile=release/'server'/'Dockerfile'
    build=['docker','build','--label','org.opencontainers.image.revision='+revision,'-t',image]
    if dockerfile.is_file() and 'AS export-assets' in dockerfile.read_text():
        build+=['-f',str(dockerfile),str(release)]
    else:
        build.append(str(release/'server'))
    # An image already built from this exact commit (an earlier run stopped
    # at the backup check) is reused: rebuilding it without its cache needs
    # several GB the disk may not have next to the backup.
    built=subprocess.run(['docker','image','inspect','--format','{{index .Config.Labels "org.opencontainers.image.revision"}}',image],capture_output=True,text=True)
    if built.returncode==0 and built.stdout.strip()==revision:print('Reusing the image already built from '+revision[:12]+'.',file=output)
    else:execute(build,stdout=output,stderr=output)
expected_version=int(command(['docker','run','--rm','--network','none','--entrypoint','python',image,'-c','import api; print(api.health()["version"])']))
if expected_version<6:raise SystemExit('The release does not support voice discovery; no replacement made.')
if expected_version>=51:
    execute(['docker','run','--rm','--network','none','--entrypoint','python',image,'-c','import api; assert api.health()["mangaTranslationExport"]'])
override=work/('release-'+revision[:12]+'.yaml')
if override.exists():raise SystemExit('Release override already exists. Inspect the previous attempt before retrying.')
# systemd-resolved's stub on the VM drops DNAME answers (CDN hosts behind
# interkh.com and similar), so Docker's embedded DNS forwards to the Oracle VCN
# resolver directly, with a public resolver as a fallback.
override.write_text('services:\n  importer:\n    image: '+image+'\n    dns: [169.254.169.254, 1.1.1.1]\n')
updated=[*base,'-f',str(override)]
maintenance=work/('maintenance-'+revision[:12]+'.yaml')
maintenance.write_text('services:\n  importer:\n    environment:\n      MEDIA_VAULT_DISABLE_WORKER: "1"\n')
paused=[*updated,'-f',str(maintenance)]
backup=Path('/opt/mediavault-backups')/(time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+revision[:12])
backup.mkdir(parents=True,mode=0o700);os.chmod(backup.parent,0o700)
# The backup is taken in three parts so the site is down only while the
# databases are copied, not while 7 GB are compressed:
#  1. with the importer running: every ordinary file (keys, profiles, models)
#     into private-files.tar.gz; regenerable caches are left out;
#  2. with the importer still running: a consistent snapshot of each large
#     WAL database through SQLite's online backup API (a 13 GB catalogue no
#     longer fits the RAM staging, and copying it while stopped meant ~16 min
#     of downtime);
#  3. with the importer stopped: the small databases, the service key and the
#     configuration into private-data.tar.gz, and a raw copy of each large
#     non-WAL database into RAM (its pages are read into the page cache first);
#  4. once the new release answers (or the old one is back): the large copies
#     into private-databases.tar.gz.
CACHE_DIRS={'temporary','.codex-local/alloha-delivery/segments','.codex-local/alloha-delivery/vod','.codex-local/alloha-delivery/logs','.codex-local/export-translations','catalogue-maintenance/hc-html-cache'}
CHROMIUM_CACHES={'Cache','Code Cache','GPUCache','GrShaderCache','ShaderCache','DawnCache','DawnGraphiteCache','DawnWebGPUCache','GPUPersistentCache','component_crx_cache','CacheStorage','ScriptCache'}
DATABASE=('.sqlite','.sqlite3','.db')
SIDECARS=('-journal','-wal','-shm')
LARGE=256*1024**2
def private_files():
    ordinary,databases=[],[]
    for folder,names,entries in os.walk(data):
        relative=Path(folder).relative_to(data)
        names[:]=sorted(n for n in names if (relative/n).as_posix() not in CACHE_DIRS and n not in CHROMIUM_CACHES)
        for name in sorted(entries):
            path=Path(folder)/name
            if path.is_symlink() or not path.is_file() or name.endswith(SIDECARS) and any(name.endswith(d+s) for d in DATABASE for s in SIDECARS):continue
            (databases if name.endswith(DATABASE) else ordinary).append(path)
    return ordinary,databases
def size(path):
    try:return path.stat().st_size
    except FileNotFoundError:return 0
def configuration(archive):
    for i,path in enumerate(dict.fromkeys([env,*files,work/'Caddyfile'])):
        if path.exists():archive.add(path,arcname='configuration/'+str(i)+'-'+path.name)
ordinary,databases=private_files()
large=[p for p in databases if size(p)>LARGE];small=[p for p in databases if p not in large]
needed=sum(map(size,ordinary))+sum(map(size,databases))
if shutil.disk_usage(backup).free<needed+512*1024**2:raise SystemExit('Insufficient disk space for a complete private backup.')
with tarfile.open(backup/'private-files.tar.gz','w:gz',compresslevel=1) as archive:
    for path in ordinary:
        try:archive.add(path,arcname='data/'+path.relative_to(data).as_posix(),recursive=False)
        except FileNotFoundError:pass  # a temporary file finished while it was listed
os.chmod(backup/'private-files.tar.gz',0o600)
def available_memory():
    try:return int(next(l for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')).split()[1])*1024
    except (OSError,StopIteration,ValueError):return 0
ram=Path('/dev/shm');large_size=sum(map(size,large))
in_ram=ram.is_dir() and available_memory()>large_size+4*1024**3 and shutil.disk_usage(ram).free>large_size+1024**3
staging=(ram if in_ram else backup)/('mediavault-backup-'+revision[:12])
def warm(path):
    with path.open('rb') as source:
        while source.read(16*1024**2):pass
def wal_database(path):
    try:
        with contextlib.closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=30)) as db:
            return str(db.execute('PRAGMA journal_mode').fetchone()[0]).lower()=='wal'
    except sqlite3.Error:return False
online=[p for p in large if wal_database(p)]
for path in large:
    if path not in online:warm(path)
staged=[]
staging.mkdir(parents=True,mode=0o700,exist_ok=True)
for path in online:
    # One backup step reads a single snapshot while the importer keeps writing.
    relative=path.relative_to(data).as_posix();copy=staging/relative.replace('/','__')
    with contextlib.closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=60)) as source,contextlib.closing(sqlite3.connect(copy)) as target:
        source.backup(target)
    os.chmod(copy,0o600)
    with contextlib.closing(sqlite3.connect(copy.resolve().as_uri()+'?mode=ro',uri=True)) as check:
        if not check.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()[0]:raise RuntimeError('Online database backup is empty.')
    staged.append((relative,copy))
def finish_large():
    if not staged:return
    try:
        with tarfile.open(backup/'private-databases.tar.gz','w:gz',compresslevel=1) as archive:
            for relative,copy in staged:archive.add(copy,arcname='data/'+relative)
        os.chmod(backup/'private-databases.tar.gz',0o600)
        with tarfile.open(backup/'private-databases.tar.gz') as archive:
            if sorted(archive.getnames())!=sorted('data/'+r for r,_ in staged):raise RuntimeError('Large database backup verification failed.')
    finally:
        shutil.rmtree(staging,ignore_errors=True);staged.clear()
stopped=False
try:
    now=state()
    if now['cancelling'] or now['active'] and not resume_active:raise RuntimeError('Imports became active during build; update postponed.')
    execute([*base,'stop','importer'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);stopped=True
    before=state()
    with tarfile.open(backup/'private-data.tar.gz','w:gz') as archive:
        archive.add(key,arcname='data/service.key')
        for path in small:
            for part in [path,*(path.with_name(path.name+s) for s in SIDECARS)]:
                if part.is_file():archive.add(part,arcname='data/'+part.relative_to(data).as_posix())
        configuration(archive)
    os.chmod(backup/'private-data.tar.gz',0o600)
    with tarfile.open(backup/'private-data.tar.gz') as archive:
        if 'data/service.key' not in archive.getnames() or 'data/tasks.sqlite' not in archive.getnames():raise RuntimeError('Private backup verification failed.')
    staging.mkdir(parents=True,mode=0o700,exist_ok=True)
    for path in large:
        if path in online:continue
        for part in [path,*(path.with_name(path.name+s) for s in SIDECARS)]:
            if part.is_file():
                relative=part.relative_to(data).as_posix();copy=staging/relative.replace('/','__')
                shutil.copyfile(part,copy);os.chmod(copy,0o600)
                if copy.stat().st_size!=part.stat().st_size:raise RuntimeError('Large database copy is incomplete.')
                staged.append((relative,copy))
    (backup/'rollback.json').write_text(json.dumps({'compose':base,'image':old['Image'],'data':str(data),'revision':revision}))
    # Validate the retained queue before allowing the new worker to change it.
    execute([*paused,'up','-d','--no-deps','--no-build','--force-recreate','importer'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for attempt in range(45):
        try:
            current=json.loads(command([*paused,'exec','-T','importer','python','-c',health_code],stderr=subprocess.DEVNULL))
            if current.get('version')==expected_version and current.get('voiceDiscovery') and (expected_version<51 or current.get('mangaTranslationExport')):break
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
            if current.get('version')==expected_version and current.get('voiceDiscovery') and current.get('oauthConfigured')==before_health.get('oauthConfigured') and (expected_version<51 or current.get('mangaTranslationExport')):break
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
    try:finish_large()
    except Exception as error:print('Large database backup: '+str(error),file=sys.stderr)
    raise
# The new release answers: the large copies go to disk now, outside the
# window in which a failure would roll the release back.
try:finish_large()
except Exception as error:print('Large database backup: '+str(error),file=sys.stderr)
if (backup/'private-databases.tar.gz').exists():print('Large databases: '+str(backup/'private-databases.tar.gz'))
PY
