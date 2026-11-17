"""Read-only cutover baseline: direct path vs Suwayomi, from production records.

Sources of truth inside the importer (nothing is written):
- manga-discovery.sqlite ``work``/``work_diagnostics``: per-source search time
  and error class of owner searches, split by ``_nativeAdapter``;
- ``catalogue_jobs``: catalogue/detail indexing jobs, split by route;
- ``suwayomi-calls.jsonl``: counted HTTP calls to Suwayomi per source.

    python scripts/suwayomi-baseline.py --ssh mediavault-vm [--hours 24]
"""

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def pct(values, q):
    values = sorted(values)
    if not values:
        return None
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def stats(values):
    return {'n': len(values), 'p50': pct(values, .5), 'p95': pct(values, .95), 'max': max(values) if values else None}


def error_class(text):
    text = (text or '').casefold()
    for needle, name in (('http 429', 'rate-limit'), ('429', 'rate-limit'), ('timeout', 'timeout'), ('не успел', 'timeout'),
                         ('по сети', 'network'), ('нет связи', 'network'), ('http 403', 'restricted'),
                         ('провер', 'challenge'), ('cloudflare', 'challenge'), ('http 5', 'upstream-5xx'),
                         ('http 404', 'missing'), ('пуст', 'empty'), ('формат', 'format'), ('регион', 'region')):
        if needle in text:
            return name
    return 'other' if text else ''


def activated():
    sys.path.insert(0, str(ROOT / 'server'))
    from manga_native_sources import ADAPTERS
    return set(ADAPTERS)


def searches(db, since):
    rows = db.execute('''SELECT w.source,w.state,w.cached,d.details,j.created FROM work w
                         JOIN jobs j ON j.id=w.job LEFT JOIN work_diagnostics d ON d.job=w.job AND d.source_id=w.source_id
                         WHERE j.created>=?''', (since,)).fetchall()
    out = defaultdict(lambda: {'states': Counter(), 'errors': Counter(), 'elapsed': [], 'first_card': [], 'sources': set()})
    for source, state, cached, details, _ in rows:
        source = json.loads(source)
        route = 'direct' if source.get('_nativeAdapter') else 'suwayomi'
        bucket = out[route]
        details = json.loads(details) if details else {}
        if details.get('code') == 'paused':
            bucket['states']['paused'] += 1
            continue
        bucket['states']['cached' if cached else state] += 1
        if cached or state != 'done' and state != 'unavailable':
            continue
        bucket['sources'].add(str(source.get('id')))
        if state == 'unavailable':
            bucket['errors'][details.get('code') or 'unknown'] += 1
        elapsed = details.get('elapsedMs')
        if isinstance(elapsed, (int, float)) and elapsed > 0:
            bucket['elapsed'].append(elapsed)
    # first card: per job and route, the fastest source that returned results
    first = defaultdict(dict)
    for row in db.execute('''SELECT w.job,w.source,w.results,d.details FROM work w JOIN jobs j ON j.id=w.job
                             JOIN work_diagnostics d ON d.job=w.job AND d.source_id=w.source_id
                             WHERE j.created>=? AND w.state='done' AND w.cached=0 AND w.results!='[]' ''', (since,)):
        source = json.loads(row[1])
        route = 'direct' if source.get('_nativeAdapter') else 'suwayomi'
        elapsed = json.loads(row[3]).get('elapsedMs')
        if isinstance(elapsed, (int, float)) and elapsed > 0:
            first[route][row[0]] = min(first[route].get(row[0], elapsed), elapsed)
    jobs = db.execute('SELECT count(*),min(created),max(created) FROM jobs WHERE created>=?', (since,)).fetchone()
    return {'jobs': jobs[0], 'from': jobs[1], 'to': jobs[2], 'routes': {
        route: {'states': dict(b['states']), 'errors': dict(b['errors'].most_common()), 'sources': len(b['sources']),
                'per_source_ms': stats(b['elapsed']), 'first_card_ms': stats(list(first[route].values()))}
        for route, b in out.items()}}


def catalogue(db, since, direct_ids):
    out = defaultdict(lambda: {'states': Counter(), 'errors': Counter(), 'records': 0, 'pages': 0, 'sources': set()})
    per_source = defaultdict(Counter)
    query = '''SELECT kind,state,error,records,pages,json_extract(spec,'$.source.id'),json_extract(spec,'$.route'),
                      json_extract(cursor,'$.route'),updated FROM catalogue_jobs WHERE kind LIKE 'bridge%' AND updated>=?'''
    for kind, state, error, records, pages, sid, spec_route, cursor_route, _ in db.execute(query, (since,)):
        sid = str(sid)
        forced = 'suwayomi' in {spec_route, cursor_route}
        route = 'suwayomi' if forced or sid not in direct_ids else 'direct'
        key = f'{route}:{kind}'
        bucket = out[key]
        bucket['states'][state] += 1
        bucket['records'] += records or 0
        bucket['pages'] += pages or 0
        bucket['sources'].add(sid)
        if error:
            bucket['errors'][error_class(error)] += 1
        if route == 'suwayomi':
            per_source[sid][state] += 1
    other = Counter(r[0] for r in db.execute("SELECT kind FROM catalogue_jobs WHERE kind NOT LIKE 'bridge%' AND updated>=?", (since,)))
    return {'routes': {k: {'states': dict(b['states']), 'errors': dict(b['errors'].most_common()), 'records': b['records'],
                           'pages': b['pages'], 'sources': len(b['sources'])} for k, b in sorted(out.items())},
            'non_bridge_kinds': dict(other), 'suwayomi_sources': len(per_source),
            'suwayomi_by_source': {sid: dict(c) for sid, c in sorted(per_source.items(), key=lambda kv: -sum(kv[1].values()))[:40]}}


def calls(data_dir, since, direct_ids):
    path = data_dir / 'suwayomi-calls.jsonl'
    totals = defaultdict(lambda: [0, 0, 0])
    by_source = Counter()
    processes = Counter()
    first = None
    for name in (path.with_name(path.name + '.1'), path):
        if not name.is_file():
            continue
        for line in name.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('to', 0) < since:
                continue
            first = row['from'] if first is None else min(first, row['from'])
            for key, (count, total, peak) in row['calls'].items():
                operation, sid, outcome = key.split('|')
                entry = totals[(row.get('process'), operation, outcome)]
                entry[0] += count
                entry[1] += total
                entry[2] = max(entry[2], peak)
                processes[row.get('process')] += count
                by_source[(sid, sid in direct_ids, row.get('process'))] += count
    return {'since': first, 'by_process': dict(processes),
            'by_operation': [{'process': p, 'operation': o, 'outcome': r, 'calls': v[0],
                              'mean_ms': round(v[1] / v[0]) if v[0] else None, 'max_ms': v[2]}
                             for (p, o, r), v in sorted(totals.items(), key=lambda kv: -kv[1][0])],
            'by_source': [{'source_id': s, 'direct_active': d, 'process': p, 'calls': n}
                          for (s, d, p), n in by_source.most_common(60)]}


def live(args):
    import sqlite3
    data_dir = Path(os.getenv('DATA_DIR', '/data'))
    since = time.time() - args.hours * 3600 if args.hours else 0
    direct_ids = activated()
    db = sqlite3.connect(f'file:{(data_dir / "manga-discovery.sqlite").as_posix()}?mode=ro', uri=True, timeout=10)
    try:
        result = {'generated': time.time(), 'window_hours': args.hours, 'direct_active_ids': len(direct_ids),
                  'search': searches(db, since), 'catalogue': catalogue(db, since, direct_ids),
                  'calls': calls(data_dir, since, direct_ids)}
    finally:
        db.close()
    print(json.dumps(result, ensure_ascii=False, indent=1))


def over_ssh(host, args):
    from io import BytesIO
    from zipfile import ZIP_DEFLATED, ZipFile
    payload = BytesIO()
    with ZipFile(payload, 'w', ZIP_DEFLATED) as bundle:
        for path in [Path(__file__), *sorted((ROOT / 'server').glob('*.py')), *sorted((ROOT / 'server').glob('*.json'))]:
            bundle.write(path, path.relative_to(ROOT).as_posix())
    bootstrap = """
import io, runpy, sys, tempfile, zipfile
from pathlib import Path
with tempfile.TemporaryDirectory() as folder:
    zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())).extractall(folder)
    script = Path(folder) / 'scripts/suwayomi-baseline.py'
    sys.argv = [str(script)] + ARGS
    runpy.run_path(str(script), run_name='__main__')
"""
    runner = ['docker', 'exec', '-i', 'oracle-importer-1', 'timeout', '-s', 'KILL', '600', 'nice', '-n', '10',
              'python', '-B', '-c', 'ARGS=' + repr(['--hours', str(args.hours)]) + '\n' + bootstrap]
    command = 'import subprocess\nraise SystemExit(subprocess.run(' + repr(runner) + ', input=' + repr(payload.getvalue()) + ').returncode)'
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6', host, 'sudo -n python3 -'],
                          input=command.encode()).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--hours', type=float, default=0, help='Only records newer than this (0 = everything).')
    parser.add_argument('--ssh', metavar='HOST')
    args = parser.parse_args()
    if args.ssh:
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.@-]*', args.ssh):
            parser.error('Invalid SSH host or alias.')
        return over_ssh(args.ssh, args)
    live(args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
