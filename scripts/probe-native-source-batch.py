"""Audit a batch of direct catalogue profiles without reading pages or updating health."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
import json
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
    import manga_fifth_batch_profiles
    import manga_niadd_novelcool
    import manga_sixth_profiles
    import manga_speedbinb_sources
    import manga_webtoons_native
    import manga_fourth_batch_profiles
    import manga_archive_ports
    import manga_bakkin
    import manga_comicfury
    import manga_comici
    import manga_dbmultiverse
    import manga_direct_articles
    import manga_direct_catalogues
    import manga_direct_payloads
    import manga_foolslide
    import manga_gigaviewer
    import manga_globalcomix
    import manga_gallery_adults
    import manga_guya
    import manga_hentaihand
    import manga_html_families
    import manga_individual_catalogues
    import manga_json_families
    import manga_loluniverse
    import manga_mangadventure
    import manga_mangaball_native
    import manga_mangadex_native
    import manga_mangadot
    import manga_mangamillion
    import manga_mangatoon
    import manga_mangak
    import manga_masonry
    import manga_multichan
    import manga_namicomi
    import manga_saymanhwa
    import manga_ru_families
    import manga_native_sources as native
    import manga_webcomics
    import manga_xcomic
    import manga_yii

    profiles = dict(native.ADAPTERS)
    for module in (native.manga_madara, native.manga_themesia, native.manga_keyoapp, native.manga_vinetheme,
                   native.manga_mangacatalog, native.manga_iken, native.manga_mangahub, manga_hentaihand,
                   manga_comici, manga_gigaviewer, manga_yii, manga_guya, manga_mangadventure,
                   manga_mangak, manga_masonry, manga_multichan, manga_bakkin, manga_loluniverse,
                   manga_mangadex_native, manga_foolslide, manga_mangaball_native, manga_mangamillion,
                   manga_mangadot, manga_namicomi, manga_globalcomix, manga_dbmultiverse,
                   manga_saymanhwa, manga_mangatoon, manga_xcomic, manga_comicfury):
        profiles.update((adapter.SOURCE_ID, adapter) for adapter in module.SOURCES)
    profiles.update((adapter.SOURCE_ID, adapter) for adapter in manga_webcomics.adapters())
    profiles.update((adapter.SOURCE_ID, adapter) for adapter in manga_fourth_batch_profiles.sources())
    profiles.update((adapter.SOURCE_ID, adapter) for adapter in manga_fifth_batch_profiles.sources())
    for group in (manga_archive_ports.SOURCES, manga_html_families.SOURCES, manga_individual_catalogues.SOURCES,
                  manga_json_families.sources(), manga_ru_families.SOURCES, manga_direct_articles.sources(),
                  manga_direct_catalogues.sources(), manga_direct_payloads.sources(), manga_gallery_adults.sources(),
                  manga_speedbinb_sources.SOURCES, manga_webtoons_native.SOURCES, manga_niadd_novelcool.SOURCES,
                  manga_sixth_profiles.SOURCES):
        profiles.update((adapter.SOURCE_ID, adapter) for adapter in group)
    standby = native.manga_mangahub.MANGA_HERE
    profiles[standby.SOURCE_ID] = standby
    return profiles, native.ADAPTERS


def audit(adapter, check_search, check_chapters):
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


def probe_origin(adapters, enabled, check_search, check_chapters):
    results = []
    rate_limited = False
    for adapter in adapters:
        started = time.monotonic()
        result = {'status': 'deferred', 'phase': 'catalogue'} if rate_limited else audit(adapter, check_search, check_chapters)
        rate_limited |= result['status'] == 'rate_limited'
        results.append({'source_id': adapter.SOURCE_ID, 'name': adapter.NAME,
                        'enabled': adapter.SOURCE_ID in enabled, 'ms': round((time.monotonic()-started)*1000), **result})
    return results


def live(args):
    sys.path.insert(0, str(ROOT / 'server'))
    profiles, enabled = candidates()
    unknown = set(args.source) - profiles.keys()
    if unknown:
        raise SystemExit('No direct profile for: ' + ', '.join(sorted(unknown)))
    ordered = sorted(profiles.values(), key=lambda row: (row.SOURCE_ID in enabled, row.NAME.casefold(), row.SOURCE_ID))
    if args.inactive:
        ordered = [row for row in ordered if row.SOURCE_ID not in enabled]
    if args.source:
        selected = [row for row in ordered if row.SOURCE_ID in args.source]
    else:
        selected = ordered[args.offset:args.offset + args.batch_size]
    groups = defaultdict(list)
    for adapter in selected:
        groups[urlsplit(adapter.ROOT).hostname].append(adapter)
    started = time.monotonic()
    emit({'event': 'started', 'total_profiles': len(profiles), 'selected': len(selected), 'origins': len(groups),
          'workers': args.workers, 'search': args.search, 'chapters': args.chapters, 'inactive_only': args.inactive})
    statuses = Counter()
    operations = Counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(probe_origin, group, enabled, args.search, args.chapters) for group in groups.values()]
        for future in as_completed(jobs):
            for result in future.result():
                statuses[result['status']] += 1
                operations.update(key for key in ('catalogue', 'search', 'chapters') if result.get(key))
                emit({'event': 'source', **result})
    emit({'event': 'summary', 'completed': sum(statuses.values()), 'catalogues_returned': operations['catalogue'],
          'searches_matched': operations['search'], 'chapter_lists_returned': operations['chapters'],
          'statuses': dict(statuses), 'seconds': round(time.monotonic() - started, 2)})


def over_ssh(host, args):
    payload = BytesIO()
    with ZipFile(payload, 'w', ZIP_DEFLATED) as archive:
        for path in [Path(__file__), *sorted((ROOT / 'server').glob('*.py'))]:
            archive.write(path, path.relative_to(ROOT).as_posix())
    bootstrap = """
import io, runpy, sys, tempfile, zipfile
from pathlib import Path
with tempfile.TemporaryDirectory() as folder:
    zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())).extractall(folder)
    script = Path(folder) / 'scripts/probe-native-source-batch.py'
    sys.argv = [str(script)] + ARGS
    runpy.run_path(str(script), run_name='__main__')
"""
    command = ('from pathlib import Path\nimport subprocess\n'
               'if Path("/opt/mediavault/deploy.lock").exists(): raise SystemExit("Deployment active")\n'
               'raise SystemExit(subprocess.run('
               "['docker', 'exec', '-i', 'oracle-importer-1', 'python', '-B', '-c', "
               + repr('ARGS=' + repr(args) + '\n' + bootstrap) + '], input=' + repr(payload.getvalue()) + ').returncode)')
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6', host, 'sudo -n python3 -'],
                          input=command.encode()).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch-size', type=int, default=150, choices=range(1, 201), metavar='1-200')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--inactive', action='store_true', help='Limit the window to unactivated direct profiles.')
    parser.add_argument('--workers', type=int, default=8, choices=range(1, 13), metavar='1-12')
    parser.add_argument('--source', action='append', default=[], help='Repeat to rerun particular source IDs.')
    parser.add_argument('--search', action='store_true', help='Also look up one returned title by exact ID.')
    parser.add_argument('--chapters', action='store_true', help='Validate one title’s chapter list without downloading images.')
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
        if args.search:
            remote_args.append('--search')
        if args.chapters:
            remote_args.append('--chapters')
        return over_ssh(args.ssh, remote_args)
    live(args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
