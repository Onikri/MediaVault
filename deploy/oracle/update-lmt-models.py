#!/usr/bin/env python3
"""Upgrade the existing reader only; preserve importer, OAuth and cloud resources.
Requires previously verified candidate weights + private detector container.
"""
from pathlib import Path
import hashlib,json,os,re,shutil,subprocess,sys,tarfile,time,urllib.request
revision=sys.argv[1]
if not re.fullmatch('[a-f0-9]{40}',revision):raise SystemExit('Full reviewed commit required')
root=Path('/opt/mediavault-lmt');source=root/revision;models=root/'models'
log=(root/'models-update.log').open('a')
def run(args,**kw):return subprocess.run(args,check=True,stdout=log,stderr=log,**kw)
def inspect(name):return json.loads(subprocess.check_output(['docker','inspect',name]))[0]
importer=inspect('oracle-importer-1')['Id'];network=next(iter(inspect('mediavault-lmt')['NetworkSettings']['Networks']))
if shutil.disk_usage(root).free<3*1024**3:raise SystemExit('Need 3 GiB free disk')
weights=[(Path('/opt/mediavault-reader-bench/data/llm/Hy-MT2-1.8B-Q8_0.gguf'),'5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4'),(models/'Index-Translate-2B.Q8_0.gguf','a09d287f41d297206947a2e51acc29dd03c8b22356111fdb1e289c0c97c173f3')]
curated=root/'translator-models';curated.mkdir(exist_ok=True)
for file,sha in weights:
    with file.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==sha
    if not (curated/file.name).exists():os.link(file,curated/file.name)
if not source.exists():
    archive=root/'models-source.tar.gz'
    with urllib.request.urlopen('https://codeload.github.com/Onikri/MediaVault/tar.gz/'+revision,timeout=90) as r,archive.open('wb') as f:shutil.copyfileobj(r,f)
    with tarfile.open(archive) as tar:tar.extractall(root,filter='data')
    (root/('MediaVault-'+revision)).rename(source);archive.unlink()
(curated/'presets.ini').write_text('version = 1\n[Hy-MT2-1.8B-Q8_0]\nmodel = /models/Hy-MT2-1.8B-Q8_0.gguf\n[Index-Translate-2B.Q8_0]\nmodel = /models/Index-Translate-2B.Q8_0.gguf\n')
image='mediavault-lmt:'+revision[:12]
run(['docker','build','-f','server/Dockerfile.lmt','-t',image,'.'],cwd=source,timeout=1500)
common=['--network',network,'--restart','unless-stopped','--cpus=2','--cap-drop=ALL','--security-opt=no-new-privileges']
old_lmt=inspect('mediavault-lmt');old_llm=inspect('mediavault-lmt-llm')
# Stopped backups remain available for immediate rollback. No secrets/importer
# mounts are copied; these two containers only contain their own reader data.
backup='before-models-'+revision[:8]
for name in ['mediavault-lmt','mediavault-lmt-llm']:
    run(['docker','stop',name]);run(['docker','rename',name,name+'-'+backup])
try:
    run(['docker','run','-d','--name','mediavault-lmt-llm','--network-alias','lmt-llm',*common,'--memory=3g','--memory-swap=3g','--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=64m','-v',str(curated)+':/models:ro','mediavault-reader-llm:b11887','--models-preset','/models/presets.ini','--models-max','1','-c','2048','-t','2','--parallel','1','--host','0.0.0.0','--port','8081','--reasoning','off','--no-webui'])
    # Router resolves exact GGUF stems; verify discovery before the reader.
    check="import urllib.request,json;v=json.load(urllib.request.urlopen('http://lmt-llm:8081/v1/models',timeout=5));ids=[x['id'] for x in v['data']];assert 'Index-Translate-2B.Q8_0' in ids and 'Hy-MT2-1.8B-Q8_0' in ids,ids"
    for _ in range(15):
        probe=subprocess.run(['docker','run','--rm','--network',network,'--entrypoint','python',old_lmt['Config']['Image'],'-c',check],stdout=log,stderr=log,timeout=15)
        if probe.returncode==0:break
        time.sleep(1)
    else:raise RuntimeError('Router models not discovered')
    run(['docker','run','-d','--name','mediavault-lmt','--network-alias','lmt',*common,'--memory=6g','--memory-swap=6g','--tmpfs','/tmp:rw,nosuid,nodev,size=512m,uid=1000,gid=1000','-v',str(root/'data')+':/data','-e','LMT_LLM_URL=http://lmt-llm:8081/v1','-e','LMT_LLM_MODEL=Hy-MT2-1.8B-Q8_0','-e','LMT_INDEX_MODEL=Index-Translate-2B.Q8_0','-e','LMT_LLM_PROFILE=hymt2','-e','LMT_DETECT_URL=http://manga-detect:7862',image])
    for _ in range(60):
        try:
            s=json.load(urllib.request.urlopen('https://141.144.225.42.sslip.io/reader/lmt/status',timeout=4))
            if s['version']>=5 and s['ready'] and 'index' in s['translators']:break
        except Exception:pass
        time.sleep(1)
    else:raise RuntimeError('Reader did not become ready')
except BaseException:
    for name in ['mediavault-lmt','mediavault-lmt-llm']:
        subprocess.run(['docker','rm','-f',name],stdout=log,stderr=log)
        run(['docker','rename',name+'-'+backup,name]);run(['docker','start',name])
    raise
assert inspect('oracle-importer-1')['Id']==importer
(root/'models-deployed.json').write_text(json.dumps({'commit':revision,'routerMaxLoaded':1,'importerUnchanged':True,'publicPortsAdded':False,'backup':backup},indent=2))
print('MODEL_UPDATE_OK')
