"""HentaiChan HTML adapter, adapted from otaku-melons/HentaiChanParser.

Copyright (c) 2022-2024 DUB1401. Apache-2.0; see licenses/hentaichan-parser.txt.
MediaVault changes: bounded requests, current mirror, lazy chapter readers,
strict public URLs and image-list parsing without executing JavaScript.
Upstream: 92d80387f6a24fd48c6be0097bbd2d1450353751.
"""
import ast
import json
import re
from urllib.parse import urljoin,urlsplit,urlencode
from bs4 import BeautifulSoup
from source_parser import SourceError,public_url

HOSTS={'hentaichan.live','x17.h-chan.me'}
ROOT='https://x17.h-chan.me'
SOURCE={'id':'990000000000000001','name':'HentaiChan','lang':'ru','baseUrl':ROOT,'isNsfw':True}
ITEM=re.compile(r'^/(manga|online|related)/([1-9]\d{0,11}-[^/?]{1,250})\.html$')


def clean(value):return re.sub(r'\s+',' ',str(value or '')).strip()[:500]


def link(value,base):
    target=public_url(urljoin(base,value),resolve_dns=False)
    if urlsplit(target).hostname not in HOSTS or not ITEM.fullmatch(urlsplit(target).path):
        raise SourceError('HentaiChan вернул ссылку вне поддерживаемой читалки.')
    return target


def document(url,http):
    text,final,_=http.document(public_url(url,resolve_dns=False))
    if urlsplit(final).hostname not in HOSTS:
        raise SourceError('HentaiChan перенаправил запрос на неизвестный сайт.')
    from manga_sources import guard
    soup=BeautifulSoup(text,'html.parser');guard(soup)
    return text,final,soup


def parse_search(text,base):
    soup=BeautifulSoup(text,'html.parser');result={}
    for card in soup.select('.content_row')[:50]:
        a=card.select_one('a.title_link,h2 a[href]')
        if not a:continue
        try:url=link(a.get('href',''),base)
        except SourceError:continue
        if ITEM.fullmatch(urlsplit(url).path)[1]!='manga':continue
        title=clean(a.get_text(' ',strip=True))
        if not title:continue
        image=card.select_one('.manga_images img,img');cover=''
        if image:
            try:cover=public_url(urljoin(base,image.get('data-src') or image.get('src') or ''),resolve_dns=False)
            except SourceError:pass
        from manga_sources import title_aliases
        slug=ITEM.fullmatch(urlsplit(url).path)[2]
        result[url]={'id':'hentaichan:'+slug.split('-')[0],'provider':'hentaichan','providerName':'HentaiChan',
                     'sourceId':SOURCE['id'],'sourceOnly':True,'sourceUrl':url,'sourceURL':url,'url':url,
                     'title':title,'aliases':title_aliases(title),'kind':'manga','format':'manga','language':'ru',
                     'adult':True,'age':18,'cover':cover,'ids':{},'genres':[],'tags':[]}
    return list(result.values())


def search(query,http):
    query=clean(query)[:160]
    if len(query)<2:return []
    text,final,_=document(ROOT+'/?'+urlencode({'do':'search','subaction':'search','story':query}),http)
    return parse_search(text,final)


def number(label):
    patterns=[r'(?:глава|часть|chapter|ch\.)\s*([0-9]+(?:[.,][0-9]{1,3})?)',
              r'([0-9]+(?:[.,][0-9]{1,3})?)\s*(?:глава|часть|chapter)']
    from manga_sources import chapter_number
    for pattern in patterns:
        match=re.search(pattern,label,re.I)
        if match:return chapter_number(match[1])
    return None


def chapter(url,label,translator=''):
    parsed=urlsplit(link(url,url));slug=ITEM.fullmatch(parsed.path)[2]
    volume=re.search(r'(?:том|volume|vol\.)\s*(\d{1,3})',label,re.I)
    return {'number':number(label),'season':max(1,int(volume[1])) if volume else 1,
            'title':clean(label),'url':f'https://{parsed.hostname}/online/{slug}.html?page=1',
            'translator':clean(translator),'language':'ru'}


def parse_pages(text,base):
    # The source publishes fullimg, not thumbnails. Treat it as data, never eval JS.
    found=re.search(r'["\']fullimg["\']\s*:\s*(\[[\s\S]*?\])',text)
    if not found:return []
    raw=found[1].replace('\\/','/')
    try:values=json.loads(re.sub(r',\s*]',']',raw))
    except ValueError:
        try:values=ast.literal_eval(raw)
        except (ValueError,SyntaxError):raise SourceError('HentaiChan изменил список страниц.') from None
    if not isinstance(values,list) or len(values)>500:raise SourceError('Недопустимый список страниц HentaiChan.')
    result=[]
    for value in values:
        if not isinstance(value,str):raise SourceError('HentaiChan вернул неверный адрес страницы.')
        target=public_url(urljoin(base,value),resolve_dns=False)
        if not re.search(r'\.(?:jpe?g|png|webp|gif|avif)$',urlsplit(target).path,re.I):
            raise SourceError('HentaiChan вернул видео или неподдерживаемый формат вместо страницы.')
        if target not in result:result.append(target)
    return result


def inspect(url,http):
    url=link(url,url);part=ITEM.fullmatch(urlsplit(url).path)
    slug=part[2]
    if part[1]=='related':url=url.replace('/related/','/manga/',1)
    text,final,soup=document(url,http)
    heading=soup.select_one('a.title_top_a,h1,.reader-title')
    if not heading and re.search(r'здесь ничего нет|ошибочная ссылка|404.{0,20}not found',soup.get_text(' ',strip=True),re.I):
        raise SourceError('HentaiChan не нашёл эту главу.')
    title=clean(heading.get_text(' ',strip=True)) if heading else clean(soup.title.get_text(' ',strip=True)) if soup.title else 'HentaiChan'
    team=soup.select_one('.translation a');team=clean(team.get_text(' ',strip=True)) if team else ''
    current=chapter(final,title,team)
    pages=parse_pages(text,final) if part[1]=='online' else []
    chapters=[];truncated=False
    if part[1]=='online':
        if not pages:raise SourceError('HentaiChan не предоставил изображения этой главы.')
        current['number']=current['number'] if current['number'] is not None else 1
        chapters=[current]
    else:
        pending=[f'https://{urlsplit(final).hostname}/related/{slug}.html'];seen=set()
        while pending and len(seen)<25:
            target=pending.pop(0)
            if target in seen:continue
            seen.add(target);_,related,part_soup=document(target,http)
            headings=part_soup.get_text(' ',strip=True)
            if re.search(r'Хентай похожий на|Похожая манга',headings,re.I):break
            for card in part_soup.select('.related_info'):
                a=card.select_one('h2 a[href],a.title_link[href]')
                if not a:continue
                try:
                    t=card.select_one('.translation a');entry=chapter(link(a['href'],related),a.get_text(' ',strip=True),t.get_text(' ',strip=True) if t else '')
                except SourceError:continue
                if entry['number'] is not None:chapters.append(entry)
            for a in part_soup.select('a[href*="offset="]'):
                candidate=urljoin(related,a['href']);p=urlsplit(candidate)
                if p.hostname in HOSTS and p.path==urlsplit(related).path and re.fullmatch(r'offset=\d{1,5}',p.query) and candidate not in seen and candidate not in pending:pending.append(candidate)
        truncated=bool(pending)
        if not chapters:
            current['number']=current['number'] if current['number'] is not None else 1
            chapters=[current]
    chapters=sorted({c['url']:c for c in chapters}.values(),key=lambda c:(c['season'],c['number'],c['translator']))
    cover=soup.select_one('img#cover');cover_url=''
    if cover:
        try:cover_url=public_url(urljoin(final,cover.get('src') or ''),resolve_dns=False)
        except SourceError:pass
    return {'provider':'hentaichan','providerName':'HentaiChan','title':title,'url':final,'kind':'manga','language':'ru',
            'adult':True,'age':18,'cover':cover_url,'episodes':chapters,'pages':pages,'available':bool(chapters),
            'seasons':[{'number':n,'name':'Том '+str(n)} for n in sorted({c['season'] for c in chapters})],
            'translations':sorted({c['translator'] for c in chapters if c['translator']}),'dubs':[],'releases':[],'truncated':truncated}
