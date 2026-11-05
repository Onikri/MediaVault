"""Public episode pages whose players publish their streams at runtime."""
import re
from urllib.parse import urlsplit

from source_parser import Page, SourceError, parse_page


def provider_for(url):
    parts = urlsplit(url)
    host = parts.hostname or ''
    if host in {'hanime.tv', 'www.hanime.tv'} and re.fullmatch(
        r'/(?:videos/hentai|hentai/video|playlists/[a-zA-Z0-9]+/video)/[^/]+/?', parts.path
    ):
        return 'hanime', 'HanimeTV'
    if (host in {'hentasis1.top', 'www.hentasis1.top', 'hentasis.me'} or host.endswith('.hentasis.me')) and re.search(
        r'/\d+-[^/]+\.html$', parts.path, re.I
    ):
        return 'hentasis', 'Hentasis'
    return None


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
    return {'provider': identifier, 'title': title, 'url': url, 'episodes': episodes,
            'dubs': [choice('Дорожка источника', url, player=label, episodes=episodes)],
            'seasons': [], 'releases': [], 'complete': True, 'available': True, 'diagnostics': diagnostics}


def check_mp4(http, stream):
    response, _ = http._open(stream['url'], headers=stream.get('headers'), byte_range='bytes=0-1023')
    try:
        mime = response.headers.get('Content-Type', '').partition(';')[0].lower()
        if response.status_code != 206 or not re.fullmatch(
            r'bytes 0-\d+/[1-9]\d*', response.headers.get('Content-Range', ''), re.I
        ) or mime not in {'video/mp4', 'application/octet-stream', 'binary/octet-stream'}:
            raise SourceError('Источник не отдал MP4 с поддержкой перемотки.')
    finally:
        response.close()


def resolve_dynamic(http, url, referer, title, provider=None):
    from browser_player import extract

    if provider == 'hanime':
        from hanime_player import extract as extract_hanime
        try:
            streams = extract_hanime(url)
            for stream in streams:
                if stream['type'] == 'mp4':
                    check_mp4(http, stream)
            return Page(title=title, streams=streams)
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
