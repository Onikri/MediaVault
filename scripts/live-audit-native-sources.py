"""Live audit of every direct (native) manga source profile, the way the reader uses it.

For each profile the audit picks titles that really exist on that site (its
popular list, then its latest updates, then a short search), opens a title's
card and chapter list, opens up to five different chapters (first, last,
middle, quarters) and fetches their images exactly like the reader and CBZ
export do, checking the first bytes and the size. A failure is classified as
the site's (dead, no DNS, empty catalogue, paid-only), a block (Cloudflare,
DDoS-Guard, geo block, captcha, rate limit), the network route's, or ours
(parser/adapter error, rejected route, hang). Only the project's own transport
(Byparr, the Japan route) is used; nothing is bypassed.

Commands:
  run     audit inside the server environment (an importer image), JSONL out, resumable
  launch  pack this checkout's server code and start `run` in a separate,
          CPU-limited container on the VM (never inside the live importer)
  status  show progress of the VM run
  fetch   copy the VM results back
  report  summarise a JSONL into Markdown + JSON
"""

import argparse
from collections import Counter, defaultdict, deque
from io import BytesIO
import json
import os
from pathlib import Path
import queue as queue_module
import re
import socket
import subprocess
import sys
import time
import traceback
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
REMOTE = '/srv/mediavault/tmp/native-audit'
CONTAINER = 'mediavault-native-audit'
MAX_CANDIDATES = 6
PER_LISTING = 2         # candidates taken from one listing before trying the next
MAX_CHAPTERS = 5
MAX_ATTEMPTS = 9        # chapters tried per title to find MAX_CHAPTERS open ones
HARD_LIMIT = 300        # seconds a profile may take before its worker is killed
SOFT_BUDGET = 170       # seconds after which no new candidate/chapter is started
SHORT_QUERIES = {
    'ru': ('а', 'и'), 'uk': ('а', 'і'), 'ja': ('の', 'a'), 'ko': ('그', 'a'), 'zh': ('的', 'a'),
    'zh-hans': ('的', 'a'), 'zh-hant': ('的', 'a'), 'ar': ('ال', 'a'), 'th': ('ก', 'a'),
}
PARKED = re.compile(r'domain (?:name )?(?:is )?for sale|buy this domain|parked (?:free|domain)|sedoparking|'
                    r'this domain (?:has expired|is parked)|hugedomains', re.I)
CAPTCHA = re.compile(r'g-recaptcha|h-captcha|hcaptcha\.com|cf-turnstile|captcha', re.I)
DDOS_GUARD = re.compile(r'ddos-guard', re.I)
# Errors that a second candidate on the same site cannot change.
SITE_WIDE = {'dns', 'timeout', 'challenge', 'geo_blocked', 'rate_limited', 'route_unavailable', 'access_denied',
             'tls_error', 'connect_error', 'http_5xx', 'hang'}
OURS = {'parser_error', 'adapter_crash', 'route_rejected', 'identity_mismatch', 'hang', 'not_image', 'domain_moved',
        'redirect', 'http_404'}


def emit(handle, row):
    handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    handle.flush()


# ----------------------------------------------------------------- profiles

def all_profiles():
    import manga_native_registry
    import manga_native_sources as native

    profiles = dict(manga_native_registry.profiles())
    for sid, adapter in native.ADAPTERS.items():
        profiles.setdefault(sid, adapter)
    return profiles, set(native.ADAPTERS)


def host_of(adapter):
    return (urlsplit(getattr(adapter, 'ROOT', '') or '').hostname or '?').removeprefix('www.')


# ----------------------------------------------------------------- errors

def classify(error):
    """(kind, detail) for an adapter failure."""
    from source_parser import (SourceAccessError, SourceAuthError, SourceChallengeError, SourceError,
                               SourcePaidError, SourceParserError, SourceRateLimitError, SourceRedirectError,
                               SourceRegionError, SourceRouteError, SourceTemporaryError, source_status)

    text = str(error)[:200]
    inner = error.__context__
    if (type(error) is SourceError and isinstance(inner, SourceError) and type(inner) is not SourceError
            and not re.search(r'HTTP \d{3}', text)):
        # A generic wrapper ("temporarily unavailable") over a specific cause.
        kind, detail = classify(inner)
        return kind, f'{text} <- {detail}'[:240]
    if isinstance(error, TimeoutError):
        return 'timeout', text
    import requests
    if isinstance(error, requests.RequestException):
        # A broken or stalled transfer, not an adapter bug.
        return ('timeout' if isinstance(error, requests.Timeout) else 'connect_error'), f'{type(error).__name__}: {text}'[:200]
    if isinstance(error, SourceRateLimitError):
        return 'rate_limited', f'retry {error.retry_after}s'
    if isinstance(error, SourceChallengeError):
        return 'challenge', f'solver={getattr(error, "solver", "?")}: {text}'
    if isinstance(error, SourceRegionError):
        return 'geo_blocked', text
    if isinstance(error, SourcePaidError):
        return 'paid_only', text
    if isinstance(error, SourceAuthError):
        return 'auth_required', text
    if isinstance(error, SourceRouteError):
        return 'route_unavailable', text
    if isinstance(error, SourceParserError):
        return 'parser_error', text
    if isinstance(error, SourceRedirectError):
        return 'redirect', text
    if isinstance(error, SourceTemporaryError):
        status = re.search(r'HTTP (\d{3})', text)
        if status:
            return 'http_5xx', text
        if 'оборвалось' in text:
            return 'connect_error', text
        return 'timeout', text
    if isinstance(error, SourceAccessError):
        # Per-chapter closures (paid/rental/members-only chapters) are not site blocks.
        if re.search(r'только часть|платн|подписк|premium|покуп|закрыта у|на условиях|ограничил[аи]? чтение|'
                     r'ограничивает доступ к (?:этому )?(?:выпуску|главе)|не передал открытые|не предоставил открытую|требует доступ на стороне|'
                     r'не открыл главу|не открыл страницы', text, re.I):
            return 'paid_only', text
        if re.search(r'на языке|другом языке', text, re.I):
            return 'no_chapters', text
        return 'access_denied', text
    if isinstance(error, SourceError):
        if source_status(error) == 'parser_error':
            return 'parser_error', text
        if 'Не удалось найти сервер' in text:
            return 'dns', text
        status = re.search(r'HTTP (\d{3})', text)
        if status:
            code = int(status[1])
            if code == 404 or code == 410:
                return 'http_404', text
            if code >= 500:
                return 'http_5xx', text
            return 'http_4xx', text
        if re.search(r'Некорректн\w* (?:маршрут|запрос|форм|ссылк|адрес|публичн|параметр)|не относится к поддерживаемой|'
                     r'не входит в список|перенаправил', text):
            return 'route_rejected', text
        if re.search(r'заглушк|не найдены изображения|не предоставил изображение|повреждённое изображение', text):
            return 'not_image', text
        if re.search(r'платн|подписк|покуп', text, re.I):
            return 'paid_only', text
        if re.search(r'вход|авториз|логин', text, re.I):
            return 'auth_required', text
        return 'source_error', text
    frame = traceback.extract_tb(error.__traceback__)[-1:] if error.__traceback__ else []
    where = f' at {Path(frame[0].filename).name}:{frame[0].lineno}' if frame else ''
    return 'adapter_crash', f'{type(error).__name__}: {text}{where}'


def diagnose(root, japan_proxy=None):
    """One plain GET of the site's home page: is it alive, blocked or moved?"""
    import requests
    from source_parser import BLOCKED, USER_AGENT

    host = urlsplit(root).hostname or ''
    found = {'host': host}
    try:
        socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        found['dns'] = True
    except OSError:
        found['dns'] = False
        if not japan_proxy:
            return found
    proxies = {'https': japan_proxy, 'http': japan_proxy} if japan_proxy else None
    try:
        with requests.get(root, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xhtml+xml'},
                          timeout=(6, 12), allow_redirects=True, stream=True, proxies=proxies) as response:
            body = response.raw.read(300_000, decode_content=True) or b''
            found.update(http=response.status_code, final=(urlsplit(response.url).hostname or '').removeprefix('www.'),
                         server=(response.headers.get('Server') or '')[:30])
            text = body.decode('utf-8', 'ignore')
            headers = ' '.join(f'{k}: {v}' for k, v in response.headers.items())
            title = re.search(r'<title[^>]*>(.*?)</title>', text, re.I | re.S)
            found['title'] = re.sub(r'\s+', ' ', title[1]).strip()[:80] if title else ''
            marks = []
            if 'cf-ray' in headers.lower() or 'cloudflare' in found['server'].lower():
                marks.append('cloudflare')
            if BLOCKED.search(text) or response.headers.get('cf-mitigated') == 'challenge':
                marks.append('challenge')
            if DDOS_GUARD.search(found['server']) or DDOS_GUARD.search(text[:20000]):
                marks.append('ddos-guard')
            if CAPTCHA.search(text[:60000]):
                marks.append('captcha')
            if PARKED.search(text[:60000]):
                marks.append('parked')
            if len(body) < 512:
                marks.append('tiny')
            found['marks'] = marks
    except requests.exceptions.SSLError:
        found['http'] = 'tls_error'
    except requests.exceptions.Timeout:
        found['http'] = 'timeout'
    except requests.exceptions.ConnectionError:
        found['http'] = 'connect_error'
    except Exception as error:  # diagnostics must never fail the audit
        found['http'] = type(error).__name__
    return found


# ----------------------------------------------------------------- one profile

class Budget(Exception):
    pass


def audit_profile(adapter, sid, active, hint=None, light=False):
    from source_parser import PublicHttp
    from source_transport import solver_budget

    started = time.monotonic()
    extra = solver_budget(sid, 0)
    record = {
        'source_id': sid, 'name': getattr(adapter, 'NAME', '?'), 'lang': getattr(adapter, 'LANGUAGE', '?'),
        'nsfw': bool(getattr(adapter, 'IS_NSFW', False)), 'root': getattr(adapter, 'ROOT', ''),
        'host': host_of(adapter), 'active': active, 'module': getattr(adapter, '__module__', '?'),
        'light': light, 'errors': [], 'candidates': [], 'chapters': [],
    }
    http = PublicHttp(timeout=(5, 15), deadline=time.monotonic() + 30, source=sid, operation='catalogue')

    def call(operation, seconds, function):
        http.operation = operation
        http.deadline = time.monotonic() + seconds + extra
        return function()

    def failed(step, error):
        kind, detail = classify(error)
        record['errors'].append({'step': step, 'kind': kind, 'detail': detail})
        return kind

    def over_budget():
        return time.monotonic() - started > SOFT_BUDGET

    def valid_row(row):
        try:
            target = adapter.site_link(row.get('url'))
        except Exception:
            target = None
        return str(row.get('sourceId', sid)) == sid and row.get('title') and target

    def listings():
        """Titles that really exist on this site, lazily: a couple from each listing
        (popular, latest, the language-scoped index, short searches) so one odd
        list (titles without chapters in this language) cannot sink the profile."""
        if hint:
            yield {'url': hint['url'], 'id': hint.get('id'), 'title': hint.get('title', ''), 'from': 'hint'}
        plans = [('popular', {'sort': 'popular'}), ('updated', {'sort': 'updated'}), ('latest', {'sort': 'latest'}),
                 ('index', {'sort': 'index'})]
        plans += [('q:' + query, {'query': query})
                  for query in SHORT_QUERIES.get(str(record['lang']).lower(), ('a', 'the'))]
        for label, options in plans:
            try:
                rows, _ = call('search' if 'query' in options else 'catalogue', 25,
                               lambda: adapter.catalogue(http, 1, **options))
            except TypeError as error:
                if label != 'popular':
                    continue
                try:
                    rows, _ = call('catalogue', 25, lambda: adapter.catalogue(http))
                except Exception as error2:
                    failed('catalogue:' + label, error2)
                    continue
            except Exception as error:
                failed('catalogue:' + label, error)
                if record['errors'][-1]['kind'] in SITE_WIDE - {'hang'}:
                    return
                continue
            rows = list(rows or [])
            record.setdefault('catalogue_rows', {})[label] = len(rows)
            bad = [row for row in rows if not valid_row(row)]
            if bad and label in {'popular', 'updated'}:
                record['errors'].append({'step': 'catalogue:' + label, 'kind': 'identity_mismatch',
                                         'detail': f'{len(bad)}/{len(rows)} rows without title/link/source'})
            good = [row for row in rows if valid_row(row)]
            # Prefer reasonably named titles; keep the site's order otherwise.
            good.sort(key=lambda row: not (2 <= len(row['title']) <= 120))
            taken = 0
            for row in good:
                key = row.get('id') or row.get('url')
                if key in offered:
                    continue
                offered.add(key)
                yield {**row, 'from': label}
                taken += 1
                if taken == PER_LISTING:
                    break

    def fetch_image(page, target):
        from manga_download import image_extension
        from manga_page_media import fetch_page, page_reference
        from suwayomi_bridge import page_image, parse_reference

        custom = getattr(adapter, 'page_headers', None)
        headers = custom(target) if custom else {'Referer': target}
        if isinstance(page, dict):
            page = page.get('url') or page.get('src') or ''
        if parse_reference(page):
            raw = page_image(page)[0]
        elif reference := page_reference(page):
            raw = fetch_page(http, reference, headers)[0]
        else:
            response, _ = http._open(page, headers=headers)
            try:
                raw = bytearray()
                for block in response.iter_content(65536):
                    raw.extend(block)
                    if len(raw) > 30 * 1024 * 1024:
                        break
            finally:
                response.close()
        raw = bytes(raw)
        return image_extension(raw[:32]), len(raw), raw[:8].hex()

    def open_chapter(entry, both_ends):
        result = {'title': str(entry.get('title') or entry.get('name') or '')[:60]}
        t0 = time.monotonic()
        try:
            chapter = call('pages', 30, lambda: adapter.inspect(entry['url'], http))
            pages = chapter.get('pages') or []
            result['pages'] = len(pages)
            if not pages:
                text = chapter.get('text') or chapter.get('html') or chapter.get('content')
                if isinstance(text, str) and len(text.strip()) > 200:
                    result.update(ok=True, text_chars=len(text))
                    return result
                result.update(ok=False, kind='no_pages', keys=sorted(chapter)[:12])
                return result
            target = chapter.get('url') or entry['url']
            picks = [0, len(pages) - 1] if both_ends and len(pages) > 1 else [0]
            images = []
            for index in picks:
                ext, size, magic = call('images', 30, lambda: fetch_image(pages[index], target))
                images.append({'i': index, 'ext': ext, 'bytes': size, **({} if ext else {'magic': magic})})
                if not ext:
                    result.update(ok=False, kind='not_image', images=images)
                    return result
                if size < 1024:
                    result.update(ok=False, kind='tiny_image', images=images)
                    return result
            result.update(ok=True, images=images)
            return result
        except Exception as error:
            kind, detail = classify(error)
            result.update(ok=False, kind=kind, detail=detail)
            return result
        finally:
            result['ms'] = round((time.monotonic() - t0) * 1000)

    def pick_chapters(episodes):
        open_ones = [entry for entry in episodes if not entry.get('locked') and entry.get('url')]
        count = len(open_ones)
        limit = 4 if light else MAX_ATTEMPTS
        # First, last, middle and quarters, then the neighbours of both ends
        # (publishers often keep the first and the newest chapters free).
        order = [0, count - 1, count // 2, count // 4, (3 * count) // 4, 1, count - 2, 2, count - 3, 3]
        seen, chosen = set(), []
        for index in order:
            if 0 <= index < count and index not in seen:
                seen.add(index)
                chosen.append(open_ones[index])
            if len(chosen) == limit:
                break
        return chosen

    working = None
    offered = set()
    try:
        tried = 0
        for row in listings():
            if tried >= MAX_CANDIDATES or over_budget():
                break
            tried += 1
            candidate = {'title': str(row.get('title'))[:80], 'from': row['from'], 'url': row.get('url')}
            record['candidates'].append(candidate)
            t0 = time.monotonic()
            try:
                detail = call('chapters', 30, lambda: adapter.inspect(row['url'], http))
            except Exception as error:
                candidate['error'] = failed('detail', error)
                candidate['ms'] = round((time.monotonic() - t0) * 1000)
                if candidate['error'] in SITE_WIDE:
                    break
                continue
            candidate['ms'] = round((time.monotonic() - t0) * 1000)
            if str(detail.get('sourceId', sid)) != sid:
                candidate['error'] = 'identity_mismatch'
                record['errors'].append({'step': 'detail', 'kind': 'identity_mismatch',
                                         'detail': f'sourceId {detail.get("sourceId")}'})
                continue
            episodes = list(detail.get('episodes') or [])
            if not episodes and detail.get('pages'):
                # A single gallery/oneshot: the card itself carries the pages.
                episodes = [{'url': row['url'], 'title': 'gallery'}]
            candidate['chapters'] = len(episodes)
            candidate['locked'] = sum(1 for entry in episodes if entry.get('locked'))
            candidate['truncated'] = bool(detail.get('truncated'))
            if not episodes:
                candidate['error'] = 'no_chapters'
                continue
            chosen = pick_chapters(episodes)
            if not chosen:
                candidate['error'] = 'paid_only'
                continue
            opened = []
            wanted = 2 if light else MAX_CHAPTERS
            for number, entry in enumerate(chosen):
                if over_budget() and opened or sum(1 for r in opened if r['ok']) >= wanted:
                    break
                result = open_chapter(entry, both_ends=not any(r['ok'] for r in opened))
                opened.append(result)
                if not result['ok'] and result.get('kind') in SITE_WIDE and not any(r['ok'] for r in opened):
                    break
            candidate['opened'] = sum(1 for result in opened if result['ok'])
            record['chapters'] = opened
            if candidate['opened']:
                working = row
                record['working'] = {'url': row.get('url'), 'id': row.get('id'), 'title': str(row.get('title'))[:120]}
                break
            kinds = {result.get('kind') for result in opened}
            candidate['error'] = 'chapters_failed:' + ','.join(sorted(k for k in kinds if k))
            if kinds & SITE_WIDE:
                break
        record['candidates_tried'] = tried
        if working is not None and not light:
            try:
                title = str(working.get('title'))[:80]
                plain = re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', title)).strip()
                for query in dict.fromkeys([title, plain]):
                    found, _ = call('search', 25, lambda: adapter.catalogue(http, 1, query=query))
                    record['search'] = any((row.get('id') and row.get('id') == working.get('id'))
                                           or row.get('url') == working.get('url') for row in found or [])
                    record['search_rows'] = len(found or [])
                    if record['search'] or not plain:
                        break
            except Exception as error:
                record['search'] = 'error:' + classify(error)[0]
                record['search_detail'] = classify(error)[1]
    finally:
        try:
            http.close()
        except Exception:
            pass
    verdict(record)
    if record['owner'] in {'site', 'blocked', 'unknown', 'ours', 'ours?'}:
        record['diag'] = diagnose(record['root'], japan_proxy_for(record['host']))
        verdict(record)
    record['seconds'] = round(time.monotonic() - started, 1)
    return record


def japan_proxy_for(host):
    try:
        config = json.loads((Path(os.getenv('DATA_DIR', '/data')) / 'source-transport.json').read_text())
        japan = config.get('japan') or {}
        hosts = {str(h).removeprefix('www.') for h in japan.get('hosts') or []}
        if host in hosts or any(host.endswith('.' + h) for h in hosts):
            return japan.get('httpProxy')
    except (OSError, ValueError, AttributeError):
        pass
    return None


def verdict(record):
    """status = what happened; owner = whose problem it is (ok/site/blocked/route/ours/unknown)."""
    chapters = record.get('chapters') or []
    opened = sum(1 for result in chapters if result.get('ok'))
    record['opened'] = opened
    record['attempted'] = len(chapters)
    if opened:
        bad = [result for result in chapters if not result.get('ok')]
        # Paid or closed chapters are skipped by readers too; they are not failures.
        bad = [result for result in bad if result.get('kind') != 'paid_only']
        record['status'] = 'ok' if not bad else 'partial'
        record['owner'] = 'ok'
        if bad:
            record['reason'] = ','.join(sorted({result.get('kind', '?') for result in bad}))
            if any(result.get('kind') in OURS | {'no_pages', 'tiny_image', 'source_error', 'adapter_crash'}
                   for result in bad):
                record['owner'] = 'ours?'
        return
    kinds = [error['kind'] for error in record['errors']]
    for result in chapters:
        if result.get('kind'):
            kinds.append(result['kind'])
    for candidate in record.get('candidates', []):
        error = candidate.get('error') or ''
        if error in {'no_chapters', 'paid_only'}:
            kinds.append(error)
    diag = record.get('diag') or {}
    marks = set(diag.get('marks') or [])
    # Most specific first: our bugs, then blocks, then the site itself.
    priority = ['hang', 'adapter_crash', 'parser_error', 'route_rejected', 'identity_mismatch', 'not_image',
                'tiny_image', 'no_pages', 'redirect', 'challenge', 'geo_blocked', 'rate_limited', 'access_denied',
                'auth_required', 'route_unavailable', 'dns', 'tls_error', 'connect_error', 'timeout', 'http_5xx',
                'http_404', 'http_4xx', 'source_error', 'paid_only', 'no_chapters']
    status = next((kind for kind in priority if kind in kinds), None)
    if status is None:
        status = 'empty_catalogue' if not record.get('candidates') else 'unknown'
    owner = {
        'hang': 'ours', 'adapter_crash': 'ours', 'parser_error': 'ours', 'route_rejected': 'ours',
        'identity_mismatch': 'ours', 'not_image': 'ours', 'tiny_image': 'ours', 'no_pages': 'ours',
        'redirect': 'ours?', 'challenge': 'blocked', 'geo_blocked': 'blocked', 'rate_limited': 'blocked',
        'access_denied': 'blocked', 'auth_required': 'site', 'route_unavailable': 'route', 'dns': 'site',
        'tls_error': 'site', 'connect_error': 'site', 'timeout': 'site', 'http_5xx': 'site', 'http_404': 'ours?',
        'http_4xx': 'site', 'source_error': 'unknown', 'paid_only': 'site', 'no_chapters': 'site',
        'empty_catalogue': 'site', 'unknown': 'unknown',
    }[status]
    if diag:
        alive = isinstance(diag.get('http'), int) and diag['http'] < 400 and not marks & {'challenge', 'parked'}
        moved = alive and diag.get('final') and diag['final'] != record['host'] and not diag['final'].endswith('.' + record['host'])
        if diag.get('dns') is False:
            status, owner = 'dns', 'site'
        elif 'parked' in marks:
            status, owner = 'parked_domain', 'site'
        elif moved and status in {'redirect', 'http_404', 'timeout', 'connect_error', 'dns', 'empty_catalogue',
                                  'source_error', 'access_denied', 'unknown', 'parser_error'}:
            status, owner = 'domain_moved', 'ours'
        elif marks & {'ddos-guard'} and status in {'access_denied', 'challenge', 'timeout', 'http_4xx', 'source_error'}:
            status, owner = 'ddos_guard', 'blocked'
        elif 'challenge' in marks and status in {'access_denied', 'timeout', 'http_4xx', 'source_error', 'unknown', 'empty_catalogue'}:
            status, owner = 'challenge', 'blocked'
        elif 'captcha' in marks and status in {'access_denied', 'source_error', 'http_4xx'}:
            status, owner = 'captcha', 'blocked'
        elif status in {'timeout', 'connect_error', 'tls_error'} and not alive:
            owner = 'site'
        elif status in {'timeout', 'connect_error'} and alive:
            # The home page answers, but the adapter's own requests do not.
            owner = 'unknown'
        elif status == 'http_404' and alive:
            owner = 'ours?'
        elif status == 'source_error':
            owner = 'site' if not alive else 'unknown'
        elif status == 'redirect':
            owner = 'ours?' if alive else 'site'
        elif status in {'http_5xx', 'empty_catalogue'} and not alive:
            owner = 'site'
        elif status in {'empty_catalogue', 'no_chapters'} and alive and not marks & {'captcha', 'ddos-guard', 'tiny'}:
            # The site answers normally, yet our parser found no titles/chapters.
            owner = 'ours?'
    rows = record.get('catalogue_rows') or {}
    if status == 'no_chapters' and not any(count for label, count in rows.items() if label == 'index' or label.startswith('q:')):
        # Global lists only: the site has nothing in this profile's language.
        status, owner = 'empty_language', 'site'
    record['status'] = status
    record['owner'] = owner
    detail = next((error['detail'] for error in record['errors'] if error['kind'] == status), None)
    if detail is None:
        detail = next((result.get('detail') for result in chapters if result.get('kind') == status), None)
    record['reason'] = (detail or status)[:200]


# ----------------------------------------------------------------- runner

def worker(sids, hints, active, light_after, messages):
    sys.setrecursionlimit(5000)
    profiles, _ = all_profiles()
    for position, sid in enumerate(sids):
        messages.put(('start', os.getpid(), sid, time.time()))
        try:
            record = audit_profile(profiles[sid], sid, sid in active, hints.get(sid), light=position >= light_after)
        except Exception as error:
            record = {'source_id': sid, 'status': 'audit_crash', 'owner': 'ours', 'reason': repr(error)[:200],
                      'name': getattr(profiles[sid], 'NAME', '?'), 'host': host_of(profiles[sid])}
        messages.put(('done', os.getpid(), sid, record))
        if record.get('status') == 'rate_limited':
            time.sleep(45)
        else:
            time.sleep(1.5)


def run(args):
    import multiprocessing

    sys.path.insert(0, str(ROOT / 'server'))
    profiles, active = all_profiles()
    out = Path(args.out)
    done = {}
    if out.exists():
        for line in out.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('source_id'):
                done[row['source_id']] = row
    hints = {}
    for path in args.hints:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('working'):
                hints[row['source_id']] = row['working']
    selected = [sid for sid in sorted(profiles) if not args.source or sid in args.source]
    if args.retry:
        retry = set(args.retry)
        selected = [sid for sid in selected if sid not in done or done[sid].get('status') in retry
                    or done[sid].get('owner') in retry]
        for sid in selected:
            if sid in done and done[sid].get('working'):
                hints.setdefault(sid, done[sid]['working'])
    else:
        selected = [sid for sid in selected if sid not in done]
    if args.limit:
        selected = selected[:args.limit]
    groups = defaultdict(list)
    for sid in selected:
        groups[host_of(profiles[sid])].append(sid)
    handle = out.open('a', encoding='utf-8')
    started = time.monotonic()
    print(json.dumps({'event': 'started', 'profiles': len(profiles), 'selected': len(selected), 'hosts': len(groups),
                      'workers': args.workers}), flush=True)
    if args.workers == 0:
        # Inline mode for local checks (no fork on Windows).
        for sids in groups.values():
            for position, sid in enumerate(sids):
                record = audit_profile(profiles[sid], sid, sid in active, hints.get(sid), light=position >= args.light_after)
                emit(handle, record)
                print(json.dumps({k: record.get(k) for k in ('name', 'status', 'owner', 'opened', 'attempted', 'reason', 'seconds')},
                                 ensure_ascii=False), flush=True)
        handle.close()
        return
    # Big host groups first so they do not end up as a long tail.
    pending = deque((sids, args.light_after) for sids in sorted(groups.values(), key=len, reverse=True))
    context = multiprocessing.get_context('fork')
    messages = context.Queue()
    running = {}  # pid -> {'proc', 'sids', 'current', 'since', 'light_after'}
    state = {'finished': 0}

    def spawn(sids, light_after):
        proc = context.Process(target=worker, args=(sids, hints, active, light_after, messages), daemon=True)
        proc.start()
        running[proc.pid] = {'proc': proc, 'sids': list(sids), 'current': None, 'since': None,
                             'light_after': light_after}

    def handle_message(message):
        kind, pid, sid, payload = message
        entry = running.get(pid)
        if kind == 'start' and entry:
            entry['current'], entry['since'] = sid, payload
        elif kind == 'done':
            emit(handle, payload)
            state['finished'] += 1
            if entry and sid in entry['sids']:
                entry['sids'].remove(sid)
                entry['light_after'] -= 1
                entry['current'] = None
            if state['finished'] % 10 == 0:
                print(json.dumps({'event': 'progress', 'done': state['finished'], 'of': len(selected),
                                  'minutes': round((time.monotonic() - started) / 60, 1)}), flush=True)

    while pending or running:
        while pending and len(running) < args.workers:
            spawn(*pending.popleft())
        try:
            handle_message(messages.get(timeout=3))
        except queue_module.Empty:
            pass
        now = time.time()
        for pid, entry in list(running.items()):
            proc = entry['proc']
            hung = bool(entry['current']) and now - entry['since'] > HARD_LIMIT
            if not hung and proc.is_alive():
                continue
            if hung:
                proc.kill()
            proc.join(5)
            # Messages the worker sent just before it exited.
            while True:
                try:
                    handle_message(messages.get(timeout=0.5))
                except queue_module.Empty:
                    break
            if not entry['sids']:
                running.pop(pid)
                continue
            current = entry['current']
            if current and current in entry['sids']:
                adapter = profiles[current]
                emit(handle, {'source_id': current, 'name': getattr(adapter, 'NAME', '?'),
                              'lang': getattr(adapter, 'LANGUAGE', '?'), 'host': host_of(adapter),
                              'root': getattr(adapter, 'ROOT', ''), 'active': current in active,
                              'module': getattr(adapter, '__module__', '?'),
                              'status': 'hang' if hung else 'worker_died', 'owner': 'ours', 'errors': [],
                              'reason': f'no result after {HARD_LIMIT}s' if hung else f'exit {proc.exitcode}',
                              'seconds': round(now - (entry['since'] or now), 1)})
                state['finished'] += 1
                entry['sids'].remove(current)
            running.pop(pid)
            if entry['sids']:
                pending.appendleft((entry['sids'], entry['light_after'] - 1))
    handle.close()
    print(json.dumps({'event': 'finished', 'done': state['finished'],
                      'minutes': round((time.monotonic() - started) / 60, 1)}), flush=True)


# ----------------------------------------------------------------- Suwayomi reference

def suwayomi(args):
    """Same smart check through the installed Suwayomi extension, for comparison."""
    sys.path.insert(0, str(ROOT / 'server'))
    from suwayomi_bridge import Client, sources

    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock

    installed = {str(row['id']): row for row in sources()}
    path = Path(args.out)
    done = set(latest_rows([path])) if path.exists() else set()
    out = path.open('a', encoding='utf-8')
    lock = Lock()

    def write(row):
        with lock:
            emit(out, row)

    # Two at a time: with more parallel calls Suwayomi answers `network` in ~10 ms.
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda sid: one(sid, installed, write), [sid for sid in args.source if sid not in done]))


def one(sid, installed, emit_row):
    from suwayomi_bridge import Client

    if True:
        row = installed.get(sid)
        if row is None:
            emit_row({'source_id': sid, 'suwayomi': 'not_installed'})
            return
        started = time.monotonic()
        client = Client()
        result = {'source_id': sid, 'name': row.get('name')}
        try:
            mangas = []
            for kind in ('popular', 'latest'):
                try:
                    data = client.get(f'/source/{sid}/{kind}/1', timeout=25)
                    mangas += [m for m in data.get('mangaList', []) if type(m.get('id')) is int]
                except Exception as error:
                    result['catalogue_error'] = type(error).__name__ + ':' + str(getattr(error, 'code', ''))
                if mangas:
                    break
            result['rows'] = len(mangas)
            opened = 0
            for manga in mangas[:3]:
                try:
                    chapters = client.get(f'/manga/{manga["id"]}/chapters', {'onlineFetch': 'true'}, timeout=30)
                except Exception as error:
                    result['chapters_error'] = type(error).__name__ + ':' + str(getattr(error, 'code', ''))
                    continue
                indexes = sorted({c['index'] for c in chapters if type(c.get('index')) is int and c['index'] >= 1})
                if not indexes:
                    continue
                picks = list(dict.fromkeys([indexes[0], indexes[-1], indexes[len(indexes) // 2]]))
                for index in picks:
                    try:
                        count = client.get(f'/manga/{manga["id"]}/chapter/{index}', timeout=30).get('pageCount')
                        raw, _ = client.get(f'/manga/{manga["id"]}/chapter/{index}/page/0', {'updateProgress': 'false'},
                                            timeout=30, image=True)
                        if count and len(raw) > 1024:
                            opened += 1
                    except Exception as error:
                        result['pages_error'] = type(error).__name__ + ':' + str(getattr(error, 'code', ''))
                result['title'] = manga.get('title')
                if opened:
                    break
            result['opened'] = opened
            result['suwayomi'] = 'ok' if opened else 'failed'
        finally:
            client.close()
            result['seconds'] = round(time.monotonic() - started, 1)
        emit_row(result)
        time.sleep(1)


# ----------------------------------------------------------------- VM driver

def ssh(host, script, payload=None, check=True):
    process = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', host, 'sudo -n bash -s'],
                             input=(script.encode() if payload is None else script.encode()), capture_output=True)
    if check and process.returncode:
        sys.stderr.write(process.stderr.decode(errors='replace'))
        raise SystemExit(process.returncode)
    return process.stdout.decode(errors='replace')


def package():
    data = BytesIO()
    server = ROOT / 'server'
    with ZipFile(data, 'w', ZIP_DEFLATED) as archive:
        archive.write(Path(__file__), 'scripts/live-audit-native-sources.py')
        for path in sorted(server.glob('*.py')) + sorted(server.glob('*.json')):
            archive.write(path, path.relative_to(ROOT).as_posix())
    return data.getvalue()


def launch(args):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.@-]*', args.ssh):
        raise SystemExit('Invalid SSH host')
    blob = package()
    upload = subprocess.run(['ssh', '-o', 'BatchMode=yes', args.ssh,
                             f'sudo -n mkdir -p {REMOTE} && sudo -n tee {REMOTE}/code-{args.name}.zip >/dev/null'],
                            input=blob)
    if upload.returncode:
        raise SystemExit('upload failed')
    run_args = ['run', '--out', f'/audit/{args.name}.jsonl', '--workers', str(args.workers),
                '--light-after', str(args.light_after)]
    for sid in args.source:
        run_args += ['--source', sid]
    for status in args.retry:
        run_args += ['--retry', status]
    for hint in args.hints:
        run_args += ['--hints', '/audit/' + Path(hint).name]
    if args.limit:
        run_args += ['--limit', str(args.limit)]
    command = ' '.join(f"'{value}'" for value in run_args)
    mode = 'suwayomi' if args.suwayomi else 'run'
    if args.suwayomi:
        command = ' '.join(["'suwayomi'", '--out', f"'/audit/{args.name}.jsonl'"] +
                           [f"--source '{sid}'" for sid in args.source])
    script = f"""set -euo pipefail
D={REMOTE}
DATA=/opt/mediavault/media-vault/deploy/oracle/data
mkdir -p $D/data
# Each run gets its own code copy, so a new launch never changes a running one.
C=$D/code-{args.name}
rm -rf $C && mkdir -p $C
python3 -c "import zipfile,sys; zipfile.ZipFile('$D/code-{args.name}.zip').extractall('$C')"
for f in source-transport.json manga-source-routes.json manga-source-transport.json manga-source-solver.json; do
  [ -f $DATA/$f ] && cp $DATA/$f $D/data/ || true
done
IMAGE=$(docker inspect oracle-importer-1 --format '{{{{.Config.Image}}}}')
ENVFILE=$D/data/env-{args.name}
docker inspect oracle-importer-1 --format '{{{{range .Config.Env}}}}{{{{println .}}}}{{{{end}}}}' \
  | grep -E '^(GLOBALCOMIX_CLIENT_ID|PUBLIC_URL|SUWAYOMI_URL|CHROMIUM_PATH|BAKKIN_SELF_HOSTED_URL|MONOCHROME_CUSTOM_API_URL)=' > $ENVFILE || true
if [ "{mode}" = suwayomi ]; then
  AUTH=$(docker inspect oracle-importer-1 --format '{{{{range .Config.Env}}}}{{{{println .}}}}{{{{end}}}}' | sed -n 's/^SUWAYOMI_AUTH_FILE=//p')
  cp "$DATA/${{AUTH#/data/}}" $D/data/suw-auth.json && chmod 600 $D/data/suw-auth.json
  echo SUWAYOMI_AUTH_FILE=/audit/data/suw-auth.json >> $ENVFILE
fi
chmod 600 $ENVFILE
docker rm -f {CONTAINER}-{args.name} >/dev/null 2>&1 || true
docker run -d --name {CONTAINER}-{args.name} --cpus {args.cpus} --memory 4g --user 0 --network oracle_default \
  --env-file $ENVFILE -e DATA_DIR=/audit/data -e PYTHONPATH=/audit/code-{args.name}/server -e SUWAYOMI_CALLS_TAG=tool -e PYTHONDONTWRITEBYTECODE=1 \
  -v $D:/audit -w /audit/code-{args.name} --entrypoint python "$IMAGE" -B scripts/live-audit-native-sources.py {command}
echo started $IMAGE
"""
    print(ssh(args.ssh, script))


def status(args):
    print(ssh(args.ssh, f"""docker ps -a --filter name={CONTAINER}-{args.name} --format '{{{{.Status}}}}'
docker logs --tail 3 {CONTAINER}-{args.name} 2>&1 | tail -3
wc -l {REMOTE}/{args.name}.jsonl 2>/dev/null || true
uptime
""", check=False))


def fetch(args):
    target = Path(args.to)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = subprocess.run(['ssh', '-o', 'BatchMode=yes', args.ssh, f'sudo -n cat {REMOTE}/{args.name}.jsonl'],
                          capture_output=True, check=True).stdout
    target.write_bytes(data)
    print(f'{len(data.splitlines())} rows -> {target}')


# ----------------------------------------------------------------- report

def latest_rows(paths):
    rows = {}
    for path in paths:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('source_id'):
                rows[row['source_id']] = row
    return rows


OWNER_RU = {'ok': 'работает', 'site': 'сторона сайта', 'blocked': 'блокировка', 'route': 'маршрут/шлюз',
            'ours': 'наш код', 'ours?': 'вероятно наш код', 'unknown': 'не ясно'}


def report(args):
    """Recompute verdicts (classification may have improved since the run) and summarise."""
    rows = latest_rows(args.inputs)
    for row in rows.values():
        if row.get('errors') is not None and row.get('status') not in {'hang', 'worker_died', 'audit_crash'}:
            verdict(row)
    hosts = defaultdict(list)
    for row in rows.values():
        hosts[row.get('host')].append(row)
    for items in hosts.values():
        # One language of a multi-language site being empty is the site's catalogue,
        # not our parser, when other languages of the same site list titles.
        if any(any((r.get('catalogue_rows') or {}).values()) for r in items):
            for r in items:
                if r.get('status') == 'empty_catalogue':
                    r['status'], r['owner'], r['reason'] = 'empty_language', 'site', 'empty_language'
    owners = Counter(row.get('owner') for row in rows.values())
    statuses = Counter(row.get('status') for row in rows.values())
    host_owner = Counter()
    for items in hosts.values():
        best = 'ok' if any(r.get('owner') == 'ok' for r in items) else Counter(r.get('owner') for r in items).most_common(1)[0][0]
        host_owner[best] += 1
    summary = {'profiles': len(rows), 'hosts': len(hosts), 'owners': dict(owners), 'statuses': dict(statuses),
               'host_owners': dict(host_owner),
               'chapters_opened': sum(r.get('opened') or 0 for r in rows.values()),
               'chapters_attempted': sum(r.get('attempted') or 0 for r in rows.values())}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.json:
        slim = []
        for row in sorted(rows.values(), key=lambda r: (r.get('host') or '', r.get('lang') or '')):
            slim.append({key: row.get(key) for key in (
                'source_id', 'name', 'lang', 'host', 'active', 'nsfw', 'status', 'owner', 'reason', 'opened',
                'attempted', 'seconds', 'search', 'module')} | {
                'title': (row.get('working') or {}).get('title'),
                'diag': {k: v for k, v in (row.get('diag') or {}).items() if k in {'http', 'final', 'marks', 'dns'}} or None,
                'images': sum(len(c.get('images') or []) for c in row.get('chapters') or [] if c.get('ok')),
            })
        Path(args.json).write_text(json.dumps({'summary': summary, 'rows': slim}, ensure_ascii=False), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('run')
    p.add_argument('--out', required=True)
    p.add_argument('--workers', type=int, default=6)
    p.add_argument('--source', action='append', default=[])
    p.add_argument('--retry', action='append', default=[], help='Re-audit rows with this status or owner.')
    p.add_argument('--hints', action='append', default=[], help='Earlier JSONL whose working titles go first.')
    p.add_argument('--light-after', type=int, default=2, help='Profiles per host checked fully before 2-chapter mode.')
    p.add_argument('--limit', type=int, default=0)
    p = sub.add_parser('suwayomi')
    p.add_argument('--out', required=True)
    p.add_argument('--source', action='append', default=[])
    for name in ('launch', 'status', 'fetch'):
        p = sub.add_parser(name)
        p.add_argument('--ssh', required=True)
        p.add_argument('--name', default='audit')
        if name == 'launch':
            p.add_argument('--workers', type=int, default=6)
            p.add_argument('--cpus', default='2')
            p.add_argument('--source', action='append', default=[])
            p.add_argument('--retry', action='append', default=[])
            p.add_argument('--hints', action='append', default=[])
            p.add_argument('--light-after', type=int, default=2)
            p.add_argument('--limit', type=int, default=0)
            p.add_argument('--suwayomi', action='store_true')
        if name == 'fetch':
            p.add_argument('--to', required=True)
    p = sub.add_parser('report')
    p.add_argument('inputs', nargs='+')
    p.add_argument('--json')
    args = parser.parse_args()
    {'run': run, 'suwayomi': suwayomi, 'launch': launch, 'status': status, 'fetch': fetch, 'report': report}[args.command](args)


if __name__ == '__main__':
    main()
