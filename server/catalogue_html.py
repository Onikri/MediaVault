"""Metadata-only adapters for the public catalogue cards, never reader pages.

The Chan family exposes tags inside collapsed catalogue rows. Reading those
nodes avoids losing labels in older extensions that only parse the detail page.
"""
import re
from urllib.parse import urljoin, urlsplit, parse_qs
from bs4 import BeautifulSoup
from manga_source_tags import unique
from source_parser import SourceError, SourceTemporaryError

CHAN = {'manga-chan.me', 'hentaichan.live', 'h-chan.me', 'y.hentaichan.live'}
SPECIAL = CHAN | {'online.hentaimoody.com', 'hentaros.com'}
# HentaiChan's own listing modules (/manga/newest, /mostfavorites, /tags/...)
# answer a bare "technical maintenance." (observed 2026-11-25, offset 0 and
# 200 alike), while the DLE category /manga/page/N/ serves the same catalogue:
# 20 cards a page with their tags, newest first, 1657 pages.
MAINTENANCE = re.compile(r'\s*technical maintenance\.?\s*', re.I)
DLE_LISTING = re.compile(r'/manga/(?:page/([1-9]\d{0,5})/)?')
# Indexed cards carry the native reader's source id, which the Library source
# filter selects (manga_hentaichan.SOURCE), not a Suwayomi extension id.
NATIVE_SOURCE = {'hentaichan.live': '990000000000000001'}


def listing_url(url, page):
    """The served HentaiChan listing page for a stored /manga/newest cursor.

    Both listings hold 20 cards a page, newest first, so page N continues
    where offset (N-1)*20 stopped."""
    p = urlsplit(url)
    if p.path.rstrip('/') != '/manga/newest':return url
    return p.scheme + '://' + p.netloc + '/manga/' + ('' if page == 1 else f'page/{page}/')


def dle_pages(soup, url, hosts, page, count):
    """Next page and catalogue size from the DLE navigation of /manga/page/N/."""
    numbers = {}
    for a in soup.select('.navigation a[href]'):
        target = urljoin(url, a.get('href', '')); p = urlsplit(target); match = DLE_LISTING.fullmatch(p.path)
        if p.scheme != 'https' or p.hostname not in hosts or not match or p.query:continue
        numbers[int(match[1] or 1)] = target
    later = [n for n in numbers if n > page]
    if later and min(later) != page + 1:raise SourceError('Источник пропустил страницу каталога')
    following = {'page': page + 1, 'url': numbers[page + 1]} if later else None
    # The last linked page bounds the catalogue; the final page gives it exactly.
    total = max([page, *numbers]) * 20 if following else (page - 1) * 20 + count
    return following, total


def valid_url(value, base, hosts, pattern):
    url = urljoin(base, value or '')
    p = urlsplit(url)
    return url if p.scheme == 'https' and p.hostname in hosts and not p.username and not p.password and re.fullmatch(pattern, p.path) else ''


def facts(scope):
    # Work-local containers only; .sidetag (singular) is a global tag cloud.
    genres = scope.select('.genre a[href*="/tags/"]')
    tags = scope.select('.tags a[href*="/tags/"],.sidetags ul a[href*="/tags/"]')
    return {'tags': unique(a.get_text(' ', strip=True) for a in tags), 'genres': unique(a.get_text(' ', strip=True) for a in genres)}


def catalogue(raw, url, spec, page):
    domain = spec['domain']; hosts = set(spec['hosts'])
    if domain in CHAN and MAINTENANCE.fullmatch(raw.lstrip('\ufeff')):
        raise SourceTemporaryError('Раздел каталога на сайте закрыт на техническое обслуживание')
    soup = BeautifulSoup(raw, 'html.parser')
    if domain=='hentaros.com' and urlsplit(url).path.rstrip('/')=='/tag':
        vocabulary=[];catalogues=[];seen=set()
        for a in soup.select('a.card[href]'):
            target=valid_url(a.get('href'),url,hosts,r'/tag/[^/?#]{1,300}/?')
            label=a.select_one('.t')
            if not target or label is None:raise SourceError('Источник изменил каталог тегов')
            if target in seen:continue
            seen.add(target)
            term={'label':label.get_text(' ',strip=True),'category':'tag','url':target}
            vocabulary.append(term);catalogues.append({**spec,'url':target,'term':term})
        if not vocabulary:raise SourceError('Источник не предоставил каталог тегов')
        return {'rows':[],'next':None,'state':'partial','vocabulary':vocabulary,'catalogues':catalogues,
                'reason':'Обход опубликованных каталогов тегов; полнота безымянных записей не подтверждена'}
    chan = domain in CHAN
    selector = '.content_row' if chan else '.manga-card' if domain == 'online.hentaimoody.com' else 'a.card'
    rows = []
    for node in soup.select(selector):
        a = node.select_one('a.title_link,h2 a[href]') if chan else node.select_one('a.manga-card__link') if domain == 'online.hentaimoody.com' else node
        if a is None:continue
        pattern = r'/manga/[^/?#]{1,1024}\.html' if chan else r'/[1-9]\d{0,11}-[^/?#]{1,1024}\.html' if domain == 'online.hentaimoody.com' else r'/[^/?#]{1,1024}'
        target = valid_url(a.get('href'), url, hosts, pattern)
        title_node = a if chan else node.select_one('.manga-card__title,.t')
        title = title_node.get_text(' ', strip=True) if title_node else ''
        if not target or not title:raise SourceError('Источник вернул нераспознанную карточку каталога')
        img = node.select_one('img'); cover = ''
        if img:
            value = img.get('data-full') or img.get('data-src') or img.get('src') or ''
            from content_catalog import safe_url
            cover = safe_url(urljoin(url, value))
        source = spec.get('source') or {}
        from catalogue_sources import source_provider
        provider = source_provider(spec)
        tags = facts(node) if chan else {'tags': [], 'genres': unique([s for n in node.select('.manga-card__meta') for s in n.stripped_strings])}
        row = {'kind':'manga','title':title[:500],'aliases':[title[:500]],'provider':provider,'providerName':spec['name'].split(' · ')[0],
               'url':target,'sourceUrl':target,'sourceOnly':True,'language':'ru','cover':cover,**tags}
        if sid := NATIVE_SOURCE.get(domain) or source.get('id'):row['sourceId'] = str(sid)
        if chan and node.select_one('.genre,.tags'):row['sourceMetadataVersion'] = 2
        rows.append(row)
    if not rows:raise SourceError('Не удалось прочитать карточки каталога')
    # Offset navigation is outside .pagination in all three Chan templates.
    if chan and (listing := DLE_LISTING.fullmatch(urlsplit(url).path)):
        if int(listing[1] or 1) != page:raise SourceError('Источник вернул другую страницу каталога')
        following, total = dle_pages(soup, url, hosts, page, len(rows))
        return {'rows':rows,'next':following,'state':'done','total':total}
    if chan:
        current = int((parse_qs(urlsplit(url).query).get('offset') or ['0'])[0])
        if current != (page-1)*20:raise SourceError('Источник вернул другую страницу каталога')
        candidates = []
        for a in soup.select('a[href*="offset="]'):
            target = urljoin(url, a.get('href','')); p = urlsplit(target)
            values = parse_qs(p.query).get('offset') or []
            if p.scheme != 'https' or p.hostname not in hosts or p.path != urlsplit(url).path or not values or not values[0].isdigit():continue
            offset = int(values[0])
            if offset > current:candidates.append((offset,target))
        next_page = None
        if candidates:
            offset,target = min(candidates)
            if offset != current+20:raise SourceError('Источник пропустил страницу каталога')
            next_page = {'page':page+1,'url':target}
        return {'rows':rows,'next':next_page,'state':'done'}
    from catalogue_sources import next_html
    return {'rows':rows,'next':next_html(raw,url,hosts,page),'state':'done' if spec.get('term') or domain!='hentaros.com' else 'partial'}


def metadata(soup, domain):
    if domain in CHAN:
        # A 200 login/error/empty extension result is not complete metadata.
        if not soup.select_one('#info_wrap') or not soup.select_one('.sidetags'):
            raise SourceError('Источник не предоставил полные теги карточки')
        result = {**facts(soup), 'sourceMetadataVersion':2}
        summary = soup.select_one('#description')
        if summary:result['description'] = summary.get_text(' ',strip=True)[:12000]
        return result
    if domain=='online.hentaimoody.com':
        hero=soup.select_one('.title-hero__body');genres=soup.select_one('.title-hero__genres')
        if not hero or not hero.select_one('h1') or genres is None:
            raise SourceError('Источник не предоставил полные метаданные карточки')
        # The reader below this public header can require login. That does not
        # make the explicitly public title metadata inaccessible.
        summary=soup.select_one('.full-text')
        return {'genres':unique(n.get_text(' ',strip=True) for n in genres.select('a[href]')),'tags':[],
                'description':summary.get_text(' ',strip=True)[:12000] if summary else '', 'sourceMetadataVersion':2}
    if domain=='hentaros.com':
        hero=soup.select_one('.post-head')
        if not hero or not hero.select_one('h1'):raise SourceError('Источник не предоставил метаданные карточки')
        return {'title':hero.select_one('h1').get_text(' ',strip=True)[:500],
                'tags':unique(a.get_text(' ',strip=True) for a in soup.select('.chip[href*="/tag/"]')),
                'genres':[], 'sourceMetadataVersion':2}
    if soup.select_one('.system-message,.login-required'):
        raise SourceError('Источник не предоставил открытые метаданные карточки')
    # Other source templates must have explicit work metadata before the normal
    # conservative HTML parser may mark the detail request as inspected.
    if not soup.select_one('h1'):
        raise SourceError('Источник не предоставил метаданные карточки')
    return {}
