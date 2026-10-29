"""Public NovelCool RU HTML reader. No script execution or account data."""
import re,time
from urllib.parse import urlsplit,urljoin
from bs4 import BeautifulSoup
from source_parser import SourceError,public_url

HOST='ru.novelcool.com'

def document(url,http):
    from manga_sources import guard
    from source_relay import relay,document as device_document
    if relay.available():
        deadline=getattr(http,'deadline',None)
        timeout=min(28,deadline-time.monotonic()) if isinstance(deadline,(int,float)) else 28
        if timeout<=0:raise SourceError('Источник не уложился во время проверки. Повтори запрос.')
        text,final,_=device_document(url,timeout=timeout)
    else:text,final,_=http.document(url)
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
    if identity:
        from source_relay import relay,chapter as device_chapter
        if relay.available():
            deadline=getattr(http,'deadline',None);timeout=min(28,deadline-time.monotonic()) if isinstance(deadline,(int,float)) else 28
            if timeout<=0:raise SourceError('Источник не уложился во время проверки.')
            return device_chapter(url,timeout=timeout)
    # This ten-image mode is linked by the site's own reader controls.
    if identity:url=url.rstrip('/').rsplit('/',1)[0]+'/'+identity+'-10-1.html'
    text,final,soup=document(url,http);entries=chapters(soup,final);pages=[]
    if identity:
        book=next((a for a in soup.select('a[href]') if re.fullmatch(r'/novel/[^/]+\.html',urlsplit(urljoin(final,a.get('href',''))).path) and urlsplit(urljoin(final,a['href'])).hostname==HOST),None)
        title=clean(book.get_text(' ',strip=True)) if book else ''
        entries=[row for row in entries if chapter_id(row['url'])==identity]
        if not entries:raise SourceError('NovelCool не подтвердил номер выбранной главы.')
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
            text,final,soup=document(next_url,http)
            if chapter_id(final)!=identity:raise SourceError('NovelCool подменил выбранную главу.')
        else:raise SourceError('NovelCool превысил лимит страниц навигации.')
        if not pages:raise SourceError('В этой главе NovelCool нет изображений манги.')
    else:
        heading=soup.select_one('h1.bookinfo-title');title=clean(heading.get_text(' ',strip=True)) if heading else ''
    if not title:raise SourceError('NovelCool не подтвердил название манги.')
    return {'provider':'novelcool-ru','providerName':'NovelCool','title':title,'aliases':[title],'url':url,'kind':'manga','language':'ru','episodes':entries,'pages':pages,
            'seasons':[{'number':n,'name':'Том '+str(n)} for n in sorted({e['season'] for e in entries})],'translations':[],'dubs':[],'releases':[],'available':bool(entries),'truncated':False}
