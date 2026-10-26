#!/usr/bin/env python3
"""Oracle-friendly CPU inpaint comparison using known clean plates and masks.
Neural outputs are composited only in the provided mask. Outside-mask errors
are separately measured on raw output to catch unintended artwork changes.
"""
import argparse,hashlib,json,math,platform,resource,time
from pathlib import Path
import cv2,numpy as np,onnxruntime as ort
from PIL import Image,ImageDraw,ImageFont
p=argparse.ArgumentParser();p.add_argument('--models',default='test-output/quality-models');p.add_argument('--output',default='test-output/manga-quality/inpaint');p.add_argument('--label',required=True);p.add_argument('--threads',type=int,default=2);p.add_argument('--runs',type=int,default=2);a=p.parse_args();root=Path(a.output);root.mkdir(parents=True,exist_ok=True);report=root/'results.json'
if report.exists():raise SystemExit('Preserve previous results; choose another --output.')
font_path=next(f for f in ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf','/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf'] if Path(f).exists());font=ImageFont.truetype(font_path,23);samples=[]
for kind in ['white','gradient','screentone','line-art']:
 y,x=np.indices((256,256))
 if kind=='white':gray=np.full((256,256),250,dtype=np.uint8)
 elif kind=='gradient':gray=np.uint8(130+100*x/255)
 elif kind=='screentone':gray=np.where((x%7-3)**2+(y%7-3)**2<3,40,235).astype(np.uint8)
 else:gray=np.where(((x+y)%43<2)|((x-y)%57<2),20,235).astype(np.uint8)
 clean=Image.fromarray(gray).convert('RGB');image=clean.copy();mask=Image.new('L',image.size);d=ImageDraw.Draw(image);m=ImageDraw.Draw(mask)
 for i,text in enumerate(['DO NOT OPEN','THAT DOOR!']):d.text((22,93+i*33),text,font=font,fill='black');m.text((22,93+i*33),text,font=font,fill=255,stroke_width=3)
 image.save(root/(kind+'-source.png'));clean.save(root/(kind+'-clean.png'));mask.save(root/(kind+'-mask.png'));samples.append((kind,np.asarray(image),np.asarray(clean),np.asarray(mask)))
out={'executionLabel':a.label,'machine':platform.machine(),'threads':a.threads,'size':[256,256],'mask':'exact glyph mask plus 3px dilation, not predicted mask','notes':'Synthetic reconstruction stress test. PSNR is not a manga visual-quality score; see output images. MI-GAN internal pipeline resizes to its training resolution.','results':[],'models':{}}
for name in ['planar-fill','telea','navier-stokes','lama','migan']:
 session=None;start=time.perf_counter()
 if name in ['lama','migan']:
  f=Path(a.models)/(name+'.onnx');options=ort.SessionOptions();options.intra_op_num_threads=a.threads;options.inter_op_num_threads=1;session=ort.InferenceSession(str(f),options,providers=['CPUExecutionProvider']);out['models'][name]={'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'loadMs':round((time.perf_counter()-start)*1000)}
 for kind,image,clean,mask in samples:
  for run in range(a.runs):
   start=time.perf_counter();raw=None;error=None
   try:
    if name=='planar-fill':raw=image.copy();raw[mask>0]=np.median(image[mask==0],axis=0).astype(np.uint8)
    elif name in ['telea','navier-stokes']:raw=cv2.inpaint(image,mask,3,cv2.INPAINT_TELEA if name=='telea' else cv2.INPAINT_NS)
    elif name=='lama':
     img=np.ascontiguousarray(image.transpose(2,0,1)[None]).astype(np.float32)/255;msk=(mask>0).astype(np.float32)[None,None];v=session.run(None,{'image':img,'mask':msk})[0];raw=np.clip(v[0].transpose(1,2,0)*255,0,255).astype(np.uint8)
    else:
     img=np.ascontiguousarray(image.transpose(2,0,1)[None]);msk=np.where(mask>0,0,255).astype(np.uint8)[None,None];v=session.run(None,{'image':img,'mask':msk})[0];raw=v[0].transpose(1,2,0)
    result=image.copy();result[mask>0]=raw[mask>0]
    delta=(result.astype(float)-clean.astype(float))[mask>0];mse=float(np.mean(delta**2));outside=float(np.mean(np.abs(raw.astype(float)-image.astype(float))[mask==0]));inside=float(np.mean(np.abs(delta)))
    if run==0:Image.fromarray(result).save(root/(name+'-'+kind+'.png'))
    record={'model':name,'case':kind,'run':run,'ms':round((time.perf_counter()-start)*1000),'maskedPSNRdB':round(10*math.log10(255**2/mse),3) if mse else None,'maskedMAE':round(inside,4),'rawOutsideMaskMAE':round(outside,4),'output':name+'-'+kind+'.png'}
   except Exception as e:record={'model':name,'case':kind,'run':run,'error':str(e)[:400]}
   out['results'].append(record);out['maxRssKiB']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;report.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(record),flush=True)
 del session
