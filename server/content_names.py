"""Names of the indexed rows that open directly in our player or reader.

A metadata card (AniList, OMDb, Shikimori …) has no page to play or read: the
client used to find one by a live title search on every site. The index often
holds the same work from a site we can open: RanobeLib books, the series pages
of HanimeTV, Hanime1, HentaiMama, WatchHentai and OHentai. Their rows are
grouped into other works (work_sql() keys by external IDs, which those sites
lack), so a card cannot reach them by its work key.

content_names maps the normalized names (title_identity.normalized: the
normalization of match_title) of those rows to their content_titles id:

* lookup(kind, names) -> the rows sharing a name with the card; callers then
  apply the live search's own identity rule (match_title, year, kind).
* ingest maintains it (update()); step() fills an existing catalogue once,
  one kind per portion, read outside the store lock (content_catalog_state
  'content-names'). Until the fill is done, lookups of an unfilled kind find
  only rows written since, which is never wrong, only incomplete.

Ingest merges names and never removes them, so the fill inserts with OR IGNORE
and never deletes what a concurrent ingest wrote.
"""
import json

TABLE = 'content_names'
STATE = 'content-names'
REVISION = 'playable-names-v1'
# kind -> providers whose index row is the page our player/reader opens.
PROVIDERS = {'anime': ('hanime', 'hanime1', 'hentaimama', 'watchhentai', 'ohentai'), 'ranobe': ('ranobelib',)}
MAX_NAMES = 60


def names(row):
    from title_identity import normalized
    values = [row.get('title'), *(row.get('aliases') or []), *((row.get('titles') or {}).values() if isinstance(row.get('titles'), dict) else [])]
    return list(dict.fromkeys(key for value in values if isinstance(value, str) and (key := normalized(value))))[:MAX_NAMES]


def playable(row):
    return isinstance(row, dict) and row.get('provider') in PROVIDERS.get(row.get('kind'), ())


def _state(conn):
    try:
        row = conn.execute('SELECT value FROM content_catalog_state WHERE name=?', (STATE,)).fetchone()
        return json.loads(row[0]) if row else {}
    except Exception:
        return {}


def _save(conn, state):
    conn.execute('INSERT OR REPLACE INTO content_catalog_state VALUES(?,?)', (STATE, json.dumps(state, sort_keys=True)))


def present(conn):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone())


def initialize(conn):
    """Create the table; an existing catalogue is filled by step()."""
    state = _state(conn)
    if state.get('revision') != REVISION:
        conn.execute('DROP TABLE IF EXISTS ' + TABLE)
    conn.execute('CREATE TABLE IF NOT EXISTS ' + TABLE + '(title_id TEXT NOT NULL,kind TEXT NOT NULL,name TEXT NOT NULL,'
                 'PRIMARY KEY(title_id,name)) WITHOUT ROWID')
    conn.execute('CREATE INDEX IF NOT EXISTS content_names_lookup ON ' + TABLE + '(kind,name)')
    if state.get('revision') != REVISION:
        empty = not conn.execute('SELECT 1 FROM content_titles LIMIT 1').fetchone()
        _save(conn, {'revision': REVISION, 'filled': sorted(PROVIDERS) if empty else []})


def update(conn, identity, row):
    """The names of one written content_titles row (ingest)."""
    if playable(row) and present(conn):
        conn.executemany('INSERT OR IGNORE INTO ' + TABLE + ' VALUES(?,?,?)', [(identity, row['kind'], name) for name in names(row)])


def pending(conn):
    state = _state(conn)
    if state.get('revision') != REVISION:
        return []
    return [kind for kind in sorted(PROVIDERS) if kind not in state.get('filled', [])]


def ready(conn, kind=None):
    left = pending(conn)
    return _state(conn).get('revision') == REVISION and (kind not in left if kind else not left)


def _rows(conn, kind):
    marks = ','.join('?' for _ in PROVIDERS[kind])
    return conn.execute("SELECT id,raw FROM content_titles WHERE kind=? AND json_extract(raw,'$.provider') IN (" + marks + ')',
                        (kind, *PROVIDERS[kind])).fetchall()


def step(store):
    """Fill one kind; False when there is nothing to do."""
    with store.lock:
        if not present(store.db):
            return False
        left = pending(store.db)
        if not left:
            return False
        kind = left[0]
    from manga_discovery import catalogue_reader
    with catalogue_reader(store) as reader:
        values = [(identity, kind, name) for identity, raw in _rows(reader, kind) for name in names(json.loads(raw))]
    with store.lock:
        db = store.db
        if pending(db)[:1] != [kind]:
            return True
        with db:
            db.executemany('INSERT OR IGNORE INTO ' + TABLE + ' VALUES(?,?,?)', values)
            state = _state(db)
            _save(db, {**state, 'filled': sorted({*state.get('filled', []), kind})})
    return True


def lookup(conn, kind, values, limit=40):
    """Rows of `kind` from playable providers that carry one of the names."""
    if kind not in PROVIDERS:
        return []
    try:
        if not present(conn):
            return []
    except Exception:
        return []
    from title_identity import normalized
    keys = list(dict.fromkeys(key for value in values if isinstance(value, str) and (key := normalized(value))))[:40]
    if not keys:
        return []
    marks = ','.join('?' for _ in keys)
    ids = [identity for (identity,) in conn.execute('SELECT DISTINCT title_id FROM ' + TABLE + ' WHERE kind=? AND name IN (' + marks + ') LIMIT ?',
                                                   (kind, *keys, limit))]
    if not ids:
        return []
    marks = ','.join('?' for _ in ids)
    rows = [json.loads(raw) for (raw,) in conn.execute('SELECT raw FROM content_titles WHERE id IN (' + marks + ')', ids)]
    return [row for row in rows if playable(row)]


def same_work(selected, row, *, year_required):
    """The live search's identity rule for an indexed row: match_title (IDs,
    kind, year, exact title or title and season) and, for video, the year
    check of source_discovery (a card's year must be confirmed by the row
    unless an external ID matched)."""
    from title_identity import match_title
    accepted, evidence = match_title(selected, row)
    if not accepted:
        return False, evidence
    if year_required and selected.get('year') and not row.get('year') and evidence != 'external_id':
        return False, 'unverified_year'
    return True, evidence


def matches(selected, kind, *, year_required, limit=8):
    """Indexed playable rows of the card's work, read-only; [] on any failure."""
    from title_identity import aliases
    try:
        from manga_discovery import catalogue_reader, manager
        with catalogue_reader(manager()) as db:
            rows = lookup(db, kind, aliases(selected))
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Could not read indexed playable sources')
        return []
    found = []
    for row in rows:
        accepted, evidence = same_work(selected, row, year_required=year_required)
        if accepted and (row.get('sourceUrl') or row.get('url')):
            found.append({**row, 'matchEvidence': evidence})
    return found[:limit]
