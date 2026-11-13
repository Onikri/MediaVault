"""Distinct source vocabulary, independent of owner visibility and title scans."""
import hashlib,json,threading
from urllib.parse import urlsplit
from manga_tag_policy import canonical_json,current,normalize

_cache={};_lock=threading.RLock()

def host(url):
    try:return urlsplit(url or '').hostname or ''
    except ValueError:return ''

def initialize(db):
    db.create_function('catalog_source_host',1,host,deterministic=True)
    db.execute('CREATE TABLE IF NOT EXISTS content_catalog_state(name TEXT PRIMARY KEY,value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS catalog_vocabulary(label TEXT NOT NULL,source TEXT NOT NULL,category TEXT NOT NULL,kind TEXT NOT NULL,PRIMARY KEY(label,source,category,kind))')
    if not db.execute("SELECT 1 FROM content_catalog_state WHERE name='vocabulary-v1'").fetchone():
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {'catalog_tag_facts','catalog_titles'}<=tables:
            db.execute("INSERT OR IGNORE INTO catalog_vocabulary SELECT DISTINCT f.original,catalog_source_host(t.source_url),f.category,'manga' FROM catalog_tag_facts f JOIN catalog_titles t ON t.id=f.title_id")
        if 'content_tag_facts' in tables:db.execute('INSERT OR IGNORE INTO catalog_vocabulary SELECT DISTINCT original,source,category,kind FROM content_tag_facts')
        db.execute("INSERT INTO content_catalog_state VALUES('vocabulary-v1','1')")
        bump(db)

def bump(db):
    db.execute("INSERT INTO content_catalog_state VALUES('vocabulary','1') ON CONFLICT(name) DO UPDATE SET value=CAST(value AS INTEGER)+1")

def add(db,label,source,category,kind):
    return db.execute('INSERT OR IGNORE INTO catalog_vocabulary VALUES(?,?,?,?)',(label,source,category,kind)).rowcount

def public(store):
    policy=current()
    with store.lock,store.db:
        initialize(store.db)
        generation=store.db.execute("SELECT value FROM content_catalog_state WHERE name='vocabulary'").fetchone()
        stamp=(id(store.db),policy.revision,generation[0] if generation else '')
        with _lock:
            if stamp in _cache:return _cache[stamp]
        data=policy.public()
        # Clients use an explicit public vocabulary, never private exclusion
        # terms or an unrestricted fallback on unfiltered remote metadata.
        if policy.include_discovered:
            known={row['key']:dict(row) for row in data['tags']}
            for label,source,category,_ in store.db.execute('SELECT label,source,category,kind FROM catalog_vocabulary ORDER BY label,source'):
                key=policy.key(label,source)
                if not key:continue
                if key not in known:known[key]={'key':key,'label':label,'aliases':[label]}
                if key not in policy.rules:
                    row=known[key]
                    if label not in row['aliases']:row['aliases'].append(label)
                    if category=='genres':row['genreHint']=True
            data['tags']=list(known.values())
        # The private switch is implemented by expanding observed, allowed
        # source labels; its private hidden list is never delivered publicly.
        data.pop('includeDiscovered',None);data.pop('hiddenTags',None)
        value={'revision':hashlib.sha256(canonical_json(data)).hexdigest(),'policy':data,'scope':'all'}
        with _lock:
            _cache.clear();_cache[stamp]=value
        return value
