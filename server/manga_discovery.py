"""Metadata-only global manga search: one SQLite queue, four shared workers.

No page bytes, credentials or account library data are stored here. Upstream
search responses are candidates, not claims that chapters are readable.
"""
from pathlib import Path
from urllib.parse import urljoin
import hashlib,json,os,re,secrets,sqlite3,threading,time,unicodedata
from source_parser import SourceError,public_url
import suwayomi_bridge as bridge

LANGUAGES={'all','ru','en','ja','ko'}

def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC',value).casefold().split())

def source_list(language='all',query=''):
    if language not in LANGUAGES:raise ValueError('Выбери язык источников.')
    query=normalize(query)[:80]
    rows=[{'id':str(s['id']),'name':s['name'],'language':s['lang'],'adult':bool(s.get('isNsfw'))}
          for s in bridge.sources() if s.get('lang') in LANGUAGES-{'all'} and (language=='all' or s['lang']==language)]
    rows.sort(key=lambda s:(s['language'],s['name'].casefold(),s['id']))
    return {'sources':[s for s in rows if query in normalize(s['name'])],'total':len(rows)}

def result_row(source,row):
    identity=row.get('id');title=row.get('title')
    if isinstance(identity,bool) or not isinstance(identity,int) or not 0<identity<10**10 or not isinstance(title,str) or not title.strip():return None
    canonical=cover=''
    try:canonical=public_url(row.get('realUrl') or urljoin(source.get('baseUrl',''),row.get('url','')),resolve_dns=False)
    except (SourceError,TypeError,ValueError):pass
    # Only genuinely public thumbnail metadata is exposed. Internal Suwayomi
    # thumbnails need Basic auth and are never presented as public image URLs.
    thumb=row.get('thumbnailUrl') or ''
    if isinstance(thumb,str) and thumb.startswith('https://'):
        try:cover=public_url(thumb,resolve_dns=False)
        except SourceError:pass
    language=source['lang'];sid=str(source['id'])
    return {'id':f'suwayomi:{sid}:{identity}','kind':'manga','title':title.strip()[:500],'aliases':[title.strip()[:500]],
            'provider':'suwayomi:'+sid,'providerName':source['name'],'sourceId':sid,'sourceUrl':canonical,
            'url':bridge.reference(identity),'sourceURL':bridge.reference(identity),'sourceOnly':True,
            'language':language,'cover':cover,'format':'manhwa' if language=='ko' else 'manga','ids':{},'genres':[],'tags':[],
            'adult':bool(source.get('isNsfw'))}

def search_source(source,query):
    client=bridge.Client()
    try:
        data=client.get('/source/'+str(source['id'])+'/search',{'searchTerm':query,'pageNum':1},timeout=4)
        rows=data.get('mangaList',[])
        if not isinstance(rows,list):raise ValueError('Invalid source result')
        return [value for row in rows[:40] if isinstance(row,dict) and (value:=result_row(source,row))]
    finally:client.close()

class SearchLimit(ValueError):pass
class SearchMissing(LookupError):pass

class Discovery:
    def __init__(self,directory,*,workers=4,cache_ttl=900,max_jobs=8,per_owner=2,fetch=None,clock=time.time,start_workers=True):
        self.path=Path(directory)/'manga-discovery.sqlite';self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db=sqlite3.connect(self.path,check_same_thread=False);self.path.chmod(0o600)
        self.db.row_factory=sqlite3.Row;self.lock=threading.RLock();self.condition=threading.Condition(self.lock)
        self.clock=clock;self.cache_ttl=cache_ttl;self.max_jobs=max_jobs;self.per_owner=per_owner
        self.fetch=fetch or search_source;self.stopping=False;self.threads=[]
        with self.db:
            self.db.executescript('''
              PRAGMA journal_mode=DELETE;
              CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,owner TEXT NOT NULL,signature TEXT NOT NULL,
                query TEXT NOT NULL,language TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,expires REAL NOT NULL,dispatched REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS jobs_owner_signature ON jobs(owner,signature,state,expires);
              CREATE TABLE IF NOT EXISTS work(job TEXT NOT NULL,source_id TEXT NOT NULL,source TEXT NOT NULL,state TEXT NOT NULL,
                results TEXT NOT NULL DEFAULT '[]',cached INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(job,source_id));
              CREATE INDEX IF NOT EXISTS work_queue ON work(state,job);
              CREATE TABLE IF NOT EXISTS query_cache(query TEXT NOT NULL,source_id TEXT NOT NULL,results TEXT NOT NULL,expires REAL NOT NULL,
                PRIMARY KEY(query,source_id));
              CREATE TABLE IF NOT EXISTS titles(id TEXT PRIMARY KEY,source_id TEXT NOT NULL,language TEXT NOT NULL,title_norm TEXT NOT NULL,
                metadata TEXT NOT NULL,updated REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS titles_source_name ON titles(source_id,title_norm);
              CREATE INDEX IF NOT EXISTS titles_language_name ON titles(language,title_norm);
            ''')
            self.db.execute("UPDATE jobs SET state='interrupted',updated=? WHERE state='running'",(self.clock(),))
            self.db.execute("UPDATE work SET state='cancelled' WHERE state IN ('queued','running')")
        if start_workers:
            for i in range(max(1,min(workers,4))):
                thread=threading.Thread(target=self._worker,daemon=True,name='manga-discovery-'+str(i));self.threads.append(thread);thread.start()

    def _prune(self,now):
        self.db.execute('DELETE FROM work WHERE job IN (SELECT id FROM jobs WHERE expires<?)',(now,))
        self.db.execute('DELETE FROM jobs WHERE expires<?',(now,))
        self.db.execute('DELETE FROM query_cache WHERE expires<?',(now,))
        self.db.execute('DELETE FROM titles WHERE updated<?',(now-7*86400,))
        self.db.execute('DELETE FROM titles WHERE id IN (SELECT id FROM titles ORDER BY updated DESC LIMIT -1 OFFSET 50000)')
        self.db.execute('DELETE FROM query_cache WHERE rowid IN (SELECT rowid FROM query_cache ORDER BY expires DESC LIMIT -1 OFFSET 10000)')
        stale=[r[0] for r in self.db.execute("SELECT id FROM jobs WHERE state!='running' ORDER BY updated DESC LIMIT -1 OFFSET 32")]
        for identity in stale:
            self.db.execute('DELETE FROM work WHERE job=?',(identity,));self.db.execute('DELETE FROM jobs WHERE id=?',(identity,))

    def start(self,owner,query,language='all',source_ids=None,refresh=False):
        if not isinstance(query,str) or not 2<=len(query.strip())<=160 or any(unicodedata.category(c)=='Cc' for c in query):raise ValueError('Укажи запрос от 2 до 160 символов.')
        query=' '.join(query.split());key=normalize(query)
        if language not in LANGUAGES:raise ValueError('Выбери язык источников.')
        if source_ids is not None and (not isinstance(source_ids,list) or not 1<=len(source_ids)<=1000 or any(not isinstance(v,str) or not re.fullmatch(r'[1-9][0-9]{0,19}',v) for v in source_ids)):raise ValueError('Выбери хотя бы один установленный источник.')
        # Persist only public source identity, never an upstream response's
        # optional preference/authentication fields.
        active=[{k:s.get(k) for k in ('id','name','lang','baseUrl','isNsfw')} for s in bridge.sources() if s.get('lang') in LANGUAGES-{'all'}]
        installed={str(s['id']) for s in active}
        if source_ids and any(v not in installed for v in source_ids):raise ValueError('Выбранный источник не установлен. Обнови каталог источников.')
        selected=list({str(s['id']):s for s in active if (language=='all' or s['lang']==language) and (not source_ids or str(s['id']) in source_ids)}.values())
        preferred='ru' if re.search(r'[а-яё]',query,re.I) else 'ko' if re.search(r'[가-힣]',query) else 'ja' if re.search(r'[ぁ-ヿ一-鿿]',query) else 'en'
        selected.sort(key=lambda s:(s['lang']!=preferred,s['lang'],s['name'].casefold(),str(s['id'])))
        signature=hashlib.sha256(json.dumps([key,language,[str(s['id']) for s in selected]],ensure_ascii=False).encode()).hexdigest()
        now=self.clock()
        with self.condition,self.db:
            self._prune(now)
            hit=self.db.execute("SELECT id FROM jobs WHERE owner=? AND signature=? AND (state='running' OR state='done' AND updated>? AND ?=0) AND expires>? ORDER BY created DESC LIMIT 1",(owner,signature,now-self.cache_ttl,int(bool(refresh)),now)).fetchone()
            if hit:return self._snapshot(owner,hit['id'])
            if self.db.execute("SELECT count(*) FROM jobs WHERE state='running'").fetchone()[0]>=self.max_jobs or self.db.execute("SELECT count(*) FROM jobs WHERE state='running' AND owner=?",(owner,)).fetchone()[0]>=self.per_owner:raise SearchLimit('Поиск уже выполняется. Дождись результата или останови предыдущий.')
            identity=secrets.token_urlsafe(24)
            self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',(identity,owner,signature,query,language,'running' if selected else 'done',now,now,now+86400,now))
            for source in selected:
                sid=str(source['id']);hit=None if refresh else self.db.execute('SELECT results FROM query_cache WHERE query=? AND source_id=? AND expires>?',(key,sid,now)).fetchone()
                # A stale metadata index is useful immediately, but is not counted
                # as a fresh provider response and never suppresses its refresh.
                seed=self._indexed(key,sid) if not hit else json.loads(hit['results'])
                self.db.execute('INSERT INTO work VALUES(?,?,?,?,?,?)',(identity,sid,json.dumps(source,ensure_ascii=False),'done' if hit else 'queued',json.dumps(seed,ensure_ascii=False),int(bool(hit))))
            if selected and self.db.execute("SELECT count(*) FROM work WHERE job=? AND state='queued'",(identity,)).fetchone()[0]==0:self.db.execute("UPDATE jobs SET state='done' WHERE id=?",(identity,))
            self.condition.notify_all()
            return self._snapshot(owner,identity)

    def _indexed(self,key,sid):
        # Parameterized escaped LIKE supports raw Japanese/Korean substring
        # matching as well as Latin/Cyrillic prefixes without SQL/FTS syntax.
        escaped=key.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        return [json.loads(r[0]) for r in self.db.execute("SELECT metadata FROM titles WHERE source_id=? AND title_norm LIKE ? ESCAPE '\\' ORDER BY updated DESC LIMIT 40",(sid,'%'+escaped+'%'))]

    def _snapshot(self,owner,identity):
        job=self.db.execute('SELECT * FROM jobs WHERE id=? AND owner=? AND expires>?',(identity,owner,self.clock())).fetchone()
        if not job:raise SearchMissing('Поиск не найден или срок хранения истёк.')
        results={};providers=[];complete=failed=cached=0
        for row in self.db.execute('SELECT * FROM work WHERE job=? ORDER BY source_id',(identity,)):
            source=json.loads(row['source']);items=json.loads(row['results'])
            for value in items:results[value['id']]=value
            providers.append({'id':row['source_id'],'name':source['name'],'language':source['lang'],'state':row['state'],'count':len(items),'cached':bool(row['cached'])})
            complete+=row['state'] in {'done','unavailable','cancelled'};failed+=row['state']=='unavailable';cached+=row['cached']
        key=normalize(job['query']);tokens=key.split()
        def rank(value):
            title=normalize(value['title']);return (title!=key,not title.startswith(key),key not in title,-sum(t in title for t in tokens),title,value['id'])
        ordered=sorted(results.values(),key=rank)
        return {'id':identity,'state':job['state'],'query':job['query'],'language':job['language'],
                'progress':{'completed':complete,'total':len(providers),'failed':failed,'cached':cached},
                'results':ordered[:3000],'resultCount':len(ordered),'truncated':len(ordered)>3000,'providers':providers,'updated':job['updated'],'expiresAt':job['expires']}

    def status(self,owner,identity):
        with self.lock:return self._snapshot(owner,identity)

    def cancel(self,owner,identity):
        with self.condition,self.db:
            self._snapshot(owner,identity)
            self.db.execute("UPDATE jobs SET state='cancelled',updated=? WHERE id=? AND state='running'",(self.clock(),identity))
            self.db.execute("UPDATE work SET state='cancelled' WHERE job=? AND state IN ('queued','running')",(identity,))
            self.condition.notify_all();return self._snapshot(owner,identity)

    def _take(self):
        row=self.db.execute("SELECT w.*,j.query,j.owner FROM work w JOIN jobs j ON j.id=w.job WHERE w.state='queued' AND j.state='running' ORDER BY j.dispatched,j.created,w.rowid LIMIT 1").fetchone()
        if row:
            with self.db:
                self.db.execute("UPDATE work SET state='running' WHERE job=? AND source_id=?",(row['job'],row['source_id']))
                self.db.execute('UPDATE jobs SET dispatched=? WHERE id=?',(self.clock(),row['job']))
        return row

    def _worker(self):
        while True:
            with self.condition:
                if self.stopping:return
                row=self._take()
                if row is None:self.condition.wait(timeout=1);continue
            try:
                values=self.fetch(json.loads(row['source']),row['query']);state='done'
                if not isinstance(values,list):raise ValueError('Invalid result')
            except Exception:values=[];state='unavailable'
            now=self.clock()
            with self.condition,self.db:
                job=self.db.execute('SELECT state FROM jobs WHERE id=?',(row['job'],)).fetchone()
                if not job or job['state']!='running':continue
                encoded=json.dumps(values,ensure_ascii=False)
                self.db.execute('UPDATE work SET state=?,results=? WHERE job=? AND source_id=?',(state,encoded,row['job'],row['source_id']))
                # Failed upstream requests are not persisted as successful empty
                # cache entries for other owners or refreshed searches.
                if state=='done':
                    self.db.execute('INSERT OR REPLACE INTO query_cache VALUES(?,?,?,?)',(normalize(row['query']),row['source_id'],encoded,now+self.cache_ttl))
                    for value in values:self.db.execute('INSERT OR REPLACE INTO titles VALUES(?,?,?,?,?,?)',(value['id'],row['source_id'],value['language'],normalize(value['title']),json.dumps(value,ensure_ascii=False),now))
                remaining=self.db.execute("SELECT count(*) FROM work WHERE job=? AND state IN ('queued','running')",(row['job'],)).fetchone()[0]
                self.db.execute('UPDATE jobs SET updated=?,state=? WHERE id=?',(now,'running' if remaining else 'done',row['job']))
                self.condition.notify_all()

    def close(self):
        with self.condition:self.stopping=True;self.condition.notify_all()
        for thread in self.threads:thread.join(timeout=6)
        with self.lock:
            if not any(t.is_alive() for t in self.threads):self.db.close()

_manager=None;_manager_lock=threading.Lock()
def manager():
    global _manager
    with _manager_lock:
        if _manager is None:_manager=Discovery(os.getenv('DATA_DIR','/data'))
        return _manager

def shutdown():
    global _manager
    with _manager_lock:
        if _manager is not None:_manager.close();_manager=None
