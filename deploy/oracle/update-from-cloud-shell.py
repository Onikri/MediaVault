#!/usr/bin/env python3
"""Update the existing VM through the owner's OCI CLI; no credentials are exported."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time


class UpdateError(RuntimeError):pass


def command(arguments,region):
    try:
        result=subprocess.run(['oci','--region',region,'--output','json','--query','@',*arguments],capture_output=True,text=True,timeout=100)
    except (OSError,subprocess.TimeoutExpired):raise UpdateError('OCI CLI не ответил. Повтори из авторизованного Cloud Shell.') from None
    if result.returncode:
        code=re.search(r'"code"\s*:\s*"([\w-]+)"',result.stderr)
        raise UpdateError('Oracle отклонил запрос: '+(code[1] if code else 'ошибка доступа')+'.')
    try:return json.loads(result.stdout)['data']
    except (ValueError,KeyError):raise UpdateError('Неизвестный ответ OCI CLI.') from None


def remote_script(revision):
    if not re.fullmatch('[a-f0-9]{40}',revision):raise UpdateError('Нужен полный проверенный SHA коммита.')
    url=f'https://raw.githubusercontent.com/Onikri/MediaVault/{revision}/deploy/oracle/update-existing.sh'
    return f'''set -euo pipefail
if ! sudo -n true 2>/dev/null; then
  echo 'Run Command не имеет sudo на VM. Обновление не начиналось; нужен административный SSH-доступ.'
  exit 5
fi
script=$(mktemp)
trap 'rm -f "$script"' EXIT
curl -fsSL '{url}' -o "$script"
sudo -n bash "$script" '{revision}'
'''


def deploy(revision,region,*,instance_id=None,enable_plugin=False,cli=command,report=print,pause=time.sleep):
    script=remote_script(revision)
    if not instance_id:
        inventory=cli(['search','resource','structured-search','--query-text',"query instance resources where displayName = 'mediavault-import' && lifecycleState = 'RUNNING'"],region)
        items=inventory.get('items',[])
        if len(items)!=1:raise UpdateError('Не найдена одна работающая mediavault-import. Укажи её OCID через --instance-id; новые VM не создаются.')
        instance_id=items[0]['identifier']
    if not re.fullmatch(r'ocid1\.instance\.[a-zA-Z0-9.]+',instance_id):raise UpdateError('Некорректный OCID существующей VM.')
    instance=cli(['compute','instance','get','--instance-id',instance_id],region)
    if instance.get('lifecycle-state')!='RUNNING':raise UpdateError('Существующая VM не запущена. Скрипт не запускает и не пересоздаёт VM.')
    config=instance.get('agent-config') or {}
    if config.get('are-all-plugins-disabled') or config.get('is-management-disabled'):
        raise UpdateError('В Oracle Cloud Agent отключено управление. В консоли включи только Compute Instance Run Command для этой VM.')
    plugins=config.get('plugins-config') or []
    plugin=next((p for p in plugins if p.get('name')=='Compute Instance Run Command'),None)
    if not plugin or plugin.get('desired-state')!='ENABLED':
        if not enable_plugin:raise UpdateError('Compute Instance Run Command не включён. Для его включения добавь --enable-run-command.')
        preserved=[{'name':p['name'],'desiredState':p['desired-state']} for p in plugins if p.get('name') and p.get('desired-state') and p['name']!='Compute Instance Run Command']
        preserved.append({'name':'Compute Instance Run Command','desiredState':'ENABLED'})
        cli(['compute','instance','update','--instance-id',instance_id,'--agent-config',json.dumps({'pluginsConfig':preserved}),'--force'],region)
        report('Включён Compute Instance Run Command на существующей VM. Другие настройки плагинов сохранены.')
    content={'source':{'sourceType':'TEXT','text':script},'output':{'outputType':'TEXT'}}
    created=cli(['instance-agent','command','create','--compartment-id',instance['compartment-id'],
                 '--target',json.dumps({'instanceId':instance_id}),'--content',json.dumps(content),
                 '--timeout-in-seconds','1200','--display-name','MediaVault update '+revision[:12]],region)
    identifier=created['id'];report('Обновление отправлено в Oracle. Сборка Chromium может занять несколько минут.')
    previous=None
    for _ in range(260):
        value=cli(['instance-agent','command-execution','get','--command-id',identifier,'--instance-id',instance_id],region)
        state=value.get('lifecycle-state','UNKNOWN')
        if state!=previous:report('Состояние: '+state);previous=state
        if state in {'SUCCEEDED','FAILED','TIMED_OUT','CANCELED','CANCELLED','EXPIRED'}:
            output=value.get('content') or {};text=output.get('text','') if isinstance(output,dict) else ''
            if text:report(text[-4000:])
            code=value.get('exit-code',value.get('exitCode'))
            if state=='SUCCEEDED' and code in (None,0) and 'health version 6 confirmed' in text:
                return {'updated':True,'revision':revision,'health_version':6}
            raise UpdateError('Oracle завершил команду без подтверждения новой версии. Сообщение выше показывает причину; не повторяй обновление вслепую.')
        pause(5)
    raise UpdateError('Истекло время ожидания. Проверь команду в Oracle Run Command; повторное обновление не запускалось.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision',required=True)
    parser.add_argument('--region',default='eu-frankfurt-1')
    parser.add_argument('--instance-id')
    parser.add_argument('--enable-run-command',action='store_true')
    args=parser.parse_args()
    if not shutil.which('oci'):raise UpdateError('Запусти эту команду в Oracle Cloud Shell с авторизованным OCI CLI.')
    print(json.dumps(deploy(args.revision,args.region,instance_id=args.instance_id,enable_plugin=args.enable_run_command),ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except (UpdateError,KeyError) as error:
        print(str(error) if isinstance(error,UpdateError) else 'Ответ Oracle неполон; обновление не подтверждено.',file=sys.stderr)
        sys.exit(1)
