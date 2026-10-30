#!/usr/bin/env python3
"""Restore JNI decompression in the existing pinned private Suwayomi service.

Docker's default /tmp tmpfs is noexec. Square Zstd loads its bundled library from
java.io.tmpdir, so use a separate private executable tmpfs; keep /tmp unchanged.
No downloaded/replaced JAR, new source endpoint, image or account is introduced.
"""
from pathlib import Path
import copy,hashlib,json,os,shutil,sqlite3,subprocess,time,struct

JNI_TMP='/run/mediavault-jni'
READER_CACHE='/opt/mediavault-suwayomi/.codex-local/cache/suwayomi-reader'
def native_overlay(original,cache_root=READER_CACHE):
    updated=copy.deepcopy(original);service=updated['services']['suwayomi']
    if not service.get('image','').startswith('ghcr.io/suwayomi/suwayomi-server@sha256:') or service.get('ports') or service.get('network_mode')=='host':
        raise RuntimeError('Expected the pinned private Suwayomi image.')
    mounts=service.setdefault('tmpfs',[])
    mounts[:]=[entry for entry in mounts if entry.split(':',1)[0]!=JNI_TMP]
    mounts.append(JNI_TMP+':rw,exec,nosuid,nodev,size=64m,uid=1000,gid=1000,mode=0700')
    # java.io.tmpdir also contains every online page, not just native libraries.
    # Bind only the reader subtree to disk; native loading stays on exec tmpfs.
    target=JNI_TMP+'/Tachidesk'
    volumes=service.setdefault('volumes',[])
    volumes[:]=[v for v in volumes if (v.split(':')[1] if isinstance(v,str) else v.get('target'))!=target]
    volumes.append({'type':'bind','source':str(cache_root),'target':target,'bind':{'create_host_path':False}})
    environment=service.setdefault('environment',{})
    words=environment.get('JAVA_TOOL_OPTIONS','-Xms128m -Xmx768m').split()
    words=[w for w in words if not w.startswith('-Djava.io.tmpdir=') and not w.startswith('--enable-native-access=')]
    environment['JAVA_TOOL_OPTIONS']=' '.join([*words,'-Djava.io.tmpdir='+JNI_TMP,'--enable-native-access=ALL-UNNAMED'])
    return updated

def native_probe():
    # Java equivalent: public static void main(String[] args) throws Exception {
    #   Class.forName("com.squareup.zstd.JniZstdKt"); }
    # Emit this minimal Java 8 diagnostic class without adding a compiler to the
    # intentionally trimmed official JRE. No upstream bytecode is modified.
    u=lambda s:b'\x01'+struct.pack('>H',len(s.encode()))+s.encode()
    entries=[u('MediaVaultNativeProbe'),b'\x07\x00\x01',u('java/lang/Object'),b'\x07\x00\x03',u('main'),u('([Ljava/lang/String;)V'),u('Code'),u('com.squareup.zstd.JniZstdKt'),b'\x08\x00\x08',u('java/lang/Class'),b'\x07\x00\x0a',u('forName'),u('(Ljava/lang/String;)Ljava/lang/Class;'),b'\x0c\x00\x0c\x00\x0d',b'\x0a\x00\x0b\x00\x0e']
    code=b'\x12\x09\xb8\x00\x0f\x57\xb1';attr=struct.pack('>HHI',1,1,len(code))+code+b'\x00\x00\x00\x00'
    return b'\xca\xfe\xba\xbe\x00\x00\x00\x34'+struct.pack('>H',16)+b''.join(entries)+struct.pack('>HHHHHH',0x21,2,4,0,0,1)+struct.pack('>HHHH',9,5,6,1)+struct.pack('>HI',7,len(attr))+attr+b'\x00\x00'


def install_cache_cleanup(root,run):
    runtime=root/'.codex-local/runtime';runtime.mkdir(parents=True,exist_ok=True)
    script=runtime/'prune-suwayomi-cache.py'
    source=Path(__file__).with_name(script.name)
    if source.resolve()!=script.resolve():shutil.copy2(source,script)
    logs=root/'.codex-local/logs';logs.mkdir(parents=True,exist_ok=True,mode=0o700)
    service=Path('/etc/systemd/system/mediavault-source-cache.service')
    timer=service.with_suffix('.timer')
    previous={p:p.read_bytes() if p.exists() else None for p in [service,timer]}
    try:
        service.write_text('[Unit]\nDescription=Prune disposable MediaVault source pages\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 '+str(script)+' '+READER_CACHE+'\nStandardOutput=append:'+str(logs/'source-cache.log')+'\nStandardError=append:'+str(logs/'source-cache.log')+'\n')
        timer.write_text('[Unit]\nDescription=Bound MediaVault source reader cache\n[Timer]\nOnBootSec=2min\nOnUnitActiveSec=2min\n[Install]\nWantedBy=timers.target\n')
        run(['systemctl','daemon-reload']);run(['systemctl','enable','--now',timer.name])
        run(['systemctl','start',service.name])
    except Exception:
        if previous[timer] is None:run(['systemctl','disable','--now',timer.name])
        for path,value in previous.items():
            if value is None:path.unlink(missing_ok=True)
            else:path.write_bytes(value)
        run(['systemctl','daemon-reload'])
        raise

def main():
    if os.geteuid()!=0:raise RuntimeError('Run with sudo on the existing VM.')
    root=Path('/opt/mediavault-suwayomi')
    backup=root/'.codex-local/backups'/('native-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()))
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
    run(['docker','exec',source['Id'],'sh','-c','test -r /home/suwayomi/startup/tachidesk_latest.jar'])
    cache=Path(READER_CACHE);cache.mkdir(parents=True,exist_ok=True,mode=0o700);os.chown(cache,1000,1000)
    original=overlay.read_bytes();changed=native_overlay(json.loads(original),cache)
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
        else:raise RuntimeError('Suwayomi did not recover after configuring the reader cache.')
        probe_dir=JNI_TMP+'/Tachidesk/.codex-probe'
        subprocess.run(['docker','exec','-i',source['Name'].lstrip('/'),'sh','-c','mkdir -p '+probe_dir+' && cat > '+probe_dir+'/MediaVaultNativeProbe.class'],input=native_probe(),check=True,stdout=log,stderr=log)
        run(['docker','exec',source['Name'].lstrip('/'),'java','-cp','/home/suwayomi/startup/tachidesk_latest.jar:'+probe_dir,'MediaVaultNativeProbe'])
        if account_state()!=before:raise RuntimeError('Account configuration changed unexpectedly.')
        install_cache_cleanup(root,run)
    except Exception:
        for path in [overlay,config]:shutil.copy2(backup/path.name,path)
        run([*base,'up','-d','--no-deps','suwayomi'])
        raise
    print(json.dumps({'nativeCompressionConfigured':True,'diskReaderCache':str(cache),'sources':count,'jniInitializationVerified':True,'backup':str(backup),'accountConfigurationPreserved':True}))


if __name__=='__main__':main()
