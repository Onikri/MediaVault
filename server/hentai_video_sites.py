"""Native adapters for hentai video sites that publish progressive MP4 files.

* hanime1.me — Japanese audio with Chinese subtitles burned in.
* HentaiMama (hentaimama.io) — English subtitles.
* Hentai.com.ua — Ukrainian dubs and subtitles.
* WatchHentai (watchhentai.net) — English subtitles and dubs.
* OHentai (ohentai.org) — English subtitles, old OVAs and 3D/western collections.
* HentaiHaven (hentaihaven.xxx) — English audio, WebVTT subtitles (Russian among them), HLS;
  its Rule 34 clips as a provider of their own (hentaihaven-rule34), never searched by title.
* MioHentai (miohentai.com) — English subtitles, MP4.

Search, episode lists and the MP4 address come from the sites' public HTML
(HentaiMama's public player AJAX, WatchHentai's own player page, OHentai's episode page,
HentaiHaven's and MioHentai's public WordPress REST APIs). MediaVault plays the file in its own
player: no third-party iframe is embedded, no account or cookie is used.
"""
import base64
import binascii
import html
import json
import re
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from source_parser import SourceError, playback_headers, public_url

HANIME1 = 'https://hanime1.me'
MAMA = 'https://hentaimama.io'
UA = 'https://hentai.com.ua'
WATCH = 'https://watchhentai.net'
OH = 'https://ohentai.org'
HAVEN = 'https://hentaihaven.xxx'
HAVEN_CMS = 'https://cms.hentaihaven.xxx'
MIO = 'https://miohentai.com'
PROVIDERS = {
    'hanime1': ('Hanime1 · JA', ('hanime1.me',)),
    'hentaimama': ('HentaiMama · EN', ('hentaimama.io',)),
    'hentaicomua': ('Hentai.com.ua · UA', ('hentai.com.ua',)),
    'watchhentai': ('WatchHentai · EN', ('watchhentai.net',)),
    'ohentai': ('OHentai · EN', ('ohentai.org',)),
    'hentaihaven': ('HentaiHaven · EN', ('hentaihaven.xxx',)),
    'hentaihaven-rule34': ('HentaiHaven · Rule 34', ('hentaihaven.xxx',)),
    'miohentai': ('MioHentai · EN', ('miohentai.com',)),
}
MAX_RESULTS = 12
MAX_EPISODES = 200


def clean(value, limit=300):
    return ' '.join(str(value or '').split())[:limit]


def _url(value, base, hosts):
    try:
        target = public_url(urljoin(base, html.unescape(str(value or '')).strip()), resolve_dns=False)
    except (SourceError, TypeError, ValueError):
        return ''
    parts = urlsplit(target)
    if parts.scheme != 'https' or parts.hostname not in hosts:
        return ''
    return target


def _media(value, base):
    """An HTTPS media file on any public host (sites keep video on their own CDN)."""
    try:
        target = public_url(urljoin(base, html.unescape(str(value or '')).strip()), resolve_dns=False)
    except (SourceError, TypeError, ValueError):
        return ''
    parts = urlsplit(target)
    return target if parts.scheme == 'https' and parts.path.lower().endswith('.mp4') else ''


def _number(text):
    """Trailing episode number: «Overflow 8», «Серія 4», «Episode 2», «【第08話】»."""
    text = clean(text)
    for pattern in (r'\b(?:серія|серия|episode|ep\.?)\s*(\d{1,3})', r'第\s*0*(\d{1,3})\s*[話话集]', r'\s(\d{1,3})\s*$'):
        match = re.search(pattern, text, re.I)
        if match:
            return int(match[1])
    return None


def _series(text):
    """Series name without the episode marker."""
    text = clean(text)
    text = re.sub(r'\s*\b(?:серія|серия|episode|ep\.?)\s*\d{1,3}\b', '', text, flags=re.I)
    text = re.sub(r'\s*【?第\s*\d{1,3}\s*[話话集]】?', '', text)
    text = re.sub(r'\s*\[[^\]]{1,30}\]\s*$', '', text)
    text = re.sub(r'\s+\d{1,3}\s*$', '', text)
    return clean(text.strip(' -–—:/'))


def _key(text):
    return re.sub(r'[\W_]+', ' ', _series(text).casefold()).strip()


def _row(provider, url, title, aliases, cover='', episodes=None):
    label = PROVIDERS[provider][0]
    names = list(dict.fromkeys(name for name in [title, *aliases] if name))
    row = {'provider': provider, 'providerName': label, 'url': url, 'title': title, 'aliases': names,
           'kind': 'anime', 'dubs': [], 'releaseDates': [], 'year': None}
    if cover:
        row['cover'] = cover
    if episodes:
        row['episodes'] = episodes
    return row


def provider_for(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host, path = parts.hostname or '', parts.path
    if host == 'hanime1.me' and path == '/watch' and re.fullmatch(r'\d{1,9}', (parse_qs(parts.query).get('v') or [''])[0]):
        return 'hanime1', PROVIDERS['hanime1'][0]
    # A few HentaiMama slugs keep a symbol percent-encoded ("star%e2%98%86jewel").
    if host == 'hentaimama.io' and re.fullmatch(r'/(?:tvshows|episodes)/(?:[a-z0-9-]|%[0-9a-f]{2}){1,160}/?', path, re.I):
        return 'hentaimama', PROVIDERS['hentaimama'][0]
    if host == 'hentai.com.ua' and re.fullmatch(r'/hentai_video/[^/]{1,240}/?', path):
        return 'hentaicomua', PROVIDERS['hentaicomua'][0]
    # WatchHentai: a series (/series/<slug>/) or an episode (/videos/<slug>/);
    # /series/page/N/ and the bare /videos/ index are listings, not titles.
    match = re.fullmatch(r'/(series|videos)/((?:[a-z0-9-]|%[0-9a-f]{2}){1,200})/?', path, re.I) if host == 'watchhentai.net' else None
    if match and match[2].lower() != 'page' and not parts.query:
        return 'watchhentai', PROVIDERS['watchhentai'][0]
    # OHentai: a series (/sery_video.php?seryid=<base64 id>) or an episode
    # (/detail.php?vid=<base64 id>), nothing else in the query.
    if host == 'ohentai.org' and _oh_parts(url):
        return 'ohentai', PROVIDERS['ohentai'][0]
    # HentaiHaven: a series (/watch/<slug>/) or its episode (/watch/<slug>/<episode>/);
    # a Rule 34 clip (/rule34/video/<slug>/) is its own provider. Channels,
    # «porn sites» and genre pages are not titles.
    if host == 'hentaihaven.xxx' and haven_parts(url):
        return 'hentaihaven', PROVIDERS['hentaihaven'][0]
    if host == 'hentaihaven.xxx' and rule34_slug(url):
        return RULE34, PROVIDERS[RULE34][0]
    # MioHentai: a series (/series/<slug>/) or an episode post by its id (/?p=<id>).
    if host == 'miohentai.com' and mio_parts(url):
        return 'miohentai', PROVIDERS['miohentai'][0]
    return None


# --- hanime1.me ---------------------------------------------------------------

def _hanime1_cards(soup, base):
    """(url, title, cover) of watch cards; sponsor cards link elsewhere and drop out."""
    found = {}
    # Search cards hold the name in `.title`; a watch page's playlist card keeps
    # the thumbnail (views, likes) apart from its `h4.video-title`.
    for card in soup.select('div.playlist-video-card, div.horizontal-card'):
        if card.find_parent(class_='playlist-video-card'):
            continue
        anchor = card.select_one('a[href*="watch?v="]')
        url = _url(anchor.get('href') if anchor else '', base, ('hanime1.me',))
        if not url or not provider_for(url):
            continue
        heading = card.select_one('.video-title, .title')
        if not heading:
            continue
        title = clean(heading.get_text(' ', strip=True))
        if not title:
            continue
        image = card.select_one('img')
        cover = _url(image.get('src') if image else '', base, ('vdownload.hembed.com',)) if image else ''
        found.setdefault(url, (url, title, cover))
    # Anime genre listings (裏番) show a poster grid: the whole card is the link.
    for card in soup.select('a[href*="watch?v="] > div.home-rows-videos-div'):
        url = _url(card.parent.get('href'), base, ('hanime1.me',))
        heading = card.select_one('.home-rows-videos-title')
        title = clean(heading.get_text(' ', strip=True)) if heading else ''
        if not url or not provider_for(url) or not title:
            continue
        image = card.select_one('img')
        cover = _url(image.get('src'), base, ('vdownload.hembed.com',)) if image else ''
        found.setdefault(url, (url, title, cover))
    return list(found.values())


def _latin(text):
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9 :!?'.,&+-]{2,}", text)
    return clean(match[0].strip(' -:')) if match else ''


def hanime1_search(query, http):
    text, final, _ = http.document(HANIME1 + '/search?' + urlencode({'query': query}))
    groups = hanime1_groups(_hanime1_cards(BeautifulSoup(text, 'html.parser'), final))
    return [hanime1_row(items) for items in list(groups.values())[:MAX_RESULTS]]


def hanime1_groups(cards):
    """(url, title, cover) cards as series in listing order, lowest episode first."""
    groups = {}
    for url, title, cover in cards:
        groups.setdefault(_key(title), []).append((_number(title) or 1, url, _series(title), cover))
    for items in groups.values():
        items.sort()
    return groups


def hanime1_row(items):
    """The search result of one series; it opens at its lowest episode."""
    _, url, name, cover = items[0]
    return _row('hanime1', url, name, [_latin(name)], cover, len(items))


def hanime1_episodes(url, http):
    text, final, _ = http.document(url)
    soup = BeautifulSoup(text, 'html.parser')
    heading = soup.select_one('#shareBtn-title') or soup.select_one('h3')
    title = clean(heading.get_text(' ', strip=True)) if heading else ''
    cards = _hanime1_cards(soup.select_one('#playlist-scroll') or soup, final)
    current = next((card for card in cards if card[0] == final or card[0] == url), None)
    series_key = _key(current[1]) if current else None
    episodes = {}
    for card_url, card_title, _ in cards:
        if series_key is not None and _key(card_title) != series_key:
            continue
        number = _number(card_title) or 1
        episodes.setdefault(number, {'number': number, 'season': 1, 'url': card_url, 'title': card_title})
    if not episodes:
        episodes[1] = {'number': 1, 'season': 1, 'url': url, 'title': title}
    name = _series(current[1]) if current else _series(title)
    return name or title, sorted(episodes.values(), key=lambda e: e['number'])[:MAX_EPISODES]


def hanime1_streams(url, http):
    text, final, _ = http.document(url)
    streams = []
    for source in BeautifulSoup(text, 'html.parser').select('video source[src]'):
        media = _media(source.get('src'), final)
        if not media:
            continue
        size = source.get('size') or ''
        streams.append({'url': media, 'type': 'mp4', 'quality': int(size) if size.isdigit() else None,
                        'headers': playback_headers({'Referer': HANIME1 + '/'})})
    return sorted(streams, key=lambda s: -(s['quality'] or 0))


# --- HentaiMama ---------------------------------------------------------------

def mama_search(query, http):
    text, final, _ = http.document(MAMA + '/?' + urlencode({'s': query}))
    results, seen = [], set()
    for card in BeautifulSoup(text, 'html.parser').select('article.series-card'):
        anchor = card.select_one('a[href*="/tvshows/"]')
        url = _url(anchor.get('href') if anchor else '', final, ('hentaimama.io',))
        heading = card.select_one('h3, .sc-title, .title')
        title = clean(heading.get_text(' ', strip=True) if heading else (anchor.get('title') if anchor else ''))
        if not url or not title or url in seen:
            continue
        seen.add(url)
        image = card.select_one('img')
        cover = _url((image.get('data-src') or image.get('src')) if image else '', final, ('hentaimama.io',))
        results.append(_row('hentaimama', url, title, [], cover))
        if len(results) >= MAX_RESULTS:
            break
    return results


def _mama_series_url(url, http):
    if '/tvshows/' in urlsplit(url).path:
        return url
    text, final, _ = http.document(url)
    for anchor in BeautifulSoup(text, 'html.parser').select('a[href*="/tvshows/"]'):
        series = _url(anchor.get('href'), final, ('hentaimama.io',))
        if series and provider_for(series):
            return series
    raise SourceError('HentaiMama не указал сериал этой серии.')


def mama_episodes(url, http):
    series = _mama_series_url(url, http)
    text, final, _ = http.document(series)
    soup = BeautifulSoup(text, 'html.parser')
    heading = soup.select_one('h1')
    title = clean(heading.get_text(' ', strip=True)) if heading else ''
    episodes = mama_episode_links(soup, final)
    if not episodes:
        raise SourceError('HentaiMama не показал серии этого тайтла.')
    return title, episodes


def mama_episode_links(soup, final):
    """Episodes a series page links (".../<slug>-episode-<n>/"), in number order."""
    episodes = {}
    for anchor in soup.select('a[href*="/episodes/"]'):
        link = _url(anchor.get('href'), final, ('hentaimama.io',))
        match = re.search(r'-episode-(\d{1,3})/?$', urlsplit(link).path) if link else None
        if match:
            number = int(match[1])
            episodes.setdefault(number, {'number': number, 'season': 1, 'url': link, 'title': 'Episode ' + str(number)})
    return sorted(episodes.values(), key=lambda e: e['number'])[:MAX_EPISODES]


def mama_streams(url, http):
    text, final, _ = http.document(url)
    post = re.search(r"get_player_contents['\"]?\s*,\s*a\s*:\s*['\"](\d{1,9})['\"]", text) or re.search(r'data-post="(\d{1,9})"', text)
    if not post:
        raise SourceError('HentaiMama не опубликовал плеер этой серии.')
    raw, _, _ = http.document(MAMA + '/wp-admin/admin-ajax.php', method='POST', headers={'Referer': final},
                              data={'action': 'get_player_contents', 'a': post[1], 'i': '1'})
    try:
        options = json.loads(raw)
    except ValueError:
        raise SourceError('HentaiMama вернул плеер в неожиданном формате.') from None
    streams = []
    for option in options if isinstance(options, list) else []:
        frame = re.search(r'src=["\']([^"\']+)', str(option))
        embed = _url(frame[1], MAMA, ('hentaimama.io',)) if frame else ''
        if not embed:
            continue
        page, _, _ = http.document(embed, headers={'Referer': final})
        for match in re.finditer(r'"file"\s*:\s*"([^"]+)"', page):
            media = _media(match[1].replace('\\/', '/'), embed)
            if media and all(s['url'] != media for s in streams):
                streams.append({'url': media, 'type': 'mp4', 'quality': None,
                                'headers': playback_headers({'Referer': MAMA + '/'})})
    return streams


# --- WatchHentai ---------------------------------------------------------------

WATCH_HOSTS = ('watchhentai.net',)
WATCH_PLAYER = re.compile(r'/player(?:-alt)?/\d{1,9}/\d{1,2}/mp4/?')


def _watch_page(value, base, kind):
    """A watchhentai.net series ('series') or episode ('videos') address, else ''."""
    url = _url(value, base, WATCH_HOSTS)
    return url if url and provider_for(url) and urlsplit(url).path.startswith('/' + kind + '/') else ''


def watch_cards(soup, base):
    """[url, title, cover, year] of the series cards of an archive or search page.

    Only the listing's own cards count: the sidebar's popular/new widgets and
    the menus link other series."""
    found = {}
    for card in soup.select('#dt-tvshows article.item.tvshows, #archive-content article.item.tvshows'):
        anchor = card.select_one('.data h3 a[href]') or card.select_one('a[href*="/series/"]')
        url = _watch_page(anchor.get('href') if anchor else '', base, 'series')
        title = clean((anchor.get('title') or anchor.get_text(' ', strip=True)) if anchor else '', 200)
        if not url or not title:
            continue
        image = card.select_one('.poster img')
        cover = _url((image.get('data-src') or image.get('src')) if image else '', base, WATCH_HOSTS)
        badge = card.select_one('.buttonyear')
        year = re.fullmatch(r'(?:19|20)\d\d', clean(badge.get_text() if badge else ''))
        found.setdefault(url, [url, title, cover, int(year[0]) if year else None])
    return list(found.values())


def watch_search(query, http):
    text, final, _ = http.document(WATCH + '/?' + urlencode({'s': query}))
    results = []
    for url, title, cover, year in watch_cards(BeautifulSoup(text, 'html.parser'), final)[:MAX_RESULTS]:
        row = _row('watchhentai', url, title, [], cover)
        row['year'] = year
        results.append(row)
    return results


def watch_episode_links(soup, final):
    """Episodes a series page lists (/videos/<slug>-episode-<n>[-id-NN]/), in number order.

    An announced episode is listed as «Episode 2 (PREVIEW)»: it plays the
    site's preview clip and keeps that mark in its title."""
    episodes = {}
    for anchor in soup.select('ul.episodios li a[href]'):
        link = _watch_page(anchor.get('href'), final, 'videos')
        if not link:
            continue
        label = anchor.select_one('.eptitle')
        label = clean(label.get_text(' ', strip=True) if label else anchor.get('title') or '', 120)
        match = (re.search(r'\bepisode\s*(\d{1,3})\b', label, re.I)
                 or re.search(r'-episode-(\d{1,3})(?:-id-\d{1,3})?/?$', urlsplit(link).path))
        if not match:
            continue
        number = int(match[1])
        preview = bool(re.search(r'\bpreview\b', label, re.I))
        episodes.setdefault(number, {'number': number, 'season': 1, 'url': link,
                                     'title': 'Episode ' + str(number) + (' (preview)' if preview else ''),
                                     **({'preview': True} if preview else {})})
    return sorted(episodes.values(), key=lambda e: e['number'])[:MAX_EPISODES]


def _watch_series_url(url, http):
    if urlsplit(url).path.startswith('/series/'):
        return url
    text, final, _ = http.document(url)
    soup = BeautifulSoup(text, 'html.parser')
    # The episode page's «All Episodes» button and its series card; not the sidebar.
    for anchor in soup.select('nav.pag_episodes .item-all a[href], .ep-series-card a[href]'):
        series = _watch_page(anchor.get('href'), final, 'series')
        if series:
            return series
    raise SourceError('WatchHentai не указал сериал этой серии.')


def watch_episodes(url, http):
    series = _watch_series_url(url, http)
    text, final, _ = http.document(series)
    soup = BeautifulSoup(text, 'html.parser')
    heading = soup.select_one('.sheader .data h1') or soup.select_one('h1')
    title = clean(heading.get_text(' ', strip=True)) if heading else ''
    episodes = watch_episode_links(soup, final)
    if not episodes:
        raise SourceError('WatchHentai не показал серии этого тайтла.')
    return title, episodes


def watch_decode(value, key=13, cycle=17):
    """The player page's whDecodeMediaUrl: base64url, XOR with (key + i % cycle), reversed base64."""
    value = str(value).replace('-', '+').replace('_', '/')
    try:
        raw = base64.b64decode(value + '=' * (-len(value) % 4), validate=True)
        mixed = ''.join(chr(byte ^ ((key + index % cycle) & 255)) for index, byte in enumerate(raw))[::-1]
        return base64.b64decode(mixed + '=' * (-len(mixed) % 4), validate=True).decode('utf-8')
    except (binascii.Error, UnicodeError, ValueError):
        return ''


def watch_player_sources(text, base):
    """[(MP4 URL, quality)] of a /player/<post>/<n>/mp4/ page, best first.

    The page lists its qualities in whJwSources with the address encoded; its
    JSON-LD contentUrl names a file the CDN does not serve, so it is not used."""
    decoder = re.search(r'function\s+whDecodeMediaUrl\s*\(\s*\w+\s*\)\s*\{(.{0,800}?)\}\s*(?:var|let|const|function)\b', text, re.S)
    key = re.search(r'\bk\s*=\s*(\d{1,3})\b', decoder[1]) if decoder else None
    cycle = re.search(r'\(\s*k\s*\+\s*\w+\s*%\s*(\d{1,3})\s*\)', decoder[1]) if decoder else None
    key, cycle = int(key[1]) if key else 13, int(cycle[1]) if cycle else 17
    listed = re.search(r'\bwhJwSources\s*=\s*(\[.{0,8000}?\])\s*;', text, re.S)
    try:
        entries = json.loads(listed[1]) if listed else []
    except ValueError:
        entries = []
    found = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get('file'), str):
            continue
        file = entry['file'] if entry['file'].startswith('https://') else watch_decode(entry['file'], key, cycle)
        media = _media(file, base)
        size = re.match(r'(\d{3,4})p', str(entry.get('label') or ''))
        if media:
            found.setdefault(media, int(size[1]) if size else None)
    return sorted(found.items(), key=lambda item: -(item[1] or 0))


def watch_streams(url, http):
    if not urlsplit(url).path.startswith('/videos/'):
        raise SourceError('WatchHentai: откройте серию, а не страницу сериала.')
    text, final, _ = http.document(url)
    frame = BeautifulSoup(text, 'html.parser').select_one('iframe[data-primary-player-url]')
    players = [frame.get(name) for name in ('data-primary-player-url', 'data-alternate-player-url')] if frame else []
    if not players:
        raise SourceError('WatchHentai не опубликовал плеер этой серии.')
    streams = []
    for player in players:
        target = _url(player, final, WATCH_HOSTS)
        if not target or not WATCH_PLAYER.fullmatch(urlsplit(target).path):
            continue
        page, page_url, _ = http.document(target, headers={'Referer': final})
        for media, quality in watch_player_sources(page, page_url):
            streams.append({'url': media, 'type': 'mp4', 'quality': quality,
                            'headers': playback_headers({'Referer': WATCH + '/'})})
        if streams:
            break  # The alternate player names the same files.
    return streams


# --- OHentai -------------------------------------------------------------------

OH_HOSTS = ('ohentai.org',)
OH_PAGES = {'/sery_video.php': 'seryid', '/detail.php': 'vid'}


def oh_number(value):
    """The integer a seryid/vid stands for (base64 of its decimal digits), else None."""
    value = unquote(str(value or ''))
    if not re.fullmatch(r'[A-Za-z0-9+/]{2,16}={0,2}', value):
        return None
    try:
        digits = base64.b64decode(value + '=' * (-len(value) % 4), validate=True).decode('ascii')
    except (binascii.Error, UnicodeError, ValueError):
        return None
    return int(digits) if re.fullmatch(r'\d{1,7}', digits) else None


def oh_address(path, number):
    """The site's own spelling of a series or episode address: ?seryid=MjIz, ?vid=MTQ5NA==."""
    return OH + path + '?' + OH_PAGES[path] + '=' + base64.b64encode(str(number).encode()).decode('ascii')


def _oh_parts(url):
    """(path, number) of an ohentai.org series or episode address, else None."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    key = OH_PAGES.get(parts.path)
    match = re.fullmatch(re.escape(key) + r'=([^&#]{2,48})', parts.query) if key else None
    if parts.scheme != 'https' or parts.hostname not in OH_HOSTS or parts.port or not match or parts.fragment:
        return None
    number = oh_number(match[1])
    return None if number is None else (parts.path, number)


def _oh_page(value, base, path):
    """The canonical address of an ohentai.org series ('/sery_video.php') or episode ('/detail.php') link, else ''."""
    found = _oh_parts(_url(value, base, OH_HOSTS))
    return oh_address(*found) if found and found[0] == path else ''


def _oh_asset(value, base):
    """An image of the site's own video_data folder, its spaces percent-encoded."""
    url = _url(value, base, OH_HOSTS)
    if not url:
        return ''
    parts = urlsplit(url)
    return parts._replace(path=quote(unquote(parts.path), safe='/!$&\'()*+,;=:@-._~'), query='', fragment='').geturl()


def _oh_brick_title(brick):
    title = brick.select_one('.videotitle')
    return clean((title.get('title') or title.get_text(' ', strip=True)) if title else '', 200)


def oh_episode_title(text):
    """«Makai Kishi Ingrid - Episode 3» → «Makai Kishi Ingrid»."""
    return clean(re.sub(r'\s+[-–—]\s+episode\s*\d{1,3}\s*$', '', clean(text), flags=re.I))


def oh_bricks(soup, base):
    """[(episode URL, title, image)] of a listing's video bricks; sponsored bricks link off the site."""
    found = {}
    for brick in soup.select('.videobrickwrap .videobrick'):
        anchor = brick.select_one('.videotitle a[href]') or brick.select_one('a[href]')
        url = _oh_page(anchor.get('href') if anchor else '', base, '/detail.php')
        title = _oh_brick_title(brick)
        if not url or not title:
            continue
        image = brick.select_one('.videocontentblock img')
        found.setdefault(url, (url, title, _oh_asset(image.get('src') if image else '', base)))
    return list(found.values())


def oh_search(query, http):
    """search.php lists episodes; they are grouped into their series, first episode as the address."""
    text, final, _ = http.document(OH + '/search.php?' + urlencode({'k': query}))
    groups = {}
    for url, title, cover in oh_bricks(BeautifulSoup(text, 'html.parser'), final):
        name = oh_episode_title(title)
        key = name.casefold()
        if key not in groups and len(groups) < MAX_RESULTS:
            groups[key] = _row('ohentai', url, name, [], cover)
    return list(groups.values())


def oh_series_episodes(soup, final):
    """Episodes of a series page in the site's order; the number is the position
    («Makai Kishi Ingrid:Re - Episode 1» is the fifth of «Makai Kishi Ingrid»)."""
    episodes = []
    for url, title, _ in oh_bricks(soup, final):
        episodes.append({'number': len(episodes) + 1, 'season': 1, 'url': url, 'title': title})
    return episodes[:MAX_EPISODES]


def oh_detail_episodes(soup, final):
    """The episode strip of an episode page (Episode1, Episode2…), the open one included."""
    episodes = []
    for anchor in soup.select('.descriptionsection .epscontainer a[href]'):
        url = _oh_page(anchor.get('href'), final, '/detail.php')
        if url and all(e['url'] != url for e in episodes):
            episodes.append({'number': len(episodes) + 1, 'season': 1, 'url': url,
                             'title': 'Episode ' + str(len(episodes) + 1)})
    return episodes[:MAX_EPISODES]


def oh_episodes(url, http):
    path, _ = _oh_parts(url) or (None, None)
    if not path:
        raise SourceError('OHentai: адрес не похож на сериал или серию.')
    text, final, _ = http.document(url)
    soup = BeautifulSoup(text, 'html.parser')
    if path == '/sery_video.php':
        heading = soup.select_one('.serydetailsection h1')
        episodes = oh_series_episodes(soup, final)
    else:
        heading = soup.select_one('.descriptionsection .sectiontitle')
        episodes = oh_detail_episodes(soup, final)
        if not episodes:
            # A single video outside any series.
            own = soup.select_one('h1.title')
            heading = heading or own
            episodes = [{'number': 1, 'season': 1, 'url': _oh_page(final, final, '/detail.php') or url,
                         'title': clean(own.get_text(' ', strip=True), 200) if own else 'Episode 1'}]
    title = clean(heading.get_text(' ', strip=True), 200) if heading else ''
    if not episodes:
        raise SourceError('OHentai не показал серии этого тайтла.')
    return title, episodes


def oh_player_sources(text, base):
    """MP4 files of an episode page's jwplayer, in page order (the selected server first).

    The page sets up jwplayer with one server and loads the other on a tab
    click: `sources: [{"file": "https://…mp4?token=…&expires=…"}]`. The
    advertising VAST tag is not a source."""
    found = []
    for listed in re.finditer(r'\bsources\s*:\s*(\[\s*\{.{0,4000}?\}\s*\])', text, re.S):
        try:
            entries = json.loads(listed[1])
        except ValueError:
            continue
        for entry in entries if isinstance(entries, list) else []:
            file = entry.get('file') if isinstance(entry, dict) else None
            if not isinstance(file, str):
                continue
            parts = urlsplit(file.strip())
            media = _media(parts._replace(path=quote(unquote(parts.path), safe='/!$&\'()*+,;=:@-._~')).geturl(), base)
            if media and media not in found:
                found.append(media)
    return found


def oh_streams(url, http):
    path, _ = _oh_parts(url) or (None, None)
    if path != '/detail.php':
        raise SourceError('OHentai: откройте серию, а не страницу сериала.')
    text, final, _ = http.document(url)
    # The address is signed for about an hour: it is read each time the episode starts.
    return [{'url': media, 'type': 'mp4', 'quality': None, 'headers': playback_headers({'Referer': OH + '/'})}
            for media in oh_player_sources(text, final)]


# --- Hentai.com.ua ------------------------------------------------------------

def _ua_names(title):
    """«Рейка – моя королева Серія 4 / Reika wa ... Episode 4» → series names, uk first."""
    parts = [clean(part) for part in re.split(r'\s+/\s+|\s+::\s+', title) if clean(part)]
    return [name for name in dict.fromkeys(_series(part) for part in parts) if name]


def _ua_cards(text, base):
    found = {}
    for card in BeautifulSoup(text, 'html.parser').select('article.hentai_video, article.card'):
        heading = card.select_one('h2 a[href], h3 a[href], .card-title a[href], a.text-body[href]')
        anchor = heading or card.select_one('a[href*="/hentai_video/"]')
        url = _url(anchor.get('href') if anchor else '', base, ('hentai.com.ua',))
        title = clean(anchor.get_text(' ', strip=True)) if anchor else ''
        if not url or not provider_for(url) or not title:
            continue
        image = card.select_one('img')
        cover = _url(image.get('src') if image else '', base, ('hentai.com.ua',))
        found.setdefault(url, (url, title, cover))
    return list(found.values())


def ua_search(query, http):
    text, final, _ = http.document(UA + '/?' + urlencode({'post_type': 'hentai_video', 's': query}))
    groups = {}
    for url, title, cover in _ua_cards(text, final):
        names = _ua_names(title)
        if names:
            groups.setdefault(_key(names[0]), []).append((_number(title) or 1, url, names, cover))
    results = []
    for items in list(groups.values())[:MAX_RESULTS]:
        items.sort()
        _, url, names, cover = items[0]
        results.append(_row('hentaicomua', url, names[0], names[1:], cover, len(items)))
    return results


def ua_episodes(url, http):
    text, final, _ = http.document(url)
    heading = BeautifulSoup(text, 'html.parser').select_one('h1')
    title = clean(heading.get_text(' ', strip=True)) if heading else ''
    names = _ua_names(title)
    current = {'number': _number(title) or 1, 'season': 1, 'url': final, 'title': title}
    episodes = {current['number']: current}
    if names:
        # The site has no series link on an episode: its own search lists the siblings.
        search, base, _ = http.document(UA + '/?' + urlencode({'post_type': 'hentai_video', 's': names[-1]}))
        for link, name, _ in _ua_cards(search, base):
            if _ua_names(name) and _key(_ua_names(name)[0]) == _key(names[0]):
                number = _number(name) or 1
                episodes.setdefault(number, {'number': number, 'season': 1, 'url': link, 'title': name})
    return (names[0] if names else title), sorted(episodes.values(), key=lambda e: e['number'])[:MAX_EPISODES]


def ua_streams(url, http):
    text, final, _ = http.document(url)
    streams = []
    for tab in BeautifulSoup(text, 'html.parser').select('.hv-player__tab[data-src]'):
        if tab.get('data-premium') not in (None, '', '0'):
            continue  # A premium track needs the site's paid account; it is not offered.
        media = _media(tab.get('data-src'), final)
        if media and all(s['url'] != media for s in streams):
            streams.append({'url': media, 'type': 'mp4', 'quality': None,
                            'headers': playback_headers({'Referer': UA + '/'})})
    return streams


# --- HentaiHaven ----------------------------------------------------------------
# The site is a Next.js front end over a WordPress back end (cms.hentaihaven.xxx)
# whose public REST API publishes the hentai series as the post type wp-manga:
# search, release years and each series' episodes («chapters») with their HLS
# master on octopusmanifest.org. Rule 34 clips are another post type
# (rule34-video, /rule34/video/…) and channels/«porn sites» other routes: the
# wp-manga search never returns them; provider_for gives /watch/ to the series
# and /rule34/video/<slug>/ to the Rule 34 provider below, nothing else.

HAVEN_HOSTS = ('hentaihaven.xxx',)
HAVEN_SLUG = r'[a-z0-9](?:[a-z0-9-]{0,198}[a-z0-9])?'
HAVEN_YEARS_TTL = 86400
_haven_years = {'at': 0.0, 'years': {}}
# Series titles seen by search, so an inspection names the series without
# another request (bounded; a miss only leaves the title to the card).
_haven_titles = {}


def haven_parts(url):
    """(series slug, episode slug or '') of a hentaihaven.xxx /watch/ address."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    match = re.fullmatch(r'/watch/(' + HAVEN_SLUG + r')/(?:(' + HAVEN_SLUG + r')/)?', parts.path)
    if parts.scheme != 'https' or parts.hostname not in HAVEN_HOSTS or parts.query or not match:
        return None
    return match[1], match[2] or ''


def haven_series_url(slug):
    return HAVEN + '/watch/' + slug + '/'


def _json(http, url):
    text, _, _ = http.document(url)
    try:
        return json.loads(text)
    except ValueError:
        raise SourceError('Источник вернул не JSON.') from None


def haven_years(http, now=None):
    """Release term id -> year (the site's «Released» years), cached for a day.

    Unknown years leave a result undated: the card's year then is not confirmed
    and the result is not accepted, rather than guessed."""
    import time
    now = time.time() if now is None else now
    if _haven_years['years'] and now - _haven_years['at'] < HAVEN_YEARS_TTL:
        return _haven_years['years']
    try:
        terms = _json(http, HAVEN_CMS + '/wp-json/wp/v2/wp-manga-release?' + urlencode({'per_page': 100, '_fields': 'id,name'}))
    except SourceError:
        return _haven_years['years']
    years = {}
    for term in terms if isinstance(terms, list) else []:
        name = clean(term.get('name') if isinstance(term, dict) else '', 8)
        if re.fullmatch(r'(?:19|20)\d\d', name) and isinstance(term.get('id'), int):
            years[term['id']] = int(name)
    if years:
        _haven_years.update(at=now, years=years)
    return years


def haven_rows(posts, years):
    """Series rows of wp-manga posts: only /watch/<slug>/ pages, earliest release year.

    A series tagged with several «Released» years (a 2020 OVA re-released in
    2025) is dated by its first release."""
    rows = []
    for post in posts if isinstance(posts, list) else []:
        if not isinstance(post, dict) or post.get('type', 'wp-manga') != 'wp-manga':
            continue
        slug = str(post.get('slug') or '')
        title = clean(html.unescape(str((post.get('title') or {}).get('rendered') or '')), 200)
        link = urlsplit(str(post.get('link') or ''))
        if not re.fullmatch(HAVEN_SLUG, slug) or not title or link.path != '/watch/' + slug + '/':
            continue
        dated = sorted(years[t] for t in post.get('wp-manga-release') or [] if t in years)
        row = _row('hentaihaven', haven_series_url(slug), title, [])
        row['year'] = dated[0] if dated else None
        row['slug'] = slug
        rows.append(row)
    return rows


def haven_search(query, http):
    posts = _json(http, HAVEN_CMS + '/wp-json/wp/v2/wp-manga?' + urlencode(
        {'search': query, 'per_page': MAX_RESULTS, '_fields': 'id,slug,type,title,link,wp-manga-release'}))
    rows = haven_rows(posts, haven_years(http))
    for row in rows:
        if len(_haven_titles) >= 512:
            _haven_titles.pop(next(iter(_haven_titles)))
        _haven_titles[row.pop('slug')] = row['title']
    return rows


def haven_episode_number(chapter, index):
    for value in (chapter.get('chapter_name'), chapter.get('episode_slug'), chapter.get('chapter_slug')):
        match = re.search(r'(?:episode|ep\.?|season)[\s-]*0*(\d{1,3})\b', str(value or ''), re.I)
        if match:
            return int(match[1])
    return index


def _haven_master(value):
    """An https HLS master the API names, else ''."""
    try:
        target = public_url(html.unescape(str(value or '')).strip(), resolve_dns=False)
    except (SourceError, TypeError, ValueError):
        return ''
    parts = urlsplit(target)
    return target if parts.scheme == 'https' and parts.path.endswith('/playlist.m3u8') and not parts.query else ''


def haven_chapters(slug, http):
    """[(number, episode slug, master)] of a series, in number order."""
    chapters = _json(http, HAVEN_CMS + '/wp-json/hhaven/v1/manga/by-slug/' + slug + '/chapters')
    found = {}
    for index, chapter in enumerate(chapters if isinstance(chapters, list) else [], 1):
        if not isinstance(chapter, dict) or chapter.get('is_deleted'):
            continue
        episode = str(chapter.get('episode_slug') or chapter.get('chapter_slug') or '')
        master = _haven_master(chapter.get('chapter_content') or chapter.get('indexable_content_url'))
        if re.fullmatch(HAVEN_SLUG, episode) and master:
            found.setdefault(haven_episode_number(chapter, index), (episode, master))
    return [(number, *found[number]) for number in sorted(found)][:MAX_EPISODES]


def haven_episodes(url, http):
    slug, _ = haven_parts(url) or (None, None)
    if not slug:
        raise SourceError('HentaiHaven: это не страница сериала.')
    episodes = [{'number': number, 'season': 1, 'url': haven_series_url(slug) + episode + '/', 'title': 'Episode ' + str(number)}
                for number, episode, _ in haven_chapters(slug, http)]
    if not episodes:
        raise SourceError('HentaiHaven не показал серии этого тайтла.')
    return _haven_titles.get(slug, ''), episodes


SUBTITLE_LANGUAGES = ('ru', 'uk', 'en')


def haven_subtitles(text, base):
    """WebVTT files a master lists as subtitle renditions (ru, uk, en)."""
    found = {}
    for line in text.splitlines():
        if not line.startswith('#EXT-X-MEDIA:') or 'TYPE=SUBTITLES' not in line:
            continue
        uri = re.search(r'URI="([^"]+)"', line)
        language = (re.search(r'LANGUAGE="([a-z]{2,3})', line) or [None, ''])[1]
        name = (re.search(r'NAME="([^"]{1,60})"', line) or [None, language])[1]
        if not uri or language not in SUBTITLE_LANGUAGES:
            continue
        target = _url(uri[1], base, (urlsplit(base).hostname,))
        if target and urlsplit(target).path.endswith('.vtt'):
            found.setdefault(language, {'url': target, 'language': language, 'name': name})
    return [found[language] for language in SUBTITLE_LANGUAGES if language in found]


def haven_streams(url, http):
    slug, episode = haven_parts(url) or (None, None)
    if not episode:
        raise SourceError('HentaiHaven: откройте серию, а не страницу сериала.')
    master = next((value for _, name, value in haven_chapters(slug, http) if name == episode), '')
    return _haven_stream(master, http) if master else []


def _haven_stream(master, http):
    headers = playback_headers({'Referer': HAVEN + '/'})
    stream = {'url': master, 'type': 'hls', 'quality': None, 'headers': headers}
    try:
        # Subtitles are separate WebVTT files (Russian among them): the player
        # shows them as its own tracks, the master's renditions are not used.
        text, final, _ = http.document(master, headers=headers)
        if text.lstrip().startswith('#EXTM3U'):
            stream['subtitles'] = haven_subtitles(text, final)
    except SourceError:
        pass
    return [stream]


# --- HentaiHaven · Rule 34 --------------------------------------------------------
# The site's Rule 34 section is the post type rule34-video of the same WordPress
# back end (/rule34/video/<slug>/, ~20 500 clips in November 2026). A clip is one
# video whose REST post names its HLS master on octopusmanifest.org
# (manifest_url, the player of the series); older imports name none and do not
# play. Clips are fan works about other franchises: only their own index row
# (catalogue_hentaihaven_rule34) opens one, no card finds them by its title (no
# search here, no index anchors: content_names.UNANCHORED).

RULE34 = 'hentaihaven-rule34'
RULE34_HOSTS = ('cms.hentaihaven.xxx', 'hentaihaven.xxx')
# Short enough for the index row id ("hentaihaven-rule34:" + the clip URL ≤ 200).
RULE34_SLUG = r'[a-z0-9](?:[a-z0-9-]{0,118}[a-z0-9])?'
RULE34_MASTER = re.compile(r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/playlist\.m3u8')
RULE34_MASTER_HOSTS = ('octopusmanifest.org',)
RULE34_FIELDS = 'id,slug,type,title,link,date,manifest_url'
RULE34_TTL = 600
# slug -> (time, clip or None): an inspection and its playback read the post once.
_rule34_posts = {}


def rule34_slug(url):
    """The clip slug of a hentaihaven.xxx /rule34/video/<slug>/ address, else ''."""
    try:
        parts = urlsplit(url)
    except (TypeError, ValueError):
        return ''
    match = re.fullmatch(r'/rule34/video/(' + RULE34_SLUG + r')/', parts.path)
    if parts.scheme != 'https' or parts.hostname not in HAVEN_HOSTS or parts.query or parts.fragment or not match:
        return ''
    return match[1]


def rule34_url(slug):
    return HAVEN + '/rule34/video/' + slug + '/'


def rule34_master(value):
    """The octopusmanifest.org HLS master a clip names, else ''."""
    master = _haven_master(value)
    parts = urlsplit(master) if master else None
    return master if parts and parts.hostname in RULE34_MASTER_HOSTS and RULE34_MASTER.fullmatch(parts.path) else ''


def rule34_clip(post):
    """{slug, title, year, master} of a rule34-video post that plays, else None."""
    if not isinstance(post, dict) or post.get('type') != 'rule34-video':
        return None
    slug = str(post.get('slug') or '')
    rendered = post['title'].get('rendered') if isinstance(post.get('title'), dict) else ''
    title = clean(html.unescape(str(rendered or '')), 200)
    link = urlsplit(str(post.get('link') or ''))
    if not re.fullmatch(RULE34_SLUG, slug) or not title or link.hostname not in RULE34_HOSTS or link.path != '/rule34/video/' + slug + '/':
        return None
    master = rule34_master(post.get('manifest_url'))
    if not master:
        return None
    year = re.match(r'((?:19|20)\d\d)-\d\d-\d\d', str(post.get('date') or ''))
    return {'slug': slug, 'title': title, 'year': int(year[1]) if year else None, 'master': master}


def rule34_post(slug, http, now=None):
    import time
    now = time.monotonic() if now is None else now
    hit = _rule34_posts.get(slug)
    if hit and now - hit[0] < RULE34_TTL:
        return hit[1]
    posts = _json(http, HAVEN_CMS + '/wp-json/wp/v2/rule34-video?' + urlencode({'slug': slug, '_fields': RULE34_FIELDS}))
    clip = next((found for post in posts if (found := rule34_clip(post)) and found['slug'] == slug), None) if isinstance(posts, list) else None
    if len(_rule34_posts) >= 256:
        _rule34_posts.pop(next(iter(_rule34_posts)))
    _rule34_posts[slug] = (now, clip)
    return clip


def rule34_episodes(url, http):
    slug = rule34_slug(url)
    if not slug:
        raise SourceError('HentaiHaven: это не страница ролика Rule 34.')
    clip = rule34_post(slug, http)
    if not clip:
        raise SourceError('HentaiHaven не опубликовал открытое видео этого ролика.')
    episodes = [{'number': 1, 'season': 1, 'url': rule34_url(slug), 'title': clip['title']}]
    return clip['title'], episodes, ({'year': clip['year']} if clip['year'] else {})


def rule34_streams(url, http):
    slug = rule34_slug(url)
    if not slug:
        raise SourceError('HentaiHaven: это не страница ролика Rule 34.')
    clip = rule34_post(slug, http)
    return _haven_stream(clip['master'], http) if clip else []


# --- MioHentai ------------------------------------------------------------------
# WordPress with a public REST API: the custom taxonomy «series» groups the
# episode posts. A post page names its MP4 as a signed cdn.miohentai.com
# address (the REST meta video_link answers 404). The site publishes upload
# dates only, never a release year.

MIO_HOSTS = ('miohentai.com',)
MIO_CDN = ('cdn.miohentai.com',)
MIO_SLUG = r'[a-z0-9](?:[a-z0-9-]{0,198}[a-z0-9])?'
_mio_series = {}  # slug -> term id seen by search (bounded)


def mio_parts(url):
    """('series', slug) or ('post', id) of a miohentai.com address."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme != 'https' or parts.hostname not in MIO_HOSTS:
        return None
    match = re.fullmatch(r'/series/(' + MIO_SLUG + r')/', parts.path)
    if match and not parts.query:
        return 'series', match[1]
    post = re.fullmatch(r'p=([1-9]\d{0,9})', parts.query)
    if parts.path == '/' and post:
        return 'post', post[1]
    return None


def mio_series_url(slug):
    return MIO + '/series/' + slug + '/'


def mio_search(query, http):
    terms = _json(http, MIO + '/wp-json/wp/v2/series?' + urlencode(
        {'search': query, 'per_page': MAX_RESULTS, '_fields': 'id,name,slug,count'}))
    rows = []
    for term in terms if isinstance(terms, list) else []:
        if not isinstance(term, dict) or not isinstance(term.get('id'), int) or not term.get('count'):
            continue
        slug = str(term.get('slug') or '')
        title = _series(html.unescape(str(term.get('name') or '')))
        if not re.fullmatch(MIO_SLUG, slug) or not title:
            continue
        if len(_mio_series) >= 512:
            _mio_series.pop(next(iter(_mio_series)))
        _mio_series[slug] = term['id']
        rows.append(_row('miohentai', mio_series_url(slug), title, [], episodes=term['count'] if term['count'] <= MAX_EPISODES else None))
    return rows


def mio_episode_number(title, index):
    return _number(title) or index


def mio_episodes(url, http):
    kind, slug = mio_parts(url) or (None, None)
    if kind != 'series':
        raise SourceError('MioHentai: это не страница сериала.')
    term = _mio_series.get(slug)
    title = ''
    if not term:
        found = _json(http, MIO + '/wp-json/wp/v2/series?' + urlencode({'slug': slug, '_fields': 'id,name'}))
        found = found[0] if isinstance(found, list) and found and isinstance(found[0], dict) else {}
        term, title = found.get('id'), _series(html.unescape(str(found.get('name') or '')))
    if not isinstance(term, int):
        raise SourceError('MioHentai не нашёл этот сериал.')
    posts = _json(http, MIO + '/wp-json/wp/v2/posts?' + urlencode(
        {'series': term, 'per_page': 100, 'orderby': 'date', 'order': 'asc', '_fields': 'id,title,date'}))
    episodes, years = {}, []
    for index, post in enumerate(posts if isinstance(posts, list) else [], 1):
        if not isinstance(post, dict) or not isinstance(post.get('id'), int):
            continue
        name = clean(html.unescape(str((post.get('title') or {}).get('rendered') or '')), 200)
        number = mio_episode_number(name, index)
        episodes.setdefault(number, {'number': number, 'season': 1, 'url': MIO + '/?p=' + str(post['id']), 'title': 'Episode ' + str(number)})
        title = title or _series(name)
        year = re.match(r'((?:19|20)\d\d)-', str(post.get('date') or ''))
        if year:
            years.append(int(year[1]))
    if not episodes:
        raise SourceError('MioHentai не показал серии этого тайтла.')
    # Upload dates bound the release from above; they never date it.
    return title, sorted(episodes.values(), key=lambda e: e['number'])[:MAX_EPISODES], {'uploadYear': min(years) if years else None}


def mio_media(value, base):
    """The signed MP4 address of a post page (cdn.miohentai.com/index.php?data=<hex>)."""
    target = _url(value, base, MIO_CDN)
    parts = urlsplit(target) if target else None
    if parts and parts.path == '/index.php' and re.fullmatch(r'data=[0-9a-f]{16,2048}', parts.query):
        return target
    return _media(target, base) if target else ''


def mio_streams(url, http):
    kind, _ = mio_parts(url) or (None, None)
    if kind != 'post':
        raise SourceError('MioHentai: откройте серию, а не страницу сериала.')
    text, final, _ = http.document(url)
    if urlsplit(final).hostname not in MIO_HOSTS:
        raise SourceError('MioHentai перенаправил на другой сайт.')
    player = BeautifulSoup(text, 'html.parser').select_one('video#video-player[data-video-src], video[data-video-src]')
    media = mio_media(player.get('data-video-src') if player else '', final)
    return [{'url': media, 'type': 'mp4', 'quality': None, 'headers': playback_headers({'Referer': MIO + '/'})}] if media else []


SEARCH = {'hanime1': hanime1_search, 'hentaimama': mama_search, 'hentaicomua': ua_search, 'watchhentai': watch_search,
          'ohentai': oh_search, 'hentaihaven': haven_search, 'miohentai': mio_search}
EPISODES = {'hanime1': hanime1_episodes, 'hentaimama': mama_episodes, 'hentaicomua': ua_episodes,
            'watchhentai': watch_episodes, 'ohentai': oh_episodes, 'hentaihaven': haven_episodes, 'miohentai': mio_episodes,
            RULE34: rule34_episodes}
STREAMS = {'hanime1': hanime1_streams, 'hentaimama': mama_streams, 'hentaicomua': ua_streams,
           'watchhentai': watch_streams, 'ohentai': oh_streams, 'hentaihaven': haven_streams, 'miohentai': mio_streams,
           RULE34: rule34_streams}


def search(provider, query, http):
    # Rule 34 clips have no title search: their own index row opens them.
    query = clean(query, 160)
    return SEARCH[provider](query, http) if provider in SEARCH and len(query) >= 2 else []


def episodes(provider, url, http):
    return EPISODES[provider](url, http)


def streams(provider, url, http):
    found = STREAMS[provider](url, http)
    if not found:
        raise SourceError(PROVIDERS[provider][0] + ' не опубликовал открытое видео этой серии.')
    return found
