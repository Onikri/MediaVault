"""Materialized «Хентай» work set for the manga catalogue.

The genre is derived per work: a work is hentai when one of its source rows
comes from a hentai origin or carries an explicit hentai tag, unless a row of
the work has a «Не хентай» source fact (catalog_taxonomy.hentai_work_set).
Evaluating that union for 400 000 works on every page took about a minute on
the VM. catalog_hentai_works stores the same set, one row per work:

* refresh() recomputes given works exactly; manga_catalog_index calls it from
  refresh_work_tags(), so every upsert, tag merge and retirement keeps it.
* step() fills an existing catalogue in short resumable portions (state row
  catalog_policy_state 'hentai-works'); until it reports done for the current
  rules, queries keep the old union.
"""
import hashlib
import json
import time
from array import array
from bisect import bisect_left

TABLE = 'catalog_hentai_works'
STATE = 'hentai-works'
PORTION = 20000
_origins = {}


def signature(policy):
    from catalog_taxonomy import HENTAI, keys
    wanted = keys('Хентай', policy, allow_hidden=True)
    return hashlib.sha256(json.dumps([HENTAI, wanted], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def initialize(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS ' + TABLE + '(work_key TEXT PRIMARY KEY) WITHOUT ROWID')
    from manga_tag_policy import current
    if _state(conn).get('signature') != signature(current()):
        _reset(conn)


def _reset(conn):
    from manga_tag_policy import current
    # A new catalogue starts complete; refresh() maintains it from the first row.
    empty = not conn.execute('SELECT 1 FROM catalog_titles LIMIT 1').fetchone()
    _save(conn, {'signature': signature(current()), 'phase': 'done' if empty else 'clear', 'cursor': ''})


def _state(conn):
    try:
        row = conn.execute('SELECT value FROM catalog_policy_state WHERE name=?', (STATE,)).fetchone()
        return json.loads(row[0]) if row else {}
    except Exception:
        return {}


def _save(conn, state):
    conn.execute('INSERT OR REPLACE INTO catalog_policy_state VALUES(?,?)', (STATE, json.dumps(state, sort_keys=True)))


def ready(conn, policy):
    state = _state(conn)
    return state.get('phase') == 'done' and state.get('signature') == signature(policy)


def invalidate(conn):
    """The explicit-tag projection was rebuilt: refill the set in the background."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone():
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
        found.difference_update(key for (key,) in conn.execute(
            'SELECT DISTINCT t.work_key FROM catalog_titles t JOIN catalog_tag_facts f ON f.title_id=t.id '
            'WHERE t.work_key IN (' + marks + ') AND catalog_not_hentai(f.original)=1', chunk))
    return found


def refresh(conn, works, policy=None):
    works = sorted({work for work in works if work})
    if not works or not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone():
        return
    from manga_tag_policy import current
    found = members(conn, works, policy or current())
    for start in range(0, len(works), 500):
        chunk = works[start:start + 500]
        conn.execute('DELETE FROM ' + TABLE + ' WHERE work_key IN (' + ','.join('?' for _ in chunk) + ')', chunk)
    conn.executemany('INSERT OR IGNORE INTO ' + TABLE + ' VALUES(?)', [(work,) for work in sorted(found)])


def _load_origins(store, stamp):
    """Rowids of hentai-origin rows, read once per run from the covering origin
    expression index on a reader connection, outside store.lock. Rows added
    later are covered by refresh() at their upsert."""
    if _origins.get('stamp') == stamp:
        return
    from manga_discovery import catalogue_reader
    with catalogue_reader(store) as db:
        value = array('q', sorted(rowid for (rowid,) in db.execute(
            "SELECT rowid FROM catalog_titles WHERE catalog_hentai_origin(provider,source_url,'manga')=1")))
    _origins.update(stamp=stamp, value=value)


def _contains(values, value):
    index = bisect_left(values, value)
    return index < len(values) and values[index] == value


def step(store, clock=time.monotonic):
    """Advance the fill by one portion; False when there is nothing to do."""
    from manga_tag_policy import current
    from catalog_taxonomy import keys, register_origin_functions
    with store.lock:
        state = _state(store.db)
    if state.get('phase') == 'origin':
        _load_origins(store, state.get('signature', '') + ':' + str(state.get('started', '')))
    with store.lock:
        db = store.db
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone():
            return False
        state = _state(db)
        policy = current()
        stamp = signature(policy)
        if state.get('signature') != stamp:
            state = {'signature': stamp, 'phase': 'clear', 'cursor': ''}
        phase = state.get('phase')
        if phase == 'done':
            return False
        register_origin_functions(db)
        started = clock()
        with db:
            if phase == 'clear':
                rows = [key for (key,) in db.execute('SELECT work_key FROM ' + TABLE + ' LIMIT ?', (PORTION,))]
                for start in range(0, len(rows), 500):
                    chunk = rows[start:start + 500]
                    db.execute('DELETE FROM ' + TABLE + ' WHERE work_key IN (' + ','.join('?' for _ in chunk) + ')', chunk)
                if not rows:
                    state.update(phase='origin', cursor='')
            elif phase == 'origin':
                if _origins.get('stamp') != stamp + ':' + str(state.get('started', '')):
                    return True
                origins = _origins['value']
                rows = db.execute('SELECT work_key,rowid FROM catalog_titles INDEXED BY catalog_titles_works '
                                  'WHERE work_key>? ORDER BY work_key LIMIT ?', (state.get('cursor', ''), PORTION)).fetchall()
                # Never split one work across portions.
                if len(rows) == PORTION:
                    last = rows[-1][0]
                    rows += db.execute('SELECT work_key,rowid FROM catalog_titles INDEXED BY catalog_titles_works '
                                       'WHERE work_key=?', (last,)).fetchall()
                found = sorted({work for work, rowid in rows if _contains(origins, rowid)})
                db.executemany('INSERT OR IGNORE INTO ' + TABLE + ' VALUES(?)', [(work,) for work in found])
                if rows:
                    state['cursor'] = max(work for work, _ in rows)
                else:
                    _origins.clear()
                    state.update(phase='explicit', cursor='')
            elif phase == 'explicit':
                wanted = keys('Хентай', policy, allow_hidden=True)
                marks = ','.join('?' for _ in wanted) or "''"
                rows = db.execute('SELECT x.title_id,t.work_key FROM catalog_tags x JOIN catalog_titles t ON t.id=x.title_id '
                                  'WHERE x.tag_key IN (' + marks + ') AND x.title_id>? ORDER BY x.title_id LIMIT ?',
                                  [*wanted, state.get('cursor', ''), PORTION]).fetchall()
                db.executemany('INSERT OR IGNORE INTO ' + TABLE + ' VALUES(?)', [(work,) for work in sorted({w for _, w in rows})])
                if rows:
                    state['cursor'] = rows[-1][0]
                else:
                    state.update(phase='veto', cursor='')
            elif phase == 'veto':
                vetoed = sorted({key for (key,) in db.execute(
                    'SELECT DISTINCT t.work_key FROM catalog_tag_facts f JOIN catalog_titles t ON t.id=f.title_id '
                    'WHERE catalog_not_hentai(f.original)=1')})
                for start in range(0, len(vetoed), 500):
                    chunk = vetoed[start:start + 500]
                    db.execute('DELETE FROM ' + TABLE + ' WHERE work_key IN (' + ','.join('?' for _ in chunk) + ')', chunk)
                state.update(phase='done', cursor='', finishedAt=int(time.time()), seconds=round(clock() - started, 2))
            state.setdefault('started', int(time.time()))
            _save(db, state)
    return True
