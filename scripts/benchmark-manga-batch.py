#!/usr/bin/env python3
"""Actual native ONNX + SoM timings, never a mocked cloud translation benchmark."""
import argparse,json,platform,statistics,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from manga_batch.detector import DetectorService,MODEL_SHA256
from manga_batch.som import compose
p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--page',required=True);p.add_argument('--runs',type=int,default=6);p.add_argument('--out',required=True);a=p.parse_args()
d=DetectorService(a.model);start=time.perf_counter();d.warm();load=(time.perf_counter()-start)*1000;data=Path(a.page).read_bytes();rows=[]
for n in range(a.runs+1):
 image,regions,timings=d.detect(data)
 try:
  marked,som=compose(image,regions)
  if n:rows.append({**timings,**som,'regions':len(regions)})
 finally:image.close()
report={'provenance':'ACTUAL native ORT detection and RAM-only Pillow/WebP, no Google API call','platform':platform.platform(),'machine':platform.machine(),'modelSha256':MODEL_SHA256,'modelBytes':Path(a.model).stat().st_size,'sessionLoadMs':round(load,2),'sample':Path(a.page).name,'runs':rows,'medianDetectionMs':statistics.median(r['detectionMs'] for r in rows),'medianSomMs':statistics.median(r['somMs'] for r in rows)}
Path(a.out).write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='runs'},indent=2))
