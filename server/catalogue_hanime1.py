"""The hanime1.me listing as indexed anime series, one listing page per call.

The listing is the site's own search page: without a genre it holds every
video, a genre route (/search?genre=裏番) holds one category. A tag route
(/search?tags[]=巨乳) and a year route (/search?date=2003+年) add that tag or
release year to series the listing already found. Cards are read
and grouped into series by the same functions as the live hanime1 search, and
each row carries that search result's identity and link ("hanime1:" + the
series' lowest episode), so a library card opens our title page and player.
"""
import re
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


def listing_url(genre, page, tag=None, date=None):
    params = [('genre', genre)] if genre else []
    if tag:params.append(('tags[]', tag))
    if date:params.append(('date', date))
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


def tags(soup):
    """The site's content tags: the tags[] checkboxes of the search form."""
    found = (sites.clean(box.get('value') or '', 60) for box in soup.select('input[name="tags[]"]'))
    return list(dict.fromkeys(name for name in found if name))


def years(soup):
    """Release years of the search form's date filter ("2003 年")."""
    found = (sites.clean(option.get('value') or '', 20) for option in soup.select('#date-year option'))
    return list(dict.fromkeys(value for value in found if re.fullmatch(r'(19|20)\d\d 年', value)))


def _first(query, *names):
    return next((query[name][0] for name in names if query.get(name)), '')


def last_page(soup, base, genre, tag=None, date=None):
    pages = [1]
    for anchor in soup.select('a[href*="page="]'):
        query = _query(anchor['href'], base)
        # The pager keeps the route's filters; a tag is written tags[0]=.
        if query and _first(query, 'genre') == (genre or '') and _first(query, 'tags[0]', 'tags[]') == (tag or '') \
                and _first(query, 'date') == (date or '') and (query.get('page') or [''])[0].isdigit():
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


def term_row(items, term):
    """A tag or year route's fact for a series the listing found.

    Only the identity, the title and the fact: the route sees a subset of the
    episodes, so its count and cover must not replace the listing's."""
    row = sites.hanime1_row(items)
    result = {'id': 'hanime1:' + row['url'], 'provider': 'hanime1', 'kind': 'anime', 'title': row['title'],
              'url': row['url'], 'sourceUrl': row['url'], 'tags': [], 'genres': [], 'age': 18}
    if term.get('category') == 'tag':result['tags'] = [term['label']]
    elif term.get('category') == 'year':result['year'] = int(term['label'])
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
    category = term.get('category') or ('genre' if term else '')
    value = term.get('sourceId') or term.get('label')
    genre = value if category == 'genre' else None
    tag = value if category == 'tag' else None
    date = value if category == 'year' else None
    own = http is None
    if own:
        from source_parser import PublicHttp
        http = PublicHttp(timeout=(6, 30))
    try:
        # A Cloudflare challenge raises SourceChallengeError in the transport;
        # the job fails with that reason and is never worked around here.
        text, final_url, _ = http.document(listing_url(genre, page, tag, date))
    finally:
        if own:http.close()
    soup = BeautifulSoup(text, 'html.parser')
    cards = sites._hanime1_cards(soup, final_url)
    # The walk keeps the deepest page any pager named: one page served with a
    # short or missing pager (the base walk stopped at page 41 of 387 on
    # 2026-11-25) no longer ends it.
    known = int(cursor.get('last') or 0)
    if not cards:
        # Past page 1 an empty listing inside the pager is where the site stops serving.
        if page > 1:
            from source_parser import SourceListingEnd
            raise SourceListingEnd(f'Дочитано до предела сайта: страница {page} без карточек'
                                   + (f' из {known} по пейджеру' if known else '') + f'; частичный охват, прочитано {page - 1} стр.')
        raise SourceError('hanime1 не отдал карточки каталога на странице ' + str(page))
    last = max(known, last_page(soup, final_url, genre, tag, date))
    more = page < last
    ready, held = page_rows(cards, cursor.get('held') or [], not more)
    rows = [term_row(items, term) if tag or date else series_row(items, genre) for items in ready]
    if len(rows) > MAX_ROWS:raise SourceError('hanime1 отдал больше карточек, чем пишет одна страница индекса')
    # A page whose every series waits for its first episode is not the end.
    result = {'rows': rows, 'next': {'page': page + 1, 'last': last, **({'held': held} if held else {})} if more else None,
              'emptySpan': not rows}
    # A tag or year route writes facts only to series the listing already
    # holds: a series seen there without its first episode is not a new card.
    if tag or date:result['enrichOnly'] = True
    if page == 1 and not term:
        # Each genre, tag and year route walks once a week and gives its series
        # the genre, the tag or the release year. All genres stay: the owner
        # decides about 3DCG, MMD and AI videos.
        name = spec.get('name', 'Хентай · Hanime1') + ' · '
        result['catalogues'] = [
            *({**spec, 'name': name + value, 'term': {'category': 'genre', 'label': value, 'sourceId': value}}
              for value in genres(soup, final_url)),
            *({**spec, 'name': name + value, 'term': {'category': 'tag', 'label': value, 'sourceId': value}}
              for value in tags(soup)),
            *({**spec, 'name': name + value[:4], 'term': {'category': 'year', 'label': value[:4], 'sourceId': value}}
              for value in years(soup))]
    return result
