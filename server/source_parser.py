"""Public HTML/player resolver with isolated source-only HTTP.

Explicit registry: Kodik, Aniboom, Sibnet, Animedia, CVH, VK and AniLiberty.
Only the enumerated public playback APIs are permitted. Google credentials
never enter this module. Signed media links are resolved at download time.
"""
from __future__ import annotations

import html
import ipaddress
import json
import math
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from anime_dl_core.http import DEFAULT_USER_AGENT
from ua_players import COLLAPS_HOSTS

try:
    import soupsieve as _soupsieve
except ImportError:  # pragma: no cover - bs4 always installs it
    _soupsieve = None
if _soupsieve is not None and hasattr(_soupsieve, 'NOSTRICT') and not getattr(_soupsieve.compile, 'mediavault', False):
    # soupsieve 4 rejects combinators inside :has() unless NOSTRICT is set.
    # The source adapters were written against the previous lenient rules,
    # so keep those rules for every BeautifulSoup .select() in the server.
    _strict_compile = _soupsieve.compile

    def _lenient_compile(pattern, namespaces=None, flags=0, **kwargs):
        return _strict_compile(pattern, namespaces, flags | _soupsieve.NOSTRICT, **kwargs)

    _lenient_compile.mediavault = True
    _soupsieve.compile = _lenient_compile


class SourceError(RuntimeError):
    # Machine-readable status of a source failure (see source_status()).
    status = 'error'


class SourceAccessError(SourceError):
    status = 'access_denied'


class SourceTemporaryError(SourceError):
    """A network failure or temporary upstream response."""
    status = 'temporary'


class SourceRedirectError(SourceError):
    """An upstream redirect that the requested route does not allow."""
    status = 'redirect'


class SourceChallengeError(SourceAccessError):
    """A browser challenge (Cloudflare, DDoS-Guard) the transport could not pass."""
    status = 'challenge'

    def __init__(self, message='Источник требует проверку браузера.', *, solver='none'):
        super().__init__(message)
        # none | unavailable | timeout | failed | busy | budget | cooldown | rejected
        self.solver = solver


class SourceRegionError(SourceAccessError):
    """The source refuses the exit's country (HTTP 451, Cloudflare 1009, geo pages)."""
    status = 'region_blocked'


class SourcePaidError(SourceAccessError):
    """A paid or subscription-only chapter. Never bypassed."""
    status = 'paid_chapter'


class SourceAuthError(SourceAccessError):
    """The request needs a signed-in account. Never bypassed."""
    status = 'auth_required'


class SourceParserError(SourceError):
    """The upstream answered, but not in the format the adapter understands."""
    status = 'parser_error'


class SourceRouteError(SourceTemporaryError):
    """The declared exit (the Japan tunnel) is down: an explicit temporary failure."""
    status = 'route_unavailable'


def source_status(error):
    """Status of any adapter failure, including older adapters' plain SourceErrors."""
    if not isinstance(error, SourceError):
        return 'parser_error' if isinstance(error, (ValueError, KeyError, TypeError, AttributeError)) else 'error'
    if type(error) is SourceError and re.search(r'изменил[аи]? формат|неожиданн\w* формат', str(error), re.I):
        return 'parser_error'
    return error.status


class SourceRateLimitError(SourceError):
    status = 'rate_limited'

    def __init__(self, retry_after, *, http_status=429):
        super().__init__(f"Источник вернул HTTP {http_status}.")
        try:
            delay = int(retry_after)
        except (TypeError, ValueError):
            try:
                delay = math.ceil(parsedate_to_datetime(retry_after).timestamp() - time.time())
            except (TypeError, ValueError, OverflowError, OSError):
                delay = 60
        self.retry_after = min(2**31 - 1, max(1, delay))


# Use the same public browser UA as the player adapters' returned stream headers.
# Some embeds reject a non-browser UA before their HTML can be parsed.
USER_AGENT = DEFAULT_USER_AGENT
MAX_DOCUMENT = 4 * 1024 * 1024
# Set by hanime_relay.install on the server: tokenised HanimeTV playlists,
# which refuse the Oracle address, are read through the owner's Worker.
RELAY_ROUTE = None
MAX_VIDEO = 40 * 1024**3
BLOCKED = re.compile(
    r"/cdn-cgi/challenge-platform(?!/scripts/(?:jsd|precursor)/)|cf-chl-|__cf_chl_|checking your browser|"
    r"enable javascript and cookies to continue|verify (?:that )?you are human|"
    r"<title[^>]*>\s*(?:just a moment|access denied)|"
    r"[\"'](?:subscription_required|requires_subscription|requires_authentication)[\"']\s*:\s*true",
    re.I,
)
PLAYER_RELAY_HOSTS={'yummyanime.tv','animego.online'}
# CDNs that block an (IP, User-Agent) pair after request bursts. Every request
# to them from this server (playback proxy, Drive import, device download)
# shares one pacer: at most one request per PACE_SECONDS.
PACED_HOSTS=('.vkvideo.cloud',)
PACE_SECONDS=0.25
_pace_lock=threading.Lock();_pace_next=[0.0]
# Whole-film transfers (Drive import, device download) must look like one
# viewer: a 2026-11-05 burst of two parallel 4K film pulls at 4 req/s burned a
# fresh UA within minutes, while playback (~1 segment/6 s) never did.
BULK_PACE_SECONDS=4.0
_bulk_next=[0.0]
def pace(url,bulk=False):
    if not (urlsplit(url).hostname or '').endswith(PACED_HOSTS):return
    with _pace_lock:
        slot=_bulk_next if bulk else _pace_next;step=BULK_PACE_SECONDS if bulk else PACE_SECONDS
        now=time.monotonic();wait=max(slot[0],_pace_next[0])-now;slot[0]=max(now,slot[0],_pace_next[0])+step
        if not bulk:_pace_next[0]=max(_pace_next[0],slot[0])
        else:_pace_next[0]=max(_pace_next[0],now+max(0,wait))+PACE_SECONDS
    if wait>0:time.sleep(wait)

def is_alloha_player(url):
    host=urlsplit(url).hostname or ''
    return host=='alloha.yani.tv' or host.endswith(('.stravers.live','.thealloha.club','.alloha.tv'))


def public_url(value, *, resolve_dns=True, allow_api=False):
    """Validate every request and every redirect, including nested HLS URLs."""
    if not isinstance(value, str) or len(value) > 8192:
        raise SourceError("Некорректная ссылка источника.")
    try:
        url = urlsplit(value.strip())
        host = (url.hostname or "").lower()
        port = url.port
    except ValueError:
        raise SourceError("Некорректная ссылка источника.") from None
    if (url.scheme != "https" or url.username or url.password or port not in (None, 443)
            or not host or "." not in host or host.endswith(".")
            or host.endswith((".local", ".internal", ".localhost"))):
        raise SourceError("Поддерживаются только публичные HTTPS-ссылки без логина и пароля.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise SourceError("IP-адреса не поддерживаются; укажи публичный домен.")
    # Only these public playback APIs are allowed; arbitrary site APIs remain blocked.
    playback_api = (
        host == "plapi.cdnvideohub.com" and bool(re.fullmatch(r"/api/v1/player/sv/(?:playlist|video/\d+)", url.path))
        or host == "ru.yummyani.me" and bool(re.fullmatch(r"/api/anime/[1-9]\d{0,9}/videos", url.path))
        or host == "guest.freeanimehentai.net" and url.path == "/api/v11/search_hvs"
        or host in {"anilibria.top", "aniliberty.top", "api.anilibria.app"}
        and bool(re.fullmatch(r"/api/v1/(?:anime/releases/[a-zA-Z0-9_-]+|app/search/releases)", url.path))
        # Collaps public embed (one film/serial page) and the Kinobox player balancer.
        or host in COLLAPS_HOSTS
        and bool(re.fullmatch(r"/embed/(?:movie|kp|imdb)/[a-zA-Z0-9]{1,24}", url.path))
        or host == "fbphdplay.top" and url.path in {"/api/players", "/api/movies/search"}
        # Ukrainian manga readers' public catalogues (Zenko).
        # Light-novel text APIs (RanobeHub, Smakolyky).
        or host == "ranobehub.org" and bool(re.fullmatch(r"/api/(?:search|books/\d{1,9}/chapters|chapters/\d{1,9})", url.path))
        or host == "api.syosetu.com" and url.path == "/novelapi/api/"
        or host == "api.smakolykytl.site" and bool(re.fullmatch(r"/api/user/(?:projects(?:/\d{1,9}/books)?|chapters/\d{1,9})", url.path))
        # Hikka: Ukrainian catalogue of anime, manga and novels (public search and details).
        or host == "api.hikka.io" and bool(re.fullmatch(r"/(?:novel|anime|manga)(?:/[a-z0-9-]{1,120})?|/integrations/mal/(?:anime|manga|novel)/\d{1,9}", url.path))
        or host == "api.zenko.online" and bool(re.fullmatch(r"/(?:titles(?:/\d{1,9}(?:/chapters)?)?|chapters/\d{1,9})", url.path))
        # ReManga's public catalogue, translator branches, free chapter pages and covers.
        or host == "api.remanga.org" and bool(re.fullmatch(r"/api/v2/search/(?:catalog/)?|/api/forms/titles/|/api/v2/titles/(?:chapters/(?:[1-9]\d{0,11}/)?|[^/]{1,300}/)|/media/[\w./-]{1,300}", url.path))
    )
    if not allow_api and not playback_api and (host.startswith(("api.", "plapi.")) or re.search(r"/(?:api|graphql)(?:/|$)", url.path, re.I)):
        from manga_iken import public_api as iken_public_api
        from manga_vinetheme import public_api as vine_public_api
        from manga_hentaihand import public_api as hentaihand_public_api
        from manga_comici import public_route as comici_public_route
        from manga_gigaviewer import public_route as giga_public_route
        from manga_guya import public_api as guya_public_api
        from manga_mangadventure import public_api as adventure_public_api
        from manga_mangak import public_api as mangak_public_api
        from manga_mangamillion import public_api as million_api
        from manga_webcomic_protocols import public_api as webcomics_api
        from manga_series_port import series_api
        adapters = (iken_public_api, vine_public_api, hentaihand_public_api, guya_public_api,
                    adventure_public_api, mangak_public_api, million_api, webcomics_api, series_api)
        if not (any(route(host, url.path, url.query) for route in adapters)
                or comici_public_route(host, url.path, url.query, 'comici-json')
                or giga_public_route(host, url.path, url.query, 'giga-json')):
            raise SourceError("Этот API не входит в список поддерживаемых публичных плееров.")
    if resolve_dns:
        try:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            raise SourceError("Не удалось найти сервер источника.") from None
        if not addresses or any(not ipaddress.ip_address(entry[4][0]).is_global for entry in addresses):
            raise SourceError("Локальные и служебные адреса источников запрещены.")
    return urlunsplit(("https", host, url.path or "/", url.query, ""))


_COLLAPS_ORIGINS = frozenset(f"https://{host}" for host in COLLAPS_HOSTS)


def playback_headers(headers=None):
    """Allow only public playback headers; never forward cookies or authorization."""
    result = {"User-Agent": USER_AGENT}
    for key, value in (headers or {}).items():
        if key.lower() == 'cache-control' and value == 'no-cache':
            result['Cache-Control'] = value
            continue
        name = {"referer": "Referer", "origin": "Origin", "user-agent": "User-Agent"}.get(key.lower())
        if not name:
            continue
        if not isinstance(value, str) or len(value) > 8192 or "\r" in value or "\n" in value:
            raise SourceError("Некорректный заголовок плеера.")
        if name in {"Referer", "Origin"}:
            if name == "Referer":
                from manga_source_urls import split_reader_url
                try:
                    _, value = split_reader_url(value)
                except ValueError:
                    raise SourceError("Некорректная ссылка читалки.") from None
            # Origin is sanitized again on every manifest/segment request.
            # The bare Collaps origin is a header, never a request target.
            collaps_origin = name == "Origin" and value.removesuffix("/") in _COLLAPS_ORIGINS
            value = requests.utils.requote_uri(public_url(value, resolve_dns=False, allow_api=collaps_origin))
            if name == "Origin":
                parsed = urlsplit(value)
                value = f"{parsed.scheme}://{parsed.netloc}"
        result[name] = value
    return result


class _SourcePoolAdapter(requests.adapters.HTTPAdapter):
    # Pool TLS/TCP connections, not Session objects, cookies or credentials.
    # The process owns this adapter; closing one short-lived Session must not
    # destroy connections currently used by another source request.
    def close(self):pass

_SOURCE_POOL=_SourcePoolAdapter(pool_connections=48,pool_maxsize=12,pool_block=False,max_retries=0)


META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_-]{2,30})""", re.I)


def decode_document(raw, declared=None):
    """Decode a page the way a browser would: header charset, then <meta>, then
    UTF-8, falling back to windows-1251 for older Russian sites that omit it."""
    if declared and declared.upper() != "ISO-8859-1":
        try:
            return raw.decode(declared, errors="replace")
        except LookupError:
            pass
    match = META_CHARSET.search(raw[:4096])
    if match:
        try:
            return raw.decode(match.group(1).decode("ascii"), errors="replace")
        except LookupError:
            pass
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        if text.count("\ufffd") > 3:
            try:
                return raw.decode("cp1251")
            except UnicodeDecodeError:
                pass
        return text


class PublicHttp:
    def __init__(self, *, session=None, validate=public_url, timeout=(6, 20), deadline=None, source=None, operation=None):
        self.session = session or requests.Session()
        if session is None:
            self.session.mount('https://',_SOURCE_POOL)
            self.session.mount('http://',_SOURCE_POOL)
        self.validate = validate
        self.timeout = timeout
        self.deadline = deadline
        # Which source/operation the requests serve (source_transport routes).
        # A client created inside an adapter call inherits the caller's scope.
        if source is None:
            from source_transport import current
            source, operation = current()
        self.source = None if source is None else str(source)
        self.operation = operation
        # Session is source-only and is never shared with Google Drive.
        self.session.headers.clear()

    def close(self):
        self.session.close()

    def fork(self):
        value=PublicHttp(validate=self.validate,timeout=self.timeout,deadline=self.deadline,source=self.source,operation=self.operation);value.bulk=getattr(self,'bulk',False);return value

    def scope(self, source, operation):
        """``with http.scope(source_id, 'search'):`` routes requests by the source's declarations."""
        from source_transport import scope
        return scope(self, source, operation)

    def _open(self, value, *, headers=None, method="GET", data=None, byte_range=None, timeout=None, action=None, expect=None):
        speedbinb = action in {'speedbinb-info', 'speedbinb-body'}
        speedbinb_site = action in {'speedbinb-site', 'speedbinb-xhr'}
        speedbinb_routed = speedbinb or speedbinb_site or action == 'speedbinb-image'
        if speedbinb:
            from manga_speedbinb import api_route
            if method != 'GET' or data is not None or not api_route(value, (headers or {}).get('Referer'), action):
                raise SourceError('Некорректный маршрут читалки SpeedBinb.')
        if speedbinb_site:
            from manga_speedbinb import reader_url
            reader_url(value)
        clipstudio = action in {'clipstudio-cgi', 'clipstudio-epub'}
        if action == 'mangahere-xhr':
            from manga_mangahere import xhr_route

            if method != 'GET' or data is not None or not xhr_route(value, (headers or {}).get('Referer', '')):
                raise SourceError('Некорректный маршрут читалки MangaHere.')
        if clipstudio:
            from manga_clipstudio import cgi_route, epub_route

            clip_ref = (headers or {}).get('Referer', '')
            clip_token = (headers or {}).get('ClipStudio-Token', '')
            valid = cgi_route(value, clip_ref) if action == 'clipstudio-cgi' else epub_route(value, clip_token)
            if method != 'GET' or data is not None or not valid:
                raise SourceError('Некорректный публичный маршрут Clip Studio Reader.')
        publus = action in {'publus-config', 'publus-image'}
        if publus:
            from manga_publus_reader import permitted

            if method != 'GET' or data is not None or not permitted(value, action):
                raise SourceError('Некорректный адрес открытой читалки Publus.')
            from manga_network_routes import configuration, routed
            publus_routes = configuration()
        ninth = None
        if isinstance(action, str) and action.startswith('n9:'):
            # Sources ported in the ninth batch declare their exact routes,
            # headers, guest cookies and forms in one place.
            from manga_ninth_routes import prepare as ninth_prepare

            ninth = ninth_prepare(action, value, method, data, headers or {})
        trusted_api = speedbinb or clipstudio or publus or bool(ninth)
        url = public_url(value, allow_api=True) if trusted_api and self.validate is public_url else self.validate(value)
        japanese_public = (action in {'cycomi-reader', 'nicovideo-public', 'japanese-published-image'}
                           or action == 'native-series-json' and urlsplit(url).netloc in {'comic-walker.com', 'web.cycomi.com'}
                           or bool(ninth and ninth.japan))
        if japanese_public:
            from manga_network_routes import configuration, routed

            japanese_routes = configuration()
        if (RELAY_ROUTE is not None and method == 'GET' and not byte_range
                and not speedbinb_routed and not clipstudio and not publus and not japanese_public and not ninth
                and action not in {'mangamillion-proto', 'mangaplus-proto', 'mangaplus-image', 'mangamee-proto', 'globalcomix-json',
                                   'madaradex-web', 'madaradex-cdn', 'fanfox-reader', 'ysk-json',
                                   'webnex-doc', 'webnex-json', 'webnex-image', 'hotcomics-doc', 'zerosum-proto',
                                   'mangaone-proto', 'mangabox-read', 'corocoro-proto', 'ciaoplus-json',
                                   'firecross-guest-title', 'firecross-guest-reader', 'comicfesta-document', 'honto-public',
                                   'hakusensha-public', 'alphapolis-guest-title', 'coronaex-public',
                                   'publus-source-json', 'publus-source-document',
                                   'pixivcomic-public', 'pixivcomic-store', 'bookwalker-public-view',
                                   'mangahere-xhr', 'viz-page', 'toonz-rsc', 'akuma-guest',
                                   'manhwazone-document', 'honeytoon-sync', 'toomics-public-view', 'toomics-display'}):
            routed = RELAY_ROUTE(url, headers)
            if routed is not None:
                return routed
        if clipstudio:
            outgoing = playback_headers({key: val for key, val in (headers or {}).items() if key.lower() != 'referer'})
            outgoing.update({'Referer': public_url(clip_ref, resolve_dns=False, allow_api=True),
                             'X-Requested-With': 'XMLHttpRequest', 'Accept-Language': 'ja,en;q=0.8'})
            if action == 'clipstudio-epub' and clip_token:
                outgoing['Authorization'] = 'Bearer ' + clip_token
        else:
            outgoing = playback_headers(headers)
        if ninth:
            outgoing.update(ninth.headers)
            data = ninth.data
        if japanese_public:
            outgoing['Accept-Language'] = 'ja,en;q=0.8'
        if action == 'nicovideo-public':
            from manga_japanese_readers import public_api as japanese_api

            endpoint = urlsplit(url)
            if (method != 'GET' or data is not None or endpoint.netloc not in {'sp.manga.nicovideo.jp', 'api.nicomanga.jp'}
                    or not japanese_api(endpoint.netloc, endpoint.path, endpoint.query)):
                raise SourceError('Некорректный маршрут открытого API Nicovideo.')
            outgoing.update({'User-Agent': ('Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 '
                                            '(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36'),
                             'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
        akuma_session = action == 'akuma-guest'
        if akuma_session:
            from manga_akuma import guest_route

            csrf = (headers or {}).get('X-CSRF-TOKEN', '')
            if not guest_route(url, method, data, csrf):
                raise SourceError('Некорректный запрос гостевой сессии источника.')
            if method == 'GET':
                self.session.cookies.clear()
            else:
                outgoing.update({'X-CSRF-TOKEN': csrf, 'X-Requested-With': 'XMLHttpRequest',
                                 'Origin': 'https://akuma.moe'})
        if action == 'publus-config':
            outgoing.update({'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
        publus_source = action in {'publus-source-json', 'publus-source-document'}
        if publus_source:
            from manga_publus_sources import BOOST, NETTAI, PASH, public_api as publus_source_api

            origin = urlsplit(url)
            allowed = origin.netloc in {urlsplit(base).netloc for base in (BOOST, NETTAI, PASH)}
            if (not allowed or method != 'GET' or data is not None or
                    action == 'publus-source-json' and not publus_source_api(origin.netloc, origin.path, origin.query)):
                raise SourceError('Некорректный запрос издателя Publus.')
            if action == 'publus-source-json':
                outgoing.update({'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
        if action in {'pixivcomic-public', 'pixivcomic-store'}:
            from manga_pixivcomic import API_HOST, CLIENT_HASH, CLIENT_TIME, KEY, public_api as pixivcomic_api

            origin = urlsplit(url)
            if method != 'GET' or data is not None:
                raise SourceError('Некорректный запрос Pixiv Comic.')
            if action == 'pixivcomic-store':
                if origin.netloc != API_HOST or origin.query or not re.fullmatch(rf'/store/viewers/{KEY}/master', origin.path):
                    raise SourceError('Некорректный адрес тома Pixiv Comic.')
            else:
                if not pixivcomic_api(origin.netloc, origin.path, origin.query):
                    raise SourceError('Некорректный запрос каталога Pixiv Comic.')
                outgoing.update({'Accept': 'application/json', 'X-Requested-With': 'pixivcomic'})
                if origin.path.endswith('/read_v4'):
                    when, digest = ((headers or {}).get(key, '') for key in ('X-Client-Time', 'X-Client-Hash'))
                    if not isinstance(when, str) or not CLIENT_TIME.fullmatch(when) or not isinstance(digest, str) or not CLIENT_HASH.fullmatch(digest):
                        raise SourceError('Некорректные параметры открытого выпуска Pixiv Comic.')
                    outgoing.update({'X-Client-Time': when, 'X-Client-Hash': digest})
        if action == 'bookwalker-public-view':
            from manga_bookwalker_jp import VIEWER_HOSTS

            origin = urlsplit(url)
            if method != 'GET' or data is not None or origin.netloc not in VIEWER_HOSTS:
                raise SourceError('Некорректный запрос Auth-адреса BookWalker.')
        webnex_document = action in {'webnex-doc', 'webnex-json'}
        if webnex_document:
            from manga_webnex import public_api as webnex_api

            origin = urlsplit(url)
            if (method != 'GET' or origin.netloc != 'webnex.cc'
                    or action == 'webnex-json' and not webnex_api(origin.netloc, origin.path, origin.query)):
                raise SourceError('Некорректный публичный запрос Webnex.')
            if action == 'webnex-json':
                outgoing.update({'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
        if action == 'hotcomics-doc':
            origin = urlsplit(url)
            if method != 'GET' or origin.netloc != 'hotcomics.io' or not re.match(r'/en(?:/|$)', origin.path):
                raise SourceError('Некорректный публичный запрос HotComics.')
            outgoing['Cookie'] = 'hc_vfs=Y'
        manhwazone_session = action in {'manhwazone-document', 'manhwazone-livewire'}
        if manhwazone_session:
            from manga_manhwazone import HOSTS as manhwazone_hosts, TITLE as manhwazone_title
            from manga_manhwazone import livewire_form

            target = urlsplit(url)
            if action == 'manhwazone-document':
                if method != 'GET' or target.netloc not in manhwazone_hosts or not re.fullmatch(manhwazone_title, target.path):
                    raise SourceError('Некорректная карточка ManhwaZone.')
            else:
                if method != 'POST' or not livewire_form(url, data, outgoing.get('Referer', '')):
                    raise SourceError('Некорректный публичный запрос оглавления ManhwaZone.')
                outgoing.update({'X-Livewire': '', 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json',
                                 'Content-Type': 'application/json', 'Origin': 'https://' + target.netloc})
        if action == 'webnex-image':
            from manga_webnex import cookie_header, public_api as webnex_api
            origin = urlsplit(url)
            cookie = (headers or {}).get('Cookie')
            if (method != 'GET' or origin.netloc != 'webnex.cc'
                    or not webnex_api(origin.netloc, origin.path, origin.query) or not cookie_header(cookie)):
                raise SourceError('Некорректный маршрут изображения Webnex.')
            outgoing['Cookie'] = cookie
        if urlsplit(url).hostname == 'img.xchina.io':
            outgoing['Accept'] = 'image/avif,image/webp,image/png,image/jpeg,*/*'
        if urlsplit(url).hostname == 'cdn.donmai.us':
            outgoing.update({'Accept': 'image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5',
                             'Sec-Fetch-Dest': 'image', 'Sec-Fetch-Mode': 'no-cors', 'Sec-Fetch-Site': 'same-site'})
        if action == 'honeytoon-sync':
            from manga_honeytoon_native import SYNC, public_api as honeytoon_api

            origin = urlsplit(url)
            if method != 'GET' or origin.path != SYNC or not honeytoon_api(origin.netloc, origin.path, origin.query):
                raise SourceError('Некорректный публичный маршрут страницы Honeytoon.')
            outgoing['Accept'] = 'image/*, application/octet-stream'
        toomics_session = action in {'toomics-public-view', 'toomics-display'}
        if toomics_session:
            from manga_toomics import routed as toomics_route

            if method != 'GET' or data is not None or not toomics_route(url, action):
                raise SourceError('Некорректный маршрут открытой читалки Toomics.')
        if speedbinb:
            outgoing.update({'Accept': 'application/json, text/javascript, */*',
                             'X-Requested-With': 'XMLHttpRequest'})
        if action == 'speedbinb-xhr':
            outgoing.update({'Accept': 'text/html, text/javascript, */*',
                             'X-Requested-With': 'XMLHttpRequest'})
        if speedbinb_routed:
            from manga_network_routes import configuration, routed
            speedbinb_config = configuration()
            outgoing['Accept-Language'] = 'ja,en;q=0.8'
        if action == 'fanfox-reader':
            from manga_html_readers import FOX_READER
            target = urlsplit(url)
            if (method != 'GET' or data is not None or target.netloc != 'm.fanfox.net' or target.query
                    or not FOX_READER.fullmatch(target.path)):
                raise SourceError('Некорректная ссылка на мобильную читалку FanFox.')
            outgoing['Cookie'] = 'readway=2; isAdult=1'
        mdx_mode = ''
        if action in {'madaradex-web', 'madaradex-cdn', 'madaradex-refresh'} or (
                action == 'madara-read' and headers and 'X-MediaVault-Mdx-Cookie' in headers):
            from manga_madaradex_guest import COOKIE_HEADER, transport_mode
            mdx_mode = transport_mode(url, method, data, action, headers or {})
            if not mdx_mode:
                raise SourceError('Некорректный маршрут гостевой сессии MadaraDex.')
            outgoing['Cookie'] = headers[COOKIE_HEADER]
            if mdx_mode == 'refresh':
                outgoing.update({'X-Requested-With': 'XMLHttpRequest', 'Origin': 'https://madaradex.org'})
        if action == 'webcomic-json':
            from manga_webcomic_protocols import public_api
            target = urlsplit(url)
            if method != 'GET' or data is not None or not public_api(target.netloc, target.path, target.query):
                raise SourceError('Некорректный маршрут JSON-каталога.')
            outgoing.update({'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
        if action == 'creator-feed-json':
            from manga_creator_feeds import public_api
            target = urlsplit(url)
            if method != 'GET' or data is not None or not public_api(target.netloc, target.path, target.query):
                raise SourceError('Некорректный маршрут каталога авторов.')
            outgoing.update({'Accept': 'text/css', 'X-Requested-With': 'XMLHttpRequest'})
        if action in {'native-series-json', 'native-series-html-api'}:
            from manga_series_port import series_api
            target = urlsplit(url)
            if method != 'GET' or data is not None or not series_api(target.netloc, target.path, target.query):
                raise SourceError('Некорректный маршрут публичного API каталога.')
            outgoing.update({'Accept': 'application/json' if action.endswith('json') else 'text/html, */*',
                             'X-Requested-With': 'XMLHttpRequest'})
            if target.netloc == 'reimanga.net':
                outgoing['Cookie'] = 'showAdultContent=true'
        if action == 'ysk-json':
            from manga_catalogue_api_ports import YSK, YSK_SEARCH, public_api
            target = urlsplit(url)
            language = (headers or {}).get('x-localization')
            if (method != 'GET' or data is not None or language not in {'ar', 'en'}
                    or target.netloc not in {YSK, YSK_SEARCH} or not public_api(target.netloc, target.path, target.query)):
                raise SourceError('Некорректный публичный маршрут YSK Comics.')
            outgoing.update({'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'x-localization': language})
        if action in {'mangaplus-proto', 'mangaplus-image'}:
            from manga_mangaplus import SESSION, TOKEN, page_host, public_api
            target = urlsplit(url)
            allowed_method = method == 'GET' and data is None
            if action == 'mangaplus-proto':
                if (not allowed_method or not public_api(target.netloc, target.path, target.query)
                        or (headers or {}).get('Session-Token') != SESSION):
                    raise SourceError('Некорректный маршрут MANGA Plus.')
                outgoing.update({'Accept': 'application/x-protobuf, application/octet-stream, */*', 'Session-Token': SESSION})
            else:
                token = (headers or {}).get('Plus-Vw-Token', '')
                if not allowed_method or not page_host(target.hostname or '') or token and not TOKEN.fullmatch(token):
                    raise SourceError('Некорректная страница MANGA Plus.')
                if token:
                    outgoing['Plus-Vw-Token'] = token
        if action == 'native-series-rsc':
            from manga_additional_catalogues import public_rsc as additional_rsc
            from manga_direct_payloads import public_api
            from manga_japanese_next import public_rsc as japanese_rsc
            from manga_clipstudio_sources import comicfesta_rsc
            from manga_lusttoon import public_api as lusttoon_rsc
            from manga_mangamee import public_rsc as mangamee_rsc
            from manga_reimanga import public_rsc as rei_rsc
            from manga_scanlation_json import public_rsc
            target = urlsplit(url)
            revival = target.netloc == 'www.revivalscans.com' and public_api(target.netloc, target.path, target.query)
            route = (target.netloc, target.path, target.query)
            if method != 'GET' or data is not None or not (
                    revival or public_rsc(*route) or additional_rsc(*route) or mangamee_rsc(*route)
                    or rei_rsc(*route) or japanese_rsc(*route) or target.netloc == 'lustoon.com' and lusttoon_rsc(*route)
                    or comicfesta_rsc(*route)):
                raise SourceError('Некорректный маршрут React Flight.')
            outgoing.update({'RSC': '1', 'Accept': 'text/x-component'})
            if rei_rsc(*route):
                outgoing['Cookie'] = 'showAdultContent=true'
        firecross_session = action in {'firecross-guest-title', 'firecross-guest-reader'}
        if firecross_session:
            from manga_clipstudio_sources import firecross_route

            if not firecross_route(url, method, data, action, outgoing.get('Referer', '')):
                raise SourceError('Некорректный запрос открытой главы FireCross.')
            if action == 'firecross-guest-reader':
                outgoing.update({'Accept': 'application/json', 'Origin': 'https://firecross.jp',
                                 'X-Requested-With': 'XMLHttpRequest'})
        if action == 'comicfesta-document':
            from manga_clipstudio_sources import comicfesta_document

            if method != 'GET' or data is not None or not comicfesta_document(url):
                raise SourceError('Некорректный запрос ComicFesta.')
        honto_session = action in {'honto-public', 'honto-view'}
        if honto_session:
            from manga_honto import doc_route as honto_document, public_form as honto_form

            if action == 'honto-public':
                allowed = honto_document(url, method, data)
            else:
                allowed = method == 'POST' and honto_form(url, data)
            if not allowed:
                raise SourceError('Некорректный запрос открытого тома Honto.')
            if action == 'honto-view':
                outgoing.update({'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'})
        if action == 'hakusensha-public':
            from manga_hakusensha import GUEST, public_api as hakusensha_api

            token = (headers or {}).get('Hakusensha-Guest', '')
            route = urlsplit(url)
            if (method != 'GET' or data is not None or not hakusensha_api(route.netloc, route.path, route.query)
                    or not isinstance(token, str) or not GUEST.fullmatch(token)):
                raise SourceError('Некорректный запрос открытого каталога Hakusensha.')
            outgoing.update({'Authorization': token, 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
        if action == 'coronaex-public':
            from manga_coronaex import KEY_VALUE, public_api as coronaex_api

            key = (headers or {}).get('Corona-Environment', '')
            route = urlsplit(url)
            if (method != 'GET' or data is not None or not coronaex_api(route.netloc, route.path, route.query)
                    or not isinstance(key, str) or not KEY_VALUE.fullmatch(key)):
                raise SourceError('Некорректный запрос открытого каталога Corona EX.')
            outgoing.update({'X-API-Environment-Key': key, 'Accept': 'application/json',
                             'X-Requested-With': 'XMLHttpRequest'})
        alphapolis_session = action in {'alphapolis-guest-title', 'alphapolis-guest-form'}
        if alphapolis_session:
            from manga_alphapolis import cookie_token as alphapolis_token, public_transport as alphapolis_route

            if not alphapolis_route(url, method, data, outgoing.get('Referer', ''), action):
                raise SourceError('Некорректный запрос открытого выпуска Alphapolis.')
            if action == 'alphapolis-guest-form':
                token = alphapolis_token(self.session)
                if not token:
                    raise SourceAccessError('Alphapolis не предоставил гостевую сессию.')
                outgoing.update({'X-XSRF-TOKEN': token, 'Accept': 'application/json',
                                 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
        if action == 'mangamee-proto':
            from manga_mangamee import public_api as mangamee_api
            target = urlsplit(url)
            if method != 'GET' or data is not None or not mangamee_api(target.netloc, target.path, target.query):
                raise SourceError('Некорректный маршрут MangaMee.')
            outgoing['Accept'] = 'application/x-protobuf, application/octet-stream, */*'
        ciao_json = action == 'ciaoplus-json'
        if ciao_json:
            from manga_ciaoplus import transport as ciao_signature

            digest = ciao_signature(url, method, data)
            if digest is None:
                raise SourceError('Некорректный маршрут Ciao Plus.')
            outgoing.update({'X-Bambi-Hash': digest, 'Accept': 'application/json',
                             'X-Requested-With': 'XMLHttpRequest', 'Accept-Language': 'ja,en;q=0.8'})
        corocoro_proto = action == 'corocoro-proto'
        if method == 'PUT' and not corocoro_proto:
            raise SourceError('Этот PUT не относится к поддерживаемой читалке.')
        if corocoro_proto:
            from manga_corocoro import transport as corocoro_route

            if not corocoro_route(url, method, data):
                raise SourceError('Некорректный маршрут Corocoro Online.')
            outgoing.update({'Accept': 'application/x-protobuf, application/octet-stream, */*',
                             'X-Requested-With': 'XMLHttpRequest', 'Accept-Language': 'ja,en;q=0.8'})
            if method == 'PUT':
                outgoing['Content-Type'] = 'application/octet-stream'
        mangaone_proto = action == 'mangaone-proto'
        if mangaone_proto:
            from manga_mangaone import transport as mangaone_route

            if not mangaone_route(url, method, data):
                raise SourceError('Некорректный маршрут Manga One.')
            outgoing.update({'Accept': 'application/x-protobuf, application/octet-stream, */*',
                             'X-Requested-With': 'XMLHttpRequest', 'Accept-Language': 'ja,en;q=0.8'})
            if method == 'POST':
                outgoing['Content-Type'] = 'application/x-protobuf'
        zerosum_viewer = False
        if action == 'zerosum-proto':
            from manga_zerosum import public_api as zerosum_api

            target = urlsplit(url)
            viewer = target.path == '/api/v1/viewer'
            zerosum_viewer = viewer and method == 'POST' and data == b''
            if (not zerosum_api(target.netloc, target.path, target.query)
                    or not (zerosum_viewer or not viewer and method == 'GET' and data is None)):
                raise SourceError('Некорректный маршрут Zerosum Online.')
            outgoing.update({'Accept': 'application/x-protobuf, application/octet-stream, */*',
                             'X-Requested-With': 'XMLHttpRequest', 'Accept-Language': 'ja,en;q=0.8'})
        if action == 'inkstory-json':
            from manga_inkstory import SERVICES, public_api
            target = urlsplit(url)
            if (target.netloc not in SERVICES or method != 'GET' or data is not None
                    or not public_api(target.netloc, target.path, target.query)):
                raise SourceError('Некорректный публичный маршрут каталога InkStory.')
            outgoing.update({'Accept': 'application/json', 'x-tsr-serverFn': 'true', 'Sec-Fetch-Site': 'same-origin',
                             'User-Agent': 'Tachiyomi (+https://github.com/keiyoushi/extensions-source)'})
        million_register = False
        if action == 'mangamillion-proto':
            from manga_mangamillion import TOKEN, public_api
            target = urlsplit(url)
            token = (headers or {}).get('Access-Token', '')
            million_register = target.path == '/api/register' and method == 'POST' and data == b'' and token == ''
            valid_read = target.path != '/api/register' and method == 'GET' and data is None
            if not public_api(target.netloc, target.path, target.query) or not (
                    million_register or valid_read and isinstance(token, str) and TOKEN.fullmatch(token)):
                raise SourceError('Некорректный маршрут Manga Million.')
            outgoing.update({'Accept': 'application/x-protobuf, application/octet-stream, */*',
                             'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
                             'X-Requested-With': 'XMLHttpRequest'})
            if token:
                outgoing['Access-Token'] = token
        if action == 'globalcomix-json':
            from manga_globalcomix import client_header, public_request
            if method != 'GET' or data is not None or not public_request(url):
                raise SourceError('Некорректный маршрут GlobalComix.')
            outgoing.update({'X-GC-Client': client_header(), 'X-GC-Identmode': 'cookie',
                             'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
        publisher = action in {'comici-json', 'comici-rsc', 'comici-html', 'comici-image',
                               'giga-json', 'giga-graphql', 'giga-html', 'giga-image'}
        if publisher:
            if action.startswith('comici-'):
                from manga_comici import image_route, public_route
            else:
                from manga_gigaviewer import image_route, public_route
            from manga_network_routes import configuration, routed
            route_config = configuration()
            origin = urlsplit(url)
            publisher_image = action.endswith('-image')
            expected_method = 'POST' if action == 'giga-graphql' else 'GET'
            if method != expected_method or not (image_route(origin.netloc) if publisher_image
                                                  else public_route(origin.netloc, origin.path, origin.query, action)):
                raise SourceError('Некорректный публичный маршрут издателя.')
            outgoing['Accept-Language'] = 'ja,en;q=0.8'
        if action in {'vine-json', 'vine-rsc', 'toonz-rsc', 'hentaihand-json', 'comici-json', 'comici-rsc', 'giga-json', 'giga-graphql'}:
            if action == 'hentaihand-json':
                from manga_hentaihand import public_api as route
            elif action == 'toonz-rsc':
                from manga_toonz import rsc_route as route
            elif not publisher:
                from manga_vinetheme import public_api, rsc_route
                route = public_api if action == 'vine-json' else rsc_route
            if not publisher:
                origin = urlsplit(url)
                if method != 'GET' or not route(origin.netloc, origin.path, origin.query):
                    raise SourceError('Некорректный публичный маршрут источника.')
            outgoing.update({'X-Requested-With': 'XMLHttpRequest', 'Sec-Fetch-Site': 'same-origin',
                             'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Dest': 'empty'})
            if action in {'vine-rsc', 'comici-rsc', 'toonz-rsc'}:
                outgoing.update({'RSC': '1', 'Accept': 'text/x-component, */*'})
            else:
                outgoing['Accept'] = 'application/json, text/javascript, */*; q=0.01'
        if urlsplit(url).hostname in {'animego.org','animego.me'} and re.fullmatch(r'/player/(?:videos/)?\d+/?',urlsplit(url).path):
            # These published player pages return their HTML in data.content.
            outgoing['X-Requested-With'] = 'XMLHttpRequest'
            outgoing['Accept'] = 'application/json, text/javascript, */*; q=0.01'
        if byte_range:
            outgoing["Range"] = byte_range
        if action == 'mangahere-xhr':
            outgoing.update({'Accept-Language': 'en-US,en;q=0.9', 'X-Requested-With': 'XMLHttpRequest'})
        if action == 'viz-page':
            from manga_viz import viewer_route

            if method != 'GET' or data is not None or not viewer_route(url, outgoing.get('Referer', '')):
                raise SourceError('Некорректный маршрут открытой читалки VIZ.')
            outgoing.update({'X-Client-Login': 'false', 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'})
        fury_form = False
        buff_form = False
        natsuid_form = False
        if action == 'natsuid-search':
            from manga_natsuid import public_form as natsuid_public_form
            if method != 'POST' or not natsuid_public_form(url, data):
                raise SourceError('Некорректная форма каталога Rawkuma.')
            natsuid_form = True
            outgoing.update({'Accept': 'text/html, */*', 'X-Requested-With': 'XMLHttpRequest'})
        init_form = ''
        if action == 'initmanga-public-form':
            from manga_initmanga import public_form as init_public_form
            init_form = init_public_form(url, data, headers or {})
            if method != 'POST' or not init_form:
                raise SourceError('Некорректная форма читалки InitManga.')
            outgoing.update({'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
            if init_form == 'key':
                outgoing['Content-Type'] = 'application/json'
                if headers.get('X-WP-Nonce'):
                    outgoing['X-WP-Nonce'] = headers['X-WP-Nonce']
        if method == "POST":
            # Explicit public playback/search forms; never login or arbitrary APIs.
            host = urlsplit(url).hostname
            player_form=host in {"kodikplayer.com", "kodik.info", "kodik.biz", "kodik.cc", "aniqit.com"} and re.fullmatch(r"/[a-zA-Z0-9_-]{1,40}", urlsplit(url).path)
            search_form=(host in {'freeanime.ru','www.freeanime.ru'} and urlsplit(url).path in {'/','/index.php'}
                         and isinstance(data,dict) and set(data)=={'do','subaction','story'}
                         and data.get('do')=='search' and data.get('subaction')=='search'
                         and isinstance(data.get('story'),str) and 0<len(data['story'])<=200)
            manga_form=(host=='mangaball.com' and urlsplit(url).scheme=='https' and urlsplit(url).path=='/api/v1/chapter/chapter-listing-by-title-id'
                        and not urlsplit(url).query and isinstance(data,bytes) and bool(re.fullmatch(rb'\{"title_id":\s*"[a-f0-9]{24}"\}',data)))
            chan_search = (action == 'hentaichan-search' and url == 'https://hentaichan.cc/'
                           and isinstance(data, str) and 0 < len(data) <= 200)
            senkognito_read=(action=='senkognito-read' and url=='https://api.senkognito.com/graphql'
                            and isinstance(data,bytes) and len(data)<=4096)
            senkuro_native = False
            if action == 'senkuro-native':
                from manga_senkuro_native import public_form
                app = (headers or {}).get('App-Id', '')
                senkuro_native = public_form(url, data, app)
                if senkuro_native:
                    outgoing.update({'App-Id': app, 'App-Version': '060626', 'Content-Type': 'application/json',
                                     'Accept': 'application/json',
                                     'User-Agent': 'Tachiyomi (+https://github.com/keiyoushi/extensions-source)'})
            lostfilm_catalog=(url=='https://www.lostfilm.tv/ajaxik.php' and isinstance(data,dict) and set(data)=={'act','type','o','s','t'}
                              and data.get('act')=='serial' and data.get('type')=='search' and str(data.get('o','')).isdigit()
                              and data.get('s') in {'1','2','3'} and data.get('t')=='0')
            honey_chapters=(url=='https://data.api.honey-manga.com.ua/v2/chapter/cursor-list' and isinstance(data,bytes) and len(data)<=256
                            and bool(re.fullmatch(rb'\{"page": \d{1,3}, "pageSize": 100, "sortOrder": "ASC", "mangaId": "[0-9a-f-]{36}"\}',data)))
            hikka_search=(action=='hikka-search' and urlsplit(url).hostname=='api.hikka.io' and urlsplit(url).path in {'/novel','/anime','/manga'}
                          and isinstance(data,bytes) and len(data)<=512 and bool(re.fullmatch(rb'\{"query": "(?:[^"\\]|\\.){1,400}"\}',data)))
            jaomix_toc=(url=='https://jaomix.ru/wp-admin/admin-ajax.php' and isinstance(data,dict) and set(data)=={'action','page'}
                        and data.get('action')=='loadpagenavchapstt' and bool(re.fullmatch(r'\d{1,3}',str(data.get('page','')))))
            madara_form=False
            if action=='madara-read':
                from manga_madara import ajax_form
                madara_form=ajax_form(url,data,(headers or {}).get('Referer'))
            giga_form = False
            if action == 'giga-graphql':
                from manga_gigaviewer import graphql_form
                giga_form = origin.path == '/graphql' and graphql_form(host, data)
            foolslide_form = False
            if action == 'foolslide-form':
                from manga_foolslide import public_form
                foolslide_form = public_form(url, data)
            namicomi_form = False
            if action == 'namicomi-access':
                from manga_namicomi import public_access_form
                namicomi_form = public_access_form(url, data)
            xcomic_form = False
            if action == 'xcomic-graphql':
                from manga_xcomic import graphql_form
                xcomic_form = graphql_form(url, data)
            if action == 'comicfury-warning':
                from manga_comicfury import warning_form
                fury_form = warning_form(url, data)
            catalogue_form = False
            if action == 'native-series-form':
                from manga_series_port import public_form
                catalogue_form = public_form(url, data, headers or {})
                buff_form = bool(catalogue_form and host == 'mangabuff.ru')
                if buff_form:
                    outgoing.update({'X-CSRF-TOKEN': headers['X-CSRF-TOKEN'], 'X-Requested-With': 'XMLHttpRequest',
                                     'Accept': 'application/json', 'Origin': 'https://mangabuff.ru'})
                if catalogue_form and host == 'manhwalike.com':
                    outgoing.update({'X-Requested-With': 'XMLHttpRequest', 'Accept': 'text/html'})
                if catalogue_form and host in {'rizzfables.com', 'hentailoop.com'}:
                    outgoing.update({'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'})
                if catalogue_form and host in {'rinkocomics.com', 'honeytoon.com', 'global.toomics.com'}:
                    outgoing.update({'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'})
            if action == 'dcm-search':
                from manga_comic_museum import public_search
                catalogue_form = isinstance(data, dict) and public_search(url, data)
            if action == 'native-series-data-form':
                from manga_independent_json_ports import public_form
                catalogue_form = public_form(url, data)
                if catalogue_form:
                    outgoing.update({'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
                    if isinstance(data, bytes):
                        outgoing['Content-Type'] = 'application/json'
            mangataro_form = False
            if action == 'mangataro-form':
                from manga_mangataro import public_form
                mangataro_form = public_form(url, data)
                if mangataro_form:
                    outgoing.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                                     'X-Requested-With': 'XMLHttpRequest'})
            mangabox_form = False
            if action == 'mangabox-read':
                from manga_mangabox import form as mangabox_request

                mangabox_form = mangabox_request(url, data)
                if mangabox_form:
                    outgoing.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                                     'X-Requested-With': 'XMLHttpRequest'})
            drecomics_form = False
            if action == 'drecomics-viewer':
                from manga_drecomics import viewer_form as drecomics_request

                drecomics_form = drecomics_request(url, data)
                if drecomics_form:
                    outgoing.update({'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
            docomo_form = False
            if action == 'docomo-reader':
                from manga_docomo import public_form as docomo_request

                docomo_form = docomo_request(url, data, outgoing.get('Referer', ''))
                if docomo_form:
                    outgoing.update({'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
            cycomi_form = False
            if action == 'cycomi-reader':
                from manga_japanese_readers import cy_viewer_form

                cycomi_form = cy_viewer_form(url, data, (headers or {}).get('Referer', ''))
                if cycomi_form:
                    outgoing.update({'Content-Type': 'application/json', 'Accept': 'application/json',
                                     'X-Requested-With': 'XMLHttpRequest', 'Origin': 'https://cycomi.com'})
            ninehentai_form = False
            if action == 'ninehentai-api':
                from manga_ninehentai import form as ninehentai_read

                ninehentai_form = ninehentai_read(url, data)
                if ninehentai_form:
                    outgoing.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                                     'X-Requested-With': 'XMLHttpRequest', 'Origin': 'https://9hentai.so'})
            voyceme_form = False
            if action == 'voyceme-graphql':
                from manga_voyceme import public_form as voyceme_read

                voyceme_form = voyceme_read(url, data)
                if voyceme_form:
                    outgoing.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                                     'X-Requested-With': 'XMLHttpRequest', 'Origin': 'https://www.voyce.me'})
            # HentaiMama's public player list for one episode post (hentai_video_sites).
            mama_player=(url=='https://hentaimama.io/wp-admin/admin-ajax.php' and isinstance(data,dict) and set(data)=={'action','a','i'}
                         and data.get('action')=='get_player_contents' and bool(re.fullmatch(r'\d{1,9}',str(data.get('a',''))))
                         and bool(re.fullmatch(r'\d{1,2}',str(data.get('i','')))))
            if not (player_form or search_form or manga_form or million_register or zerosum_viewer or manhwazone_session
                    or foolslide_form or namicomi_form or ninehentai_form or voyceme_form or mangabox_form or mangaone_proto
                    or ciao_json or firecross_session or honto_session or alphapolis_session or drecomics_form or docomo_form or cycomi_form
                    or xcomic_form or fury_form or catalogue_form or natsuid_form or mangataro_form or init_form or akuma_session
                    or mdx_mode == 'refresh'
                    or chan_search or senkognito_read or senkuro_native or lostfilm_catalog or honey_chapters
                    or hikka_search or jaomix_toc or madara_form or giga_form or mama_player or ninth and ninth.post):
                raise SourceError("Этот POST не относится к поддерживаемой публичной форме.")
            if madara_form:outgoing['X-Requested-With']='XMLHttpRequest'
            if chan_search:
                # The public search box's Next.js action. The caller supplies only the title.
                outgoing.update({'Next-Action': '7fe1df09f7c8151b600f1a3e496cdda2e7ed7f0f95',
                                 'Accept': 'text/x-component', 'Content-Type': 'text/plain;charset=UTF-8',
                                 'Origin': 'https://hentaichan.cc', 'Referer': 'https://hentaichan.cc/'})
                data = json.dumps([{'name': data, 'page': 1, 'limit': 24}]).encode()
            if manga_form or honey_chapters or hikka_search or giga_form or namicomi_form or xcomic_form:
                outgoing['Content-Type'] = 'application/json'
            if xcomic_form:
                outgoing.update({'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json',
                                 'Origin': 'https://xcomic.me'})
            if player_form:
                outgoing["X-Requested-With"] = "XMLHttpRequest"
                outgoing["Accept"] = "application/json, text/javascript, */*; q=0.01"
        import source_transport as transport
        # Declared routes (source ID + operation + domain) decide the exit and
        # whether a browser challenge goes to the solver; undeclared traffic
        # keeps the legacy per-action routing below.
        route_source, route_operation = transport.resolve(self, url, headers, expect)
        solved = solved_key = None
        started = time.time()
        for hop in range(6):
            pace(url,getattr(self,'bulk',False))
            if self.deadline and time.monotonic() >= self.deadline:
                raise SourceError('Источник не уложился во время проверки. Можно повторить его отдельно.')
            decision = transport.decide(route_source, route_operation, url) if route_source else None
            if solved is not None and (decision is None or transport.session_key(decision) != solved_key):
                # A redirect to another host or exit never carries these cookies.
                solved = None
            solver_session = None
            options = {}
            send = outgoing
            try:
                # A Comic Fury warning can set a cookie for a redirect to the same page.
                if not (fury_form or buff_form or webnex_document or manhwazone_session or toomics_session
                        or firecross_session or honto_session or alphapolis_session or publus_source or akuma_session
                        or ninth and ninth.cookies):
                    self.session.cookies.clear()
                request_timeout=timeout or self.timeout
                if self.deadline:
                    remaining=max(.2,self.deadline-time.monotonic());request_timeout=(min(request_timeout[0],remaining),min(request_timeout[1],remaining))
                if publisher and routed(url, route_config):
                    options['proxies'] = {'https': route_config['httpProxy']}
                if speedbinb_routed and routed(url, speedbinb_config):
                    options['proxies'] = {'https': speedbinb_config['httpProxy']}
                if publus and routed(url, publus_routes):
                    options['proxies'] = {'https': publus_routes['httpProxy']}
                if japanese_public and routed(url, japanese_routes):
                    options['proxies'] = {'https': japanese_routes['httpProxy']}
                if decision is not None:
                    options.pop('proxies', None)
                    if decision.proxy:
                        options['proxies'] = {'https': decision.proxy, 'http': decision.proxy}
                    if decision.solver:
                        solver_session = solved or transport.sessions.get(transport.session_key(decision))
                    if solver_session:
                        if solver_session.cookies_work is False:
                            # This site already refused the solved cookies: a new
                            # solver run would not help a non-page request either.
                            solved, solved_key = solver_session, transport.session_key(decision)
                        send, jar = dict(outgoing), {}
                        transport.apply(solver_session, send, jar)
                        if jar:
                            options['cookies'] = jar
                        if (solver_session.cookies_work is False
                                and decision.page_allowed(method, send.get('Accept'), expect)):
                            # Clearance cookies do not work outside the solver's
                            # browser for this site: read pages through it.
                            return transport.solver_page(decision, url, self.deadline), url
                body = data
                if natsuid_form or init_form == 'vault' or action == 'dcm-search':
                    options['files'] = {key: (None, value) for key, value in data.items()}
                    body = None
                if decision is not None and decision.rule.tls and 'files' not in options:
                    response = transport.impersonated(decision, method, url, send, body, request_timeout, options,
                                                      keep_agent=solver_session is not None)
                else:
                    response = self.session.request(method, url, headers=send, data=body,
                                                    timeout=request_timeout, allow_redirects=False, stream=True, **options)
            except requests.exceptions.ProxyError:
                if options.get('proxies'):
                    transport.route_down()
                    raise SourceRouteError('Японский шлюз не принял соединение. Повтори позже.') from None
                raise SourceTemporaryError("Источник не ответил. Повтори импорт позднее.") from None
            except requests.RequestException:
                raise SourceTemporaryError("Источник не ответил. Повтори импорт позднее.") from None
            retry_after = response.headers.get('Retry-After')
            if response.status_code == 429 or (response.status_code == 503 and retry_after):
                response.close()
                raise SourceRateLimitError(retry_after, http_status=response.status_code)
            if decision is not None and decision.solver and response.status_code not in {301, 302, 303, 307, 308}:
                kind = None
                if response.status_code in {401, 403, 429, 451, 503}:
                    kind = transport.classify(response.status_code, response.headers, self._peek(response, 65536))
                elif (200 <= response.status_code < 300 and expect == 'page'
                      and 'html' in response.headers.get('Content-Type', '').lower()):
                    head = self._peek(response, MAX_DOCUMENT, strict=True)
                    kind = 'challenge' if transport.classify(200, response.headers, head) == 'challenge' else None
                if kind == 'challenge':
                    response.close()
                    if solved is None:
                        site = decision.rule.site(decision.host)
                        # Byparr clears challenges on HTML pages. A CDN subdomain (page
                        # images) takes its site's clearance, which Cloudflare scopes to
                        # the whole zone; a POST is cleared on its own host's root.
                        if site != decision.host and expect != 'page':
                            solve_url = f'https://{site}/'
                        else:
                            solve_url = url if method == 'GET' else f'https://{decision.host}/'
                        solved = transport.solve(decision, solve_url, self.deadline, started)
                        solved_key = transport.session_key(decision)
                        continue
                    solved.cookies_work = False
                    if decision.page_allowed(method, send.get('Accept'), expect):
                        return transport.solver_page(decision, url, self.deadline), url
                    raise SourceChallengeError('Источник отклонил решённую проверку браузера.', solver='rejected')
                if solver_session is not None and 200 <= response.status_code < 300:
                    solver_session.cookies_work = True
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location", "")
                if action == 'pixivcomic-store' and location:
                    from manga_webcomics import param

                    try:
                        next_url = self.validate(urljoin(url, location))
                    except (SourceError, ValueError):
                        response.close()
                        raise
                    if urlsplit(next_url).netloc not in {'comic.pixiv.net', 'comic-store-viewer.pixiv.net'}:
                        response.close()
                        raise SourceError('Pixiv Comic перенаправил том на другой домен.')
                    if param(next_url, 'cid') and (param(next_url, 'u1') or param(next_url, 'u2')):
                        return response, url
                response.close()
                if ninth and not (ninth.redirect and location and hop < 5
                                  and urlsplit(urljoin(url, location)).netloc == urlsplit(url).netloc):
                    raise SourceRedirectError("Некорректное перенаправление источника.")
                if (speedbinb or clipstudio or publus or action in {'mangamillion-proto', 'mangaplus-proto', 'mangaplus-image', 'mangamee-proto',
                               'globalcomix-json', 'webcomic-json',
                               'native-series-json', 'native-series-html-api', 'native-series-rsc', 'inkstory-json',
                               'natsuid-search', 'creator-feed-json', 'fanfox-reader', 'ysk-json',
                               'webnex-json', 'webnex-image', 'zerosum-proto', 'manhwazone-livewire', 'honeytoon-sync',
                               'mangaone-proto', 'mangabox-read', 'corocoro-proto', 'ciaoplus-json', 'firecross-guest-reader',
                               'hakusensha-public', 'alphapolis-guest-form', 'drecomics-viewer', 'coronaex-public',
                               'mangahere-xhr', 'viz-page', 'toonz-rsc', 'akuma-guest',
                               'cycomi-reader', 'nicovideo-public',
                               'publus-source-json', 'docomo-reader', 'pixivcomic-public'}
                        or not location or hop == 5):
                    raise SourceRedirectError("Некорректное перенаправление источника.")
                next_url = self.validate(urljoin(url, location))
                if action == 'publus-source-document' and urlsplit(next_url).netloc != origin.netloc:
                    raise SourceError('Издатель Publus перенаправил гостевой запрос на другой домен.')
                if action == 'bookwalker-public-view' and urlsplit(next_url).netloc not in VIEWER_HOSTS:
                    raise SourceError('BookWalker перенаправил читалку на другой домен.')
                if action == 'firecross-guest-title' and not firecross_route(next_url, method, data, action, ''):
                    raise SourceError('FireCross перенаправил страницу на другой маршрут.')
                if action == 'honto-public' and not honto_document(next_url, method, None):
                    raise SourceError('Honto перенаправил страницу на другой маршрут.')
                if action == 'alphapolis-guest-title' and not alphapolis_route(next_url, method, None, '', action):
                    raise SourceError('Alphapolis перенаправил страницу на другой маршрут.')
                if (action in {'webnex-doc', 'hotcomics-doc'} and urlsplit(next_url).netloc != urlsplit(url).netloc):
                    raise SourceError('Источник перенаправил гостевой запрос на другой сайт.')
                if action == 'manhwazone-document' and urlsplit(next_url).netloc not in manhwazone_hosts:
                    raise SourceError('ManhwaZone перенаправил карточку на другой домен.')
                if toomics_session and urlsplit(next_url).netloc != 'global.toomics.com':
                    raise SourceError('Toomics перенаправил сессию на другой домен.')
                if mdx_mode and (method != 'GET' or urlsplit(next_url).netloc != urlsplit(url).netloc):
                    raise SourceError('MadaraDex перенаправил запрос гостевой сессии.')
                if publisher:
                    target = urlsplit(next_url)
                    allowed = (image_route(target.netloc) if publisher_image
                               else target.netloc == origin.netloc and target.path.rstrip('/') == origin.path.rstrip('/')
                               and public_route(target.netloc, target.path, target.query, action)
                               and (action == 'comici-rsc' or target.query == origin.query))
                    if not allowed:
                        raise SourceError('Издатель перенаправил запрос на другой маршрут.')
                if action in {'vine-json', 'vine-rsc'}:
                    target = urlsplit(next_url)
                    if (target.netloc != origin.netloc or target.path.rstrip('/') != origin.path.rstrip('/')
                            or not route(target.netloc, target.path, target.query)):
                        raise SourceError('VineTheme перенаправил запрос на другой маршрут.')
                if fury_form:
                    current, target = urlsplit(url), urlsplit(next_url)
                    if (response.status_code not in {301, 302, 303} or current.netloc != target.netloc
                            or current.path.rstrip('/') != target.path.rstrip('/') or current.query != target.query):
                        raise SourceError('Comic Fury перенаправил подтверждение на другую страницу.')
                    method, data = "GET", None
                if method == "POST" and (action or urlsplit(next_url).netloc != urlsplit(url).netloc):
                    raise SourceError("Плеер перенаправил форму на другой сервер.")
                if response.status_code == 303:
                    method, data = "GET", None
                url = next_url
                continue
            if not 200 <= response.status_code < 300:
                status = response.status_code
                if (init_form == 'key' and status in {400, 401, 403}
                        and response.headers.get('Content-Type', '').partition(';')[0].strip() == 'application/json'):
                    return response, url
                kind = (transport.classify(status, response.headers, self._peek(response, 65536))
                        if status in {401, 403, 429, 451, 503} else None)
                response.close()
                if kind:
                    raise transport.error_for(kind, url)
                if status in {401, 403}:
                    raise SourceAccessError("Источник требует вход, проверку браузера или ограничивает доступ.")
                if status in {408, 502, 503, 504}:
                    raise SourceTemporaryError(f"Источник вернул HTTP {status}.")
                raise SourceError(f"Источник вернул HTTP {status}.")
            if response.headers.get('cf-mitigated', '').strip().lower() == 'challenge':
                response.close()
                raise transport.error_for('challenge', url)
            return response, url
        raise SourceError("Слишком много перенаправлений.")

    @staticmethod
    def _peek(response, limit, strict=False):
        """Read (and keep) up to ``limit`` bytes of a streamed answer to classify it.

        The body stays readable: the response becomes a consumed one whose
        iter_content() replays the bytes. A body declared larger is not read."""
        if getattr(response, '_content_consumed', False):
            raw = response._content if isinstance(response._content, bytes) else b''
        else:
            declared = response.headers.get('Content-Length', '')
            if declared.isdigit() and int(declared) > limit:
                return ''
            parts, size = [], 0
            try:
                for block in response.iter_content(65536):
                    size += len(block)
                    if size > limit:
                        if strict:
                            raise SourceError("Страница или плейлист слишком велики.")
                        break
                    parts.append(block)
            except requests.RequestException:
                raise SourceTemporaryError("Соединение с источником оборвалось во время чтения ответа.") from None
            raw = b''.join(parts)
            response._content = raw
            response._content_consumed = True
        return decode_document(raw[:262144], response.encoding)

    def leslie_image_exists(self, value, referer):
        from manga_madara import SEGMENT

        url = urlsplit(value)
        if url.netloc != 'leslie-victims.pages.dev' or url.query or not re.fullmatch(
                rf'/content/{SEGMENT}/{SEGMENT}/\d{{2,3}}\.webp', url.path):
            raise SourceError('Некорректная ссылка на страницу комикса.')
        try:
            response, final = self._open(value, headers={'Referer': referer}, method='HEAD')
        except SourceError as error:
            if str(error) == 'Источник вернул HTTP 404.':
                return False
            raise
        try:
            return final == value and response.headers.get('Content-Type', '').startswith('image/')
        finally:
            response.close()

    def document(self, value, *, headers=None, method="GET", data=None, timeout=None, action=None, limit=MAX_DOCUMENT):
        options = {'timeout': timeout} if timeout else {}
        if action:
            options['action'] = action
        response, url = self._open(value, headers=headers, method=method, data=data, expect='page', **options)
        try:
            parts, size, start = [], 0, time.monotonic()
            for block in response.iter_content(65536):
                size += len(block)
                if size > limit:
                    raise SourceError("Страница или плейлист слишком велики.")
                if time.monotonic() - start > 20 or self.deadline and time.monotonic() > self.deadline:
                    raise SourceTemporaryError("Источник отдаёт страницу слишком долго.")
                parts.append(block)
            text = decode_document(b"".join(parts), response.encoding)
            if BLOCKED.search(text):
                from source_transport import classify, error_for
                kind = classify(200, response.headers, text)
                if kind:
                    raise error_for(kind, url)
                raise SourceError("Страница требует проверку браузера или подписку. Выбери другой публичный источник.")
            return text, url, dict(response.headers)
        except requests.RequestException:
            raise SourceTemporaryError("Соединение с источником оборвалось во время чтения ответа.") from None
        finally:
            response.close()

    def download(self, value, target, *, headers=None, byte_range=None, maximum=MAX_VIDEO):
        response, final_url = self._open(value, headers=headers, byte_range=byte_range)
        expected = None
        if byte_range:
            expected = int(byte_range.split("-")[1]) - int(byte_range.split("=")[1].split("-")[0]) + 1
            if response.status_code != 206 or response.headers.get("Content-Range", "").split("/")[0] != byte_range.replace("=", " "):
                response.close()
                raise SourceError("Источник не поддерживает нужный диапазон HLS.")
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > maximum:
            response.close()
            raise SourceError("Файл превышает лимит свободной сессии.")
        size = 0
        try:
            if "text/html" in response.headers.get("Content-Type", "").lower():
                raise SourceError("Вместо видео источник вернул HTML-страницу.")
            with Path(target).open("wb") as output:
                for block in response.iter_content(1024 * 1024):
                    size += len(block)
                    if size > maximum:
                        raise SourceError("Файл превышает лимит свободной сессии.")
                    output.write(block)
            if size == 0 or (expected is not None and size != expected) or (declared and declared.isdigit() and size != int(declared)):
                raise SourceError("Источник передал неполный файл.")
            return size
        except requests.RequestException:
            Path(target).unlink(missing_ok=True)
            raise SourceError("Скачивание прервалось. Повтори импорт: завершённые серии будут пропущены.") from None
        except BaseException:
            Path(target).unlink(missing_ok=True)
            raise
        finally:
            response.close()

    # The exact small interface anime-dl-core expects. It cannot use its own network client.
    def get(self, url, *, headers=None, params=None, **_):
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        text, final, response_headers = self.document(url, headers=headers)
        from anime_dl_core.http import Response
        return Response(200, text, final, response_headers)

    def post(self, url, *, headers=None, data=None):
        text, final, response_headers = self.document(url, headers=headers, method="POST", data=data)
        from anime_dl_core.http import Response
        return Response(200, text, final, response_headers)


def episode_number(text):
    for expression in (r"(?:серия|эпизод|episode|ep)[\s_/-]*(\d{1,4})(?!\d)",
                       r"(?<!\d)(\d{1,4})[\s_/-]*(?:серия|серию|серии|seriya|episode)(?![a-z])"):
        found = re.search(expression, text, re.I)
        if found and int(found[1]) > 0:
            return int(found[1])
    query = dict(parse_qsl(urlsplit(text).query))
    if query.get("episode", "").isdigit() and int(query["episode"]) > 0:
        return int(query["episode"])
    return None


@dataclass
class Page:
    title: str = ""
    streams: list = field(default_factory=list)
    players: list = field(default_factory=list)
    episodes: list = field(default_factory=list)
    subtitles: list = field(default_factory=list)
    skip_segments: list = field(default_factory=list)


class PageParser(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.result = base, Page()
        self.title = False
        self.anchor = None
        self.select = ""
        self.option = None
        self.containers = []
        self.yummy_player_id = None
        self.published_episodes = []

    def link(self, value):
        try:
            target=public_url(urljoin(self.base, html.unescape(value).replace("\\/", "/")), resolve_dns=False)
            # This published iframe is AnimeVost's advertisement, not a series.
            if urlsplit(target).path.startswith('/html5banner/'):
                from animevost_source import HOSTS as animevost_hosts
                if urlsplit(target).hostname in animevost_hosts:return None
            return target
        except SourceError:
            return None

    def candidate(self, value, label="", attrs=None):
        url = self.link(value)
        if not url:
            return
        path = urlsplit(url).path.lower()
        if path.endswith((".mp4", ".m3u8")):
            self.result.streams.append({"url": url, "type": "hls" if path.endswith(".m3u8") else "mp4",
                                        "quality": None, "headers": {"Referer": self.base}})
        number = episode_number(label + " " + url)
        if attrs and str(attrs.get("data-episode", "")).isdigit():
            number = int(attrs["data-episode"])
        if number and urlsplit(url).netloc == urlsplit(self.base).netloc and url != self.base:
            self.result.episodes.append({"number": number, "title": label.strip()[:180], "url": url})
        if re.search(r"/(?:embed|seria|serial|shell\.php|vod|video_ext\.php)(?:/|\?|$)", url):
            self.result.players.append(url)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if urlsplit(self.base).hostname in {'amd.online','animedia.online'} and attrs.get('data-vlnk'):
            value=self.link(attrs['data-vlnk']);number=attrs.get('data-vid','')
            if value and number.isdigit() and 1<=int(number)<=10000:
                self.published_episodes.append({'number':int(number),'title':'Серия '+number,'url':value})
                self.candidate(value,attrs=attrs)
        # The site's published player-relay.js loads these exact public slots.
        # Read the same GET response as the iframe; no search/developer API,
        # session, key or generated player ID is used.
        if urlsplit(self.base).hostname in PLAYER_RELAY_HOSTS:
            identity = attrs.get("data-player-anime-id", "")
            if re.fullmatch(r"\d{1,10}", identity):
                self.yummy_player_id = identity
            slot = attrs.get("data-player-slot", "")
            if self.yummy_player_id and re.fullmatch(r"\d{1,2}", slot):
                query = urlencode({"mod": "player", "id": self.yummy_player_id, "slot": slot})
                self.result.players.append('https://'+urlsplit(self.base).hostname+'/engine/ajax/controller.php?' + query)
        if tag == "div":
            self.containers.append(attrs.get("class", ""))
        if tag == "title":
            self.title = True
        if tag == "meta" and (attrs.get("property") or attrs.get("name")) == "og:title":
            self.result.title = (attrs.get("content") or "")[:300]
        if tag == "a":
            self.anchor = [attrs, ""]
        if tag == "select":
            self.select = " ".join(self.containers[-4:] + [attrs.get("class", ""), attrs.get("name", "")])
        if tag == "option":
            self.option = [attrs, "", self.select]
        for attribute in ("src", "data-src", "data-href", "data-video", "data-player"):
            value = attrs.get(attribute)
            if value:
                self.candidate(value, attrs=attrs)
                if tag in {"iframe", "embed"}:
                    url = self.link(value)
                    if url:
                        self.result.players.append(url)

    def handle_data(self, data):
        if self.title and not self.result.title:
            self.result.title = data.strip()[:300]
        if self.anchor:
            self.anchor[1] += data
        if self.option:
            self.option[1] += data

    def handle_endtag(self, tag):
        if tag == "div" and self.containers:
            self.containers.pop()
        if tag == "title":
            self.title = False
        if tag == "a" and self.anchor:
            attrs, label = self.anchor
            self.candidate(attrs.get("href", ""), label, attrs)
            self.anchor = None
        if tag == "option" and self.option:
            attrs, label, select = self.option
            if attrs.get("value", "").startswith(("/", "https:")):
                self.candidate(attrs["value"], label, attrs)
            # Kodik's published episode choices carry per-episode IDs and hashes.
            if "serial-series" in select and attrs.get("data-id") and attrs.get("data-hash"):
                number = episode_number(label) or (int(attrs["value"]) if attrs.get("value", "").isdigit() else None)
                if number:
                    root = urlsplit(self.base)
                    url = f"https://{root.netloc}/seria/{attrs['data-id']}/{attrs['data-hash']}/720p"
                    self.result.episodes.append({"number": number, "title": label[:180], "url": url})
            self.option = None
        if tag == "select":
            self.select = ""


def public_player_html(text, base):
    """Unwrap AnimeGO's public XHR response without treating arbitrary JSON as HTML."""
    if urlsplit(base).hostname not in {'animego.org','animego.me'} or not re.fullmatch(r'/player/(?:videos/)?\d+/?',urlsplit(base).path) or not text.lstrip().startswith('{'):
        return text
    try:
        data=json.loads(text).get('data')
        content=data.get('content') if isinstance(data,dict) else None
        if not isinstance(content,str) or not content.strip():raise ValueError()
        return html.unescape(content)
    except (ValueError,AttributeError):
        raise SourceError('AnimeGO не вернул содержимое публичного плеера.') from None


def parse_page(text, base):
    text=public_player_html(text,base)
    if BLOCKED.search(text):
        raise SourceError("Источник требует проверку браузера или подписку.")
    from anistar_source import player_page
    published = player_page(text, base)
    if published is not None:
        return published
    parser = PageParser(base)
    parser.feed(text)
    # Public inline player configuration; scripts are read as text, never executed.
    decoded = html.unescape(text).replace("\\/", "/").replace('\\"','"').replace("\\'", "'")
    decoded=re.sub(r'\\u00(26|3d|2f|3a)',lambda m:chr(int(m[1],16)),decoded,flags=re.I)
    # Yummy's public iframe relay is a JSON envelope, not HTML. Only consume
    # its declared iframe source; unrelated URL strings are not player links.
    if urlsplit(base).hostname in PLAYER_RELAY_HOSTS and urlsplit(base).path=='/engine/ajax/controller.php':
        try:
            envelope=json.loads(text);payload=envelope.get('data',{})
            if envelope.get('status') is True and payload.get('kind')=='iframe':
                target=parser.link(payload.get('src',''))
                if target:parser.result.players.append(target)
        except (ValueError,TypeError,AttributeError):pass
    # DLE player switchers often publish iframe markup inside an escaped JS string.
    for match in re.finditer(r'''<iframe\b[^>]*\b(?:src|data-src)\s*=\s*["']([^"']+)["']''',decoded,re.I):
        target=parser.link(match[1])
        if target:parser.result.players.append(target)
    for match in re.finditer(r"[\"']((?:https:)?//[^\s<>\"'\\]+|/[^\s<>\"'\\]+\.(?:mp4|m3u8)(?:\?[^\s<>\"'\\]*)?)[\"']", decoded):
        parser.candidate(match[1])
    page = parser.result
    if parser.published_episodes:page.episodes=parser.published_episodes
    page.streams = list({entry["url"]: entry for entry in page.streams}.values())
    page.players = list(dict.fromkeys(page.players))
    # Preserve alternate translations; only identical episode URLs collapse.
    page.episodes = list({(entry["number"], entry["url"]): entry for entry in page.episodes}.values())
    page.episodes.sort(key=lambda entry: entry["number"])
    from animevost_source import is_title_page as is_animevost_title, episode_list as animevost_episodes
    if is_animevost_title(base):
        page.episodes = animevost_episodes(text, base)
    if '__NUXT_DATA__' in text:
        from public_page_data import episode_streams
        published=episode_streams(text,base)
        if published:
            page.episodes=sorted(published,key=lambda e:e['number'])
            selected=re.search(r'/episodes/(\d+)',urlsplit(base).path)
            if selected:
                found=next((entry for entry in published if entry['number']==int(selected[1])),None)
                if found:page.streams=[{'url':found['url'],'type':'hls','quality':None,'headers':{}}]
    return page


class Resolver:
    def __init__(self, http=None, *, native_alloha=False):
        self.http = http or PublicHttp()
        self.native_alloha = native_alloha

    def inspect(self, url, referer=None):
        url = public_url(url, resolve_dns=False)
        path = urlsplit(url).path.lower()
        if path.endswith((".mp4", ".m3u8")):
            return Page(streams=[{"url": url, "type": "hls" if path.endswith(".m3u8") else "mp4", "quality": None, "headers": {}}])
        text, final, _ = self.http.document(url,headers={'Referer':referer}) if referer else self.http.document(url)
        return parse_page(text, final)

    def player(self, url, referer=None):
        host=urlsplit(url).hostname or ''
        if is_alloha_player(url):
            if getattr(self, 'native_alloha', False):
                return Page(streams=[{'url': url, 'type': 'alloha-native', 'headers': {'Referer': referer} if referer else {}}])
            # This is a public iframe player, not a top-level HTML document.
            # A plain HTTP request can be rejected even though the publisher's
            # embedded player works. Preserve its selected audio/episode URL.
            from browser_player import extract
            options={}
            if getattr(self.http,'refresh_playback',False) is True:options['refresh']=True
            if getattr(self.http,'preview',False) is True:options['cached_only']=True
            result=extract(url,referer,details=True,**options)
            return Page(streams=result['streams'],subtitles=result.get('subtitles',[]))
        from anime_dl_core import AniboomPlayer, AnimediaPlayer, SibnetPlayer, CvhPlayer, VkPlayer, AnilibriaPlayer, SovetRomanticaPlayer
        from player_compat import KodikPlayer
        # Explicit registry: never ap.extract(), which also registers API-based players.
        for player_type in (KodikPlayer, AniboomPlayer, SibnetPlayer, AnimediaPlayer, CvhPlayer, VkPlayer, AnilibriaPlayer, SovetRomanticaPlayer):
            cvh_video = player_type is CvhPlayer and urlsplit(url).hostname == 'plapi.cdnvideohub.com' and re.fullmatch(r'/api/v1/player/sv/video/\d+',urlsplit(url).path)
            if cvh_video or player_type.matches(url):
                with player_type(client=self.http) as player:
                    options = {"referer": referer} if referer else {}
                    if player_type is KodikPlayer:
                        options["include_mp4"] = False  # Do not fabricate MP4 URLs from HLS.
                    result = player.extract(url, **options)
                streams = [{"url": stream.url, "type": stream.kind.value, "quality": stream.quality,
                            "headers": playback_headers(stream.headers)} for stream in result.streams
                           if stream.kind.value in {"mp4", "hls"}]
                segments=[]
                for segment in getattr(result,'skip_segments',[]) or []:
                    start,end=getattr(segment,'start',None),getattr(segment,'end',None)
                    kind=getattr(segment,'kind',None)
                    if isinstance(start,(int,float)) and isinstance(end,(int,float)) and 0<=start<end<=86400 and kind in {'opening','ending'}:
                        segments.append({'type':'op' if kind=='opening' else 'ed','start':start,'end':end,'source':'Kodik' if player_type is KodikPlayer else player_type.__name__})
                return Page(title=result.title or "", streams=streams,skip_segments=segments)
        return None

    def ua_player(self, url, referer=None):
        """Ashdi / HDVB-UA / Tortuga Playerjs and Collaps: re-read the embed for fresh media."""
        from ua_players import split_selectors, is_collaps, playerjs_stream, collaps_episode, collaps_captions, _number
        embed, selected = split_selectors(url)
        # The embed itself is the validated page URL; Origin is reduced to its host.
        text, final, _ = self.http.document(embed, headers={'Referer': referer or embed})
        if is_collaps(embed):
            item = collaps_episode(text, selected)
            if not item:raise SourceError('Выбранная серия больше не опубликована в плеере.')
            return Page(streams=[{'url': item['hls'], 'type': 'hls', 'quality': None, 'audio': _number(selected.get('mv_audio')),
                                  'headers': playback_headers({'Referer': embed, 'Origin': embed})}],
                        subtitles=collaps_captions(item))
        media = playerjs_stream(embed, text, selected)
        if not media:raise SourceError('Выбранная озвучка или серия больше не опубликована в плеере.')
        return Page(streams=[{'url': media, 'type': 'hls' if '.m3u8' in media else 'mp4', 'quality': None,
                              'headers': playback_headers({'Referer': embed, 'Origin': embed})}])

    def resolve(self, url, *, referer=None, depth=0, visited=None):
        if depth > 4:
            raise SourceError("Слишком длинная цепочка вложенных плееров.")
        visited = visited if visited is not None else set()
        if url in visited:
            raise SourceError("Источник зациклил вложенные плееры.")
        visited.add(url)
        from player_catalog import relay_selection, animego_buttons
        selected = relay_selection(url)
        if selected:
            original, translation, player = selected
            text, final, _ = self.http.document(original)
            matches = [v for v in animego_buttons(text, final) if v['id'] == translation and v['player'] == player]
            if len(matches) != 1:
                raise SourceError('Выбранный перевод этой серии отсутствует. Другая озвучка автоматически не подставляется.')
            return self.resolve(matches[0]['url'], referer=final, depth=depth+1, visited=visited)
        from hentaichan_video import resolve, video_page
        if video_page(url):
            return resolve(url, self.http)
        from animevost_source import is_title_page as animevost_title, resolve as resolve_animevost
        if animevost_title(url):
            return resolve_animevost(public_url(url, resolve_dns=False), self.http)
        from dynamic_video_sources import provider_for, resolve_dynamic
        provider = provider_for(url)
        if provider:
            identifier, label = provider
            return resolve_dynamic(self.http, url, referer, label, identifier)
        from ua_players import is_playerjs, is_collaps
        if is_playerjs(url) or is_collaps(url):
            return self.ua_player(url, referer)
        page = self.player(url, referer) or self.inspect(url,referer)
        if page.streams:
            return page
        for embed in page.players:
            try:
                resolved = self.resolve(embed, referer=url, depth=depth + 1, visited=visited)
                if resolved.streams:
                    resolved.title = page.title or resolved.title
                    return resolved
            except (SourceError, requests.RequestException):
                continue
            except Exception as error:
                if error.__class__.__module__.startswith("anime_dl_core"):
                    continue
                raise
        host=urlsplit(url).hostname or ''
        if host in {'jut.su','www.jut.su'}:
            from browser_player import extract
            result=extract(url,referer,details=True)
            return Page(title=page.title,streams=result['streams'],subtitles=result.get('subtitles',[]))
        if depth == 0:
            return resolve_dynamic(self.http, url, referer, page.title)
        raise SourceError("Публичный MP4/HLS-поток не найден. Вставь ссылку на доступную серию или поддерживаемый плеер.")
