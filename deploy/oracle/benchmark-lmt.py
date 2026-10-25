#!/usr/bin/env python3
"""Read-only LMT benchmark inside the existing importer container.

No api/TaskStore imports, resource changes, paid API or user media writes.
Uses the already published short translation demo (not a redistributed page).
Each scenario has cold and warm measurements. Network/cache work is reported.
"""
import argparse,base64,hashlib,json,os,re,resource,statistics,time,sys,threading,platform
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright

p=argparse.ArgumentParser();p.add_argument('--engine-url',default='https://onikri.github.io/MediaVault/lmt/index.html');p.add_argument('--runs',type=int,default=2);p.add_argument('--label',default='unspecified');p.add_argument('--models-dir');p.add_argument('--vision-url');p.add_argument('--vision-model');args=p.parse_args()
if not 1<=args.runs<=5:raise SystemExit('runs must be 1..5')
html=requests.get('https://onikri.github.io/MediaVault/translation-demo.html',timeout=30);html.raise_for_status()
m=re.search(r'data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)',html.text)
if not m:raise SystemExit('Published cropped demo image not found')
image=base64.b64decode(m[1]);sample_hash=hashlib.sha256(image).hexdigest()
sys.path.insert(0,os.getcwd())
from reader_translation import translate_image,translate_texts
# This import has no app startup, queue-recovery or TaskStore side effects.
rss_peak=[0];sampling=threading.Event()
def sample_memory():
 while not sampling.wait(.1):
  processes={}
  for status in Path('/proc').glob('[0-9]*/status'):
   try:
    text=status.read_text();parent=int(re.search(r'^PPid:\s+(\d+)',text,re.M)[1]);rss=re.search(r'^VmRSS:\s+(\d+)',text,re.M)
    processes[int(status.parent.name)]=(parent,int(rss[1]) if rss else 0)
   except (OSError,TypeError,ValueError):continue
  family={os.getpid()}
  for _ in range(10):
   extra={pid for pid,(parent,rss) in processes.items() if parent in family};new=family|extra
   if new==family:break
   family=new
  rss_peak[0]=max(rss_peak[0],sum(processes.get(pid,(0,0))[1] for pid in family))
sampler=threading.Thread(target=sample_memory,daemon=True);sampler.start()
results=[];data_dir=os.getenv('DATA_DIR','/data')
t=time.perf_counter();translate_texts(['Hello.'],data_dir);argos_warmup_ms=round((time.perf_counter()-t)*1000)
for run in range(args.runs):
 t=time.perf_counter();output=translate_image(image,data_dir);results.append({'scenario':'existing-oracle-en-ru','run':run,'wallMs':round((time.perf_counter()-t)*1000),'regions':output['regions']})

with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
 context=browser.new_context();page=context.new_page();page.set_default_timeout(300000)
 traffic={'requests':0,'downloadedBodyBytes':0}
 def count(response):
  if 'huggingface.co' in response.url:
   traffic['requests']+=1
   try:traffic['downloadedBodyBytes']+=len(response.body())
   except Exception:pass
 page.on('response',count)
 if args.models_dir:
  directory=Path(args.models_dir);manifest=json.loads((directory/'manifest.json').read_text())
  def cached_model(route):
   name=manifest.get(route.request.url)
   if not name:raise RuntimeError('No pre-downloaded model for '+route.request.url)
   route.fulfill(body=(directory/Path(name).name).read_bytes(),headers={'access-control-allow-origin':'*'})
  context.route('https://huggingface.co/**',cached_model)
 def local_translation(route):
  if route.request.method=='OPTIONS':return route.fulfill(status=204,headers={'access-control-allow-origin':'*','access-control-allow-headers':'*'})
  body=route.request.post_data_json;text=body['messages'][1]['content'];texts=[json.loads(s) for s in re.findall(r'Box \d+: ("(?:[^"\\]|\\.)*")',text)]
  translated=translate_texts(texts,data_dir)
  route.fulfill(json={'choices':[{'message':{'content':json.dumps({'translations':translated,'context':{'summary':'','dictionary':''}},ensure_ascii=False)}}]},headers={'access-control-allow-origin':'*'})
 context.route('https://mv-benchmark.invalid/v1/chat/completions',local_translation)
 if args.vision_url and args.vision_model:
  def vision_request(route):
   if route.request.method=='OPTIONS':return route.fulfill(status=204,headers={'access-control-allow-origin':'*','access-control-allow-headers':'*'})
   response=requests.post(args.vision_url.rstrip('/')+'/chat/completions',json=route.request.post_data_json,timeout=300)
   route.fulfill(status=response.status_code,body=response.content,content_type='application/json',headers={'access-control-allow-origin':'*'})
  context.route('https://mv-benchmark-vision.invalid/v1/chat/completions',vision_request)
 page.goto(args.engine_url,wait_until='load',timeout=90000)
 evaluate="""async({image,config})=>{const c=new MessageChannel(),bytes=Uint8Array.from(atob(image),c=>c.charCodeAt(0)).buffer;return new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Pipeline exceeds 5 minutes')),300000);c.port1.onmessage=({data})=>{if(data.ready)c.port1.postMessage({type:'translate',id:1,bytes,config},[bytes]);else if(data.error){clearTimeout(timer);c.port1.close();reject(Error(data.error));}else if(data.result){clearTimeout(timer);c.port1.close();const r=data.result;resolve({engine:r.engine,regions:r.regions,timings:r.timings,inpaint:r.inpaint,warnings:r.warnings,inputMode:r.inputMode,imageBytes:r.renderedImage?.byteLength});}};window.postMessage({type:'mv-lmt-connect'},location.origin,[c.port2]);});}"""
 scenarios=[('lmt-ocr-argos',{'allowDownloads':True,'mode':'api','apiInput':'text','host':'https://mv-benchmark.invalid/v1','serverModel':'existing-local-argos','language':'English','ocr':'paddle','inpaint':'fast'})]
 if args.vision_url and args.vision_model:
  scenarios.append(('lmt-vision',{'allowDownloads':True,'mode':'api','apiInput':'vision','host':'https://mv-benchmark-vision.invalid/v1','serverModel':args.vision_model,'language':'English','inpaint':'fast'}))
 for name,config in scenarios:
  for run in range(args.runs):
   t=time.perf_counter()
   try:r=page.evaluate(evaluate,{'image':base64.b64encode(image).decode(),'config':config});r.update({'scenario':name,'run':run,'wallMs':round((time.perf_counter()-t)*1000)});results.append(r)
   except Exception as e:results.append({'scenario':name,'run':run,'error':str(e)[:300]});break
 browser.close()
sampling.set();sampler.join(1)
print(json.dumps({'executionLabel':args.label,'machine':platform.machine(),'approxProcessTreePeakRssKiB':rss_peak[0],'sample':'public-short-cropped-demo','sampleSHA256':sample_hash,'argosSharedWarm':True,'argosWarmupMs':argos_warmup_ms,'comparisonNotes':'Existing pipeline returns text overlays; LMT also renders inpainting/typesetting. Compare stages and text separately, not a blanket speedup ratio.','cpuCount':os.cpu_count(),'pythonMaxRssKiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'childMaxRssKiB':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,'modelTraffic':traffic,'modelFetchMode':'pre-downloaded-real-weights' if args.models_dir else 'network-and-browser-cache','visionTested':bool(args.vision_url and args.vision_model),'results':results},ensure_ascii=False))
