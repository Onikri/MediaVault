"""MadaraDex's anonymous fingerprint and short-lived page session."""

import re
import secrets
from http.cookies import CookieError, SimpleCookie
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

from source_parser import SourceAccessError, SourceError, SourceRateLimitError


ROOT = 'https://madaradex.org'
HOST = 'madaradex.org'
IMAGE_HOST = 'cdn.madaradex.org'
REFRESH = ROOT + '/wp-admin/admin-ajax.php'
COOKIE_HEADER = 'X-MediaVault-Mdx-Cookie'
MARKER = 'mv_madaradex_guest'
GUEST_TOKEN = r'[A-Za-z0-9._~%+=!/-]{1,2048}'
SESSION_COOKIE = re.compile(rf'mdx_fp=[a-f0-9]{{32}}(?:; mdx_auth={GUEST_TOKEN})?')


def valid_cookie(value):
    return isinstance(value, str) and SESSION_COOKIE.fullmatch(value) is not None


def transport_mode(url, method, data, action, headers):
    parsed = urlsplit(url)
    cookie = headers.get(COOKIE_HEADER, '')
    if not valid_cookie(cookie) or parsed.scheme != 'https':
        return ''
    if action == 'madaradex-refresh' and url == REFRESH and method == 'POST' and data == {'action': 'mdx_auth_refresh'}:
        return 'refresh'
    if (action == 'madaradex-web' and method == 'GET' and parsed.netloc == HOST
            or action == 'madara-read' and method == 'POST' and parsed.netloc == HOST
            or action == 'madaradex-cdn' and method == 'GET' and parsed.netloc == IMAGE_HOST):
        return 'request'
    return ''


class GuestSession:
    def __init__(self):
        self.fingerprint = 'mdx_fp=' + secrets.token_hex(16)
        self.cookie = self.fingerprint
        self.expires = 0
        self.lock = Lock()

    def get(self, http, rejected=''):
        with self.lock:
            if self.expires > monotonic() and self.cookie != rejected:
                return self.cookie
            cookie, expires = self.fingerprint, 30
            try:
                _, final, response = http.document(REFRESH, method='POST', action='madaradex-refresh',
                                                   headers={'Referer': ROOT + '/', COOKIE_HEADER: self.fingerprint},
                                                   data={'action': 'mdx_auth_refresh'})
                if final != REFRESH:
                    raise SourceError('MadaraDex перенаправил запрос гостевой сессии.')
                raw = response.get('Set-Cookie', '') or response.get('set-cookie', '')
                parsed = SimpleCookie(raw)
                session = parsed.get('mdx_auth')
                if session and re.fullmatch(GUEST_TOKEN, session.value):
                    cookie += '; mdx_auth=' + session.value
                    ttl = session.get('max-age', '')
                    expires = min(1800, int(ttl)) if ttl.isdecimal() and len(ttl) < 10 else 600
            except SourceRateLimitError:
                raise
            except (SourceError, CookieError, ValueError):
                pass
            self.cookie, self.expires = cookie, monotonic() + expires
            return cookie

    def request(self, http, url, *, headers, method='GET', data=None, image=False):
        action = 'madaradex-cdn' if image else 'madara-read' if method == 'POST' else 'madaradex-web'
        request = http._open if image else http.document
        cookie = self.get(http)
        try:
            return request(url, headers={**headers, COOKIE_HEADER: cookie}, method=method, data=data, action=action)
        except SourceAccessError:
            refreshed = self.get(http, rejected=cookie)
            return request(url, headers={**headers, COOKIE_HEADER: refreshed}, method=method, data=data, action=action)


SESSION = GuestSession()
