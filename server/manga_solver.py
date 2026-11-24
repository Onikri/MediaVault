"""Extra cold-start time only for sources verified with the private solver.

The administrator writes this small local manifest after a real source check.
It contains source IDs and a bounded budget, never cookies or proxy addresses.
"""
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from contextlib import closing


def valid(value):
    if not isinstance(value, dict):
        return False
    sources, budget = value.get('sourceIds'), value.get('requestTimeout')
    return (value.get('engine') in {'flaresolverr', 'byparr'}
            and isinstance(sources, list) and 1 <= len(sources) <= 128
            and all(isinstance(s, str) and re.fullmatch(r'\d{1,20}', s) for s in sources)
            and type(budget) is int and 12 <= budget <= 75)


def source_timeout(source_id, normal):
    path = Path(os.getenv('DATA_DIR', '/data')) / 'manga-source-solver.json'
    try:
        if path.stat().st_size > 8192:
            return normal
        value = json.loads(path.read_text())
        if not valid(value):
            return normal
        return max(normal, value['requestTimeout']) if str(source_id) in value['sourceIds'] else normal
    except (OSError, ValueError, TypeError, AttributeError):
        return normal


def configure(manifest, reader_ids=()):
    """Called only by the locked VM installer after separate live checks.

    Invalidate stale failures for those exact sources. Keep successful caches,
    all indexed titles and every catalogue job/cursor. Other sources retain their
    backoff. Reader failures are cleared only after a chapter/image check.
    """
    if not valid(manifest) or not set(reader_ids).issubset(manifest['sourceIds']):
        raise ValueError('Invalid verified solver source configuration')
    root = Path(os.getenv('DATA_DIR', '/data'))
    target = root / 'manga-source-solver.json'
    temporary = root / '.manga-source-solver.json.tmp'
    temporary.write_text(json.dumps(manifest))
    temporary.chmod(0o600)
    stats = {'resetSearchFailures': 0, 'invalidatedSnapshots': 0, 'queuedCatalogueJobs': 0}
    database = root / 'manga-discovery.sqlite'
    try:
        if database.is_file():
            with closing(sqlite3.connect(database, timeout=20)) as db, db:
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for identity in manifest['sourceIds']:
                    if 'reachability' in tables:
                        stats['resetSearchFailures'] += db.execute('DELETE FROM reachability WHERE source_id=? AND failures>0', (identity,)).rowcount
                    if {'jobs', 'work'}.issubset(tables):
                        stats['invalidatedSnapshots'] += db.execute("UPDATE jobs SET state='interrupted' WHERE state='done' AND id IN (SELECT job FROM work WHERE source_id=? AND state IN ('skipped','unavailable'))", (identity,)).rowcount
                    if 'catalogue_jobs' in tables:
                        stats['queuedCatalogueJobs'] += db.execute("UPDATE catalogue_jobs SET due=MIN(due,?) WHERE state IN ('retry','stalled','partial') AND CAST(json_extract(spec,'$.source.id') AS TEXT)=?", (time.time(), identity)).rowcount
        if reader_ids:
            from manga_source_health import reset_failures
            reset_failures(reader_ids)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return stats
