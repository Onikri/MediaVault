"""Native adapters for hentai video sites that publish progressive MP4 files.

* hanime1.me — Japanese audio with Chinese subtitles burned in.
* HentaiMama (hentaimama.io) — English subtitles.
* Hentai.com.ua — Ukrainian dubs and subtitles.

Search, episode lists and the MP4 address come from the sites' public HTML
(and HentaiMama's public player AJAX). MediaVault plays the file in its own
player: no third-party iframe is embedded, no account or cookie is used.
"""
import html
import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from source_parser import SourceError, playback_headers, public_url

HANIME1 = 'https://hanime1.me'
MAMA = 'https://hentaimama.io'
UA = 'https://hentai.com.ua'
PROVIDERS = {
    'hanime1': ('Hanime1 · JA', ('hanime1.me',)),
    'hentaimama': ('HentaiMama · EN', ('hentaimama.io',)),
    'hentaicomua': ('Hentai.com.ua · UA', ('hentai.com.ua',)),
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
    if host == 'hentaimama.io' and re.fullmatch(r'/(?:tvshows|episodes)/[a-z0-9-]{1,160}/?', path, re.I):
        return 'hentaimama', PROVIDERS['hentaimama'][0]
    if host == 'hentai.com.ua' and re.fullmatch(r'/hentai_video/[^/]{1,240}/?', path):
        return 'hentaicomua', PROVIDERS['hentaicomua'][0]
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
    episodes = {}
    for anchor in soup.select('a[href*="/episodes/"]'):
        link = _url(anchor.get('href'), final, ('hentaimama.io',))
        match = re.search(r'-episode-(\d{1,3})/?$', urlsplit(link).path) if link else None
        if match:
            number = int(match[1])
            episodes.setdefault(number, {'number': number, 'season': 1, 'url': link, 'title': 'Episode ' + str(number)})
    if not episodes:
        raise SourceError('HentaiMama не показал серии этого тайтла.')
    return title, sorted(episodes.values(), key=lambda e: e['number'])[:MAX_EPISODES]


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


SEARCH = {'hanime1': hanime1_search, 'hentaimama': mama_search, 'hentaicomua': ua_search}
EPISODES = {'hanime1': hanime1_episodes, 'hentaimama': mama_episodes, 'hentaicomua': ua_episodes}
STREAMS = {'hanime1': hanime1_streams, 'hentaimama': mama_streams, 'hentaicomua': ua_streams}


def search(provider, query, http):
    query = clean(query, 160)
    return SEARCH[provider](query, http) if len(query) >= 2 else []


def episodes(provider, url, http):
    return EPISODES[provider](url, http)


def streams(provider, url, http):
    found = STREAMS[provider](url, http)
    if not found:
        raise SourceError(PROVIDERS[provider][0] + ' не опубликовал открытое видео этой серии.')
    return found
