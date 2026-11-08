"""Owner-only server metrics for the control center.

CPU, memory, load and the data-disk numbers come from /proc and statvfs, which
inside the importer container describe the whole VM. Containers and host
processes cannot be seen from the container (no Docker socket is mounted on
purpose); deploy/oracle/host-status.sh writes them to DATA_DIR/host-status.json
from the host and this module only reads that file.
"""
import json,os,shutil,threading,time
import requests
from fastapi import Depends,HTTPException

_cpu={'sample':None,'percent':None}
_lock=threading.Lock()
_quota={}
QUOTA_TTL=300

def _read(path):
    try:
        with open(path,encoding='utf-8') as handle:return handle.read()
    except OSError:return ''

def cpu_percent():
    line=_read('/proc/stat').split('\n',1)[0].split()
    if len(line)<5 or line[0]!='cpu':return None
    values=[int(v) for v in line[1:]];idle=values[3]+(values[4] if len(values)>4 else 0);total=sum(values)
    with _lock:
        previous=_cpu['sample'];_cpu['sample']=(total,idle)
        if previous and total>previous[0]:_cpu['percent']=round(100*(1-(idle-previous[1])/(total-previous[0])),1)
        return _cpu['percent']

def memory():
    info={}
    for row in _read('/proc/meminfo').splitlines():
        name,_,rest=row.partition(':');parts=rest.split()
        if parts:info[name]=int(parts[0])*1024
    if 'MemTotal' not in info:return None
    available=info.get('MemAvailable',info.get('MemFree',0))
    return {'total':info['MemTotal'],'used':info['MemTotal']-available,'available':available,
            'swapTotal':info.get('SwapTotal',0),'swapUsed':info.get('SwapTotal',0)-info.get('SwapFree',0)}

def host(data_dir):
    load=_read('/proc/loadavg').split()
    uptime=_read('/proc/uptime').split()
    try:disk=shutil.disk_usage(data_dir);disk={'total':disk.total,'used':disk.used,'free':disk.free}
    except OSError:disk=None
    return {'cpu':cpu_percent(),'cores':os.cpu_count(),'load':[float(v) for v in load[:3]] if len(load)>=3 else None,
            'memory':memory(),'disk':disk,'uptime':float(uptime[0]) if uptime else None}

def host_report(data_dir,now=None):
    """Containers and processes from the host helper; stale reports are flagged, not hidden."""
    try:
        with open(os.path.join(data_dir,'host-status.json'),encoding='utf-8') as handle:report=json.load(handle)
    except (OSError,ValueError):return {'available':False}
    at=float(report.get('at') or 0);now=now or time.time()
    return {'available':True,'at':at,'stale':now-at>90,'containers':report.get('containers') or [],
            'processes':report.get('processes') or [],'hostDisk':report.get('disk')}

def drive_quota(subject,credentials,now=None):
    now=now or time.time();cached=_quota.get(subject)
    if cached and now-cached['checkedAt']<QUOTA_TTL:return cached
    credential=credentials(subject)
    if not credential.valid:
        from google.auth.transport.requests import Request
        credential.refresh(Request())
    response=requests.get('https://www.googleapis.com/drive/v3/about',params={'fields':'storageQuota'},
                          headers={'Authorization':'Bearer '+credential.token},timeout=8)
    response.raise_for_status();quota=response.json().get('storageQuota') or {}
    number=lambda key:int(quota[key]) if quota.get(key) not in (None,'') else None
    value={'limit':number('limit'),'usage':number('usage'),'drive':number('usageInDrive'),'trash':number('usageInDriveTrash'),'checkedAt':now}
    _quota[subject]=value;return value

def install(app,owner,data_dir,credentials,store):
    @app.get('/admin/system')
    def system(subject=Depends(owner)):
        return {'host':host(data_dir()),**host_report(data_dir()),'at':time.time()}
    @app.get('/admin/drive-quota')
    def quota(subject=Depends(owner)):
        if not store().setting('google:'+subject):raise HTTPException(409,'Google Диск не подключён к серверу.')
        try:return drive_quota(subject,credentials)
        except requests.HTTPError as error:raise HTTPException(502,'Google не отдал объём Диска ('+str(error.response.status_code)+').')
        except Exception:raise HTTPException(502,'Не удалось узнать объём Google Диска.')
