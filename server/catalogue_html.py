"""Metadata-only adapters for the public catalogue cards, never reader pages.

The Chan family exposes tags inside collapsed catalogue rows. Reading those
nodes avoids losing labels in older extensions that only parse the detail page.
"""
import re
from urllib.parse import urljoin, urlsplit, parse_qs
from bs4 import BeautifulSoup
from manga_source_tags import unique
from source_parser import SourceError

CHAN = {'manga-chan.me', 'hentaichan.live', 'h-chan.me', 'yaoi-chan.me', 'y.hentaichan.live'}
SPECIAL = CHAN | {'online.hentaimoody.com', 'hentaros.com'}


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
    soup = BeautifulSoup(raw, 'html.parser'); domain = spec['domain']; hosts = set(spec['hosts'])
    chan = domain in CHAN
    selector = '.content_row' if chan else '.manga-card' if domain == 'online.hentaimoody.com' else 'a.card'
    rows = []
    for node in soup.select(selector):
        a = node.select_one('a.title_link,h2 a[href]') if chan else node.select_one('a.manga-card__link') if domain == 'online.hentaimoody.com' else node
        if a is None:continue
        pattern = r'/manga/[^/?#]{1,1024}\.html' if chan else r'/[1-9]\d{0,11}-[^/?#]{1,1024}\.html' if domain == 'online.hentaimoody.com' else r'/[\w-]{1,300}'
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
        provider = 'suwayomi:' + str(source['id']) if source.get('id') else {'hentaichan.live':'hentaichan','h-chan.me':'hentaichan','manga-chan.me':'mangachan'}.get(domain, domain)
        tags = facts(node) if chan else {'tags': [], 'genres': unique([s for n in node.select('.manga-card__meta') for s in n.stripped_strings])}
        row = {'kind':'manga','title':title[:500],'aliases':[title[:500]],'provider':provider,'providerName':spec['name'].split(' · ')[0],
               'url':target,'sourceUrl':target,'sourceOnly':True,'language':'ru','cover':cover,**tags}
        if source.get('id'):row['sourceId'] = str(source['id'])
        if chan and node.select_one('.genre,.tags'):row['sourceMetadataVersion'] = 2
        rows.append(row)
    if not rows:raise SourceError('Не удалось прочитать карточки каталога')
    # Offset navigation is outside .pagination in all three Chan templates.
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
    return {'rows':rows,'next':next_html(raw,url,hosts,page), 'state':'partial' if domain=='hentaros.com' else 'done',
            **({'reason':'Открыта витрина; полный каталог источник не предоставил'} if domain=='hentaros.com' else {})}


def metadata(soup, domain):
    if domain in CHAN:
        # A 200 login/error/empty extension result is not complete metadata.
        if not soup.select_one('#info_wrap') or not soup.select_one('.sidetags'):
            raise SourceError('Источник не предоставил полные теги карточки')
        result = {**facts(soup), 'sourceMetadataVersion':2}
        summary = soup.select_one('#description')
        if summary:result['description'] = summary.get_text(' ',strip=True)[:12000]
        return result
    if soup.select_one('.system-message,.login-required'):
        raise SourceError('Источник не предоставил открытые метаданные карточки')
    # Other source templates must have explicit work metadata before the normal
    # conservative HTML parser may mark the detail request as inspected.
    if not soup.select_one('h1'):
        raise SourceError('Источник не предоставил метаданные карточки')
    return {}
