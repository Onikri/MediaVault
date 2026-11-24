"""The hanime1.me listing as indexed anime series, one listing page per call.

The listing is the site's own search page: without a genre it holds every
video, a genre route (/search?genre=裏番) holds one category. Cards are read
and grouped into series by the same functions as the live hanime1 search, and
each row carries that search result's identity and link ("hanime1:" + the
series' lowest episode), so a library card opens our title page and player.
"""
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

import hentai_video_sites as sites
from source_parser import SourceError

DOMAIN = 'hanime1.me'
# The listing is newest first, so a series often shows a later episode one page
# before its first. A series without episode 1 waits this many pages for it.
HOLD_PAGES = 3
HOLD_LIMIT = 30
# content_catalog.ingest writes at most 100 rows per call; a page has <=60 cards.
MAX_ROWS = 100


def listing_url(genre, page):
    params = [('genre', genre)] if genre else []
    if page > 1:params.append(('page', page))
    return sites.HANIME1 + '/search' + ('?' + urlencode(params) if params else '')


def _query(href, base):
    parts = urlsplit(urljoin(base, href))
    if parts.hostname != DOMAIN or parts.path != '/search':return None
    return parse_qs(parts.query)


def genres(soup, base):
    """Genre names linked as plain /search?genre=<name> routes."""
    found = []
    for anchor in soup.select('a[href*="genre="]'):
        query = _query(anchor['href'], base)
        if query and set(query) == {'genre'} and (name := sites.clean(query['genre'][0], 60)) and name != '全部':
            found.append(name)
    return list(dict.fromkeys(found))


def last_page(soup, base, genre):
    pages = [1]
    for anchor in soup.select('a[href*="page="]'):
        query = _query(anchor['href'], base)
        if query and (query.get('genre') or [''])[0] == (genre or '') and (query.get('page') or [''])[0].isdigit():
            pages.append(int(query['page'][0]))
    return max(pages)


def series_row(items, genre=None):
    row = sites.hanime1_row(items)
    # The client keys a source result as provider:url; no providerId, so the
    # title page does not ask a catalogue API that hanime1 does not have.
    result = {'id': 'hanime1:' + row['url'], 'provider': 'hanime1', 'kind': 'anime', 'title': row['title'],
              'aliases': row['aliases'], 'url': row['url'], 'sourceUrl': row['url'], 'cover': row.get('cover', ''),
              'episodes': row.get('episodes', 1), 'tags': [], 'genres': [genre] if genre else [], 'age': 18}
    return result


def page_rows(cards, held, final):
    """Series ready on this page and the cards still waiting for episode 1.

    held is the cursor's [url, title, cover, pages waited] list."""
    ages = {url: age for url, _, _, age in held}
    # A card the listing shifted onto the next page is the same episode.
    unique = {}
    for url, title, cover in [*((url, title, cover) for url, title, cover, _ in held), *cards]:
        unique.setdefault(url, (url, title, cover))
    pool = list(unique.values())
    titles = {url: title for url, title, _ in pool}
    ready, waiting = [], []
    for items in sites.hanime1_groups(pool).values():
        waited = max(ages.get(url, 0) for _, url, _, _ in items)
        if final or items[0][0] == 1 or waited + 1 >= HOLD_PAGES:ready.append(items)
        else:waiting.append(items)
    # The cursor stays small: the oldest waiting series are released first.
    while len(waiting) > HOLD_LIMIT:ready.append(waiting.pop(0))
    keep = [[url, titles[url], cover, ages.get(url, 0) + 1] for items in waiting for _, url, _, cover in items]
    return ready, keep


def catalogue(spec, cursor, http=None):
    page = max(1, int(cursor.get('page', 1)))
    term = spec.get('term') or {}
    genre = term.get('sourceId') or term.get('label')
    own = http is None
    if own:
        from source_parser import PublicHttp
        http = PublicHttp(timeout=(6, 30))
    try:
        # A Cloudflare challenge raises SourceChallengeError in the transport;
        # the job fails with that reason and is never worked around here.
        text, final_url, _ = http.document(listing_url(genre, page))
    finally:
        if own:http.close()
    soup = BeautifulSoup(text, 'html.parser')
    cards = sites._hanime1_cards(soup, final_url)
    if not cards:raise SourceError('hanime1 не отдал карточки каталога на странице ' + str(page))
    last = last_page(soup, final_url, genre)
    more = page < last
    ready, held = page_rows(cards, cursor.get('held') or [], not more)
    rows = [series_row(items, genre) for items in ready]
    if len(rows) > MAX_ROWS:raise SourceError('hanime1 отдал больше карточек, чем пишет одна страница индекса')
    # A page whose every series waits for its first episode is not the end.
    result = {'rows': rows, 'next': {'page': page + 1, **({'held': held} if held else {})} if more else None,
              'emptySpan': not rows}
    if page == 1 and not term:
        # Each genre route walks once a week and gives its series the genre.
        result['catalogues'] = [{**spec, 'name': spec.get('name', 'Хентай · Hanime1') + ' · ' + name,
                                 'term': {'category': 'genre', 'label': name, 'sourceId': name}}
                                for name in genres(soup, final_url)]
    return result
