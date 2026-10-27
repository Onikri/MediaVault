#!/usr/bin/env python3
"""Apply the reviewed progress update via the user's existing Cloud Shell CLI.

No IAM key registration. Updates only the existing manga sidecar; its data,
Google key, importer and Caddy configuration are preserved. Commit must be pinned.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

class UpdateError(RuntimeError): pass

def check_revision(value):
    if not re.fullmatch(r'[a-f0-9]{40}',value):raise UpdateError('Нужен полный проверенный SHA коммита.')
    return value

def bootstrap(revision):
    check_revision(revision)
    return "sudo python3 - <<'MV_PROGRESS'\nimport urllib.request,subprocess,sys\nfrom pathlib import Path\np=Path('/opt/mediavault-manga-batch/update-progress-"+revision[:12]+".py')\np.write_bytes(urllib.request.urlopen('https://raw.githubusercontent.com/Onikri/MediaVault/"+revision+"/deploy/oracle/update-manga-progress.py',timeout=45).read())\nsubprocess.run([sys.executable,str(p),'--on-vm','--revision','"+revision+"'],check=True)\nMV_PROGRESS\n"

def cli(region,*arguments):
    prefix=['oci','--region',region,'--output','json','--query','@','--connection-timeout','10','--read-timeout','30']
    try:r=subprocess.run([*prefix,*arguments],capture_output=True,text=True,timeout=90)
    except (OSError,subprocess.TimeoutExpired):raise UpdateError('OCI CLI не ответил. Проверь открытую сессию Cloud Shell.') from None
    if r.returncode:
        code=re.search(r'"code"\s*:\s*"([A-Za-z0-9_-]+)"',r.stderr)
        raise UpdateError('Oracle отклонил команду: '+(code[1] if code else 'ошибка OCI CLI')+'.')
    try:return json.loads(r.stdout)['data']
    except (ValueError,KeyError,TypeError):raise UpdateError('Oracle вернул неожиданный ответ. Не запускай установку повторно вслепую.') from None

def cloud_shell(revision,instance_id,region):
    if not shutil.which('oci'):raise UpdateError('Выполни команду в авторизованной Oracle Cloud Shell.')
    if not re.fullmatch(r'ocid1\.instance\.[a-zA-Z0-9.-]+',instance_id or ''):raise UpdateError('Нужен OCID существующей ВМ.')
    instance=cli(region,'compute','instance','get','--instance-id',instance_id)
    content={'source':{'sourceType':'TEXT','text':bootstrap(revision)},'output':{'outputType':'TEXT'}}
    command=cli(region,'instance-agent','command','create','--compartment-id',instance['compartment-id'],'--display-name','MediaVault live translation progress','--target',json.dumps({'instanceId':instance_id}),'--content',json.dumps(content),'--timeout-in-seconds','600')
    identity=command['id'];print('Oracle принял установку: '+identity,flush=True)
    print('Ожидаем агент ВМ. Эта команда не создаёт ключи доступа.',flush=True)
    start=time.monotonic()
    for _ in range(50):
        result=cli(region,'instance-agent','command-execution','get','--command-id',identity,'--instance-id',instance_id)
        state=result['lifecycle-state'];delivery=result.get('delivery-state','')
        if state in ('SUCCEEDED','FAILED','TIMED_OUT','CANCELED'):
            output=result.get('content') or {};text=output.get('text','').strip()
            if state!='SUCCEEDED' or output.get('exit-code',0)!=0:
                print('Команда Oracle: '+state,flush=True)
                if text:print(text[-900:],flush=True)
                raise UpdateError('Установка не подтвердилась. Пришли результат команды из Cloud Shell.')
            print(text or json.dumps({'oracleState':state,'message':'Проверь статус сервиса на сайте.'}),flush=True)
            return
        print('Oracle: '+delivery+' / '+state+' · прошло '+str(round(time.monotonic()-start))+' с',flush=True)
        time.sleep(10)
    raise UpdateError('Oracle ещё выполняет команду '+identity+'. Не запускай вторую установку; проверь Run Command в консоли.')

def install(revision, *, root=None):
    if os.geteuid()!=0:raise UpdateError('Установка на ВМ требует root.')
    root=root or Path('/opt/mediavault-manga-batch');root.mkdir(exist_ok=True,mode=0o750)
    work=root/('live-progress-'+revision[:12]);work.mkdir(exist_ok=True,mode=0o750)
    log=(work/'install.log').open('a')
    try:
        def run(arguments,**kwargs):return subprocess.run(arguments,stdout=log,stderr=log,check=True,**kwargs)
        def inspect(name):return json.loads(subprocess.check_output(['docker','inspect',name],timeout=15))[0]
        name='mediavault-manga-batch';old=inspect(name);importer=inspect('oracle-importer-1')
        image='mediavault-manga-batch:live-progress-'+revision[:12]
        def readiness(container):
            code="import json,urllib.request;v=json.load(urllib.request.urlopen('http://127.0.0.1:7863/api/v1/manga-translation/status',timeout=5));assert v['ready'] and v.get('progressVersion')==1;print(json.dumps({'ready':v['ready'],'configured':v['configured'],'progressVersion':v['progressVersion']}))"
            for _ in range(20):
                r=subprocess.run(['docker','exec',container,'python','-c',code],capture_output=True,text=True,timeout=10)
                if r.returncode==0:return json.loads(r.stdout)
                time.sleep(1)
            raise UpdateError('Новая служба не прошла проверку готовности.')
        if old['Config']['Image']==image:
            print(json.dumps({'alreadyInstalled':True,**readiness(name)}));return
        for filename in ['provider.py','orchestrator.py','app.py','progress.py']:
            url='https://raw.githubusercontent.com/Onikri/MediaVault/'+revision+'/server/manga_batch/'+filename
            with urllib.request.urlopen(url,timeout=40) as response:data=response.read()
            compile(data,filename,'exec');(work/filename).write_bytes(data)
        (work/'Dockerfile').write_text('FROM '+old['Config']['Image']+'\nCOPY --chown=vault:vault provider.py orchestrator.py app.py progress.py /app/manga_batch/\n')
        run(['docker','build','-t',image,str(work)],timeout=240)
        network=next(iter(old['NetworkSettings']['Networks']))
        common=['--network',network,'--restart','unless-stopped','--cpus=2','--memory=2g','--memory-swap=2g','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--tmpfs','/tmp:rw,nosuid,nodev,size=32m,uid=1000,gid=1000','--env-file',str(root/'service.env')]
        mounts={m['Destination']:m for m in old['Mounts'] if m['Type']=='bind'}
        if not {'/data','/models','/importer'}<=set(mounts):raise UpdateError('Существующие тома отличаются от ожидаемых; требуется проверка.')
        for m in mounts.values():common+=['-v',m['Source']+':'+m['Destination']+('' if m['RW'] else ':ro')]
        def start(container,alias=False):run(['docker','run','-d','--name',container,*(['--network-alias','manga-batch'] if alias else []),*common,image],timeout=45)
        candidate=name+'-progress-check-'+revision[:8]
        exists=subprocess.run(['docker','inspect',candidate],stdout=log,stderr=log,timeout=10).returncode==0
        if exists:run(['docker','rm','-f',candidate],timeout=20)
        try:start(candidate);readiness(candidate)
        finally:subprocess.run(['docker','rm','-f',candidate],stdout=log,stderr=log,timeout=20)
        backup=name+'-before-progress-'+revision[:8]
        if subprocess.run(['docker','inspect',backup],stdout=log,stderr=log,timeout=10).returncode==0:raise UpdateError('Найден контейнер отката этой версии. Сначала проверь предыдущую установку.')
        run(['docker','stop','--time','15',name],timeout=25);run(['docker','rename',name,backup],timeout=15)
        try:
            start(name,True);state=readiness(name)
            run(['docker','exec','oracle-https-1','caddy','reload','--config','/etc/caddy/Caddyfile'],timeout=25)
        except BaseException:
            subprocess.run(['docker','rm','-f',name],stdout=log,stderr=log,timeout=20)
            run(['docker','rename',backup,name],timeout=15);run(['docker','start',name],timeout=25)
            raise
        after=inspect('oracle-importer-1')
        result={'updated':True,'revision':revision,**state,'importerUnchanged':after['Id']==importer['Id'] and after['RestartCount']==importer['RestartCount'],'googleKeyPreserved':(Path(mounts['/data']['Source'])/'google-api-key').is_file()}
        (work/'result.json').write_text(json.dumps(result));print(json.dumps(result),flush=True)
    finally:log.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--revision',required=True);parser.add_argument('--instance-id');parser.add_argument('--region',default='eu-frankfurt-1');parser.add_argument('--on-vm',action='store_true');args=parser.parse_args()
    try:
        revision=check_revision(args.revision)
        if args.on_vm:install(revision)
        else:cloud_shell(revision,args.instance_id,args.region)
    except (UpdateError,OSError,subprocess.SubprocessError) as error:
        print(str(error) if isinstance(error,UpdateError) else 'Установка не завершилась. Диагностика сохранена в /opt/mediavault-manga-batch/live-progress-*/install.log.',file=sys.stderr);return 1
    return 0

if __name__=='__main__':sys.exit(main())
