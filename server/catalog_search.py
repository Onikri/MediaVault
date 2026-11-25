"""Full-text index of manga catalogue titles and aliases (SQLite FTS5, trigram).

browse(q=...) tests every word with LIKE '%word%' against search_text. A
leading % cannot use an index, so each search read the whole search_text
index and then every matching table row (metadata for the exact-name rank):
29 s for «naruto» on a cold VM disk.

* catalog_search: contentless FTS5 table, one document per catalog_titles row
  (same rowid). The document lists the row's normalized names (title, then
  aliases, exactly the parts search_text is built from) between '|'
  separators. trigram keeps the LIKE semantics: a query word of three or more
  characters matches every row whose search_text contains it as a substring
  (Cyrillic, Latin, digits; text and query are both normalized, so case and
  ё/е behave as before). '"|query|"' finds rows with an exact title or alias,
  the first rank of the old ordering, without reading metadata.
* catalog_search_rows: rowid -> work_key and the sort columns, so a search
  groups works and orders them without touching the 15 GB table.

upsert() and retire_removed() maintain both through update()/forget(). step()
fills an existing catalogue in short resumable portions in rowid order
(catalog_policy_state 'search-index': cursor and end). Rows above the cursor
and at most end are left to the fill; until it reports done, browse() keeps
the LIKE path.
"""
import json
import time

FTS = 'catalog_search'
ROWS = 'catalog_search_rows'
STATE = 'search-index'
# Bump when document() or the normalization behind search_text changes: the
# index is then dropped and refilled (a contentless delete must repeat the
# document exactly as it was inserted).
REVISION = 'trigram-names-v1'
PORTION = 2000
MIN_WORD = 3
COLUMNS = 'rowid,title,search_text,metadata,work_key,year,chapter_count,first_seen'


def document(title, data, search_text):
    """'|name|name|' for one row; the name parts cover search_text exactly."""
    from manga_catalog_index import _aliases
    from manga_tag_policy import normalize
    try:
        names = [name for name in (normalize(value) for value in [title, *_aliases(data)]) if name]
    except (AttributeError, TypeError):
        names = None
    if names is None or ' '.join(names)[:5000] != search_text:
        # An older search_text: keep its exact substring semantics.
        return '|' + search_text + '|'
    kept = []
    position = 0
    for name in names:
        if position >= 5000:
            break
        part = name[:5000 - position].strip()
        if part:
            kept.append(part)
        position += len(name) + 1
    return '|' + '|'.join(dict.fromkeys(kept)) + '|'


def initialize(conn):
    state = _state(conn)
    present = conn.execute('SELECT COUNT(*) FROM sqlite_master WHERE name IN (?,?)', (FTS, ROWS)).fetchone()[0] == 2
    if state.get('revision') != REVISION or not present:
        conn.execute('DROP TABLE IF EXISTS ' + FTS)
        conn.execute('DROP TABLE IF EXISTS ' + ROWS)
        state = {}
    conn.execute('CREATE VIRTUAL TABLE IF NOT EXISTS ' + FTS + " USING fts5(names, content='', columnsize=0, tokenize='trigram')")
    conn.execute('CREATE TABLE IF NOT EXISTS ' + ROWS + '(id INTEGER PRIMARY KEY,work_key TEXT NOT NULL,'
                 'year INTEGER,chapter_count INTEGER,first_seen REAL NOT NULL)')
    if state.get('revision') != REVISION:
        _reset(conn)
    elif state.get('phase') == 'done':
        # Rows inserted by an image without this module (a rollback): index
        # the rows above the last indexed one.
        top = conn.execute('SELECT MAX(rowid) FROM catalog_titles').fetchone()[0] or 0
        last = conn.execute('SELECT MAX(id) FROM ' + ROWS).fetchone()[0] or 0
        if top > last:
            _save(conn, {**state, 'phase': 'fill', 'cursor': last, 'end': top})


def _reset(conn):
    # A new catalogue starts complete; update() maintains it from the first row.
    end = conn.execute('SELECT MAX(rowid) FROM catalog_titles').fetchone()[0]
    _save(conn, {'revision': REVISION, 'phase': 'fill' if end else 'done', 'cursor': 0, 'end': end or 0})


def _state(conn):
    try:
        row = conn.execute('SELECT value FROM catalog_policy_state WHERE name=?', (STATE,)).fetchone()
        return json.loads(row[0]) if row else {}
    except Exception:
        return {}


def _save(conn, state):
    conn.execute('INSERT OR REPLACE INTO catalog_policy_state VALUES(?,?)', (STATE, json.dumps(state, sort_keys=True)))


def ready(conn):
    state = _state(conn)
    return state.get('phase') == 'done' and state.get('revision') == REVISION


def progress(conn):
    state = _state(conn)
    return {**state, 'ready': ready(conn)}


def _covers(state, rowid):
    """True when the index holds (or must now hold) this row."""
    return state.get('phase') == 'done' or rowid <= state.get('cursor', 0) or rowid > state.get('end', 0)


def _document(row):
    try:
        data = json.loads(row[3])
    except (TypeError, ValueError):
        data = {}
    return document(row[1], data if isinstance(data, dict) else {}, row[2])


def update(conn, changes):
    """changes: (rowid, before, after); before/after are COLUMNS rows without
    the rowid (title, search_text, metadata, work_key, year, chapter_count,
    first_seen) or None for an insert/delete."""
    state = _state(conn)
    if state.get('revision') != REVISION:
        return
    for rowid, before, after in changes:
        if not _covers(state, rowid):
            continue
        old = _document((rowid, *before)) if before else None
        new = _document((rowid, *after)) if after else None
        if old != new:
            if old is not None:
                conn.execute('INSERT INTO ' + FTS + '(' + FTS + ',rowid,names) VALUES(\'delete\',?,?)', (rowid, old))
            if new is not None:
                conn.execute('INSERT INTO ' + FTS + '(rowid,names) VALUES(?,?)', (rowid, new))
        if after:
            conn.execute('INSERT OR REPLACE INTO ' + ROWS + ' VALUES(?,?,?,?,?)', (rowid, *after[3:]))
        else:
            conn.execute('DELETE FROM ' + ROWS + ' WHERE id=?', (rowid,))


def forget(conn, identities):
    """Before catalog_titles rows are deleted by id."""
    if not conn.execute('SELECT 1 FROM sqlite_master WHERE name=?', (ROWS,)).fetchone():
        return
    identities = list(identities)
    for start in range(0, len(identities), 500):
        chunk = identities[start:start + 500]
        rows = conn.execute('SELECT ' + COLUMNS + ' FROM catalog_titles WHERE id IN (' + ','.join('?' * len(chunk)) + ')', chunk).fetchall()
        update(conn, [(row[0], tuple(row[1:]), None) for row in rows])


def _portion(db, cursor, end):
    return [tuple(row) for row in db.execute('SELECT ' + COLUMNS + ' FROM catalog_titles WHERE rowid>? AND rowid<=? '
                                             'ORDER BY rowid LIMIT ?', (cursor, end, PORTION))]


def step(store):
    """Advance the fill by one portion; False when there is nothing to do."""
    with store.lock:
        if not store.db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (ROWS,)).fetchone():
            return False
        state = _state(store.db)
        if state.get('revision') != REVISION or state.get('phase') != 'fill':
            return False
    # Read (and warm) the portion outside the lock; under it, the same rows are
    # read again from the page cache and only changed rows are rebuilt.
    from manga_discovery import catalogue_reader
    with catalogue_reader(store) as reader:
        prepared = {row[0]: (row, _document(row)) for row in _portion(reader, state['cursor'], state['end'])}
    with store.lock:
        db = store.db
        if _state(db) != state:
            return True
        with db:
            rows = _portion(db, state['cursor'], state['end'])
            documents = [(row[0], prepared[row[0]][1] if prepared.get(row[0], (None,))[0] == row else _document(row)) for row in rows]
            db.executemany('INSERT INTO ' + FTS + '(rowid,names) VALUES(?,?)', documents)
            db.executemany('INSERT OR REPLACE INTO ' + ROWS + ' VALUES(?,?,?,?,?)', [(row[0], *row[4:]) for row in rows])
            if len(rows) == PORTION:
                state['cursor'] = rows[-1][0]
            else:
                state.update(phase='done', cursor=state['end'], finishedAt=int(time.time()))
            state.setdefault('startedAt', int(time.time()))
            state['rows'] = state.get('rows', 0) + len(rows)
            _save(db, state)
    return True


def match_words(words):
    """FTS5 query for normalized words (letters and digits only)."""
    return ' AND '.join('"' + word + '"' for word in words)


def match_name(query):
    return '"|' + query.replace('"', '""') + '|"'
