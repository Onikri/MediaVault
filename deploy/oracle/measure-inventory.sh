#!/usr/bin/env bash
set -euo pipefail
sudo -n python3 - <<'PY'
import json,os,platform,subprocess
from pathlib import Path
memory={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in Path('/proc/meminfo').read_text().splitlines()}
print(json.dumps({'architecture':platform.machine(),'cpus':os.cpu_count(),'loadAverage':os.getloadavg(),'memory':{key:memory[key] for key in ['MemTotal','MemAvailable','SwapTotal','SwapFree']}}))
print(subprocess.check_output(['df','-h','/'],text=True))
print(subprocess.check_output(['docker','stats','--no-stream','--format','{{.Name}} CPU={{.CPUPerc}} RAM={{.MemUsage}}'],text=True))
ids=subprocess.check_output(['docker','ps','-q'],text=True).split()
items=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True)) if ids else []
for item in items:
 labels=item.get('Config',{}).get('Labels') or {}
 if labels.get('com.docker.compose.service')!='importer':continue
 print(json.dumps({'importer':item['Name'],'image':item['Config']['Image'],'workingDirectory':labels.get('com.docker.compose.project.working_dir'),'dataMounts':[{'source':m['Source'],'destination':m['Destination']} for m in item['Mounts'] if m['Destination']=='/data']}))
 print(subprocess.check_output(['docker','exec',item['Id'],'python','-c','import json,urllib.request;print(json.dumps(json.load(urllib.request.urlopen("http://127.0.0.1:7860/health",timeout=5))))'],text=True))
PY
