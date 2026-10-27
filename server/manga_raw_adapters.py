"""Public JA/KO readers; no account cookies, private endpoints or JS execution.

Contracts checked against Keiyoushi extensions-source (Apache-2.0), revision
6768cbc2049c5e07d67ea1ac667af73f9737596a. See docs/manga-raw-sources.md.
"""
import base64
import json
import re
import time
from urllib.parse import parse_qs,quote,urlencode,urlsplit
from bs4 import BeautifulSoup
from source_parser import PublicHttp,SourceError,public_url

RAW_API='https://api.mangarw.com/api/v1'
NAVER='https://comic.naver.com'
SEN='https://raw.senmanga.com'
LANGUAGES=('ru','en','ja','ko')

def api_url(value):
    p=urlsplit(value)
    allowed=(p.hostname=='api.mangarw.com' and re.fullmatch(r'/api/v1/(?:search/?|manga/\d+(?:/chapters)?|chapter/\d+)',p.path)) or (p.hostname=='raw.senmanga.com' and re.fullmatch(r'/api/(?:directory|manga/[\w.-]+|read/[\w.-]+/[\w.-]+)',p.path)) or (p.hostname=='comic.naver.com' and re.fullmatch(r'/api/(?:search/(?:webtoon|bestChallenge|challenge)|article/list(?:/info)?)',p.path))
    if not allowed or any(v in {'.','..'} for v in p.path.split('/')):raise SourceError('Этот адрес не относится к публичным данным поддерживаемой читалки.')
    return public_url(value,allow_api=True)

def get(url,http):
    client=PublicHttp(validate=api_url,timeout=getattr(http,'timeout',(3,7)),deadline=getattr(http,'deadline',time.monotonic()+32))
    try:
        text,_,_=client.document(url)
        try:value=json.loads(text)
        except ValueError:raise SourceError('Источник не предоставил публичный JSON читалки.') from None
        if not isinstance(value,dict):raise SourceError('Источник изменил формат данных читалки.')
        return value
    finally:client.close()

def number(value):
    from manga_sources import chapter_number
    text='' if value is None else str(value)
    for pattern in [r'(?:chapter|ch\.?|глава|第)\s*(\d+(?:[.,]\d{1,3})?)',r'(\d+(?:[.,]\d{1,3})?)\s*(?:話|화|회)',r'^(\d+(?:[.,]\d{1,3})?)$']:
        match=re.search(pattern,text,re.I)
        if match:return chapter_number(match[1])
    return None

def record(site,title,url,cover='',aliases=(),format=None):
    from manga_sources import clean,safe_link
    names=list(dict.fromkeys(clean(v) for v in [title,*aliases] if v))
    return {'provider':site.id,'providerName':site.name,'title':names[0] if names else '', 'aliases':names,'url':url,'kind':'manga','format':format or site.format,'readingMode':'scroll' if (format or site.format) in {'manhwa','webtoon'} else 'pages','language':site.languages[0],'cover':safe_link(cover,site.root)}

def search(query,site,http):
    from manga_sources import safe_link,guard,site_for
    if site.family=='naver':
        section=urlsplit(site.root).path.strip('/')
        data=get(NAVER+'/api/search/'+section+'?'+urlencode({'keyword':query,'page':1}),http)
        return [record(site,r.get('titleName'),site.root+'/list?'+urlencode({'titleId':r['titleId']}),r.get('thumbnailUrl')) for r in data.get('searchList',[])[:50] if str(r.get('titleId','')).isdigit() and r.get('titleName')]
    if site.family=='mangaraw':
        data=get(RAW_API+'/search/?'+urlencode({'keyword':query}),http)
        return [record(site,r.get('title'),site.root+'/manga/'+str(r['id']),r.get('image'),re.split(r'\s*[;|]\s*',r.get('alternative') or '')) for r in data.get('data',[])[:50] if str(r.get('id','')).isdigit() and r.get('title')]
    if site.family=='sen':
        rows=[];page=1
        # The public directory currently sometimes ignores `s`. Exact title
        # matching remains mandatory; read only the bounded published pages.
        while page<=5:
            data=get(SEN+'/api/directory?'+urlencode({'s':query,'page':page}),http)
            rows.extend(data.get('series',[])[:50])
            if page>=min(5,int(data.get('totalPages') or 1)):break
            page+=1
        return [record(site,r.get('title'),site.root+'/manga/'+r['slug'],r.get('cover'),re.split(r'\s*[;|]\s*',r.get('alt_name') or '')) for r in rows if re.fullmatch(r'[\w.-]{1,300}',r.get('slug','')) and r.get('title')]
    if site.family=='toonkor':
        text,final,_=http.document(site.root+'/bbs/search.php?'+urlencode({'sfl':'wr_subject||wr_content','stx':query}));soup=BeautifulSoup(text,'html.parser');guard(soup);out=[]
        if site_for(final)!=site:raise SourceError('Источник сменил адрес. Адаптер требует проверки.')
        for card in soup.select('div.section-item-inner')[:50]:
            link=card.select_one('div.section-item-title a');heading=link.select_one('h3') if link else None;image=card.select_one('img')
            if link and heading:
                url=safe_link(link.get('href'),final)
                if site_for(url)==site:out.append(record(site,heading.get_text(' ',strip=True),url,image.get('data-src') or image.get('src') if image else ''))
        return out
    raise SourceError('Для этой читалки не настроен поиск.')

def payload(site,title,url,chapters,pages,**extra):
    from manga_catalog_adapters import result
    return {**result(site.id,site.name,title,url,site.languages[0],chapters,pages,extra.pop('truncated',False)), 'aliases':[title], 'format':site.format, 'readingMode':'scroll' if site.format in {'manhwa','webtoon'} else 'pages', **extra}

def chapter(n,url,title,language):
    return {'number':n,'season':1,'url':url,'title':title or 'Глава '+str(n),'translator':'','language':language}

def inspect(url,site,http):
    from manga_sources import safe_link,guard,clean,site_for
    p=urlsplit(url);q=parse_qs(p.query);pages=[];chapters=[]
    if site.family=='naver':
        section=urlsplit(site.root).path.strip('/');identity=q.get('titleId',[''])[0];n=q.get('no',[''])[0]
        if not identity.isdigit() or p.path not in {'/'+section+'/list','/'+section+'/detail'} or n and not n.isdigit():raise SourceError('Нужна ссылка Naver на тайтл или опубликованную главу.')
        detail=get(NAVER+'/api/article/list/info?'+urlencode({'titleId':identity}),http);title=detail.get('titleName') or 'Манхва'
        if n:
            text,final,_=http.document(url);soup=BeautifulSoup(text,'html.parser');guard(soup)
            if urlsplit(final).hostname not in {'comic.naver.com','m.comic.naver.com'}:raise SourceError('Глава требует входа или перенаправила на другой сайт.')
            pages=[safe_link(image.get('data-src') or image.get('src'),final) for image in soup.select('.wt_viewer img,.toon_view_lst img.toon_image')]
            if not any(pages):raise SourceError('Naver не предоставил открытые страницы: глава может требовать покупки, входа или подтверждения возраста.')
            heading=soup.select_one('.view h3,.tit_area h3,.end_head h2,title');label=clean(heading.get_text(' ',strip=True)) if heading else 'Глава '+n
            chapters=[chapter(number(label) if number(label) is not None else int(n),url,label,'ko')]
        else:
            page=1;seen=set()
            while page and page not in seen and len(seen)<50 and len(chapters)<1500:
                seen.add(page);data=get(NAVER+'/api/article/list?'+urlencode({'titleId':identity,'page':page}),http)
                for row in data.get('articleList',[]):
                    no=row.get('no');label=clean(row.get('subtitle'))
                    if not isinstance(no,int) or row.get('charge') or row.get('thumbnailLock') or row.get('blind') or row.get('isBlind'):continue
                    target=site.root+'/detail?'+urlencode({'titleId':identity,'no':no});ordinal=number(label)
                    chapters.append(chapter(ordinal if ordinal is not None else no,target,label,'ko'))
                page=int((data.get('pageInfo') or {}).get('nextPage') or 0)
            chapters=sorted({c['url']:c for c in chapters}.values(),key=lambda c:(c['number'],c['url']))
            return payload(site,title,url,chapters,[],truncated=bool(page),cover=safe_link(detail.get('thumbnailUrl'),url))
        return payload(site,title,url,chapters,[p for p in pages if p],cover=safe_link(detail.get('thumbnailUrl'),url))
    if site.family=='sen':
        match=re.fullmatch(r'/manga/([\w.-]+)(?:/chapter-([\w.-]+))?/?',p.path)
        if not match:raise SourceError('Нужна ссылка Sen Manga на тайтл или главу.')
        slug,part=match.groups();detail=get(SEN+'/api/manga/'+quote(slug,safe=''),http);title=clean(detail.get('title')) or slug
        for row in detail.get('chapterList') or []:
            segment=str(row.get('url') or '');n=number(row.get('title'))
            if n is None:n=number(segment)
            if n is None or not re.fullmatch(r'[\w.-]+',segment):continue
            chapters.append(chapter(n,site.root+'/manga/'+slug+'/chapter-'+segment+'/',clean(row.get('title')),'ja'))
        if part:
            pages=get(SEN+'/api/read/'+quote(slug,safe='')+'/'+quote(part,safe=''),http).get('pages',[])
            chapters=[c for c in chapters if urlsplit(c['url']).path.rstrip('/')==p.path.rstrip('/')]
        return payload(site,title,url,sorted(chapters,key=lambda c:c['number']),[safe_link(v,url) for v in pages if isinstance(v,str)],cover=safe_link(detail.get('cover'),url),aliases=[title,*re.split(r'\s*[;|]\s*',detail.get('alt_name') or '')])
    if site.family=='mangaraw':
        match=re.fullmatch(r'/(manga|chapter)/(\d+)/?',p.path)
        if not match:raise SourceError('Нужна ссылка MangaRaw на тайтл или главу.')
        kind,identity=match.groups();detail=get(RAW_API+'/'+kind+'/'+identity,http).get('data',{})
        if kind=='manga':
            title=clean(detail.get('title')) or 'Манга';rows=get(RAW_API+'/manga/'+identity+'/chapters?order=desc',http).get('data',[])
            for row in rows[:1500]:
                n=number(row.get('index'))
                if n is None:n=number(row.get('title'))
                if n is not None and str(row.get('id','')).isdigit():chapters.append(chapter(n,site.root+'/chapter/'+str(row['id']),clean(row.get('title')),'ja'))
            return payload(site,title,url,sorted(chapters,key=lambda c:c['number']),[],aliases=[title,*re.split(r'\s*[;|]\s*',detail.get('alternative') or '')],cover=safe_link(detail.get('image'),url),truncated=len(rows)>1500)
        storage=detail.get('storageUrl','')
        for content in detail.get('content',[]):
            data=content.get('data');kind=content.get('type')
            if kind=='selfhosted' and isinstance(data,dict):
                first,last=data.get('from'),data.get('to');template=data.get('url')
                if not isinstance(first,int) or not isinstance(last,int) or not 0<=first<=last<=5000 or last-first>=500 or not isinstance(template,str):raise SourceError('Источник вернул некорректный список страниц.')
                pages.extend(storage+template.replace('{page}',str(i)) for i in range(first,last+1))
            elif kind in {'hotlink','external'} and isinstance(data,list):pages.extend((storage if kind=='external' else '')+v for v in data if isinstance(v,str))
        parent=detail.get('manga') or {};title=clean(parent.get('title') or detail.get('mangaTitle')) or 'Манга';n=number(detail.get('index'))
        if n is None:n=number(detail.get('title'))
        if n is not None:chapters=[chapter(n,url,clean(detail.get('title')),'ja')]
        return payload(site,title,url,chapters,[safe_link(v,url) for v in pages if v])
    if site.family=='toonkor':
        text,final,_=http.document(url);soup=BeautifulSoup(text,'html.parser');guard(soup)
        if site_for(final)!=site:raise SourceError('Источник сменил адрес. Адаптер требует проверки.')
        heading=soup.select_one('table.bt_view1 td.bt_title,.view-title,h1,h2,.toon-title') or soup.title;title=clean(heading.get_text(' ',strip=True)) if heading else 'Манхва'
        for cell in soup.select('table.web_list td.content__title[data-role]'):
            target=safe_link(cell.get('data-role'),final);label=clean(cell.get_text(' ',strip=True));n=number(label)
            if n is not None and site_for(target)==site:chapters.append(chapter(n,target,label,'ko'))
        match=re.search(r'''toon_img\s*=\s*['"]([A-Za-z0-9+/=\s]+)['"]''',text)
        if match:
            try:decoded=base64.b64decode(re.sub(r'\s','',match[1]),validate=True).decode('utf-8')
            except (ValueError,UnicodeError):raise SourceError('Источник изменил список изображений.') from None
            pages=[safe_link(i.get('src'),final) for i in BeautifulSoup(decoded,'html.parser').select('img[src]')]
            n=number(title)
            if n is not None:chapters=[chapter(n,final,title,'ko')]
        return payload(site,title,final,sorted(chapters,key=lambda c:c['number']),[p for p in pages if p])
    raise SourceError('Неизвестная читалка оригинальных глав.')
