"""Run inside the importer: bounded live search → chapters → first image audit.

Only health metadata is persisted in the project-local discovery cache. Images
stay in RAM. One or two catalogue entries per source are sampled, not every work.
No failure is permanent: registry entries expire and explicit retries are allowed.
"""
import argparse,concurrent.futures,json,sys,time,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import suwayomi_bridge as bridge
from source_parser import PublicHttp
from manga_download import image_extension
from manga_source_health import record,report

MESSAGES={'search':'Поиск источника не отвечает.','chapters':'Источник не отдаёт открытые главы.',
          'image':'Источник не отдаёт изображения страниц.','empty':'Нет открытой главы для проверки.',
          'restricted':'Источник ограничивает доступ к страницам (HTTP 401/403).'}

def private_json(client,path,params=None,timeout=5):
    response=client.session.get(client.root+'/api/v1'+path,params=params,timeout=(2,timeout),allow_redirects=False)
    try:
        if response.status_code!=200:raise ValueError('upstream')
        if len(response.content)>8*1024*1024:raise ValueError('size')
        return response.json()
    finally:response.close()

def inspect_native(source,query):
    from manga_discovery import native_search_source
    from manga_sources import inspect
    deadline=time.monotonic()+18
    rows=native_search_source(source,query)
    phase='chapters'
    for row in rows[:2]:
        http=PublicHttp(timeout=(2,4),deadline=deadline)
        try:
            data=inspect(row['url'],http)
            entries=data.get('episodes',[])
            if not entries:continue
            chapter=inspect(entries[0]['url'],http)
            if not chapter.get('pages'):continue
            phase='image';response=None
            try:
                response,_=http._open(chapter['pages'][0],headers={'Referer':chapter['url']})
                raw=bytearray()
                for chunk in response.iter_content(65536):
                    raw.extend(chunk)
                    if len(raw)>30*1024*1024:raise ValueError('size')
                if image_extension(raw[:32]):return 'working','image',''
            finally:
                if response is not None:response.close()
        except Exception:pass
        finally:http.close()
    return 'unavailable',phase,MESSAGES[phase] if rows else MESSAGES['empty']

def audit(source):
    phase='search';client=bridge.Client();started=time.monotonic()
    try:
        if source['name'] in {'MangaDex','MangaLib','HentaiLib'}:
            return inspect_native(source,{'ru':'Наруто','en':'Naruto','ja':'ナルト','ko':'나루토'}[source['lang']])
        result=private_json(client,f'/source/{source["id"]}/popular/1')
        rows=result.get('mangaList',[])
        if not rows:
            result=private_json(client,f'/source/{source["id"]}/search',{'searchTerm':{'ru':'Наруто','en':'Naruto','ja':'ナルト','ko':'나루토'}[source['lang']],'pageNum':1})
            rows=result.get('mangaList',[])
        if not rows:return 'empty','empty',MESSAGES['empty']
        phase='chapters'
        for row in rows[:2]:
            if time.monotonic()-started>22:break
            try:
                mid=int(row['id'])
                private_json(client,f'/manga/{mid}',{'onlineFetch':'true'},timeout=5)
                entries=private_json(client,f'/manga/{mid}/chapters',{'onlineFetch':'true'},timeout=6)
                if not entries:continue
                # Old chapters are less likely to be advance/paid previews.
                chapter=entries[-1];index=int(chapter['index'])
                details=private_json(client,f'/manga/{mid}/chapter/{index}',timeout=6)
                if not 0<int(details.get('pageCount',0))<=500:continue
                phase='image'
                response=client.session.get(client.root+f'/api/v1/manga/{mid}/chapter/{index}/page/0',params={'updateProgress':'false'},timeout=(2,8),stream=True,allow_redirects=False)
                try:
                    if response.status_code in {401,403}:return 'restricted','image',MESSAGES['restricted']
                    if response.status_code!=200:continue
                    raw=bytearray()
                    for chunk in response.iter_content(65536):
                        raw.extend(chunk)
                        if len(raw)>30*1024*1024:raise ValueError('size')
                    if image_extension(raw[:32]):return 'working','image',''
                finally:response.close()
            except Exception:continue
        return 'unavailable',phase,MESSAGES[phase]
    except Exception:return 'unavailable',phase,MESSAGES[phase]
    finally:client.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=6);parser.add_argument('--retry-failed',action='store_true');args=parser.parse_args()
    sources=[s for s in bridge.sources() if s.get('lang') in {'ru','en','ja','ko'}]
    if args.retry_failed:
        from manga_source_health import states,blocked
        health=states();sources=[s for s in sources if blocked(s['id'],health)]
    # Prioritize reported failures and Russian sources, without omitting others.
    sources.sort(key=lambda s:(s['name']!='Manga Ball',s['lang']!='ru',s['name'],str(s['id'])))
    started=time.monotonic();done=0
    print(json.dumps({'phase':'started','total':len(sources)}),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,min(args.workers,8))) as pool:
        pending={pool.submit(audit,s):s for s in sources}
        for future in concurrent.futures.as_completed(pending):
            source=pending[future]
            try:status,phase,message=future.result()
            except Exception:status,phase,message='unavailable','search',MESSAGES['search']
            record(source['id'],source['name'],source['lang'],status,phase,message);done+=1
            if done%20==0 or done==len(sources):
                r=report();print(json.dumps({'phase':'progress','completed':done,'total':len(sources),'working':r['working'],'unavailable':r['unavailable'],'seconds':round(time.monotonic()-started)}),flush=True)
    r=report();print(json.dumps({k:v for k,v in r.items() if k!='sources'}),flush=True)

if __name__=='__main__':main()
