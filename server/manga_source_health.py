"""Short-lived, metadata-only reader health. Never store pages, cookies or stacks."""
import os,sqlite3,time
from pathlib import Path

FAILED={'unavailable','restricted'}
TTL=6*3600

def path():
    root=Path(os.getenv('DISCOVERY_CACHE_DIR',str(Path(__file__).resolve().parent/'.codex-local'/'discovery')))
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    return root/'manga-source-health.sqlite'

def connection():
    db=sqlite3.connect(path(),timeout=15)
    db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS health(id TEXT PRIMARY KEY,name TEXT,language TEXT,status TEXT,phase TEXT,message TEXT,checked REAL)')
    return db

def record(identity,name,language,status,phase,message=''):
    if status not in {'working','empty',*FAILED}:raise ValueError('Invalid reader status')
    # Callers supply fixed descriptions, never provider exception strings.
    db=connection()
    try:
        with db:db.execute('INSERT OR REPLACE INTO health VALUES(?,?,?,?,?,?,?)',(str(identity),str(name)[:120],str(language)[:8],status,phase,message[:300],time.time()))
    finally:db.close()

def states():
    db=connection()
    try:return {r['id']:dict(r) for r in db.execute('SELECT * FROM health WHERE checked>?',(time.time()-TTL,))}
    finally:db.close()

def blocked(identity,known=None):
    row=(states() if known is None else known).get(str(identity),{})
    return row.get('status') in FAILED

def report():
    rows=list(states().values())
    return {'sources':sorted(rows,key=lambda r:(r['language'],r['name'].casefold(),r['id'])),
            'checked':len(rows),'working':sum(r['status']=='working' for r in rows),
            'unavailable':sum(r['status'] in FAILED for r in rows),'unverified':sum(r['status']=='empty' for r in rows),'expiresAfter':TTL}
