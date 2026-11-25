"""The HentaiMama (hentaimama.io) series archive as indexed anime series.

One request per call. The walk reads an archive page /tvshows/page/N/ (24
series cards, newest first), then each of its series pages in turn: a series
page names the genres, the studio, the release date, the synopsis, the poster
and the episodes. After the first archive page one call reads the genre
dictionary from /genres-filter/. Each row carries the live search result's
identity and link ("hentaimama:" + the /tvshows/ URL), so a library card opens
our title page and the player the same way a search result does.

The site's WordPress REST API does not publish its series (/wp-json/wp/v2/tvshows
answers 404); its core sitemap lists only URLs, so archive pages stay the list.
"""
import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

import hentai_video_sites as sites
from source_parser import SourceError

DOMAIN = 'hentaimama.io'
ARCHIVE = sites.MAMA + '/tvshows/'
GENRES = sites.MAMA + '/genres-filter/'
HOSTS = (DOMAIN,)
# Slugs of the last archive pages: a card the archive shifted onto the next
# page (a new series came out during the walk) is not read twice.
REMEMBER = 48


def archive_url(page):
    return ARCHIVE if page <= 1 else ARCHIVE + 'page/' + str(page) + '/'


def series_url(slug):
    return ARCHIVE + slug + '/'


def _slug(url):
    match = re.fullmatch(r'/tvshows/([^/]{1,160})/?', urlsplit(url).path) if url else None
    return match[1] if match and sites.provider_for(url) else ''


def archive_cards(soup, base):
    """[slug, year] of the archive's series cards in page order."""
    found = {}
    for card in soup.select('article.item.tvshows'):
        anchor = card.select_one('.data h3 a[href], a[href*="/tvshows/"]')
        slug = _slug(sites._url(anchor.get('href') if anchor else '', base, HOSTS))
        if not slug:
            continue
        tag = card.select_one('.card-tags .tag')
        year = re.fullmatch(r'(19|20)\d\d', sites.clean(tag.get_text() if tag else ''))
        found.setdefault(slug, [slug, int(year[0]) if year else None])
    return list(found.values())


def last_page(soup):
    pager = soup.select_one('.pagination[data-pages]')
    pages = [1]
    if pager and str(pager.get('data-pages')).isdigit():
        pages.append(int(pager['data-pages']))
    for anchor in soup.select('a[href*="/tvshows/page/"]'):
        match = re.search(r'/tvshows/page/(\d{1,5})/?$', urlsplit(anchor.get('href') or '').path)
        if match:
            pages.append(int(match[1]))
    return max(pages)


def genres(soup):
    """The genre dictionary of /genres-filter/ (its chips, else its select)."""
    found = [sites.clean(a.get_text(' ', strip=True), 60) for a in soup.select('#genres a.genreitem[href*="/genre/"]')]
    if not found:
        found = [sites.clean(option.get('value') or option.get_text(), 60) for option in soup.select('select option')]
    return list(dict.fromkeys(name for name in found if name))


def _ld_series(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text() or '')
        except ValueError:
            continue
        for item in (data.get('@graph') if isinstance(data, dict) else None) or [data]:
            if isinstance(item, dict) and item.get('@type') == 'TVSeries':
                return item
    return {}


def _texts(nodes, limit=120):
    return list(dict.fromkeys(name for node in nodes if (name := sites.clean(node.get_text(' ', strip=True), limit))))


def series_row(text, final, year=None):
    """The index row of one series page, or None when it is not a series page."""
    url = sites._url(final, final, HOSTS)
    if not _slug(url):
        return None
    soup = BeautifulSoup(text, 'html.parser')
    card = soup.select_one('.dt-show-card') or soup
    ld = _ld_series(soup)
    heading = card.select_one('h1.dsc-title') or soup.select_one('h1')
    title = sites.clean(heading.get_text(' ', strip=True) if heading else ld.get('name'), 200)
    if not title:
        return None
    alt = card.select_one('.dsc-alt')
    aliases = [title, *([sites.clean(alt.get_text(' ', strip=True), 200)] if alt else []),
               *([sites.clean(ld['alternateName'], 200)] if isinstance(ld.get('alternateName'), str) else [])]
    genre_names = _texts(card.select('.dsc-genres a[href*="/genre/"]'))
    if not genre_names and isinstance(ld.get('genre'), list):
        genre_names = list(dict.fromkeys(sites.clean(g, 120) for g in ld['genre'] if isinstance(g, str) and g.strip()))
    studios = _texts(card.select('.dsc-stats a[href*="/studio/"]'))
    company = ld.get('productionCompany')
    if not studios and isinstance(company, dict) and isinstance(company.get('name'), str) and company['name'].strip():
        studios = [sites.clean(company['name'], 120)]
    published = re.match(r'((?:19|20)\d\d)', str(ld.get('datePublished') or ''))
    aired = next((re.search(r'\b((?:19|20)\d\d)\b', stat.get_text(' ')) for stat in card.select('.dsc-stat')
                  if sites.clean(stat.select_one('span').get_text() if stat.select_one('span') else '') == 'Aired'), None)
    found_year = int(published[1]) if published else int(aired[1]) if aired else year
    # The synopsis paragraphs; the JSON-LD description is the site's SEO line.
    desc = card.select_one('.dsc-desc')
    description = '\n'.join(line for p in (desc.select('p') or [desc]) if (line := sites.clean(p.get_text(' ', strip=True), 4000))) if desc else ''
    poster = card.select_one('.dsc-poster img')
    cover = sites._url((poster.get('data-src') or poster.get('src')) if poster else '', final, HOSTS)
    if not cover:
        image = soup.select_one('meta[property="og:image"]')
        cover = sites._url(image.get('content') if image else '', final, (DOMAIN, 'image.tmdb.org'))
    episodes = len(sites.mama_episode_links(soup, final))
    if not episodes and isinstance(ld.get('numberOfEpisodes'), int) and 0 < ld['numberOfEpisodes'] <= sites.MAX_EPISODES:
        episodes = ld['numberOfEpisodes']
    # The client keys a source result as provider:url; no providerId, so the
    # title page does not ask a catalogue API that HentaiMama does not have.
    row = {'id': 'hentaimama:' + url, 'provider': 'hentaimama', 'kind': 'anime', 'title': title,
           'aliases': list(dict.fromkeys(name for name in aliases if name)), 'url': url, 'sourceUrl': url,
           'cover': cover, 'tags': [], 'genres': genre_names, 'studios': studios, 'description': description, 'age': 18}
    if episodes:
        row['episodes'] = episodes
    if found_year:
        row['year'] = found_year
    return row


def _document(http, url):
    own = http is None
    if own:
        from source_parser import PublicHttp
        http = PublicHttp(timeout=(6, 30))
    try:
        # A Cloudflare challenge raises SourceChallengeError in the transport;
        # the job fails with that reason and is never worked around here.
        return http.document(url)
    finally:
        if own:http.close()


def catalogue(spec, cursor, http=None):
    page = max(1, int(cursor.get('page', 1)))
    queue = [item for item in cursor.get('queue') or [] if isinstance(item, list) and item and isinstance(item[0], str)]
    seen = [slug for slug in cursor.get('seen') or [] if isinstance(slug, str)]
    known = int(cursor.get('last') or 0)
    rest = {key: value for key, value in (('last', known), ('seen', seen)) if value}
    if cursor.get('genres'):
        # The genre dictionary: one page, read once per walk.
        text, _, _ = _document(http, GENRES)
        state = {**rest, 'page': page, **({'queue': queue} if queue else {})}
        return {'rows': [], 'next': state if queue or page <= known else None, 'emptySpan': True,
                'vocabulary': [{'category': 'genre', 'label': name} for name in genres(BeautifulSoup(text, 'html.parser'))]}
    if queue:
        (slug, year), queue = (queue[0] + [None])[:2], queue[1:]
        try:
            text, final, _ = _document(http, series_url(slug))
        except SourceError as error:
            # A series removed since its card was listed is skipped, not the walk's end.
            if getattr(error, 'http_status', None) not in {404, 410}:raise
            text, final = '', ''
        row = series_row(text, final, year) if text else None
        more = bool(queue) or page <= known
        state = {**rest, 'page': page, **({'queue': queue} if queue else {})}
        return {'rows': [row] if row else [], 'next': state if more else None, 'emptySpan': not row}
    text, final, _ = _document(http, archive_url(page))
    soup = BeautifulSoup(text, 'html.parser')
    cards = archive_cards(soup, final)
    if not cards:
        if page > 1:
            from source_parser import SourceListingEnd
            raise SourceListingEnd(f'Дочитано до предела сайта: страница архива {page} без сериалов'
                                   + (f' из {known}' if known else '') + f'; частичный охват, прочитано {page - 1} стр.')
        raise SourceError('HentaiMama не отдал сериалы архива на странице ' + str(page))
    last = max(known, last_page(soup))
    fresh = [card for card in cards if card[0] not in seen]
    state = {'page': page + 1, 'last': last, 'seen': [*seen, *(card[0] for card in cards)][-REMEMBER:],
             **({'queue': fresh} if fresh else {})}
    if page == 1:
        state['genres'] = True
    more = bool(fresh) or page < last or page == 1
    return {'rows': [], 'next': state if more else None, 'emptySpan': True}
