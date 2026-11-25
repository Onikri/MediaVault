"""Read-only catalogue browse timings (C0 «Хентай», C1 search and filters).

Run on the VM, always with a timeout inside the container:

  ssh mediavault-vm 'sudo -n docker exec -i -w /app oracle-importer-1 timeout 120 nice -n 19 python - [--rounds 2] [--simulate] [--content [--kinds anime,movie]]' < scripts/catalog/browse-timing.py

It opens the catalogue read-only (like the API's catalogue_reader) and times
manga_catalog_index.browse(limit=60): no filter, deep pages, «Романтика»
pages 1 and 2, «Школа», both, «Большая грудь», «Хентай», text searches with
and without a filter. Round 2 shows the cached totals a running API serves.
--content times content_catalog.browse instead (C2): per kind (anime, movie,
tv, ranobe or --kinds) the client's sorts with and without «available»,
page 2, the most used genre and tag, a rare tag, an exclusion, a search, and
«Хентай» for anime; it prints the content-works fill state first. Each case
stops after 20 s. Nothing is written to the database file.

--simulate (before the deploy has filled the work set or the search index):
builds catalog_hentai_works and, for the searched words only, catalog_search
and catalog_search_rows in TEMP tables of this connection. Index reads are
then from memory, so search timings are a lower bound.
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
content = '--content' in sys.argv

db = sqlite3.connect(DB, uri=True, timeout=5, isolation_level=None)
db.row_factory = sqlite3.Row
db.execute('PRAGMA query_only=ON')
db.create_function('catalog_normalize', 1, normalize, deterministic=True)
register_origin_functions(db)

CASES = [('без фильтра', {}), ('без фильтра, стр. 2', {'offset': 60}), ('offset 3000', {'offset': 3000}),
         ('Романтика', {'genre': 'Романтика'}), ('Романтика, стр. 2', {'genre': 'Романтика', 'offset': 60}),
         ('Школа', {'tag': 'Школа'}), ('Романтика+Школа', {'genre': 'Романтика', 'tag': 'Школа'}),
         ('Большая грудь', {'tag': 'Большая грудь'}), ('Хентай', {'genre': 'Хентай'}),
         ('Хентай, стр. 2', {'genre': 'Хентай', 'offset': 60}), ('не Хентай', {'excludeGenre': 'Хентай'}),
         ('q=naruto', {'q': 'naruto'}), ('q=ван пис', {'q': 'ван пис'}), ('q=xyzqwv', {'q': 'xyzqwv'}),
         ('q=naruto, стр. 2', {'q': 'naruto', 'offset': 60}), ('q=naruto+Романтика', {'q': 'naruto', 'genre': 'Романтика'})]


def state(name):
    row = db.execute('SELECT value FROM catalog_policy_state WHERE name=?', (name,)).fetchone()
    return row[0] if row else 'missing'


import hentai_works
print('hentai-works:', state(hentai_works.STATE), '| ready:', hentai_works.ready(db, current()), flush=True)
try:
    import catalog_search
except ImportError:
    catalog_search = None
if catalog_search:
    print('search-index:', state(catalog_search.STATE), '| ready:', catalog_search.ready(db), flush=True)
    if db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (catalog_search.FTS,)).fetchone():
        top = db.execute('SELECT MAX(rowid) FROM catalog_titles').fetchone()[0]
        filled = json.loads(state(catalog_search.STATE)).get('cursor', 0) if state(catalog_search.STATE) != 'missing' else 0
        print('  rows indexed ~%d of %d' % (filled, top), flush=True)

if simulate:
    # Only this connection's TEMP schema is written; the file stays mode=ro.
    db.execute('PRAGMA query_only=OFF')
    if not hentai_works.ready(db, current()):
        from catalog_taxonomy import hentai_work_set
        started = time.monotonic()
        sql, args = hentai_work_set(current(), manga=True)
        db.execute('CREATE TEMP TABLE ' + hentai_works.TABLE + '(work_key TEXT PRIMARY KEY) WITHOUT ROWID')
        db.execute('INSERT INTO temp.' + hentai_works.TABLE + ' ' + sql, args)
        hentai_works.ready = lambda conn, policy: True
        print('simulated work set in %.2fs' % (time.monotonic() - started), flush=True)
    if catalog_search and not catalog_search.ready(db):
        started = time.monotonic()
        db.execute('CREATE VIRTUAL TABLE temp.' + catalog_search.FTS + " USING fts5(names, content='', columnsize=0, tokenize='trigram')")
        db.execute('CREATE TEMP TABLE ' + catalog_search.ROWS + '(id INTEGER PRIMARY KEY,work_key TEXT NOT NULL,year INTEGER,chapter_count INTEGER,first_seen REAL NOT NULL)')
        wanted = set()
        for _, args in CASES:
            for word in normalize(args.get('q', '')).split():
                wanted.update(r[0] for r in db.execute('SELECT s.rowid FROM catalog_titles s INDEXED BY catalog_titles_search WHERE s.search_text LIKE ?', ('%' + word + '%',)))
        rows = [tuple(r) for r in db.execute('SELECT ' + catalog_search.COLUMNS + ' FROM catalog_titles WHERE rowid IN (SELECT value FROM json_each(?))', (json.dumps(sorted(wanted)),))]
        db.executemany('INSERT INTO temp.' + catalog_search.FTS + '(rowid,names) VALUES(?,?)', [(r[0], catalog_search._document(r)) for r in rows])
        db.executemany('INSERT INTO temp.' + catalog_search.ROWS + ' VALUES(?,?,?,?,?)', [(r[0], *r[4:]) for r in rows])
        catalog_search.ready = lambda conn: True
        print('simulated search index: %d rows in %.2fs' % (len(rows), time.monotonic() - started), flush=True)
    db.execute('PRAGMA query_only=ON')


def timed(label, call):
    db.execute('BEGIN')
    started = time.monotonic()
    try:
        result = call()
        line = 'works=%s workTotal=%s total=%s exact=%s' % (result.get('works', len(result.get('items', []))), result.get('workTotal', '-'), result['total'], result.get('totalExact', True))
    except sqlite3.OperationalError as error:
        line = 'ERROR ' + str(error)[:120]
    finally:
        db.execute('COMMIT')
    print('%-44s %6.2fs %s' % (label, time.monotonic() - started, line), flush=True)


content_cases = []
if content:
    import content_catalog
    try:
        import content_works
        print('content-works:', content_works.progress(db), flush=True)
    except ImportError:
        content_works = None
    kinds = sys.argv[sys.argv.index('--kinds') + 1].split(',') if '--kinds' in sys.argv else ['anime', 'movie', 'tv', 'ranobe']
    for kind in kinds:
        add = lambda label, args, kind=kind: content_cases.append((kind, kind + ' ' + label, args))
        for status in ('available', ''):
            for sort in ('trending', 'score', 'new', 'old', 'title', 'updated'):
                add(sort + (' [available]' if status else ''), {'sort': sort, 'status': status})
            add('trending, стр. 2' + (' [available]' if status else ''), {'sort': 'trending', 'status': status, 'offset': 60})
        picks = [('genres', 'DESC'), ('tags', 'DESC')]
        for category, direction in picks:
            top = db.execute('SELECT tag_key,works FROM content_tag_stats WHERE kind=? AND category=? ORDER BY works ' + direction + ' LIMIT 1', (kind, category)).fetchone()
            if top:
                label = current().label(top[0], top[0])
                field = 'genre' if category == 'genres' else 'tag'
                add('%s=%s (%d)' % (field, label, top[1]), {field: label, 'sort': 'trending', 'status': 'available'})
                add('%s=%s, стр. 2' % (field, label), {field: label, 'sort': 'trending', 'status': 'available', 'offset': 60})
                add('%s=%s [все, new]' % (field, label), {field: label, 'sort': 'new'})
                add('не %s' % label, {'exclude' + field.capitalize(): label, 'sort': 'trending', 'status': 'available'})
        rare = db.execute('SELECT tag_key,works FROM content_tag_stats WHERE kind=? AND category=? AND works BETWEEN 50 AND 400 ORDER BY works DESC LIMIT 1', (kind, 'tags')).fetchone()
        if rare:
            label = current().label(rare[0], rare[0])
            add('редкий tag=%s (%d)' % (label, rare[1]), {'tag': label, 'sort': 'trending', 'status': 'available'})
        if kind == 'anime':
            add('Хентай', {'genre': 'Хентай', 'sort': 'trending', 'status': 'available'})
            add('Хентай, стр. 2', {'genre': 'Хентай', 'sort': 'trending', 'status': 'available', 'offset': 60})
            add('Хентай [все, new]', {'genre': 'Хентай', 'sort': 'new'})
        for q in ('love', 'маг'):
            add('q=' + q + ' [available]', {'q': q, 'sort': 'trending', 'status': 'available'})
            add('q=' + q, {'q': q})

for number in range(1, rounds + 1):
    print('--- round', number, flush=True)
    for status in ('', 'available') if not content else ():
        for label, args in CASES:
            if status and label.startswith('q='):
                continue
            timed(label + (' [available]' if status else ''), lambda: index.browse(db, limit=60, status=status, **args))
    for kind, label, args in content_cases:
        deadline = time.monotonic() + 20
        db.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 20000)
        timed(label, lambda: content_catalog.browse(db, kind=kind, limit=60, prepared=True, **args))
        db.set_progress_handler(None, 0)
    # Let the single background count of this process finish before the next round.
    for thread in threading.enumerate():
        if thread.name == 'catalog-total':
            thread.join(30)
db.close()
