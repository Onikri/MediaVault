"""Owner-approved compaction of catalogue_page_items (2026-11-25).

catalogue_page_items is not a snapshot of pages: it is the URL set (job, url)
of a listing's current run. INSERT OR IGNORE into it counts the run's unique
records (catalogue_jobs.records); nothing else reads it. Repeated and
unchanged pages are recognised by catalogue_page_fingerprints, which this
module never touches. Indexer.purge_items() drops a run's set when the run
ends and again before a restarted run reads page one.

Rows no run will read again: jobs that no longer exist, finished jobs (done,
partial, unsupported: a run that ended before purge_items existed) and jobs waiting for their first page. A set of a job in
progress (pages > 0, or running) stays.

The conductor drops DATA_DIR/page-cache-compact-pending.json; the tag-merge
thread then walks the jobs of the table in primary-key order and deletes at
most BATCH rows per transaction under store.lock, with a pause between
batches. Progress lives in page-cache-compact-job.json (cursor = last job
finished), so a restart continues. Freed pages go to SQLite's freelist and
are reused by later writes; the file only shrinks with VACUUM, which this
does not run.
"""
import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger('page_cache_compact')
PENDING = 'page-cache-compact-pending.json'
JOB = 'page-cache-compact-job.json'
BATCH = 5000
MIN_BATCH = 500
BUDGET = .25
FINISHED = ('done', 'partial', 'unsupported')


def directory():
    return Path(os.getenv('DATA_DIR', '/data'))


def read_job():
    try:
        return json.loads((directory() / JOB).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _write(job):
    from manga_tag_deploy import atomic_write
    atomic_write(directory() / JOB, json.dumps(job, sort_keys=True).encode() + b'\n')


def status():
    job = read_job()
    fields = ('state', 'deleted', 'jobs', 'kept', 'startedAt', 'finishedAt', 'error')
    return {'pageCacheCompact': {field: job[field] for field in fields if field in job}} if job else {}


def unneeded(db, job_id):
    """No run reads this job's URL set again."""
    row = db.execute('SELECT state,pages FROM catalogue_jobs WHERE id=?', (job_id,)).fetchone()
    if row is None:
        return True
    state, pages = row[0], row[1]
    return state in FINISHED or (state != 'running' and not pages)


def step(store, clock=time.monotonic):
    """One batch; False when no compaction is pending or running."""
    pending = directory() / PENDING
    job = read_job()
    if pending.exists() and job.get('state') != 'running':
        job = {'state': 'running', 'cursor': '', 'deleted': 0, 'jobs': 0, 'kept': 0, 'batch': BATCH, 'startedAt': int(time.time())}
        _write(job)
        pending.replace(pending.with_name('page-cache-compact-accepted.json'))
        log.info('page cache compaction: started')
        return True
    if job.get('state') != 'running':
        return False
    batch = int(job.get('batch') or BATCH)
    with store.lock:
        db = store.db
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='catalogue_page_items'").fetchone():
            found = None
        else:
            found = db.execute('SELECT job FROM catalogue_page_items WHERE job>? ORDER BY job LIMIT 1', (job.get('cursor', ''),)).fetchone()
        if found is None:
            job.update(state='done', finishedAt=int(time.time()))
            _write(job)
            log.info('page cache compaction: done, %d rows of %d jobs, %d kept', job['deleted'], job['jobs'], job['kept'])
            return True
        key = found[0]
        started = clock()
        with db:
            # The job's state is read in the transaction that deletes, so a
            # run cannot start between the test and the delete.
            if unneeded(db, key):
                deleted = db.execute('DELETE FROM catalogue_page_items WHERE rowid IN '
                                     '(SELECT rowid FROM catalogue_page_items WHERE job=? LIMIT ?)', (key, batch)).rowcount
            else:
                deleted = None
        held = clock() - started
    if deleted is None:
        job.update(cursor=key, kept=job.get('kept', 0) + 1)
    else:
        job['deleted'] = job.get('deleted', 0) + deleted
        if deleted < batch:
            job.update(cursor=key, jobs=job.get('jobs', 0) + 1)
        if held > BUDGET:
            job['batch'] = max(MIN_BATCH, batch // 2)
    _write(job)
    return True
