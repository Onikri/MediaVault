"""Site-specific public HTML adapters. No catalogue/video-site API requests."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import re
import time
import threading
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from source_parser import PublicHttp, Resolver, SourceError, episode_number, parse_page, public_url


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    root: str
    hosts: tuple
    cards: str
    title: str
    search_path: str = "/"
    kind: str = "anime"

    def search_url(self, query):
        if self.id == "animego":
            return self.root + "/search/anime?" + urlencode({"q": query})
        if self.id == "jutsu":
            # Jut.su's public catalogue is HTML; its search form is not a DLE API.
            return self.root + "/anime/"
        if self.id == "anilibria":
            return self.root + "/anime/catalog?" + urlencode({"q": query})
        if self.id == 'shiza':
            return self.root + '/releases?' + urlencode({'search':query})
        if self.id == 'sovet':
            return self.root + '/anime?' + urlencode({'query': query})
        return self.root + self.search_path + "?" + urlencode({"do": "search", "subaction": "search", "story": query})


SITES = (
    Site("yummy", "YummyAnime", "https://yummyanime.tv", ("yummyanime.tv",), ".movie-item", ".movie-item__title"),
    Site("animego", "AnimeGo", "https://animego.me", ("animego.me", "animego.org"), ".animes-list-item, .anime-item, .ani-grid__item", ".h5, h2, h3"),
    Site("jutsu", "Jut.su", "https://jut.su", ("jut.su",), ".all_anime_global, .all_anime", ".aaname, .anime_name"),
    Site("animevost", "AnimeVost", "https://animevost.org", ("animevost.org",), ".shortstory", ".shortstoryHead h2, .shortstoryHead a", "/index.php"),
    Site("anilibria", "AniLiberty / AniLibria", "https://aniliberty.top", ("anilibria.tv", "anilibria.top", "aniliberty.top"), ".release, .release-item, .goodcell, a[href*='/anime/releases/release/']", "h2, h3, .title"),
    Site('animejoy','AnimeJoy','https://animejoy.ru',('animejoy.ru',),'.shortstory','.ntitle a, .ntitle, h2'),
    Site('sovet','SovetRomantica','https://sovetromantica.com',('sovetromantica.com',),'.anime--block__desu','.anime--block__name'),
    Site('animedia','Animedia','https://amd.online',('amd.online','animedia.online'),'.shortstory, .poster, .movie-item','.title, h2, h3'),
    Site('anidub','AniDub','https://anidub.life',('anidub.life','anime.anidub.life','online.anidub.life','v14.anidub.digital'),'.shortstory, .poster, .short','.title, h2, h3'),
    Site('anistar','AniStar','https://anistar.org',('anistar.org',),'.shortstory, .shortstoryContent','.shortstoryHead a, h2, h3'),
    Site('shiza','SHIZA Project','https://shiza-project.com',('shiza-project.com',),'.shortstory, .release, .post, a[href*="/releases/"]','h2, h3, .title'),
    Site('animejet','AnimeJet','https://animejet.org',('animejet.org',),'.movie-item, .shortstory, .poster','.movie-item__title, h2, h3'),
    Site('anilibriafun','AniLibria releases','https://anilibria.tv',('anilibria.tv',),'.goodcell, .release','.title, h2, h3'),
    Site('anime365','Anime365','https://smotret-anime.org',('smotret-anime.org','smotret-anime.com'),'.m-catalog-item','h2, h3, .item-title'),
    Site('animeon','AnimeOn','https://animeon.club',('animeon.club',),'.movie-item, .shortstory','.movie-item__title, h2, h3'),
    Site('animebesst','AnimeBesst','https://animebesst.org',('animebesst.org',),'.shortstory, .movie-item','h2, h3, .movie-item__title'),
    Site('animebuff','AnimeBuff','https://animebuff.ru',('animebuff.ru',),'.anime-item, .shortstory','h2, h3, .title'),
    Site('animeone','AnimeOne','https://animeone.online',('animeone.online',),'.movie-item, .shortstory','.movie-item__title, h2, h3'),
    Site('animebit','AnimeBit','https://animebit.ru',('animebit.ru',),'.shortstory, .poster','h2, h3, .title'),
    Site('animelayer','AnimeLayer','https://animelayer.ru',('animelayer.ru',),'.release, .shortstory','h2, h3, .title'),
    Site('animespirit','AnimeSpirit','https://animespirit.ru',('animespirit.ru',),'.shortstory','h2, h3, .title'),
    Site('animeonline','AnimeOnline','https://animeonline.cc',('animeonline.cc',),'.shortstory, .movie-item','h2, h3, .movie-item__title'),
    Site('animeseries','AnimeSeries','https://animeseries.ru',('animeseries.ru',),'.shortstory','h2, h3, .title'),
    Site('animevosttv','AnimeVost catalogue','https://animevost.tv',('animevost.tv',),'.shortstory, .movie-item','h2, h3, .movie-item__title'),
    Site("readmanga", "ReadManga", "https://readmanga.live", ("readmanga.live", "mintmanga.live"), ".tile, .manga-list-item", "h3, .title", "/search", "manga"),
)
BY_ID = {site.id: site for site in SITES}


def site_for(url):
    host = urlsplit(public_url(url, resolve_dns=False)).hostname
    return next((site for site in SITES if host in site.hosts), None)


def clean(value, limit=300):
    return " ".join(str(value or "").split())[:limit]


def link(value, base):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return public_url(urljoin(base, str(value)), resolve_dns=False)
    except SourceError:
        return None


def parse_search(site, text, base, query=""):
    soup = BeautifulSoup(text, "html.parser")
    results, seen = [], set()
    cards = soup.select(site.cards)
    if site.id == "jutsu":
        cards = soup.select("a[href]")
    for card in cards:
        heading = card.select_one(site.title)
        anchor = heading.find_parent("a") if heading else None
        anchor = anchor or card.select_one("a[href]") or (card if card.name == "a" else None)
        if not anchor:
            continue
        url = link(anchor.get("href"), base)
        if not url or urlsplit(url).hostname not in site.hosts or url in seen:
            continue
        image = card.select_one("img")
        title = clean(heading.get_text(" ", strip=True) if heading else anchor.get_text(" ", strip=True))
        title = title or clean(anchor.get("title")) or clean(image.get("alt") if image else "")
        if site.id == "jutsu":
            if not card.select_one(".aaname, .all_anime_global, .all_anime") and not re.search(r"class=[\"'][^\"']*all_anime", str(card)):
                continue
            title = clean((card.select_one(".aaname") or card).get_text(" ", strip=True))
        if not title or (query and site.id == "jutsu" and query.casefold() not in (title + " " + url).casefold()):
            continue
        seen.add(url)
        result = {"provider": site.id, "providerName": site.name, "url": url, "title": title,
                  "kind": site.kind, "dubs": [], "releaseDates": [],
                  "year": int(re.search(r'\b((?:19|20)\d{2})\b',card.get_text(' ',strip=True))[1]) if re.search(r'\b((?:19|20)\d{2})\b',card.get_text(' ',strip=True)) else None}
        if image:
            result["cover"] = link(image.get("data-src") or image.get("src"), base)
        elif site.id == 'jutsu':
            background=card.select_one('.all_anime_image[style]')
            match=re.search(r'url\([\"\']?([^\"\')]+)',background.get('style','')) if background else None
            if match:result['cover']=link(match[1],base)
        # Only labels actually present in the HTML are exposed as voice filters.
        for element in card.select("[data-translation], [data-dubbing], .dubbing, .translation"):
            value = clean(element.get("data-translation") or element.get("data-dubbing") or element.get_text(" "), 120)
            if value and value not in result["dubs"]:
                result["dubs"].append(value)
        results.append(result)
    return results[:24]


def player_choices(text, base):
    """Kodik publishes real translation/season IDs in its HTML select options."""
    soup = BeautifulSoup(text, "html.parser")
    choices = []
    for select in soup.select(".serial-translations-box select, select[name*=translation], select[data-type=translation]"):
        for option in select.select("option"):
            kind = option.get("data-media-type") or option.get("data-type", "serial")
            identity = option.get("data-media-id") or option.get("data-id")
            digest = option.get("data-media-hash") or option.get("data-hash")
            explicit = option.get("data-src") or option.get("data-link") or option.get("value", "")
            target = link(explicit, base) if explicit.startswith(("/", "https:")) else None
            if identity and digest and kind in {"serial", "video", "seria"} and re.fullmatch(r"[\w-]+", identity + digest):
                root = urlsplit(base)
                target = f"https://{root.netloc}/{kind}/{identity}/{digest}/720p"
            if target and (identity or target != base):
                choices.append({"id": str(option.get("value") or identity), "name": clean(option.get("data-title") or option.get_text(" "), 120), "url": target})
    seasons = []
    for option in soup.select(".serial-seasons-box option, select[name*=season] option"):
        number = option.get("value", "")
        target = link(option.get("data-src") or option.get("data-link"), base)
        identity, digest = option.get("data-serial-id") or option.get("data-id"), option.get("data-serial-hash") or option.get("data-hash")
        if identity and digest and re.fullmatch(r"[\w-]+", identity + digest):
            target = f"https://{urlsplit(base).netloc}/serial/{identity}/{digest}/720p"
        if number.isdigit() and 1 <= int(number) <= 1000:
            seasons.append({"number": int(number), "url": target, "name": clean(option.get_text(" "))})
    return choices, seasons


def parse_reader(text, base):
    """ReadManga's HTML reader exposes image locations without a developer API."""
    soup = BeautifulSoup(text, "html.parser")
    pages, chapters = [], []
    for image in soup.select("#mangaPicture, .reader-page img, .manga-pages img, img[data-page]"):
        value = link(image.get("data-src") or image.get("src"), base)
        if value:
            pages.append(value)
    # rm_h.init is parsed as data, never evaluated as JavaScript.
    match = re.search(r"rm_h\.init\s*\(\s*(\[\s*\[.*?\]\s*\])", text, re.S)
    if match:
        import json
        try:
            values = json.loads(match[1])
            for parts in values:
                if isinstance(parts, list) and all(isinstance(part, str) for part in parts[:3]):
                    value = link("".join(parts[:3]), base)
                    if value:
                        pages.append(value)
        except (ValueError, TypeError):
            pass
    for anchor in soup.select(".chapters-link, .chapters a[href], .chapter-link"):
        value = link(anchor.get("href"), base)
        number = episode_number(anchor.get_text(" "))
        if number is None:
            match = re.search(r"(?:глава|chapter|ch)\s*(\d+)", anchor.get_text(" "), re.I)
            number = int(match[1]) if match else None
        if value and number:
            chapters.append({"number": number, "url": value, "title": clean(anchor.get_text(" "))})
    return list(dict.fromkeys(pages)), list({entry["url"]: entry for entry in chapters}.values())


def inspect_source(url, *, http=None, dub_url=None, season=None, kind="anime"):
    own_http = http is None
    http = http or PublicHttp(timeout=(4,7),deadline=time.monotonic()+18)
    try:
        original = public_url(url, resolve_dns=False)
        site = site_for(original)
        if urlsplit(original).path.lower().endswith((".mp4", ".m3u8")):
            return {"provider": "direct", "title": "Видео по ссылке", "url": original,
                    "dubs": [], "seasons": [], "episodes": [{"number": 1, "url": original}], "releases": []}
        text, final, _ = http.document(original)
        page = parse_page(text, final)
        choices, seasons = player_choices(text, final)
        if kind == "ranobe":
            soup = BeautifulSoup(text, "html.parser")
            _, chapters = parse_reader(text, final)
            has_text = bool(soup.select_one(".chapter-content, .text-content, article"))
            return {"provider": site.id if site else "public", "title": page.title, "url": final,
                    "dubs": [], "seasons": [], "episodes": chapters or ([{"number": 1, "url": final}] if has_text else []), "releases": []}
        if kind == "manga" or (site and site.kind == "manga"):
            pages, chapters = parse_reader(text, final)
            return {"provider": site.id if site else "public", "title": page.title, "url": final, "dubs": [], "seasons": [],
                    "episodes": chapters or ([{"number": 1, "url": final}] if pages else []),
                    "pages": pages, "kind": "manga", "releases": []}
        from player_catalog import inspect_catalog
        return inspect_catalog(original, text, final, http, dub_url=dub_url, season=season,
                               provider=site.id if site else 'public', provider_name=site.name if site else 'Публичный источник')
    finally:
        if own_http:
            http.close()


def search_site(site, query, *, http=None):
    own_http = http is None
    http = http or PublicHttp(timeout=(4,6),deadline=time.monotonic()+9)
    try:
        text, final, _ = http.document(site.search_url(query))
        values=parse_search(site,text,final,query)
        if site.id=='anilibria' and not values:
            from public_page_data import releases
            values=releases(text,final,query)
        return {"provider": site.id, "name": site.name, "status": "ok" if values else 'empty', "results": values,
                **({'message':'В публичном HTML нет совпадений. Страница может загружать каталог отдельно в браузере.'} if not values else {})}
    except SourceError as error:
        return {"provider": site.id, "name": site.name, "status": "unavailable", "message": str(error), "results": []}
    finally:
        if own_http:
            http.close()


_search_cache,_search_lock={},threading.Lock()


def search_sources(query, kind="anime"):
    if kind not in {"anime", "manga"}:
        return {"providers": [], "results": [], "checkedAt": int(time.time())}
    key=(query.casefold(),kind)
    with _search_lock:
        cached=_search_cache.get(key)
        if cached and cached[0]>time.monotonic():return cached[1]
    sites = [site for site in SITES if site.id != "sovet" and site.kind == ("manga" if kind == "manga" else "anime")]
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(search_site, site, query) for site in sites]
        for future in as_completed(futures):
            results.append(future.result())
    value={"providers": results, "results": [item for result in results for item in result["results"]], "checkedAt": int(time.time())}
    with _search_lock:
        _search_cache[key]=(time.monotonic()+120,value)
        if len(_search_cache)>128:_search_cache.pop(next(iter(_search_cache)))
    return value


_voice_cache, _voice_lock = {}, threading.Lock()


def voice_availability(query):
    """Bounded HTML lookups, cached for 15 minutes; never a fabricated global dub index."""
    with _voice_lock:
        cached = _voice_cache.get(query.casefold())
        if cached and cached[0] > time.monotonic():
            return cached[1]
    import difflib
    normalize = lambda value: re.sub(r"[^\w]+", " ", value.casefold()).strip()
    target = normalize(query)
    dubs, sources = set(), []
    def check(result):
        identity=result['provider']
        score = lambda item: max(
            difflib.SequenceMatcher(None, target, normalize(item["title"].split("/")[0])).ratio(),
            difflib.SequenceMatcher(None, target, normalize(urlsplit(item["url"]).path)).ratio())
        candidates = sorted(result["results"], key=score, reverse=True)
        if not candidates or score(candidates[0]) < 0.45:
            return None
        candidate = candidates[0]
        # Search results are only candidates. A voice is reported with its source URL.
        http = PublicHttp(timeout=(4,6),deadline=time.monotonic()+10)
        try:
            inspected = inspect_source(candidate["url"], http=http)
            names = [entry["name"] for entry in inspected["dubs"]]
            return {"provider": identity, "title": candidate["title"], "url": candidate["url"], "dubs": names}
        except SourceError:
            pass
        finally:
            http.close()
        return None
    candidates=search_sources(query)['providers']
    with ThreadPoolExecutor(max_workers=4) as executor:
        for result in executor.map(check,candidates):
            if result:sources.append(result);dubs.update(result['dubs'])
    value = {"query": query, "dubs": sorted(dubs), "sources": sources, "checkedAt": int(time.time())}
    with _voice_lock:
        _voice_cache[query.casefold()] = (time.monotonic() + 900, value)
        if len(_voice_cache) > 128:
            _voice_cache.pop(next(iter(_voice_cache)))
    return value
