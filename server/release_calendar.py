"""Only source-published dates. An original air date is never a dub release date."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.utils import parsedate_to_datetime
import re
import threading
import time
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from site_adapters import SITES
from source_parser import PublicHttp, episode_number

_cache=None;_lock=threading.Lock()


def published_date(value):
    try:
        date=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except ValueError:
        try:date=parsedate_to_datetime(str(value))
        except (ValueError,TypeError):return None
    return date.isoformat()


def parse_announcements(text,base,provider):
    soup=BeautifulSoup(text,'html.parser');events=[]
    for element in soup.select('time[datetime], [data-release-date], [itemprop="datePublished"][content]')[:100]:
        value=element.get('datetime') or element.get('data-release-date') or element.get('content')
        date=published_date(value)
        if not date:continue
        parent=element.find_parent(['article','li']) or element.parent
        title_node=parent.select_one('h1,h2,h3,.title,.movie-item__title')
        title=title_node.get_text(' ',strip=True) if title_node else parent.get_text(' ',strip=True)
        anchor=parent.select_one('a[href]');url=urljoin(base,anchor.get('href')) if anchor else base
        if urlsplit(url).hostname!=urlsplit(base).hostname:continue
        label=title[:240]
        if not label:continue
        events.append({'title':label,'label':label,'date':date,'url':url,'provider':provider,
                       'episode':episode_number(label),'kind':'translation','datePrecision':'time' if 'T' in str(value) else 'day'})
    # RSS is read as data; entities/DOCTYPE are rejected, no external XML resources.
    if '<rss' in text[:1000] and '<!DOCTYPE' not in text.upper() and '<!ENTITY' not in text.upper():
        import xml.etree.ElementTree as ET
        try:
            for item in ET.fromstring(text).findall('.//item')[:100]:
                date=published_date(item.findtext('pubDate'))
                title=item.findtext('title') or '';url=item.findtext('link') or base
                if date and title and urlsplit(url).hostname==urlsplit(base).hostname:
                    events.append({'title':title[:240],'label':title[:240],'date':date,'url':url,'provider':provider,'episode':episode_number(title),'kind':'translation','datePrecision':'time'})
        except ET.ParseError:pass
    return list({(e['provider'],e['url'],e['date'],e['title']):e for e in events}.values())


def calendar():
    global _cache
    with _lock:
        if _cache and _cache[0]>time.monotonic():return _cache[1]
    def work(site):
        http=PublicHttp(timeout=(2,4),deadline=time.monotonic()+7)
        try:
            text,final,_=http.document(site.root)
            events=parse_announcements(text,final,site.name)
            if not events:
                feed=BeautifulSoup(text,'html.parser').select_one('link[type="application/rss+xml"][href]')
                if feed:
                    url=urljoin(final,feed['href'])
                    if urlsplit(url).hostname in site.hosts:
                        text,final,_=http.document(url);events=parse_announcements(text,final,site.name)
            return events,{'name':site.name,'status':'ok' if events else 'no_dates'}
        except Exception:return [],{'name':site.name,'status':'unavailable'}
        finally:http.close()
    with ThreadPoolExecutor(max_workers=6) as pool:values=list(pool.map(work,[s for s in SITES if s.kind=='anime' and s.id not in {'sovet','anilibriafun','animevosttv'}]))
    result={'events':sorted([e for v,_ in values for e in v],key=lambda e:e['date'],reverse=True)[:150], 'providers':[p for _,p in values],'checkedAt':int(time.time())}
    with _lock:_cache=(time.monotonic()+300,result)
    return result
