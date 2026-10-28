"""Resumable language-pack installation from Suwayomi's trusted catalog only.

One sequential worker keeps extension loading bounded on the Oracle free VM.
The journal contains package names/statuses, never auth or manga pages.
"""
from pathlib import Path
import json,os,secrets,threading,time
from suwayomi_bridge import LANGUAGES,extensions,install
from source_parser import SourceError

_lock=threading.RLock();_worker=None

def journal():return Path(os.getenv('DATA_DIR','/data'))/'suwayomi-install.json'

def read():
    try:return json.loads(journal().read_text('utf-8'))
    except (OSError,ValueError):return {'state':'idle','completed':0,'total':0,'failed':[]}

def save(value):
    path=journal();path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp=path.with_suffix('.part');temp.write_text(json.dumps(value,ensure_ascii=False),'utf-8');temp.chmod(0o600);temp.replace(path)

def status():
    with _lock:
        value=read()
        if value.get('state')=='running' and not(_worker and _worker.is_alive()):value={**value,'state':'interrupted'}
        return value

def start(languages):
    global _worker
    wanted=set(languages)
    if not wanted or not wanted<=LANGUAGES:raise SourceError('Выбери RU, EN, JA или KO.')
    with _lock:
        if _worker and _worker.is_alive():return status()
        # Refreshing the catalog happens in the worker, not in the HTTP request.
        value={'id':secrets.token_urlsafe(16),'state':'running','languages':sorted(wanted),'completed':0,'installed':0,'alreadyInstalled':0,'total':0,'failed':[],'current':'Обновляем каталог','updated':time.time()}
        save(value);_worker=threading.Thread(target=run,args=(value,),daemon=True,name='suwayomi-language-pack');_worker.start()
        return value.copy()

def run(value):
    try:
        catalog=extensions()
        packages=sorted((e for e in catalog if e.get('lang') in {*value['languages'],'all'} and not e.get('obsolete')),key=lambda e:(e['lang'],e['pkgName']))
        value['total']=len(packages)
        for row in packages:
            with _lock:
                value.update(current=row['name'],updated=time.time());save(value)
            try:
                if row.get('installed'):value['alreadyInstalled']+=1
                else:install(row['pkgName']);value['installed']+=1
            except Exception:
                # Provider errors can contain URLs/tokens; journal only fixed text.
                value['failed'].append({'package':row['pkgName'],'name':row['name'],'reason':'Расширение не установилось; повтор пакета попробует его снова.'})
            with _lock:
                value['completed']+=1;value['updated']=time.time();save(value)
        value['state']='partial' if value['failed'] else 'done';value['current']=''
    except Exception:value.update(state='error',current='Каталог Suwayomi недоступен. Повтори после подключения сервера.')
    finally:
        with _lock:value['updated']=time.time();save(value)
