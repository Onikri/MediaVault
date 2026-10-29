"""Public MangaDex catalogue and MangaLib reader data; no keys or login state.

MangaLib field layout checked against Keiyoushi LibGroup (Apache-2.0).
Only openly accessible chapters are accepted. Availability is reported by caller.
"""
import json,re,time
from urllib.parse import urlencode,urlsplit,parse_qs,quote
from source_parser import PublicHttp,SourceError,public_url
UUID=r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'
LIB='https://api.cdnlibs.org'
def api_url(value):
    p=urlsplit(value)
    allowed=(p.hostname=='api.mangadex.org' and re.fullmatch(rf'/(?:manga(?:/{UUID}(?:/feed)?)?|chapter/{UUID}|at-home/server/{UUID})',p.path)) or (p.hostname=='api.cdnlibs.org' and re.fullmatch(r'/api/(?:manga(?:/[\w-]+(?:/chapters|/chapter)?)?|constants)',p.path))
    if not allowed:raise SourceError('Этот адрес не относится к публичной читалке.')
    return public_url(value,allow_api=True)
def get(url,http):
    client=PublicHttp(validate=api_url,timeout=getattr(http,'timeout',(3,7)),deadline=getattr(http,'deadline',time.monotonic()+30))
    try:
        if urlsplit(url).hostname=='api.cdnlibs.org':
            # LibGroup identifies its public catalogue with a site header, not
            # only the search parameter. Without it this API returns HTTP403.
            client.session.headers.update({'Site-Id':'1','Accept':'application/json'})
            text,_,_=client.document(url,headers={'Referer':'https://mangalib.me/'})
        else:text,_,_=client.document(url)
        try:data=json.loads(text)
        except ValueError:raise SourceError('Читалка не предоставила данные.') from None
        if not isinstance(data,dict):raise SourceError('Неизвестный формат данных читалки.')
        return data
    finally:client.close()
def names(attributes):
    return list(dict.fromkeys(v for row in [attributes.get('title',{}),*attributes.get('altTitles',[])] for v in row.values() if isinstance(v,str) and v.strip()))
def dex_search(query,language,http):
    languages=['ru','en','ja','ko'] if language=='all' else [language if language in {'ru','en','ja','ko'} else 'ru']
    params=[('title',query),('limit','25'),('includes[]','cover_art')]+[('availableTranslatedLanguage[]',l) for l in languages]+[('contentRating[]',r) for r in ['safe','suggestive','erotica']]
    rows=get('https://api.mangadex.org/manga?'+urlencode(params),http).get('data',[]);out=[]
    for row in rows:
        a=row.get('attributes',{});aliases=names(a)
        if not aliases or a.get('contentRating')=='pornographic':continue
        cover=next((v.get('attributes',{}).get('fileName') for v in row.get('relationships',[]) if v['type']=='cover_art'),None)
        for lang in languages:
            if lang not in a.get('availableTranslatedLanguages',[]):continue
            name=a.get('title',{}).get('ru') or next((v['ru'] for v in a.get('altTitles',[]) if v.get('ru')),aliases[0])
            out.append({'provider':'mangadex','providerName':'MangaDex · '+lang.upper(),'title':name,'aliases':aliases,'kind':'manga','format':'manhwa' if a.get('originalLanguage')=='ko' else 'manhua' if a.get('originalLanguage') in {'zh','zh-hk'} else 'manga','readingMode':'scroll' if any(v.get('attributes',{}).get('name',{}).get('en')=='Long Strip' for v in a.get('tags',[])) else 'pages','language':lang,'year':a.get('year'),'url':'https://mangadex.org/title/'+row['id']+'?lang='+lang,'cover':'https://uploads.mangadex.org/covers/'+row['id']+'/'+cover+'.256.jpg' if cover else ''})
    return out

def dex_available(url,http):
    p=urlsplit(url);identity=p.path.split('/')[2];lang=parse_qs(p.query).get('lang',['ru'])[0]
    data=get('https://api.mangadex.org/manga/'+identity+'/feed?'+urlencode({'translatedLanguage[]':lang,'limit':1,'includeExternalUrl':0}),http)
    return any(v.get('attributes',{}).get('pages') and not v.get('attributes',{}).get('externalUrl') for v in data.get('data',[]))

def lib_search(query,http):
    data=get(LIB+'/api/manga?'+urlencode({'q':query,'site_id[]':1}),http);out=[]
    for a in data.get('data',[]):
        slug=str(a.get('slug_url') or '')
        if not re.fullmatch(r'[\w-]{1,250}',slug):continue
        aliases=list(dict.fromkeys(v for v in [a.get('rus_name'),a.get('eng_name'),a.get('name'),*(a.get('otherNames') or [])] if isinstance(v,str) and v))
        if not aliases:continue
        out.append({'provider':'mangalib','providerName':'MangaLib','title':aliases[0],'aliases':aliases,'kind':'manga','language':'ru','year':a.get('releaseDate'),'url':'https://mangalib.me/ru/'+slug,'cover':a.get('cover',{}).get('default','')})
    return out

def inspect_catalog(url,http):
    from manga_sources import chapter_number,clean
    p=urlsplit(url);query=parse_qs(p.query);chapters=[];pages=[];language=query.get('lang',['ru'])[0]
    if p.hostname=='mangadex.org':
        language=language if language in {'ru','en','ja','ko'} else 'ru'
        match=re.fullmatch(r'/(title|chapter)/('+UUID+r')(?:/[^/]*)?/?',p.path)
        if not match:raise SourceError('Нужна ссылка MangaDex на тайтл или главу.')
        kind,identity=match.groups()
        if kind=='chapter':
            record=get('https://api.mangadex.org/chapter/'+identity,http).get('data',{});a=record.get('attributes',{})
            if a.get('externalUrl'):raise SourceError('Эта глава доступна только на внешнем сайте.')
            language=a.get('translatedLanguage')
            if language not in {'ru','en','ja','ko'}:raise SourceError('Выбери доступный язык главы: RU, EN, JA или KO.')
            server=get('https://api.mangadex.org/at-home/server/'+identity+'?forcePort443=true',http);part=server.get('chapter',{});base=public_url(server.get('baseUrl',''),resolve_dns=False)
            pages=[base+'/data/'+quote(part['hash'],safe='')+'/'+quote(f,safe='') for f in part.get('data',[])][:1500]
            root=next((v['id'] for v in record.get('relationships',[]) if v['type']=='manga'),None)
            detail=get('https://api.mangadex.org/manga/'+root,http).get('data',{}) if root else {};title=(names(detail.get('attributes',{})) or ['Манга'])[0]
            chapters=[{'number':chapter_number(a.get('chapter') or '0'),'season':max(1,int(a.get('volume') or 1)) if str(a.get('volume') or 1).isdigit() else 1,'title':clean(a.get('title')),'url':url,'translator':'','language':language}];truncated=False
        else:
            detail=get('https://api.mangadex.org/manga/'+identity,http).get('data',{});a=detail.get('attributes',{});title=(names(a) or ['Манга'])[0]
            if a.get('contentRating')=='pornographic':raise SourceError('Этот источник не поддерживается.')
            offset=0;total=1
            while offset<total and offset<1500:
                data=get('https://api.mangadex.org/manga/'+identity+'/feed?'+urlencode({'translatedLanguage[]':language,'limit':100,'offset':offset,'order[volume]':'asc','order[chapter]':'asc','includes[]':'scanlation_group','includeExternalUrl':0}),http)
                rows=data.get('data',[]);total=data.get('total',0)
                for row in rows:
                    a=row.get('attributes',{});n=str(a.get('chapter') or '0')
                    if a.get('externalUrl') or not a.get('pages') or not re.fullmatch(r'\d{1,4}(?:\.\d{1,3})?',n):continue
                    team=', '.join(v.get('attributes',{}).get('name','') for v in row.get('relationships',[]) if v['type']=='scanlation_group')
                    chapters.append({'number':chapter_number(n),'season':max(1,int(a.get('volume') or 1)) if str(a.get('volume') or 1).isdigit() else 1,'title':clean(a.get('title')) or 'Глава '+n,'url':'https://mangadex.org/chapter/'+row['id']+'?lang='+language,'translator':team,'language':language})
                if not rows:break
                offset+=len(rows)
            truncated=offset<total
        attributes=detail.get('attributes',{});format='manhwa' if attributes.get('originalLanguage')=='ko' else 'manhua' if attributes.get('originalLanguage') in {'zh','zh-hk'} else 'manga'
        return {**result('mangadex','MangaDex',title,url,language,chapters,pages,truncated),'format':format,'readingMode':'scroll' if format=='manhwa' or any(v.get('attributes',{}).get('name',{}).get('en')=='Long Strip' for v in attributes.get('tags',[])) else 'pages','aliases':names(attributes)}
    match=re.fullmatch(r'/ru/(?:manga/)?([\w-]+)(?:/read/v(\d+)/c(\d+(?:\.\d+)?))?/?',p.path)
    if not match:raise SourceError('Нужна ссылка MangaLib на тайтл или главу.')
    slug,volume,number=match.groups();detail=get(LIB+'/api/manga/'+slug+'?fields[]=otherNames&fields[]=eng_name',http).get('data',{});title=detail.get('rus_name') or detail.get('name') or detail.get('eng_name') or slug
    if volume and number:
        args={'volume':volume,'number':number}
        branch=query.get('bid',[''])[0]
        if branch.isdigit():args['branch_id']=branch
        data=get(LIB+'/api/manga/'+slug+'/chapter?'+urlencode(args),http).get('data',{})
        if (data.get('restricted_view') or {}).get('is_open') is False:raise SourceError('Глава закрыта или требует покупки.')
        constants=get(LIB+'/api/constants?fields[]=imageServers',http).get('data',{}).get('imageServers',[])
        hosts=[v['url'] for v in constants if 1 in v.get('site_ids',[]) and v.get('id')=='compress'] or [v['url'] for v in constants if 1 in v.get('site_ids',[])]
        if not hosts:raise SourceError('MangaLib не предоставил сервер страниц.')
        pages=[public_url(hosts[0].rstrip('/')+'/'+v['url'].lstrip('/'),resolve_dns=False) for v in sorted(data.get('pages',[]),key=lambda v:v.get('slug',0))][:1500]
        chapters=[{'number':chapter_number(number),'season':int(volume),'title':'Глава '+number,'url':url,'translator':'','language':'ru'}]
    else:
        data=get(LIB+'/api/manga/'+slug+'/chapters',http).get('data',[])
        for row in data[:1500]:
            n=str(row.get('number') or '0');vol=str(row.get('volume') or 1)
            if not re.fullmatch(r'\d{1,4}(?:\.\d{1,3})?',n) or not vol.isdigit():continue
            for branch in row.get('branches',[]) or [{}]:
                if (branch.get('restricted_view') or {}).get('is_open') is False:continue
                bid=str(branch.get('branch_id') or '');suffix='?bid='+bid if bid.isdigit() else ''
                team=', '.join(v.get('name','') for v in branch.get('teams',[]))
                chapters.append({'number':chapter_number(n),'season':max(1,int(vol)),'title':clean(row.get('name')) or 'Глава '+n,'url':'https://mangalib.me/ru/'+slug+'/read/v'+vol+'/c'+n+suffix,'translator':team,'language':'ru'})
    return result('mangalib','MangaLib',title,url,'ru',chapters,pages,len(chapters)>=1500)

def result(provider,name,title,url,language,chapters,pages,truncated=False):
    return {'provider':provider,'providerName':name,'title':str(title)[:300],'url':url,'kind':'manga','language':language,'episodes':chapters,'pages':pages,'seasons':[{'number':n,'name':'Том '+str(n)} for n in sorted({c['season'] for c in chapters})],'dubs':[],'releases':[],'truncated':truncated,'available':bool(chapters),'translations':sorted({c['translator'] for c in chapters if c['translator']})}
