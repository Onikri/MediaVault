"""Real fixed ONNX Moebius comparison without opening a browser.

Uses exactly the exported weights and DDIM schedule, seed, guidance and letterbox
settings of lmt/moebius. Native DirectML/CUDA/CPU timings are labelled separately
from WebGPU. Input masks must be exported by the production JS mask builder.
"""
import argparse,hashlib,json,math,time,os,sys
from pathlib import Path
import numpy as np
from PIL import Image
import onnxruntime as ort

HASHES={'vae_encoder.onnx':'b8b81d41e757222a0707665ba9d826703987855e5bed056036b90b988968042f','vae_decoder.onnx':'d90ef0b7f6c8c8b7234459c8b449d70be0033bf1576c842e8b9991baf3934280','unet.onnx':'e3f90f52f72378339b990459fadb29a68d3c7b5c6851545ba42774f489160b08'}
def randn(n,seed):
 s=seed&0xffffffff
 def rng():
  nonlocal s
  s=(s+0x6d2b79f5)&0xffffffff;t=((s^(s>>15))*(1|s))&0xffffffff;t=((t+(((t^(t>>7))*(61|t))&0xffffffff))^t)&0xffffffff
  return ((t^(t>>14))&0xffffffff)/4294967296
 out=np.zeros(n,dtype=np.float32)
 for i in range(n):
  u=rng()
  while u==0:u=rng()
  v=rng()
  while v==0:v=rng()
  out[i]=math.sqrt(-2*math.log(u))*math.cos(2*math.pi*v)
 return out

class Moebius:
 def __init__(self,models,provider='DmlExecutionProvider',device=0,profile=None):
  started=time.perf_counter();self.sessions={};self.provider=provider
  if provider=='CUDAExecutionProvider':
   bins=list((Path(sys.prefix)/'Lib/site-packages/nvidia').glob('*/bin'));self.dll_handles=[os.add_dll_directory(str(p)) for p in bins] if os.name=='nt' else [];os.environ['PATH']=os.pathsep.join(str(p) for p in bins)+os.pathsep+os.environ['PATH'];ort.preload_dlls(directory='')
  for name in HASHES:
   path=Path(models)/name
   with path.open('rb') as file:assert hashlib.file_digest(file,'sha256').hexdigest()==HASHES[name],name+' checksum'
   options=ort.SessionOptions();options.enable_mem_pattern=False;options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL;options.intra_op_num_threads=2;options.inter_op_num_threads=1;options.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL
   if profile:options.enable_profiling=True;options.profile_file_prefix=str(Path(profile)/name)
   providers=[(provider,{'device_id':device}),'CPUExecutionProvider'] if provider!='CPUExecutionProvider' else [provider]
   self.sessions[name]=ort.InferenceSession(str(path),sess_options=options,providers=providers)
   self.sessions[name].disable_fallback()
   assert self.sessions[name].get_providers()[0]==provider,'Requested GPU provider unavailable'
   print('Loaded',name,self.sessions[name].get_providers(),flush=True)
  self.startup_ms=round((time.perf_counter()-started)*1000,2)
  self.run_count=0
  self.alpha=np.cumprod(1-np.linspace(math.sqrt(.00085),math.sqrt(.012),1000,dtype=np.float64)**2)
 def run(self,rgb,mask,whole_page=False):
  assert rgb.shape==(512,512,3) and mask.shape==(512,512)
  start=time.perf_counter();self.run_count+=1
  if self.run_count==1:print('First inference: encoding',flush=True)
  image=rgb.astype(np.float32).transpose(2,0,1)/127.5-1;masked=image*(1-mask[None])
  moments=self.sessions['vae_encoder.onnx'].run(None,{'image':masked[None].astype(np.float32)})[0]
  latent=moments[:,:4]*np.float32(.13025)
  if self.run_count==1:print('First inference: encoder complete',round(time.perf_counter()-start,2),flush=True)
  # Legacy: PyTorch-nearest top-left. Page mode: max pooling keeps small text.
  small=(mask.reshape(64,8,64,8).max(axis=(1,3)) if whole_page else mask[::8,::8])[None,None].astype(np.float32)
  noisy=randn(4*64*64,42).reshape(1,4,64,64);noisy+=np.float32(.0357)*randn(4,42^0x9e3779b9).reshape(1,4,1,1)
  ids=np.array([[*range(10,20)],[*range(10)]],dtype=np.int64)
  steps=list(range(800,-1,-100))
  for index,t in enumerate(steps):
   if self.run_count==1:print('First inference: denoise',index+1,round(time.perf_counter()-start,2),flush=True)
   nine=np.concatenate([noisy,small,latent],axis=1);batch=np.concatenate([nine,nine],axis=0)
   raw=self.sessions['unet.onnx'].run(None,{'latent':batch,'timesteps':np.array([t,t],dtype=np.int64),'input_ids':ids})[0]
   eps=raw[:1]+np.float32(3)*(raw[1:]-raw[:1]);prev=steps[index+1] if index+1<len(steps) else -1
   a=self.alpha[t];b=self.alpha[prev] if prev>=0 else 1
   # JS computes scalar arithmetic as float64, then writes Float32Array.
   clean=(noisy.astype(np.float64)-math.sqrt(1-a)*eps.astype(np.float64))/math.sqrt(a)
   noisy=(math.sqrt(b)*clean+math.sqrt(1-b)*eps).astype(np.float32)
  if self.run_count==1:print('First inference: decoding',round(time.perf_counter()-start,2),flush=True)
  decoded=self.sessions['vae_decoder.onnx'].run(None,{'latent':noisy/np.float32(.13025)})[0][0]
  result=np.clip(np.floor((decoded.transpose(1,2,0)+1)*127.5+.5),0,255).astype(np.uint8)
  assert all(session.get_providers()[0]==self.provider for session in self.sessions.values()),'Provider changed during inference'
  return result,round((time.perf_counter()-start)*1000,2)
 def profiles(self):
  from collections import Counter
  result={}
  for name,session in self.sessions.items():
   if session.get_session_options().enable_profiling:
    path=session.end_profiling();events=json.loads(Path(path).read_text());result[name]=dict(Counter(event.get('args',{}).get('provider') for event in events if event.get('args',{}).get('provider')))
  return result

def fitted(rgb,mask,layout,pooled=None):
 x,y,w,h=layout['x'],layout['y'],layout['w'],layout['h'];image=Image.fromarray(rgb).resize((w,h),Image.Resampling.BILINEAR)
 result=np.full((512,512,3),255,dtype=np.uint8);result[y:y+h,x:x+w]=np.asarray(image)
 if pooled is not None:holes=pooled.astype(np.float32)
 else:
  holes=np.zeros((512,512),dtype=np.float32);holes[y:y+h,x:x+w]=(np.asarray(Image.fromarray(mask.astype(np.uint8)*255).resize((w,h),Image.Resampling.BILINEAR))>=128).astype(np.float32)
 return result,holes
def layout(width,height):
 scale=min(512/width,512/height);w=max(1,int(width*scale+.5));h=max(1,int(height*scale+.5));return {'w':w,'h':h,'x':(512-w)//2,'y':(512-h)//2}
def restore(output,geometry,width,height):
 x,y,w,h=(geometry[k] for k in ['x','y','w','h']);return np.asarray(Image.fromarray(output[y:y+h,x:x+w]).resize((width,height),Image.Resampling.BILINEAR))

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--models',required=True);parser.add_argument('--provider',default='DmlExecutionProvider');parser.add_argument('--device',type=int,default=0);parser.add_argument('--only');parser.add_argument('--runs',type=int,default=2);parser.add_argument('--verify-gpu',action='store_true');args=parser.parse_args()
 root=Path(args.root);cases=json.loads((root/'prepared.json').read_text());model=Moebius(args.models,args.provider,args.device,root if args.verify_gpu else None);results=[]
 # Report cold setup separately; benchmark warmed inference with identical seed.
 warm_rgb=np.full((512,512,3),255,dtype=np.uint8);warm_mask=np.zeros((512,512),dtype=np.float32);warm_mask[200:250,100:300]=1
 _,cold_ms=model.run(warm_rgb,warm_mask);print('Warm-up',cold_ms,flush=True)
 if args.verify_gpu:
  proof=model.profiles();(root/'gpu-kernels.json').write_text(json.dumps(proof,indent=2));print(proof,flush=True);return
 for page in cases:
  if args.only and page['id'] not in args.only.split(','):continue
  identity=page['id'];w,h=page['width'],page['height'];original=np.asarray(Image.open(root/(identity+'.png')).convert('RGB'));mask=np.fromfile(root/(identity+'-mask.raw'),dtype=np.uint8).reshape(h,w);pooled=np.fromfile(root/(identity+'-mask512.raw'),dtype=np.uint8).reshape(512,512);valid=[p for p in page['patches'] if not p.get('declined')]
  record={'id':identity,'language':page['language'],'width':w,'height':h,'regions':len(page['patches']),'safeRegions':len(valid),'maskedPixels':int(mask.sum()),'provider':model.provider,'old':[],'page':[]}
  for run in range(args.runs):
   for strategy in (['page','old'] if run%2==0 else ['old','page']):
    start=time.perf_counter();working=original.copy();times=[]
    if strategy=='page':
     image,holes=fitted(original,mask,page['layout'],pooled);output,ms=model.run(image,holes,whole_page=True);times.append(ms);restored=restore(output,page['layout'],w,h);working[mask!=0]=restored[mask!=0]
    else:
     for patch in valid:
      index=patch['index'];pw,ph=patch['width'],patch['height'];raw=np.fromfile(root/(identity+'-'+str(index)+'-image.raw'),dtype=np.uint8).reshape(ph,pw,4)[:,:,:3];pm=np.fromfile(root/(identity+'-'+str(index)+'-mask.raw'),dtype=np.uint8).reshape(ph,pw);geometry=layout(pw,ph)
      image,holes=fitted(raw,pm,geometry);output,ms=model.run(image,holes);times.append(ms);restored=restore(output,geometry,pw,ph);roi=working[patch['top']:patch['top']+ph,patch['left']:patch['left']+pw];roi[pm!=0]=restored[pm!=0]
    outside=int(np.count_nonzero(np.any(working!=original,axis=2)&(mask==0)));assert outside==0
    metrics={'wallMs':round((time.perf_counter()-start)*1000,2),'inferenceMs':round(sum(times),2),'calls':len(times),'outsideMaskChanges':outside}
    record[strategy].append(metrics)
    if run==0:Image.fromarray(working).save(root/(identity+'-'+strategy+'.png'))
    print(identity,strategy,run,metrics,flush=True)
  Image.fromarray(mask*255).save(root/(identity+'-mask.png'));results.append(record)
  (root/'results.json').write_text(json.dumps({'runtime':ort.__version__,'startupMs':model.startup_ms,'warmupMs':cold_ms,'results':results},indent=2))
 profiles=model.profiles();(root/'profile-summary.json').write_text(json.dumps(profiles,indent=2));print('Profiles',profiles,flush=True)

if __name__=='__main__':main()
