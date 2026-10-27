#!/usr/bin/env python3
"""Opt-in real public-reader smoke test; output contains no images or credentials."""
import argparse,concurrent.futures,hashlib,json,sys,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
from manga_sources import inspect,site_for
from manga_raw_adapters import search
from manga_download import image_extension
from source_parser import PublicHttp

CASES=[('mangaraw','https://mangaraw.co.uk/manga/1424'),('senmanga','https://raw.senmanga.com/manga/dandadan'),('naver-webtoon','https://comic.naver.com/webtoon/list?titleId=769209'),('toonkor','https://toonkor7.org/화산귀환')]
def run(case):
    name,url=case;started=time.monotonic();row={'provider':name,'url':url,'checkedAt':int(time.time())}
    http=PublicHttp(timeout=(3,9),deadline=time.monotonic()+60)
    try:
        title=inspect(url,http);row.update(title=title['title'],language=title['language'],format=title.get('format'),chapters=len(title['episodes']),truncated=title['truncated'])
        if not title['episodes']:raise ValueError('No published chapter URLs')
        chapter=inspect(title['episodes'][0]['url'],http);row.update(chapterUrl=chapter['url'],pages=len(chapter['pages']))
        if not chapter['pages']:raise ValueError('No actual page image URLs')
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'page';http.download(chapter['pages'][0],file,headers={'Referer':chapter['url']},maximum=5*1024**2)
            image=file.read_bytes();extension=image_extension(image[:32])
            if not extension:raise ValueError('Reader image is not a recognized image')
            row.update(imageType=extension,imageBytes=len(image),imageSHA256=hashlib.sha256(image).hexdigest())
        row['status']='ok'
    except Exception as error:row.update(status='unavailable',error=type(error).__name__+': '+str(error)[:500])
    finally:http.close()
    row['totalMs']=round((time.monotonic()-started)*1000);return row

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='test-output/manga-expansion/live-reader-report.json');args=p.parse_args()
    rows=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(run,c) for c in CASES]
        for future in concurrent.futures.as_completed(futures):
            row=future.result();rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
            Path(args.output).write_text(json.dumps({'actualNetwork':True,'runtime':'production Python parser, CaaS x86_64; not an Oracle deployment test','results':rows},ensure_ascii=False,indent=2)+'\n')
