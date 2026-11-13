"""Owner-triggered bounded public taxonomy/metadata refresh. No reader bytes."""
import json,time
from urllib.parse import urljoin,urlsplit,urlencode
from urllib.robotparser import RobotFileParser
import requests,httpx
from bs4 import BeautifulSoup
from content_source_routes import HTML,LIB
from manga_source_coverage import SOURCES
from manga_source_tags import clean_label,from_api
from manga_tag_policy import current,canonical_json
from manga_tag_deploy import atomic_write

UA='MediaVault-Content/1.0 (+https://github.com/Onikri/MediaVault)'
SELECTOR='a[rel="tag"],.tags a[href],.genres a[href],.tag-list a[href],.genre-list a[href],a[href*="/tag/"],a[href*="/tags/"],a[href*="/genre/"],a[href*="/genres/"],a[href*="/category/"],a[href*="tag="]'

def matching_terms(terms,domain,keys):
    found={}
    for term in terms:
        key=current().key(term['label'],domain)
        if key and (keys is None or key in keys):found.setdefault(key,term)
    return list(found.values())

def checked_get(session,url,hosts,headers=None):
    for _ in range(4):
        p=urlsplit(url)
        if p.scheme!='https' or p.hostname not in hosts or p.username or p.password:raise ValueError('unapproved taxonomy host')
        response=session.send(session.build_request('GET',url,headers=headers or {},timeout=10),stream=True,follow_redirects=False) if isinstance(session,httpx.Client) else session.get(url,headers=headers or {},timeout=(4,10),allow_redirects=False,stream=True)
        try:
            if isinstance(response,httpx.Response) and response.http_version!='HTTP/2':raise ValueError('HTTP/2 required')
            if response.status_code in {301,302,303,307,308}:
                url=urljoin(url,response.headers.get('location',''));continue
            if response.status_code==429:raise ValueError('rate_limited')
            response.raise_for_status();data=bytearray()
            for chunk in response.iter_bytes(65536) if isinstance(response,httpx.Response) else response.iter_content(65536):
                data.extend(chunk)
                if len(data)>1_500_000:raise ValueError('taxonomy too large')
            return bytes(data),url
        finally:response.close()
    raise ValueError('too many redirects')

def permitted(session,url,hosts,headers=None):
    p=urlsplit(url)
    try:
        raw,_=checked_get(session,p.scheme+'://'+p.netloc+'/robots.txt',hosts,headers)
        robots=RobotFileParser();robots.parse(raw.decode(errors='replace').splitlines());return robots.can_fetch(UA,url)
    except (requests.HTTPError,httpx.HTTPStatusError) as error:return error.response.status_code==404
    except Exception:return False

def html_terms(raw,url,hosts):
    found={}
    for anchor in BeautifulSoup(raw,'html.parser').select(SELECTOR)[:4000]:
        label=clean_label(anchor.get_text(' ',strip=True));link=urljoin(url,anchor.get('href') or '')
        p=urlsplit(link)
        if not label or p.scheme!='https' or p.hostname not in hosts:continue
        category='genre' if 'genre' in link or any('genre' in c for c in anchor.get('class',[])) else 'tag'
        found[(label,category)]={'label':label,'category':category,'url':link}
    return list(found.values())[:1500]

def lib_terms(raw,site_id):
    payload=json.loads(raw);payload=payload.get('data',payload);out=[]
    if not isinstance(payload,dict):return out
    for field,category in (('genres','genre'),('tags','tag')):
        for row in (payload.get(field) or [])[:1500]:
            if not isinstance(row,dict) or not isinstance(row.get('id'),int):continue
            if isinstance(row.get('site_ids'),list) and site_id not in row['site_ids']:continue
            value=row.get('name') or row.get('label');names=value.values() if isinstance(value,dict) else [value]
            for name in names:
                if label:=clean_label(name):out.append({'label':label,'category':category,'sourceId':row['id']})
    return out[:1500]

def html_titles(raw,url,label,category):
    from manga_sources import site_for,parse_search
    from manga_hmanga import parse_search as hmanga
    site=site_for(url)
    if not site:return []
    text=raw.decode('utf-8',errors='replace')
    if site.id=='hmanga':rows=hmanga(text,url)
    else:
        try:rows=parse_search(text,url,site)
        except (KeyError,ValueError):return []
    # Membership in a source's exact tag listing is an explicit source fact.
    field='genres' if category=='genre' else 'tags'
    return [{**row,field:list(dict.fromkeys([*(row.get(field) or []),label]))} for row in rows[:50]]

def summary_text(value,depth=0,budget=None):
    if budget is None:budget=[3000]
    if depth>12 or budget[0]<=0:return ''
    budget[0]-=1
    if isinstance(value,str):return BeautifulSoup(value[:50000],'html.parser').get_text(' ',strip=True)[:12000]
    if isinstance(value,list):return ' '.join(summary_text(v,depth+1,budget) for v in value[:1000])[:12000]
    if isinstance(value,dict):
        if isinstance(value.get('text'),str):return value['text'][:12000]
        return summary_text(value.get('content'),depth+1,budget)
    return ''


def lib_metadata(row):
    cover=row.get('cover') or {}
    summary=row.get('summary') or row.get('description') or ''
    return {'cover':cover.get('default','') if isinstance(cover,dict) else '',
            'description':summary_text(summary),
            'aliases':list(dict.fromkeys(v for v in [row.get('rus_name'),row.get('eng_name'),row.get('name'),*(row.get('otherNames') or [])] if isinstance(v,str) and v.strip()))[:60],
            'status':(row.get('status') or {}).get('label','') if isinstance(row.get('status'),dict) else ''}


def lib_titles(payload,site_id,label,category):
    from manga_catalog_adapters import LIB_SITES,lib_identity
    provider,name,root=LIB_SITES[site_id];rows=[]
    for row in payload.get('data',[])[:60]:
        slug=row.get('slug_url');title=row.get('rus_name') or row.get('eng_name') or row.get('name')
        if not isinstance(slug,str) or not __import__('re').fullmatch(r'[\w-]{1,250}',slug) or not isinstance(title,str):continue
        field='genres' if category=='genre' else 'tags';facts=from_api(row);facts[field]=list(dict.fromkeys([*facts[field],label]))
        format={'Манга':'manga','Манхва':'manhwa','Маньхуа':'manhua','Manga':'manga','Manhwa':'manhwa','Manhua':'manhua'}.get((row.get('type') or {}).get('label'),'manga')
        rows.append({'kind':'manga','format':format,'provider':provider,'providerName':name,'title':title,'aliases':[title],
                     'url':root+'/ru/'+slug,'sourceUrl':root+'/ru/'+slug,'language':'ru','adult':site_id==4,'age':18 if site_id==4 else None,**lib_metadata(row),**lib_identity(row),**facts})
    return rows

def scan(store,keys=None):
    from content_management import directory
    from manga_catalog_index import upsert
    path=directory()/'content-source-vocabulary.json'
    try:cache=json.loads(path.read_text())
    except (OSError,ValueError):cache={'sources':[]}
    cached={row['domain']:row for row in cache.get('sources',[])}
    with requests.Session() as session:
        session.headers.update({'User-Agent':UA,'Accept':'text/html,application/json'})
        for domain,name,integration,*_ in SOURCES:
            result={'domain':domain,'name':name,'status':'unavailable','indexed':0,'matched':0}
            terms=[]
            if integration=='closed':result['status']='closed';yield result;continue
            try:
                if domain in LIB:
                    site_id,referer=LIB[domain];root='https://api.cdnrulib.link';hosts={'api.cdnrulib.link'}
                    headers={'Site-id':str(site_id),'Referer':referer,'Accept':'application/json'}
                    with httpx.Client(http2=True,headers={'User-Agent':UA}) as client:
                        url=root+'/api/constants?fields[]=genres&fields[]=tags'
                        if not permitted(client,url,hosts,headers):raise ValueError('robots_or_network')
                        raw,_=checked_get(client,url,hosts,headers);terms=lib_terms(raw,site_id)
                        matches=matching_terms(terms,domain,keys)
                        result['matched']=len(matches)
                        for term in matches[:4]:
                            params=[('site_id[]',site_id),('genres[]' if term['category']=='genre' else 'tags[]',term['sourceId']),('page',1)]
                            data,_=checked_get(client,root+'/api/manga?'+urlencode(params),hosts,headers)
                            rows=lib_titles(json.loads(data),site_id,term['label'],term['category'])
                            with store.lock,store.db:result['indexed']+=upsert(store.db,rows)
                            time.sleep(.3)
                elif domain in HTML:
                    url,hosts=HTML[domain]
                    if not permitted(session,url,hosts):raise ValueError('robots_or_network')
                    raw,final=checked_get(session,url,hosts);terms=html_terms(raw,final,hosts)
                    matches=matching_terms(terms,domain,keys)
                    result['matched']=len(matches)
                    for term in matches[:4]:
                        if not permitted(session,term['url'],hosts):continue
                        data,final=checked_get(session,term['url'],hosts)
                        rows=html_titles(data,final,term['label'],term['category'])
                        with store.lock,store.db:result['indexed']+=upsert(store.db,rows)
                        time.sleep(.3)
                else:raise ValueError('not_configured')
                result.update(status='partial' if terms else 'no_taxonomy',terms=len(terms),limited=result['matched']>4)
                cached[domain]={'domain':domain,'terms':terms,'checkedAt':int(time.time())}
            except Exception:
                result.update(status='unavailable',reason='Источник не предоставил доступный публичный каталог тегов.')
            atomic_write(path,canonical_json({'sources':list(cached.values())}))
            yield result;time.sleep(.3)
