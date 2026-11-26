"""The Rule 34 section of HentaiHaven (hentaihaven.xxx) as indexed clips.

One request per call. The site's WordPress back end (cms.hentaihaven.xxx)
publishes the section as the post type rule34-video through its public REST
API: ~20 500 clips in November 2026, 100 a page in id order. A clip post names
its own HLS master (manifest_url on octopusmanifest.org, the series' player),
so the list pages alone decide what plays: no request per clip.

The walk reads three term dictionaries (categories: franchises and 2D/3D,
tags, artists; ~6 + 59 + 25 pages), then ~205 list pages: ~300 requests a
weekly walk. The dictionaries ride in the cursor, packed. Its host is the
series job's (catalogue_hentaihaven): both share the host's pace and its one
slot (catalogue_indexer.SLOTS), so the site sees one walk at a time.

A row is one clip, only when its master is named (older imports without one
do not play). The site's categories and tags are the row's tags, its artists
the studios, unchanged (the tag policy decides how they show); the genre
«Rule 34» marks the section. Clips are fan works of other franchises, so they
are their own works: no external IDs, never an index anchor of a card
(content_names.UNANCHORED), never searched by title (hentai_video_sites).
"""
import base64
import json
import zlib
from urllib.parse import urlencode, urlsplit

import catalogue_hentaihaven as series
import hentai_video_sites as sites
from source_parser import SourceError

DOMAIN = 'hentaihaven.xxx'
API = sites.HAVEN_CMS + '/wp-json/wp/v2/'
GENRE = 'Rule 34'
PER_PAGE = 100
# Dictionaries in walk order: category and tag names become the row's tags,
# artist names its studios.
TAXONOMIES = ('rule34-video-category', 'rule34-video-tag', 'rule34-video-artist')
FIELDS = 'id,slug,type,title,link,date,meta,manifest_url,thumbnail_url,' + ','.join(TAXONOMIES)
# A clip's cover is the player's own thumbnail (thumbnail_url, image/webp);
# the series' img.hentaihaven.xxx path of its meta answered 404 for clips.
THUMBNAILS = ('cdnr-octopus.hhpanel.org',)
# Sanity bounds (59 tag pages and 205 list pages in November 2026).
MAX_TERM_PAGES = 200
MAX_PAGES = 1000
MAX_TAGS = 60
MAX_STUDIOS = 10


def terms_url(taxonomy, page):
    return API + taxonomy + '?' + urlencode({'per_page': PER_PAGE, 'page': page, 'orderby': 'id', 'order': 'asc',
                                             '_fields': 'id,name', 'hide_empty': 'true'})


def page_url(page):
    return API + 'rule34-video?' + urlencode({'per_page': PER_PAGE, 'page': page, 'orderby': 'id', 'order': 'asc', '_fields': FIELDS})


def pack(terms):
    raw = json.dumps(terms, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()
    return base64.b64encode(zlib.compress(raw, 9)).decode()


def unpack(value):
    try:
        data = json.loads(zlib.decompress(base64.b64decode(str(value or ''))).decode())
    except (ValueError, zlib.error):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}


def cover(post):
    value = str(post.get('thumbnail_url') or '')
    parts = urlsplit(value)
    return value if parts.scheme == 'https' and parts.hostname in THUMBNAILS and not parts.query else ''


def names(post, taxonomy, terms):
    ids = post.get(taxonomy) if isinstance(post.get(taxonomy), list) else []
    return [terms[str(t)] for t in ids if isinstance(t, int) and str(t) in terms]


def clip_row(post, terms):
    """The index row of a rule34-video post, or None when it does not play."""
    clip = sites.rule34_clip(post)
    if not clip:
        return None
    url = sites.rule34_url(clip['slug'])
    category, tag, artist = (terms.get(name, {}) for name in TAXONOMIES)
    tags = list(dict.fromkeys([*names(post, TAXONOMIES[0], category), *names(post, TAXONOMIES[1], tag)]))
    row = {'id': sites.RULE34 + ':' + url, 'provider': sites.RULE34, 'kind': 'anime', 'title': clip['title'],
           'aliases': [clip['title']], 'url': url, 'sourceUrl': url, 'cover': cover(post), 'tags': tags[:MAX_TAGS],
           'genres': [GENRE], 'studios': list(dict.fromkeys(names(post, TAXONOMIES[2], artist)))[:MAX_STUDIOS],
           'description': '', 'age': 18, 'episodes': 1}
    if clip['year']:
        row['year'] = clip['year']
    return row


def _get(http, url):
    own = http is None
    if own:
        from source_parser import PublicHttp
        http = PublicHttp(timeout=(6, 30))
    try:
        # A Cloudflare challenge raises SourceChallengeError in the transport;
        # the job fails with that reason and is never worked around here.
        text, _, headers = http.document(url)
    finally:
        if own:
            http.close()
    try:
        return json.loads(text), {k.lower(): v for k, v in (headers or {}).items()}
    except ValueError:
        raise SourceError('HentaiHaven вернул не JSON.') from None


def _pages(headers, bound):
    total = str(headers.get('x-wp-totalpages') or '')
    return min(bound, int(total)) if total.isdigit() else None


def _past_end(error, page):
    # WordPress answers 400 for a page past the end of a list.
    return page > 1 and getattr(error, 'http_status', None) == 400


def catalogue(spec, cursor, http=None):
    step = cursor.get('step') or 'terms'
    packed = cursor.get('terms') if isinstance(cursor.get('terms'), dict) else {}
    page = max(1, int(cursor.get('page', 1) or 1))
    if step == 'terms':
        index = int(cursor.get('taxonomy') or 0)
        if not 0 <= index < len(TAXONOMIES):
            index = 0
        taxonomy = TAXONOMIES[index]
        try:
            data, headers = _get(http, terms_url(taxonomy, page))
        except SourceError as error:
            if not _past_end(error, page):
                raise
            data, headers = [], {}
        found = series.term_names(data)
        known = unpack(packed.get(taxonomy))
        known.update({str(k): v for k, v in found.items()})
        last = _pages(headers, MAX_TERM_PAGES)
        more = bool(found) and page < (last if last is not None else MAX_TERM_PAGES)
        terms = {**packed, taxonomy: pack(known)}
        if more:
            state = {'step': 'terms', 'taxonomy': index, 'page': page + 1, 'terms': terms}
        elif index + 1 < len(TAXONOMIES):
            state = {'step': 'terms', 'taxonomy': index + 1, 'page': 1, 'terms': terms}
        else:
            state = {'step': 'clips', 'page': 1, 'terms': terms}
        vocabulary = [{'category': 'genre', 'label': GENRE}] if index == 0 and page == 1 else []
        if taxonomy != TAXONOMIES[2]:
            vocabulary += [{'category': 'tag', 'label': name} for name in dict.fromkeys(found.values())]
        return {'rows': [], 'next': state, 'emptySpan': True, **({'vocabulary': vocabulary} if vocabulary else {})}
    try:
        posts, headers = _get(http, page_url(page))
    except SourceError as error:
        if _past_end(error, page):
            from source_parser import SourceListingEnd
            raise SourceListingEnd(f'Дочитано до предела сайта: страница {page} списка пуста; прочитано {page - 1} стр.') from None
        raise
    if not isinstance(posts, list) or not posts:
        if page > 1:
            from source_parser import SourceListingEnd
            raise SourceListingEnd(f'Дочитано до предела сайта: страница {page} без роликов; прочитано {page - 1} стр.')
        raise SourceError('HentaiHaven не отдал список роликов Rule 34.')
    terms = {name: unpack(packed.get(name)) for name in TAXONOMIES}
    rows = [row for post in posts if (row := clip_row(post, terms))]
    last = max(int(cursor.get('last') or 0), _pages(headers, MAX_PAGES) or page)
    more = page < last
    state = {'step': 'clips', 'page': page + 1, 'last': last, 'terms': packed}
    return {'rows': rows, 'next': state if more else None, 'emptySpan': not rows}
