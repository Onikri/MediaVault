"""Public search and reader for hentaichan.cc's Next.js and TanStack pages."""
import json
import re
from urllib.parse import urlsplit,urljoin,parse_qs

from bs4 import BeautifulSoup
from source_parser import PublicHttp, SourceError, public_url
from manga_source_tags import from_api, from_html,unique

ROOT = 'https://hentaichan.cc'
SOURCE = {'id': '990000000000000002', 'name': 'HentaiChan.cc', 'lang': 'ru',
          'baseUrl': ROOT, 'isNsfw': True}
CDN = 'cdn.hentaichan.cc'
SLUG = r'[\w-]{1,1024}'
PATH = re.compile(r'/(manga|read)/('+SLUG+r')/?')


def cdn_image(value):
    try:
        url = public_url(value, resolve_dns=False)
        if urlsplit(url).hostname == CDN:
            return url
    except SourceError:
        pass
    return ''


def catalogue_metadata(soup):
    """Explicit work tags; recommendations, global filters and counters aren't facts."""
    complete=flight_tags(flight_text(soup))
    tags=complete if complete is not None else unique(a.get_text(' ',strip=True) for a in soup.select('a[href^="/catalog/tags/"]'))
    description=soup.select_one('meta[property="og:description"],meta[name="description"]')
    cover=soup.select_one('meta[property="og:image"]')
    return {'tags':tags,'genres':[],'sourceMetadataVersion':2 if complete is not None else 1,
            'description':str(description.get('content',''))[:12000] if description else '',
            'cover':cdn_image(cover.get('content')) if cover else ''}


def flight_text(soup):
    chunks=[]
    for script in soup.select('script:not([src])'):
        text=script.get_text().strip()
        if not text.startswith('self.__next_f.push('):continue
        try:part=json.JSONDecoder().raw_decode(text[len('self.__next_f.push('):])[0]
        except ValueError:continue
        if isinstance(part,list) and len(part)>1 and isinstance(part[1],str):chunks.append(part[1])
    return ''.join(chunks)


def flight_tags(text):
    """WorkTags props contain every tag; the DOM renders only five of them.

    A filter dictionary also has `tags` but carries other fields. Never attach
    its global vocabulary to a work, and never execute the source scripts.
    """
    found=[];present=False
    for line in text.splitlines():
        prefix,_,payload=line.partition(':')
        if not re.fullmatch(r'[0-9a-f]+',prefix):continue
        try:stack=[json.loads(payload)]
        except ValueError:continue
        while stack:
            value=stack.pop()
            if isinstance(value,dict):
                tags=value.get('tags')
                if set(value)=={'tags'} and isinstance(tags,list) and all(isinstance(t,dict) and isinstance(t.get('name'),str) and isinstance(t.get('slug'),str) and isinstance(t.get('id'),int) for t in tags):
                    if len({t['name'].strip().casefold() for t in tags})>120:raise SourceError('Полный список тегов карточки превышает лимит индекса; частичный результат не сохранён')
                    present=True;found.extend(t['name'] for t in tags)
                stack.extend(value.values())
            elif isinstance(value,list):stack.extend(value)
    return unique(found) if present else None


def catalogue_page(raw,url,page):
    """The public /catalog listing, its real next link and declared total."""
    soup=BeautifulSoup(raw,'html.parser');rows={};path=urlsplit(url).path
    for anchor in soup.select('a[href^="/manga/"]'):
        target=urljoin(ROOT,anchor['href']);match=PATH.fullmatch(urlsplit(target).path)
        if not match or match[1]!='manga' or urlsplit(target).hostname!='hentaichan.cc':continue
        title=anchor.select_one('p');image=anchor.select_one('img')
        name=title.get_text(' ',strip=True) if title else image.get('alt','') if image else ''
        if not name:continue
        cover=image.get('src','') if image else ''
        if cover.startswith('/_next/image?'):cover=parse_qs(urlsplit(cover).query).get('url',[''])[0]
        rows[target]={'id':'hentaichan-cc:'+match[2],'provider':'hentaichan-cc','providerName':SOURCE['name'],
                      'sourceId':SOURCE['id'],'title':name[:500],'aliases':[name[:500]],'kind':'manga','format':'manga',
                      'language':'ru','url':target,'sourceUrl':target,'cover':cdn_image(cover),'adult':True,'age':18,'tags':[],'genres':[]}
    flight=flight_text(soup)
    counts={key:int(value) for key,value in re.findall(r'"(currentPage|totalPosts|limit)"\s*:\s*(\d+)',flight)}
    if counts.get('currentPage',page)!=page:raise SourceError('Каталог HentaiChan.cc вернул другую страницу')
    next_url=None
    for anchor in soup.select('a[href]'):
        target=urljoin(url,anchor['href']);parts=urlsplit(target)
        if parts.scheme!='https' or parts.hostname!='hentaichan.cc' or parts.path!=path:continue
        if parse_qs(parts.query).get('page')==[str(page+1)]:next_url=target;break
    total=counts.get('totalPosts');limit=counts.get('limit')
    if total is None or not limit:raise SourceError('Каталог HentaiChan.cc не предоставил итоговое число записей')
    if page*limit<total and not next_url:raise SourceError('Не найдена следующая страница каталога HentaiChan.cc')
    if not rows and total:raise SourceError('Каталог HentaiChan.cc не предоставил карточки')
    return {'rows':list(rows.values()),'next':{'page':page+1,'url':next_url} if next_url else None,'total':total,'state':'done'}


def entries(query, http):
    """Raw (title, slug, row) triples from the public search box."""
    text, final, _ = http.document(ROOT + '/', method='POST', data=query, action='hentaichan-search')
    if final != ROOT + '/':
        raise SourceError('HentaiChan.cc перенаправил поиск.')
    for line in text.splitlines():
        prefix, _, payload = line.partition(':')
        if prefix != '1':
            continue
        try:
            result = json.loads(payload)
        except ValueError:
            break
        rows = result.get('data') if isinstance(result, dict) else None
        if not isinstance(rows, list):
            break
        found = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title, slug = row.get('name'), row.get('slug')
            if not isinstance(title, str) or not title.strip() or not isinstance(slug, str) or not re.fullmatch(SLUG, slug):
                continue
            found.append((title.strip()[:500], slug, row))
        return found
    raise SourceError('HentaiChan.cc изменил формат ответа поиска.')


def search(query, http):
    from manga_hentaichan import number, series_title
    grouped = {}
    for title, slug, row in entries(query, http):
        # A series split into per-chapter entries is one work; its earliest
        # entry represents it and the reader collects the sibling parts.
        series = series_title(title)
        name = series or title
        part = number(title) if series else None
        url = ROOT + '/manga/' + slug
        value = {'id': 'hentaichan-cc:' + slug, 'provider': 'hentaichan-cc', 'providerName': SOURCE['name'],
                 'sourceId': SOURCE['id'], 'url': url, 'sourceURL': url, 'sourceUrl': url,
                 'title': name, 'aliases': [name], 'cover': cdn_image(row.get('src')),
                 'kind': 'manga', 'format': 'manga', 'language': 'ru', 'sourceOnly': True, 'adult': True, 'age': 18, **from_api(row)}
        rank = (part is None, part if part is not None else 0)
        key = name.casefold()
        if key not in grouped or rank < grouped[key][0]:
            grouped[key] = (rank, value)
    return [value for _, value in grouped.values()]


def siblings(series, http):
    """Every per-chapter entry of a split series, as reader chapters."""
    from manga_hentaichan import number, series_title
    try:
        found = entries(series, http)
    except SourceError:
        return []
    result = []
    for title, slug, _ in found:
        if (series_title(title) or '').casefold() != series.casefold():
            continue
        part = number(title)
        if part is None:
            continue
        result.append({'number': part, 'season': 1, 'url': ROOT + '/read/' + slug, 'title': title,
                       'language': 'ru', 'translator': ''})
    return result


def chapter(url, slug, index):
    from manga_sources import chapter_number

    number = re.search(r'-(?:glava|chapter)-(\d+(?:[.-]\d+)?)$', slug)
    value = chapter_number(number[1].replace('-', '.')) if number else index
    return {'number': value, 'season': 1, 'url': url, 'title': f'Глава {value}', 'language': 'ru', 'translator': ''}


def inspect(url, http: PublicHttp):
    parts = urlsplit(public_url(url, resolve_dns=False))
    path = PATH.fullmatch(parts.path)
    if parts.hostname != 'hentaichan.cc' or not path:
        raise SourceError('Выбери мангу или главу HentaiChan.cc.')
    canonical = ROOT + f'/{path[1]}/{path[2]}'
    text, final, _ = http.document(canonical)
    if final.rstrip('/') != canonical:
        raise SourceError('HentaiChan.cc перенаправил на другую публикацию.')
    soup = BeautifulSoup(text, 'html.parser')
    title = soup.select_one('h1') or soup.select_one('meta[property="og:title"]') or soup.title
    name = (title.get('content') or title.get_text(' ', strip=True))[:500] if title else SOURCE['name']
    meta = soup.select_one('meta[property="og:image"]')
    cover = cdn_image(meta.get('content')) if meta else ''
    pages, chapters = [], []
    if path[1] == 'read':
        script = next((s.string for s in soup.select('script:not([src])') if '$_TSR.router=' in (s.string or '')), '')
        block = re.search(r'pages:\$R\[\d+\]=\[(.*?)\],\w+:', script, re.S)
        if block:
            pages = [cdn_image(value) for value in re.findall(r'originalSrc:"([^"\\]+)"', block[1])]
        if not pages or not all(pages) or len(pages) > 500:
            raise SourceError('HentaiChan.cc не предоставил страницы этой главы.')
        chapters = [chapter(canonical, path[2], 1)]
    else:
        seen = set()
        for link in soup.select('a[href^="/read/"]'):
            match = PATH.fullmatch(link['href'])
            if match and match[2] not in seen:
                seen.add(match[2])
                chapters.append(chapter(ROOT + '/read/' + match[2], match[2], len(chapters) + 1))
        from manga_hentaichan import series_title
        series = series_title(name)
        if series and len(chapters) <= 1:
            # A per-chapter entry shows only its own part; its siblings are
            # separate catalogue entries found by the series name.
            from manga_hentaichan import number
            parts = siblings(series, http)
            if parts:
                own = number(name)
                for entry in chapters:
                    entry['number'] = own if own is not None else entry['number']
                known = {entry['url'] for entry in parts}
                chapters = parts + [entry for entry in chapters if entry['url'] not in known]
                name = series
        chapters = list({entry['url']: entry for entry in chapters}.values())
        chapters.sort(key=lambda entry: entry['number'])
    return {'provider': 'hentaichan-cc', 'providerName': SOURCE['name'], 'url': canonical,
            'title': name, 'cover': cover, 'kind': 'manga', 'format': 'manga', 'language': 'ru',
            'adult': True, 'age': 18, **catalogue_metadata(soup), 'episodes': chapters, 'pages': pages,
            'seasons': [{'number': 1, 'name': 'Том 1'}] if chapters else [], 'dubs': [],
            'releases': [], 'translations': [], 'available': bool(chapters)}
