#!/usr/bin/env python3
"""Host-side metrics for the owner control center.

Runs on the VM (systemd unit mediavault-host-status.service) and every 10 s
writes containers, the busiest processes and the root disk to
<data>/host-status.json. The importer reads that file; it never gets the Docker
socket. Process names come from `comm` only, so command-line secrets never leave
the host.
Usage: host-status.py /path/to/importer/data
"""
import json,os,shutil,subprocess,sys,time

def run(*args):
    try:return subprocess.run(args,capture_output=True,text=True,timeout=15).stdout
    except Exception:return ''

def rows(text):
    for line in text.splitlines():
        try:yield json.loads(line)
        except ValueError:pass

def snapshot():
    stats={s.get('ID','')[:12]:s for s in rows(run('docker','stats','--no-stream','--format','{{json .}}'))}
    containers=[]
    for c in rows(run('docker','ps','-a','--format','{{json .}}')):
        s=stats.get(c.get('ID','')[:12],{})
        containers.append({'name':c.get('Names'),'image':c.get('Image'),'state':c.get('State'),'status':c.get('Status'),
                           'cpu':s.get('CPUPerc'),'memory':s.get('MemUsage'),'memoryPercent':s.get('MemPerc'),
                           'net':s.get('NetIO'),'block':s.get('BlockIO'),'pids':s.get('PIDs')})
    processes=[]
    for line in run('ps','-eo','pid,user,pcpu,pmem,rss,etimes,comm','--sort=-pcpu','--no-headers').splitlines()[:12]:
        p=line.split(None,6)
        if len(p)==7:
            try:processes.append({'pid':int(p[0]),'user':p[1],'cpu':float(p[2]),'memory':float(p[3]),'rss':int(p[4])*1024,'elapsed':int(p[5]),'command':p[6]})
            except ValueError:pass
    disk=shutil.disk_usage('/')
    return {'at':time.time(),'containers':containers,'processes':processes,'disk':{'total':disk.total,'used':disk.used,'free':disk.free}}

def write(path,value):
    temporary=path+'.tmp'
    with open(temporary,'w',encoding='utf-8') as handle:json.dump(value,handle)
    os.chmod(temporary,0o644);os.replace(temporary,path)

if __name__=='__main__':
    target=os.path.join(sys.argv[1],'host-status.json')
    while True:
        try:write(target,snapshot())
        except Exception as error:print('host-status: '+str(error),file=sys.stderr,flush=True)
        time.sleep(10)
