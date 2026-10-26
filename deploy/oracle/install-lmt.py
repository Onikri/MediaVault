#!/usr/bin/env python3
"""Install only the native reader sidecars on the EXISTING free Oracle VM.
Run as root with an immutable reviewed Git commit. No OCI resources are created.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

revision=sys.argv[1]
if not re.fullmatch('[a-f0-9]{40}',revision):raise SystemExit('Pass a full reviewed Git SHA')
root=Path('/opt/mediavault-lmt');root.mkdir(exist_ok=True,mode=0o750)
log=(root/'install.log').open('a')
def run(args,**kw):return subprocess.run(args,check=True,stdout=log,stderr=log,**kw)
def output(args):return subprocess.check_output(args,text=True)
if os.uname().machine!='aarch64':raise SystemExit('This deployment uses the existing tested ARM64 images')
if shutil.disk_usage('/opt').free<4*1024**3:raise SystemExit('Need at least 4 GiB free disk')
inspect=json.loads(output(['docker','inspect','oracle-importer-1']))[0]
if not inspect['State']['Running']:raise SystemExit('Importer is not running; stop and diagnose first')
config=json.loads(output(['docker','inspect','oracle-https-1']))[0]
mount=next(m for m in config['Mounts'] if m['Destination']=='/etc/caddy/Caddyfile')
caddy=Path(mount['Source']);backup=root/('Caddyfile.before-'+revision[:12]);
if not backup.exists():backup.write_bytes(caddy.read_bytes())
networks=set(inspect['NetworkSettings']['Networks'])&set(config['NetworkSettings']['Networks'])
if len(networks)!=1:raise SystemExit('Review the existing Docker network before deployment')
network=networks.pop()
llm=Path('/opt/mediavault-reader-bench/data/llm/Hy-MT2-1.8B-Q8_0.gguf')
expected='5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4'
with llm.open('rb') as f:
 if hashlib.file_digest(f,'sha256').hexdigest()!=expected:raise SystemExit('Hy-MT2 model integrity check failed')
run(['docker','image','inspect','mediavault-reader-llm:b11887'])
source=root/revision
if not source.exists():
 archive=root/'source.tar.gz'
 with urllib.request.urlopen('https://codeload.github.com/Onikri/MediaVault/tar.gz/'+revision,timeout=60) as r,archive.open('wb') as f:shutil.copyfileobj(r,f)
 with tarfile.open(archive) as tar:tar.extractall(root,filter='data')
 (root/('MediaVault-'+revision)).rename(source);archive.unlink()
# A separate new data directory, no importer/Drive config mounts.
data=root/'data';data.mkdir(exist_ok=True);os.chown(data,1000,1000)
# Reuse SHA-addressed ONNX files from our successful previous tests. Validate
# once again in NativeOnnx on first inference. Leave original caches intact.
cache=data/'onnx-models';cache.mkdir(exist_ok=True);os.chown(cache,1000,1000)
bench=Path('/opt/mediavault-reader-bench/data')
for old in bench.rglob('*.onnx'):
 if re.fullmatch('[a-f0-9]{64}\\.onnx',old.name) and not (cache/old.name).exists():
  try:os.link(old,cache/old.name)
  except OSError:shutil.copy2(old,cache/old.name)
image='mediavault-lmt:'+revision[:12]
run(['docker','build','-f','server/Dockerfile.lmt','-t',image,'.'],cwd=source,timeout=1500)
meminfo={line.split(':',1)[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if len(line.split())>=3 and line.split()[1].isdigit()}
if meminfo.get('MemAvailable',0)<9*1024**3:raise SystemExit('VM is busy: need 9 GiB available before starting the quality worker. Existing containers untouched.')
# Private Docker DNS, no new published host port. Existing importer untouched.
for name in ['mediavault-lmt','mediavault-lmt-llm']:
 existing=subprocess.run(['docker','inspect',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 if existing.returncode==0:run(['docker','rm','-f',name])
common=['--restart','unless-stopped','--network',network,'--cpus=2','--cap-drop=ALL','--security-opt=no-new-privileges']
run(['docker','run','-d','--name','mediavault-lmt-llm','--network-alias','lmt-llm',*common,'--memory=3g','--memory-swap=3g','--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=64m','-v',str(llm.parent)+':/models:ro','mediavault-reader-llm:b11887','-m','/models/'+llm.name,'--alias',llm.stem,'-c','4096','-t','2','--parallel','1','--host','0.0.0.0','--port','8081','--reasoning','off','--no-webui'])
run(['docker','run','-d','--name','mediavault-lmt','--network-alias','lmt',*common,'--memory=6g','--memory-swap=6g','--tmpfs','/tmp:rw,nosuid,nodev,size=512m,uid=1000,gid=1000','-v',str(data)+':/data','-e','LMT_LLM_URL=http://lmt-llm:8081/v1','-e','LMT_LLM_MODEL='+llm.stem,'-e','LMT_LLM_PROFILE=hymt2',image])
health="import urllib.request,json;v=json.load(urllib.request.urlopen('http://127.0.0.1:7861/reader/lmt/status',timeout=5));assert v['ready'];print('LMT_READY')"
for _ in range(90):
 check=subprocess.run(['docker','exec','mediavault-lmt','python','-c',health],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 if check.returncode==0:break
 time.sleep(1)
else:raise SystemExit('New sidecar did not become ready; public config untouched')
raw=caddy.read_text()
if 'handle /reader/lmt/*' not in raw:
 # Preserve user-specific headers, streaming routes, and limits already in use.
 marker='    reverse_proxy importer:7860'
 if marker not in raw:raise SystemExit('Review custom Caddy routes; automatic insertion stopped')
 raw=raw.replace(marker,'    @lmt path /reader/lmt/*\n    reverse_proxy @lmt lmt:7861\n'+marker,1)
 # Existing global 512KB upload limit rejects images. Scope a larger image limit
 # to this route and keep all other existing limits unchanged.
 # Route order is explicit; use a separate handle before the original global
 # request_body which is converted to only match non-LMT requests.
 raw=raw.replace('    request_body {','    @nonLmt not path /reader/lmt/*\n    request_body @nonLmt {',1)
 raw=raw.replace('    @lmt path /reader/lmt/*','    @lmt path /reader/lmt/*\n    request_body @lmt {\n        max_size 14MB\n    }',1)
 temp=root/'Caddyfile.pending';temp.write_text(raw)
 # Validate with the running image before changing its mounted config.
 run(['docker','run','--rm','--network',network,'-e','SERVER_NAME=141.144.225.42.sslip.io','-v',str(temp)+':/etc/caddy/Caddyfile:ro',config['Config']['Image'],'caddy','validate','--config','/etc/caddy/Caddyfile'],timeout=60)
 # Modify the existing inode: the running bind mount sees the update.
 caddy.write_text(raw)
 try:run(['docker','exec','oracle-https-1','caddy','reload','--config','/etc/caddy/Caddyfile'],timeout=30)
 except BaseException:
  caddy.write_bytes(backup.read_bytes());run(['docker','exec','oracle-https-1','caddy','reload','--config','/etc/caddy/Caddyfile']);raise
assert json.loads(output(['docker','inspect','oracle-importer-1']))[0]['Id']==inspect['Id']
(root/'deployed.json').write_text(json.dumps({'commit':revision,'image':image,'importerUnchanged':True,'publicPortsAdded':False,'caddyBackup':str(backup)},indent=2))
print('LMT_INSTALLED importerUnchanged=true publicPortsAdded=false')
