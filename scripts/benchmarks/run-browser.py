#!/usr/bin/env python3
"""CPU/WASM component comparisons. Checkpoints each case; supports --resume.
Run with the built developer bundle, real weight files and annotated case set.
"""
import argparse,asyncio,base64,hashlib,http.server,json,os,platform,threading,time,sys
from pathlib import Path
from playwright.async_api import async_playwright
from metrics import match_boxes,cer
p=argparse.ArgumentParser();p.add_argument('--detectors',default='comic-bubble,comic-text-detector');p.add_argument('--runtime',choices=['wasm','native'],default='wasm');p.add_argument('--threads',type=int,default=2);p.add_argument('--root',default='test-output/manga-quality');p.add_argument('--models',default='test-output/quality-models');p.add_argument('--label',required=True);p.add_argument('--resume',action='store_true');p.add_argument('--stages',default='detection,ocr,fonts');p.add_argument('--chromium',default='/usr/bin/chromium');args=p.parse_args()
root=Path(args.root).resolve();models=Path(args.models).resolve();report=root/'browser-results.json';cases=json.loads((root/'cases/cases.json').read_text())
out=json.loads(report.read_text()) if args.resume and report.exists() else {'environment':args.label,'machine':platform.machine(),'threads':1 if args.runtime=='wasm' else args.threads,'runtime':args.runtime+'-cpu','results':[]}
# Cache key includes the complete bundle, fixtures and models; stale reports fail closed.
fingerprint=hashlib.sha256(b''.join(f.read_bytes() for f in sorted((root/'browser/assets').glob('*.js')))+args.runtime.encode()+json.dumps(cases,sort_keys=True).encode()+b''.join(hashlib.sha256(f.read_bytes()).digest() for f in sorted(models.glob('*.onnx')))).hexdigest()
if out.get('fingerprint',fingerprint)!=fingerprint:raise SystemExit('Inputs changed: use a new report directory, not --resume.')
out['fingerprint']=fingerprint
out['models']=[{'file':f.name,'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in sorted(models.glob('*.onnx'))]
def save():
 report.with_suffix('.tmp').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');report.with_suffix('.tmp').replace(report)
def seen(key):return any(r.get('key')==key for r in out['results'])
class Handler(http.server.SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(root/'browser'),**kw)
 def log_message(self,*a):pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
aliases={'detector-v4-s_int8.onnx':models/'rtdetr.onnx','comictextdetector.pt.onnx':models/'ctd.onnx','ppocr-rec-v6-small-manga.onnx':models/'ppv6-jp.onnx','brainocr.onnx':models/'pororo.onnx','ocr-opt.txt':models/'pororo-dict.txt','korean_PP-OCRv5_mobile_rec.onnx':models/'korean.onnx','lama-manga-dynamic.onnx':models/'lama.onnx'}
async def main():
 async with async_playwright() as pw:
  browser=await pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox','--disable-dev-shm-usage']);page=await browser.new_page();page.set_default_timeout(300000);await page.add_init_script("Object.defineProperty(navigator,'gpu',{value:undefined,configurable:true});")
  page.on('pageerror',lambda e:print('PAGE_ERROR',str(e)[:250],flush=True))
  page.on('console',lambda m:print('BROWSER',m.text[:200],flush=True) if m.type in ['warning','error'] else None)
  async def weights(route):
   url=route.request.url;file=url.rsplit('/',1)[-1]
   if '/languages/english/' in url:path=models/('english.onnx' if file.endswith('.onnx') else 'english-dict.txt')
   elif '/languages/chinese/' in url:path=models/('paddle-cn.onnx' if file.endswith('.onnx') else 'paddle-cn-dict.txt')
   else:path=aliases.get(file)
   if not path or not path.exists():return await route.abort()
   await route.fulfill(path=str(path),headers={'access-control-allow-origin':'*'})
  await page.route('https://huggingface.co/**',weights);await page.route('https://github.com/**.onnx',weights)
  native=None
  if args.runtime=='native':
   sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
   from lmt_onnx import NativeOnnx
   native=NativeOnnx(root/'browser',models/'native-cache',args.threads)
   for f in models.glob('*.onnx'):
    sha=hashlib.sha256(f.read_bytes()).hexdigest()
    if sha in native.allowed:native.known[sha]=f
   await page.expose_function('mvOrtCreate',lambda request:native.create(request,True))
   await page.expose_function('mvOrtRun',native.run)
   await page.expose_function('mvOrtRelease',native.release)
  await page.goto('http://127.0.0.1:'+str(server.server_port)+'/benchmark.html');await page.wait_for_function('window.bench')
  async def execute(key,stage,case,model,params):
   if seen(key):print('RESUME',key,flush=True);return
   print('RUN',key,flush=True)
   start=time.perf_counter();record={'key':key,'stage':stage,'case':case['id'] if case else None,'model':model}
   try:
    result=await page.evaluate('async p=>window.bench[p.stage](...p.args)',{'stage':stage,'args':params});record.update(result)
    if stage=='detect':record['metrics']=match_boxes([r['box'] for r in case['regions']],[[b['x1'],b['y1'],b['x2'],b['y2']] for b in result['boxes']])
    if stage=='ocr':record['cer']=sum(cer(a['text'],b.get('text','')) for a,b in zip(case['regions'],result['results']))/len(case['regions']);record['reference']=[r['text'] for r in case['regions']]
    if stage=='inpaint':
     file=root/(key.replace(':','-')+'.png');file.write_bytes(bytes(record.pop('image')));record['image']=file.name
   except Exception as e:record['error']=str(e)[:500]
   record['wallMs']=round((time.perf_counter()-start)*1000);out['results'].append(record);save();print(json.dumps({k:record[k] for k in ['key','wallMs','metrics','cer','error'] if k in record}),flush=True)
  if 'detection' in args.stages.split(','):
   for model in args.detectors.split(','):
    for c in cases:
     if c.get('language'):continue
     await execute('detect:'+model+':'+c['id'],'detect',c,model,[list((root/'cases'/c['file']).read_bytes()),model])
    await page.evaluate('window.bench.release()')
  if 'ocr' in args.stages.split(','):
   for c in cases:
    language=c.get('language','English');engines={'English':['paddle'],'Japanese':['paddle','ppocrv6-manga'],'Korean':['pororo','ppocrv5-korean']}[language]
    for model in engines:
     boxes=[dict(zip(['x1','y1','x2','y2'],r['box'])) for r in c['regions']]
     await execute('ocr:'+model+':'+c['id'],'ocr',c,model,[list((root/'cases'/c['file']).read_bytes()),boxes,language,model]);await page.evaluate('window.bench.release()')
  if 'fonts' in args.stages.split(','):await execute('fonts:all','fonts',None,'bundled',[])
  if 'inpaint' in args.stages.split(','):
   for model in ['fast','quality']:
    for c in cases:
     if c.get('language'):continue
     boxes=[dict(zip(['x1','y1','x2','y2'],r['box'])) for r in c['regions']]
     await execute('inpaint:'+model+':'+c['id'],'inpaint',c,model,[list((root/'cases'/c['file']).read_bytes()),boxes,model])
  if native:await native.close()
  await browser.close()
asyncio.run(main());server.shutdown();save();print('REPORT',report)
