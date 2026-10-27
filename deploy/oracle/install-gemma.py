#!/usr/bin/env python3
"""Update the existing private LMT sidecar with an immutable Git revision.

Requires the Google key already installed at data/secrets/gemma-api-key.
Preserves the importer, existing LLM/detector sidecars, Caddy and host ports.
Keeps the old LMT container for rollback. Never prints environment/key contents.
"""
from pathlib import Path
import json,os,re,shutil,subprocess,sys,tarfile,time,urllib.request

revision=sys.argv[1]
if not re.fullmatch(r'[a-f0-9]{40}',revision):raise SystemExit('Pass an immutable full Git SHA')
root=Path('/opt/mediavault-lmt');root.mkdir(exist_ok=True,mode=0o750)
log=(root/('gemma-install-'+revision[:12]+'.log')).open('a')
def run(args,**kwargs):return subprocess.run(args,stdout=log,stderr=log,check=True,**kwargs)
def inspect(name):return json.loads(subprocess.check_output(['docker','inspect',name],text=True))[0]
old=inspect('mediavault-lmt');importer=inspect('oracle-importer-1');https=inspect('oracle-https-1')
image='mediavault-lmt:gemma-'+revision[:12]
if old['Config']['Image']==image and old['State']['Running']:
    print(json.dumps({'commit':revision,'image':image,'alreadyInstalled':True}));raise SystemExit(0)
if not old['State']['Running'] or not importer['State']['Running']:raise SystemExit('Existing services must be healthy before update')
network=set(old['NetworkSettings']['Networks'])&set(importer['NetworkSettings']['Networks'])&set(https['NetworkSettings']['Networks'])
if len(network)!=1:raise SystemExit('Review the existing private Docker network')
network=network.pop();data=Path(next(m['Source'] for m in old['Mounts'] if m['Destination']=='/data'))
key=data/'secrets/gemma-api-key'
if not key.is_file() or not 15<len(key.read_bytes())<4096:raise SystemExit('Install the server-owned Google API key first')
if shutil.disk_usage(root).free<4*1024**3:raise SystemExit('Need at least 4 GiB free disk')
snapshot=root/('gemma-before-'+revision[:12]+'.json');snapshot.write_text(json.dumps(old));snapshot.chmod(0o600)
source=root/('gemma-source-'+revision)
if not source.exists():
    archive=root/('gemma-source-'+revision+'.tgz')
    with urllib.request.urlopen('https://codeload.github.com/Onikri/MediaVault/tar.gz/'+revision,timeout=60) as response,archive.open('wb') as output:shutil.copyfileobj(response,output)
    with tarfile.open(archive) as tar:tar.extractall(root,filter='data')
    (root/('MediaVault-'+revision)).rename(source);archive.unlink()
run(['docker','build','-f','server/Dockerfile.lmt','-t',image,'.'],cwd=source,timeout=1800)
env={k:v for k,v in (line.split('=',1) for line in old['Config'].get('Env',[]) if '=' in line)}
env['GEMMA_API_KEY_FILE']='/data/secrets/gemma-api-key'
envfile=root/('gemma-worker-'+revision[:12]+'.env');envfile.write_text(''.join(k+'='+v+'\n' for k,v in env.items()));envfile.chmod(0o600)
candidate='mediavault-gemma-check-'+revision[:12];backup='mediavault-lmt-backup-'+revision[:12]
if subprocess.run(['docker','inspect',backup],stdout=log,stderr=log).returncode==0:raise SystemExit('Rollback container already exists; review previous attempt')
if subprocess.run(['docker','inspect',candidate],stdout=log,stderr=log).returncode==0:run(['docker','rm','-f',candidate])
def start(name,alias=False):
    args=['docker','run','-d','--name',name,'--restart','unless-stopped','--network',network,'--cpus=2','--memory=6g','--memory-swap=6g','--cap-drop=ALL','--security-opt=no-new-privileges','--tmpfs','/tmp:rw,nosuid,nodev,size=512m,uid=1000,gid=1000','-v',str(data)+':/data','--env-file',str(envfile)]
    if alias:args+=['--network-alias','lmt']
    run(args+[image])
def healthy(name):
    code="import json,urllib.request;v=json.load(urllib.request.urlopen('http://127.0.0.1:7861/reader/lmt/status',timeout=5));assert v.get('gemma',{}).get('ready')"
    for _ in range(45):
        if subprocess.run(['docker','exec',name,'python','-c',code],stdout=log,stderr=log).returncode==0:return True
        time.sleep(2)
    return False
start(candidate)
if not healthy(candidate):
    run(['docker','stop',candidate]);raise SystemExit('Candidate failed; existing worker unchanged')
run(['docker','stop',candidate]);run(['docker','rm',candidate])
run(['docker','stop','mediavault-lmt']);run(['docker','rename','mediavault-lmt',backup])
try:
    start('mediavault-lmt',True)
    if not healthy('mediavault-lmt'):raise RuntimeError('New worker did not become healthy')
except BaseException:
    if subprocess.run(['docker','inspect','mediavault-lmt'],stdout=log,stderr=log).returncode==0:
        run(['docker','stop','mediavault-lmt']);run(['docker','rename','mediavault-lmt','mediavault-gemma-failed-'+revision[:12]])
    run(['docker','rename',backup,'mediavault-lmt']);run(['docker','start','mediavault-lmt']);raise
assert inspect('oracle-importer-1')['Id']==importer['Id']
assert inspect('oracle-https-1')['Id']==https['Id']
deployment={'commit':revision,'image':image,'backupContainer':backup,'importerUnchanged':True,'httpsUnchanged':True,'publicPortsAdded':False}
(root/'deployed-gemma.json').write_text(json.dumps(deployment,indent=2))
print(json.dumps(deployment))
