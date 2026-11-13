"""One metadata page per call; cursors use upstream pagination, never chapters."""
import json,re
from urllib.parse import urlsplit,urljoin,urlencode
from bs4 import BeautifulSoup
import httpx,requests
from content_source_routes import LIB,HTML
from content_sources import checked_get,permitted,html_terms,lib_terms,lib_titles,lib_metadata
from manga_source_tags import from_api,from_html,unique
from source_parser import SourceError

def source_provider(spec):
    if spec.get('source',{}).get('id'):return 'suwayomi:'+str(spec['source']['id'])
    if spec.get('site') in {1,2,4}:return {1:'mangalib',2:'slashlib',4:'hentailib'}[spec['site']]
    return {'hentaichan.cc':'hentaichan-cc','hentaichan.live':'hentaichan','h-chan.me':'hentaichan','manga-chan.me':'mangachan','hmanga.su':'hmanga','remanga.org':'remanga'}.get(spec['domain'],spec['domain'])

def base_sources(installed):
    from manga_source_coverage import SOURCES
    from manga_tag_policy import alias_domains
    jobs=[];seen=set()
    for domain,name,integration,*_ in SOURCES:
        if integration=='closed':jobs.append({'type':'unsupported','domain':domain,'name':name,'reason':'Сайт закрыт'});continue
        if domain in LIB:
            site,referer=LIB[domain];jobs.append({'type':'lib','domain':domain,'name':name,'site':site,'referer':referer});continue
        if domain=='remanga.org':
            # The HTML front is CAPTCHA-gated; the public JSON catalogue is not.
            jobs.append({'type':'remanga','domain':domain,'name':name});continue
        hosts=set(alias_domains(domain));matches=[s for s in installed if urlsplit(s.get('baseUrl','')).hostname in hosts]
        if not matches:
            matches=[s for s in installed if s.get('name','').casefold()==name.casefold() or (name=='AllHentai' and s.get('name')=='AllHentai')]
        # These extensions discard collapsed catalogue tags, and some return an
        # empty popular list even while the public catalogue is available.
        if domain in {'hentaichan.live','manga-chan.me','yaoi-chan.me'}:
            url,allowed=HTML[domain]
            jobs.append({'type':'html','domain':domain,'name':name,'url':url,'hosts':sorted(allowed),
                         **({'source':matches[0]} if matches else {})})
        elif domain=='h-chan.me':
            jobs.append({'type':'mirror','domain':domain,'name':name,'primary':'hentaichan.live'})
        elif domain=='henchan.pro':
            # This requested address currently serves a parked domain, not the
            # HenChan extension's different .live catalogue. Audit it separately.
            url,allowed=HTML[domain];jobs.append({'type':'html','domain':domain,'name':name,'url':url,'hosts':sorted(allowed)})
        elif matches:
            for source in matches:
                sid=str(source['id'])
                if sid in seen:continue
                seen.add(sid);jobs.append({'type':'bridge','domain':domain,'name':name+' · '+source.get('lang',''),
                    'source':{key:source.get(key) for key in ('id','name','lang','baseUrl','isNsfw')}})
        elif domain in HTML:
            url,allowed=HTML[domain];jobs.append({'type':'html','domain':domain,'name':name,'url':url,'hosts':sorted(allowed)})
        else:jobs.append({'type':'unsupported','domain':domain,'name':name,'reason':'Нет доступного каталога или установленного адаптера'})
    for kind in ('anime','manga','ranobe'):jobs.append({'type':'anilist','kind':kind,'domain':'anilist.co','name':{'anime':'Аниме','manga':'Манга','ranobe':'Ранобэ'}[kind]+' · AniList'})
    for kind in ('movie','tv'):jobs.append({'type':'kinobox','kind':kind,'domain':'fbphdplay.top','name':('Фильмы' if kind=='movie' else 'Сериалы')+' · Kinobox'})
    jobs.append({'type':'books','kind':'book','domain':'openlibrary.org','name':'Книги · Open Library'})
    return jobs

def headers(spec):
    result={'Site-id':str(spec['site']),'Referer':spec['referer'],'Accept':'application/json','User-Agent':'MediaVault-Catalogue/1.0'}
    if spec['type']=='lib-detail':
        from catalogue_lib_auth import token
        if value:=token(spec['site']):result['Authorization']='Bearer '+value
    return result

def next_html(raw,url,hosts,page):
    soup=BeautifulSoup(raw,'html.parser')
    for node in soup.select('a[rel~="next"],link[rel~="next"],.pagination a.next,.nav-links a.next,a.nextpostslink'):
        target=urljoin(url,node.get('href',''))
        if urlsplit(target).scheme=='https' and urlsplit(target).hostname in hosts and target!=url:return {'url':target,'page':page+1}
    from urllib.parse import parse_qs
    candidates=[]
    for node in soup.select('.pagination a[href],.navigation a[href],.nav-links a[href]'):
        target=urljoin(url,node['href']);p=urlsplit(target);query=parse_qs(p.query)
        number=next(iter(query.get('page',[]) or query.get('paged',[])),None)
        if number is None:
            match=re.search(r'/page/(\d+)',p.path);number=match[1] if match else None
        if number and str(number).isdigit() and int(number)>page and p.scheme=='https' and p.hostname in hosts:candidates.append((int(number),target))
    if candidates:
        number,target=min(candidates);return {'url':target,'page':number}
    return None

def html_rows(raw,url):
    from content_sources import html_titles
    rows=html_titles(raw,url,'','tag')
    if rows:return rows
    # Next.js catalogues can expose plain title links without the older wrappers.
    from manga_sources import site_for
    site=site_for(url)
    if not site:return []
    result={};soup=BeautifulSoup(raw,'html.parser')
    for anchor in soup.select('a[href*="/manga/"]'):
        target=urljoin(url,anchor.get('href',''));p=urlsplit(target);title=anchor.get_text(' ',strip=True)
        if not title or len(title)>500 or site_for(target)!=site or not re.fullmatch(r'/manga/[\w-]+/?',p.path):continue
        result[target]={'kind':'manga','title':title,'aliases':[title],'provider':site.id,'providerName':site.name,'url':target,'sourceUrl':target,'language':'ru','tags':[],'genres':[]}
    return list(result.values())

def fetch(spec,cursor):
    page=int(cursor.get('page',1));kind=spec['type'];details=[];vocabulary=[]
    if kind=='unsupported':return {'rows':[],'next':None,'state':'unsupported','reason':spec['reason']}
    if kind=='mirror':return {'rows':[],'next':None,'state':'done','reason':'Зеркало '+spec['primary']}
    if kind in {'lib','lib-detail','lib-vocabulary'}:
        with httpx.Client(http2=True,timeout=15,headers=headers(spec)) as client:
            root='https://api.cdnrulib.link';hosts={'api.cdnrulib.link'}
            if kind=='lib-vocabulary':
                raw,_=checked_get(client,root+'/api/constants?fields[]=genres&fields[]=tags',hosts)
                return {'rows':[],'next':None,'vocabulary':lib_terms(raw,spec['site'])}
            if kind=='lib-detail':
                raw,_=checked_get(client,root+'/api/manga/'+spec['slug']+'?fields[]=genres&fields[]=tags&fields[]=summary&fields[]=otherNames',hosts)
                data=json.loads(raw).get('data') or {}
                if not data.get('id') and not data.get('slug_url'):raise SourceError('Источник не предоставил метаданные карточки')
                metadata=lib_metadata(data);row={**spec['row'],**metadata,**from_api(data),'metadataInspected':True}
                if metadata.get('aliases'):row['title']=metadata['aliases'][0]
                if not row.get('title','').strip():raise SourceError('Источник пока не опубликовал название этой записи')
                return {'rows':[row],'next':None}
            params=[('site_id[]',spec['site']),('page',page)]
            if cursor.get('seed'):params.append(('seed',cursor['seed']))
            if spec.get('term'):params.append(('genres[]' if spec['term']['category']=='genre' else 'tags[]',spec['term']['sourceId']))
            raw,_=checked_get(client,root+'/api/manga?'+urlencode(params),hosts);data=json.loads(raw)
            if not isinstance(data.get('data'),list):raise SourceError('Источник изменил структуру каталога')
            term=spec.get('term') or {};rows=lib_titles(data,spec['site'],term.get('label',''),term.get('category','tag'))
            for row in rows:
                slug=urlsplit(row['url']).path.rstrip('/').split('/')[-1]
                details.append({**spec,'type':'lib-detail','slug':slug,'row':row})
            meta=data.get('meta') or {};more=meta.get('has_next_page')
            if more is None:more=bool(data.get('links',{}).get('next')) if 'links' in data else bool(rows)
            # An incomplete listing stub must remain queued for its own detail
            # fetch, without stopping every subsequent catalogue page.
            return {'rows':[r for r in rows if r.get('title','').strip()],'next':{'page':page+1,'seed':meta.get('seed') or cursor.get('seed')} if more else None,'details':details}
    if kind in {'remanga','remanga-vocabulary'}:
        from source_parser import PublicHttp
        import manga_remanga
        http=PublicHttp(timeout=(3,15))
        try:
            if kind=='remanga-vocabulary':return {'rows':[],'next':None,'vocabulary':manga_remanga.vocabulary(http)}
            term=spec.get('term') or {};identity=term.get('sourceId')
            result=manga_remanga.catalogue_page(page,http,genre=identity if term.get('category')=='genre' else None,category=identity if term and term.get('category')!='genre' else None)
            return result
        finally:http.close()
    if kind in {'bridge','bridge-detail','bridge-vocabulary'}:
        from suwayomi_bridge import Client,filter_vocabulary,filtered_page
        from manga_discovery import result_row
        client=Client()
        try:
            if kind=='bridge-vocabulary':return {'rows':[],'next':None,'vocabulary':filter_vocabulary(client,spec['source']['id'])}
            if kind=='bridge-detail':
                data=client.get('/manga/'+str(spec['manga']),{'onlineFetch':'true'},timeout=25)
                if not data.get('title'):raise SourceError('Адаптер не предоставил метаданные карточки')
                found=from_api(data);row=spec['row']
                # Keep a label learned from the extension's own filter listing.
                for field in ('tags','genres'):found[field]=unique([*(found.get(field) or []),*(row.get(field) or [])])
                updated=__import__('manga_discovery').result_row(spec['source'],data)
                return {'rows':[{**row,**(updated or {}),'description':str(data.get('description') or '')[:12000],**found,'metadataInspected':True}],'next':None}
            source=spec['source'];term=spec.get('term')
            data=filtered_page(client,source['id'],term,page) if term else client.get('/source/'+str(source['id'])+'/popular/'+str(page),timeout=25)
            if not isinstance(data.get('mangaList'),list) or not isinstance(data.get('hasNextPage'),bool):raise SourceError('Адаптер не предоставил пагинацию каталога')
            if page==1 and not data['mangaList'] and not spec.get('term'):raise SourceError('Адаптер вернул пустую первую страницу каталога')
            rows=[];field='genres' if term and term.get('category')=='genre' else 'tags'
            for raw in data['mangaList']:
                row=result_row(source,raw)
                if not row:continue
                # A title listed under the extension's own filter carries that label.
                if term:row[field]=unique([*(row.get(field) or []),term['label']])
                rows.append(row);details.append({**{k:v for k,v in spec.items() if k!='term'},'type':'bridge-detail','manga':raw['id'],'row':row})
            return {'rows':rows,'next':{'page':page+1} if data['hasNextPage'] else None,'details':details}
        finally:client.close()
    if kind in {'html','html-detail'}:
        url=cursor.get('url') or spec['url'];hosts=set(spec['hosts'])
        with requests.Session() as session:
            from content_sources import UA
            session.headers.update({'User-Agent':UA,'Referer':'https://'+urlsplit(url).hostname+'/','Accept':'text/html'})
            if not permitted(session,url,hosts):raise SourceError('Источник не разрешил получение каталога')
            raw,final=checked_get(session,url,hosts,timeout=30)
        soup=BeautifulSoup(raw,'html.parser')
        from manga_sources import guard
        guard(soup)
        if kind=='html-detail':
            if urlsplit(final).path.rstrip('/')!=urlsplit(url).path.rstrip('/'):
                raise SourceError('Источник перенаправил карточку на другое произведение')
            if spec['domain']=='hentaichan.cc':
                from manga_hentaichan_cc import catalogue_metadata
                metadata=catalogue_metadata(soup)
                if metadata['sourceMetadataVersion']<2:raise SourceError('Не получен полный список тегов карточки HentaiChan.cc')
                return {'rows':[{**spec['row'],**metadata,'metadataInspected':True}],'next':None}
            from catalogue_html import SPECIAL,metadata as source_metadata
            metadata=source_metadata(soup,spec['domain']) if spec['domain'] in SPECIAL else {}
            description=soup.select_one('meta[property="og:description"],meta[name="description"]')
            summary=soup.select_one('.description-summary,.summary__content,[itemprop="description"],.manga-description')
            text=summary.get_text(' ',strip=True) if summary else description.get('content','') if description else ''
            if text:metadata['description']=str(text)[:12000]
            cover=soup.select_one('meta[property="og:image"]')
            if cover:
                from content_catalog import safe_url
                value=safe_url(urljoin(final,cover.get('content','')))
                if value:metadata['cover']=value
            for node in soup.select('nav,aside,footer,.sidebar,.tagcloud,.tag-cloud,.related,.recommendations'):node.decompose()
            generic=from_html(soup)
            for field in ('tags','genres'):generic[field]=unique([*generic[field],*(metadata.get(field) or [])])
            return {'rows':[{**spec['row'],**metadata,**generic,'metadataInspected':True}],'next':None}
        if spec['domain']=='hentaichan.cc':
            from manga_hentaichan_cc import catalogue_page
            result=catalogue_page(raw,final,page)
            for row in result['rows']:
                if spec.get('term'):row['tags']=unique([*row.get('tags',[]),spec['term']['label']])
                details.append({**spec,'type':'html-detail','url':row['url'],'row':row})
            return {**result,'details':details}
        from catalogue_html import SPECIAL,catalogue
        if spec['domain'] in SPECIAL:
            result=catalogue(raw,final,spec,page)
            for row in result['rows']:
                if spec.get('term'):
                    field='genres' if spec['term'].get('category')=='genre' else 'tags'
                    row[field]=unique([*row.get(field,[]),spec['term']['label']])
                details.append({**spec,'type':'html-detail','url':row['url'],'row':row})
            return {**result,'details':details,'vocabulary':result.get('vocabulary',html_terms(raw,final,hosts))}
        rows=html_rows(raw,final)
        if not rows:raise SourceError('Не удалось прочитать карточки каталога')
        if spec.get('term'):
            term=spec['term'];field='genres' if term.get('category')=='genre' else 'tags'
            for row in rows:row[field]=list(dict.fromkeys([*(row.get(field) or []),term['label']]))
        for row in rows:details.append({**spec,'type':'html-detail','url':row['url'],'row':row})
        return {'rows':rows,'next':next_html(raw,final,hosts,page),'details':details,'vocabulary':html_terms(raw,final,hosts)}
    from metadata_catalog import get_json
    from content_metadata import anilist_rows,movie_rows
    if kind=='anilist':
        from metadata_catalog import MEDIA_FIELDS
        media='ANIME' if spec['kind']=='anime' else 'MANGA'
        formats=',format_in:[NOVEL]' if spec['kind']=='ranobe' else ',format_not_in:[NOVEL]' if spec['kind']=='manga' else ''
        term=spec.get('term');definition=',$term:[String]' if term else '';argument=','+('genre_in' if term.get('field')=='genre' else 'tag_in')+':$term' if term else ''
        body={'query':'query($page:Int'+definition+'){Page(page:$page,perPage:40){pageInfo{hasNextPage,total}media(type:'+media+',sort:ID'+formats+argument+'){'+MEDIA_FIELDS+'}}}','variables':{'page':page,**({'term':[term['label']]} if term else {})}}
        data=get_json('https://graphql.anilist.co',body=body);info=data.get('data',{}).get('Page',{}).get('pageInfo') or {}
        if 'hasNextPage' not in info:raise SourceError('Каталог не предоставил пагинацию')
        return {'rows':anilist_rows(data,spec['kind']),'next':{'page':page+1} if info['hasNextPage'] else None,'total':info.get('total')}
    if kind=='kinobox':
        data=get_json('https://fbphdplay.top/api/popular',params={'page':page,'type':'series' if spec['kind']=='tv' else 'films'});rows=movie_rows(data,spec['kind'])
        return {'rows':rows,'next':{'page':page+1} if rows else None}
    if kind=='books':
        params={'limit':40,'offset':(page-1)*40,'sort':'key','fields':'key,title,subject,first_publish_year,cover_i'}
        params.update({'subject':spec['term']['label']} if spec.get('term') else {'q':'*:*'})
        data=get_json('https://openlibrary.org/search.json',params=params);rows=[]
        for item in data.get('docs',[]):
            identity=str(item.get('key','')).removeprefix('/works/')
            if not re.fullmatch(r'OL\d+W',identity) or not item.get('title'):continue
            rows.append({'id':'openlibrary:'+identity,'provider':'openlibrary','providerId':identity,'kind':'book','title':item['title'],'ids':{'openlibrary':identity},'genres':item.get('subject') or [],'tags':[],'year':item.get('first_publish_year'),'sourceUrl':'https://openlibrary.org/works/'+identity,'cover':'https://covers.openlibrary.org/b/id/'+str(item['cover_i'])+'-L.jpg' if item.get('cover_i') else ''})
        total=int(data.get('numFound') or 0)
        return {'rows':rows,'next':{'page':page+1} if rows and page*40<total else None,'total':total}
    raise SourceError('Неизвестный адаптер каталога')
