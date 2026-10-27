#!/usr/bin/env python3
"""Operator-run REAL 1–4 page Gemma benchmark. Requires an installed owner key.

Never prints the key, source images, OCR text or dialogue. No paid fallback.
Use only when the production queue is idle: this CLI has its own quota window.
"""
import argparse,asyncio,json,platform,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from manga_batch.detector import DetectorService
from manga_batch.som import compose
from manga_batch.provider import GemmaBatchTranslator
from manga_batch.quota import QuotaPacer,Deferred
p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--page',action='append',required=True);p.add_argument('--key-file',default='/data/google-api-key');p.add_argument('--out',required=True);a=p.parse_args()
if not 1<=len(a.page)<=4:p.error('Supply one to four --page arguments')
async def main():
 detector=DetectorService(a.model);await asyncio.to_thread(detector.warm);pages=[];started=time.perf_counter()
 for index,name in enumerate(a.page,1):
  image,regions,metrics=await asyncio.to_thread(detector.detect,Path(name).read_bytes(),index)
  try:
   marked,extra=await asyncio.to_thread(compose,image,regions);pages.append({'page':index,'width':image.width,'height':image.height,'regions':regions,'som':marked,'timings':{**metrics,**extra}})
  finally:image.close()
 boxes=sum(len(p['regions']) for p in pages)
 if not 1<=boxes<=65:raise ValueError('Benchmark expects1…65 regions; production orchestrator splits denser pages automatically')
 provider=GemmaBatchTranslator(QuotaPacer(),a.key_file)
 try:rows,usage=await provider.translate(pages)
 except Deferred as e:raise SystemExit('Google quota deferred: '+str(round(e.seconds,2))+'s. Production SSE would keep waiting; this benchmark stops without another call.')
 result={'provenance':'ACTUAL native ONNX + RAM SoM + official Google Gemma API; no client cleanup measured here','machine':platform.machine(),'pages':len(pages),'boxes':boxes,'validatedTranslations':len(rows),'timings':[p['timings'] for p in pages],'usage':usage,'totalMs':round((time.perf_counter()-started)*1000,2)}
 Path(a.out).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
asyncio.run(main())
