"""One metadata page per call; cursors use upstream pagination, never chapters."""
import json,re
from urllib.parse import urlsplit,urljoin,urlencode
from bs4 import BeautifulSoup
import httpx,requests
from content_source_routes import LIB,HTML
from content_sources import checked_get,permitted,html_terms,lib_terms,lib_titles
from manga_source_tags import from_api,from_html
from source_parser import SourceError

def base_sources(installed):
    from manga_source_coverage import SOURCES
    from manga_tag_policy import alias_domains
    jobs=[];seen=set()
    for domain,name,integration,*_ in SOURCES:
        if integration=='closed':jobs.append({'type':'unsupported','domain':domain,'name':name,'reason':'Сайт закрыт'});continue
        if domain in LIB:
            site,referer=LIB[domain];jobs.append({'type':'lib','domain':domain,'name':name,'site':site,'referer':referer});continue
        hosts=set(alias_domains(domain));matches=[s for s in installed if urlsplit(s.get('baseUrl','')).hostname in hosts]
        if not matches:
            matches=[s for s in installed if s.get('name','').casefold()==name.casefold() or (name=='AllHentai' and s.get('name')=='AllHentai')]
        if matches:
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

def headers(spec):return {'Site-id':str(spec['site']),'Referer':spec['referer'],'Accept':'application/json','User-Agent':'MediaVault-Catalogue/1.0'}

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
    if kind in {'lib','lib-detail','lib-vocabulary'}:
        with httpx.Client(http2=True,timeout=15,headers=headers(spec)) as client:
            root='https://api.cdnrulib.link';hosts={'api.cdnrulib.link'}
            if kind=='lib-vocabulary':
                raw,_=checked_get(client,root+'/api/constants?fields[]=genres&fields[]=tags',hosts)
                return {'rows':[],'next':None,'vocabulary':lib_terms(raw,spec['site'])}
            if kind=='lib-detail':
                raw,_=checked_get(client,root+'/api/manga/'+spec['slug']+'?fields[]=genres&fields[]=tags',hosts)
                data=json.loads(raw).get('data') or {}
                if not data.get('id') and not data.get('slug_url'):raise SourceError('Источник не предоставил метаданные карточки')
                row={**spec['row'],**from_api(data),'metadataInspected':True}
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
            return {'rows':rows,'next':{'page':page+1,'seed':meta.get('seed') or cursor.get('seed')} if more else None,'details':details}
    if kind in {'bridge','bridge-detail'}:
        from suwayomi_bridge import Client
        from manga_discovery import result_row
        client=Client()
        try:
            if kind=='bridge-detail':
                data=client.get('/manga/'+str(spec['manga']),{'onlineFetch':'true'},timeout=25)
                if not data.get('title'):raise SourceError('Адаптер не предоставил метаданные карточки')
                return {'rows':[{**spec['row'],**from_api(data),'metadataInspected':True}],'next':None}
            source=spec['source'];data=client.get('/source/'+str(source['id'])+'/popular/'+str(page),timeout=25)
            if not isinstance(data.get('mangaList'),list) or not isinstance(data.get('hasNextPage'),bool):raise SourceError('Адаптер не предоставил пагинацию каталога')
            rows=[]
            for raw in data['mangaList']:
                row=result_row(source,raw)
                if not row:continue
                rows.append(row);details.append({**spec,'type':'bridge-detail','manga':raw['id'],'row':row})
            return {'rows':rows,'next':{'page':page+1} if data['hasNextPage'] else None,'details':details}
        finally:client.close()
    if kind in {'html','html-detail'}:
        url=cursor.get('url') or spec['url'];hosts=set(spec['hosts'])
        with requests.Session() as session:
            session.headers['User-Agent']='MediaVault-Catalogue/1.0'
            if not permitted(session,url,hosts):raise SourceError('Источник не разрешил получение каталога')
            raw,final=checked_get(session,url,hosts)
        soup=BeautifulSoup(raw,'html.parser')
        from manga_sources import guard
        guard(soup)
        if kind=='html-detail':
            for node in soup.select('nav,aside,footer,.sidebar,.tagcloud,.tag-cloud,.related,.recommendations'):node.decompose()
            return {'rows':[{**spec['row'],**from_html(soup),'metadataInspected':True}],'next':None}
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
