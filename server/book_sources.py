"""Public-domain book texts: Project Gutenberg and Wikisource.

Both are legal, free full texts: Gutenberg works are public domain in the US,
Wikisource holds public-domain and freely licensed texts.
A book is split into chapters by its own headings (Gutenberg HTML) or by its
subpages (Wikisource), and chapters are returned as plain paragraphs, in the
same shape as the ranobe sources, so the reader and narration are shared.
Only the fixed hosts below are contacted.
"""
from __future__ import annotations

import html as html_tools
import json
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit, parse_qs

import requests
from bs4 import BeautifulSoup
import warnings
try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:  # older bs4
    pass

from source_parser import SourceError

USER_AGENT = "MediaVault/5.1 (https://github.com/Onikri/MediaVault; personal catalogue)"
GUTENBERG = "https://www.gutenberg.org"
WIKISOURCE = {"ru": "Викитека", "uk": "Вікіджерела", "en": "Wikisource", "ja": "ウィキソース", "ko": "위키문헌"}
HOSTS = {"www.gutenberg.org", *(code + ".wikisource.org" for code in WIKISOURCE)}
MAX_BYTES = 24 * 1024 * 1024
MAX_CHAPTERS = 3000
MAX_PARAGRAPHS = 4000
PART = 120  # paragraphs per part when a text has no headings
BOOK_FORMATS = ("text/plain", "text/html", "application/xhtml+xml", "application/epub+zip", "application/x-mobipocket-ebook")
SOURCES = (("gutenberg", "Project Gutenberg"), *((f"wikisource-{code}", name) for code, name in WIKISOURCE.items()))
_cache: dict = {}
_lock = threading.RLock()


class MissingBook(SourceError):
    pass


def _remember(key, ttl, make):
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    value = make()
    with _lock:
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = (time.monotonic() + ttl, value)
    return value


def _get(url, *, params=None, accept="application/json"):
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    try:
        for _ in range(5):
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.netloc not in HOSTS:
                raise SourceError("Этот адрес не относится к библиотекам книг.")
            with requests.get(url, params=params, headers=headers, timeout=(5, 15), stream=True, allow_redirects=False) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["Location"])
                    if url.startswith("http://www.gutenberg.org/") and parts.netloc == "www.gutenberg.org":
                        url = "https://" + url.removeprefix("http://")
                    params = None
                    continue
                if response.status_code == 404:
                    raise MissingBook("Книга не найдена в библиотеке.")
                if response.status_code == 429:
                    raise SourceError("Библиотека ограничила частоту запросов. Попробуй немного позже.")
                response.raise_for_status()
                raw = bytearray()
                for block in response.iter_content(262144):
                    raw.extend(block)
                    if len(raw) > MAX_BYTES:
                        raise SourceError("Книга слишком велика для онлайн-чтения.")
                return bytes(raw).decode(response.encoding or "utf-8", errors="replace")
        raise SourceError("Слишком много перенаправлений библиотеки.")
    except requests.RequestException:
        raise SourceError("Библиотека сейчас недоступна.") from None


def _norm(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def _aliases(title):
    values = [title.get("title"), *(title.get("titles") or {}).values(), *(title.get("aliases") or [])]
    result = []
    for value in values:
        value = " ".join(str(value or "").split())[:200]
        # "Title: subtitle" — the main title is what libraries file it under.
        for variant in (value, re.split(r"[:.(]", value)[0].strip()):
            if len(_norm(variant)) >= 2 and variant not in result:
                result.append(variant)
    return result[:6]


def _surnames(title):
    names = []
    for author in title.get("authors") or []:
        parts = re.split(r"[\s,]+", str(author or "").strip())
        names += [_norm(p) for p in parts if len(_norm(p)) >= 3]
    return set(names)


def _title_match(candidate, aliases):
    value = _norm(candidate)
    for alias in aliases:
        alias = _norm(alias)
        if value == alias or value.startswith(alias + " ") and len(alias) >= 4:
            return True
    return False


# ------------------------------------------------------------ search

def _gutenberg_formats(identity):
    def load():
        text = _get(GUTENBERG + "/ebooks/" + identity + ".opds", accept="application/atom+xml")
        feed = BeautifulSoup(text, "html.parser")
        links = feed.find_all("link", rel=re.compile(r"^http://opds-spec\.org/acquisition"))
        readable = any(link.get("type", "").startswith(BOOK_FORMATS) for link in links)
        language = feed.find(["dc:language", "dcterms:language"])
        return readable, _clean(language.get_text())[:2] if language else "und"
    return _remember(("gutenberg-formats", identity), 6 * 3600, load)


def _gutenberg_search(title, languages):
    """Gutenberg's own OPDS search (fast); "l.xx" limits the language."""
    aliases, surnames, results = _aliases(title), _surnames(title), []
    for alias in aliases[:3]:
        query = alias + (" l." + languages[0] if len(languages) == 1 else "")
        text = _get(GUTENBERG + "/ebooks/search.opds/", params={"query": query}, accept="application/atom+xml")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            feed = BeautifulSoup(text, "html.parser")
        for entry in feed.find_all("entry")[:25]:
            identity = re.search(r"/ebooks/(\d{1,7})\.opds$", _clean(entry.find("id").get_text() if entry.find("id") else ""))
            name = _clean(entry.find("title").get_text() if entry.find("title") else "")
            author = _clean(entry.find("content").get_text() if entry.find("content") else "")
            if not identity or not _title_match(re.split(r"[;:]", name)[0], aliases):
                continue
            if re.search(r"[,;:]\s*(?:a play|a dramatization|study guide)\b", name, re.I) and _norm(name) not in {_norm(alias) for alias in aliases}:
                continue
            links = entry.find_all("link", rel=re.compile(r"^http://opds-spec\.org/acquisition"))
            if links and not any(link.get("type", "").startswith(BOOK_FORMATS) for link in links):
                continue
            if surnames and author and not surnames & {_norm(p) for p in re.split(r"[\s,]+", author)}:
                continue
            url = GUTENBERG + "/ebooks/" + identity[1]
            if any(r["url"] == url for r in results):
                continue
            lang_node = entry.find(["dc:language", "dcterms:language"])
            language = languages[0] if len(languages) == 1 else _clean(lang_node.get_text())[:2] if lang_node else "und"
            details = bool(entry.find("link", rel="subsection", href="/ebooks/" + identity[1] + ".opds"))
            results.append({"provider": "gutenberg", "providerName": "Project Gutenberg", "title": name[:300],
                            "translator": author[:120], "url": url, "language": language, "_formats": identity[1] if details and not links else ""})
        if len(results) >= 6:
            break

    def verify_formats(row):
        identity = row.pop("_formats")
        if not identity:
            return row
        try:
            readable, language = _gutenberg_formats(identity)
        except SourceError:
            return row
        if row["language"] == "und":
            row["language"] = language
        return row if readable else None

    with ThreadPoolExecutor(max_workers=3) as pool:
        return [row for row in pool.map(verify_formats, results[:6]) if row][:4]


def _wikisource_search(title, language):
    aliases, surnames, results = _aliases(title), _surnames(title), []
    api = f"https://{language}.wikisource.org/w/api.php"
    script = {"ja": r"[ぁ-ヿ一-鿿]", "ko": r"[가-힣]", "en": r"[a-z]", "ru": r"[а-яё]", "uk": r"[а-яіїєґ]"}[language]
    localized = [alias for alias in aliases if re.search(script, alias, re.I)]
    exclude = ' -incategory:"Mainspace disambiguation pages" -incategory:"Versions pages"' if language == "en" else ""

    def author_in_title(page):
        ending = re.search(r"\(([^()]+)\)\s*$", page)
        if not ending or re.search(r"\d{4}|\b(?:edition|version|translation)\b", ending[1], re.I):
            return set()
        return {_norm(p) for p in re.split(r"[\s,]+", ending[1])}

    for alias in (localized or ([] if language in {"ja", "ko"} else aliases))[:3]:
        phrase = alias.replace('"', " ")
        data = json.loads(_get(api, params={"action": "query", "list": "search", "srsearch": f'intitle:"{phrase}"' + exclude,
                                            "srnamespace": 0, "srlimit": 12, "format": "json"}))
        for row in (data.get("query") or {}).get("search") or []:
            page = str(row.get("title") or "")
            # Subpages are chapters of another page; "(ДО)" is pre-reform spelling.
            if "/" in page or re.search(r"\(ДО\)|\bДО\)$", page) or not _title_match(page, aliases):
                continue
            if language == "en" and re.search(r"\([^)]*\b(?:film|television|screenplay)\b[^)]*\)$", page, re.I):
                continue
            author = author_in_title(page)
            if surnames and author and not surnames & author:
                continue
            url = f"https://{language}.wikisource.org/wiki/" + quote(page.replace(" ", "_"))
            if any(r["url"] == url for r in results):
                continue
            results.append({"provider": "wikisource-" + language, "providerName": WIKISOURCE[language],
                            "title": page[:300], "translator": "", "url": url, "language": language})
        if results:
            break
    matching_author = [r for r in results if surnames & author_in_title(r["title"])]
    if matching_author:
        results = matching_author
    return results[:4]


def search(title, language="all"):
    if not isinstance(title, dict) or not _aliases(title):
        raise SourceError("Выбери конкретную книгу из каталога.")
    if language not in {"all", *WIKISOURCE}:
        raise SourceError("Выбери поддерживаемый язык книги.")
    jobs = [("gutenberg", "Project Gutenberg", language, lambda: _gutenberg_search(title, list(WIKISOURCE) if language == "all" else [language]))]
    for code, name in WIKISOURCE.items():
        if language in {"all", code}:
            jobs.append(("wikisource-" + code, name, code, lambda code=code: _wikisource_search(title, code)))

    def work(job):
        identity, name, lang, run = job
        try:
            found = run()
            return {"provider": identity, "name": name, "language": lang, "status": "ok" if found else "empty",
                    "message": "Найдено: " + str(len(found)) if found else "Точное совпадение не найдено.", "results": found}
        except SourceError as error:
            return {"provider": identity, "name": name, "language": lang, "status": "unavailable", "message": str(error), "results": []}
        except (ValueError, TypeError, KeyError, AttributeError):
            return {"provider": identity, "name": name, "language": lang, "status": "unavailable", "message": "Формат библиотеки изменился.", "results": []}

    key = ("search", language, json.dumps([_aliases(title), sorted(_surnames(title))], ensure_ascii=False))

    def make():
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            providers = list(pool.map(work, jobs))
        return {"results": [{**r, "kind": "book"} for p in providers for r in p["results"]],
                "providers": [{k: p[k] for k in ("provider", "name", "language", "status", "message")} for p in providers],
                "language": language, "checkedAt": int(time.time())}

    return _remember(key, 600, make)


# ------------------------------------------------------------ text

def _clean(text):
    return re.sub(r"\s+", " ", str(text or "").replace("\xa0", " ")).strip()


def _chapters_from_html(html, *, drop=()):
    """Split a whole book page into chapters at h2/h3 headings."""
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script,style,noscript,table,img,figure,sup.reference,.reference,ol.references,.mw-references-wrap,"
                            ".ws-noexport,.noprint,.caption,.pagenum,.pageno,.ws-pagenum,.pg-boilerplate,#pg-header,#pg-footer,#pg-machine-header,.toc,pre," + ",".join(drop or ["x-none"])):
        node.decompose()
    body = soup.body or soup
    chapters, pending = [], ""
    wanted = {"h1", "h2", "h3", "h4", "p", "blockquote", "center"}
    for node in body.find_all(lambda tag: tag.name in wanted or tag.name == "div" and tag.get("role") == "heading"):
        if node.name == "div":
            node.name = "h3"
        if node.name in {"p", "blockquote", "center"} and node.find_parent(["p", "blockquote", "center"]):
            continue
        text = re.sub(r"\{[ivxlcdm\d]+\}", " ", _clean(node.get_text(" ")), flags=re.I).strip()
        if not text or re.fullmatch(r"[*\-_=·.—–\s]{3,}", text):
            continue
        if node.name == "h1":
            continue
        # Chapter keyword inside an illustrated heading: keep "CHAPTER II." only.
        keyword = re.search(r"(?:chapter|глава|розділ|часть|частина|book|книга|том)\s+[\wivxlc]+\.?.*$", text, re.I)
        if node.name in {"h2", "h3", "h4"} and keyword and keyword.start() > 0:
            text = keyword.group(0)
        # A lone numeral or "Глава N" in an ordinary paragraph is a heading too.
        if node.name == "center":
            node.name = "p" if node.find(["p", "div"]) or len(text) > 80 else "center"
            if node.name == "p" and node.find(["p", "div"]):
                continue  # its own paragraphs follow in document order
        if node.name in {"p", "center"} and re.fullmatch(r"(?:[IVXLC]{1,7}|\d{1,3}|(?:глава|розділ|chapter|часть|частина)\s+[\wIVXLC]{1,12})\.?", text, re.I):
            node.name = "h3"
        if node.name in {"h2", "h3", "h4"}:
            if chapters and not chapters[-1]["paragraphs"]:
                # "Book One" followed by "Chapter I": keep both in one name.
                chapters[-1]["title"] = (chapters[-1]["title"] + " · " + text)[:200]
            else:
                chapters.append({"title": text[:200], "paragraphs": []})
            continue
        if node.name == "center" and len(text) <= 80 and not re.search(r"[.!?…]\s*\S", text):
            node.name = "h3" if not chapters or chapters[-1]["paragraphs"] else "h3"
            if chapters and not chapters[-1]["paragraphs"]:
                chapters[-1]["title"] = (chapters[-1]["title"] + " · " + text)[:200]
            else:
                chapters.append({"title": text[:200], "paragraphs": []})
            continue
        link = node.find("a")
        if link and _clean(link.get_text(" ")) == text and len(text) < 120:
            continue  # contents line
        if re.fullmatch(r"[*\-_=·.\s]{3,}", text):
            continue
        if not chapters:
            chapters.append({"title": pending or "Начало", "paragraphs": []})
        chapters[-1]["paragraphs"].append(text[:4000])
    chapters = [c for c in chapters if c["paragraphs"]]
    result = []
    for chapter in chapters:
        rows = chapter["paragraphs"]
        if len(rows) <= PART * 2:
            result.append(chapter)
            continue
        for start in range(0, len(rows), PART):
            result.append({"title": chapter["title"] + " · часть " + str(start // PART + 1), "paragraphs": rows[start:start + PART]})
    return result[:MAX_CHAPTERS]


def _gutenberg_book(identity):
    def make():
        base = GUTENBERG + "/ebooks/" + identity
        try:
            html = _get(GUTENBERG + "/cache/epub/" + identity + "/pg" + identity + "-images.html", accept="text/html")
        except MissingBook:
            try:
                html = _get(base + ".html", accept="text/html")
            except MissingBook:
                text = _get(base + ".txt.utf-8", accept="text/plain")
                if text.lstrip().startswith("<"):
                    raise SourceError("Библиотека не предоставила текст книги.")
                parts = re.split(r"^\*{3}\s*(?:START|END) OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*$", text, flags=re.M | re.I)
                title = re.search(r"^Title:\s*(.+)$", parts[0], re.M | re.I)
                original = re.search(r"^Language:\s*(\w+)", parts[0], re.M | re.I)
                language = {"english": "en", "russian": "ru", "ukrainian": "uk", "japanese": "ja", "korean": "ko"}.get(original[1].lower() if original else "", "und")
                paragraphs = [p.strip() for p in re.split(r"\r?\n\s*\r?\n", parts[1] if len(parts) > 1 else text) if p.strip()]
                html = (f'<html lang="{language}"><head><title>' + html_tools.escape(title[1] if title else "Project Gutenberg " + identity)
                        + "</title></head><body>" + "".join("<p>" + html_tools.escape(p) + "</p>" for p in paragraphs) + "</body></html>")
        head = BeautifulSoup(html[:200000], "html.parser")
        meta = lambda name: _clean((head.find("meta", attrs={"name": name}) or {}).get("content", "")) if head.find("meta", attrs={"name": name}) else ""
        title = meta("dc.title") or _clean(head.title.get_text() if head.title else "").split(" | ")[0] or "Project Gutenberg " + identity
        author = meta("dc.creator")
        lang_attr = (head.find("html") or {}).get("lang", "") if head.find("html") else ""
        language = meta("dc.language")[:2] or str(lang_attr)[:2] or "en"
        chapters = _chapters_from_html(html)
        if not chapters:
            raise SourceError("Не удалось разобрать текст книги.")
        return {"title": title[:300], "authors": [author] if author else [], "language": language if language in WIKISOURCE else "und", "chapters": chapters}
    return _remember(("gutenberg", identity), 6 * 3600, make)


def _wiki_page(language, page):
    return _remember(("wikipage", language, page), 6 * 3600, lambda: _wiki_html(language, page))


def _wiki_html(language, page):
    return _get(f"https://{language}.wikisource.org/api/rest_v1/page/html/" + quote(page.replace(" ", "_"), safe=""), accept="text/html")


def _subpages(html, page):
    soup, prefix, found = BeautifulSoup(html, "html.parser"), page.replace(" ", "_") + "/", []
    for link in soup.select('a[rel~="mw:WikiLink"], a[href^="./"]'):
        target = unquote(str(link.get("href") or "")).split("#")[0]
        target = target[2:] if target.startswith("./") else target
        if target.startswith(prefix) and target not in [t for t, _ in found] and not target.endswith("/ДО"):
            found.append((target, _clean(link.get_text(" "))[:200] or target[len(prefix):].replace("_", " ")))
    return found


def _wikisource_book(language, page):
    def make():
        html = _wiki_html(language, page)
        subpages = _subpages(html, page)[:MAX_CHAPTERS]
        chapters = []
        if subpages and language in {"en", "ja", "ko"}:
            # Build the TOC from the edition page. Fetch a subpage only when
            # the reader selects it, so one broken chapter cannot block entry.
            chapters = [{"title": name, "page": target} for target, name in subpages]
        elif len(subpages) >= 2:
            # Volumes that only list their own chapters are expanded one level.
            first = _wiki_page(language, subpages[0][0]) if len(subpages) <= 40 else ""
            nested = first and len(_subpages(first, subpages[0][0])) >= 2 and sum(len(c["paragraphs"]) for c in _chapters_from_html(first)) < 8
            deadline = time.monotonic() + 40
            for target, name in subpages:
                page_html = (first if target == subpages[0][0] and first else _wiki_page(language, target)) if len(subpages) <= 40 and time.monotonic() < deadline else ""
                inner = _subpages(page_html, target) if nested and page_html else []
                parts = _chapters_from_html(page_html) if page_html and len(inner) < 2 else []
                if len(inner) >= 2:
                    chapters += [{"title": (name + " · " + label)[:200], "page": page} for page, label in inner]
                elif len(parts) >= 2:
                    chapters += [{"title": (name + " · " + part["title"])[:200], "page": target, "part": index} for index, part in enumerate(parts)]
                else:
                    chapters.append({"title": name, "page": target})
            chapters = chapters[:MAX_CHAPTERS]
        else:
            for index, chapter in enumerate(_chapters_from_html(html)):
                chapters.append({"title": chapter["title"], "index": index, "paragraphs": chapter["paragraphs"]})
        if not chapters:
            raise SourceError("На странице Викитеки нет текста книги.")
        return {"title": page.replace("_", " ")[:300], "language": language, "chapters": chapters}
    return _remember(("wikisource", language, page), 6 * 3600, make)


def route(url):
    parts = urlsplit(str(url or ""))
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.netloc != host or host not in HOSTS:
        return None
    selected = parse_qs(parts.query).get("mv_chapter", [""])[0]
    if selected and not selected.isdigit():
        raise SourceError("Некорректная ссылка на главу.")
    if host == "www.gutenberg.org":
        match = re.fullmatch(r"/ebooks/(\d{1,7})/?", parts.path)
        if match:
            return "gutenberg", match[1], selected
    if host.removesuffix(".wikisource.org") in WIKISOURCE:
        match = re.fullmatch(r"/wiki/([^?#]{1,300})", unquote(parts.path))
        if match:
            page = match[1].replace(" ", "_")
            if ":" in page.split("/")[0] or "/" in page:
                raise SourceError("Открой страницу самого произведения в Викитеке.")
            return "wikisource-" + host[:2], page, selected
    return None


def _book_url(identity, book):
    return GUTENBERG + "/ebooks/" + book if identity == "gutenberg" else f"https://{identity[-2:]}.wikisource.org/wiki/" + quote(book)


def inspect(url):
    identity, book, _ = route(url) or (None, None, None)
    if not identity:
        raise SourceError("Эта ссылка не относится к библиотекам книг.")
    data = _gutenberg_book(book) if identity == "gutenberg" else _wikisource_book(identity[-2:], book)
    base = _book_url(identity, book)
    episodes = [{"number": i + 1, "season": 1, "title": c["title"] or "Глава " + str(i + 1), "translator": "",
                 "language": data["language"], "url": base + "?" + urlencode({"mv_chapter": i})} for i, c in enumerate(data["chapters"])]
    return {"provider": identity, "providerName": dict(SOURCES)[identity], "kind": "book", "title": data["title"],
            "aliases": [data["title"]], "authors": data.get("authors", []), "url": base, "language": data["language"],
            "episodes": episodes, "seasons": [{"number": 1, "name": "Книга"}]}


def chapter(url):
    identity, book, selected = route(url) or (None, None, None)
    if not identity:
        raise SourceError("Эта ссылка не относится к библиотекам книг.")
    if selected == "":
        raise SourceError("Выбери конкретную главу.")
    data = _gutenberg_book(book) if identity == "gutenberg" else _wikisource_book(identity[-2:], book)
    index = int(selected)
    if index >= len(data["chapters"]):
        raise SourceError("Такой главы в книге нет.")
    item = data["chapters"][index]
    if "paragraphs" in item:
        paragraphs = item["paragraphs"]
    else:
        language = identity[-2:]
        html = _wiki_page(language, item["page"])
        parts = _chapters_from_html(html)
        if "part" in item and item["part"] < len(parts):
            return {"title": item["title"], "paragraphs": parts[item["part"]]["paragraphs"][:MAX_PARAGRAPHS], "url": url, "language": data["language"]}
        paragraphs = [p for part in parts for p in ([part["title"]] if len(parts) > 1 else []) + part["paragraphs"]]
        if not paragraphs and _subpages(html, item["page"]):
            paragraphs = ["Эта часть состоит из глав: " + ", ".join(name for _, name in _subpages(html, item["page"])[:40]) + "."]
    return {"title": item["title"], "paragraphs": paragraphs[:MAX_PARAGRAPHS], "url": url, "language": data["language"]}
