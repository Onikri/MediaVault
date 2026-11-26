"""Public-domain book texts: Project Gutenberg, Standard Ebooks, Wikisource
and the public scans of the Internet Archive.

All are legal, free full texts: Gutenberg works are public domain in the US,
Standard Ebooks are proofread editions of them, Wikisource holds public-domain
and freely licensed texts, and an Internet Archive item is read only when Open
Library marks it public (ebook_access=public) and the item itself is not
access-restricted: lent and print-disabled books are never opened.
A book is split into chapters by its own headings (Gutenberg HTML, the single
XHTML page of Standard Ebooks, the headings of a scan's text) or by its
subpages (Wikisource), and chapters are returned as plain paragraphs, in the
same shape as the ranobe sources, so the reader and narration are shared.

A catalogue card first gets the books it is known to be: the free-text
identifiers Open Library keeps for the work (one cached search.json request:
Gutenberg numbers, Standard Ebooks ids, Internet Archive items) and the
Gutenberg rows of the catalogue index with the same title and the same
author's surname (catalogue_gutenberg, content_names). Those answer at once
(pending); the live title search of the libraries continues in the background
and its answer keeps the old form. Only the fixed hosts below are contacted.
"""
from __future__ import annotations

import html as html_tools
import json
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
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
STANDARD = "https://standardebooks.org"
ARCHIVE = "https://archive.org"
HOSTS = {"www.gutenberg.org", "standardebooks.org", "archive.org", *(code + ".wikisource.org" for code in WIKISOURCE)}
# archive.org serves the files of an item from its storage hosts
# (ia800300.us.archive.org, dn720003.ca.archive.org …).
ARCHIVE_STORAGE = re.compile(r"[a-z0-9-]{1,40}(?:\.[a-z0-9-]{1,20})?\.archive\.org")
OPENLIBRARY_SEARCH = "https://openlibrary.org/search.json"
OPENLIBRARY_FIELDS = "key,title,author_name,id_project_gutenberg,id_standard_ebooks,ia,ebook_access,language"
# Open Library's MARC language codes of the reader's languages.
MARC = {"eng": "en", "rus": "ru", "ukr": "uk", "jpn": "ja", "kor": "ko"}
# Catalogue hosts asked only for the original title of a work (never texts).
TITLE_HOSTS = {"openlibrary.org", "api.fantlab.ru"}
MAX_BYTES = 24 * 1024 * 1024
MAX_CHAPTERS = 3000
MAX_PARAGRAPHS = 4000
PART = 120  # paragraphs per part when a text has no headings
BOOK_FORMATS = ("text/plain", "text/html", "application/xhtml+xml", "application/epub+zip", "application/x-mobipocket-ebook")
SOURCES = (("gutenberg", "Project Gutenberg"), ("standard-ebooks", "Standard Ebooks"), ("internet-archive", "Internet Archive · скан"),
           *((f"wikisource-{code}", name) for code, name in WIKISOURCE.items()))
# Evidence an index or identifier answer may rest on (the live search's rule).
STRONG = {"external_id", "exact_title", "title_and_season"}
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
    origin = urlsplit(url).netloc
    try:
        for _ in range(5):
            parts = urlsplit(url)
            storage = origin == "archive.org" and ARCHIVE_STORAGE.fullmatch(parts.netloc)
            if parts.scheme != "https" or parts.netloc not in HOSTS | TITLE_HOSTS and not storage:
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
    values = [title.get("title"), *(title.get("titles") or {}).values(), *(title.get("aliases") or []), *(title.get("_original") or [])]
    result = []
    for value in values:
        value = " ".join(str(value or "").split())[:200]
        variants = [value, re.split(r"[:.(]", value)[0].strip()]
        if "&" in value:
            # "Гордость & предубеждение" is filed as "Гордость и предубеждение".
            word = "и" if re.search(r"[а-яёіїєґ]", value, re.I) else "and"
            variants.insert(0, re.sub(r"\s*&\s*", f" {word} ", value))
        # "Title: subtitle" — the main title is what libraries file it under.
        for variant in variants:
            if len(_norm(variant)) >= 2 and variant not in result:
                result.append(variant)
    return result[:8]


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
    # Gutenberg files most books under their Latin-script title.
    for alias in sorted(aliases, key=lambda a: not re.search(r"[a-z]", a, re.I))[:3]:
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


def _original_titles(title):
    """Original (Latin-script) title of a catalogue work that arrived only with
    its Russian or Ukrainian name: Open Library and Fantlab know it by id."""
    if any(re.search(r"[a-z]", a, re.I) for a in _aliases(title)):
        return []
    ids, found = title.get("ids") or {}, []
    library, fantlab = str(ids.get("openlibrary") or ""), str(ids.get("fantlab") or "")

    def lookup(kind, identity):
        def load():
            try:
                if kind == "openlibrary":
                    return str(json.loads(_get(f"https://openlibrary.org/works/{identity}.json")).get("title") or "")[:200]
                return str(json.loads(_get(f"https://api.fantlab.ru/work/{identity}")).get("work_name_orig") or "")[:200]
            except (SourceError, ValueError, AttributeError):
                return ""
        return _remember(("original", kind, identity), 24 * 3600, load)

    if re.fullmatch(r"OL\d{1,12}W", library):
        found.append(lookup("openlibrary", library))
    if re.fullmatch(r"\d{1,9}", fantlab) and not any(found):
        found.append(lookup("fantlab", fantlab))
    return [value for value in found if value]


def _catalogue_ids(title):
    """Free texts Open Library knows for the card's work, by identifier.

    One search.json request per work (cached a day): Gutenberg numbers,
    Standard Ebooks ids and, only when the work's best edition is public,
    its Internet Archive items. Its title and authors complete a card that
    arrived without them. {} when the card has no Open Library id or the
    request fails (the failure is not cached)."""
    library = str((title.get("ids") or {}).get("openlibrary") or "")
    if not re.fullmatch(r"OL\d{1,12}W", library):
        return {}

    def load():
        data = json.loads(_get(OPENLIBRARY_SEARCH, params={"q": "key:/works/" + library, "fields": OPENLIBRARY_FIELDS, "limit": 1}))
        doc = next((d for d in data.get("docs") or [] if isinstance(d, dict) and d.get("key") == "/works/" + library), None)
        if not doc:
            return {}
        listed = lambda field: [str(v).strip() for v in doc.get(field) or [] if isinstance(v, (str, int))] if isinstance(doc.get(field), list) else []
        standard = [re.sub(r"^(?:https://standardebooks\.org)?/?(?:ebooks/)?", "", v).strip("/") for v in listed("id_standard_ebooks")]
        return {"title": str(doc.get("title") or "")[:200], "authors": [a[:120] for a in listed("author_name")][:4],
                "gutenberg": list(dict.fromkeys(v for v in listed("id_project_gutenberg") if re.fullmatch(r"\d{1,7}", v)))[:6],
                "standard": list(dict.fromkeys(v for v in standard if _standard_id(v)))[:3],
                "ia": list(dict.fromkeys(v for v in listed("ia") if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", v)))[:6] if doc.get("ebook_access") == "public" else [],
                "languages": [MARC.get(v, v) for v in listed("language")][:6]}
    try:
        return _remember(("openlibrary-ids", library), 24 * 3600, load)
    except (SourceError, ValueError, TypeError, AttributeError):
        return {}


def _fold(value):
    value = unicodedata.normalize("NFKD", _norm(value))
    return "".join(c for c in value if not unicodedata.combining(c))


def _last_names(authors):
    """Surnames of 'First Last' (or 'Last, First') names, accents folded."""
    found = set()
    for author in authors or []:
        name = str(author or "").strip()
        if "," in name:
            name = name.split(",")[0]
        words = [w for w in _fold(name).split() if not re.fullmatch(r"(?:jr|sr|[ivx]+)", w)]
        if words and len(words[-1]) >= 2:
            found.add(words[-1])
    return found


def _one_edit(left, right):
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) <= 1
    short, long = sorted((left, right), key=len)
    return any(long[:i] + long[i + 1:] == short for i in range(len(long)))


def _same_author(card, row):
    """One surname in common; a one-letter spelling difference only in long
    names (Dostoevsky / Dostoyevsky). No author on either side is no match."""
    left, right = _last_names(card), _last_names(row)
    return any(a == b or len(a) >= 6 and len(b) >= 6 and _one_edit(a, b) for a in left for b in right)


@contextmanager
def _catalogue():
    from manga_discovery import catalogue_reader, manager
    with catalogue_reader(manager()) as db:
        yield db


def _index(title, numbers):
    """Gutenberg rows of the catalogue index: by number, and by name for a card
    with an author. Read-only; nothing on any failure."""
    authors = title.get("authors") or []
    if not numbers and not authors:
        return {}, []
    try:
        import content_names
        from content_catalog import title_key
        from title_identity import aliases
        with _catalogue() as db:
            if not content_names.present(db):
                return {}, []
            by_number = {}
            if numbers:
                keys = [title_key("book", "gutenberg", "gutenberg:" + n) for n in numbers]
                for (raw,) in db.execute("SELECT raw FROM content_titles WHERE id IN (" + ",".join("?" for _ in keys) + ")", keys):
                    row = json.loads(raw)
                    by_number[str(row.get("providerId") or "")] = row
            named = content_names.lookup(db, "book", [*aliases(title), *(title.get("_original") or [])]) if authors else []
        return by_number, named
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Could not read the Gutenberg rows of the catalogue")
        return {}, []


def _same_book(title, row):
    """The live search's identity rule (match_title, strong evidence only) and
    the author's surname: one title by another writer is another book."""
    from title_identity import match_title
    accepted, evidence = match_title(title, row)
    if not accepted or evidence not in STRONG or not _same_author(title.get("authors"), row.get("authors")):
        return False, evidence
    return True, evidence


def _row_language(row, facts):
    language = str((row or {}).get("language") or "")
    if not language or language == "und":
        languages = set((facts or {}).get("languages") or [])
        language = next(iter(languages)) if len(languages) == 1 else "und"
    return language[:3]


def _gutenberg_result(number, row, title, facts, evidence):
    return {"provider": "gutenberg", "providerName": "Project Gutenberg", "title": str((row or {}).get("title") or title.get("title") or "")[:300],
            "translator": ", ".join((row or {}).get("authors") or [])[:120], "url": GUTENBERG + "/ebooks/" + number,
            "language": _row_language(row, facts), "matchEvidence": evidence, "indexed": bool(row)}


def _ia_item(identifier):
    """An archive.org item's own metadata: public only when it is not lent."""
    def load():
        data = json.loads(_get(ARCHIVE + "/metadata/" + identifier + "/metadata"))
        meta = data.get("result") if isinstance(data, dict) else None
        if not isinstance(meta, dict) or not meta:
            raise MissingBook("Книга не найдена в Internet Archive.")
        first = lambda value: _clean(value[0] if isinstance(value, list) and value else value if isinstance(value, str) else "")
        restricted = str(meta.get("access-restricted-item") or "").lower() == "true"
        language = first(meta.get("language")).lower()
        return {"public": not restricted and first(meta.get("mediatype")) in {"", "texts"}, "title": first(meta.get("title"))[:300],
                "creator": first(meta.get("creator"))[:120], "language": MARC.get(language, language[:2] or "und")}
    return _remember(("ia-item", identifier), 6 * 3600, load)


def _fast(title, facts):
    """Books of the card known by identifier or from the index, without a title search."""
    numbers = list(dict.fromkeys([str(n) for n in [(title.get("ids") or {}).get("gutenberg")] if re.fullmatch(r"\d{1,7}", str(n or ""))]
                                 + (facts.get("gutenberg") or [])))[:6]
    by_number, named = _index(title, numbers)
    # Rows the index holds (texts of the feed) go first; an unknown number
    # (the index is still filling) stays after them.
    found = [_gutenberg_result(n, by_number[n], title, facts, "external_id") for n in numbers if n in by_number]
    found += [_gutenberg_result(n, None, title, facts, "external_id") for n in numbers if n not in by_number]
    for identity in facts.get("standard") or []:
        found.append({"provider": "standard-ebooks", "providerName": "Standard Ebooks", "title": str(facts.get("title") or title.get("title") or "")[:300],
                      "translator": ", ".join(facts.get("authors") or [])[:120], "url": STANDARD + "/ebooks/" + identity,
                      "language": "en", "matchEvidence": "external_id"})
    for row in named:
        accepted, evidence = _same_book(title, row)
        number = str(row.get("providerId") or "")
        if accepted and re.fullmatch(r"\d{1,7}", number):
            found.append(_gutenberg_result(number, row, title, facts, evidence))
    if not found:
        # The last resort: a public scan (two items checked at most).
        for identifier in (facts.get("ia") or [])[:2]:
            try:
                item = _ia_item(identifier)
            except SourceError:
                continue
            if item["public"]:
                found.append({"provider": "internet-archive", "providerName": dict(SOURCES)["internet-archive"],
                              "title": item["title"] or str(title.get("title") or "")[:300], "translator": item["creator"],
                              "url": ARCHIVE + "/details/" + identifier, "language": item["language"], "matchEvidence": "external_id", "scan": True})
                break
    unique, seen = [], set()
    for row in found:
        if row["url"] not in seen:
            seen.add(row["url"])
            unique.append({**row, "kind": "book"})
    return unique[:6]


def _prepared(title):
    """The card with the facts its Open Library work adds (authors, original title)."""
    facts = _catalogue_ids(title)
    title = dict(title)
    if facts.get("authors") and not title.get("authors"):
        title["authors"] = facts["authors"]
    if "_original" not in title:
        latin = any(re.search(r"[a-z]", a, re.I) for a in _aliases(title))
        known = facts.get("title") if facts.get("title") and re.search(r"[a-z]", facts["title"], re.I) else ""
        title["_original"] = [] if latin else [known] if known else _original_titles(title)
    return title, facts


def search(title, language="all"):
    if not isinstance(title, dict):
        raise SourceError("Выбери конкретную книгу из каталога.")
    if language not in {"all", *WIKISOURCE}:
        raise SourceError("Выбери поддерживаемый язык книги.")
    title, facts = _prepared(title)
    if not _aliases(title):
        raise SourceError("Выбери конкретную книгу из каталога.")
    fast = _fast(title, facts)
    if not fast:
        return _live(title, language)
    key = ("merged", language, json.dumps([_aliases(title), sorted(_surnames(title)), [r["url"] for r in fast]], ensure_ascii=False))
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        if key not in _running:
            _running.add(key)
            threading.Thread(target=_background, args=(title, language, key, fast), daemon=True, name="book-search").start()
    # The books known by identifier or from the index answer at once; the
    # libraries are still searched (pending) and the next request merges them.
    lead = [r for r in fast if language == "all" or r["language"] == language]
    found = {r["provider"] for r in fast}
    providers = [{"provider": identity, "name": name, "language": source_language,
                  "status": "ok" if identity in found else "pending",
                  "message": "Найдено по каталогу: " + str(sum(r["provider"] == identity for r in fast)) if identity in found else "Поиск продолжается."}
                 for identity, name, source_language in _jobs(language, fast)]
    return {"results": lead + [r for r in fast if r not in lead], "providers": providers, "language": language,
            "checkedAt": int(time.time()), "pending": True, **({"fallback": "all"} if not lead else {})}


_running = set()


def _jobs(language, fast=()):
    """(provider, name, language) of the libraries a search asks."""
    rows = [("gutenberg", "Project Gutenberg", language)]
    rows += [(r, dict(SOURCES)[r], "en" if r == "standard-ebooks" else "all") for r in ("standard-ebooks", "internet-archive") if any(f["provider"] == r for f in fast)]
    return rows + [("wikisource-" + code, name, code) for code, name in WIKISOURCE.items() if language in {"all", code}]


def _background(title, language, key, fast):
    try:
        value = _merged(title, language, fast)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Book live search failed")
        value, ttl = {"results": fast, "providers": [], "language": language, "checkedAt": int(time.time())}, 30
    else:
        ttl = 600
    with _lock:
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = (time.monotonic() + ttl, value)
        _running.discard(key)


def _merged(title, language, fast):
    """The live answer with the identifier/index books: those in the reader's
    language first, the others after the libraries' own results."""
    skip = {"gutenberg"} if any(r["provider"] == "gutenberg" for r in fast) else set()
    live = _live(title, language, skip)
    lead = [r for r in fast if language == "all" or r["language"] == language]
    rows = {}
    for row in [*lead, *live["results"], *fast]:
        rows.setdefault(row["url"], row)
    found = {r["provider"] for r in fast}
    known = [{"provider": identity, "name": name, "language": source_language, "status": "ok",
              "message": "Найдено по каталогу: " + str(sum(r["provider"] == identity for r in fast))}
             for identity, name, source_language in _jobs(language, fast) if identity in found]
    value = {"results": list(rows.values()), "providers": known + [p for p in live["providers"] if p["provider"] not in found],
             "language": language, "checkedAt": live["checkedAt"]}
    if language != "all" and value["results"] and not any(r["language"] == language for r in value["results"]):
        # No text in the reader's language: the original edition (the reader shows its language).
        value["fallback"] = "all"
    return value


def _live(title, language, skip=frozenset()):
    """The libraries' own title search (Gutenberg OPDS, Wikisource)."""
    jobs = [] if "gutenberg" in skip else [("gutenberg", "Project Gutenberg", language, lambda: _gutenberg_search(title, list(WIKISOURCE) if language == "all" else [language]))]
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

    key = ("search", language, json.dumps([_aliases(title), sorted(_surnames(title)), sorted(skip)], ensure_ascii=False))

    def make():
        with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
            providers = list(pool.map(work, jobs))
        return {"results": [{**r, "kind": "book"} for p in providers for r in p["results"]],
                "providers": [{k: p[k] for k in ("provider", "name", "language", "status", "message")} for p in providers],
                "language": language, "checkedAt": int(time.time())}

    found = _remember(key, 600, make)
    if language != "all" and not found["results"]:
        # No free text in the reader's language: offer the original edition
        # instead of an empty shelf (the reader shows its language).
        wider = _live(title, "all", skip)
        if wider["results"]:
            return {**wider, "language": language, "fallback": "all", "providers": found["providers"] + wider["providers"]}
    return found


# ------------------------------------------------------------ text

def _clean(text):
    return re.sub(r"\s+", " ", str(text or "").replace("\xa0", " ")).strip()


def _chapters_from_html(html, *, drop=()):
    """Split a whole book page into chapters at h2/h3 headings."""
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script,style,noscript,table,img,figure,sup.reference,.reference,ol.references,.mw-references-wrap,"
                            ".ws-noexport,.noprint,.caption,.pagenum,.pageno,.ws-pagenum,.pg-boilerplate,#pg-header,#pg-footer,#pg-machine-header,.toc,pre," + ",".join(drop or ["x-none"])):
        node.decompose()
    for node in soup.find_all("br"):
        node.replace_with(" ")
    body = soup.body or soup
    chapters, pending = [], ""
    wanted = {"h1", "h2", "h3", "h4", "p", "blockquote", "center"}
    for node in body.find_all(lambda tag: tag.name in wanted or tag.name == "div" and tag.get("role") == "heading"):
        if node.name == "div":
            node.name = "h3"
        if node.name in {"p", "blockquote", "center"} and node.find_parent(["p", "blockquote", "center"]):
            continue
        # Inline markup is joined as written: a drop cap "<span>I</span>t is"
        # stays "It is" (line breaks were turned into spaces above).
        text = re.sub(r"\{[ivxlcdm\d]+\}", " ", _clean(node.get_text("")), flags=re.I).strip()
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


def _standard_id(value):
    """author/title[/translator…] of a Standard Ebooks book page."""
    parts = str(value or "").split("/")
    return 2 <= len(parts) <= 4 and all(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", part) for part in parts) and not {"text", "downloads", "single-page"} & set(parts)


# Sections of a Standard Ebooks page that are not the book's text.
STANDARD_FRAME = re.compile(r"\b(?:titlepage|halftitlepage|imprint|colophon|copyright-page|toc|loi|endnotes|noteref)\b")


def _standard_book(identity):
    """The "Read online" single XHTML page of a Standard Ebooks book."""
    def make():
        html = _get(STANDARD + "/ebooks/" + identity + "/text/single-page", accept="application/xhtml+xml,text/html")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            soup = BeautifulSoup(html, "html.parser")
        root = soup.find("html")
        language = str((root.get("xml:lang") or root.get("lang") or "en") if root else "en")[:2].lower()
        author = soup.find(attrs={"epub:type": re.compile(r"\bz3998:author\b")})
        author = _clean(author.get_text())[:120] if author else ""
        title = _clean(soup.title.get_text() if soup.title else "")
        title = re.sub(r"\s+[-–—|]\s+Standard Ebooks$", "", title) or identity.split("/")[1].replace("-", " ").title()
        for node in soup.find_all(attrs={"epub:type": STANDARD_FRAME}):
            node.decompose()
        for node in soup.select("nav"):
            node.decompose()
        # "Chapter 1" and its name in one heading group are one chapter title.
        for node in soup.select("hgroup p"):
            node.name = "h4"
        chapters = _chapters_from_html(str(soup))
        if not chapters:
            raise SourceError("Не удалось разобрать текст книги.")
        return {"title": title[:300], "authors": [author] if author else [],
                "language": language if language in WIKISOURCE else "und", "chapters": chapters}
    return _remember(("standard", identity), 6 * 3600, make)


SCAN_HEADING = re.compile(r"(?:chapter|book|part|глава|книга|часть|розділ|частина)\s+[\wivxlc]{1,12}\.?(?:\s.{0,60})?|[IVXLC]{1,7}\.?", re.I)


def _chapters_from_scan(text):
    """Paragraphs of a scan's OCR text (blank lines), chapters at its headings.
    Lone page numbers are dropped; a word broken at a line end is rejoined."""
    body = []
    for block in re.split(r"\n[ \t\f\v]*\n", str(text or "").replace("\r\n", "\n").replace("\r", "\n")):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        lines = [line for line in lines if not re.fullmatch(r"\d{1,4}|[ivxlc]{1,7}\.?", line)]
        if not lines:
            continue
        paragraph = lines[0]
        for line in lines[1:]:
            if re.search(r"[A-Za-zА-Яа-яЁё]-$", paragraph) and re.match(r"[a-zа-яё]", line):
                paragraph = paragraph[:-1] + line
            else:
                paragraph += " " + line
        paragraph = _clean(paragraph)
        if len(paragraph) <= 80 and SCAN_HEADING.fullmatch(paragraph) and (paragraph.isupper() or not re.fullmatch(r"[ivxlc]+\.?", paragraph)):
            body.append("<h3>" + html_tools.escape(paragraph) + "</h3>")
        else:
            body.append("<p>" + html_tools.escape(paragraph) + "</p>")
    return _chapters_from_html("<body>" + "".join(body) + "</body>")


def _ia_book(identifier):
    """A public Internet Archive scan: its OCR text (_djvu.txt), marked as a scan."""
    def make():
        item = _ia_item(identifier)
        if not item["public"]:
            raise SourceError("Эту книгу Internet Archive только выдаёт читателям: открытого текста нет.")
        text = _get(ARCHIVE + "/download/" + identifier + "/" + identifier + "_djvu.txt", accept="text/plain")
        if text.lstrip().startswith("<"):
            raise SourceError("Internet Archive не предоставил текст книги.")
        chapters = _chapters_from_scan(text)
        if not chapters:
            raise SourceError("Не удалось разобрать текст книги.")
        language = item["language"]
        return {"title": item["title"] or identifier, "authors": [item["creator"]] if item["creator"] else [],
                "language": language if language in WIKISOURCE else "und", "chapters": chapters, "scan": True}
    return _remember(("ia", identifier), 6 * 3600, make)


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
    if host == "standardebooks.org":
        match = re.fullmatch(r"/ebooks/([a-z0-9_/-]{3,400}?)/?", parts.path)
        if match and _standard_id(match[1]):
            return "standard-ebooks", match[1], selected
    if host == "archive.org":
        match = re.fullmatch(r"/details/([A-Za-z0-9][A-Za-z0-9._-]{0,99})/?", parts.path)
        if match:
            return "internet-archive", match[1], selected
    if host.removesuffix(".wikisource.org") in WIKISOURCE:
        match = re.fullmatch(r"/wiki/([^?#]{1,300})", unquote(parts.path))
        if match:
            page = match[1].replace(" ", "_")
            if ":" in page.split("/")[0] or "/" in page:
                raise SourceError("Открой страницу самого произведения в Викитеке.")
            return "wikisource-" + host[:2], page, selected
    return None


def _book_url(identity, book):
    if identity == "gutenberg":
        return GUTENBERG + "/ebooks/" + book
    if identity == "standard-ebooks":
        return STANDARD + "/ebooks/" + book
    if identity == "internet-archive":
        return ARCHIVE + "/details/" + book
    return f"https://{identity[-2:]}.wikisource.org/wiki/" + quote(book)


def _book(identity, book):
    if identity == "gutenberg":
        return _gutenberg_book(book)
    if identity == "standard-ebooks":
        return _standard_book(book)
    if identity == "internet-archive":
        return _ia_book(book)
    return _wikisource_book(identity[-2:], book)


def inspect(url):
    identity, book, _ = route(url) or (None, None, None)
    if not identity:
        raise SourceError("Эта ссылка не относится к библиотекам книг.")
    data = _book(identity, book)
    base = _book_url(identity, book)
    episodes = [{"number": i + 1, "season": 1, "title": c["title"] or "Глава " + str(i + 1), "translator": "",
                 "language": data["language"], "url": base + "?" + urlencode({"mv_chapter": i})} for i, c in enumerate(data["chapters"])]
    return {"provider": identity, "providerName": dict(SOURCES)[identity], "kind": "book", "title": data["title"],
            "aliases": [data["title"]], "authors": data.get("authors", []), "url": base, "language": data["language"],
            "episodes": episodes, "seasons": [{"number": 1, "name": "Книга"}], **({"scan": True} if data.get("scan") else {})}


def chapter(url):
    identity, book, selected = route(url) or (None, None, None)
    if not identity:
        raise SourceError("Эта ссылка не относится к библиотекам книг.")
    if selected == "":
        raise SourceError("Выбери конкретную главу.")
    data = _book(identity, book)
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
