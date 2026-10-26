# SPDX-License-Identifier: AGPL-3.0-or-later
"""One page/process: heavy weights are released before OCR/translation starts.

MAGI detection only uses safetensors and Transformers primitives. No HF remote
Python is executed, and OCR/character-clustering weights are never instantiated.
"""
from pathlib import Path
import json
import sys
import time
import resource

def suppress_duplicates(boxes, threshold=.5):
    out=[]
    for b in sorted(boxes,key=lambda b:-b['confidence']):
        area=(b['x2']-b['x1'])*(b['y2']-b['y1'])
        if area<=0:continue
        duplicate=False
        for a in out:
            inter=max(0,min(a['x2'],b['x2'])-max(a['x1'],b['x1']))*max(0,min(a['y2'],b['y2'])-max(a['y1'],b['y1']))
            union=area+(a['x2']-a['x1'])*(a['y2']-a['y1'])-inter
            if inter/max(1,union)>threshold:duplicate=True;break
        if not duplicate:out.append(b)
    return out

def magi(image, root):
    import torch
    import numpy as np
    from safetensors import safe_open
    from transformers import ConditionalDetrConfig, ConditionalDetrModel, ConditionalDetrImageProcessor
    from transformers.models.conditional_detr.modeling_conditional_detr import ConditionalDetrMLPPredictionHead, inverse_sigmoid
    torch.set_num_threads(2)
    config=json.loads((root/'config.json').read_text())
    dc=ConditionalDetrConfig(**config['detection_model_config'])
    dc.use_pretrained_backbone=False
    model=ConditionalDetrModel(dc).eval()
    head=ConditionalDetrMLPPredictionHead(dc.d_model,dc.d_model,4,3).eval()
    classifier=torch.nn.Linear(dc.d_model,dc.num_labels).eval()
    with safe_open(str(root/'model.safetensors'),framework='pt',device='cpu') as weights:
        # Strict load: no random untrained replacement heads.
        for module,prefix in [(model,'detection_transformer.'),(head,'bbox_predictor.'),(classifier,'class_labels_classifier.')]:
            module.load_state_dict({k[len(prefix):]:weights.get_tensor(k) for k in weights.keys() if k.startswith(prefix)},strict=True)
    processor=ConditionalDetrImageProcessor.from_dict(config['detection_image_preprocessing_config'])
    with torch.inference_mode():
        output=model(**processor([np.asarray(image)],return_tensors='pt'),return_dict=True)
        objects=output.last_hidden_state[:,:-5]
        scores,labels=classifier(objects).max(-1);scores=scores.sigmoid()[0]
        boxes=head(objects);boxes[...,:2]+=inverse_sigmoid(output.reference_points[:-5]).transpose(0,1)
        boxes=boxes.sigmoid()[0];labels=labels[0]
    text=[];panels=[];w,h=image.size
    for box,label,score in zip(boxes.tolist(),labels.tolist(),scores.tolist()):
        if label not in (1,2) or score<(.25 if label==1 else .2):continue
        cx,cy,bw,bh=box;b={'x1':max(0,(cx-bw/2)*w),'y1':max(0,(cy-bh/2)*h),'x2':min(w,(cx+bw/2)*w),'y2':min(h,(cy+bh/2)*h),'confidence':score}
        if b['x2']-b['x1']>=3 and b['y2']-b['y1']>=3:(text if label==1 else panels).append(b)
    return {'text':suppress_duplicates(text),'panels':suppress_duplicates(panels),'profile':'MAGI detection-only · safetensors'}

def yolo_panels(image, root):
    from ultralytics import YOLO
    import torch
    torch.set_num_threads(2)
    detector=YOLO(str(root/'best.pt'),task='detect')
    if set(detector.names.values())-{'Comic Panel','comic panel','panel','Panel'}:
        raise ValueError('Unexpected YOLOv12 classes: '+str(detector.names))
    result=detector.predict(image,imgsz=640,conf=.25,device='cpu',verbose=False)[0]
    return {'text':[],'panels':[{'x1':float(b[0]),'y1':float(b[1]),'x2':float(b[2]),'y2':float(b[3]),'confidence':float(c)} for b,c in zip(result.boxes.xyxy.tolist(),result.boxes.conf.tolist())],'profile':'YOLOv12x · panels only'}

def main():
    from PIL import Image
    Image.MAX_IMAGE_PIXELS=24_000_000
    model,source,destination=sys.argv[1:]
    image=Image.open(source).convert('RGB');started=time.perf_counter()
    root=Path('/models')
    result=magi(image,root/'magi') if model=='magi' else yolo_panels(image,root/'yolov12') if model=='yolov12-panels' else None
    if result is None:raise ValueError('Unsupported detector')
    result.update(ms=round((time.perf_counter()-started)*1000),maxRssKiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    Path(destination).write_text(json.dumps(result))

if __name__=='__main__':main()
