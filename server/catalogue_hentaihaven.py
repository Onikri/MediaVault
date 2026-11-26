"""The HentaiHaven (hentaihaven.xxx) series list as indexed anime series.

One request per call. HentaiHaven's WordPress back end (cms.hentaihaven.xxx)
publishes its hentai series as the post type wp-manga through the public REST
API, 100 a page in id order (new series are appended, nothing shifts). The
walk reads the «Released» year dictionary, then the genre dictionary, then
each list page and, in turn, the episodes («chapters») of its series.

A series is indexed only when at least one episode has a master the player
opens (hentai_video_sites.haven_chapters: the octopusmanifest.org HLS). The
site's older imports name a master-lengs.org playlist whose fragments are
served by a CDN that answered HTTP 523 in November 2026: a library card of
such a series would open no source, so it is left out until it is
re-imported. About 1 000 series: ~1 000 chapter requests a weekly walk.

Rule 34 clips (post type rule34-video), channels and «porn sites» are other
routes of the site and never part of this list. Each row carries the live
search result's identity and link ("hentaihaven:" + the /watch/<slug>/ URL),
so a library card opens our title page and the player the same way a search
result does.
"""
import html
import json
import re
from urllib.parse import urlencode

import hentai_video_sites as sites
from source_parser import SourceError

DOMAIN = 'hentaihaven.xxx'
API = sites.HAVEN_CMS + '/wp-json/wp/v2/'
PER_PAGE = 100
FIELDS = 'id,slug,type,title,link,meta,wp-manga-release,wp-manga-genre'
IMAGES = 'https://img.hentaihaven.xxx/'
# A sanity bound for the listing (1 242 «Released» tags in November 2026).
MAX_PAGES = 200


def terms_url(taxonomy):
    return API + taxonomy + '?' + urlencode({'per_page': 100, '_fields': 'id,name', 'hide_empty': 'true'})


def page_url(page):
    return API + 'wp-manga?' + urlencode({'per_page': PER_PAGE, 'page': page, 'orderby': 'id', 'order': 'asc', '_fields': FIELDS})


def term_names(terms):
    """{id: name} of a taxonomy answer."""
    found = {}
    for term in terms if isinstance(terms, list) else []:
        name = sites.clean(html.unescape(str(term.get('name') or '')), 80) if isinstance(term, dict) else ''
        if name and isinstance(term.get('id'), int):
            found[term['id']] = name
    return found


def cover_path(post):
    meta = post.get('meta') if isinstance(post.get('meta'), dict) else {}
    path = str(meta.get('vraven_remote_thumbnail') or '')
    return path if re.fullmatch(r'images/hh/[A-Za-z0-9/_.-]{1,240}\.(?:jpe?g|png|webp)', path) else ''


def listed(posts, years, genres):
    """Queue entries [slug, title, year, genre names, cover path] of one list page."""
    numeric = {int(k): v for k, v in years.items()}
    named = {int(k): v for k, v in genres.items()}
    by_slug = {str(post.get('slug')): post for post in posts if isinstance(post, dict)} if isinstance(posts, list) else {}
    entries = []
    for row in sites.haven_rows(posts, numeric):
        post = by_slug.get(row['slug'], {})
        names = list(dict.fromkeys(named[t] for t in post.get('wp-manga-genre') or [] if t in named))
        entries.append([row['slug'], row['title'], row.get('year'), names[:30], cover_path(post)])
    return entries


def series_row(entry, chapters):
    """The index row of a queued series, or None when no episode plays."""
    slug, title, year, genres, cover = (list(entry) + [None] * 5)[:5]
    if not chapters:
        return None
    url = sites.haven_series_url(slug)
    row = {'id': 'hentaihaven:' + url, 'provider': 'hentaihaven', 'kind': 'anime', 'title': title,
           'aliases': [title], 'url': url, 'sourceUrl': url, 'cover': IMAGES + cover if cover else '',
           'tags': [], 'genres': [g for g in genres or [] if isinstance(g, str)], 'description': '', 'age': 18,
           'episodes': len(chapters)}
    if isinstance(year, int):
        row['year'] = year
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
        return json.loads(text), headers
    except ValueError:
        raise SourceError('HentaiHaven вернул не JSON.') from None


def _chapters(http, slug):
    own = http is None
    if own:
        from source_parser import PublicHttp
        http = PublicHttp(timeout=(6, 30))
    try:
        return sites.haven_chapters(slug, http)
    finally:
        if own:
            http.close()


def catalogue(spec, cursor, http=None):
    step = cursor.get('step') or 'years'
    years = cursor.get('years') if isinstance(cursor.get('years'), dict) else {}
    genres = cursor.get('genres') if isinstance(cursor.get('genres'), dict) else {}
    if step == 'years':
        data, _ = _get(http, terms_url('wp-manga-release'))
        found = {str(k): int(v) for k, v in term_names(data).items() if re.fullmatch(r'(?:19|20)\d\d', v)}
        return {'rows': [], 'next': {'step': 'genres', 'years': found}, 'emptySpan': True}
    if step == 'genres':
        data, _ = _get(http, terms_url('wp-manga-genre'))
        found = {str(k): v for k, v in term_names(data).items()}
        return {'rows': [], 'next': {'step': 'series', 'page': 1, 'years': years, 'genres': found}, 'emptySpan': True,
                'vocabulary': [{'category': 'genre', 'label': name} for name in dict.fromkeys(found.values())]}
    page = max(1, int(cursor.get('page', 1)))
    last = int(cursor.get('last') or 0)
    queue = [item for item in cursor.get('queue') or [] if isinstance(item, list) and item and isinstance(item[0], str)]
    keep = {'step': 'series', 'years': years, 'genres': genres, **({'last': last} if last else {})}
    if queue:
        entry, queue = queue[0], queue[1:]
        try:
            chapters = _chapters(http, entry[0])
        except SourceError as error:
            # A series removed since it was listed is skipped, not the walk's end.
            if getattr(error, 'http_status', None) not in {404, 410}:
                raise
            chapters = []
        row = series_row(entry, chapters)
        more = bool(queue) or page <= last
        state = {**keep, 'page': page, **({'queue': queue} if queue else {})}
        return {'rows': [row] if row else [], 'next': state if more else None, 'emptySpan': not row}
    try:
        posts, headers = _get(http, page_url(page))
    except SourceError as error:
        # WordPress answers 400 for a page past the end of the list.
        if page > 1 and getattr(error, 'http_status', None) == 400:
            from source_parser import SourceListingEnd
            raise SourceListingEnd(f'Дочитано до предела сайта: страница {page} списка пуста; прочитано {page - 1} стр.') from None
        raise
    if not isinstance(posts, list) or not posts:
        if page > 1:
            from source_parser import SourceListingEnd
            raise SourceListingEnd(f'Дочитано до предела сайта: страница {page} без сериалов; прочитано {page - 1} стр.')
        raise SourceError('HentaiHaven не отдал список сериалов.')
    total = str({k.lower(): v for k, v in (headers or {}).items()}.get('x-wp-totalpages') or '')
    last = max(last, min(MAX_PAGES, int(total)) if total.isdigit() else page)
    fresh = listed(posts, years, genres)
    state = {**keep, 'last': last, 'page': page + 1, **({'queue': fresh} if fresh else {})}
    return {'rows': [], 'next': state if fresh or page < last else None, 'emptySpan': True}
