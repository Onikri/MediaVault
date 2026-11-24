"""Read-only audit of the catalogue indexer on the VM (step A1 of «Быстрый каталог»).

Run inside the importer container, never against a TaskStore:
  ssh mediavault-vm 'sudo -n docker exec -i -w /app oracle-importer-1 nice -n 19 python -' < scripts/catalog/indexer-audit.py
  ... python - --probe host1 host2   # at most 20 GET requests, one per host (home page only)
  ... python - --hygiene             # A2 retry/purge/junk-title counters (no network)

Every query runs on a separate mode=ro connection with query_only=ON and in its
own short read transaction so the auditor never pins the WAL for long.
"""
import json, os, sqlite3, sys, time
from collections import Counter, defaultdict

sys.path[:0] = ['/app', '/app/server']
DB = os.getenv('DATA_DIR', '/data') + '/manga-discovery.sqlite'
NOW = time.time()


def connect():
    db = sqlite3.connect('file:' + DB + '?mode=ro', uri=True, timeout=5)
    db.execute('PRAGMA query_only=ON')
    return db


def timed(db, sql, args=()):
    start = time.perf_counter()
    rows = db.execute(sql, args).fetchall()
    return rows, round(time.perf_counter() - start, 3)


def out(title, value):
    print('## ' + title)
    if isinstance(value, (list, tuple)):
        for row in value[:40]:
            print('  ' + str(row)[:300])
    else:
        print('  ' + str(value)[:2000])


def audit():
    from catalogue_indexer import CLAIMABLE, BASE_KINDS, HOST_SLOTS, BRIDGE_SLOTS
    db = connect()
    out('files', {p: os.path.getsize(DB + p) for p in ('', '-wal', '-shm') if os.path.exists(DB + p)})
    out('pragma', {k: db.execute('PRAGMA ' + k).fetchone()[0] for k in
                   ('page_size', 'page_count', 'freelist_count', 'journal_mode', 'wal_autocheckpoint',
                    'auto_vacuum', 'synchronous', 'journal_size_limit')})
    out('workers env', os.getenv('MEDIA_VAULT_CATALOGUE_WORKERS', '12 (default)'))
    out('jobs columns', [r[1] for r in db.execute('PRAGMA table_info(catalogue_jobs)')])

    # 1. Queue shape.
    rows, t = timed(db, 'SELECT kind,state,COUNT(*),SUM(due<=?),SUM(pages),SUM(records) FROM catalogue_jobs GROUP BY kind,state ORDER BY 3 DESC', (NOW,))
    out('jobs kind/state/count/due_now/pages/records (%.2fs)' % t, rows)
    rows, t = timed(db, "SELECT kind,(json_extract(spec,'$.term') IS NOT NULL) term,state,COUNT(*) FROM catalogue_jobs WHERE kind IN ('bridge','lib','html','remanga','anilist','books') GROUP BY 1,2,3 ORDER BY 4 DESC")
    out('base vs term jobs', rows)
    rows, _ = timed(db, "SELECT host,kind,COUNT(*) FROM catalogue_jobs WHERE state='running' GROUP BY 1,2 ORDER BY 3 DESC")
    out('running by host (HOST_SLOTS=%d BRIDGE_SLOTS=%d)' % (HOST_SLOTS, BRIDGE_SLOTS), rows)
    rows, _ = timed(db, "SELECT host,COUNT(*),ROUND(AVG(?-due)/60,1),ROUND(MAX(?-due)/3600,1) FROM catalogue_jobs WHERE state IN ('queued','retry','done','partial') AND due<=? GROUP BY host ORDER BY 2 DESC", (NOW, NOW, NOW))
    out('overdue by host: host,count,avg_wait_min,max_wait_h', rows[:25])
    out('hosts with overdue work', len(rows))

    # The claim path: these run under claim_lock for every single claim.
    rows, t = timed(db, 'SELECT DISTINCT host FROM catalogue_jobs WHERE ' + CLAIMABLE, (NOW,))
    out('claim: DISTINCT host scan -> %d hosts in %.3fs' % (len(rows), t), [r[0] for r in rows][:30])
    plan = db.execute('EXPLAIN QUERY PLAN SELECT DISTINCT host FROM catalogue_jobs WHERE ' + CLAIMABLE, (NOW,)).fetchall()
    out('claim plan', [p[-1] for p in plan])
    base_sql = ('SELECT id FROM catalogue_jobs INDEXED BY catalogue_jobs_kind WHERE kind IN (' + ','.join('?' * len(BASE_KINDS)) +
                ") AND json_extract(spec,'$.term') IS NULL AND " + CLAIMABLE + ' ORDER BY updated,id')
    rows, t = timed(db, base_sql, (*BASE_KINDS, NOW))
    out('claim: base-kind turn -> %d rows in %.3fs' % (len(rows), t), '')
    out('jobs total', db.execute('SELECT COUNT(*) FROM catalogue_jobs').fetchone()[0])

    # Progress of each base crawl (pages walked, records, expected, cursor).
    rows, _ = timed(db, "SELECT host,kind,state,pages,records,expected,substr(cursor,1,40),ROUND((?-updated)/60) FROM catalogue_jobs WHERE json_extract(spec,'$.term') IS NULL AND kind IN ('lib','bridge','remanga','html','anilist','kinobox','books','omdb') ORDER BY records DESC", (NOW,))
    out('base crawls host,kind,state,pages,records,expected,cursor,min_since_update', rows[:40])
    out('base crawls total', len(rows))

    # 2. Retries.
    rows, _ = timed(db, "SELECT kind,host,error,COUNT(*),MAX(attempts),ROUND(MIN(due-?)/60),ROUND(MAX(due-?)/60) FROM catalogue_jobs WHERE state='retry' GROUP BY 1,2,3 ORDER BY 4 DESC", (NOW, NOW))
    out('retry kind,host,error,count,max_attempts,next_due_min..max', rows)
    rows, _ = timed(db, "SELECT host,json_extract(spec,'$.source.lang'),json_extract(spec,'$.source.name'),json_extract(cursor,'$.route'),COUNT(*),MAX(attempts),SUM(json_extract(spec,'$.term') IS NOT NULL) FROM catalogue_jobs WHERE state='retry' AND kind LIKE 'bridge%' GROUP BY 1,2,3,4 ORDER BY 5 DESC")
    out('bridge retry host,lang,source,route,count,max_attempts,term_jobs', rows)

    # 3. Storage.
    stat1 = {}
    try:
        stat1 = {tbl + '/' + (idx or ''): stat.split()[0] for tbl, idx, stat in db.execute('SELECT tbl,idx,stat FROM sqlite_stat1')}
    except sqlite3.Error as error:
        stat1 = {'sqlite_stat1': str(error)}
    out('sqlite_stat1 (rows at last ANALYZE)', sorted(stat1.items())[:60])
    try:
        rows, t = timed(db, "SELECT name,SUM(pgsize),COUNT(*) FROM dbstat WHERE name IN ('catalogue_jobs','catalogue_page_fingerprints','sqlite_autoindex_catalogue_page_fingerprints_1','catalogue_tag_targets') AND aggregate=0 GROUP BY name")
        out('dbstat small tables bytes,pages (%.2fs)' % t, rows)
    except sqlite3.Error as error:
        out('dbstat', str(error))
    sample = db.execute('SELECT AVG(length(job)+length(url)),COUNT(*) FROM (SELECT job,url FROM catalogue_page_items WHERE rowid>(SELECT MAX(rowid)-20000 FROM catalogue_page_items))').fetchone()
    top = db.execute('SELECT MAX(rowid) FROM catalogue_page_items').fetchone()[0]
    out('page_items avg payload bytes, sample, max rowid', (sample, top))
    rows, t = timed(db, 'SELECT j.state,COUNT(*) FROM (SELECT job,COUNT(*) n FROM catalogue_page_items WHERE rowid>? GROUP BY job) p LEFT JOIN catalogue_jobs j ON j.id=p.job GROUP BY 1', (top - 200000,))
    out('page_items (last 200k rowids) by owning job state (%.2fs)' % t, rows)
    rows, _ = timed(db, "SELECT COUNT(*),SUM(records),MAX(records) FROM catalogue_jobs WHERE state IN ('done','partial','unsupported')")
    out('finished jobs count,records,max', rows)

    # 1b. Throughput from the cards themselves.
    for span in (3600, 86400):
        rows, t = timed(db, 'SELECT source_id,COUNT(*) FROM catalog_titles INDEXED BY catalog_titles_source WHERE updated>=? GROUP BY source_id ORDER BY 2 DESC', (NOW - span,))
        out('manga rows updated in %dh by source_id (total %d, %.1fs)' % (span // 3600, sum(r[1] for r in rows), t), rows[:20])
    rows, t = timed(db, 'SELECT SUM(first_seen>=?),SUM(first_seen>=?),COUNT(*),COUNT(DISTINCT work_key) FROM catalog_titles INDEXED BY catalog_titles_works', (NOW - 3600, NOW - 86400))
    out('manga new_1h,new_24h,total,works (%.1fs)' % t, rows)
    rows = db.execute('SELECT source_id,first_seen>=? FROM catalog_titles INDEXED BY catalog_titles_recent ORDER BY updated DESC LIMIT 20000', (NOW - 86400,)).fetchall()
    by = defaultdict(Counter)
    for sid, new in rows:
        by[sid]['new' if new else 'refresh'] += 1
    out('last 20k manga writes: source -> new/refresh', sorted(((s, dict(c)) for s, c in by.items()), key=lambda x: -sum(x[1].values()))[:15])
    rows, _ = timed(db, 'SELECT kind,COUNT(*),SUM(updated>=?),SUM(updated>=?) FROM content_titles GROUP BY kind', (NOW - 3600, NOW - 86400))
    out('content kind,total,upd_1h,upd_24h', rows)
    rows, _ = timed(db, "SELECT COALESCE(json_extract(raw,'$.provider'),substr(id,1,instr(id,':')-1)),COUNT(*),SUM(json_extract(raw,'$.adult')=1) FROM content_titles WHERE kind='anime' GROUP BY 1 ORDER BY 2 DESC")
    out('anime by provider,count,adult', rows)
    rows, _ = timed(db, "SELECT kind,state,pages,records,cursor,error FROM catalogue_jobs WHERE kind LIKE 'anilist%' AND json_extract(spec,'$.term') IS NULL")
    out('anilist base jobs', rows)

    # 4. Language scope.
    rows, _ = timed(db, "SELECT lower(replace(json_extract(spec,'$.source.lang'),'_','-')) l,COUNT(*),SUM(NOT (" + CLAIMABLE.split(' AND state')[0] + ")) FROM catalogue_jobs WHERE kind LIKE 'bridge%' GROUP BY l ORDER BY 2 DESC")
    out('bridge jobs by lang,count,out_of_scope', rows)
    try:
        from suwayomi_bridge import configured, sources
        from manga_profile_languages import included
        installed = sources() if configured() else []
        langs = Counter(s.get('lang') for s in installed)
        out('suwayomi installed sources %d; by lang' % len(installed), sorted(langs.items(), key=lambda x: -x[1]))
        out('suwayomi excluded by PROFILE_LANGUAGES', sum(n for l, n in langs.items() if not included(l)))
    except Exception as error:
        out('suwayomi sources', repr(error)[:200])
    try:
        from manga_source_coverage import SOURCES
        out('SOURCES by integration', Counter(s[2] for s in SOURCES).most_common())
    except Exception as error:
        out('SOURCES', repr(error)[:200])
    rows, _ = timed(db, "SELECT host,json_extract(spec,'$.reason') FROM catalogue_jobs WHERE kind='unsupported'")
    out('unsupported jobs %d' % len(rows), rows[:20])


def writes():
    """Write-path shape: page cadence, slot occupancy, index fan-out, hot works."""
    db = connect()
    # Every upsert() call stamps one `updated` value on all rows of its page,
    # so distinct values approximate committed manga pages.
    stamps = [r[0] for r in db.execute('SELECT DISTINCT updated FROM catalog_titles INDEXED BY catalog_titles_recent WHERE updated>=? ORDER BY updated', (NOW - 3600,))]
    gaps = sorted(b - a for a, b in zip(stamps, stamps[1:]))
    pct = lambda p: round(gaps[int(p * (len(gaps) - 1))], 3) if gaps else None
    out('manga pages committed in last 1h', len(stamps))
    out('gap between page writes p10/p50/p90/max s', (pct(.1), pct(.5), pct(.9), pct(1)))
    rows = db.execute('SELECT updated,COUNT(*) FROM catalog_titles INDEXED BY catalog_titles_recent WHERE updated>=? GROUP BY updated', (NOW - 600,)).fetchall()
    sizes = sorted(n for _, n in rows)
    out('rows per page last 10 min p50/p90/max', (sizes[len(sizes) // 2], sizes[int(.9 * (len(sizes) - 1))], sizes[-1]) if sizes else None)
    samples = []
    for _ in range(10):
        samples.append(db.execute("SELECT COUNT(*),SUM(kind LIKE 'bridge%') FROM catalogue_jobs WHERE state='running'").fetchone())
        time.sleep(1.5)
    out('running jobs (total,bridge) sampled 10x/1.5s', samples)
    out('indexes', db.execute("SELECT tbl_name,COUNT(*) FROM sqlite_master WHERE type='index' AND tbl_name IN ('catalog_titles','catalog_tags','catalog_tag_facts','catalog_work_tags','catalog_vocabulary','content_titles','content_tags','content_tag_facts') GROUP BY 1").fetchall())
    out('triggers', [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")])
    rows, t = timed(db, 'SELECT work_key,COUNT(*) FROM catalog_titles INDEXED BY catalog_titles_works GROUP BY work_key ORDER BY 2 DESC LIMIT 8')
    out('largest works (titles per work_key) %.1fs' % t, rows)
    for table in ('catalog_tags', 'catalog_tag_facts', 'catalog_work_tags', 'catalog_tag_stats', 'catalog_vocabulary', 'content_tags', 'catalogue_tag_targets'):
        try:
            out('max rowid/count ' + table, db.execute('SELECT MAX(rowid) FROM ' + table).fetchone()[0])
        except sqlite3.Error:
            out('count ' + table, db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0])
    out('avg metadata bytes (last 2000 rows)', db.execute('SELECT AVG(length(metadata)),AVG(length(search_text)) FROM (SELECT metadata,search_text FROM catalog_titles INDEXED BY catalog_titles_recent ORDER BY updated DESC LIMIT 2000)').fetchone())
    rows = db.execute("SELECT host,substr(json_extract(spec,'$.url'),1,90),json_extract(spec,'$.term.label'),attempts FROM catalogue_jobs WHERE kind='html' AND state='retry' ORDER BY attempts DESC LIMIT 6").fetchall()
    out('html retry samples', rows)
    rows = db.execute("SELECT host,kind,state,COUNT(*) FROM catalogue_jobs WHERE host IN (SELECT DISTINCT host FROM catalogue_jobs WHERE state IN ('queued','retry','done','partial') AND due<? AND due<?) AND NOT (" + __import__('catalogue_indexer').CLAIMABLE.split(' AND state')[0] + ") GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 12", (NOW - 86400, NOW)).fetchall()
    out('stale out-of-scope jobs by host', rows)
    rows = db.execute("SELECT kind,(json_extract(spec,'$.term') IS NOT NULL),COUNT(*),SUM(pages) FROM catalogue_jobs WHERE state IN ('done','partial') AND updated>=? GROUP BY 1,2 ORDER BY 4 DESC", (NOW - 86400,)).fetchall()
    out('jobs finished in 24h: kind,term,count,pages (recrawled each 6h)', rows)


def hygiene():
    """A2 before/after: job states, failure classes, stalled jobs, leftover page items
    and stored server-error titles (counted only, never deleted). Index lookups only."""
    from catalogue_indexer import JUNK_TITLE_PREFIXES, JUNK_TITLES
    from manga_tag_policy import normalize
    db = connect()
    out('job states', sorted(Counter(r[0] for r in db.execute('SELECT state FROM catalogue_jobs')).items(), key=lambda x: -x[1]))
    columns = {r[1] for r in db.execute('PRAGMA table_info(catalogue_jobs)')}
    failed = db.execute("SELECT host,kind,state,attempts,error" + (",reason" if 'reason' in columns else ",''") +
                        " FROM catalogue_jobs WHERE state IN ('retry','stalled')").fetchall()
    out('failure classes', Counter((r[4].split(':', 1)[0] if ':' in r[4] else r[4])[:60] for r in failed).most_common(25))
    out('stalled jobs %d' % sum(r[2] == 'stalled' for r in failed), [r[:5] for r in failed if r[2] == 'stalled'][:30])
    out('attempts>=48 still retry', sum(r[2] == 'retry' and r[3] >= 48 for r in failed))
    done = [key for (key,) in db.execute("SELECT id FROM catalogue_jobs WHERE state IN ('done','partial')")]
    left = sum(bool(db.execute('SELECT 1 FROM catalogue_page_items WHERE job=? LIMIT 1', (key,)).fetchone()) for key in done)
    out('page_items: max rowid / finished jobs with leftover items', (db.execute('SELECT MAX(rowid) FROM catalogue_page_items').fetchone()[0], left, len(done)))
    junk = {}
    for phrase in (*JUNK_TITLE_PREFIXES, *JUNK_TITLES):
        key = normalize(phrase)
        if not key:
            continue
        exact = key in JUNK_TITLES or phrase in JUNK_TITLES
        sql = 'SELECT COUNT(*) FROM catalog_titles INDEXED BY catalog_titles_works WHERE ' + (
            'work_key=?' if exact else 'work_key>=? AND work_key<?')
        junk[phrase] = db.execute(sql, (key,) if exact else (key, key + '\U0010ffff')).fetchone()[0]
    out('stored error-page titles (not deleted) total %d' % sum(junk.values()), sorted(((k, v) for k, v in junk.items() if v), key=lambda x: -x[1]))


def probe(hosts):
    import httpx
    from content_sources import UA
    for host in hosts[:20]:
        try:
            start = time.perf_counter()
            r = httpx.get('https://' + host + '/', headers={'User-Agent': UA, 'Accept': 'text/html'}, timeout=15, follow_redirects=True)
            body = r.text[:20000].lower()
            marks = [m for m in ('cloudflare', 'just a moment', 'captcha', 'ddos-guard', 'access denied', 'parked', 'domain is for sale') if m in body]
            title = body.split('<title>', 1)[1].split('</title>', 1)[0].strip()[:60] if '<title>' in body else ''
            print(host, r.status_code, str(r.url)[:80], len(r.content), round(time.perf_counter() - start, 1), marks, repr(title))
        except Exception as error:
            print(host, 'ERR', type(error).__name__, str(error)[:120])


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--probe':
        probe(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == '--native':
        # Which "bridge" jobs never touch Suwayomi yet still share BRIDGE_SLOTS.
        from manga_native_sources import for_source
        tally = Counter()
        for spec, state in connect().execute("SELECT spec,state FROM catalogue_jobs WHERE kind LIKE 'bridge%'"):
            spec = json.loads(spec)
            tally[('native' if for_source(spec.get('source') or {}) else 'suwayomi', spec['type'], state)] += 1
        out('bridge jobs by route,kind,state', sorted(tally.items(), key=lambda x: -x[1]))
    elif len(sys.argv) > 1 and sys.argv[1] == '--lockhold':
        # upsert() stamps rows when it starts (inside store.lock); the job row is
        # stamped at the end of the same transaction. The gap is the write time
        # under the shared lock, before the commit's fsync.
        db = connect();holds = []
        for sid, ended in db.execute("SELECT json_extract(spec,'$.source.id'),updated FROM catalogue_jobs WHERE kind='bridge' AND records>0 AND updated>=? ORDER BY updated DESC LIMIT 60", (NOW - 900,)).fetchall():
            began = db.execute('SELECT MAX(updated) FROM catalog_titles INDEXED BY catalog_titles_source WHERE source_id=? AND updated<=?', (str(sid), ended)).fetchone()[0]
            if began and ended - began < 30:holds.append(round(ended - began, 3))
        holds.sort()
        out('write hold s (n=%d) p10/p50/p90/max' % len(holds), [holds[int(p * (len(holds) - 1))] for p in (.1, .5, .9, 1)] if holds else None)
    elif len(sys.argv) > 1 and sys.argv[1] == '--writes':
        writes()
    elif len(sys.argv) > 1 and sys.argv[1] == '--hygiene':
        hygiene()
    else:
        audit()
