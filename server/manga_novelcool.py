"""Public NovelCool RU HTML reader. No script execution or account data."""
import re,time,threading,unicodedata
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit,urljoin,unquote,quote
from bs4 import BeautifulSoup
from source_parser import SourceError,public_url

HOST='ru.novelcool.com'
_books={};_book_lock=threading.Lock()

def document(url,http):
    from manga_sources import guard
    text,final,_=http.document(url)
    if urlsplit(final).hostname!=HOST:raise SourceError('NovelCool перенаправил чтение на другой сайт.')
    soup=BeautifulSoup(text,'html.parser');guard(soup)
    heading=soup.title.get_text(' ',strip=True) if soup.title else ''
    if re.fullmatch(r'404(?:\s+not\s+found)?',heading,re.I):
        raise SourceError('NovelCool вернул серверу страницу «404 Not Found» вместо манги. Адрес виден в поиске, но этот ответ не содержит глав. Повтори подключение позже.')
    return text,final,soup


def chapter_id(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!=HOST or parsed.query or parsed.fragment:return None
    match=re.fullmatch(r'/chapter/[^/]+/(\d+)(?:-\d+(?:-\d+)?)?(?:\.html|/)',parsed.path)
    return match[1] if match else None

def canonical_book(url):
    parsed=urlsplit(public_url(url,resolve_dns=False))
    if parsed.hostname!=HOST or parsed.query or not re.fullmatch(r'/novel/[^/]+\.html',parsed.path):raise SourceError('NovelCool вернул другой адрес произведения.')
    return unicodedata.normalize('NFC',unquote(parsed.path)).casefold()

def locked(value):return value not in (None,False,0,'0','false','')

def api_book(identity,http):
    from novelcool_client import request
    info=request('book/info',{'book_id':identity},http).get('info')
    if not isinstance(info,dict) or str(info.get('id'))!=identity or info.get('lang')!='ru' or not isinstance(info.get('name'),str) or not info['name'].strip():raise SourceError('API NovelCool не подтвердил произведение и язык.')
    canonical_book(info.get('url',''))
    if locked(info.get('copyright_limit')) or locked(info.get('is_novel')) or info.get('show_it','ALLOW')!='ALLOW':raise SourceError('NovelCool ограничил доступ к этому произведению.')
    return info

def api_entry(row,identity):
    from manga_sources import clean,chapter_number
    if not isinstance(row,dict) or str(row.get('book_id'))!=identity or row.get('lang')!='ru' or locked(row.get('is_locked')):return None
    identifier=str(row.get('id',''));label=clean(row.get('title',''))
    if not re.fullmatch(r'[1-9]\d{0,12}',identifier) or not label:return None
    match=re.match(r'(\d+)\s*[-–]\s*(\d+(?:[.,]\d{1,3})?)(?:\s|$)',label)
    try:
        number=chapter_number(match[2] if match else row.get('order_id',''))
        volume=int(match[1]) if match else int(re.match(r'\d+',label)[0]) if re.match(r'\d+',label) else 1
    except (SourceError,ValueError):return None
    return {'number':number,'season':max(1,volume),'title':label,'url':'https://'+HOST+'/chapter/'+quote(label,safe='')+'/'+identifier+'/','translator':clean(row.get('group_name','')),'language':'ru'}

def inspect_api(url,http):
    from novelcool_client import request
    from manga_sources import clean
    identifier=chapter_id(url)
    if identifier:
        chapter=request('chapter/info',{'chapter_id':identifier},http).get('info')
        if not isinstance(chapter,dict) or str(chapter.get('id'))!=identifier or chapter.get('lang')!='ru' or chapter_id(chapter.get('url',''))!=identifier:raise SourceError('API NovelCool вернул другую главу или язык.')
        if locked(chapter.get('is_locked')):raise SourceError('NovelCool ограничил доступ к этой главе.')
        book_id=str(chapter.get('book_id',''));book=api_book(book_id,http);entry=api_entry(chapter,book_id)
        if not entry:raise SourceError('NovelCool не подтвердил номер выбранной главы.')
        entries=[entry];pictures=chapter.get('pic_list');pages=[]
        if not isinstance(pictures,list) or not 1<=len(pictures)<=500:raise SourceError('В главе нет страниц или превышен лимит 500 страниц.')
        order=[]
        for picture in pictures:
            if not isinstance(picture,dict) or not re.fullmatch(r'\d{1,5}',str(picture.get('order_id',''))):raise SourceError('NovelCool вернул некорректный порядок страниц.')
            page=public_url(picture.get('pic_path',''),resolve_dns=False);parsed=urlsplit(page)
            if not parsed.hostname.endswith('.movietop.cc') or not parsed.path.startswith('/comics/'):raise SourceError('NovelCool вернул неподдерживаемый адрес страницы.')
            order.append((int(picture['order_id']),page))
        if len({index for index,_ in order})!=len(order):raise SourceError('NovelCool повторил номер страницы.')
        pages=[page for _,page in sorted(order)]
    else:
        canonical=canonical_book(url)
        with _book_lock:cached=_books.get(canonical)
        book_id=cached[0] if cached and cached[1]>time.monotonic() else None
        if not book_id:
            keyword=unquote(urlsplit(url).path.rsplit('/',1)[1][:-5]).replace('_',' ').replace('-',' ').strip()
            for page in range(1,4):
                rows=request('book/search',{'keyword':keyword,'page':page},http).get('list')
                if not isinstance(rows,list):raise SourceError('NovelCool не вернул список поиска.')
                matches=[]
                for row in rows:
                    if not isinstance(row,dict) or row.get('lang')!='ru':continue
                    try:same=canonical_book(row.get('url',''))==canonical
                    except SourceError:same=False
                    if same:matches.append(str(row.get('id','')))
                if len(set(matches))>1:raise SourceError('NovelCool неоднозначно определил произведение.')
                if matches:book_id=matches[0];break
                if len(rows)<100:break
            if not book_id:raise SourceError('NovelCool не нашёл точный адрес выбранного произведения.')
        book=api_book(book_id,http)
        if canonical_book(book['url'])!=canonical:raise SourceError('API NovelCool подменил произведение.')
        with _book_lock:
            if len(_books)>=128:_books.clear()
            _books[canonical]=(book_id,time.monotonic()+3600)
        rows=request('chapter/book_list',{'book_id':book_id},http).get('list')
        if not isinstance(rows,list) or len(rows)>10000:raise SourceError('NovelCool вернул некорректный список глав.')
        entries=[entry for row in rows if (entry:=api_entry(row,book_id))]
        entries=list({chapter_id(entry['url']):entry for entry in entries}.values());entries.sort(key=lambda e:(e['season'],e['number']));pages=[]
    title=clean(book['name'])
    return {'provider':'novelcool-ru','providerName':'NovelCool','title':title,'aliases':[title],'url':url,'kind':'manga','language':'ru','year':book.get('publish_year'),'episodes':entries,'pages':pages,
            'seasons':[{'number':n,'name':'Том '+str(n)} for n in sorted({e['season'] for e in entries})],'translations':[],'dubs':[],'releases':[],'available':bool(entries),'truncated':False}


def chapters(soup,base):
    from manga_sources import clean,chapter_number
    values={}
    for anchor in soup.select('.chp-item > a[href],select option[value]'):
        target=anchor.get('href') or anchor.get('value')
        joined=urljoin(base,target) if target else ''
        if not chapter_id(joined):continue
        url=public_url(joined,resolve_dns=False)
        label=clean(anchor.get('title') or anchor.get_text(' ',strip=True))
        match=re.match(r'(\d+)\s*[-–]\s*(\d+(?:[.,]\d{1,3})?)(?:\s|$)',label)
        if not match:continue
        volume,number=int(match[1]),chapter_number(match[2])
        values[chapter_id(url)]={'number':number,'season':max(1,volume),'title':label,'url':url,'translator':'','language':'ru'}
    return sorted(values.values(),key=lambda row:(row['season'],row['number']))


def inspect(url,http):
    from manga_sources import clean
    initial=urlsplit(url);identity=chapter_id(url)
    if initial.scheme!='https' or initial.hostname!=HOST or initial.query or initial.fragment or not (identity or re.fullmatch(r'/novel/[^/]+\.html',initial.path)):
        raise SourceError('Нужна публичная ссылка NovelCool RU на мангу или главу.')
    from novelcool_client import settings
    if settings():return inspect_api(url,http)
    # This ten-image mode is linked by the site's own reader controls.
    if identity:url=url.rstrip('/').rsplit('/',1)[0]+'/'+identity+'-10-1.html'
    text,final,soup=document(url,http);entries=chapters(soup,final);pages=[]
    if identity:
        book=next((a for a in soup.select('a[href]') if re.fullmatch(r'/novel/[^/]+\.html',urlsplit(urljoin(final,a.get('href',''))).path) and urlsplit(urljoin(final,a['href'])).hostname==HOST),None)
        title=clean(book.get_text(' ',strip=True)) if book else ''
        entries=[row for row in entries if chapter_id(row['url'])==identity]
        if not entries:raise SourceError('NovelCool не подтвердил номер выбранной главы.')
        # The reader advertises every pagination URL. Fetch these independently
        # in a bounded pool instead of six sequential HTML round trips for a
        # long chapter. Keep next_page traversal as the source of page order.
        advertised=[];prefetched={}
        for option in soup.select('select.sl-page option[value]'):
            target=urljoin(final,option['value'])
            if chapter_id(target)==identity and target!=final and target not in advertised:advertised.append(target)
        if len(advertised)>49:raise SourceError('NovelCool превысил лимит страниц навигации.')
        if advertised and hasattr(http,'fork'):
            def fetch(target):
                client=http.fork()
                try:return target,document(target,client)
                finally:client.close()
            with ThreadPoolExecutor(max_workers=3) as pool:prefetched=dict(pool.map(fetch,advertised))
        seen=set()
        for _ in range(50):
            seen.add(final)
            for img in soup.select('img.mangaread-manga-pic,img.manga_pic'):
                value=img.get('data-src') or img.get('src')
                if value:
                    page=public_url(urljoin(final,value),resolve_dns=False)
                    if page not in pages:pages.append(page)
            if len(pages)>500:raise SourceError('Глава NovelCool превышает лимит 500 страниц.')
            match=re.search(r'\bnext_page\s*=\s*["\']([^"\']+)["\']',text)
            next_url=urljoin(final,match[1]) if match else ''
            if not next_url or next_url in seen:break
            if urlsplit(next_url).hostname!=HOST:raise SourceError('NovelCool передал страницу другого сайта.')
            if chapter_id(next_url)!=identity:break # next chapter is not a page
            text,final,soup=prefetched.pop(next_url) if next_url in prefetched else document(next_url,http)
            if chapter_id(final)!=identity:raise SourceError('NovelCool подменил выбранную главу.')
        else:raise SourceError('NovelCool превысил лимит страниц навигации.')
        if not pages:raise SourceError('В этой главе NovelCool нет изображений манги.')
    else:
        heading=soup.select_one('h1.bookinfo-title');title=clean(heading.get_text(' ',strip=True)) if heading else ''
    if not title:raise SourceError('NovelCool не подтвердил название манги.')
    return {'provider':'novelcool-ru','providerName':'NovelCool','title':title,'aliases':[title],'url':url,'kind':'manga','language':'ru','episodes':entries,'pages':pages,
            'seasons':[{'number':n,'name':'Том '+str(n)} for n in sorted({e['season'] for e in entries})],'translations':[],'dubs':[],'releases':[],'available':bool(entries),'truncated':False}
