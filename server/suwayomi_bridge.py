"""Private, authenticated Suwayomi adapter; browser URLs are identifiers, never proxy targets.
Protocol: Suwayomi Server v2.4 REST v1 (MPL-2.0 upstream, no vendored code).
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit,urljoin
import json,os,re,threading,time
import requests
from source_parser import SourceError,public_url

PREFIX='/__manga/suwayomi/'
LANGUAGES={'ru','en','ja','ko'}
_cache={};_lock=threading.RLock();_install_lock=threading.Lock()

def configured():return bool(os.getenv('SUWAYOMI_URL') and os.getenv('SUWAYOMI_AUTH_FILE') and os.getenv('PUBLIC_URL','').startswith('https://'))
def reference(manga,chapter=None,page=None):
    root=os.getenv('PUBLIC_URL','').rstrip('/')
    if not configured():raise SourceError('Каталог дополнительных источников ещё не подключён.')
    value=f'{root}{PREFIX}m/{int(manga)}'
    if chapter is not None:value+=f'/c/{int(chapter)}'
    if page is not None:value+=f'/p/{int(page)}'
    return value

def parse_reference(value):
    try:
        root=urlsplit(os.getenv('PUBLIC_URL',''));url=urlsplit(value)
        if not configured() or (url.scheme,url.netloc)!=(root.scheme,root.netloc) or url.query or url.fragment or url.username:return None
        match=re.fullmatch(re.escape(root.path.rstrip('/')+PREFIX)+r'm/([1-9]\d{0,9})(?:/c/([1-9]\d{0,6})(?:/p/(\d{1,4}))?)?',url.path)
        return tuple(int(v) if v is not None else None for v in match.groups()) if match else None
    except (ValueError,TypeError):return None

class Client:
    def __init__(self):
        if not configured():raise SourceError('Suwayomi ещё не подключён к серверу.')
        self.root=os.environ['SUWAYOMI_URL'].rstrip('/')
        uri=urlsplit(self.root)
        if uri.scheme!='http' or uri.hostname not in {'suwayomi','127.0.0.1','localhost'} or uri.path or uri.query or uri.fragment or uri.username:raise SourceError('Некорректный внутренний адрес Suwayomi.')
        try:auth=json.loads(Path(os.environ['SUWAYOMI_AUTH_FILE']).read_text())
        except (OSError,ValueError):raise SourceError('Учётные данные каталога источников недоступны.') from None
        self.session=requests.Session();self.session.trust_env=False # fixed private Docker endpoint only
        self.session.auth=(auth['username'],auth['password'])
    def close(self):self.session.close()
    def get(self,path,params=None,timeout=12,image=False):
        # Paths are constructed only by this module, never taken from external URLs.
        if not re.fullmatch(r'/[a-zA-Z0-9_./-]+',path) or '..' in path:raise SourceError('Некорректный запрос к каталогу.')
        response=None
        try:
            response=self.session.get(self.root+'/api/v1'+path,params=params,timeout=(3,timeout),allow_redirects=False,stream=True)
            if path.startswith('/extension/install/') and response.status_code in {200,201}:return {'installed':True}
            if response.status_code!=200:raise SourceError('Источник временно недоступен или требует настройки в каталоге.')
            chunks=[];size=0;limit=30*1024*1024 if image else 8*1024*1024
            for block in response.iter_content(65536):
                size+=len(block)
                if size>limit:raise SourceError('Ответ источника превышает допустимый размер.')
                chunks.append(block)
            raw=b''.join(chunks)
            if image:
                from manga_download import image_extension
                extension=image_extension(raw[:32])
                if not extension:raise SourceError('Источник вернул заглушку вместо страницы.')
                return raw,'image/'+('jpeg' if extension=='jpg' else extension)
            return json.loads(raw)
        except (requests.RequestException,ValueError,KeyError):raise SourceError('Каталог источников не ответил. Повтори запрос позже.') from None
        finally:
            if response is not None:response.close()

def cached(name,path,ttl):
    now=time.monotonic()
    with _lock:hit=_cache.get(name)
    if hit and hit[0]>now:return hit[1]
    client=Client()
    try:value=client.get(path,timeout=40)
    finally:client.close()
    with _lock:_cache[name]=(now+ttl,value)
    return value

def sources():return [s for s in cached('sources','/source/list',30) if str(s.get('id'))!='0']
def extensions():return cached('extensions','/extension/list',120)
def status():
    if not configured():return {'configured':False,'ready':False,'message':'Дополнительные источники пока не подключены.'}
    try:
        active=sources();available=extensions()
        return {'configured':True,'ready':True,'availableExtensions':len(available),'installedExtensions':sum(bool(x.get('installed')) for x in available),'sources':[{'id':str(s['id']),'name':s['name'],'language':s['lang'],'adult':bool(s.get('isNsfw'))} for s in active]}
    except SourceError:return {'configured':True,'ready':False,'message':'Каталог источников запускается или временно недоступен.'}

def extension_catalog(language='all',query=''):
    query=query.casefold().strip()[:80]
    result=[{'package':x['pkgName'],'name':x['name'],'language':x['lang'],'adult':bool(x.get('isNsfw')),'installed':bool(x.get('installed')),'obsolete':bool(x.get('obsolete'))} for x in extensions() if x['lang'] in {*LANGUAGES,'all'} and (language=='all' or x['lang'] in {language,'all'}) and (not query or query in x['name'].casefold())]
    result.sort(key=lambda x:(not x['installed'],x['language'],x['name'].casefold(),x['package']))
    return {'extensions':result,'total':len(extensions()),'matching':len(result)}

def install(package):
    if not re.fullmatch(r'eu\.kanade\.tachiyomi\.extension\.[a-z0-9_.]{1,140}',package):raise SourceError('Выбери источник из каталога.')
    with _install_lock:
        found=next((x for x in extensions() if x['pkgName']==package and not x.get('obsolete')),None)
        if not found:raise SourceError('Это расширение отсутствует в доверенном каталоге.')
        if not found.get('installed'):
            client=Client()
            try:client.get('/extension/install/'+package,timeout=90)
            finally:client.close()
        with _lock:_cache.clear()
    return {'installed':True,'name':found['name']}

def inspect(value):
    ids=parse_reference(value)
    if not ids:raise SourceError('Некорректная ссылка на главу.')
    manga,chapter,page=ids
    if page is not None:raise SourceError('Открой главу, а не отдельную страницу.')
    client=Client()
    try:
        data=client.get(f'/manga/{manga}',{'onlineFetch':'true' if chapter is None else 'false'},timeout=25)
        source=data.get('source') or client.get('/source/'+str(data['sourceId']))
        lang=source.get('lang','')
        if lang not in {'ru','en','ja','ko'}:raise SourceError('Этот источник пока не поддерживает выбранный язык чтения.')
        chapters=client.get(f'/manga/{manga}/chapters',{'onlineFetch':'true' if chapter is None else 'false'},timeout=30)
        episodes=[]
        for row in chapters[:1500]:
            number=row.get('chapterNumber');index=row.get('index')
            if not isinstance(number,(int,float)) or not 0<=number<=9999 or not isinstance(index,int) or index<1:continue
            volume=re.search(r'(?:Том|Vol\.?|Volume)\s*(\d+)',row.get('name',''),re.I)
            episodes.append({'number':number,'season':int(volume[1]) if volume else 1,'url':reference(manga,index),'title':row.get('name') or 'Глава '+str(number),'language':lang,'translator':row.get('scanlator') or ''})
        pages=[]
        if chapter is not None:
            if not any(row.get('index')==chapter for row in chapters):raise SourceError('Глава отсутствует в этом источнике.')
            details=client.get(f'/manga/{manga}/chapter/{chapter}',timeout=30);count=details.get('pageCount',0)
            if not isinstance(count,int) or not 0<count<=500:raise SourceError('В открытой главе не найдены страницы или превышен лимит 500 страниц.')
            pages=[reference(manga,chapter,i) for i in range(count)]
            episodes=[e for e in episodes if e['url']==value]
        episodes.sort(key=lambda e:(e['season'],e['number'],e['translator']))
        return {'provider':'suwayomi:'+str(source['id']),'providerName':source['name'],'title':data['title'],'aliases':[data['title']],'url':value,'kind':'manga','language':lang,'episodes':episodes,'pages':pages,'seasons':[{'number':n,'name':'Том '+str(n)} for n in sorted({e['season'] for e in episodes})],'translations':sorted({e['translator'] for e in episodes if e['translator']}),'cover':'','description':data.get('description') or '','dubs':[],'releases':[],'truncated':len(chapters)>1500,**({'format':'manhwa','readingMode':'scroll'} if lang=='ko' else {})}
    finally:client.close()

def page_image(value):
    ids=parse_reference(value)
    if not ids or ids[1] is None or ids[2] is None:raise SourceError('Некорректная ссылка на страницу.')
    manga,chapter,page=ids;client=Client()
    try:return client.get(f'/manga/{manga}/chapter/{chapter}/page/{page}',{'updateProgress':'false'},timeout=25,image=True)
    finally:client.close()

def search(title,language='all',format='all',offset=0,limit=8):
    from title_identity import aliases,match_title
    if not configured():return {'results':[],'providers':[]}
    try:active=[s for s in sources() if s['lang'] in ({'ru'} if language=='auto' else {'ru','en','ja','ko'} if language=='all' else {language})]
    except SourceError as e:return {'results':[],'providers':[{'provider':'suwayomi','name':'Дополнительные источники','status':'unavailable','message':str(e)}]}
    # A stable, explicit window replaces the old silent first-32-source cut-off.
    # The UI can continue until every installed source in this language is tried.
    active=sorted(active,key=lambda s:(s['lang'],s['name'].casefold(),str(s['id'])))
    total=len(active);offset=max(0,min(int(offset),total));limit=max(1,min(int(limit),16))
    deadline=time.monotonic()+12
    def work(source):
        provider='suwayomi:'+str(source['id']);result=[]
        if deadline-time.monotonic()<1:return {'provider':provider,'name':source['name'],'status':'pending','results':[],'attempted':False}
        client=Client()
        try:
            queries=aliases(title)
            lang=source['lang'];pattern={'ja':r'[\u3040-\u30ff\u3400-\u9fff]','ko':r'[\uac00-\ud7af]','ru':r'[а-яё]','en':r'[a-z]'}[lang]
            queries=sorted(queries,key=lambda q:not bool(re.search(pattern,q,re.I)))
            for query in queries[:2]:
                remaining=deadline-time.monotonic()
                if remaining<1:break
                rows=client.get('/source/'+str(source['id'])+'/search',{'searchTerm':query,'pageNum':1},timeout=min(4,remaining)).get('mangaList',[])
                for row in rows[:40]:
                    candidate={'title':row['title'],'aliases':[row['title']],'kind':'manga'};accepted,evidence=match_title(title,candidate)
                    try:canonical=public_url(row.get('realUrl') or urljoin(source.get('baseUrl',''),row.get('url','')),resolve_dns=False)
                    except SourceError:canonical=''
                    if accepted:result.append({**candidate,'url':reference(row['id']),'sourceUrl':canonical, 'provider':provider,'providerName':source['name'],'language':lang,'format':title.get('format') or ('manhwa' if lang=='ko' else 'manga'),'matchEvidence':evidence,'cover':''})
                if result:break
            return {'provider':provider,'name':source['name'],'status':'ok' if result else 'empty','message':'','results':result,'attempted':True}
        except (SourceError,ValueError,TypeError,KeyError,AttributeError):return {'provider':provider,'name':source['name'],'status':'unavailable','message':'Источник временно недоступен или изменил формат ответа.','results':[],'attempted':True}
        finally:client.close()
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(work,active[offset:offset+limit]))
    attempted=[r for r in rows if r['attempted']];next_offset=offset+len(attempted)
    return {'results':[v for row in attempted for v in row['results']],
            'providers':[{k:v for k,v in row.items() if k not in {'results','attempted'}} for row in attempted],
            'window':{'offset':offset,'checked':len(attempted),'nextOffset':next_offset,'totalSources':total,'hasMore':next_offset<total}}
