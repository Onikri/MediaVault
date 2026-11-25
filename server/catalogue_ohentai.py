"""The OHentai (ohentai.org) series list as indexed anime series.

One request per call. The walk reads the whole series list (series.php, one
page of about 4 200 series, A–Z), then the tag dictionary (alltags.php, one
page), then each series page in id order: a series page names the tags, the
year, the Japanese title, the cover and the episodes. The site has no studio
or synopsis field on a series page (its tags name some studios and artists
among the themes; they stay tags). Each row carries the live search result's
identity and link ("ohentai:" + the sery_video.php address), so a library card
opens our title page and the player the same way a search result does.

The site is plain PHP: no WordPress REST API or sitemap with these fields, so
its own list pages stay the source. The cursor keeps the listed ids as a
bitmap (a few hundred bytes) and the next id to read, not the list itself.
"""
import base64
import binascii
import re
import zlib

from bs4 import BeautifulSoup

import hentai_video_sites as sites
from source_parser import SourceError

DOMAIN = 'ohentai.org'
SERIES_LIST = sites.OH + '/series.php'
TAG_LIST = sites.OH + '/alltags.php'
HOSTS = (DOMAIN,)
# A sanity bound for series ids (the list ended at 5 218 in November 2026).
MAX_ID = 1_000_000
# series.php is ~460 KB: above the transport's default page limit.
LIST_LIMIT = 4_000_000


def series_url(number):
    return sites.oh_address('/sery_video.php', number)


def series_ids(soup, base):
    """Series ids of series.php in page order (each series is listed once, A–Z)."""
    found = {}
    for anchor in soup.select('.videoseryconatiner .sererytitle a[href]'):
        url = sites._oh_page(anchor.get('href'), base, '/sery_video.php')
        if url:
            found.setdefault(sites._oh_parts(url)[1], None)
    return list(found)


def tags(soup):
    """The tag dictionary of alltags.php (themes, and some studios and artists)."""
    found = [sites.clean(a.get_text(' ', strip=True), 80) for a in soup.select('.videoseryconatiner a.tagtext[href*="tagsearch.php"]')]
    return list(dict.fromkeys(name for name in found if name))


def pack(ids):
    bits = bytearray((max(ids) >> 3) + 1 if ids else 0)
    for number in ids:
        bits[number >> 3] |= 1 << (number & 7)
    return base64.b64encode(zlib.compress(bytes(bits), 9)).decode('ascii')


def unpack(value):
    try:
        bits = zlib.decompress(base64.b64decode(str(value or ''), validate=True))
    except (binascii.Error, ValueError, zlib.error):
        raise SourceError('OHentai: курсор обхода повреждён.') from None
    return bits


def next_id(bits, start):
    """The first listed id at or after start, else None."""
    for number in range(max(0, start), len(bits) * 8):
        if bits[number >> 3] & (1 << (number & 7)):
            return number
    return None


def _field(section, label):
    for line in section.select('.longdes'):
        name = line.select_one('span')
        if name and sites.clean(name.get_text(' ', strip=True)).rstrip(':').casefold() == label:
            name.extract()
            return sites.clean(line.get_text(' ', strip=True), 200)
    return ''


def series_row(text, final):
    """The index row of one series page, or None when it is not a series page."""
    url = sites._oh_page(final, final, '/sery_video.php')
    soup = BeautifulSoup(text, 'html.parser')
    section = soup.select_one('.serylistcontainer .serydetailsection')
    heading = section.select_one('h1') if section else None
    title = sites.clean(heading.get_text(' ', strip=True) if heading else '', 200)
    if not url or not title:
        return None
    japanese = _field(section, 'japanese name')
    year = re.fullmatch(r'(?:19|20)\d\d', _field(section, 'year'))
    tag_names = list(dict.fromkeys(name for a in section.select('.tagcontainer a[href*="tagsearch.php"]')
                                   if (name := sites.clean(a.get_text(' ', strip=True), 80))))
    poster = soup.select_one('.serylistcontainer > img')
    cover = sites._oh_asset(poster.get('src') if poster else '', final)
    episodes = len(sites.oh_series_episodes(soup, final))
    counted = re.fullmatch(r'\d{1,3}', _field(section, 'episode included'))
    if not episodes and counted and 0 < int(counted[0]) <= sites.MAX_EPISODES:
        episodes = int(counted[0])
    # The client keys a source result as provider:url; no providerId, so the
    # title page does not ask a catalogue API that OHentai does not have.
    row = {'id': 'ohentai:' + url, 'provider': 'ohentai', 'kind': 'anime', 'title': title,
           'aliases': list(dict.fromkeys(name for name in (title, japanese) if name)), 'url': url, 'sourceUrl': url,
           'cover': cover, 'tags': tag_names, 'genres': [], 'studios': [], 'age': 18}
    if episodes:
        row['episodes'] = episodes
    if year:
        row['year'] = int(year[0])
    return row


def _document(http, url, **options):
    own = http is None
    if own:
        from source_parser import PublicHttp
        http = PublicHttp(timeout=(6, 40))
    try:
        # A Cloudflare challenge raises SourceChallengeError in the transport;
        # the job fails with that reason and is never worked around here.
        return http.document(url, **options)
    finally:
        if own:
            http.close()


def catalogue(spec, cursor, http=None):
    step = max(1, int(cursor.get('page', 1) or 1))
    if step == 1 or not cursor.get('map'):
        text, final, _ = _document(http, SERIES_LIST, limit=LIST_LIMIT)
        ids = [number for number in series_ids(BeautifulSoup(text, 'html.parser'), final) if number <= MAX_ID]
        if not ids:
            raise SourceError('OHentai не отдал список сериалов.')
        return {'rows': [], 'emptySpan': True, 'total': len(ids),
                'next': {'page': 2, 'map': pack(ids), 'from': 0}}
    bits = unpack(cursor['map'])
    if step == 2:
        try:
            text, _, _ = _document(http, TAG_LIST, limit=LIST_LIMIT)
            vocabulary = tags(BeautifulSoup(text, 'html.parser'))
        except SourceError as error:
            # The dictionary only adds labels: a removed page does not stop the walk.
            if getattr(error, 'http_status', None) not in {404, 410}:
                raise
            vocabulary = []
        return {'rows': [], 'emptySpan': True, 'next': {**cursor, 'page': 3},
                'vocabulary': [{'category': 'tag', 'label': name} for name in vocabulary]}
    number = next_id(bits, int(cursor.get('from') or 0))
    if number is None:
        return {'rows': [], 'emptySpan': True, 'next': None}
    try:
        text, final, _ = _document(http, series_url(number))
    except SourceError as error:
        # A series removed since the list was read is skipped, not the walk's end.
        if getattr(error, 'http_status', None) not in {404, 410}:
            raise
        text, final = '', ''
    row = series_row(text, final) if text else None
    more = next_id(bits, number + 1) is not None
    state = {'page': step + 1, 'map': cursor['map'], 'from': number + 1}
    return {'rows': [row] if row else [], 'next': state if more else None, 'emptySpan': not row}
