#!/usr/bin/env python3
"""Real Google + reader renderer, synthetic pages; run privately inside importer.

No library import, Drive upload or credential output. Results are separate from
mocked concurrency contracts. Uses the installed owner's existing Google pool.
"""
import argparse,io,json,sqlite3,threading,time,sys
from pathlib import Path
from types import SimpleNamespace
from PIL import Image,ImageDraw,ImageFont

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--label',required=True);parser.add_argument('--pages',type=int,default=6);args=parser.parse_args()
    if not 2<=args.pages<=9:raise SystemExit('Use 2..9 synthetic pages.')
    import api,manga_export_runtime as runtime
    root=Path('/data');db=sqlite3.connect('file:'+str(root/'tasks.sqlite')+'?mode=ro',uri=True)
    row=db.execute("SELECT owner FROM tasks WHERE owner NOT LIKE 'guest:%' AND owner NOT LIKE 'share:%' ORDER BY updated DESC LIMIT 1").fetchone();db.close()
    if not row:raise SystemExit('No installed owner.')
    # Only signing material is needed by the existing runtime. Do not initialize
    # a second TaskStore (its startup recovery would alter live queue state).
    api.store=SimpleNamespace(key=(root/'service.key').read_bytes())
    pages=[];font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',30)
    for n in range(args.pages):
        image=Image.new('RGB',(900,1300),'white');draw=ImageDraw.Draw(image)
        for k,lines in enumerate([['We must leave before sunrise.','Bring the map, not the sword.'],['I counted three bridges.','The northern gate is closed.'],['Wait here for ten minutes.','I will bring our friend back.'],['Do not lose this letter.','We promised to meet tomorrow.']]):
            x=40 if k%2==0 else 470;y=60+(k//2)*620
            draw.rounded_rectangle((x,y,x+380,y+480),radius=35,outline='black',width=3)
            for j,line in enumerate(lines):
                words=line.split();draw.multiline_text((x+20,y+70+j*180),' '.join(words[:3])+'\n'+' '.join(words[3:]),font=font,fill='black',spacing=12)
        out=io.BytesIO();image.save(out,format='PNG');pages.append(out.getvalue())
    started=time.monotonic();saved={};calls=[];lock=threading.Lock();flight=0;peak=0;original=runtime.requests.request
    def request(method,url,**kw):
        nonlocal flight,peak
        if not url.endswith('/reader/google/generate'):return original(method,url,**kw)
        t=time.monotonic()
        with lock:flight+=1;peak=max(peak,flight)
        try:
            response=original(method,url,**kw)
            try:usage=response.json().get('usageMetadata',{})
            except ValueError:usage={}
            calls.append({'startSeconds':round(t-started,3),'seconds':round(time.monotonic()-t,3),'status':response.status_code,'inputTokens':usage.get('promptTokenCount'),'requestBytes':len(json.dumps(kw.get('json',{})))})
            return response
        finally:
            with lock:flight-=1
    runtime.requests.request=request
    class Budget:
        def check(self):
            if time.monotonic()-started>180:raise RuntimeError('Benchmark deadline reached.')
    def save(index,data):
        with Image.open(io.BytesIO(data)) as image:image.verify()
        saved[index]={'bytes':len(data),'seconds':round(time.monotonic()-started,3)}
    options={'directModel':'gemini-3.5-flash-lite','language':'English','direction':'ltr','directInput':'blocks','directDetector':'en-fast','directBatchPages':2,'inpaint':'fast','font':'auto'}
    result={'label':args.label,'kind':'real-google-and-canvas-synthetic-pages','pages':args.pages}
    try:runtime.translate_pages(SimpleNamespace(owner=row[0]),pages,options,[],save,lambda value:None,Budget())
    except Exception as error:result['error']=type(error).__name__+': '+str(error)[:180]
    result.update(seconds=round(time.monotonic()-started,3),saved=saved,gatewayCalls=calls,peakGatewayRequests=peak)
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
