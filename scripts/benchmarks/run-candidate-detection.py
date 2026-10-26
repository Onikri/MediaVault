#!/usr/bin/env python3
"""Use the production JS runners + actual native ONNX on existing labelled pages.
No synthetic inference outputs, no downloaded page images are redistributed.
"""
import argparse,asyncio,base64,hashlib,json,os,platform,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
from lmt_runtime import LmtRuntime
from metrics import match_boxes,cer

async def main(args):
    root=Path(args.output);root.mkdir(exist_ok=True,parents=True)
    runtime=LmtRuntime(args.assets,root/'browser')
    runtime.allow_downloads=True
    os.environ.update(LMT_ONNX_RUNTIME='native',CHROMIUM_PATH=args.chromium,LMT_CHROMIUM_NO_SANDBOX='1')
    report={'actualInference':True,'machine':platform.machine(),'label':args.label,'runtime':'production JS + native ONNX CPU, 2 threads','results':[]}
    dest=root/'report.json'
    def save():dest.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    try:
        await runtime._start(False)
        for file in Path(args.weights).glob('*.onnx'):
            with file.open('rb') as source:sha=hashlib.file_digest(source,'sha256').hexdigest()
            if sha in runtime.native.allowed:runtime.native.known[sha]=file
        for case_dir in args.cases:
            directory=Path(case_dir);cases=json.loads((directory/'cases.json').read_text())
            for case in cases:
                raw=(directory/case['file']).read_bytes();image=base64.b64encode(raw).decode()
                for model in ['yolo26n-manga','ppocrv6-det']:
                    record={'case':case['id'],'model':model,'imageSHA256':hashlib.sha256(raw).hexdigest()};start=time.monotonic()
                    try:
                        result=await runtime.page.evaluate("async p=>window.mangaDetect(Uint8Array.from(atob(p.image),c=>c.charCodeAt(0)).buffer,{detector:p.model,language:p.language,panelDetector:p.model==='yolo26n-manga'?'yolo26n-manga':'none'})",{'image':image,'model':model,'language':case.get('language','English')})
                        record.update(result);record['metrics']=match_boxes([r['box'] for r in case['regions']],[[b[k] for k in ('x1','y1','x2','y2')] for b in result['boxes']])
                        if case.get('partialAnnotations'):
                            record['metrics'].update(fp=None,precision=None,f1=None,partialAnnotations=True)
                    except Exception as e:record['error']=str(e)[-1000:]
                    record['ms']=round((time.monotonic()-start)*1000);report['results'].append(record);save();print(case['id'],model,record.get('metrics',record.get('error')),flush=True)
                if case.get('language')=='Japanese':
                    boxes=[dict(zip(('x1','y1','x2','y2'),r['box'])) for r in case['regions']];start=time.monotonic();record={'case':case['id'],'model':'ppocrv6-manga-v0.2','stage':'ocr','references':[r['text'] for r in case['regions']]}
                    try:
                        result=await runtime.page.evaluate("async p=>window.mangaPpOcr(Uint8Array.from(atob(p.image),c=>c.charCodeAt(0)).buffer,p.boxes)",{'image':image,'boxes':boxes})
                        record.update(result);record['cer']=sum(cer(r['text'],h['text']) for r,h in zip(case['regions'],result['results']))/len(boxes)
                    except Exception as e:record['error']=str(e)[-1000:]
                    record['ms']=round((time.monotonic()-start)*1000);report['results'].append(record);save();print(record,flush=True)
    finally:await runtime.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--assets',default='dist/lmt');p.add_argument('--weights',required=True);p.add_argument('--cases',nargs='+',required=True);p.add_argument('--output',required=True);p.add_argument('--label',required=True);p.add_argument('--chromium',default='/usr/bin/chromium');asyncio.run(main(p.parse_args()))
