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
    import manga_additional_catalogues
    import manga_booru_pools
    import manga_comicklive
    import manga_japanese_next
    import manga_asura_native
    import manga_alphapolis
    import manga_blacktoon
    import manga_ciaoplus
    import manga_clipstudio_sources
    import manga_corocoro
    import manga_coronaex
    import manga_dle_readers
    import manga_dynasty
    import manga_drecomics
    import manga_ebookrenta
    import manga_flower_comics
    import manga_lusttoon
    import manga_mangabox
    import manga_mangameets
    import manga_mangaone
    import manga_mangaplaza
    import manga_momonga
    import manga_mokuro
    import manga_nicomanga
    import manga_park_publisher
    import manga_toomics
    import manga_toonkotsu
    import manga_fourkhd
    import manga_honeytoon_native
    import manga_hakusensha
    import manga_honto
    import manga_jjcos
    import manga_multporn
    import manga_ososedki
    import manga_twicomi
    import manga_voyceme
    import manga_alpha_manga
    import manga_catalogue_api_ports
    import manga_comic_museum
    import manga_comic_grast
    import manga_comics_kingdom
    import manga_ksbd
    import manga_korean_seventh
    import manga_ninehentai
    import manga_toon11
    import manga_girlstop
    import manga_manhwazone
    import manga_rawkuma_overlay
    import manga_reimanga
    import manga_vyvy
    import manga_gallery_archive_ports
    import manga_klto9
    import manga_mangaplus
    import manga_mangamee
    import manga_manta_native
    import manga_omega
    import manga_rinko
    import manga_unicomics
    import manga_webnex
    import manga_yellownote
    import manga_nexus_reader
    import manga_rayuba
    import manga_seventh_data
    import manga_seventh_html
    import manga_zerosum
    import manga_small_readers
    import manga_scan_api_ports
    import manga_luscious_native
    import manga_pandachaika
    import manga_simply_native
    import manga_toonlook
    import manga_wordpress_locales
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
                  manga_sixth_profiles.SOURCES, manga_wordpress_locales.SOURCES, manga_simply_native.SOURCES,
                  manga_luscious_native.SOURCES, manga_additional_catalogues.SOURCES, manga_pandachaika.SOURCES,
                  manga_toonlook.SOURCES, manga_alpha_manga.SOURCES, manga_catalogue_api_ports.SOURCES,
                  manga_gallery_archive_ports.SOURCES, manga_klto9.SOURCES, manga_mangaplus.SOURCES,
                  manga_small_readers.SOURCES, manga_scan_api_ports.SOURCES, manga_manta_native.SOURCES,
                  manga_comic_museum.SOURCES, manga_mangamee.SOURCES, manga_omega.SOURCES,
                  manga_rinko.SOURCES, manga_unicomics.SOURCES, manga_webnex.SOURCES, manga_yellownote.SOURCES,
                  manga_seventh_data.SOURCES, manga_seventh_html.SOURCES, manga_rayuba.SOURCES,
                  manga_zerosum.SOURCES, manga_nexus_reader.SOURCES, manga_comics_kingdom.SOURCES,
                  manga_comic_grast.SOURCES, manga_ksbd.SOURCES, manga_girlstop.SOURCES,
                  manga_reimanga.SOURCES, manga_vyvy.SOURCES, manga_manhwazone.SOURCES,
                  manga_rawkuma_overlay.SOURCES, manga_korean_seventh.SOURCES, manga_toon11.SOURCES,
                  manga_ninehentai.SOURCES, manga_comicklive.SOURCES, manga_jjcos.SOURCES,
                  manga_twicomi.SOURCES, manga_booru_pools.SOURCES, manga_ososedki.SOURCES,
                  manga_honeytoon_native.SOURCES, manga_fourkhd.SOURCES, manga_voyceme.SOURCES, manga_multporn.SOURCES,
                  manga_japanese_next.SOURCES, manga_mangameets.SOURCES, manga_momonga.SOURCES,
                  manga_park_publisher.SOURCES, manga_toomics.SOURCES, manga_mangaone.SOURCES,
                  manga_mangabox.SOURCES, manga_asura_native.SOURCES, manga_corocoro.SOURCES,
                  manga_ciaoplus.SOURCES, manga_lusttoon.SOURCES, manga_blacktoon.SOURCES, manga_nicomanga.SOURCES,
                  manga_dle_readers.SOURCES, manga_dynasty.SOURCES, manga_mokuro.SOURCES, manga_toonkotsu.SOURCES,
                  manga_clipstudio_sources.SOURCES, manga_honto.SOURCES, manga_hakusensha.SOURCES,
                  manga_mangaplaza.SOURCES, manga_ebookrenta.SOURCES, manga_drecomics.SOURCES,
                  manga_flower_comics.SOURCES, manga_alphapolis.SOURCES, manga_coronaex.SOURCES):
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
