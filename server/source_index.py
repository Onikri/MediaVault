"""Stable public voice index; no CDN links, cookies, headers or playback capabilities."""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit

def directory():return Path(os.getenv('DISCOVERY_CACHE_DIR',str(Path(__file__).resolve().parent/'.codex-local'/'discovery')))

def database():
    folder=directory();folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    db=sqlite3.connect(folder/'index.sqlite',timeout=2)
    db.execute('CREATE TABLE IF NOT EXISTS voices(k TEXT PRIMARY KEY,payload TEXT NOT NULL,at REAL NOT NULL)')
    return db

def stable_url(value):
    try:
        url=urlsplit(value)
        return value if url.scheme=='https' and not url.username and not url.password and not url.path.lower().endswith(('.m3u8','.mp4','.mpd','.ts','.m4s')) else None
    except (ValueError,TypeError):return None

def save(key,result):
    voices=[]
    for voice in result.get('voices',[]):
        variants=[]
        for v in voice.get('variants',[]):
            url,source=stable_url(v.get('url')),stable_url(v.get('sourceUrl'))
            if not url or not source:continue
            row={k:v[k] for k in ('id','name','player','provider','providerName','language','kind','named') if k in v}
            row.update(url=url,sourceUrl=source)
            # Counts remain useful without persisting expiring episode URLs.
            row['episodes']=[{k:e[k] for k in ('number','season','title') if k in e} for e in (v.get('episodes') or [])[:1500]]
            variants.append(row)
        if variants:voices.append({**{k:voice[k] for k in ('id','name','kind','language','aliases') if k in voice},'variants':variants})
    if not voices:return
    payload={'voices':voices,'sources':[],'providers':[],'progress':0,'pending':True,'complete':False,'stale':True,'checkedAt':int(time.time())}
    try:
        with closing(database()) as db,db:
            db.execute('INSERT OR REPLACE INTO voices VALUES(?,?,?)',(hashlib.sha256(key.encode()).hexdigest(),json.dumps(payload,ensure_ascii=False),time.time()))
            db.execute('DELETE FROM voices WHERE at<?',(time.time()-86400,))
            db.execute('DELETE FROM voices WHERE k IN (SELECT k FROM voices ORDER BY at DESC LIMIT -1 OFFSET 256)')
    except (OSError,sqlite3.Error):pass

def load(key):
    try:
        with closing(database()) as db:row=db.execute('SELECT payload FROM voices WHERE k=? AND at>?',(hashlib.sha256(key.encode()).hexdigest(),time.time()-86400)).fetchone()
        return json.loads(row[0]) if row else None
    except (OSError,sqlite3.Error,ValueError):return None
