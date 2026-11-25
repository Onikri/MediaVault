"""Materialized works of the browsed content kinds (anime, movie, tv, ranobe).

content_catalog.browse() grouped every content_titles row of a kind by the
work_sql() expression (json_extract over raw) and sorted the groups by
aggregates of raw: a temporary B-tree over all rows of the kind plus
COUNT(DISTINCT) for every page. On the VM a cold movie page with the client's
defaults (trending, «available») ran for more than 25 s.

content_works holds one row per work with exactly those aggregates, computed by
the same SQL expressions over the work's rows (refresh()):

* updated, year (RELEASE_YEAR), search (MIN), score, popularity: the columns of
  content_catalog.ORDERS, each with an index in that order, so a page is read
  in index order without grouping.
* trend_at = MAX(trendingAt). The trending order counts a row's trending value
  only for two hours; a work whose trend_at is older has 0 there. The few fresh
  works are computed live from their rows on every request.
* avail: 1 when a row is «available» (release_status.eligible), 2 when not but
  a row has a year, start date or first airing (time can make it available;
  checked live from its rows), 0 when nothing but a new write can change it.
  Every time test of eligible() has the form «a moment has passed», so 1 stays
  true until the rows change, and refresh() runs on every change.
* hentai: catalog_taxonomy.hentai_work_set() for this work (explicit tag or
  hentai origin, no «Не хентай» fact). The state's 'hentai' names the rules of
  the last complete pass; while a pass for new rules runs, every work carries
  either its previous or its new flag and «Хентай» pages keep using it.

content_work_stats counts works per (kind, avail, hentai) through triggers: the
exact total of an unfiltered page without a COUNT.

Maintenance: content_catalog.ingest() and refresh_work_tags() (ingest, tag
merges) call refresh() with the affected work keys; an unchanged row only
moves updated (touch()). step() fills an existing catalogue in resumable
portions of content_titles rowids (state row content_catalog_state
'content-works'); rebuild_work_tags() restarts the pass for the hentai flag
only. Until a first pass reports complete, browse keeps the old grouped
query.
"""
import hashlib
import json
import time

TABLE = 'content_works'
STATS = 'content_work_stats'
STATE = 'content-works'
KINDS = ('anime', 'movie', 'tv', 'ranobe')
# Bump when a column's definition changes: the table is rebuilt and refilled.
REVISION = 'content-works-v1'
PORTION = 2000
# The legacy origin expression index is dropped only by a release that has
# been answering for this long (the deploy's rollback target still uses it).
RETIRE_AFTER = 900
_started = time.monotonic()
FRESH = 7200
# A streamed page stops being cheaper than reading a tag's works and sorting
# them once about this many index entries must be tested.
STREAM_SCAN = 4000

INDEXES = {
    'updated': ('content_works_updated', 'w.updated DESC'),
    'new': ('content_works_new', 'w.year DESC'),
    'old': ('content_works_old', 'w.year IS NULL,w.year'),
    'title': ('content_works_title', 'w.search'),
    'score': ('content_works_score', 'w.score DESC,w.year DESC'),
    'trending': ('content_works_trending', 'w.popularity DESC,w.score DESC,w.year DESC'),
}
_signatures = {}


def _work(alias='t'):
    from content_catalog import work_sql
    return work_sql(alias)


def signature(policy=None):
    """The hentai flag's inputs: HENTAI rules and the keys of «Хентай»."""
    from catalog_taxonomy import HENTAI, keys
    from manga_tag_policy import current
    policy = policy or current()
    if policy.revision not in _signatures:
        if len(_signatures) > 16:
            _signatures.clear()
        wanted = keys('Хентай', policy, allow_hidden=True)
        _signatures[policy.revision] = hashlib.sha256(json.dumps([REVISION, HENTAI, wanted], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return _signatures[policy.revision]


def _present(conn):
    return bool(conn.execute('SELECT 1 FROM sqlite_master WHERE name=?', (TABLE,)).fetchone())


def _create(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS ' + TABLE + '(work_key TEXT PRIMARY KEY,kind TEXT NOT NULL,'
                 'updated INTEGER NOT NULL,year INTEGER,search TEXT NOT NULL,score REAL,popularity INTEGER,'
                 'trend_at INTEGER,avail INTEGER NOT NULL,hentai INTEGER NOT NULL) WITHOUT ROWID')
    order = lambda sql: sql.replace('w.', '')
    for name, columns in INDEXES.values():
        # avail and hentai make the order indexes covering for the default filters.
        conn.execute('CREATE INDEX IF NOT EXISTS ' + name + ' ON ' + TABLE + '(kind,' + order(columns) + ',work_key,avail,hentai)')
    conn.execute('CREATE INDEX IF NOT EXISTS content_works_fresh ON ' + TABLE + '(kind,trend_at) WHERE trend_at IS NOT NULL')
    conn.execute('CREATE TABLE IF NOT EXISTS ' + STATS + '(kind TEXT NOT NULL,avail INTEGER NOT NULL,hentai INTEGER NOT NULL,'
                 'works INTEGER NOT NULL,PRIMARY KEY(kind,avail,hentai)) WITHOUT ROWID')
    add = ('INSERT INTO ' + STATS + '(kind,avail,hentai,works) VALUES(NEW.kind,NEW.avail,NEW.hentai,1) '
           'ON CONFLICT(kind,avail,hentai) DO UPDATE SET works=works+1;')
    remove = 'UPDATE ' + STATS + ' SET works=works-1 WHERE kind=OLD.kind AND avail=OLD.avail AND hentai=OLD.hentai;'
    conn.execute('CREATE TRIGGER IF NOT EXISTS content_works_add AFTER INSERT ON ' + TABLE + ' BEGIN ' + add + ' END')
    conn.execute('CREATE TRIGGER IF NOT EXISTS content_works_remove AFTER DELETE ON ' + TABLE + ' BEGIN ' + remove + ' END')
    conn.execute('CREATE TRIGGER IF NOT EXISTS content_works_change AFTER UPDATE OF kind,avail,hentai ON ' + TABLE + ' BEGIN ' + remove + add + ' END')


def _state(conn):
    try:
        row = conn.execute('SELECT value FROM content_catalog_state WHERE name=?', (STATE,)).fetchone()
        return json.loads(row[0]) if row else {}
    except Exception:
        return {}


def _save(conn, state):
    conn.execute('INSERT OR REPLACE INTO content_catalog_state VALUES(?,?)', (STATE, json.dumps(state, sort_keys=True)))


def _top(conn):
    return conn.execute('SELECT MAX(rowid) FROM content_titles').fetchone()[0] or 0


def initialize(conn):
    """Create the tables and start (or resume) the fill when needed. Cheap:
    content_catalog.initialize() runs it on every ingest."""
    state = _state(conn)
    if state.get('revision') != REVISION:
        conn.execute('DROP TABLE IF EXISTS ' + TABLE)
        conn.execute('DROP TABLE IF EXISTS ' + STATS)
        _create(conn)
        empty = not conn.execute('SELECT 1 FROM content_titles LIMIT 1').fetchone()
        # A new catalogue starts complete; ingest maintains it from the first row.
        state = {'revision': REVISION, 'signature': signature(), 'cursor': 0, 'rows': 0,
                 'phase': 'done' if empty else 'fill', 'complete': empty, 'hentai': signature() if empty else '', 'top': _top(conn)}
        _save(conn, state)
        return
    _create(conn)
    if state.get('signature') != signature():
        _restart(conn, state)
    elif state.get('phase') == 'done' and _top(conn) > state.get('top', 0):
        # Rows written by an image without this module (a rollback): their
        # rowids are above the recorded top. Fill the tail before serving.
        _save(conn, {**state, 'phase': 'fill', 'cursor': state.get('top', 0), 'complete': False})


def _restart(conn, state):
    """New hentai inputs: recompute every work in the background; other
    columns stay valid and the previous flags are served meanwhile."""
    if not conn.execute('SELECT 1 FROM content_titles LIMIT 1').fetchone():
        _save(conn, {**state, 'signature': signature(), 'phase': 'done', 'cursor': 0, 'hentai': signature(), 'complete': True})
        return
    _save(conn, {**state, 'signature': signature(), 'phase': 'fill', 'cursor': 0})


def invalidate_hentai(conn):
    """Explicit tags were rebuilt (content_catalog.rebuild_work_tags)."""
    if _present(conn):
        state = _state(conn)
        if state.get('revision') == REVISION:
            _restart(conn, state)


def ready(conn):
    state = _state(conn)
    return state.get('revision') == REVISION and bool(state.get('complete'))


def hentai_ready(conn, policy=None):
    """The hentai flags are complete: for the current rules or, while a pass
    for new rules runs, for the previous ones."""
    return ready(conn) and bool(_state(conn).get('hentai'))


def hentai_current(conn, policy=None):
    """The hentai flags follow the current rules (no pass is recomputing them)."""
    state = _state(conn)
    return ready(conn) and state.get('phase') == 'done' and state.get('hentai') == signature(policy)


def progress(conn):
    state = _state(conn)
    return {**state, 'ready': ready(conn), 'hentaiReady': hentai_ready(conn), 'hentaiCurrent': hentai_current(conn)}


def aggregate_sql(conn, condition, policy=None, many=True):
    """(sql, leading args): one content_works row per work of the
    content_titles rows t matching condition, by the expressions of
    content_catalog.ORDERS, release_status.eligible() and
    catalog_taxonomy.hentai_work_set(). many: the hentai-tagged and «Не хентай»
    rows are read once from their indexes instead of probed row by row (the
    same sets; probes are cheaper for the few rows of one ingest)."""
    from catalog_taxonomy import keys as tag_keys, origin_sql, register_origin_functions, veto_index
    from content_catalog import RELEASE_YEAR
    from manga_tag_policy import current
    from release_status import eligible
    register_origin_functions(conn)
    wanted = tag_keys('Хентай', policy or current(), allow_hidden=True)
    video = eligible('t.raw', 'anime')
    other = eligible('t.raw', 'ranobe')
    dated = "json_extract(t.raw,'$.year') IS NOT NULL OR json_extract(t.raw,'$.startDate') IS NOT NULL OR json_extract(t.raw,'$.firstAiringAt') IS NOT NULL"
    tags = ','.join('?' for _ in wanted) or "''"
    if many:
        tagged = 't.id IN (SELECT x.title_id FROM content_tags x WHERE x.tag_key IN (' + tags + '))'
    else:
        tagged = 'EXISTS(SELECT 1 FROM content_tags x WHERE x.title_id=t.id AND x.tag_key IN (' + tags + '))'
    if many and veto_index(conn):
        vetoed = 't.id IN (SELECT f.title_id FROM content_tag_facts f WHERE catalog_not_hentai(f.original)=1)'
    else:
        # Without an index for the current labels: the row's own facts.
        vetoed = 'EXISTS(SELECT 1 FROM content_tag_facts f WHERE f.title_id=t.id AND catalog_not_hentai(f.original)=1)'
    work = _work('t')
    sql = ('SELECT ' + work + ',MIN(t.kind),MAX(t.updated),' + RELEASE_YEAR + ',MIN(t.search),'
           "MAX(CAST(json_extract(t.raw,'$.score') AS REAL)),MAX(CAST(json_extract(t.raw,'$.popularity') AS INTEGER)),"
           "MAX(CAST(json_extract(t.raw,'$.trendingAt') AS INTEGER)),"
           "CASE WHEN MAX(CASE WHEN (CASE WHEN t.kind IN ('anime','tv','movie') THEN (" + video + ') ELSE (' + other + ') END) THEN 1 ELSE 0 END)=1 THEN 1 '
           'WHEN MAX(CASE WHEN ' + dated + ' THEN 1 ELSE 0 END)=1 THEN 2 ELSE 0 END,'
           'CASE WHEN MAX(CASE WHEN ' + origin_sql('t') + '=1 OR ' + tagged + ' THEN 1 ELSE 0 END)=1 '
           'AND MAX(CASE WHEN ' + vetoed + ' THEN 1 ELSE 0 END)=0 THEN 1 ELSE 0 END '
           'FROM content_titles t WHERE ' + condition + ' GROUP BY ' + work)
    return sql, list(wanted)


def _aggregate(conn, keys, policy=None):
    """content_works rows (work_key, kind, updated, year, search, score,
    popularity, trend_at, avail, hentai) of these works, from their rows."""
    result = []
    for start in range(0, len(keys), 1000):
        chunk = keys[start:start + 1000]
        sql, args = aggregate_sql(conn, _work('t') + ' IN (' + ','.join('?' for _ in chunk) + ')', policy, many=len(chunk) > 40)
        result.extend(tuple(row) for row in conn.execute(sql, [*args, *chunk]))
    return result


def refresh(conn, keys, policy=None):
    """Recompute these works exactly from their rows (inside the writer's
    transaction); works without rows are removed."""
    keys = sorted({key for key in keys if isinstance(key, str) and key.split(':', 1)[0] in KINDS})
    if not keys or not _present(conn):
        return
    rows = _aggregate(conn, keys, policy)
    conn.executemany('INSERT INTO ' + TABLE + ' VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(work_key) DO UPDATE SET '
                     'kind=excluded.kind,updated=excluded.updated,year=excluded.year,search=excluded.search,'
                     'score=excluded.score,popularity=excluded.popularity,trend_at=excluded.trend_at,'
                     'avail=excluded.avail,hentai=excluded.hentai', rows)
    gone = sorted(set(keys) - {row[0] for row in rows})
    for start in range(0, len(gone), 500):
        chunk = gone[start:start + 500]
        conn.execute('DELETE FROM ' + TABLE + ' WHERE work_key IN (' + ','.join('?' for _ in chunk) + ')', chunk)


def touch(conn, changes):
    """(updated, work_key): an unchanged row was seen again at updated."""
    if changes and _present(conn):
        conn.executemany('UPDATE ' + TABLE + ' SET updated=MAX(updated,?) WHERE work_key=?', changes)


def advance(conn):
    """After a write by this code: rows up to MAX(rowid) are maintained."""
    if not _present(conn):
        return
    state = _state(conn)
    top = _top(conn)
    if state.get('revision') == REVISION and top > state.get('top', 0):
        _save(conn, {**state, 'top': top})


def _portion(conn, cursor):
    kinds = ','.join("'" + kind + "'" for kind in KINDS)
    return conn.execute('SELECT rowid,CASE WHEN kind IN (' + kinds + ') THEN ' + _work('') + ' END FROM content_titles '
                        'WHERE rowid>? ORDER BY rowid LIMIT ?', (cursor, PORTION)).fetchall()


def step(store, clock=time.monotonic):
    """Advance the fill by one portion; False when there is nothing to do."""
    with store.lock:
        if not _present(store.db):
            return False
        state = _state(store.db)
        if state.get('revision') != REVISION or state.get('phase') != 'fill':
            if state.get('revision') == REVISION and hentai_current(store.db) and clock() - _started >= RETIRE_AFTER:
                from catalog_taxonomy import retire_indexes
                with store.db:
                    return retire_indexes(store.db)
            return False
    # Read (and warm) the portion and its works outside the lock; under it the
    # same works are recomputed from the page cache.
    from manga_discovery import catalogue_reader
    with catalogue_reader(store) as reader:
        rows = _portion(reader, state.get('cursor', 0))
        keys = sorted({key for _, key in rows if key})
        _aggregate(reader, keys)
    with store.lock:
        db = store.db
        if _state(db) != state:
            return True
        with db:
            refresh(db, keys)
            state.setdefault('startedAt', int(time.time()))
            state['rows'] = state.get('rows', 0) + len(rows)
            if len(rows) == PORTION:
                state['cursor'] = rows[-1][0]
            else:
                # Later rows are maintained by ingest.
                state.update(phase='done', complete=True, hentai=state['signature'], cursor=0,
                             top=_top(db), finishedAt=int(time.time()))
            _save(db, state)
    return True


# ---- browse ---------------------------------------------------------------

def available(kind, work='w.work_key'):
    """«available» for the work in a content_works row aliased w."""
    from release_status import eligible
    # The work's own rows (the kind index would read every row of the kind);
    # +w.work_key drops the column's TEXT affinity so the expression index
    # serves the comparison.
    live = ('EXISTS(SELECT 1 FROM content_titles peer INDEXED BY content_work_identity WHERE ' + _work('peer') + '=+w.work_key AND peer.kind=? AND ' + eligible('peer.raw', kind) + ')')
    test = '(w.avail=1 OR (w.avail=2 AND ' + live + '))'
    if work == 'w.work_key':
        return test, [kind]
    return 'EXISTS(SELECT 1 FROM ' + TABLE + ' w WHERE w.work_key=' + work + ' AND ' + test + ')', [kind]


def _stats(conn, kind):
    return {(avail, hentai): works for avail, hentai, works in conn.execute('SELECT avail,hentai,works FROM ' + STATS + ' WHERE kind=?', (kind,))}


def _groups(conn, kind, policy, genre, tag, excludeGenre, excludeTag):
    """Filter groups as content_catalog's clauses() builds them, as tests of a
    content_works row w; None when a needed index is not ready."""
    from catalog_taxonomy import _signed, compiled_work_tags, is_hentai
    groups = []
    for field, wanted, negative in _signed(policy, kind, genre, tag, excludeGenre, excludeTag):
        if not wanted:
            if not negative:
                groups.append({'test': '0', 'args': [], 'negative': False, 'works': 0, 'set': None, 'exact': True, 'hentai': False, 'keys': 0})
            continue
        if not compiled_work_tags(conn):
            return None
        hentai = field == 'genres' and any(is_hentai(key, policy) for key in wanted)
        if hentai and not hentai_ready(conn, policy):
            return None
        ordinary = [key for key in wanted if not is_hentai(key, policy)] if hentai else list(wanted)
        tests, args, works, counted, found, largest = [], [], 0, 0, None, 0
        if ordinary:
            marks = ','.join('?' for _ in ordinary)
            tests.append('EXISTS(SELECT 1 FROM content_work_tags x WHERE x.kind=? AND x.work_key=w.work_key AND x.category=? AND x.tag_key IN (' + marks + '))')
            args = [kind, field, *ordinary]
            found = ('SELECT x.work_key FROM content_work_tags x WHERE x.kind=? AND x.category=? AND x.tag_key IN (' + marks + ')', list(args))
            for (count,) in conn.execute('SELECT works FROM content_tag_stats WHERE kind=? AND category=? AND tag_key IN (' + marks + ')', args):
                works += count
                counted += 1
                largest = max(largest, count)
        if hentai:
            tests.append('w.hentai=1')
            found = None
            flagged = sum(value for (_, flag), value in _stats(conn, kind).items() if flag == 1)
            works += flagged
            largest = max(largest, flagged)
        test = '(' + ' OR '.join(tests) + ')' if len(tests) > 1 else tests[0]
        groups.append({'test': ('NOT ' if negative else '') + test, 'args': args, 'negative': negative, 'works': works,
                       'set': found, 'exact': not hentai and counted <= 1, 'hentai': hentai and not ordinary, 'keys': counted,
                       # works counts each key (an upper bound of the OR); the largest key is a lower bound.
                       'lower': largest})
    return groups


def page(conn, *, kind, genre='', tag='', excludeGenre='', excludeTag='', status='', sort='updated', limit=60, offset=0, policy=None):
    """(work keys, total, exact) of a page without row-level filters, or None
    when the materialized works cannot answer it yet."""
    from manga_tag_policy import current
    policy = policy or current()
    if kind not in KINDS or not ready(conn):
        return None
    groups = _groups(conn, kind, policy, genre, tag, excludeGenre, excludeTag)
    if groups is None:
        return None
    if any(group['test'] == '0' for group in groups):
        # A filter value without keys matches nothing.
        return [], 0, True
    conditions, args = [], []
    for group in groups:
        conditions.append(group['test'])
        args.extend(group['args'])
    if status == 'available':
        clause, values = available(kind)
    else:
        from content_catalog import work_sql
        from release_status import condition
        clause, values = condition(status, table='content_titles', document='raw', work='w.work_key', peer_work=work_sql('peer'), kind=kind)
    if clause:
        conditions.append(clause)
        args.extend(values)
    sort = sort if sort in INDEXES else 'updated'
    index, order = INDEXES[sort]
    order += ',w.work_key'
    where = ''.join(' AND ' + condition for condition in conditions)

    stats = _stats(conn, kind)
    works = sum(stats.values()) or 1
    lead = min((group for group in groups if group['set'] and not group['negative']), key=lambda group: group['works'], default=None)
    driven = lead is not None and (offset + limit) * works / max(1, lead['works']) > STREAM_SCAN

    def select(skip, count, exclude=()):
        extra = ' AND w.work_key NOT IN (' + ','.join('?' for _ in exclude) + ')' if exclude else ''
        if driven:
            # A rare tag: its works by primary key, sorted once (+kind keeps
            # the planner off the order indexes).
            sql = ('SELECT w.work_key FROM ' + TABLE + ' w WHERE w.work_key IN (' + lead['set'][0] + ') AND +w.kind=?' + where + extra +
                   ' ORDER BY ' + order + ' LIMIT ? OFFSET ?')
            values = [*lead['set'][1], kind, *args, *exclude, count, skip]
        else:
            sql = ('SELECT w.work_key FROM ' + TABLE + ' w INDEXED BY ' + index + ' WHERE w.kind=?' + where + extra +
                   ' ORDER BY ' + order + ' LIMIT ? OFFSET ?')
            values = [kind, *args, *exclude, count, skip]
        return [key for (key,) in conn.execute(sql, values)]

    if sort != 'trending':
        keys = select(offset, limit)
    else:
        # Works with a fresh trending value lead (or trail when it is below 0
        # or NULL); every other work has 0 there and keeps the indexed order.
        from content_catalog import work_sql
        live = ("(SELECT MAX(CASE WHEN CAST(json_extract(t.raw,'$.trendingAt') AS INTEGER)>=unixepoch()-" + str(FRESH) +
                " THEN CAST(json_extract(t.raw,'$.trending') AS INTEGER) ELSE 0 END) FROM content_titles t INDEXED BY content_work_identity WHERE " + work_sql('t') + '=+w.work_key)')
        fresh = conn.execute('WITH w AS MATERIALIZED (SELECT w.work_key,w.popularity,w.score,w.year,' + live + ' AS v FROM ' + TABLE +
                             ' w INDEXED BY content_works_fresh WHERE w.kind=? AND w.trend_at IS NOT NULL AND w.trend_at>=unixepoch()-' + str(FRESH) + where +
                             ') SELECT work_key,CASE WHEN v>0 THEN 0 WHEN v=0 THEN 1 ELSE 2 END FROM w ORDER BY v DESC,' + order, [kind, *args]).fetchall()
        leading = [key for key, flag in fresh if flag == 0]
        trailing = [key for key, flag in fresh if flag == 2]
        keys = leading[offset:offset + limit]
        middle_offset = max(0, offset - len(leading))
        middle = select(middle_offset, limit - len(keys), leading + trailing) if len(keys) < limit else []
        keys += middle
        if len(keys) < limit and trailing:
            if middle:
                passed = middle_offset + len(middle)
            elif middle_offset:
                passed = conn.execute('SELECT COUNT(*) FROM ' + TABLE + ' w WHERE w.kind=?' + where + ' AND w.work_key NOT IN (' + ','.join('?' for _ in leading + trailing) + ')',
                                      [kind, *args, *leading, *trailing]).fetchone()[0]
            else:
                passed = 0
            skip = max(0, offset - len(leading) - passed)
            keys += trailing[skip:skip + limit - len(keys)]

    # Totals: exact from the counters when they answer the filter, else a
    # bounded count (manga_catalog_index._total: 0.1 s here, then cached
    # from a background count) with a lower bound meanwhile.
    known = lower = None
    hentai_only = [group for group in groups if group['hentai'] and not group['negative']]
    plain = not groups or (len(groups) == 1 and hentai_only)
    if plain:
        scope = {key: value for key, value in stats.items() if not hentai_only or key[1] == 1}
        if not status:
            known = sum(scope.values())
        elif status == 'available':
            lower = sum(value for key, value in scope.items() if key[0] == 1)
            if not any(value for key, value in scope.items() if key[0] == 2):
                known = lower
    elif not status and len(groups) == 1 and not groups[0]['negative'] and groups[0]['set'] and groups[0]['exact']:
        known = groups[0]['works']
    if known is not None:
        return keys, known, True
    if lower is None:
        # Every condition holds for at least its lower count of the kind's N
        # works, so all k hold for at least sum - (k-1)*N of them.
        total = sum(stats.values())
        bounds = [total - group['works'] if group['negative'] else group['lower'] for group in groups]
        if status:
            bounds.append(sum(value for key, value in stats.items() if key[0] == 1) if status == 'available' else 0)
        lower = max(0, sum(bounds) - (len(bounds) - 1) * total)
    from manga_catalog_index import _total
    counted = _total(conn, 'SELECT COUNT(*) FROM ' + TABLE + ' w WHERE w.kind=?' + where, [kind, *args], wait=not lower)
    if counted is not None:
        return keys, counted[0], True
    bound = offset + len(keys) + (1 if len(keys) == limit else 0)
    return keys, max(bound, lower), False
