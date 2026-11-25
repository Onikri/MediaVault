"""Owner-approved additive tag merges, applied in short resumable batches.

A full reindex rewrites millions of rows in one transaction under store.lock.
Here only titles whose tag projection changes are recomputed. The owner (or
the conductor) drops the new policy into DATA_DIR/tag-merge-pending.json:

1. The policy must only add rules, aliases and hidden labels. It is written
   together with the stored index revisions, exactly like save(); hiding
   takes effect immediately and new ingests already use the new keys.
2. A read-only snapshot finds the retained source labels whose key or
   category changed and queues the titles that carry them.
3. Batches of at most BATCH titles (and BUDGET seconds under store.lock)
   replace those titles' tag rows and their works' compiled tags, deleting
   each finished title from the queue in the same transaction.

Progress lives in tag-merge-job.json and the tag_merge_queue table, so a
restart continues where it stopped. Raw *_tag_facts are never deleted.
"""
import json
import logging
import os
import threading
import time
from pathlib import Path

from catalog_labels import readable_label
from manga_tag_policy import Policy, canonical_json, current

log = logging.getLogger('tag_merge')
PENDING = 'tag-merge-pending.json'
JOB = 'tag-merge-job.json'
PREVIOUS = 'tag-merge-previous.json'
BATCH = 200
BUDGET = .25
PAUSE = .5
POLL = 30
_started = threading.Lock()
_thread = None
stop = threading.Event()


def directory():
    return Path(os.getenv('DATA_DIR', '/data'))


def additive_problems(old, new):
    """Reasons a new policy is not a pure addition to the old one."""
    problems = []
    for field in ('schemaVersion', 'excludedTerms', 'excludedPrefixes', 'includeDiscovered'):
        if old.get(field) != new.get(field):
            problems.append('changed ' + field)
    hidden = set(new.get('hiddenTags', []))
    if any(value not in hidden for value in old.get('hiddenTags', [])):
        problems.append('hidden labels removed')
    rows = {row.get('key'): row for row in new.get('tags', []) if isinstance(row, dict)}
    for row in old.get('tags', []):
        other = rows.get(row['key'])
        if other is None:
            problems.append('rule removed: ' + row['key'])
            continue
        if other.get('label') != row.get('label') or other.get('category') != row.get('category'):
            problems.append('rule changed: ' + row['key'])
        if any(value not in other.get('aliases', []) for value in row.get('aliases', [])):
            problems.append('aliases removed: ' + row['key'])
        scoped = other.get('sourceAliases', {})
        if any(value not in scoped.get(domain, []) for domain, values in row.get('sourceAliases', {}).items() for value in values):
            problems.append('source aliases removed: ' + row['key'])
    return problems


def projection(policy, label, kind):
    """What the indexers store for one retained label: key and category."""
    from catalog_taxonomy import classify
    key = policy.identity(label) if policy.include_discovered else policy.key(label)
    return key, tuple((classify(label, field, kind, policy) or ('',))[0] for field in ('tags', 'genres'))


def changed(old, new, label, kind):
    value = readable_label(label)
    return bool(value) and projection(old, value, kind) != projection(new, value, kind)


def _write(name, value):
    from manga_tag_deploy import atomic_write
    atomic_write(directory() / name, canonical_json(value) + b'\n')


def read_job():
    try:
        return json.loads((directory() / JOB).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def status():
    import label_repair
    return {**_merge_status(), **label_repair.status()}


def _merge_status():
    job = read_job()
    if not job:
        return {}
    fields = ('state', 'phase', 'total', 'processed', 'labels', 'startedAt', 'finishedAt', 'error')
    value = {field: job[field] for field in fields if field in job}
    if 'total' in job:
        value['remaining'] = max(0, job['total'] - job.get('processed', 0))
    return {'tagMerge': value}


def _queue(db):
    db.execute('''CREATE TABLE IF NOT EXISTS tag_merge_queue(kind TEXT NOT NULL,work_key TEXT NOT NULL,
                  title_id TEXT NOT NULL,PRIMARY KEY(kind,work_key,title_id)) WITHOUT ROWID''')


def begin(store, path):
    """Validate and publish the pending policy; queue collection comes next."""
    from manga_tag_deploy import _update_lock, atomic_write
    import content_catalog
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        data = data.get('policy', data) if isinstance(data, dict) and 'schemaVersion' not in data else data
        policy = Policy(data)
    except (OSError, ValueError, TypeError, KeyError) as error:
        _write(JOB, {'state': 'rejected', 'error': 'Неверный файл правил: ' + str(error)[:200], 'finishedAt': int(time.time())})
        path.replace(path.with_name('tag-merge-rejected.json'))
        return
    with _update_lock, store.lock:
        previous = current()
        saved = {}
        try:
            saved = json.loads((directory() / PREVIOUS).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        if previous.revision == policy.revision:
            # Published before a restart: the job record may be missing.
            if saved.get('for') != policy.revision:
                _write(JOB, {'state': 'done', 'phase': 'done', 'total': 0, 'processed': 0, 'finishedAt': int(time.time())})
                path.replace(path.with_name('tag-merge-applied.json'))
                return
        else:
            problems = additive_problems(previous.data, policy.data)
            if problems:
                _write(JOB, {'state': 'rejected', 'error': 'Правила не только добавляют: ' + '; '.join(problems[:5]), 'finishedAt': int(time.time())})
                path.replace(path.with_name('tag-merge-rejected.json'))
                return
            _write(PREVIOUS, {'for': policy.revision, 'revision': previous.revision, 'policy': previous.data})
            target = directory() / 'manga-tag-policy.json'
            prior = target.read_bytes() if target.exists() else None
            try:
                with store.db:
                    _queue(store.db)
                    store.db.execute('DELETE FROM tag_merge_queue')
                    atomic_write(target, canonical_json(policy.data) + b'\n')
                    # The stored revisions say the index follows this policy, so
                    # initialize() never starts a full reindex; the queue closes
                    # the remaining difference.
                    store.db.execute('CREATE TABLE IF NOT EXISTS catalog_policy_state(name TEXT PRIMARY KEY,value TEXT NOT NULL)')
                    store.db.execute("INSERT OR REPLACE INTO catalog_policy_state VALUES('revision',?)", (policy.revision,))
                    store.db.execute("INSERT OR REPLACE INTO catalog_policy_state VALUES('commit','private-owner')")
                    content_catalog.invalidate(store.db)
                    store.db.execute("INSERT OR REPLACE INTO content_catalog_state VALUES('policy',?)", (policy.revision,))
            except BaseException:
                if prior is not None:
                    atomic_write(target, prior)
                elif target.exists():
                    target.unlink()
                raise
        _write(JOB, {'state': 'running', 'phase': 'collect', 'revision': policy.revision,
                     'previous': saved.get('revision') if previous.revision == policy.revision else previous.revision,
                     'startedAt': int(time.time())})
    path.replace(path.with_name('tag-merge-applied.json'))
    log.info('tag merge: policy %s published', policy.revision[:12])


def collect(store, job):
    """Queue every title that carries a label whose projection changed."""
    from manga_discovery import catalogue_reader
    from content_catalog import work_sql
    old = Policy(json.loads((directory() / PREVIOUS).read_text(encoding='utf-8'))['policy'])
    new = current()
    queued = []
    labels = 0
    with catalogue_reader(store) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {'catalog_tag_facts', 'catalog_titles'} <= tables:
            manga = {label for (label,) in db.execute('SELECT DISTINCT original FROM catalog_tag_facts') if changed(old, new, label, 'manga')}
            labels += len(manga)
            ids = {identity for identity, label in db.execute('SELECT title_id,original FROM catalog_tag_facts') if label in manga}
            ids = sorted(ids)
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                marks = ','.join('?' for _ in chunk)
                queued += [('manga', work, identity) for identity, work in db.execute('SELECT id,work_key FROM catalog_titles WHERE id IN (' + marks + ')', chunk)]
        if {'content_tag_facts', 'content_titles'} <= tables:
            content = sorted({label for label, kind in db.execute('SELECT DISTINCT original,kind FROM content_tag_facts') if changed(old, new, label, kind)})
            labels += len(content)
            ids = set()
            for start in range(0, len(content), 500):
                chunk = content[start:start + 500]
                marks = ','.join('?' for _ in chunk)
                ids.update(identity for (identity,) in db.execute('SELECT DISTINCT title_id FROM content_tag_facts WHERE original IN (' + marks + ')', chunk))
            ids = sorted(ids)
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                marks = ','.join('?' for _ in chunk)
                queued += [('content', work, identity) for identity, work in db.execute('SELECT id,' + work_sql('') + ' FROM content_titles WHERE id IN (' + marks + ')', chunk)]
    for start in range(0, len(queued), 2000):
        with store.lock, store.db:
            _queue(store.db)
            store.db.executemany('INSERT OR IGNORE INTO tag_merge_queue VALUES(?,?,?)', queued[start:start + 2000])
    job.update(phase='apply', total=len(queued), processed=0, labels=labels)
    _write(JOB, job)
    log.info('tag merge: %d changed labels, %d titles queued', labels, len(queued))


def apply_batch(store, policy=None, clock=time.monotonic):
    """Recompute one batch; returns (processed, remaining)."""
    import content_catalog
    import manga_catalog_index
    policy = policy or current()
    with store.lock, store.db:
        started = clock()
        _queue(store.db)
        rows = store.db.execute('SELECT kind,work_key,title_id FROM tag_merge_queue ORDER BY kind,work_key,title_id LIMIT ?', (BATCH,)).fetchall()
        done, works = [], {'manga': set(), 'content': set()}
        for kind, work, identity in rows:
            if kind == 'manga':
                found = store.db.execute('SELECT metadata,work_key FROM catalog_titles WHERE id=?', (identity,)).fetchone()
                if found:
                    manga_catalog_index.reproject_title(store.db, identity, found[0], policy, single=True)
                    works['manga'].update({work, found[1]})
            else:
                found = store.db.execute('SELECT raw,' + content_catalog.work_sql('') + ' FROM content_titles WHERE id=?', (identity,)).fetchone()
                if found:
                    content_catalog._index(store.db, identity, json.loads(found[0]), policy)
                    works['content'].update({work, found[1]})
            done.append((kind, work, identity))
            if clock() - started > BUDGET:
                break
        manga_catalog_index.refresh_work_tags(store.db, works['manga'])
        content_catalog.refresh_work_tags(store.db, works['content'])
        store.db.executemany('DELETE FROM tag_merge_queue WHERE kind=? AND work_key=? AND title_id=?', done)
        remaining = store.db.execute('SELECT COUNT(*) FROM tag_merge_queue').fetchone()[0]
        if not remaining:
            content_catalog.invalidate(store.db)
    return len(done), remaining


def step(store, pause=None):
    """Advance the job by one unit; False when there is nothing to do."""
    pending = directory() / PENDING
    job = read_job()
    if pending.exists() and job.get('state') != 'running':
        begin(store, pending)
        return True
    if job.get('state') != 'running':
        # Same thread, lower priority: the one-off label repair, then the
        # resumable fills of the materialized «Хентай» work set and of the
        # full-text title index.
        import catalog_search
        import hentai_works
        import label_repair
        if not (label_repair.step(store) or hentai_works.step(store) or catalog_search.step(store)):
            return False
        time.sleep(PAUSE if pause is None else pause)
        return True
    try:
        if job.get('phase') == 'collect':
            collect(store, job)
            return True
        processed, remaining = apply_batch(store)
        job['processed'] = job.get('processed', 0) + processed
        job['batches'] = job.get('batches', 0) + 1
        if not remaining:
            job.update(state='done', phase='done', finishedAt=int(time.time()), processed=job.get('total', job['processed']))
            log.info('tag merge: done, %d titles', job['processed'])
        _write(JOB, job)
        if job['batches'] % 50 == 0:
            log.info('tag merge: %d/%d titles', job['processed'], job.get('total', 0))
    except Exception as error:
        log.exception('tag merge failed')
        job.update(error=str(error)[:300])
        _write(JOB, job)
        raise
    time.sleep(PAUSE if pause is None else pause)
    return True


def watch(manager, root):
    # A data directory switch (tests) ends the watcher instead of applying a
    # job from one directory to another store.
    while not stop.is_set() and directory() == root:
        try:
            store = manager()
            while not stop.is_set() and directory() == root and not getattr(store, 'stopping', False) and step(store):
                pass
        except Exception:
            stop.wait(60)
            continue
        stop.wait(POLL)


def start(manager):
    global _thread
    if os.getenv('MEDIA_VAULT_DISABLE_WORKER') == '1':
        return
    with _started:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=watch, args=(manager, directory()), daemon=True, name='tag-merge')
            _thread.start()
