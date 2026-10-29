#!/usr/bin/env python3
"""Add a private ARM64 Suwayomi service to the EXISTING installation only.
Run after updating the importer to backend v14. No cloud resources/ports created.
"""
from pathlib import Path
import argparse,hashlib,json,os,secrets,shutil,sqlite3,subprocess,sys,time
IMAGE='ghcr.io/suwayomi/suwayomi-server@sha256:1fac27c387dc2ea9949e1a01ad7f6d6de9d72d3988338a95476748e5c45c4582'
ROOT=Path('/opt/mediavault-suwayomi')

def main(all_languages=False):
    ROOT.mkdir(exist_ok=True,mode=0o700);ROOT.chmod(0o700)
    log=(ROOT/'install.log').open('a')
    def cmd(args):return subprocess.check_output(args,text=True,stderr=log).strip()
    def run(args):subprocess.run(args,check=True,stdout=log,stderr=log)
    ids=cmd(['docker','ps','-q']).split();containers=json.loads(cmd(['docker','inspect',*ids]))
    selected=[c for c in containers if c['Config'].get('Labels',{}).get('com.docker.compose.service')=='importer']
    if len(selected)!=1:raise RuntimeError('Expected one existing Compose importer.')
    importer=selected[0];labels=importer['Config']['Labels'];work=Path(labels['com.docker.compose.project.working_dir']);files=labels['com.docker.compose.project.config_files'].split(',')
    data=Path(next(m['Source'] for m in importer['Mounts'] if m['Destination']=='/data'))
    health_code='import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen("http://127.0.0.1:7860/health",timeout=5))))'
    before=json.loads(cmd(['docker','exec',importer['Id'],'python','-c',health_code]))
    if before['version']<14:raise RuntimeError('Update importer to v14 before enabling Suwayomi.')
    if all_languages and before['version']<15:raise RuntimeError('Language packs need importer v15.')
    with sqlite3.connect('file:'+str(data/'tasks.sqlite')+'?mode=ro',uri=True) as db:
        if db.execute("SELECT count(*) FROM tasks WHERE status IN ('queued','running','cancelling')").fetchone()[0]:raise RuntimeError('Wait for active imports before changing the importer configuration.')
    if shutil.disk_usage(ROOT).free<2*1024**3:raise RuntimeError('Need 2 GiB free disk.')
    fingerprints={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [work/'.env',data/'service.key']}
    authfile=data/'suwayomi-auth.json'
    if not authfile.exists():
        authfile.write_text(json.dumps({'username':'mediavault','password':secrets.token_urlsafe(36)}));authfile.chmod(0o600);os.chown(authfile,1000,1000)
    auth=json.loads(authfile.read_text());storage=ROOT/'data';storage.mkdir(exist_ok=True,mode=0o700);os.chown(storage,1000,1000)
    settings={'ip':'0.0.0.0','port':4567,'webUIEnabled':False,'initialOpenInBrowserEnabled':False,'systemTrayEnabled':False,'webUIUpdateCheckInterval':0.0,'kcefEnabled':True,'maxSourcesInParallel':2,'extensionStores':['https://github.com/keiyoushi/extensions/raw/repo/index.pb'],'authMode':'BASIC_AUTH','authUsername':auth['username'],'authPassword':auth['password'],'autoDownloadNewChapters':False,'globalUpdateInterval':0.0,'backupInterval':0,'maxLogFolderSize':'32mb'}
    config=storage/'server.conf'
    if not config.exists():
        config.write_text('\n'.join('server.'+k+' = '+json.dumps(v) for k,v in settings.items())+'\n');config.chmod(0o600);os.chown(config,1000,1000)
    # Immutable official multiarch release; no preview tag, admin UI, host ports,
    # FlareSolverr, automatic downloads, or mounted Google/Drive credentials.
    overlay=work/'suwayomi.yaml'
    content={'services':{'suwayomi':{'image':IMAGE,'restart':'unless-stopped','user':'1000:1000','entrypoint':['tini','--'],'command':['/home/suwayomi/startup_script.sh'],'environment':{'TZ':'Etc/UTC','KCEF_ENABLED':'true','JAVA_TOOL_OPTIONS':'-Xms128m -Xmx768m'},'volumes':[str(storage)+':/home/suwayomi/.local/share/Tachidesk'],'mem_limit':'2304m','memswap_limit':'2304m','cpus':1.0,'pids_limit':512,'security_opt':['no-new-privileges:true'],'cap_drop':['ALL'],'tmpfs':['/tmp:size=256m,uid=1000,gid=1000,mode=1777'],'logging':{'driver':'json-file','options':{'max-size':'10m','max-file':'2'}}},'importer':{'environment':{'SUWAYOMI_URL':'http://suwayomi:4567','SUWAYOMI_AUTH_FILE':'/data/suwayomi-auth.json'}}}}
    if overlay.exists() and json.loads(overlay.read_text())!=content:raise RuntimeError('Existing Suwayomi configuration differs; preserve it before updating.')
    overlay.write_text(json.dumps(content,indent=2)+'\n');overlay.chmod(0o600)
    base=['docker','compose','--project-directory',str(work),'-p',labels['com.docker.compose.project']]
    for f in files:
        if Path(f)!=overlay:base+=['-f',f]
    updated=[*base,'-f',str(overlay)]
    (ROOT/'rollback.json').write_text(json.dumps({'composeBefore':base,'overlay':str(overlay),'previousImporter':importer['Id']}));(ROOT/'rollback.json').chmod(0o600)
    run([*updated,'config','--quiet']);run([*updated,'pull','suwayomi']);run([*updated,'up','-d','--no-deps','suwayomi'])
    # Check auth and extensions through the importer's existing private network.
    probe="import os,json;os.environ['SUWAYOMI_URL']='http://suwayomi:4567';os.environ['SUWAYOMI_AUTH_FILE']='/data/suwayomi-auth.json';from suwayomi_bridge import status;v=status();assert v['ready'];print(v['availableExtensions'])"
    for attempt in range(45):
        try:
            count=int(cmd(['docker','exec',importer['Id'],'python','-c',probe]));break
        except (subprocess.CalledProcessError,ValueError):time.sleep(2)
    else:raise RuntimeError('Suwayomi failed readiness; importer unchanged. See private install.log.')
    try:
        run([*updated,'up','-d','--no-deps','--no-build','importer'])
        cid=cmd([*updated,'ps','-q','importer'])
        for attempt in range(30):
            try:
                after=json.loads(cmd(['docker','exec',cid,'python','-c',health_code]));break
            except (subprocess.CalledProcessError,ValueError):time.sleep(2)
        else:raise RuntimeError('Importer did not recover.')
        if after['version']!=before['version'] or after['oauthConfigured']!=before['oauthConfigured']:raise RuntimeError('Importer/OAuth health changed unexpectedly.')
        for path,expected in fingerprints.items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=expected:raise RuntimeError('Existing private configuration changed.')
        source_code="import json;from suwayomi_bridge import extensions,install,status;wanted={'eu.kanade.tachiyomi.extension.en.mangapill','eu.kanade.tachiyomi.extension.ru.mangalib','eu.kanade.tachiyomi.extension.ru.mangapoisk','eu.kanade.tachiyomi.extension.ja.senmanga','eu.kanade.tachiyomi.extension.ko.navercomic'};available={e['pkgName'] for e in extensions()};results=[]\nfor package in sorted(wanted & available):\n try:results.append(install(package))\n except Exception:results.append({'installed':False})\nv=status();print(json.dumps({'ready':v['ready'],'availableExtensions':v['availableExtensions'],'sources':len(v['sources']),'installs':results}))"
        result=json.loads(cmd(['docker','exec',cid,'python','-c',source_code]));(ROOT/'verification.json').write_text(json.dumps(result,indent=2))
        if all_languages:
            # The deployment operator starts bulk installation separately through
            # the existing authenticated API; no local auth token is manufactured.
            print('Language packs available: use the owner-only install-pack endpoint for RU/EN/JA/KO.')
        print(json.dumps({'installed':True,'privateOnly':True,'availableExtensions':count,'sources':result['sources'],'oauthPreserved':True}))
    except Exception:
        run([*base,'up','-d','--no-deps','--no-build','importer']);raise

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--all-languages',action='store_true',help='Require the resumable RU/EN/JA/KO language-pack API (v15).')
    main(parser.parse_args().all_languages)
