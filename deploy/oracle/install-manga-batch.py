#!/usr/bin/env python3
"""Install only the batch sidecars, preserving importer/ML/parser containers.

Run on the existing VM, as root, with an immutable full Git commit SHA.
No cloud resources, paid models, host ports or Google keys are provisioned.
"""
from pathlib import Path
import hashlib,json,os,re,shutil,subprocess,sys,tarfile,time,urllib.request

revision=sys.argv[1] if len(sys.argv)==2 else ''
if not re.fullmatch(r'[a-f0-9]{40}',revision):raise SystemExit('Supply a reviewed immutable commit SHA')
root=Path('/opt/mediavault-manga-batch');root.mkdir(exist_ok=True,mode=0o750)
log=(root/('install-'+revision[:12]+'.log')).open('a')
def run(args,**kw):return subprocess.run(args,stdout=log,stderr=log,check=True,**kw)
def inspect(name):return json.loads(subprocess.check_output(['docker','inspect',name]))[0]
importer=inspect('oracle-importer-1');https=inspect('oracle-https-1')
network=set(importer['NetworkSettings']['Networks'])&set(https['NetworkSettings']['Networks'])
if len(network)!=1:raise SystemExit('Review the existing private Docker network')
network=network.pop();data=Path(next(m['Source'] for m in importer['Mounts'] if m['Destination']=='/data'))
caddy=Path(next(m['Source'] for m in https['Mounts'] if m['Destination']=='/etc/caddy/Caddyfile'))
original=caddy.read_text();before=root/('Caddyfile-before-'+revision[:12]);before.write_text(original);before.chmod(0o600)
if shutil.disk_usage(root).free<2*1024**3:raise SystemExit('Need 2 GiB free disk before installation')
source=root/revision
if not source.exists():
    archive=root/(revision+'.tgz')
    with urllib.request.urlopen('https://codeload.github.com/Onikri/MediaVault/tar.gz/'+revision,timeout=90) as response,archive.open('wb') as out:shutil.copyfileobj(response,out)
    with tarfile.open(archive) as tar:tar.extractall(root,filter='data')
    (root/('MediaVault-'+revision)).rename(source);archive.unlink()
models=root/'models';models.mkdir(exist_ok=True,mode=0o755);storage=root/'data';storage.mkdir(exist_ok=True,mode=0o700);os.chown(storage,1000,1000)
expected='5fe9e4f576e49d4e7e8b0e029d6d3cdc252abd4694113e1cae120e62c931ea79';model=models/'rtdetr.onnx'
if not model.is_file():
    found=False
    for base in [Path('/opt/mediavault-lmt'),Path('/opt/mediavault-reader-bench')]:
        for candidate in base.rglob('*.onnx'):
            if candidate.stat().st_size!=11120765:continue
            with candidate.open('rb') as f:valid=hashlib.file_digest(f,'sha256').hexdigest()==expected
            if valid:shutil.copyfile(candidate,model);found=True;break
        if found:break
    if not found:
        url='https://huggingface.co/ogkalu/comic-text-and-bubble-detector/resolve/main/detector-v4-s_int8.onnx'
        with urllib.request.urlopen(url,timeout=90) as response,model.open('wb') as out:shutil.copyfileobj(response,out)
with model.open('rb') as f:
    if hashlib.file_digest(f,'sha256').hexdigest()!=expected:raise SystemExit('RT-DETR SHA-256 verification failed')
model.chmod(0o644)
# Reuse a key explicitly installed for the former Gemma worker, if present.
# It never leaves the VM and is not printed.
existing_key=Path('/opt/mediavault-lmt/data/secrets/gemma-api-key')
if not (storage/'google-api-key').exists() and existing_key.is_file():
    shutil.copyfile(existing_key,storage/'google-api-key');(storage/'google-api-key').chmod(0o600);os.chown(storage/'google-api-key',1000,1000)
image='mediavault-manga-batch:'+revision[:12]
run(['docker','build','-f','server/Dockerfile.manga-batch','-t',image,'.'],cwd=source,timeout=1500)
name='mediavault-manga-batch';candidate=name+'-check-'+revision[:8]
# Copy only the OAuth client fallback if not configured in the database. The
# credential file is private and never printed, including on build failures.
env={line.split('=',1)[0]:line.split('=',1)[1] for line in importer['Config'].get('Env',[]) if '=' in line}
envfile=root/'service.env';envfile.write_text(''.join(k+'='+v+'\n' for k,v in env.items() if k in ['GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET'])+'REDIS_URL=redis://manga-redis:6379/0\nGEMMA_INDEPENDENT_POOLS=0\n');envfile.chmod(0o600)
common=['--network',network,'--restart','unless-stopped','--cpus=2','--memory=2g','--memory-swap=2g','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--tmpfs','/tmp:rw,nosuid,nodev,size=32m,uid=1000,gid=1000','-v',str(storage)+':/data','-v',str(data)+':/importer:ro','-v',str(models)+':/models:ro','--env-file',str(envfile)]
def exists(n):return subprocess.run(['docker','inspect',n],stdout=log,stderr=log).returncode==0
def healthy(n):
    code="import json,urllib.request;v=json.load(urllib.request.urlopen('http://127.0.0.1:7863/api/v1/manga-translation/status',timeout=5));assert v['detectorReady'] and v['maxPages']==3"
    for _ in range(30):
        if subprocess.run(['docker','exec',n,'python','-c',code],stdout=log,stderr=log).returncode==0:return True
        time.sleep(2)
    return False
if not exists('mediavault-manga-redis'):
    run(['docker','run','-d','--name','mediavault-manga-redis','--user=999:999','--network',network,'--network-alias','manga-redis','--restart','unless-stopped','--memory=192m','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','redis:7.4.6-alpine','redis-server','--save','','--appendonly','no','--maxmemory','128mb','--maxmemory-policy','allkeys-lru'])
if exists(candidate):run(['docker','rm','-f',candidate])
run(['docker','run','-d','--name',candidate,*common,image])
if not healthy(candidate):
    run(['docker','rm','-f',candidate]);raise SystemExit('Candidate failed; existing importer/Caddy unchanged')
run(['docker','rm','-f',candidate])
backup=name+'-before-'+revision[:8];had_old=exists(name)
if had_old:
    if exists(backup):raise SystemExit('Review the existing rollback container before retrying')
    run(['docker','stop',name]);run(['docker','rename',name,backup])
try:
    run(['docker','run','-d','--name',name,'--network-alias','manga-batch',*common,image])
    if not healthy(name):raise RuntimeError('New batch service failed readiness')
    route='''    handle /api/v1/* {
        request_body {
            max_size 512KB
        }
        reverse_proxy manga-batch:7863 {
            flush_interval -1
        }
    }
'''
    if 'reverse_proxy @mangaBatch manga-batch:7863' in original:
        proposed=original
    elif 'handle /api/v1/*' not in original:
        anchor='    handle /reader/lmt/* {'
        if anchor in original:proposed=original.replace(anchor,route+anchor,1)
        elif '    reverse_proxy @lmt lmt:7861' in original:
            # Older production configuration uses named matchers rather than
            # handle blocks. Keep its request limits and existing proxies.
            batch_route='    @mangaBatch path /api/v1/*\n    reverse_proxy @mangaBatch manga-batch:7863 {\n        flush_interval -1\n    }\n'
            proposed=original.replace('    reverse_proxy @lmt lmt:7861',batch_route+'    reverse_proxy @lmt lmt:7861',1)
        else:raise RuntimeError('Unknown Caddy routing; review before applying')
    else:
        if 'reverse_proxy manga-batch:7863' not in original:raise RuntimeError('Existing /api/v1 route belongs to another service')
        proposed=original
    # Write through the existing bind-mount inode; atomically replacing the host
    # file would leave the container seeing the old inode.
    caddy.write_text(proposed)
    run(['docker','exec','oracle-https-1','caddy','validate','--config','/etc/caddy/Caddyfile'])
    run(['docker','exec','oracle-https-1','caddy','reload','--config','/etc/caddy/Caddyfile'])
    # Unauthenticated POST must be rejected by the service after routing.
    request=urllib.request.Request('https://141.144.225.42.sslip.io/api/v1/chapters',data=b'{}',headers={'Content-Type':'application/json'})
    try:urllib.request.urlopen(request,timeout=10);raise RuntimeError('Authentication check unexpectedly succeeded')
    except urllib.error.HTTPError as e:
        if e.code!=401:raise
except BaseException:
    caddy.write_text(original);subprocess.run(['docker','exec','oracle-https-1','caddy','reload','--config','/etc/caddy/Caddyfile'],stdout=log,stderr=log)
    if exists(name):run(['docker','rm','-f',name])
    if had_old:run(['docker','rename',backup,name]);run(['docker','start',name])
    raise
assert inspect('oracle-importer-1')['Id']==importer['Id']
assert inspect('oracle-https-1')['Id']==https['Id']
result={'commit':revision,'detectorReady':True,'googleKeyInstalled':(storage/'google-api-key').exists(),'importerUnchanged':True,'httpsReloadOnly':True,'publicPortsAdded':False,'backup':backup if had_old else None}
(root/'deployed.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
