"""Metadata is separate from public player resolution; no Google credentials here.

Provider origins are operator configuration, never arbitrary client URLs. Adapters
return candidates, not a claim that a stream can be extracted. Resolve on import.
"""
from concurrent.futures import ThreadPoolExecutor
import html
import re
import threading
import time
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup
import requests
from source_parser import PublicHttp, SourceError

DEFAULT_PROVIDERS = [
    {"id": "animego", "name": "AnimeGO", "origin": "https://animego.org", "adapter": "animego"},
    {"id": "animevost", "name": "AnimeVost", "origin": "https://animevost.org", "adapter": "dle"},
]


def plain(value):
    return BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)[:6000]


def safe_image(value, base):
    if not value:
        return ""
    url = urljoin(base, str(value or ""))
    parts = urlsplit(url)
    return url if parts.scheme == "https" and parts.hostname and not parts.username else ""


def parse_candidates(document, origin, adapter, provider):
    soup = BeautifulSoup(document, "html.parser")
    result, seen = [], set()
    for anchor in soup.select("a[href]"):
        url = urljoin(origin, anchor.get("href", ""))
        parsed = urlsplit(url)
        if parsed.netloc != urlsplit(origin).netloc or parsed.scheme != "https":
            continue
        accepted = (re.fullmatch(r"/anime/[^/]+/?", parsed.path) if adapter == "animego"
                    else re.search(r"/\d+[-_][^/]+\.html$", parsed.path))
        if not accepted or url in seen:
            continue
        image = anchor.find("img")
        title = anchor.get_text(" ", strip=True) or anchor.get("title") or (image.get("alt") if image else "")
        if not title or len(title) < 2:
            continue
        seen.add(url)
        result.append({"provider": provider["id"], "provider_name": provider["name"],
                       "title": html.unescape(title)[:250], "url": url,
                       "image": safe_image(image.get("data-src") or image.get("src"), origin) if image else ""})
    return result[:20]


class CatalogSearch:
    def __init__(self, providers=None, *, metadata_get=None, http_factory=PublicHttp):
        self.providers = DEFAULT_PROVIDERS if providers is None else providers
        self.metadata_get = metadata_get or self._metadata_get
        self.http_factory = http_factory
        self.lock, self.cache = threading.Lock(), {}
        self.last_metadata = 0

    def _metadata_get(self, path, params=None):
        # Shikimori has its own allowlisted client: source resolver still rejects API URLs.
        # Serialize requests and cache to remain below the documented public API limits.
        with self.lock:
            time.sleep(max(0, self.last_metadata + 1.1 - time.monotonic()))
            self.last_metadata = time.monotonic()
            try:
                response = requests.get("https://shikimori.one/api/animes" + path,
                    params=params, headers={"User-Agent": "MediaVault/3.1 (personal library)"},
                    timeout=(5, 12), allow_redirects=False, stream=True)
                with response:
                    response.raise_for_status()
                    if response.is_redirect:
                        raise SourceError("Каталог перенаправляет запрос; проверь конфигурацию.")
                    body = bytearray()
                    for chunk in response.iter_content(65536):
                        body.extend(chunk)
                        if len(body) > 2 * 1024 * 1024:
                            raise SourceError("Ответ каталога слишком велик.")
                    import json
                    return json.loads(body)
            except (requests.RequestException, ValueError):
                raise SourceError("Shikimori временно недоступен или ограничил запросы.") from None

    def _cached(self, key, operation):
        with self.lock:
            entry = self.cache.get(key)
            if entry and entry[0] > time.monotonic():
                return entry[1]
        value = operation()
        with self.lock:
            if len(self.cache) >= 256:
                self.cache.clear()
            self.cache[key] = (time.monotonic() + 300, value)
        return value

    @staticmethod
    def card(item):
        image = item.get("image") or {}
        return {"id": item["id"], "title": item.get("russian") or item.get("name") or "Без названия",
                "original_title": item.get("name") or "", "score": item.get("score"),
                "image": safe_image(image.get("original"), "https://shikimori.one"),
                "year": str(item.get("aired_on") or "")[:4], "kind": item.get("kind"),
                "episodes": item.get("episodes"), "description": plain(item.get("description_html") or item.get("description")),
                "url": "https://shikimori.one/animes/" + str(item["id"])}

    def provider_search(self, provider, query):
        http = self.http_factory()
        origin = provider["origin"].rstrip("/")
        params = {"q": query} if provider["adapter"] == "animego" else {"do": "search", "subaction": "search", "story": query}
        path = "/search/anime?" if provider["adapter"] == "animego" else "/index.php?"
        try:
            document, final, _ = http.document(origin + path + urlencode(params))
            if urlsplit(final).netloc != urlsplit(origin).netloc:
                raise SourceError("Источник сменил адрес; обнови его в настройках сервера.")
            items = parse_candidates(document, origin, provider["adapter"], provider)
            return {"id": provider["id"], "name": provider["name"], "items": items,
                    "status": "ok" if items else "empty", "error": ""}
        except Exception:
            return {"id": provider["id"], "name": provider["name"], "items": [], "status": "unavailable",
                    "error": "Поиск источника недоступен: возможны блокировка или изменение разметки."}
        finally:
            http.close()

    def search(self, query):
        query = str(query).strip()
        if not 2 <= len(query) <= 120:
            raise SourceError("Введи от 2 до 120 символов.")
        def perform():
            # Providers fail independently; an unavailable catalogue must not hide source results.
            with ThreadPoolExecutor(max_workers=4) as pool:
                tasks = [pool.submit(self.provider_search, provider, query) for provider in self.providers]
                try:
                    items = [self.card(item) for item in self.metadata_get("", {"search": query, "limit": 12})]
                    error = ""
                except Exception:
                    items, error = [], "Не удалось получить карточки Shikimori. Источники показаны отдельно."
                providers = [task.result() for task in tasks]
            return {"items": items, "providers": providers, "metadata_error": error}
        return self._cached(("search", query.casefold()), perform)

    def detail(self, anime_id):
        if not str(anime_id).isdigit():
            raise SourceError("Некорректный ID аниме.")
        return self._cached(("detail", str(anime_id)), lambda: self.card(self.metadata_get("/" + str(anime_id))))
