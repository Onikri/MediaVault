#!/usr/bin/env python3
"""Actual new direct-preparation paths against existing labelled EN fixtures.
No Google key/calls. Native ONNX CPU is labelled separately from browser WASM.
"""
import argparse,asyncio,base64,hashlib,json,os,platform,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
from lmt_runtime import LmtRuntime
from metrics import match_boxes

async def main(args):
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    os.environ.update(LMT_ONNX_RUNTIME='native',LMT_CHROMIUM_NO_SANDBOX='1',CHROMIUM_PATH=args.chromium)
    runtime=LmtRuntime('dist/lmt',out/'browser');runtime.allow_downloads=True
    report={'actualInference':True,'machine':platform.machine(),'runtime':'production direct preparation + native ONNX CPU, 2 threads','googleInference':False,'cases':'existing manually specified synthetic EN fixtures, not a real-page quality claim','results':[]}
    if args.resume and (out/'report.json').exists():report=json.loads((out/'report.json').read_text())
    try:
        await runtime._start(False)
        for folder in args.weights:
            for file in Path(folder).glob('*.onnx'):
                sha=hashlib.sha256(file.read_bytes()).hexdigest()
                if sha in runtime.native.allowed:runtime.native.known[sha]=file
        root=Path(args.cases);cases=json.loads((root/'cases.json').read_text())
        for model in args.detectors.split(','):
            for case in [c for c in cases if c['id'] in args.include.split(',')]:
                if args.resume and any(r['detector']==model and r['case']==case['id'] and 'error' not in r for r in report['results']):continue
                data=(root/case['file']).read_bytes();start=time.monotonic();row={'case':case['id'],'detector':model,'imageSha256':hashlib.sha256(data).hexdigest()}
                try:
                    result=await asyncio.wait_for(runtime.page.evaluate('''async p=>{
                      const bytes=Uint8Array.from(atob(p.image),c=>c.charCodeAt(0)).buffer;
                      const out=await window.mangaTranslate(bytes,{operation:'gemma-prepare',mode:'gemma',language:'English',allowDownloads:true,fastDirect:true,directDetector:p.model,directInput:'annotated',direction:'rtl',pageIndex:0},()=>{});
                      delete out.image;return out;
                    }''',{'image':base64.b64encode(data).decode(),'model':model}),120)
                    row.update(result);row['metrics']=match_boxes([r['box'] for r in case['regions']],[r['bbox'] for r in result['regions']])
                except Exception as error:row['error']=type(error).__name__+': '+str(error)[-1500:]
                row['wallMs']=round((time.monotonic()-start)*1000);report['results'].append(row)
                (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
                print(model,case['id'],row.get('metrics',row.get('error')),row['wallMs'],flush=True)
    finally:await runtime.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--detectors',default='rtdetr,yolo26n-manga,ppocrv6-det');p.add_argument('--resume',action='store_true');p.add_argument('--weights',nargs='+',default=['test-output/quality-models','test-output/candidate-models']);p.add_argument('--cases',default='test-output/manga-quality/cases');p.add_argument('--include',default='clean,adjacent,over-art,low-contrast');p.add_argument('--output',default='test-output/direct-detector-benchmark');p.add_argument('--chromium',default='/usr/bin/chromium');asyncio.run(main(p.parse_args()))
