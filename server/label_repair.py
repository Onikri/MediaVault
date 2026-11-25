"""One-off reprojection of manga titles whose stored tag labels are Mac mojibake.

catalog_labels.readable_label now restores labels such as «–≤–μ–±» («веб»),
but the projection (catalog_tags, compiled work tags, title documents) was
written with the damaged spelling. The conductor drops
DATA_DIR/label-repair-pending.json; the tag-merge thread then

1. scans catalog_tag_facts in title order on a reader connection, PORTION
   facts at a time, and queues titles whose raw label mac_repair() changes;
2. adds the readable spelling of damaged catalog_vocabulary rows;
3. reprojects queued titles in batches of BATCH under a short store.lock.

Progress lives in label-repair-job.json and label_repair_queue, so a restart
continues where it stopped. Raw facts and vocabulary rows are never deleted.
"""
import json
import logging
import time

from catalog_labels import mac_repair

log = logging.getLogger('label_repair')
PENDING = 'label-repair-pending.json'
JOB = 'label-repair-job.json'
PORTION = 20000
BATCH = 100


def _directory():
    from tag_merge import directory
    return directory()


def read_job():
    try:
        return json.loads((_directory() / JOB).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _write(job):
    from tag_merge import _write
    _write(JOB, job)


def _queue(db):
    db.execute('CREATE TABLE IF NOT EXISTS label_repair_queue(title_id TEXT PRIMARY KEY) WITHOUT ROWID')


def status():
    job = read_job()
    fields = ('state', 'phase', 'scanned', 'queued', 'processed', 'vocabulary', 'startedAt', 'finishedAt', 'error')
    return {'labelRepair': {field: job[field] for field in fields if field in job}} if job else {}


def scan(store, job):
    from manga_discovery import catalogue_reader
    cursor = job.get('cursor', '')
    with catalogue_reader(store) as db:
        rows = db.execute('SELECT title_id,original FROM catalog_tag_facts WHERE title_id>? ORDER BY title_id LIMIT ?',
                          (cursor, PORTION)).fetchall()
        if len(rows) == PORTION:
            # Finish the last title so the next portion starts after it.
            last = rows[-1][0]
            rows += db.execute('SELECT title_id,original FROM catalog_tag_facts WHERE title_id=?', (last,)).fetchall()
    found = sorted({identity for identity, label in rows if mac_repair(label)})
    with store.lock, store.db:
        _queue(store.db)
        store.db.executemany('INSERT OR IGNORE INTO label_repair_queue VALUES(?)', [(identity,) for identity in found])
    job['scanned'] = job.get('scanned', 0) + len(rows)
    job['queued'] = job.get('queued', 0) + len(found)
    if rows:
        job['cursor'] = max(identity for identity, _ in rows)
    else:
        job.update(phase='vocabulary', cursor='')


def vocabulary(store, job):
    from content_vocabulary import add, bump
    with store.lock, store.db:
        rows = store.db.execute('SELECT label,source,category,kind FROM catalog_vocabulary').fetchall()
        added = sum(add(store.db, label, source, category, kind) for label, source, category, kind in rows if mac_repair(label))
        if added:
            bump(store.db)
    job.update(phase='apply', vocabulary=added)


def apply_batch(store):
    import manga_catalog_index
    from manga_tag_policy import current
    policy = current()
    with store.lock, store.db:
        _queue(store.db)
        ids = [identity for (identity,) in store.db.execute('SELECT title_id FROM label_repair_queue ORDER BY title_id LIMIT ?', (BATCH,))]
        works = set()
        for identity in ids:
            found = store.db.execute('SELECT metadata,work_key FROM catalog_titles WHERE id=?', (identity,)).fetchone()
            if found:
                manga_catalog_index.reproject_title(store.db, identity, found[0], policy, single=True)
                works.add(found[1])
        manga_catalog_index.refresh_work_tags(store.db, works)
        store.db.executemany('DELETE FROM label_repair_queue WHERE title_id=?', [(identity,) for identity in ids])
        remaining = store.db.execute('SELECT COUNT(*) FROM label_repair_queue').fetchone()[0]
        if not remaining:
            import content_catalog
            content_catalog.invalidate(store.db)
    return len(ids), remaining


def step(store):
    """Advance the repair by one unit; False when there is nothing to do."""
    pending = _directory() / PENDING
    job = read_job()
    if pending.exists() and job.get('state') != 'running':
        job = {'state': 'running', 'phase': 'scan', 'cursor': '', 'startedAt': int(time.time())}
        _write(job)
        pending.replace(pending.with_name('label-repair-applied.json'))
        return True
    if job.get('state') != 'running':
        return False
    try:
        if job['phase'] == 'scan':
            scan(store, job)
        elif job['phase'] == 'vocabulary':
            vocabulary(store, job)
        else:
            processed, remaining = apply_batch(store)
            job['processed'] = job.get('processed', 0) + processed
            if not remaining:
                import manga_catalog_index
                manga_catalog_index.expire_tag_cache()
                job.update(state='done', phase='done', finishedAt=int(time.time()))
                log.info('label repair: done, %d titles', job['processed'])
        _write(job)
    except Exception as error:
        log.exception('label repair failed')
        job.update(error=str(error)[:300])
        _write(job)
        raise
    return True
