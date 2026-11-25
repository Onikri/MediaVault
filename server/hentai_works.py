"""Materialized «Хентай» work set for the manga catalogue.

The genre is derived per work: a work is hentai when one of its source rows
comes from a hentai origin or carries an explicit hentai tag, unless a row of
the work has a «Не хентай» source fact (catalog_taxonomy.hentai_work_set).
Evaluating that union for 400 000 works on every page took about a minute on
the VM. catalog_hentai_works stores the same set, one row per work:

* refresh() recomputes given works exactly; manga_catalog_index calls it from
  refresh_work_tags(), so every upsert, tag merge and retirement keeps it.
* step() computes the set for new rules (a new source, new «Хентай» keys) in
  short resumable portions (state row catalog_policy_state 'hentai-works')
  into catalog_hentai_works_next, then merges it into catalog_hentai_works.
  Meanwhile pages keep reading the previous set ('served'); only a catalogue
  that never had a complete set uses the derived union.

No phase needs an expression index over catalog_titles: the origin phase
reads (provider, source_url) from the UNIQUE index on a reader connection,
outside store.lock, and decides the origin in Python.
"""
import hashlib
import json
import time

TABLE = 'catalog_hentai_works'
NEXT = 'catalog_hentai_works_next'
STATE = 'hentai-works'
PORTION = 20000
# Entries of the (provider, source_url) index read per origin portion.
SCAN = 20000
# Legacy expression indexes are dropped only by a release that has been
# answering for this long: the deploy's rollback target still uses them.
RETIRE_AFTER = 900
_started = time.monotonic()


def signature(policy):
    from catalog_taxonomy import HENTAI, keys
    wanted = keys('Хентай', policy, allow_hidden=True)
    return hashlib.sha256(json.dumps([HENTAI, wanted], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _present(conn, table=TABLE):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _served(state):
    """Signature of the complete set in TABLE ('' when it is incomplete)."""
    if 'served' in state:
        return state['served']
    # The state format before C3 had a complete set exactly when done.
    return state.get('signature', '') if state.get('phase') == 'done' else ''


def initialize(conn):
    """Cheap: a rule change only records the new target; step() does the work."""
    conn.execute('CREATE TABLE IF NOT EXISTS ' + TABLE + '(work_key TEXT PRIMARY KEY) WITHOUT ROWID')
    from manga_tag_policy import current
    if _state(conn).get('signature') != signature(current()):
        _reset(conn)


def _reset(conn):
    from manga_tag_policy import current
    stamp = signature(current())
    # A new catalogue starts complete; refresh() maintains it from the first row.
    if not conn.execute('SELECT 1 FROM catalog_titles LIMIT 1').fetchone():
        _save(conn, {'signature': stamp, 'phase': 'done', 'cursor': '', 'served': stamp})
        return
    _save(conn, {'signature': stamp, 'phase': 'clear', 'cursor': '', 'served': _served(_state(conn))})


def _state(conn):
    try:
        row = conn.execute('SELECT value FROM catalog_policy_state WHERE name=?', (STATE,)).fetchone()
        return json.loads(row[0]) if row else {}
    except Exception:
        return {}


def _save(conn, state):
    conn.execute('INSERT OR REPLACE INTO catalog_policy_state VALUES(?,?)', (STATE, json.dumps(state, sort_keys=True, ensure_ascii=False)))


def ready(conn, policy=None):
    """TABLE holds a complete set: the current one or, while new rules are
    computed, the previous one."""
    return bool(_served(_state(conn)))


def current(conn, policy=None):
    """TABLE holds the set of the current rules."""
    if policy is None:
        from manga_tag_policy import current as policy_now
        policy = policy_now()
    state = _state(conn)
    stamp = signature(policy)
    return state.get('phase') == 'done' and state.get('signature') == stamp and _served(state) == stamp


def invalidate(conn):
    """The explicit-tag projection was rebuilt: recompute the set in the background."""
    if _present(conn):
        _reset(conn)


def members(conn, works, policy):
    """The exact hentai_work_set() restricted to these works."""
    from catalog_taxonomy import keys, register_origin_functions
    register_origin_functions(conn)
    works = sorted({work for work in works if work})
    wanted = keys('Хентай', policy, allow_hidden=True)
    found = set()
    for start in range(0, len(works), 500):
        chunk = works[start:start + 500]
        marks = ','.join('?' for _ in chunk)
        tags = ','.join('?' for _ in wanted) or "''"
        found.update(key for (key,) in conn.execute(
            'SELECT DISTINCT t.work_key FROM catalog_titles t WHERE t.work_key IN (' + marks + ') AND '
            "(catalog_hentai_origin(t.provider,t.source_url,'manga')=1 OR EXISTS("
            'SELECT 1 FROM catalog_tags x WHERE x.title_id=t.id AND x.tag_key IN (' + tags + ')))', [*chunk, *wanted]))
        found.difference_update(_vetoed(conn, chunk))
    return found


def _vetoed(conn, works):
    """Works among these (at most 500) with a «Не хентай» source fact."""
    marks = ','.join('?' for _ in works)
    return {key for (key,) in conn.execute(
        'SELECT DISTINCT t.work_key FROM catalog_titles t JOIN catalog_tag_facts f ON f.title_id=t.id '
        'WHERE t.work_key IN (' + marks + ') AND catalog_not_hentai(f.original)=1', works)}


def refresh(conn, works, policy=None):
    """Recompute these works exactly in the served set and in a set being built."""
    works = sorted({work for work in works if work})
    if not works or not _present(conn):
        return
    from manga_tag_policy import current as policy_now
    found = members(conn, works, policy or policy_now())
    for table in [TABLE, *([NEXT] if _present(conn, NEXT) else [])]:
        for start in range(0, len(works), 500):
            chunk = works[start:start + 500]
            conn.execute('DELETE FROM ' + table + ' WHERE work_key IN (' + ','.join('?' for _ in chunk) + ')', chunk)
        conn.executemany('INSERT OR IGNORE INTO ' + table + ' VALUES(?)', [(work,) for work in sorted(found)])


def _origin_rows(db, cursor):
    """(entries, rowids of hentai-origin rows) of the next SCAN entries of the
    UNIQUE(provider, source_url) index after cursor."""
    from catalog_taxonomy import hentai_origin
    if cursor:
        entries = db.execute('SELECT provider,source_url,rowid FROM catalog_titles WHERE (provider,source_url)>(?,?) '
                             'ORDER BY provider,source_url LIMIT ?', (cursor[0], cursor[1], SCAN)).fetchall()
    else:
        entries = db.execute('SELECT provider,source_url,rowid FROM catalog_titles ORDER BY provider,source_url LIMIT ?', (SCAN,)).fetchall()
    return entries, [rowid for provider, url, rowid in entries if hentai_origin(provider, url, 'manga')]


def _works_of(db, rowids):
    found = set()
    for start in range(0, len(rowids), 500):
        chunk = rowids[start:start + 500]
        found.update(key for (key,) in db.execute(
            'SELECT work_key FROM catalog_titles WHERE rowid IN (' + ','.join('?' for _ in chunk) + ") AND work_key<>''", chunk))
    return found


def step(store, clock=time.monotonic):
    """Advance the computation by one portion; False when there is nothing to do."""
    from manga_tag_policy import current as policy_now
    from catalog_taxonomy import keys, register_origin_functions, retire_indexes, veto_index
    with store.lock:
        db = store.db
        if not _present(db):
            return False
        stored = state = _state(db)
        stamp = signature(policy_now())
        if state.get('signature') != stamp:
            state = {'signature': stamp, 'phase': 'clear', 'cursor': '', 'served': _served(state)}
        phase = state.get('phase')
        if phase == 'done':
            if clock() - _started < RETIRE_AFTER:
                return False
            with db:
                return retire_indexes(db, manga=True)
    if phase == 'origin':
        # Read and decide the portion outside the lock (and warm its rows).
        from manga_discovery import catalogue_reader
        with catalogue_reader(store) as reader:
            entries, origins = _origin_rows(reader, state.get('cursor'))
            _works_of(reader, origins)
    with store.lock:
        db = store.db
        if _state(db) != stored:
            # Changed meanwhile (new rules, rebuilt tags): start over from it.
            return True
        register_origin_functions(db)
        started = clock()
        with db:
            if phase == 'clear':
                db.execute('CREATE TABLE IF NOT EXISTS ' + NEXT + '(work_key TEXT PRIMARY KEY) WITHOUT ROWID')
                rows = [key for (key,) in db.execute('SELECT work_key FROM ' + NEXT + ' LIMIT ?', (PORTION,))]
                for start in range(0, len(rows), 500):
                    chunk = rows[start:start + 500]
                    db.execute('DELETE FROM ' + NEXT + ' WHERE work_key IN (' + ','.join('?' for _ in chunk) + ')', chunk)
                if not rows:
                    state.update(phase='origin', cursor=None, started=int(time.time()))
            elif phase == 'origin':
                # The works of the portion's rows as they are now.
                found = sorted(_works_of(db, origins))
                db.executemany('INSERT OR IGNORE INTO ' + NEXT + ' VALUES(?)', [(work,) for work in found])
                if len(entries) == SCAN:
                    state['cursor'] = [entries[-1][0], entries[-1][1]]
                else:
                    state.update(phase='explicit', cursor='')
            elif phase == 'explicit':
                wanted = keys('Хентай', policy_now(), allow_hidden=True)
                marks = ','.join('?' for _ in wanted) or "''"
                rows = db.execute('SELECT x.title_id,t.work_key FROM catalog_tags x JOIN catalog_titles t ON t.id=x.title_id '
                                  'WHERE x.tag_key IN (' + marks + ') AND x.title_id>? ORDER BY x.title_id LIMIT ?',
                                  [*wanted, state.get('cursor', ''), PORTION]).fetchall()
                db.executemany('INSERT OR IGNORE INTO ' + NEXT + ' VALUES(?)', [(work,) for work in sorted({w for _, w in rows if w})])
                if rows:
                    state['cursor'] = rows[-1][0]
                else:
                    state.update(phase='veto', cursor='')
            elif phase == 'veto':
                if veto_index(db, manga=True):
                    # Read from the veto index: a few thousand facts.
                    vetoed = sorted({key for (key,) in db.execute(
                        'SELECT DISTINCT t.work_key FROM catalog_tag_facts f JOIN catalog_titles t ON t.id=f.title_id '
                        'WHERE catalog_not_hentai(f.original)=1')})
                    done = True
                else:
                    # Probe the facts of the set's works, a portion at a time.
                    works = [key for (key,) in db.execute('SELECT work_key FROM ' + NEXT + ' WHERE work_key>? ORDER BY work_key LIMIT 2000',
                                                          (state.get('cursor', ''),))]
                    vetoed = sorted(set().union(*(_vetoed(db, works[n:n + 500]) for n in range(0, len(works), 500))))
                    done = not works
                    if works:
                        state['cursor'] = works[-1]
                for start in range(0, len(vetoed), 500):
                    chunk = vetoed[start:start + 500]
                    db.execute('DELETE FROM ' + NEXT + ' WHERE work_key IN (' + ','.join('?' for _ in chunk) + ')', chunk)
                if done:
                    state.update(phase='prune', cursor='')
            elif phase == 'prune':
                # Merge the new set into the served one by its difference, so
                # pages see at most one portion of changes at a time.
                rows = [key for (key,) in db.execute('SELECT work_key FROM ' + TABLE + ' WHERE work_key>? ORDER BY work_key LIMIT ?',
                                                     (state.get('cursor', ''), PORTION))]
                gone = [(key,) for key in rows if not db.execute('SELECT 1 FROM ' + NEXT + ' WHERE work_key=?', (key,)).fetchone()]
                db.executemany('DELETE FROM ' + TABLE + ' WHERE work_key=?', gone)
                if rows:
                    state['cursor'] = rows[-1]
                else:
                    state.update(phase='add', cursor='')
            elif phase == 'add':
                rows = [(key,) for (key,) in db.execute('SELECT work_key FROM ' + NEXT + ' WHERE work_key>? ORDER BY work_key LIMIT ?',
                                                        (state.get('cursor', ''), PORTION))]
                db.executemany('INSERT OR IGNORE INTO ' + TABLE + ' VALUES(?)', rows)
                if rows:
                    state['cursor'] = rows[-1][0]
                else:
                    db.execute('DROP TABLE IF EXISTS ' + NEXT)
                    state.update(phase='done', cursor='', served=stamp, finishedAt=int(time.time()))
            state['seconds'] = round(clock() - started, 2)
            _save(db, state)
    return True
