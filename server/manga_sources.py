"""Multilingual manga and manhwa adapters. Public HTML and inline page data, never site API keys."""
import ast
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal,InvalidOperation
import json
import re
import threading
import time
from urllib.parse import urlencode,urljoin,urlsplit
from bs4 import BeautifulSoup
from source_parser import PublicHttp,SourceError,public_url
from title_identity import aliases,match_title

@dataclass(frozen=True)
class MangaSite:
    id:str
    name:str
    root:str
    family:str
    hosts:tuple=()
    languages:tuple=('ru',)
    format:str=''

SITES=(MangaSite('mangapoisk','MangaPoisk','https://mangapoisk.me','poisk',('mangapoisk.io','eropoisk.com')),
       MangaSite('mangahub','MangaHub','https://mangahub.ru','hub'),
       MangaSite('mangachan','MangaChan','https://im.manga-chan.me','chan',('manga-chan.me','mangachan.me')),
       MangaSite('readmanga','ReadManga','https://a.zazaza.me','grouple',('readmanga.live','readmanga.io','readmanga.me')),
       MangaSite('mintmanga','MintManga','https://mintmanga.live','grouple'),
       MangaSite('mangabuff','MangaBuff','https://mangabuff.ru','buff'),
       MangaSite('mangapill','MangaPill · EN','https://mangapill.com','pill',languages=('en',)),
       MangaSite('mangakatana','MangaKatana · EN','https://mangakatana.com','katana',languages=('en',)),
       MangaSite('mangadex','MangaDex','https://mangadex.org','dex',languages=('ru','en','ja','ko')),
       MangaSite('mangalib','MangaLib','https://mangalib.me','lib',('mangalib.org',)),
       MangaSite('senmanga','Sen Manga · JA','https://raw.senmanga.com','sen',languages=('ja',),format='manga'),
       MangaSite('mangaraw','MangaRaw · JA','https://mangaraw.co.uk','mangaraw',languages=('ja',),format='manga'),
       MangaSite('naver-webtoon','Naver Webtoon · KO','https://comic.naver.com/webtoon','naver',languages=('ko',),format='manhwa'),
       MangaSite('naver-best','Naver Best Challenge · KO','https://comic.naver.com/bestChallenge','naver',languages=('ko',),format='manhwa'),
       MangaSite('naver-challenge','Naver Challenge · KO','https://comic.naver.com/challenge','naver',languages=('ko',),format='manhwa'),
       MangaSite('toonkor','Toonkor · KO','https://toonkor7.org','toonkor',hosts=('toonkor0.org','toonkor2.org'),languages=('ko',),format='manhwa'),
       MangaSite('webtoons','WEBTOON · EN · Originals и Canvas','https://www.webtoons.com','webtoons',hosts=('webtoons.com','m.webtoons.com'),languages=('en',),format='webtoon'))
_cache={};_lock=threading.RLock()
def site_for(url):
    host=urlsplit(url).hostname
    return next((s for s in SITES if host in (urlsplit(s.root).hostname,*s.hosts) and (s.family!='naver' or urlsplit(url).path.startswith(urlsplit(s.root).path+'/'))),None)
def clean(value):return re.sub(r'\s+',' ',str(value or '')).strip()[:300]
def chapter_number(value):
    text=str(value).strip().replace(',','.')
    if not re.fullmatch(r'\d{1,4}(?:\.\d{1,3})?',text):raise SourceError('Номер главы должен быть от 0 до 9999; допускается дробная часть.')
    result=Decimal(text)
    return int(result) if result==int(result) else float(result)
def chapter_ranges(value):
    if str(value or 'all').strip().lower() in {'all','все',''}:return None
    result=[]
    for part in str(value).split(','):
        match=re.fullmatch(r'\s*(\d+(?:\.\d{1,3})?)(?:\s*-\s*(\d+(?:\.\d{1,3})?))?\s*',part)
        if not match:raise SourceError('Главы: all, 0, 12.5 или 1-20, 25.5.')
        first,last=chapter_number(match[1]),chapter_number(match[2] or match[1])
        if last<first:raise SourceError('Конец диапазона глав меньше начала.')
        result.append((first,last))
    return result
def selected(number,ranges):return ranges is None or any(a<=number<=b for a,b in ranges)
def safe_link(value,base):
    try:return public_url(urljoin(base,str(value or '')),resolve_dns=False) if value else ''
    except SourceError:return ''
def guard(soup):
    text=soup.get_text(' ',strip=True)
    if soup.select_one('form.purchase-form,.purchase-required,.paywall') or re.search(r'(?:для (?:просмотра|чтения|доступа).{0,70}(?:необходима авторизация|требуется премиум|требуется подписка)|глав[аы].{0,45}удален[аы] по требованию правообладателя)',text,re.I):
        raise SourceError('Глава требует вход, подписку или удалена правообладателем. Выбери другой открытый перевод.')
def title_aliases(value):
    value=re.sub(r'^Манга\s+','',clean(value),flags=re.I)
    return list(dict.fromkeys([value,*[clean(v) for v in re.split(r'\s/\s|\s\|\s|[()]',value) if len(clean(v))>1]]))
def parse_search(text,base,site):
    soup=BeautifulSoup(text,'html.parser');results=[]
    if site.family=='pill':
        for anchor in soup.select('a.mb-2[href^="/manga/"]')[:40]:
            card=anchor.parent.parent;heading=anchor.select_one('.font-black');other=anchor.select_one('.text-secondary')
            names=[clean((heading or anchor).get_text(' ',strip=True))]
            if other:names.extend(title_aliases(other.get_text(' ',strip=True)))
            image=card.select_one('img');year=re.search(r'\b(19\d\d|20\d\d)\b',card.get_text(' ',strip=True))
            results.append({'provider':site.id,'providerName':site.name,'title':names[0],'aliases':names,'url':safe_link(anchor.get('href'),base),'kind':'manga','language':'en','year':int(year[1]) if year else None,'cover':safe_link(image.get('data-src') or image.get('src'),base) if image else ''})
        return results
    selectors={'katana':('#book_list .item','h3.title a','h3.title a'),'poisk':('article.card,.manga-card','.card-title,h2.entry-title','a.card-about,a[href*="/manga/"]'),
               'hub':('.item-grid','a.fw-medium','a.fw-medium'),
               'chan':('.content_row','h2 a','h2 a'),
               'buff':('.cards__item','.cards__name','a[href*="/manga/"]'),
               'grouple':('.entity-card-tile,.tile','.entity-card-tile__title,h3,.title','a[href]')}
    cards,title_selector,anchor_selector=selectors[site.family]
    for card in soup.select(cards)[:50]:
        anchor=card if card.name=='a' else card.select_one(anchor_selector);heading=card.select_one(title_selector)
        if not anchor:continue
        names=title_aliases((heading or anchor).get_text(' ',strip=True));url=safe_link(anchor.get('href'),base)
        if not names or not url or site_for(url)!=site:continue
        image=card.select_one('img');year=re.search(r'(?:Год[:\s]*)(19\d\d|20\d\d)',card.get_text(' ',strip=True))
        results.append({'provider':site.id,'providerName':site.name,'title':names[0],'aliases':names,'url':url,'kind':'manga','language':'en' if site.family=='katana' else 'ru',
                        'year':int(year[1]) if year else None,'cover':safe_link(image.get('data-src') or image.get('src'),base) if image else ''})
    return list({v['url']:v for v in results}.values())
def search_url(site,query):
    if site.family=='katana':return site.root+'/?'+urlencode({'search':query,'search_by':'book_name'})
    if site.family=='chan':return site.root+'/?'+urlencode({'do':'search','subaction':'search','story':query})
    if site.family=='hub':return site.root+'/search/title?'+urlencode({'query':query})
    return site.root+'/search?'+urlencode({'q':query,**({'type':'manga'} if site.family=='buff' else {})})
def normalized_format(value):
    value=str(value or '').lower().replace('-','_')
    return {'манга':'manga','манхва':'manhwa','маньхуа':'manhua','вебтун':'webtoon','web_manga':'manga','long_strip':'webtoon'}.get(value,value)

def search_title(title,language='auto',format='all'):
    if language not in {'auto','all','ru','en','ja','ko'}:raise SourceError('Выбери русский, английский, японский или корейский язык источника.')
    if format not in {'all','manga','manhwa','manhua','webtoon'}:raise SourceError('Выбери доступный формат комикса.')
    if not isinstance(title,dict) or title.get('kind')!='manga' or not aliases(title):raise SourceError('Выбери конкретную мангу из каталога.')
    if len(json.dumps(title).encode())>50000:raise SourceError('Описание выбранной манги слишком велико.')
    key=json.dumps([2,language,format,title.get('ids'),aliases(title),title.get('year')],sort_keys=True,ensure_ascii=False)
    with _lock:hit=_cache.get(key)
    if hit and hit[0]>time.monotonic():return hit[1]
    search_deadline=time.monotonic()+18
    def work(site):
        http=PublicHttp(timeout=(3,6),deadline=search_deadline);results=[];message='Точное совпадение не найдено.';status='empty'
        try:
            queries=[q for q in aliases(title) if re.search('[a-z]',q,re.I) and not re.search('[а-яё]',q,re.I)] if site.family in {'pill','katana','webtoons'} else aliases(title)
            if site.languages==('ja',):queries=sorted(aliases(title),key=lambda q:not bool(re.search(r'[\u3040-\u30ff\u3400-\u9fff]',q)))
            if site.languages==('ko',):queries=sorted(aliases(title),key=lambda q:not bool(re.search(r'[\uac00-\ud7af]',q)))
            for query in queries[:2]:
                if site.family in {'dex','lib'}:
                    from manga_catalog_adapters import dex_search,lib_search
                    candidates=dex_search(query,language,http) if site.family=='dex' else lib_search(query,http)
                elif site.family=='webtoons':
                    from manga_webtoons import search
                    candidates=search(query,site,http)
                elif site.family in {'naver','mangaraw','sen','toonkor'}:
                    from manga_raw_adapters import search
                    candidates=search(query,site,http)
                else:
                    text,final,_=http.document(search_url(site,query))
                    if site_for(final)!=site:raise SourceError('Источник перенаправил поиск на другой сайт.')
                    candidates=parse_search(text,final,site)
                for value in candidates:
                    accepted,evidence=match_title(title,value)
                    if accepted:
                        if site.family=='dex':
                            from manga_catalog_adapters import dex_available
                            if not dex_available(value['url'],http):continue
                        source_format=normalized_format(value.get('format') or title.get('format') or site.format)
                        if format!='all' and source_format and source_format!=format and not (format=='webtoon' and value.get('readingMode')=='scroll' or format=='manhwa' and source_format=='webtoon' and normalized_format(title.get('format'))=='manhwa'):continue
                        results.append({**value,'format':source_format,'matchEvidence':evidence})
                if results:break
            status='ok' if results else 'empty'
            if results:message='Найдено точных совпадений: '+str(len(results))
        except SourceError as error:status='unavailable';message=str(error)
        except (ValueError,TypeError,KeyError,AttributeError):status='unavailable';message='Формат читалки изменился; адаптер требует проверки.'
        finally:http.close()
        return {'provider':site.id,'name':site.name,'status':status,'message':message,'results':results}
    # Current GroupLe search is JS/API-only; its HTML reader remains available
    # for direct links. Do not misrepresent an empty HTML search as a working API.
    sites=[s for s in SITES if s.family!='grouple' and (language=='all' or (language if language!='auto' else 'ru') in s.languages) and (format not in {'manhwa','manhua','webtoon'} or not s.format or s.format==format or format=='webtoon' and s.format=='manhwa' or format=='manhwa' and s.format=='webtoon')]
    with ThreadPoolExecutor(max_workers=min(12,len(sites) or 1)) as pool:providers=list(pool.map(work,sites))
    if language=='auto' and not any(p['results'] for p in providers):
        with ThreadPoolExecutor(max_workers=3) as pool:providers.extend(pool.map(work,[s for s in SITES if s.family in {'pill','katana','webtoons'}]))
    result={'results':list({v['url']:v for p in providers for v in p['results']}.values()),'providers':[{k:p[k] for k in ('provider','name','status','message')} for p in providers],'language':language,'format':format,'checkedAt':int(time.time())}
    with _lock:
        if len(_cache)>80:_cache.clear()
        _cache[key]=(time.monotonic()+120,result)
    return result

def parse_chapters(text,base):
    soup=BeautifulSoup(text,'html.parser');guard(soup);chapters=[]
    for anchor in soup.select('a.chapter-link,a.chapters__item,.chapter-item a,.detail-item div.align-items-center > a,.table_cha a,.chapters a,.chapter-link a,a[href^="/chapters/"]'):
        row=anchor.find_parent('tr') or anchor.find_parent(class_='chapter-item') or anchor
        label=clean(anchor.get_text(' ',strip=True));number=re.search(r'(?:глава|часть|chapter)\s*(\d+(?:[.,]\d{1,3})?)',label,re.I)
        data=row.select_one('[data-num]') if row.name!='td' else row
        if not number and data and data.get('data-num','').isdigit():value=chapter_number(str(Decimal(data['data-num'])/10))
        elif number:value=chapter_number(number[1])
        else:continue
        target=safe_link(anchor.get('href'),base)
        if not target or urlsplit(target).hostname!=urlsplit(base).hostname:continue
        volume=re.search(r'(?:том|volume|vol\.?)[\s:]*([1-9]\d{0,2})',label+' '+urlsplit(target).path,re.I)
        team=clean(anchor.get('data-translator') or anchor.get('title'))
        chapters.append({'number':value,'season':int(volume[1]) if volume else 1,'url':target,'title':label,'translator':team,'language':'ru'})
    return sorted({c['url']:c for c in chapters}.values(),key=lambda c:(c['season'],c['number'],c['translator']))

def parse_pages(text,base):
    soup=BeautifulSoup(text,'html.parser');guard(soup);pages=[]
    if urlsplit(base).hostname=='mangakatana.com':
        match=re.search(r'var\s+thzq\s*=\s*(\[[^;]+\])',text)
        if match:
            try:pages.extend(ast.literal_eval(match[1]))
            except (ValueError,SyntaxError):pass
    # MultiChan publishes a JSON image list, sometimes with a trailing comma.
    full=re.search(r'["\']fullimg["\']\s*:\s*(\[[\s\S]*?\])',text)
    if full:
        try:pages.extend(v for v in json.loads(re.sub(r',\s*]',']',full[1])) if isinstance(v,str))
        except (ValueError,TypeError):pass
    # GroupLe tuples are plain strings. No JavaScript, tokens or login state is executed.
    for script in soup.select('script'):
        source=script.string or script.get_text()
        mark=re.search(r'rm_h\.(init|readerInit|readerDoInit)\s*\(',source)
        if not mark:continue
        for row in re.findall(r'\[\s*((?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*,\s*(?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*,\s*(?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'))',source[mark.end():]):
            try:host,middle,end=[p.replace('\\/','/') for p in ast.literal_eval('['+row+']')]
            except (SyntaxError,ValueError):continue
            if mark[1]=='init' and host.startswith('https://'):value=host+middle+end
            elif not middle and end.startswith('/static/'):value=urljoin(base,end)
            elif middle.endswith('/manga/'):value=host+end
            else:value=middle+host+end
            pages.append('https:'+value if value.startswith('//') else value)
    if not pages:
        for image in soup.select('img.js-page,img.page-image,img.reader-viewer-img,.reader__pages img,.reader-page img,.manga-pages img,img[data-page],#mangaPicture'):
            pages.append(image.get('data-src') or image.get('data-original') or image.get('src'))
    result=list(dict.fromkeys(safe_link(p,base) for p in pages if p))
    return [p for p in result if p and not re.search(r'(?:placeholder|no-image|premium|blocked|not.?found)',urlsplit(p).path,re.I)]

def inspect(url,http=None):
    own=http is None;http=http or PublicHttp(timeout=(3,7),deadline=time.monotonic()+32)
    try:
        initial=site_for(url)
        if initial and initial.family=='webtoons':
            from manga_webtoons import inspect as inspect_webtoons
            try:return inspect_webtoons(url,initial,http)
            except (ValueError,TypeError,KeyError,AttributeError):raise SourceError('WEBTOON изменил формат данных. Адаптер требует проверки.') from None
        if initial and initial.family in {'naver','mangaraw','sen','toonkor'}:
            from manga_raw_adapters import inspect as inspect_raw
            try:return inspect_raw(url,initial,http)
            except (ValueError,TypeError,KeyError,AttributeError):raise SourceError('Читалка изменила формат данных. Адаптер требует проверки.') from None
        if initial and initial.family in {'dex','lib'}:
            from manga_catalog_adapters import inspect_catalog
            return inspect_catalog(url,http)
        text,final,_=http.document(public_url(url,resolve_dns=False));soup=BeautifulSoup(text,'html.parser');guard(soup);site=site_for(final)
        if not site:raise SourceError('Для этой читалки пока нет проверенного адаптера.')
        heading=soup.select_one('.cr-hero-names__main,.detail-panel h1,h1,.card header .text-base span,meta[itemprop=name]')
        title=clean(heading.get('content') or heading.get_text(' ',strip=True)) if heading else clean(soup.title.get_text().split(' — ')[0] if soup.title else '')
        chapters=parse_chapters(text,final);pages=parse_pages(text,final)
        extra=[]
        if not chapters and not pages and site.family=='poisk' and re.fullmatch(r'/manga/[^/]+/?',urlsplit(final).path):extra=[final.rstrip('/')+'/chaptersList']
        if not chapters and not pages and site.family=='hub' and re.fullmatch(r'/title/[^/]+/?',urlsplit(final).path):extra=[final.rstrip('/')+'/chapters']
        seen=set();truncated=False
        while extra and len(seen)<25 and len(chapters)<1500:
            target=extra.pop(0)
            if target in seen:continue
            seen.add(target);html,target,_=http.document(target);chapters.extend(parse_chapters(html,target));part=BeautifulSoup(html,'html.parser')
            for a in part.select('a[rel=next],ul.pagination a[href],.pagination .page-item a[href]'):
                link=safe_link(a.get('href'),target)
                if link and urlsplit(link).hostname==urlsplit(final).hostname and urlsplit(link).path==urlsplit(target).path and link not in seen and link not in extra:extra.append(link)
        truncated=bool(extra)
        if pages and not chapters:
            labels=' '.join(node.get_text(' ',strip=True) for node in soup.select('h1,title,.reader-title,.reading-title,.detail-header'))
            match=re.search(r'(?:глава|chapter)\s*(\d+(?:\.\d+)?)',labels,re.I)
            path=re.search(r'/chapter/(\d+)-(\d+(?:\.\d+)?)',urlsplit(final).path)
            number=chapter_number(match[1]) if match else chapter_number(path[2]) if path else 1
            volume=re.search(r'Том\s*(\d+)',labels,re.I)
            season=int(volume[1]) if volume else int(path[1]) if path else 1
            chapters=[{'number':number,'season':max(1,season),'url':final,'title':'Глава '+str(number),'language':'ru','translator':''}]
        language='en' if site.family in {'pill','katana'} else 'ru'
        for chapter in chapters:chapter['language']=language
        chapters=sorted({c['url']:c for c in chapters}.values(),key=lambda c:(c['season'],c['number'],c['translator']))
        return {'provider':site.id,'providerName':site.name,'title':title,'url':final,'kind':'manga','language':language,'episodes':chapters,'pages':pages,
                'seasons':[{'number':n,'name':'Том '+str(n)} for n in sorted({c['season'] for c in chapters})],'dubs':[],'releases':[],
                'truncated':truncated,'available':bool(chapters),'translations':sorted({c['translator'] for c in chapters if c['translator']})}
    finally:
        if own:http.close()
