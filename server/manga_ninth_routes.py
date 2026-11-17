"""Exact network routes of the sources ported in the ninth migration batch.

Every adapter of the batch sends its requests with an ``n9:<name>`` action.
The adapter module registers a checker for that name; the checker receives
the parsed URL, method, body and caller headers and returns a ``Route`` with
the extra headers, the guest cookie policy and an allowed form body, or
``None`` when the request is not one the upstream extension makes.
"""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from source_parser import SourceError


@dataclass(frozen=True)
class Route:
    headers: dict = field(default_factory=dict)
    # Keep the guest cookies a site sets on its own pages for the requests
    # of the same short-lived client (they are never stored or shared).
    cookies: bool = False
    post: bool = False
    data: object = None
    # Follow redirects only inside the same host.
    redirect: bool = True


CHECKS = {}
APIS = []


def register(name, check, api=None):
    if check is not None:
        CHECKS[name] = check
    if api is not None and api not in APIS:
        APIS.append(api)


def register_api(api):
    register('', None, api)


def _load():
    # Importing the modules registers their routes.
    import manga_ninth_sources  # noqa: F401


def prepare(action, value, method, data, headers):
    _load()
    check = CHECKS.get(action[3:])
    try:
        url = urlsplit(value)
    except ValueError:
        raise SourceError('Некорректный адрес источника.') from None
    route = check(url, method, data, headers) if check and url.scheme == 'https' else None
    if not isinstance(route, Route):
        raise SourceError('Этот запрос не входит в маршруты источника.')
    if method == 'POST' and not route.post or method not in {'GET', 'POST'}:
        raise SourceError('Этот запрос не входит в маршруты источника.')
    return route


def public_api(host, path, query):
    _load()
    return any(api(host, path, query) for api in APIS)
