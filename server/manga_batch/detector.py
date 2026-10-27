"""Warm direct ONNX detector. No Chromium, OCR, image files or inpainting."""
from __future__ import annotations
import hashlib
import io
import math
from pathlib import Path
import threading
import time
import numpy as np
from PIL import Image, ImageOps

MODEL_SHA256 = '5fe9e4f576e49d4e7e8b0e029d6d3cdc252abd4694113e1cae120e62c931ea79'
Image.MAX_IMAGE_PIXELS = 24_000_000

def area(b): return max(0,b[2]-b[0])*max(0,b[3]-b[1])
def overlap(a,b): return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))

def combine_boxes(detections, width, height, page=1, rtl=False):
    valid=[]
    for raw in detections:
        box=raw['bbox']; score=float(raw['confidence'])
        if len(box)!=4 or not all(math.isfinite(v) for v in [*box,score]):continue
        box=[max(0,min(width,box[0])),max(0,min(height,box[1])),max(0,min(width,box[2])),max(0,min(height,box[3]))]
        if score<.35 or box[2]-box[0]<12 or box[3]-box[1]<12:continue
        valid.append({**raw,'bbox':box,'confidence':score})
    bubbles=[b for b in valid if b['label']==0]
    text=sorted((b for b in valid if b['label'] in (1,2)),key=lambda b:-b['confidence'])
    kept=[]
    for b in text:
        # Duplicate text predictions are suppressed; distinct text blocks in a
        # single balloon remain distinct. Bubble boxes are never extra items.
        if any(overlap(b['bbox'],a['bbox'])/max(1,area(b['bbox'])+area(a['bbox'])-overlap(b['bbox'],a['bbox']))>.8 for a in kept):continue
        kept.append(b)
    kept.sort(key=lambda b:(b['bbox'][1],-b['bbox'][0] if rtl else b['bbox'][0]))
    result=[];groups={}
    for b in kept:
        matches=[(i,a) for i,a in enumerate(bubbles) if overlap(b['bbox'],a['bbox'])/max(1,area(b['bbox']))>.7]
        chosen=min(matches,key=lambda a:area(a[1]['bbox'])) if matches else None
        region={'uid':f'P{page}_B{len(result)+1}','text_bbox':b['bbox'],'bubble_bbox':chosen[1]['bbox'] if chosen else None,'layout_bbox':chosen[1]['bbox'][:] if chosen else b['bbox'][:], 'confidence':round(b['confidence'],4),'detection_class':'text_bubble' if b['label']==1 else 'text_free'}
        if chosen:groups.setdefault(chosen[0],[]).append(region)
        result.append(region)
    # Two texts in one balloon must not both typeset over the whole balloon.
    for siblings in groups.values():
        if len(siblings)<2:continue
        outer=siblings[0]['bubble_bbox']; xs=[(r['text_bbox'][0]+r['text_bbox'][2])/2 for r in siblings];ys=[(r['text_bbox'][1]+r['text_bbox'][3])/2 for r in siblings]
        axis=0 if max(xs)-min(xs)>max(ys)-min(ys) else 1
        ordered=sorted(siblings,key=lambda r:(r['text_bbox'][axis]+r['text_bbox'][axis+2])/2)
        centers=[(r['text_bbox'][axis]+r['text_bbox'][axis+2])/2 for r in ordered]
        for i,r in enumerate(ordered):
            layout=outer[:];layout[axis]=outer[axis] if i==0 else (centers[i-1]+centers[i])/2;layout[axis+2]=outer[axis+2] if i==len(ordered)-1 else (centers[i]+centers[i+1])/2;r['layout_bbox']=layout
    return result

class DetectorService:
    def __init__(self, model_path, *, session_factory=None):
        self.path=Path(model_path);self.lock=threading.Lock();self.session=None;self.factory=session_factory

    def warm(self):
        with self.lock:
            if self.session is not None:return
            with self.path.open('rb') as f:
                if hashlib.file_digest(f,'sha256').hexdigest()!=MODEL_SHA256:raise ValueError('Detector checksum mismatch')
            import onnxruntime as ort
            opts=ort.SessionOptions();opts.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL;opts.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL;opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
            self.session=(self.factory or ort.InferenceSession)(str(self.path),sess_options=opts,providers=['CPUExecutionProvider'])

    def detect(self, data, page=1, rtl=False):
        if len(data)>10*1024*1024:raise ValueError('Page exceeds 10 MiB')
        start=time.perf_counter()
        with Image.open(io.BytesIO(data)) as opened:
            if opened.width*opened.height>24_000_000:raise ValueError('Page exceeds 24 MP')
            image=ImageOps.exif_transpose(opened).convert('RGB')
        w,h=image.size;scale=min(640/w,640/h);rw,rh=round(w*scale),round(h*scale);px,py=(640-rw)//2,(640-rh)//2
        square=Image.new('RGB',(640,640),(114,114,114));square.paste(image.resize((rw,rh),Image.Resampling.BILINEAR),(px,py));tensor=np.asarray(square,dtype=np.float32).transpose(2,0,1)[None]/255
        pre=time.perf_counter();self.warm()
        with self.lock:
            names=[v.name for v in self.session.get_inputs()];out=self.session.run(None,{names[0]:tensor,names[1]:np.array([[640,640]],dtype=np.int64)})
            values=dict(zip([v.name for v in self.session.get_outputs()],out))
        end=time.perf_counter();detections=[]
        for label,box,score in zip(values['labels'].reshape(-1),values['boxes'].reshape(-1,4),values['scores'].reshape(-1)):
            detections.append({'label':int(label),'bbox':[(float(box[0])-px)/scale,(float(box[1])-py)/scale,(float(box[2])-px)/scale,(float(box[3])-py)/scale],'confidence':float(score)})
        regions=combine_boxes(detections,w,h,page,rtl)
        return image,regions,{'preprocessMs':round((pre-start)*1000,2),'inferenceMs':round((end-pre)*1000,2),'detectionMs':round((time.perf_counter()-start)*1000,2)}
