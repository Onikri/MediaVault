#!/usr/bin/env python3
"""Restore the official image's WebView runtime on an existing private service.

No new ports, challenge solver, account export, or extension reinstallation.
The original Compose/config files are restored if service readiness fails.
"""
from pathlib import Path
import copy,hashlib,json,os,shutil,sqlite3,subprocess,time


def browser_overlay(original):
    updated=copy.deepcopy(original)
    service=updated['services']['suwayomi']
    if not service.get('image','').startswith('ghcr.io/suwayomi/suwayomi-server@sha256:'):
        raise RuntimeError('Expected the pinned official Suwayomi image.')
    if service.get('ports') or service.get('network_mode')=='host':
        raise RuntimeError('Expected a private Suwayomi service.')
    # The official launcher links the bundled ARM64 CEF, starts Xvfb, and sets
    # its library preload. Starting java directly skips all three steps.
    service['entrypoint']=['tini','--']
    service['command']=['/home/suwayomi/startup_script.sh']
    service.setdefault('environment',{}).update(KCEF_ENABLED='true',JAVA_TOOL_OPTIONS='-Xms128m -Xmx768m -Djava.io.tmpdir=/run/mediavault-jni --enable-native-access=ALL-UNNAMED')
    mounts=service.setdefault('tmpfs',[])
    if not any(m.split(':',1)[0]=='/run/mediavault-jni' for m in mounts):mounts.append('/run/mediavault-jni:rw,exec,nosuid,nodev,size=64m,uid=1000,gid=1000,mode=0700')
    service.update(mem_limit='2304m',memswap_limit='2304m',pids_limit=512)
    return updated


def main():
    if os.geteuid()!=0:raise RuntimeError('Run with sudo on the existing VM.')
    root=Path('/opt/mediavault-suwayomi')
    backup=root/('browser-backup-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()))
    backup.mkdir(parents=True,mode=0o700)
    log=(backup/'operation.log').open('a')
    def get(args):return subprocess.check_output(args,text=True,stderr=log).strip()
    def run(args):subprocess.run(args,check=True,stdout=log,stderr=log)
    containers=json.loads(get(['docker','inspect',*get(['docker','ps','-q']).split()]))
    def one(name):
        rows=[c for c in containers if c['Config'].get('Labels',{}).get('com.docker.compose.service')==name]
        if len(rows)!=1:raise RuntimeError('Expected one running '+name+' service.')
        return rows[0]
    importer,source=one('importer'),one('suwayomi')
    labels=source['Config']['Labels'];work=Path(labels['com.docker.compose.project.working_dir'])
    files=labels['com.docker.compose.project.config_files'].split(',')
    overlay=work/'suwayomi.yaml'
    if str(overlay) not in files:raise RuntimeError('Existing Suwayomi overlay not found.')
    config=root/'data/server.conf'
    if not config.is_file():raise RuntimeError('Existing source configuration not found.')
    data=Path(next(m['Source'] for m in importer['Mounts'] if m['Destination']=='/data'))
    def account_state():
        with sqlite3.connect('file:'+str(data/'tasks.sqlite')+'?mode=ro',uri=True) as db:
            if db.execute("SELECT count(*) FROM tasks WHERE status IN ('queued','running','cancelling')").fetchone()[0]:
                raise RuntimeError('Wait for active imports before restarting sources.')
        return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [work/'.env',data/'service.key',data/'suwayomi-auth.json']}
    before=account_state()
    run(['docker','exec',source['Id'],'sh','-c','command -v Xvfb && command -v tini && test -f /opt/kcef/jcef/release && test -x /home/suwayomi/startup_script.sh'])
    original=overlay.read_bytes();changed=browser_overlay(json.loads(original))
    for path in [overlay,config]:shutil.copy2(path,backup/path.name)
    base=['docker','compose','--project-directory',str(work),'-p',labels['com.docker.compose.project']]
    for file in files:base+=['-f',file]
    probe="from suwayomi_bridge import Client;c=Client();v=c.get('/source/list',timeout=5);c.close();assert len(v)>0;print(len(v))"
    try:
        overlay.write_text(json.dumps(changed,indent=2)+'\n');overlay.chmod(0o600)
        run([*base,'config','--quiet']);run([*base,'up','-d','--no-deps','suwayomi'])
        for attempt in range(60):
            try:
                count=int(get(['docker','exec',importer['Id'],'python','-c',probe]));break
            except (subprocess.CalledProcessError,ValueError):time.sleep(2)
        else:raise RuntimeError('Suwayomi did not recover after enabling WebView.')
        if account_state()!=before:raise RuntimeError('Account configuration changed unexpectedly.')
    except Exception:
        for path in [overlay,config]:shutil.copy2(backup/path.name,path)
        run([*base,'up','-d','--no-deps','suwayomi'])
        raise
    print(json.dumps({'browserRuntimeConfigured':True,'sources':count,'backup':str(backup),'accountConfigurationPreserved':True}))


if __name__=='__main__':main()
