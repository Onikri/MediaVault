"""Compare the direct MediaVault path with Suwayomi on the same title and chapter.

For each source ID the chain is: exact search -> title card -> chapter list ->
opened chapter -> first image, optionally every page of that chapter (CBZ
payload). Each step is timed separately on both paths; ``--repeat`` measures a
cold first run against later runs (solver session reuse). Nothing is written
to the catalogue, the search index or source health.

    python scripts/compare-source-paths.py --ssh mediavault-vm \
        --source 1585589665574145721 --query "..." --cbz --repeat 2
"""

import argparse
import json
import os
from io import BytesIO
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
MAX_CBZ_PAGES = 120


def emit(row):
    print(json.dumps(row, ensure_ascii=False), flush=True)


def norm(value):
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return re.sub(r'[\W_]+', '', value)


def number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


class Steps:
    def __init__(self):
        self.started = time.monotonic()
        self.ms = {}
        self.phase = 'search'

    def run(self, name, call):
        self.phase = name
        began = time.monotonic()
        try:
            return call()
        finally:
            self.ms[name] = round((time.monotonic() - began) * 1000)


def summary(steps, result):
    ms = steps.ms
    result['ms'] = ms
    result['first_card_ms'] = ms.get('search')
    if 'open' in ms and 'first_image' in ms:
        # Opening a known chapter as the reader does: page list + first image.
        result['first_page_ms'] = ms['open'] + ms['first_image']
    result['total_ms'] = round((time.monotonic() - steps.started) * 1000)
    return result


def classify(error):
    from source_parser import SourceAccessError, SourceRateLimitError, SourceTemporaryError
    code = getattr(error, 'code', None)
    if code:
        return code
    if isinstance(error, SourceRateLimitError):
        return 'rate-limit'
    if isinstance(error, SourceAccessError):
        return 'restricted'
    if isinstance(error, SourceTemporaryError):
        return 'temporary'
    status = re.search(r'HTTP (\d{3})', str(error))
    return f'http-{status[1]}' if status else type(error).__name__


def direct_chain(sid, query, chapter_number, cbz):
    import manga_native_registry
    from manga_download import image_extension
    from manga_page_media import fetch_page, page_reference
    from source_parser import PublicHttp
    from suwayomi_bridge import page_image, parse_reference

    adapter = manga_native_registry.profiles().get(sid)
    if adapter is None:
        return {'status': 'no-adapter'}
    steps, result = Steps(), {}
    http = PublicHttp(timeout=(3, 15), deadline=time.monotonic() + 240)
    try:
        rows, _ = steps.run('search', lambda: adapter.catalogue(http, query=query))
        result['search_rows'] = len(rows)
        exact = [row for row in rows if norm(row.get('title')) == norm(query)
                 or any(norm(v) == norm(query) for v in row.get('aliases') or [])]
        if not exact:
            return summary(steps, {**result, 'status': 'no-exact-match', 'phase': 'search'})
        card = exact[0]
        result['title'] = card.get('title')
        detail = steps.run('card', lambda: adapter.inspect(card['url'], http))
        episodes = [e for e in detail.get('episodes') or [] if not e.get('locked')]
        result['chapters'] = len(detail.get('episodes') or [])
        result['open_chapters'] = len(episodes)
        if not episodes:
            return summary(steps, {**result, 'status': 'no-chapters', 'phase': 'card'})
        target = pick(episodes, chapter_number, lambda e: e.get('number'))
        result['chapter_number'] = number(target.get('number'))
        chapter = steps.run('open', lambda: adapter.inspect(target['url'], http))
        pages = chapter.get('pages') or []
        result['page_count'] = len(pages)
        if not pages:
            return summary(steps, {**result, 'status': 'no-pages', 'phase': 'open'})
        referer = chapter.get('url') or target['url']
        custom = getattr(adapter, 'page_headers', None)
        headers = custom(referer) if custom else {'Referer': referer}

        def fetch(page):
            if parse_reference(page):
                return page_image(page)[0]
            if reference := page_reference(page):
                return fetch_page(http, reference, headers)[0]
            response, _ = http._open(page, headers=headers)
            try:
                return b''.join(response.iter_content(65536))
            finally:
                response.close()

        raw = steps.run('first_image', lambda: fetch(pages[0]))
        if not image_extension(bytes(raw[:32])):
            return summary(steps, {**result, 'status': 'not-image', 'phase': 'first_image'})
        result['first_image_bytes'] = len(raw)
        if cbz:
            result.update(steps.run('cbz', lambda: build_cbz([raw] + [fetch(p) for p in pages[1:MAX_CBZ_PAGES]])))
        return summary(steps, {**result, 'status': 'passed'})
    except Exception as error:  # every failure is reported, never hidden as empty
        return summary(steps, {**result, 'status': 'error', 'phase': steps.phase, 'error': classify(error)})
    finally:
        http.close()


def suwayomi_chain(sid, query, chapter_number, cbz):
    from manga_download import image_extension
    from manga_solver import source_timeout
    from suwayomi_bridge import Client

    steps, result = Steps(), {}
    timeout = max(source_timeout(sid, 25), 25)
    client = Client()
    try:
        found = steps.run('search', lambda: client.get(f'/source/{sid}/search', {'searchTerm': query, 'pageNum': 1}, timeout=timeout))
        rows = found.get('mangaList', [])
        result['search_rows'] = len(rows)
        exact = [row for row in rows if norm(row.get('title')) == norm(query)]
        if not exact:
            return summary(steps, {**result, 'status': 'no-exact-match', 'phase': 'search'})
        manga = exact[0]['id']
        result['title'] = exact[0].get('title')
        steps.run('card', lambda: client.get(f'/manga/{manga}', {'onlineFetch': 'true'}, timeout=timeout))
        chapters = steps.run('chapters', lambda: client.get(f'/manga/{manga}/chapters', {'onlineFetch': 'true'}, timeout=timeout))
        result['chapters'] = len(chapters)
        if not chapters:
            return summary(steps, {**result, 'status': 'no-chapters', 'phase': 'chapters'})
        target = pick(chapters, chapter_number, lambda c: c.get('chapterNumber'))
        index = target['index']
        result['chapter_number'] = number(target.get('chapterNumber'))
        opened = steps.run('open', lambda: client.get(f'/manga/{manga}/chapter/{index}', timeout=timeout))
        count = opened.get('pageCount')
        result['page_count'] = count
        if type(count) is not int or count < 1:
            return summary(steps, {**result, 'status': 'no-pages', 'phase': 'open'})

        def fetch(page):
            return client.get(f'/manga/{manga}/chapter/{index}/page/{page}', {'updateProgress': 'false'},
                              timeout=timeout, image=True)[0]

        raw = steps.run('first_image', lambda: fetch(0))
        if not image_extension(raw[:32]):
            return summary(steps, {**result, 'status': 'not-image', 'phase': 'first_image'})
        result['first_image_bytes'] = len(raw)
        if cbz:
            result.update(steps.run('cbz', lambda: build_cbz([raw] + [fetch(p) for p in range(1, min(count, MAX_CBZ_PAGES))])))
        return summary(steps, {**result, 'status': 'passed'})
    except Exception as error:
        return summary(steps, {**result, 'status': 'error', 'phase': steps.phase, 'error': classify(error)})
    finally:
        client.close()


def pick(entries, wanted, key):
    """The requested chapter number, else the lowest numbered open chapter."""
    numbered = [(number(key(e)), e) for e in entries]
    if wanted is not None:
        for value, entry in numbered:
            if value is not None and abs(value - wanted) < 1e-6:
                return entry
    numbered = [(v, e) for v, e in numbered if v is not None and v >= 1]
    return min(numbered, key=lambda item: item[0])[1] if numbered else entries[-1]


def build_cbz(images):
    from manga_download import image_extension
    payload = BytesIO()
    with ZipFile(payload, 'w', ZIP_STORED) as archive:
        for index, raw in enumerate(images, 1):
            extension = image_extension(bytes(raw[:32]))
            if not extension:
                raise ValueError(f'page {index} is not an image')
            archive.writestr(f'{index:03d}.{extension}', bytes(raw))
    return {'cbz_pages': len(images), 'cbz_bytes': len(payload.getvalue())}


def live(args):
    sys.path.insert(0, str(ROOT / 'server'))
    os.environ.setdefault('SUWAYOMI_CALLS_TAG', 'pilot')
    emit({'event': 'started', 'sources': args.source, 'query': args.query, 'repeat': args.repeat, 'cbz': args.cbz})
    for sid in args.source:
        for attempt in range(1, args.repeat + 1):
            for route in args.routes:
                chain = direct_chain if route == 'direct' else suwayomi_chain
                chapter = args.chapter
                result = chain(sid, args.query, chapter, args.cbz)
                emit({'event': 'chain', 'source_id': sid, 'route': route, 'attempt': attempt, **result})
    from suwayomi_bridge import flush_calls
    flush_calls()


def archive():
    payload = BytesIO()
    server = ROOT / 'server'
    paths = [Path(__file__), *sorted(server.glob('*.py')), *sorted(server.glob('*.json'))]
    with ZipFile(payload, 'w', ZIP_DEFLATED) as bundle:
        for path in paths:
            bundle.write(path, path.relative_to(ROOT).as_posix())
    return payload.getvalue()


def over_ssh(host, args):
    bootstrap = """
import io, runpy, sys, tempfile, zipfile
from pathlib import Path
with tempfile.TemporaryDirectory() as folder:
    zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())).extractall(folder)
    script = Path(folder) / 'scripts/compare-source-paths.py'
    sys.argv = [str(script)] + ARGS
    runpy.run_path(str(script), run_name='__main__')
"""
    limit = max(60, int(os.environ.get('PROBE_TIMEOUT') or 1800))
    runner = ['docker', 'exec', '-i', '-e', 'SUWAYOMI_CALLS_TAG=pilot', 'oracle-importer-1', 'timeout', '-s', 'KILL',
              str(limit), 'python', '-B', '-c', 'ARGS=' + repr(args) + '\n' + bootstrap]
    command = ('from pathlib import Path\nimport subprocess\n'
               'if Path("/opt/mediavault/deploy.lock").exists(): raise SystemExit("Deployment active")\n'
               'raise SystemExit(subprocess.run(' + repr(runner) + ', input=' + repr(archive()) + ').returncode)')
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6', host, 'sudo -n python3 -'],
                          input=command.encode()).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', action='append', required=True, help='Suwayomi source ID; repeatable.')
    parser.add_argument('--query', required=True, help='Exact title to search on both paths.')
    parser.add_argument('--chapter', type=float, help='Chapter number to open (default: lowest numbered).')
    parser.add_argument('--cbz', action='store_true', help='Fetch every page of the chapter into an in-memory CBZ.')
    parser.add_argument('--repeat', type=int, default=1, choices=range(1, 6), metavar='1-5')
    parser.add_argument('--routes', default='direct,suwayomi', help='Comma list of direct and/or suwayomi.')
    parser.add_argument('--ssh', metavar='HOST', help='Run temporarily inside the importer through SSH.')
    args = parser.parse_args()
    args.routes = [r for r in args.routes.split(',') if r]
    if not args.routes or set(args.routes) - {'direct', 'suwayomi'}:
        parser.error('--routes accepts direct and suwayomi.')
    if any(not re.fullmatch(r'\d{1,20}', s) for s in args.source):
        parser.error('Source IDs are numeric.')
    if args.ssh:
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.@-]*', args.ssh):
            parser.error('Invalid SSH host or alias.')
        remote = [v for s in args.source for v in ('--source', s)] + ['--query', args.query,
                                                                     '--repeat', str(args.repeat),
                                                                     '--routes', ','.join(args.routes)]
        if args.chapter is not None:
            remote += ['--chapter', str(args.chapter)]
        if args.cbz:
            remote.append('--cbz')
        return over_ssh(args.ssh, remote)
    live(args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
