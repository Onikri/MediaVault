"""Public episode pages whose players publish their streams at runtime."""
import re
from urllib.parse import urlsplit

from source_parser import Page, SourceAccessError, SourceError, parse_page

HENTASIS_HOST = re.compile(r'(?:[a-z0-9-]+\.)?hentasis\d{0,3}\.(?:top|me)')


def provider_for(url):
    parts = urlsplit(url)
    host = parts.hostname or ''
    if host in {'hanime.tv', 'www.hanime.tv'} and re.fullmatch(
        r'/(?:videos/hentai|hentai/video|playlists/[a-zA-Z0-9]+/video)/[^/]+/?', parts.path
    ):
        return 'hanime', 'HanimeTV'
    # Hentasis moves between numbered mirrors (hentasis1.top, v4.hentasis.me,
    # v5.hentasis5.top in November 2026); accept the whole family, not one host.
    if HENTASIS_HOST.fullmatch(host) and re.search(r'/\d+-[^/]+\.html$', parts.path, re.I):
        return 'hentasis', 'Hentasis'
    return None


# Current mirrors first; a mirror that is down or redirected elsewhere is skipped.
HENTASIS_MIRRORS = ('https://v5.hentasis5.top', 'https://hentasis1.top', 'https://v4.hentasis.me')
HENTASIS_TITLE = re.compile(r'(.+?)\s*\(\s*((?:19|20)\d{2})\s*г?\.?\s*\)\s*$')


def search_hentasis(query, http):
    """DLE search on the first working mirror. Cards are `a.sres-wrap` with an
    `h2` of "Русское / Romaji (2026г.)"; the year comes from that title, not
    from the card's publication date."""
    from site_adapters import Site, parse_search
    failure = None
    for root in HENTASIS_MIRRORS:
        host = urlsplit(root).hostname
        site = Site('hentasis', 'Hentasis', root, (host,), 'a.sres-wrap', 'h2')
        try:
            text, final, _ = http.document(site.search_url(query))
        except SourceError as error:
            failure = error
            continue
        if urlsplit(final).hostname != host:
            continue
        results = []
        for row in parse_search(site, text, final, query):
            match = HENTASIS_TITLE.fullmatch(row['title'])
            names = [name.strip() for name in (match[1] if match else row['title']).split(' / ') if name.strip()]
            if names:
                results.append({**row, 'title': names[0], 'aliases': names, 'year': int(match[2]) if match else None})
        return results
    raise failure or SourceError('Зеркала Hentasis не ответили.')


def inspect(url, provider, http, dub_url=None, state=None):
    from player_catalog import choice

    identifier, label = provider
    if dub_url and dub_url != url:
        raise SourceError('На этой странице нет выбранной дорожки.')
    title = label
    diagnostics = []
    try:
        if state is not None and state.get('_root'):
            text, final = state['_root']
        else:
            text, final, _ = http.document(url)
            if state is not None:
                state['_root'] = (text, final)
        if provider_for(final) != provider:
            raise SourceError('Источник перенаправил на другую страницу.')
        title = parse_page(text, final).title or label
    except SourceError:
        diagnostics.append({'status': 'unavailable', 'message': 'Доступ к плееру проверяется при запуске.'})
    episodes = [{'number': 1, 'season': 1, 'url': url, 'title': title}]
    if identifier == 'hanime':
        # Other episodes of the same series come from the HanimeTV catalogue feed.
        try:
            from hanime_source import episodes_for, series_name
            series = episodes_for(url, http)
            if series:
                episodes = series
                title = series_name(series[0]['title']) or title
        except SourceError:
            pass
    return {'provider': identifier, 'title': title, 'url': url, 'episodes': episodes,
            'dubs': [choice('Дорожка источника', url, player=label, episodes=episodes)],
            'seasons': [], 'releases': [], 'complete': True, 'available': True, 'diagnostics': diagnostics}


def check_mp4(http, stream, *, open_stream=None):
    response, final = (open_stream or http._open)(
        stream['url'], headers=stream.get('headers'), byte_range='bytes=0-1023')
    try:
        mime = response.headers.get('Content-Type', '').partition(';')[0].lower()
        if response.status_code != 206 or not re.fullmatch(
            r'bytes 0-\d+/[1-9]\d*', response.headers.get('Content-Range', ''), re.I
        ) or mime not in {'video/mp4', 'application/octet-stream', 'binary/octet-stream'}:
            raise SourceError('Источник не отдал MP4 с поддержкой перемотки.')
        return final
    finally:
        response.close()


def resolve_dynamic(http, url, referer, title, provider=None):
    from browser_player import extract

    if provider == 'hanime':
        # Cloudflare challenges the Oracle address for every HanimeTV page and
        # signed API call. The handshake and playlists go through the owner's
        # Worker (hanime_relay); Oracle still fetches the video segments itself.
        import hanime_relay
        if hanime_relay.settings():
            return Page(title=title, streams=hanime_relay.resolve(url))
        from hanime_player import extract as extract_hanime
        try:
            streams = extract_hanime(url)
            for stream in streams:
                if stream['type'] == 'mp4':
                    check_mp4(http, stream)
            return Page(title=title, streams=streams)
        except SourceAccessError:
            raise SourceError(hanime_relay.HINT) from None
        except (SourceError, ImportError):
            pass
    mode = 'auto'
    if provider == 'hentasis':
        mode = 'hentasis-mirror' if urlsplit(url).hostname == 'v4.hentasis.me' else 'mp4'
    result = extract(url, referer, details=True, mode=mode)
    for stream in result['streams']:
        if stream['type'] == 'mp4':
            check_mp4(http, stream)
    return Page(title=title, streams=result['streams'], subtitles=result.get('subtitles', []))
