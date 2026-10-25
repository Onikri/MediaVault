"""Server-side Russian dossiers and real per-episode frames, including old files."""
import base64
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import re
import secrets
import subprocess
import threading
import time
from urllib.parse import urljoin

from metadata_catalog import metadata
from vault_drive import CHUNK_SIZE,open_chunk,group_section

def russian(value):
    from bs4 import BeautifulSoup
    text=BeautifulSoup(str(value or ''),'html.parser').get_text(' ',strip=True)
    text=re.sub(r'\[/?[a-z_]+[^\]]*\]','',text,flags=re.I)
    return text if re.search('[а-яё]',text,re.I) else ''

def image(value):
    if not value or re.search(r'(?:/|_)(?:missing|404|no[_-]?image)(?:[./_-]|$)',value,re.I):return ''
    value=urljoin('https://shikimori.io',value)
    return value if value.startswith('https://') else ''

def load_profile(identity,kind):
    details=metadata('shikimori',kind=kind,identity=str(identity))
    names=['roles','related']+(['screenshots'] if kind=='anime' else [])
    def fetch(part):
        try:return metadata('shikimori',kind=kind,identity=str(identity),part=part),False
        except Exception:return [],True
    with ThreadPoolExecutor(max_workers=3) as pool:extra=list(pool.map(fetch,names))
    roles,related=extra[0][0],extra[1][0];screenshots=extra[2][0] if len(extra)>2 else []
    roles=sorted(roles,key=lambda role:0 if 'Main' in role.get('roles',[]) else 1)
    formats={'tv':'Аниме-сериал','movie':'Фильм','ova':'OVA','ona':'ONA','special':'Спецвыпуск','manga':'Манга','novel':'Ранобэ','light_novel':'Ранобэ'}
    profile={'version':4,'source':'shikimori','sourceId':str(identity),'sourceURL':f"https://shikimori.io/{'animes' if kind=='anime' else 'mangas'}/{identity}",'language':'ru',
             'title':russian(details.get('russian')),'description':russian(details.get('description_html') or details.get('description')),
             'cover':image((details.get('image') or {}).get('original')),'format':formats.get(details.get('kind'),'Произведение'),
             'status':{'released':'Завершён','ongoing':'Выходит','anons':'Анонсирован'}.get(details.get('status'),''),
             'startDate':details.get('aired_on'),'endDate':details.get('released_on'),'year':int(details['aired_on'][:4]) if details.get('aired_on') else None,
             'episodes':details.get('episodes'),'episodesAired':details.get('episodes_aired'),'duration':details.get('duration'),'score':float(details.get('score') or 0) or None,
             'rating':{'g':'0+','pg':'6+','pg_13':'13+','r':'17+','r_plus':'18+','rx':'18+'}.get(details.get('rating'),''),
             'origin':{'manga':'Манга','light_novel':'Ранобэ','original':'Оригинальное произведение','game':'Игра','novel':'Роман'}.get(details.get('source'),''),
             'genres':[g['russian'] for g in details.get('genres',[]) if g.get('russian')],
             'studios':[g['name'] for g in details.get('studios',[]) if g.get('name')],
             'directors':[russian(r['person'].get('russian')) for r in roles if r.get('person') and 'Director' in r.get('roles',[])],
             'characters':[{'id':str(r['character']['id']),'name':russian(r['character'].get('russian')) or 'Персонаж','role':', '.join(filter(None,(russian(v) for v in r.get('roles_russian',[])))) or ('Главный герой' if 'Main' in r.get('roles',[]) else 'Второстепенный персонаж'),
                            'image':image((r['character'].get('image') or {}).get('original')),'description':''} for r in roles if r.get('character')][:18],
             'screenshots':[image(s.get('original')) for s in screenshots if s.get('original')][:10],'related':[],
             'partial':any(error for _,error in extra),'retryAfter':int((time.time()+120)*1000),'fetchedAt':datetime.now(timezone.utc).isoformat()}
    for relation in related:
        value=relation.get('anime') or relation.get('manga')
        if not value:continue
        profile['related'].append({'id':str(value['id']),'kind':'anime' if relation.get('anime') else 'ranobe' if value.get('kind') in {'novel','light_novel'} else 'manga',
                                   'title':russian(value.get('russian')) or 'Связанное произведение','cover':image((value.get('image') or {}).get('original')),
                                   'format':formats.get(value.get('kind'),'Произведение'),'relation':russian(relation.get('relation_russian')) or 'Связано'})
    def character_detail(value):
        if 'главн' not in value['role'].lower():return value
        try:
            detail=metadata('shikimori',kind='character',identity=value['id'])
            return {**value,'description':russian(detail.get('description_html') or detail.get('description')),
                    'actors':[russian(a.get('russian')) for a in detail.get('seyu',[]) if russian(a.get('russian'))],
                    'voiceActors':[{'id':str(a['id']),'name':russian(a.get('russian')),'image':image((a.get('image') or {}).get('original')),'role':'Сэйю'} for a in detail.get('seyu',[]) if a.get('id') and russian(a.get('russian'))]}
        except Exception:return value
    with ThreadPoolExecutor(max_workers=2) as pool:profile['characters']=list(pool.map(character_detail,profile['characters']))
    profile['partial']=profile['partial'] or not profile['description']
    if profile['screenshots']:profile['background']=profile['screenshots'][0]
    from title_extras import staff_from_roles,trailers_from_details
    profile['staff']=staff_from_roles(roles);profile['trailers']=trailers_from_details(details)
    try:
        from poster_assets import posters
        art=posters([str(identity),*[r['id'] for r in profile['related'] if r['kind']==kind]],kind)
        if art.get(str(identity)):profile['cover']=art[str(identity)]['cover']
        for related in profile['related']:
            if art.get(related['id']):related.update(art[related['id']])
    except Exception:pass
    return profile

def preview_existing(vault,item):
    """ffmpeg seeks through a loopback-only decrypted range stream: no full copy."""
    token=secrets.token_urlsafe(32);cache=OrderedDict();cache_lock=threading.Lock();key=vault._key;stopped=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_HEAD(self):self.respond(False)
        def do_GET(self):self.respond(True)
        def respond(self,body):
            if self.path!='/'+token or stopped.is_set():self.send_error(404);return
            size=item['size'];match=re.fullmatch(r'bytes=(\d+)-(\d*)',self.headers.get('Range',''))
            start=int(match[1]) if match else 0;end=min(size-1,int(match[2]) if match and match[2] else size-1)
            if start>=size or end<start:self.send_error(416);return
            self.send_response(206 if match else 200);self.send_header('Content-Type',item.get('mime','video/mp4'));self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
            if match:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            if not body:return
            try:
                for index in range(start//CHUNK_SIZE,end//CHUNK_SIZE+1):
                    if stopped.is_set():return
                    with cache_lock:
                        if index not in cache:
                            chunk=item['chunks'][index];cache[index]=open_chunk(vault.drive.download(chunk['fileId']),key,item['id'],index,chunk['iv'])
                            while len(cache)>4:cache.popitem(last=False)
                        raw=cache[index]
                    offset=index*CHUNK_SIZE;self.wfile.write(raw[max(0,start-offset):min(len(raw),end-offset+1)])
            except (BrokenPipeError,ConnectionResetError,OSError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    source=f'http://127.0.0.1:{server.server_port}/{token}'
    try:
        result=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',source],capture_output=True,timeout=45,check=False)
        duration=float(json.loads(result.stdout)['format']['duration'])
        result=subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',str(round(duration*.35,2)),'-i',source,'-frames:v','1','-vf',"scale='min(1280,iw)':-2",'-q:v','4','-threads','1','-f','image2pipe','-vcodec','mjpeg','-'],capture_output=True,timeout=45,check=False)
        return result.stdout if result.returncode==0 and result.stdout.startswith(b'\xff\xd8\xff') and len(result.stdout)<=500000 else None
    except (subprocess.SubprocessError,KeyError,ValueError):return None
    finally:stopped.set();server.shutdown();server.server_close();cache.clear()

def enrich_profile(vault,group,section):
    title_id=section+':'+group['id'];previous=vault.catalog.get('titleProfiles',{}).get(title_id,{})
    info=group.get('metadata') or {};identity=group.get('metadataId') or info.get('ids',{}).get('mal')
    profile=previous.copy()
    if identity and (not previous.get('sourceId') or previous.get('version',0)<4 or previous.get('partial') and previous.get('retryAfter',0)<time.time()*1000):
        try:profile.update(load_profile(identity,'manga' if section in {'manga','ranobe'} else 'anime'))
        except Exception:profile.update({'partial':True,'retryAfter':int((time.time()+120)*1000)})
    profile.setdefault('version',4);profile.setdefault('title',group['name']);profile.setdefault('language','ru')
    own=[i['previewArtwork'] for i in vault.catalog['items'] if i.get('collectionId')==group['id'] and i.get('previewArtwork')][:10]
    assets={**profile.get('artwork',{}),**{'drive:'+a['id']:a for a in own}}
    own_urls=['drive:'+a['id'] for a in own]
    if profile==previous and all(url in previous.get('screenshots',[]) for url in own_urls) and previous.get('artworkRetryAfter',0)>time.time()*1000:return previous
    profile['artwork']=assets;published=[u for u in [profile.get('background'),*profile.get('screenshots',[])] if u and u.startswith('https://') and u!=profile.get('cover')];profile['backgrounds']=list(dict.fromkeys(published+own_urls))[:10]
    profile['screenshots']=list(dict.fromkeys(own_urls+profile.get('screenshots',[])))[:14]
    urls=list(dict.fromkeys([profile.get('cover'),profile.get('background'),*profile['screenshots'],*[c.get('image') for c in profile.get('characters',[])],*[r.get('cover') for r in profile.get('related',[])],*[r.get('image') for r in profile.get('staff',[])],*[a.get('image') for c in profile.get('characters',[]) for a in c.get('voiceActors',[])],*[t.get('image') for t in profile.get('trailers',[])]]))
    from artwork import fetch_image
    def fetch(url):
        if not url or url in assets or not url.startswith('https://'):return None
        try:
            data,mime=fetch_image(url)
            return (url,data,mime) if len(data)<=2*1024*1024 else None
        except Exception:return None
    images=[]
    if previous.get('version',0)<4 or previous.get('artworkRetryAfter',0)<time.time()*1000:
        with ThreadPoolExecutor(max_workers=4) as executor:images=[value for value in executor.map(fetch,[u for u in urls if u and u not in assets][:48]) if value]
    downloaded={value[0] for value in images}
    profile['missingArtwork']=sum(1 for url in urls if url and url.startswith('https://') and url not in assets and url not in downloaded)
    profile['artworkRetryAfter']=int((time.time()+120)*1000)
    return vault.save_title_profile(title_id,profile,images)

def enrichment_step(vault,*,cursor=0,title_id=None,progress=lambda _:None):
    items=[i for i in vault.catalog['items'] if i.get('category')=='video' and (not title_id or title_id.endswith(':'+str(i.get('collectionId',''))))]
    if cursor>=len(items):return {'cursor':cursor,'remaining':False,'total':len(items),'saved':0,'failed':0,'skipped':0}
    item=items[cursor];progress({'phase':'artwork','title':'Оформление библиотеки','current':cursor+1,'total':len(items)})
    failed=False
    if not item.get('previewArtwork'):
        frame=preview_existing(vault,item)
        if frame:vault.save_preview(item['id'],frame)
        else:failed=True
    group=next((g for g in vault.catalog.get('storage',{}).get('collections',[]) if g['id']==item.get('collectionId')),None)
    if group:enrich_profile(vault,group,group_section(group,vault.catalog))
    return {'cursor':cursor+1,'remaining':cursor+1<len(items),'total':len(items),'saved':0 if failed else 1,'failed':1 if failed else 0,'skipped':0}
