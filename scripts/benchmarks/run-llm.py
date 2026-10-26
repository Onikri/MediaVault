#!/usr/bin/env python3
"""Start a private CPU llama.cpp for quality probes; never opens a public port."""
import argparse,hashlib,json,os,socket,subprocess,sys,time
from pathlib import Path
import requests
p=argparse.ArgumentParser();p.add_argument('--server',required=True);p.add_argument('--weights',required=True);p.add_argument('--name',required=True);p.add_argument('--label',required=True);p.add_argument('--output',required=True);a=p.parse_args();output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
log=output.with_suffix('.llama.log').open('w');cmd=[a.server,'-m',a.weights,'--alias',a.name,'--host','127.0.0.1','--port',str(port),'-t','2','-c','4096','--parallel','1','--reasoning','off','--no-webui','-ngl','0']
process=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
try:
 deadline=time.monotonic()+180
 while time.monotonic()<deadline:
  if process.poll() is not None:raise RuntimeError('llama.cpp failed; inspect private benchmark log')
  try:
   if requests.get(f'http://127.0.0.1:{port}/health',timeout=2).ok:break
  except requests.RequestException:pass
  time.sleep(1)
 else:raise RuntimeError('llama.cpp startup exceeded 180 seconds')
 subprocess.run([sys.executable,str(Path(__file__).with_name('run-text.py')),'--model','openai','--url',f'http://127.0.0.1:{port}/v1','--name',a.name,'--label',a.label,'--output',str(output)],check=True,timeout=1800)
 d=json.loads(output.read_text());f=Path(a.weights);d['gguf']={'file':f.name,'bytes':f.stat().st_size,'sha256':hashlib.file_digest(f.open('rb'),'sha256').hexdigest()};d['llamaCommand']=[x if x!=a.weights else f.name for x in cmd];output.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
finally:
 process.terminate()
 try:process.wait(timeout=20)
 except subprocess.TimeoutExpired:process.kill();process.wait()
 log.close()
