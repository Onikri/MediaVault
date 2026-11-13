"""Private, authenticated Suwayomi adapter; browser URLs are identifiers, never proxy targets.
Protocol: Suwayomi Server v2.4 REST v1 (MPL-2.0 upstream, no vendored code).
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit,urljoin,parse_qs
import json,os,re,threading,time,sqlite3
import requests
from source_parser import SourceAccessError,SourceError,public_url
from manga_source_tags import from_api

PREFIX='/__manga/suwayomi/'
LANGUAGES={'ru','uk','en','ja','ko'}
_cache={};_lock=threading.RLock();_install_lock=threading.Lock();_origins={}

class BridgeError(SourceError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code=code


def bridge_error(status, text, image=False):
    text=str(text or '').casefold()
    for terms, code, message in (
        (('no space left on device','disk quota exceeded'),'storage','На сервере источников заполнен кэш страниц. Требуется очистка кэша; повторное открытие главы не поможет.'),
        (('cef is disabled','webview.getfactory'),'webview','Для этого расширения на сервере отключён браузер WebView. Требуется восстановить среду Suwayomi.'),
        (('no chapters found','no chapter found'),'no-chapters','Источник отвечает, но не опубликовал открытые главы этого тайтла на выбранном языке.'),
        (('cloudflare bypass currently disabled','bypass site protection','necessary cookies'),'challenge','Источник требует браузерную проверку.'),
        (('запретил доступ из вашей сети','not available from your network'),'network-restricted','Источник запретил доступ из сети сервера.'),
        (('sslhandshakeexception','certificate verify failed','unable to find valid certification path'),'tls','Не удалось проверить TLS-сертификат источника.'),
        (('missingfieldexception','serializationexception'),'format','Расширение не распознало изменившийся ответ источника.'),
        (('your country is not supported','only available in japan','only be used from japan','not available in your region'),'region','Источник ограничил доступ из региона сервера.'),
        (('timed out','timeout'),'timeout','Источник не успел ответить.'),
        (('name or service not known','failure in name resolution','unknownhostexception'),'dns','Домен источника не разрешается.'),
        (('enter a valid cubari url','enter a deviantart gallery url'),'link-required','Расширение открывает прямые ссылки и не ищет по названию.'),
        (('username or password cannot be empty','requires a login'),'login','Источник требует вход.'),
    ):
        if any(term in text for term in terms):return BridgeError(code,message)
    # Extensions often wrap the origin's status in their own HTTP 500.
    origin = re.search(r'\bhttp(?:\s+error)?[:\s]+([45]\d{2})\b', text)
    if status >= 500 and origin:
        status = int(origin[1])
    code={400:'bad-request',401:'login',403:'restricted',404:'missing',408:'timeout',429:'rate-limit',504:'timeout'}.get(status,'upstream')
    return BridgeError(code,f'Ошибка источника (HTTP {status}). Не удалось получить '+('страницу главы.' if image else 'данные читалки.'))

# Geo walls that answer the VM with 403 (Comici/CloudFront publishers say
# "アクセスを制限しております"). Matched on the origin's own home page only.
GEO_WALL=('アクセスを制限','一部の通信環境','block access from your country','not available in your country',
          'only available in japan','only be used from japan','your country is not supported','not available in your region')
ORIGIN_TTL=6*3600

def origin_block(base_url,fetch=None,clock=time.monotonic):
    """Explain an extension's bare "Server Error" by asking its public home page once.

    Suwayomi turns an uncaught HttpException into an empty HTTP 500, so the
    origin's real answer (often a regional 403) is lost. One GET per host per
    six hours, no cookies, no retries, bounded body; returns a BridgeError or None.
    """
    try:url=public_url(str(base_url or '').rstrip('/')+'/',allow_api=False)
    except SourceError:return None
    from manga_network_routes import configuration,routed
    routes=configuration();host=urlsplit(url).hostname;now=clock();cache_key=(host,routes.get('revision','direct'))
    with _lock:hit=_origins.get(cache_key)
    if hit and hit[0]>now:return hit[1]
    result=None;response=None
    try:
        options={'proxies':{'http':routes['httpProxy'],'https':routes['httpProxy']}} if routed(url,routes) else {}
        get=fetch or (lambda u:requests.get(u,timeout=(3,6),allow_redirects=False,stream=True,**options,
            headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36','Accept-Language':'ja,en;q=0.8'}))
        response=get(url);raw=b''
        for block in response.iter_content(4096):
            raw+=block[:16384-len(raw)]
            if len(raw)>=16384:break
        text=raw.decode('utf-8',errors='replace').casefold()
        if response.status_code in {401,403,451} and any(term in text for term in GEO_WALL):
            result=BridgeError('region','Источник открыт только из своей страны (обычно Япония) и закрыт для сервера.')
        elif response.status_code>=400:
            result=bridge_error(response.status_code,text)
    except requests.RequestException:result=None
    finally:
        if response is not None:response.close()
    with _lock:_origins[cache_key]=(now+ORIGIN_TTL,result)
    return result

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
    def get(self,path,params=None,timeout=12,image=False,body=None):
        # Paths are constructed only by this module, never taken from external URLs.
        if not re.fullmatch(r'/[a-zA-Z0-9_./-]+',path) or '..' in path:raise SourceError('Некорректный запрос к каталогу.')
        # The only write-shaped call is the stateless filtered search; it never
        # changes the source's shared filter or preference state.
        if body is not None and not re.fullmatch(r'/source/\d{1,20}/quick-search',path):raise SourceError('Некорректный запрос к каталогу.')
        response=None
        try:
            request=self.session.get if body is None else partial(self.session.post,json=body)
            response=request(self.root+'/api/v1'+path,params=params,timeout=(3,timeout),allow_redirects=False,stream=True)
            if path.startswith(('/extension/install/','/extension/update/')) and response.status_code in {200,201,204}:return {'installed':True}
            if response.status_code!=200:
                # Classify bounded upstream text; never expose its HTML, stack,
                # account settings or arbitrary response content to the browser.
                raw=b''
                for block in response.iter_content(4096):
                    raw+=block[:4096-len(raw)]
                    if len(raw)>=4096:break
                text=raw.decode('utf-8',errors='replace').casefold()
                error=bridge_error(response.status_code,text,image)
                if error.code=='bad-request' and re.fullmatch(r'/source/\d+/(?:search|quick-search)',path):
                    error=BridgeError('query','Источник не принял поисковый запрос (HTTP 400).')
                raise error
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
        except requests.Timeout:raise BridgeError('timeout','Каталог источников не успел ответить.') from None
        except requests.RequestException:raise BridgeError('network','Нет связи с каталогом источников.') from None
        except (ValueError,KeyError):raise BridgeError('format','Каталог источников вернул данные в неизвестном формате.') from None
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

def indexed_reader(value):
    """Recover a failed extension through the same indexed public reader URL."""
    ids=parse_reference(value)
    if not ids or ids[1] is not None:return None
    path=Path(os.getenv('DATA_DIR','/data'))/'manga-discovery.sqlite'
    if not path.is_file():return None
    try:
        with closing(sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True,timeout=1)) as db:
            rows=db.execute('SELECT metadata FROM titles WHERE id LIKE ? LIMIT 8',('%:'+str(ids[0]),)).fetchall()
        for row in rows:
            item=json.loads(row[0]);canonical=item.get('sourceUrl','');url=urlsplit(canonical)
            if item.get('url')==value and url.scheme=='https' and url.hostname=='ru.novelcool.com' and re.fullmatch(r'/novel/[^/]+\.html',url.path):return canonical
    except (sqlite3.Error,ValueError,OSError,TypeError):pass
    return None

def inspect_indexed_reader(value):
    canonical=indexed_reader(value)
    if canonical:
        from manga_sources import inspect as native_inspect
        return native_inspect(canonical)
    return None
def status():
    if not configured():return {'configured':False,'ready':False,'message':'Дополнительные источники пока не подключены.'}
    try:
        active=sources();available=extensions()
        return {'configured':True,'ready':True,'availableExtensions':len(available),'installedExtensions':sum(bool(x.get('installed')) for x in available),'sources':[{'id':str(s['id']),'name':s['name'],'language':s['lang'],'adult':bool(s.get('isNsfw'))} for s in active if s.get('lang') in LANGUAGES]}
    except SourceError:return {'configured':True,'ready':False,'message':'Каталог источников запускается или временно недоступен.'}

def extension_catalog(language='all',query=''):
    query=query.casefold().strip()[:80]
    result=[{'package':x['pkgName'],'name':x['name'],'language':x['lang'],'adult':bool(x.get('isNsfw')),'installed':bool(x.get('installed')),'hasUpdate':bool(x.get('hasUpdate')),'obsolete':bool(x.get('obsolete'))} for x in extensions() if x['lang'] in {*LANGUAGES,'all'} and (language=='all' or x['lang'] in {language,'all'}) and (not query or query in x['name'].casefold())]
    result.sort(key=lambda x:(not x['installed'],x['language'],x['name'].casefold(),x['package']))
    return {'extensions':result,'total':len(extensions()),'matching':len(result)}

def install(package):
    if not re.fullmatch(r'eu\.kanade\.tachiyomi\.extension\.[A-Za-z0-9_.]{1,140}',package):raise SourceError('Выбери источник из каталога.')
    with _install_lock:
        found=next((x for x in extensions() if x['pkgName']==package and not x.get('obsolete')),None)
        if not found:raise SourceError('Это расширение отсутствует в доверенном каталоге.')
        if not found.get('installed') or found.get('hasUpdate'):
            client=Client()
            try:client.get('/extension/'+('update' if found.get('installed') else 'install')+'/'+package,timeout=90)
            finally:client.close()
        with _lock:_cache.clear()
    return {'installed':True,'name':found['name']}

def mangaball_languages(client,manga):
    """Its title search is multilingual even when this language has no chapters.

    Public API shape verified against MangaBall and Keiyoushi's MangaBall adapter.
    Keep bridge identities stable; do not switch the selected provider or work.
    """
    key='mangaball-languages:'+str(manga);now=time.monotonic()
    with _lock:hit=_cache.get(key)
    if hit and hit[0]>now:return hit[1]
    saved=client.get(f'/manga/{manga}',{'onlineFetch':'false'},timeout=4)
    parsed=urlsplit(saved.get('realUrl',''))
    match=re.fullmatch(r'/title-detail/([a-f0-9]{24})',parsed.path)
    if parsed.scheme!='https' or parsed.hostname!='mangaball.com' or not match:return None
    from source_parser import PublicHttp
    def validate(url):
        if url!='https://mangaball.com/api/v1/chapter/chapter-listing-by-title-id':raise SourceError('Неизвестный адрес каталога Manga Ball.')
        return public_url(url,allow_api=True)
    http=PublicHttp(validate=validate,timeout=(3,5),deadline=time.monotonic()+8)
    try:
        text,_,_=http.document('https://mangaball.com/api/v1/chapter/chapter-listing-by-title-id',method='POST',headers={'Content-Type':'application/json'},data=json.dumps({'title_id':match[1]}).encode())
        rows=json.loads(text).get('data')
        if not isinstance(rows,list):raise SourceError('Manga Ball изменил формат списка глав.')
        languages={str(row.get('lang') or row.get('language') or '').lower() for row in rows if str(row.get('title_id'))==match[1] and row.get('status','published')=='published'}
        languages={ {'jp':'ja','kr':'ko'}.get(lang,lang) for lang in languages }
        with _lock:_cache[key]=(now+300,languages)
        return languages
    finally:http.close()

def inspect(value):
    ids=parse_reference(value)
    if not ids:raise SourceError('Некорректная ссылка на главу.')
    manga,chapter,page=ids
    if page is not None:raise SourceError('Открой главу, а не отдельную страницу.')
    client=Client()
    native_access_error = None
    try:
        # LibGroup can fail before chapter/page calls while initializing its
        # Android WebView. Resolve its already indexed identity first and use
        # that same site's public reader, including old saved bridge links.
        try:
            saved=client.get(f'/manga/{manga}',{'onlineFetch':'false'},timeout=8)
            saved_source=saved.get('source') or client.get('/source/'+str(saved['sourceId']))
            if native:=native_reader_url(client,saved,saved_source,manga,chapter):
                from manga_sources import inspect as native_inspect
                return native_inspect(native)
        except SourceError as error:
            if isinstance(error, SourceAccessError):
                native_access_error = error
            # The normal path retains bounded retries and indexed NovelCool
            # recovery for providers without a public catalogue adapter.
            if 'native' in locals() and native and saved_source.get('name')!='MangaDex':raise
        try:data=client.get(f'/manga/{manga}',{'onlineFetch':'true' if chapter is None else 'false'},timeout=25)
        except SourceError as error:
            recovered=inspect_indexed_reader(value)
            if recovered is not None:return recovered
            if native_access_error and isinstance(error, BridgeError) and error.code=='upstream':
                raise native_access_error from None
            raise
        source=data.get('source') or client.get('/source/'+str(data['sourceId']))
        lang=source.get('lang','')
        if lang not in LANGUAGES:raise SourceError('Этот источник пока не поддерживает выбранный язык чтения.')
        if chapter is None and source.get('name')=='Manga Ball':
            languages=mangaball_languages(client,manga)
            if languages is not None and lang not in languages:raise SourceError('Manga Ball не опубликовал главы этого тайтла на выбранном языке. Доступные языки: '+(', '.join(sorted(languages)).upper() or 'нет')+'.')
        try:chapters=client.get(f'/manga/{manga}/chapters',{'onlineFetch':'true' if chapter is None else 'false'},timeout=30)
        except SourceError as error:
            recovered=inspect_indexed_reader(value)
            if recovered is not None:return recovered
            if native_access_error and isinstance(error, BridgeError) and error.code=='upstream':
                raise native_access_error from None
            # MangaDex can fail in its extension while its public API still
            # answers. Resolve the SAME title UUID and language, never another
            # title/provider. Native chapter URLs keep reading/download working.
            canonical=data.get('realUrl') or urljoin(source.get('baseUrl',''),data.get('url',''))
            parsed=urlsplit(canonical)
            if chapter is None and parsed.scheme=='https' and parsed.hostname=='mangadex.org' and re.fullmatch(r'/(?:title|manga)/[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}(?:/[^/]*)?/?',parsed.path):
                from manga_sources import inspect as native_inspect
                identity=parsed.path.split('/')[2]
                try:return native_inspect('https://mangadex.org/title/'+identity+'?lang='+lang)
                except SourceError:pass
            raise
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
        from manga_discovery import public_aliases
        try:canonical=public_url(data.get('realUrl') or urljoin(source.get('baseUrl',''),data.get('url','')),resolve_dns=False)
        except SourceError:canonical=''
        return {'sourceId':str(source['id']),'sourceUrl':canonical,**from_api(data),'provider':'suwayomi:'+str(source['id']),'providerName':source['name'],'title':data['title'],'aliases':public_aliases(data),'url':value,'kind':'manga','language':lang,'episodes':episodes,'pages':pages,'seasons':[{'number':n,'name':'Том '+str(n)} for n in sorted({e['season'] for e in episodes})],'translations':sorted({e['translator'] for e in episodes if e['translator']}),'cover':'','description':data.get('description') or '','dubs':[],'releases':[],'truncated':len(chapters)>1500,**({'format':'manhwa','readingMode':'scroll'} if lang=='ko' else {})}
    finally:client.close()

def native_reader_url(client,data,source,manga,chapter=None):
    """Map only this cached source/title/chapter, never substitute a search hit."""
    from manga_catalog_adapters import UUID,LIB_SITES
    canonical=data.get('realUrl') or urljoin(source.get('baseUrl',''),data.get('url',''))
    parsed=urlsplit(canonical);lang=source.get('lang')
    # Several installed extensions can search but fail at chapter/page retrieval.
    # Use this SAME site's existing native reader adapter, including saved IDs.
    from manga_sources import site_for
    native=site_for(canonical)
    if (native and native.family in {'pill','katana','poisk','hub','chan','buff','novelcool','naver','sen','mangaraw','webtoons'}
        and lang in native.languages and parsed.scheme=='https' and site_for(source.get('baseUrl',''))==native):
        if chapter is None:return canonical
        rows=client.get(f'/manga/{manga}/chapters',{'onlineFetch':'false'},timeout=8)
        row=next((r for r in rows if r.get('index')==chapter),None)
        if row:
            target=row.get('realUrl') or urljoin(source.get('baseUrl',''),row.get('url',''))
            if urlsplit(target).scheme=='https' and site_for(target)==native:return target
        raise SourceError('Не удалось сопоставить сохранённую главу с исходной читалкой.')
    lib=next((row for row in LIB_SITES.values() if parsed.hostname in {urlsplit(row[2]).hostname,row[0]+'.org'} and source.get('name')==row[1]),None)
    dex=source.get('name')=='MangaDex' and parsed.hostname=='mangadex.org'
    if parsed.scheme!='https' or lang not in LANGUAGES:return None
    if not(lib or dex):
        from manga_sources import site_for
        site=site_for(canonical)
        if not site or site.family not in {'pill','katana','poisk','hub','chan','buff'} or site_for(source.get('baseUrl',''))!=site:return None
        if chapter is None:return canonical
        rows=client.get(f'/manga/{manga}/chapters',{'onlineFetch':'false'},timeout=8)
        row=next((r for r in rows if r.get('index')==chapter),None)
        if row:
            target=row.get('realUrl') or urljoin(site.root,row.get('url',''))
            if site_for(target)==site:return target
        raise SourceError('Не удалось сопоставить главу с исходной читалкой.')
    if dex:
        match=re.fullmatch(r'/(?:title|manga)/('+UUID+r')(?:/[^/]*)?/?',parsed.path)
        if not match:return None
        title_url='https://mangadex.org/title/'+match[1]+'?lang='+lang
    else:
        # Suwayomi stores LibGroup's /slug separately from its public /ru URL.
        match=re.fullmatch(r'/(?:ru/(?:manga/)?)?([\w-]{1,250})/?',parsed.path)
        if not match:return None
        slug=match[1];title_url=lib[2]+'/ru/'+slug
    if chapter is None:return title_url
    rows=client.get(f'/manga/{manga}/chapters',{'onlineFetch':'false'},timeout=8)
    row=next((r for r in rows if r.get('index')==chapter),None)
    if row is None:raise SourceError('Сохранённая глава отсутствует в этом источнике. Обнови список глав.')
    original=urlsplit(str(row.get('url') or ''))
    if dex:
        match=re.fullmatch(r'/chapter/('+UUID+r')/?',original.path)
        if match:return 'https://mangadex.org/chapter/'+match[1]+'?lang='+lang
    else:
        args=parse_qs(original.query);volume=args.get('volume',[''])[0];number=args.get('number',[''])[0];bid=args.get('branch_id',[''])[0]
        if original.path in {'/'+slug+'/chapter','/api/manga/'+slug+'/chapter'} and volume.isdigit() and re.fullmatch(r'\d{1,4}(?:\.\d{1,3})?',number):
            return lib[2]+'/ru/'+slug+'/read/v'+volume+'/c'+number+('?bid='+bid if bid.isdigit() else '')
        if original.path.startswith('/ru/'+slug+'/read/') and (not original.netloc or original.hostname==urlsplit(lib[2]).hostname):return lib[2]+original.path+('?'+original.query if original.query else '')
    raise SourceError('Не удалось сопоставить сохранённую главу с её исходной ссылкой.')

def page_image(value):
    ids=parse_reference(value)
    if not ids or ids[1] is None or ids[2] is None:raise SourceError('Некорректная ссылка на страницу.')
    manga,chapter,page=ids;client=Client()
    try:
        try:return client.get(f'/manga/{manga}/chapter/{chapter}/page/{page}',{'updateProgress':'false'},timeout=25,image=True)
        except SourceError:
            saved=client.get(f'/manga/{manga}',{'onlineFetch':'false'},timeout=8)
            source=saved.get('source') or client.get('/source/'+str(saved['sourceId']))
            if source.get('name')=='Manga Ball':
                from mangaball_reader import page as reserve_page
                return reserve_page(client,saved,source,manga,chapter,page)
            target=native_reader_url(client,saved,source,manga,chapter)
            if not target:raise
            from manga_sources import inspect as native_inspect
            from manga_download import image_extension
            from source_parser import PublicHttp
            key='native-pages:'+target;now=time.monotonic()
            with _lock:hit=_cache.get(key)
            if hit and hit[0]>now:pages=hit[1]
            else:
                pages=native_inspect(target)['pages']
                with _lock:_cache[key]=(now+300,pages)
            if not 0<=page<len(pages):raise SourceError('Страница отсутствует в исходной главе.')
            http=PublicHttp(timeout=(3,20));response=None
            try:
                response,_=http._open(pages[page],headers={'Referer':target});raw=bytearray()
                for block in response.iter_content(65536):
                    raw.extend(block)
                    if len(raw)>30*1024*1024:raise SourceError('Страница превышает допустимый размер.')
                extension=image_extension(raw[:32])
                if not extension:raise SourceError('Источник вернул заглушку вместо страницы.')
                return bytes(raw),'image/'+('jpeg' if extension=='jpg' else extension)
            finally:
                if response is not None:response.close()
                http.close()
    finally:client.close()

def search(title,language='all',format='all',offset=0,limit=8):
    from title_identity import aliases,match_title
    if not configured():return {'results':[],'providers':[]}
    try:active=[s for s in sources() if s['lang'] in ({'ru'} if language=='auto' else LANGUAGES if language=='all' else {language})]
    except SourceError as e:return {'results':[],'providers':[{'provider':'suwayomi','name':'Дополнительные источники','status':'unavailable','message':str(e)}]}
    # A stable, explicit window replaces the old silent first-32-source cut-off.
    # The UI can continue until every installed source in this language is tried.
    from manga_source_health import states,blocked
    health=states();active=sorted((s for s in active if not blocked(s['id'],health)),key=lambda s:(s['lang'],s['name'].casefold(),str(s['id'])))
    total=len(active);offset=max(0,min(int(offset),total));limit=max(1,min(int(limit),16))
    deadline=time.monotonic()+12
    def work(source):
        provider='suwayomi:'+str(source['id']);result=[]
        if deadline-time.monotonic()<1:return {'provider':provider,'name':source['name'],'status':'pending','results':[],'attempted':False}
        client=Client()
        try:
            queries=aliases(title)
            lang=source['lang'];pattern={'ja':r'[\u3040-\u30ff\u3400-\u9fff]','ko':r'[\uac00-\ud7af]','ru':r'[а-яё]','uk':r'[а-яіїєґ]','en':r'[a-z]'}[lang]
            queries=sorted(queries,key=lambda q:not bool(re.search(pattern,q,re.I)))
            for query in queries[:2]:
                remaining=deadline-time.monotonic()
                if remaining<1:break
                rows=client.get('/source/'+str(source['id'])+'/search',{'searchTerm':query,'pageNum':1},timeout=min(4,remaining)).get('mangaList',[])
                for row in rows[:40]:
                    candidate={'title':row['title'],'aliases':[row['title']],'kind':'manga'};accepted,evidence=match_title(title,candidate)
                    try:canonical=public_url(row.get('realUrl') or urljoin(source.get('baseUrl',''),row.get('url','')),resolve_dns=False)
                    except SourceError:canonical=''
                    if accepted:
                        if source.get('name')=='Manga Ball':
                            languages=mangaball_languages(client,row['id'])
                            if languages is not None and lang not in languages:continue
                        result.append({**candidate,'url':reference(row['id']),'sourceUrl':canonical, 'provider':provider,'providerName':source['name'],'language':lang,'format':title.get('format') or ('manhwa' if lang=='ko' else 'manga'),'matchEvidence':evidence,'cover':''})
                if result:break
            return {'provider':provider,'name':source['name'],'status':'ok' if result else 'empty','message':'','results':result,'attempted':True}
        except (SourceError,ValueError,TypeError,KeyError,AttributeError):return {'provider':provider,'name':source['name'],'status':'unavailable','message':'Источник временно недоступен или изменил формат ответа.','results':[],'attempted':True}
        finally:client.close()
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(work,active[offset:offset+limit]))
    attempted=[r for r in rows if r['attempted']];next_offset=offset+len(attempted)
    return {'results':[v for row in attempted for v in row['results']],
            'providers':[{k:v for k,v in row.items() if k not in {'results','attempted'}} for row in attempted],
            'window':{'offset':offset,'checked':len(attempted),'nextOffset':next_offset,'totalSources':total,'hasMore':next_offset<total}}

# Filter groups that carry a work's subject. Status, year, rating and sort
# controls are not tags and are never offered to the owner's vocabulary.
TAXONOMY_GROUP=re.compile(r'жанр|тэг|тег|категор|тематик|genre|tag|categor|theme|demographic',re.I)
GENRE_GROUP=re.compile(r'жанр|genre',re.I)

def filter_vocabulary(client,source_id):
    """The extension's own genre/tag options with their stateless filter path."""
    data=client.get('/source/'+str(source_id)+'/filters',{'reset':'true'},timeout=25)
    if not isinstance(data,list):raise BridgeError('format','Каталог источников вернул данные в неизвестном формате.')
    terms=[]
    for position,item in enumerate(data[:60]):
        node=item.get('filter') if isinstance(item,dict) else None
        if not isinstance(node,dict) or item.get('type')!='Group' or not TAXONOMY_GROUP.search(str(node.get('name') or '')):continue
        category='genre' if GENRE_GROUP.search(str(node.get('name'))) else 'tag'
        for child,option in enumerate((node.get('state') or [])[:600]):
            kind=option.get('type') if isinstance(option,dict) else None;label=str(((option or {}).get('filter') or {}).get('name') or '').strip()
            if kind not in {'CheckBox','TriState'} or not label or len(label)>120:continue
            terms.append({'label':label,'category':category,'sourceId':{'position':position,'child':child,'kind':kind}})
    return terms

def filtered_page(client,source_id,term,page):
    """One page of an extension's catalogue narrowed to a single genre/tag."""
    path=term.get('sourceId') if isinstance(term,dict) else None
    if not isinstance(path,dict) or path.get('kind') not in {'CheckBox','TriState'} or not all(isinstance(path.get(k),int) and 0<=path[k]<=600 for k in ('position','child')):
        raise SourceError('Некорректный фильтр источника.')
    change={'position':path['child'],'state':'true' if path['kind']=='CheckBox' else '1'}
    return client.get('/source/'+str(source_id)+'/quick-search',{'pageNum':page},timeout=30,body={'searchTerm':'','filter':[{'position':path['position'],'state':json.dumps(change)}]})
