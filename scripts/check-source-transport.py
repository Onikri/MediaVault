"""Live check of the source transport on the Oracle importer (read-only).

For each source ID: catalogue, exact search of a catalogue title, its card
(chapter list), one opened chapter and its first image, every step inside the
transport scope of that source, so declared routes (Japan exit, Byparr) apply.
Nothing is activated or switched off Suwayomi; no health or index state is
written. The current branch's ``server/`` is shipped to the container in an
archive, so the check also runs before a deployment.

    python scripts/check-source-transport.py --host mediavault-vm 7324763859222949244 1024627298672457456
    python scripts/check-source-transport.py --local <ids>   # inside the importer
"""

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def emit(row):
    print(json.dumps(row, ensure_ascii=False), flush=True)


def first_image(http, adapter, chapter, target):
    from manga_download import image_extension
    from manga_page_media import fetch_page, page_reference

    first = chapter['pages'][0]
    custom = getattr(adapter, 'page_headers', None)
    headers = custom(target) if custom else {'Referer': target}
    if reference := page_reference(first):
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
    return len(raw), bool(image_extension(bytes(raw[:32])))


def check(source_id, query=None):
    import manga_native_registry
    import source_transport
    from source_parser import PublicHttp, source_status

    adapter = manga_native_registry.profiles()[source_id]
    budget = source_transport.solver_budget(source_id, 20)
    result = {'source': source_id, 'name': adapter.NAME, 'declared': bool(source_transport.declared(source_id))}
    http = PublicHttp(timeout=(4, 15), source=source_id, operation='catalogue')
    phase, started = 'catalogue', time.monotonic()
    timings = {}

    def step(name, operation, call):
        nonlocal phase
        phase = name
        http.deadline = time.monotonic() + budget + 25
        began = time.monotonic()
        with http.scope(source_id, operation):
            value = call()
        timings[name] = round(time.monotonic() - began, 1)
        return value

    try:
        rows, _ = step('catalogue', 'catalogue', lambda: adapter.catalogue(http))
        result['catalogueRows'] = len(rows)
        sample = next((r for r in rows if 2 <= len(r.get('title') or '') <= 100), rows[0]) if rows else None
        term = query or (sample and sample['title'])
        found, _ = step('search', 'search', lambda: adapter.catalogue(http, query=term))
        result['searchRows'] = len(found)
        if not query:
            result['exactSearch'] = any(r.get('id') == sample['id'] for r in found)
        else:
            sample = found[0] if found else None
            result['exactSearch'] = bool(found) and any(term.casefold() in (r.get('title') or '').casefold() for r in found)
        if not sample:
            raise LookupError('nothing to open')
        result['title'] = sample['title']
        detail = step('card', 'chapters', lambda: adapter.inspect(sample['url'], http))
        episodes = [e for e in detail.get('episodes', []) if e.get('available') is not False]
        result['chapters'] = len(detail.get('episodes', []))
        if not episodes:
            raise LookupError('no open chapter')
        target = episodes[-1]['url'] if len(episodes) > 1 else episodes[0]['url']
        chapter = step('chapter', 'pages', lambda: adapter.inspect(target, http))
        result['pages'] = len(chapter.get('pages') or [])
        if not result['pages']:
            raise LookupError('chapter without pages')
        size, valid = step('image', 'images', lambda: first_image(http, adapter, chapter, chapter.get('url') or target))
        result.update(imageBytes=size, imageValid=valid, status='passed' if valid and result['exactSearch'] else 'partial')
    except Exception as error:  # noqa: BLE001 - every failure is reported with its status
        result.update(status=source_status(error), phase=phase, error=f'{type(error).__name__}: {str(error)[:200]}')
        if getattr(error, 'solver', None):
            result['solver'] = error.solver
    finally:
        http.close()
    result['seconds'] = round(time.monotonic() - started, 1)
    result['timings'] = timings
    sessions = source_transport.describe()['sessions']
    result['solverSessions'] = [s for s in sessions if s['source'] == source_id]
    return result


def local(args):
    sys.path.insert(0, str(ROOT / 'server'))
    import source_transport

    info = source_transport.describe()
    emit({'transport': {k: v for k, v in info.items() if k != 'sessions'}})
    queries = dict(item.split('=', 1) for item in args.query)
    for source_id in args.sources:
        emit(check(source_id, queries.get(source_id)))


def archive():
    payload = BytesIO()
    server = ROOT / 'server'
    paths = [Path(__file__), *sorted(server.glob('*.py')), *sorted(server.glob('*.json'))]
    with ZipFile(payload, 'w', ZIP_DEFLATED) as bundle:
        for path in paths:
            bundle.write(path, path.relative_to(ROOT).as_posix())
    return payload.getvalue()


def over_ssh(args):
    bootstrap = """
import io, runpy, sys, tempfile, zipfile
from pathlib import Path
with tempfile.TemporaryDirectory() as folder:
    zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())).extractall(folder)
    script = Path(folder) / 'scripts/check-source-transport.py'
    sys.argv = [str(script)] + ARGS
    runpy.run_path(str(script), run_name='__main__')
"""
    remote = ['--local', *args.sources, *[x for q in args.query for x in ('--query', q)]]
    limit = max(60, int(os.environ.get('PROBE_TIMEOUT') or 900))
    runner = ['docker', 'exec', '-i', 'oracle-importer-1', 'timeout', '-s', 'KILL', str(limit), 'python', '-B', '-c',
              'ARGS=' + repr(remote) + '\n' + bootstrap]
    command = ('from pathlib import Path\nimport subprocess\n'
               'if Path("/opt/mediavault/deploy.lock").exists(): raise SystemExit("Deployment active")\n'
               'raise SystemExit(subprocess.run(' + repr(runner) + ', input=' + repr(archive()) + ').returncode)')
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6', args.host, 'sudo -n python3 -'],
                          input=command.encode()).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', nargs='+')
    parser.add_argument('--host', default='mediavault-vm')
    parser.add_argument('--local', action='store_true', help='Run here (inside the importer container).')
    parser.add_argument('--query', action='append', default=[], metavar='SOURCE=TITLE',
                        help='Search this exact title instead of a catalogue sample.')
    args = parser.parse_args()
    if args.local:
        local(args)
        return 0
    return over_ssh(args)


if __name__ == '__main__':
    raise SystemExit(main())
