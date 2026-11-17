"""Audit direct source profiles without changing source or index health."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]


def emit(row):
    print(json.dumps(row, ensure_ascii=True), flush=True)


def candidates():
    import manga_native_registry
    import manga_native_sources as native

    return dict(manga_native_registry.profiles()), native.ADAPTERS


def probe_archive():
    payload = BytesIO()
    server = ROOT / 'server'
    paths = [Path(__file__), *sorted(server.glob('*.py')), server / 'manga_native_activation.json']
    with ZipFile(payload, 'w', ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, path.relative_to(ROOT).as_posix())
    return payload.getvalue()


def audit(adapter, check_search, check_chapters, check_pages=False):
    from source_parser import PublicHttp, SourceAccessError, SourceError, SourceRateLimitError, SourceTemporaryError

    phase = 'catalogue'
    http = PublicHttp(timeout=(3, 6), deadline=time.monotonic() + 12)
    result = {}
    try:
        rows, more = adapter.catalogue(http)
        result.update(rows=len(rows), more=bool(more))
        if not rows:
            return {**result, 'status': 'empty', 'phase': phase}
        for row in rows:
            target = adapter.site_link(row.get('url'))
            if (str(row.get('sourceId')) != adapter.SOURCE_ID or not row.get('title') or not target
                    or not adapter.TITLE_PATH.fullmatch(urlsplit(target).path)):
                return {**result, 'status': 'identity_mismatch', 'phase': phase}
        result['catalogue'] = True
        sample = next((row for row in rows if 2 <= len(row['title']) <= 100), rows[0])
        if check_search:
            phase = 'search'
            http.deadline = time.monotonic() + 12
            found, _ = adapter.catalogue(http, query=sample['title'])
            result['search'] = any(row.get('id') == sample['id'] for row in found)
        if check_chapters:
            phase = 'chapters'
            http.deadline = time.monotonic() + 12
            detail = adapter.inspect(sample['url'], http)
            episodes = detail.get('episodes', [])
            result['chapter_count'] = len(episodes)
            result['chapters_truncated'] = bool(detail.get('truncated'))
            if detail.get('pages') or str(detail.get('sourceId')) != adapter.SOURCE_ID or detail.get('id') != sample['id']:
                return {**result, 'status': 'identity_mismatch', 'phase': phase}
            if not episodes:
                return {**result, 'status': 'empty', 'phase': phase}
            for entry in episodes:
                url = adapter.site_link(entry.get('url'))
                if not url or not adapter.CHAPTER_PATH.fullmatch(urlsplit(url).path):
                    return {**result, 'status': 'identity_mismatch', 'phase': phase}
            result['chapters'] = True
            if check_pages:
                phase = 'pages'
                http.deadline = time.monotonic() + 20
                chapter = adapter.inspect(episodes[0]['url'], http)
                pages = chapter.get('pages') or []
                result['page_count'] = len(pages)
                if not pages:
                    return {**result, 'status': 'empty', 'phase': phase}
                # Fetch the first image exactly as the reader and CBZ export do.
                from manga_download import image_extension
                from manga_page_media import fetch_page, page_reference
                from suwayomi_bridge import page_image, parse_reference

                first = pages[0]
                target = chapter.get('url') or episodes[0]['url']
                custom = getattr(adapter, 'page_headers', None)
                headers = custom(target) if custom else {'Referer': target}
                if parse_reference(first):
                    raw = page_image(first)[0]
                elif reference := page_reference(first):
                    raw = fetch_page(http, reference, headers)[0]
                else:
                    response, _ = http._open(first, headers=headers)
                    try:
                        raw = bytearray()
                        for block in response.iter_content(65536):
                            raw.extend(block)
                            if len(raw) > 30 * 1024 * 1024:
                                break
                    finally:
                        response.close()
                if not image_extension(bytes(raw[:32])):
                    return {**result, 'status': 'not_image', 'phase': phase}
                result['image_bytes'] = len(raw)
                result['pages'] = True
        if check_search and not result['search']:
            return {**result, 'status': 'search_mismatch', 'phase': 'search'}
        return {**result, 'status': 'passed', 'phase': phase}
    except SourceRateLimitError as error:
        return {**result, 'status': 'rate_limited', 'phase': phase, 'retry_after_seconds': error.retry_after}
    except SourceAccessError:
        return {**result, 'status': 'restricted', 'phase': phase}
    except SourceTemporaryError:
        return {**result, 'status': 'temporary_error', 'phase': phase}
    except SourceError as error:
        status = re.search(r'HTTP (\d{3})', str(error))
        return {**result, 'status': 'source_error', 'phase': phase, 'http': int(status[1]) if status else None}
    except Exception as error:
        return {**result, 'status': 'adapter_error', 'phase': phase, 'error_type': type(error).__name__}
    finally:
        http.close()


def probe_suwayomi(source, check_search, check_chapters, check_pages):
    from manga_solver import source_timeout
    from source_parser import SourceError
    from suwayomi_bridge import BridgeError, Client

    sid = str(source['id'])
    timeout = source_timeout(sid, 8)
    result, phase = {}, 'catalogue'
    client = Client()
    try:
        data = client.get(f'/source/{sid}/popular/1', timeout=timeout)
        rows = data.get('mangaList', [])
        result.update(rows=len(rows), more=bool(data.get('hasNextPage')))
        sample = next((row for row in rows if type(row.get('id')) is int and 2 <= len(row.get('title') or '') <= 100), None)
        if not sample:
            return {**result, 'status': 'empty', 'phase': phase}
        result['catalogue'] = True
        if check_search:
            phase = 'search'
            found = client.get(f'/source/{sid}/search', {'searchTerm': sample['title'], 'pageNum': 1}, timeout=timeout)
            result['search'] = any(row.get('id') == sample['id'] for row in found.get('mangaList', []))
        if check_chapters:
            phase = 'chapters'
            mid = sample['id']
            detail = client.get(f'/manga/{mid}', {'onlineFetch': 'true'}, timeout=timeout)
            detail_source = str(detail.get('sourceId') or (detail.get('source') or {}).get('id') or '')
            if detail_source and detail_source != sid:
                return {**result, 'status': 'identity_mismatch', 'phase': phase}
            chapters = client.get(f'/manga/{mid}/chapters', {'onlineFetch': 'true'}, timeout=timeout)
            result['chapter_count'] = len(chapters)
            chapter = next((row for row in reversed(chapters) if type(row.get('index')) is int and row['index'] >= 1), None)
            if chapter is None:
                return {**result, 'status': 'empty', 'phase': phase}
            result['chapters'] = True
            if check_pages:
                phase = 'pages'
                index = chapter['index']
                count = client.get(f'/manga/{mid}/chapter/{index}', timeout=max(timeout, 10)).get('pageCount')
                if type(count) is not int or count < 1:
                    return {**result, 'status': 'empty', 'phase': phase}
                raw, _ = client.get(f'/manga/{mid}/chapter/{index}/page/0', {'updateProgress': 'false'},
                                    timeout=max(timeout, 10), image=True)
                result.update(pages=True, page_count=count, image_bytes=len(raw))
        if check_search and not result['search']:
            return {**result, 'status': 'search_mismatch', 'phase': 'search'}
        return {**result, 'status': 'passed', 'phase': phase}
    except BridgeError as error:
        return {**result, 'status': error.code, 'phase': phase}
    except SourceError:
        return {**result, 'status': 'source_error', 'phase': phase}
    except (AttributeError, KeyError, TypeError, ValueError):
        return {**result, 'status': 'format', 'phase': phase}
    finally:
        client.close()


def probe_origin(adapters, enabled, check_search, check_chapters, check_pages=False, *, suwayomi=False):
    results = []
    rate_limited = False
    for adapter in adapters:
        started = time.monotonic()
        sid, name = (str(adapter['id']), adapter['name']) if suwayomi else (adapter.SOURCE_ID, adapter.NAME)
        probe = probe_suwayomi if suwayomi else audit
        result = {'status': 'deferred', 'phase': 'catalogue'} if rate_limited else probe(adapter, check_search, check_chapters, check_pages)
        rate_limited |= result['status'] in {'rate_limited', 'rate-limit'}
        results.append({'source_id': sid, 'name': name, 'enabled': sid in enabled,
                        'route': 'suwayomi' if suwayomi else 'direct', 'ms': round((time.monotonic()-started)*1000), **result})
    return results


def live(args):
    sys.path.insert(0, str(ROOT / 'server'))
    profiles, enabled = candidates()
    if args.suwayomi:
        from suwayomi_bridge import sources

        profiles = {str(row['id']): row for row in sources()}
    unknown = set(args.source) - profiles.keys()
    if unknown:
        raise SystemExit('No profile for this route: ' + ', '.join(sorted(unknown)))

    def identity(row):
        return (str(row['id']), row['name']) if args.suwayomi else (row.SOURCE_ID, row.NAME)

    def order(row):
        sid, name = identity(row)
        return sid in enabled, name.casefold(), sid

    ordered = sorted(profiles.values(), key=order)
    if args.inactive:
        ordered = [row for row in ordered if identity(row)[0] not in enabled]
    if args.source:
        selected = [row for row in ordered if identity(row)[0] in args.source]
    else:
        selected = ordered[args.offset:args.offset + args.batch_size]
    groups = defaultdict(list)
    for adapter in selected:
        base = adapter.get('baseUrl', '') if args.suwayomi else adapter.ROOT
        groups[urlsplit(base).hostname].append(adapter)
    started = time.monotonic()
    emit({'event': 'started', 'total_profiles': len(profiles), 'selected': len(selected), 'origins': len(groups),
          'route': 'suwayomi' if args.suwayomi else 'direct', 'workers': args.workers,
          'search': args.search, 'chapters': args.chapters, 'inactive_only': args.inactive})
    statuses = Counter()
    operations = Counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(probe_origin, group, enabled, args.search, args.chapters, args.pages, suwayomi=args.suwayomi)
                for group in groups.values()]
        for future in as_completed(jobs):
            for result in future.result():
                statuses[result['status']] += 1
                operations.update(key for key in ('catalogue', 'search', 'chapters', 'pages') if result.get(key))
                emit({'event': 'source', **result})
    emit({'event': 'summary', 'completed': sum(statuses.values()), 'catalogues_returned': operations['catalogue'],
          'searches_matched': operations['search'], 'chapter_lists_returned': operations['chapters'],
          'images_returned': operations['pages'],
          'statuses': dict(statuses), 'seconds': round(time.monotonic() - started, 2)})


def over_ssh(host, args):
    payload = probe_archive()
    bootstrap = """
import io, runpy, sys, tempfile, zipfile
from pathlib import Path
with tempfile.TemporaryDirectory() as folder:
    zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())).extractall(folder)
    script = Path(folder) / 'scripts/probe-native-source-batch.py'
    sys.argv = [str(script)] + ARGS
    runpy.run_path(str(script), run_name='__main__')
"""
    # A hard limit inside the container, so a source that ignores its
    # deadline cannot keep the probe (or the importer's CPU) busy.
    limit = max(30, int(os.environ.get('PROBE_TIMEOUT') or 3600))
    runner = ['docker', 'exec', '-i', 'oracle-importer-1', 'timeout', '-s', 'KILL', str(limit), 'python', '-B', '-c',
              'ARGS=' + repr(args) + '\n' + bootstrap]
    command = ('from pathlib import Path\nimport subprocess\n'
               'if Path("/opt/mediavault/deploy.lock").exists(): raise SystemExit("Deployment active")\n'
               'raise SystemExit(subprocess.run(' + repr(runner) + ', input=' + repr(payload) + ').returncode)')
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6', host, 'sudo -n python3 -'],
                          input=command.encode()).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch-size', type=int, default=150, choices=range(1, 201), metavar='1-200')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--inactive', action='store_true', help='Limit the window to unactivated direct profiles.')
    parser.add_argument('--suwayomi', action='store_true', help='Probe the installed extension directly through Suwayomi.')
    parser.add_argument('--workers', type=int, default=8, choices=range(1, 13), metavar='1-12')
    parser.add_argument('--source', action='append', default=[], help='Repeat to rerun particular source IDs.')
    parser.add_argument('--search', action='store_true', help='Also look up one returned title by exact ID.')
    parser.add_argument('--chapters', action='store_true', help='Validate one title’s chapter list without downloading images.')
    parser.add_argument('--pages', action='store_true', help='Also open the first chapter and fetch its first image.')
    parser.add_argument('--ssh', metavar='HOST', help='Run temporarily inside the importer through SSH.')
    args = parser.parse_args()
    if args.offset < 0 or len(args.source) > args.batch_size or args.source and (args.offset or args.inactive):
        parser.error('Supply a nonnegative offset with an optional inactive filter, or up to batch-size explicit IDs.')
    if args.ssh:
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.@-]*', args.ssh):
            parser.error('Invalid SSH host or alias.')
        remote_args = ['--batch-size', str(args.batch_size), '--offset', str(args.offset), '--workers', str(args.workers)]
        remote_args += [value for source in args.source for value in ('--source', source)]
        if args.inactive:
            remote_args.append('--inactive')
        if args.suwayomi:
            remote_args.append('--suwayomi')
        if args.search:
            remote_args.append('--search')
        if args.chapters:
            remote_args.append('--chapters')
        if args.pages:
            remote_args.append('--pages')
        return over_ssh(args.ssh, remote_args)
    live(args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
