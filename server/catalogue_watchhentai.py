"""The WatchHentai (watchhentai.net) series archive as indexed anime series.

One request per call. The walk reads an archive page /series/page/N/ (30
series cards, newest first; page 1 also shows the upcoming strip), then each
of its series pages in turn: a series page names the genres, the studio, the
first air date, the alternative title, the synopsis, the poster and the
episodes. The genre dictionary is the archive's own genre menu, read from page
1 with no extra request. Each row carries the live search result's identity
and link ("watchhentai:" + the /series/ URL), so a library card opens our
title page and the player the same way a search result does.

The site's WordPress REST API does not publish its series
(/wp-json/wp/v2/tvshows answers 404) and its sitemaps list only URLs, so the
archive pages stay the list.
"""
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

import hentai_video_sites as sites
from source_parser import SourceError

DOMAIN = 'watchhentai.net'
ARCHIVE = sites.WATCH + '/series/'
HOSTS = (DOMAIN,)
# Slugs of the last archive pages: a card the archive shifted onto the next
# page (a new series came out during the walk) is not read twice.
REMEMBER = 96


def archive_url(page):
    return ARCHIVE if page <= 1 else ARCHIVE + 'page/' + str(page) + '/'


def series_url(slug):
    return ARCHIVE + slug + '/'


def _slug(url):
    match = re.fullmatch(r'/series/([^/]{1,200})/?', urlsplit(url).path) if url else None
    return match[1] if match and sites.provider_for(url) else ''


def archive_cards(soup, base):
    """[slug, year] of the archive's series cards in page order."""
    found = {}
    for url, _, _, year in sites.watch_cards(soup, base):
        slug = _slug(url)
        if slug:
            found.setdefault(slug, [slug, year])
    return list(found.values())


def last_page(soup):
    pages = [1]
    for status in soup.select('.pagination__status'):
        match = re.search(r'\bof\s+(\d{1,5})\b', status.get_text(' '))
        if match:
            pages.append(int(match[1]))
    for anchor in soup.select('a[href*="/series/page/"]'):
        match = re.search(r'/series/page/(\d{1,5})/?$', urlsplit(anchor.get('href') or '').path)
        if match:
            pages.append(int(match[1]))
    return max(pages)


def genres(soup):
    """The genre dictionary: the archive's genre menu (name and series count)."""
    found = [sites.clean(a.get_text(' ', strip=True), 60) for a in soup.select('nav.genres li a[href*="/genre/"]')]
    return list(dict.fromkeys(name for name in found if name))


def _about(card):
    """The series page's «About» fields: label → value node."""
    fields = {}
    for field in card.select('.tv-about-field'):
        label = field.select_one('.tv-about-field__label')
        value = field.select_one('.tv-about-field__value')
        if label and value:
            fields.setdefault(sites.clean(label.get_text(' ', strip=True), 60).casefold(), value)
    return fields


def _texts(nodes, limit=120):
    return list(dict.fromkeys(name for node in nodes if (name := sites.clean(node.get_text(' ', strip=True), limit))))


def series_row(text, final, year=None):
    """The index row of one series page, or None when it is not a series page."""
    soup = BeautifulSoup(text, 'html.parser')
    canonical = soup.select_one('link[rel="canonical"][href]')
    url = sites._url(final, final, HOSTS)
    hero = soup.select_one('.sheader')
    if not _slug(url) or not hero:
        return None
    # The canonical address (the -id-NN page a short link redirects to) is the id.
    own = sites._url(canonical['href'], final, HOSTS) if canonical else ''
    url = own if _slug(own) else url
    heading = hero.select_one('.data h1') or hero.select_one('h1')
    title = sites.clean(heading.get_text(' ', strip=True) if heading else '', 200)
    if not title:
        return None
    about = _about(soup)
    alternative = about.get('alternative title')
    # One alternative title, kept whole: a romaji title may hold a comma itself.
    aliases = [title, sites.clean(alternative.get_text(' ', strip=True), 200) if alternative else '']
    genre_names = _texts(hero.select('.sgeneros a[href*="/genre/"]'))
    studios = _texts(hero.select('.extra .studio a[href*="/studio/"]'))
    if not studios and about.get('studio'):
        studios = _texts(about['studio'].select('a[href*="/studio/"]')) or _texts([about['studio']])
    aired = about.get('first air date')
    dated = re.search(r'\b((?:19|20)\d\d)\b', aired.get_text(' ') if aired else '')
    if not dated:
        created = hero.select_one('.extra .date')
        dated = re.search(r'\b((?:19|20)\d\d)\b', created.get_text(' ') if created else '')
    found_year = int(dated[1]) if dated else year
    synopsis = soup.select_one('.tv-single-synopsis__body') or soup.select_one('.wp-content')
    description = '\n'.join(line for p in (synopsis.select('p') or [synopsis])
                            if (line := sites.clean(p.get_text(' ', strip=True), 4000))) if synopsis else ''
    poster = hero.select_one('.poster img')
    cover = sites._url((poster.get('data-src') or poster.get('src')) if poster else '', final, HOSTS)
    # Released episodes; an announced one («Episode 2 (PREVIEW)») only plays a clip.
    listed = sites.watch_episode_links(soup, final)
    episodes = len([e for e in listed if not e.get('preview')])
    counted = re.fullmatch(r'\d{1,3}', sites.clean(about['episodes'].get_text() if about.get('episodes') else ''))
    if not episodes and counted and 0 < int(counted[0]) <= sites.MAX_EPISODES:
        episodes = int(counted[0])
    # The client keys a source result as provider:url; no providerId, so the
    # title page does not ask a catalogue API that WatchHentai does not have.
    row = {'id': 'watchhentai:' + url, 'provider': 'watchhentai', 'kind': 'anime', 'title': title,
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
        if own:
            http.close()


def catalogue(spec, cursor, http=None):
    page = max(1, int(cursor.get('page', 1)))
    queue = [item for item in cursor.get('queue') or [] if isinstance(item, list) and item and isinstance(item[0], str)]
    seen = [slug for slug in cursor.get('seen') or [] if isinstance(slug, str)]
    known = int(cursor.get('last') or 0)
    rest = {key: value for key, value in (('last', known), ('seen', seen)) if value}
    if queue:
        (slug, year), queue = (queue[0] + [None])[:2], queue[1:]
        try:
            text, final, _ = _document(http, series_url(slug))
        except SourceError as error:
            # A series removed since its card was listed is skipped, not the walk's end.
            if getattr(error, 'http_status', None) not in {404, 410}:
                raise
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
        raise SourceError('WatchHentai не отдал сериалы архива на странице ' + str(page))
    last = max(known, last_page(soup))
    fresh = [card for card in cards if card[0] not in seen]
    state = {'page': page + 1, 'last': last, 'seen': [*seen, *(card[0] for card in cards)][-REMEMBER:],
             **({'queue': fresh} if fresh else {})}
    result = {'rows': [], 'next': state if fresh or page < last else None, 'emptySpan': True}
    if page == 1:
        # The genre dictionary rides on the first archive page: no extra request.
        result['vocabulary'] = [{'category': 'genre', 'label': name} for name in genres(soup)]
    return result
