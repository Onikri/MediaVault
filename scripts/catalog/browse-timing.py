"""Read-only manga catalogue browse timings (C0: «Хентай» filter).

Run on the VM, always with a timeout inside the container:

  ssh mediavault-vm 'sudo -n docker exec -i -w /app oracle-importer-1 timeout 120 nice -n 19 python - [--rounds 2] [--simulate]' < scripts/catalog/browse-timing.py

It opens the catalogue read-only (like the API's catalogue_reader) and times
manga_catalog_index.browse(limit=60) for: no filter, «Романтика», «Хентай»,
not-«Хентай»; first and second page; status '' and 'available'. Round 2 shows
the cached totals a running API would serve. Nothing is written.

--simulate (before the deploy has filled catalog_hentai_works): builds the
work set in a TEMP table of this connection from the old derived union and
times the new streamed pages against it. Totals stay lower bounds there.
"""
import json
import sqlite3
import sys
import threading
import time

sys.path.insert(0, '/app')
from manga_tag_policy import current, normalize
from catalog_taxonomy import register_origin_functions
import manga_catalog_index as index

DB = 'file:/data/manga-discovery.sqlite?mode=ro'
rounds = int(sys.argv[sys.argv.index('--rounds') + 1]) if '--rounds' in sys.argv else 2
simulate = '--simulate' in sys.argv

db = sqlite3.connect(DB, uri=True, timeout=5, isolation_level=None)
db.row_factory = sqlite3.Row
db.execute('PRAGMA query_only=ON')
db.create_function('catalog_normalize', 1, normalize, deterministic=True)
register_origin_functions(db)

try:
    import hentai_works
except ImportError:
    hentai_works = None
if hentai_works:
    state = db.execute("SELECT value FROM catalog_policy_state WHERE name=?", (hentai_works.STATE,)).fetchone()
    print('hentai-works state:', state[0] if state else 'missing', '| ready:', hentai_works.ready(db, current()), flush=True)
    if simulate and not hentai_works.ready(db, current()):
        from catalog_taxonomy import hentai_work_set
        started = time.monotonic()
        sql, args = hentai_work_set(current(), manga=True)
        # Only this connection's TEMP schema is written; the file stays mode=ro.
        db.execute('PRAGMA query_only=OFF')
        db.execute('CREATE TEMP TABLE ' + hentai_works.TABLE + '(work_key TEXT PRIMARY KEY) WITHOUT ROWID')
        db.execute('INSERT INTO temp.' + hentai_works.TABLE + ' ' + sql, args)
        db.execute('PRAGMA query_only=ON')
        hentai_works.ready = lambda conn, policy: True
        print('simulated work set: %d works in %.2fs' % (db.execute('SELECT COUNT(*) FROM temp.' + hentai_works.TABLE).fetchone()[0], time.monotonic() - started), flush=True)

CASES = [('без фильтра', {}), ('без фильтра, стр. 2', {'offset': 60}),
         ('Романтика', {'genre': 'Романтика'}),
         ('Хентай', {'genre': 'Хентай'}), ('Хентай, стр. 2', {'genre': 'Хентай', 'offset': 60}),
         ('не Хентай', {'excludeGenre': 'Хентай'})]
for number in range(1, rounds + 1):
    print('--- round', number, flush=True)
    for status in ('', 'available'):
        for label, args in CASES:
            db.execute('BEGIN')
            started = time.monotonic()
            try:
                result = index.browse(db, limit=60, status=status, **args)
                line = 'works=%d workTotal=%d total=%d exact=%s' % (result['works'], result['workTotal'], result['total'], result.get('totalExact', True))
            except sqlite3.OperationalError as error:
                line = 'ERROR ' + str(error)[:120]
            finally:
                db.execute('COMMIT')
            print('%-20s status=%-9s %6.2fs %s' % (label, status or '-', time.monotonic() - started, line), flush=True)
    # Let the single background count of this process finish before the next round.
    for thread in threading.enumerate():
        if thread.name == 'catalog-total':
            thread.join(30)
db.close()
