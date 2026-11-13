"""Durable, fair metadata crawling on the VM; no image or chapter requests."""
import hashlib,json,os,shutil,threading,time
from pathlib import Path
from manga_tag_policy import canonical_json,current

_service=None;_service_lock=threading.Lock()

def identity(spec):
    key={k:spec.get(k) for k in ('type','domain','site','kind','slug','manga','url')}
    key['source']=(spec.get('source') or {}).get('id');key['term']=spec.get('term')
    return hashlib.sha256(canonical_json(key)).hexdigest()[:32]

class Indexer:
    def __init__(self,store,fetch=None,clock=time.time,interval=1.1):
        self.store=store;self.clock=clock;self.fetch=fetch or __import__('catalogue_sources').fetch;self.stop=threading.Event();self.threads=[];self.rate={};self.rate_lock=threading.Lock();self.interval=interval;self.turn=0;self.inflight={}
        with store.lock,store.db:
            store.db.execute('CREATE TABLE IF NOT EXISTS catalogue_jobs(id TEXT PRIMARY KEY,spec TEXT NOT NULL,cursor TEXT NOT NULL,state TEXT NOT NULL,priority INTEGER NOT NULL,due REAL NOT NULL,pages INTEGER NOT NULL DEFAULT 0,records INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT \'\',updated REAL NOT NULL,lease TEXT NOT NULL DEFAULT \'\')')
            store.db.execute('CREATE INDEX IF NOT EXISTS catalogue_jobs_due ON catalogue_jobs(state,due,priority)')
            columns={r[1] for r in store.db.execute('PRAGMA table_info(catalogue_jobs)')}
            if 'kind' not in columns:
                store.db.execute("ALTER TABLE catalogue_jobs ADD COLUMN kind TEXT NOT NULL DEFAULT ''")
                store.db.execute("UPDATE catalogue_jobs SET kind=json_extract(spec,'$.type')")
            store.db.execute('CREATE INDEX IF NOT EXISTS catalogue_jobs_kind ON catalogue_jobs(kind,state)')
            store.db.execute("CREATE INDEX IF NOT EXISTS catalogue_jobs_domain_due ON catalogue_jobs(kind,json_extract(spec,'$.domain'),state,due,id)")
            if 'expected' not in columns:store.db.execute('ALTER TABLE catalogue_jobs ADD COLUMN expected INTEGER')
            store.db.execute('CREATE TABLE IF NOT EXISTS catalogue_page_fingerprints(job TEXT NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(job,digest))')
            store.db.execute('CREATE TABLE IF NOT EXISTS catalogue_tag_targets(source TEXT NOT NULL,label TEXT NOT NULL,target TEXT NOT NULL,PRIMARY KEY(source,label,target))')
            store.db.execute("UPDATE catalogue_jobs SET state='queued',lease='' WHERE state='running'")

    def enqueue(self,spec,priority=10):
        key=identity(spec);now=self.clock()
        self.store.db.execute("INSERT INTO catalogue_jobs(id,spec,cursor,state,priority,due,updated,kind) VALUES(?,?,?,'queued',?,?,?,?) ON CONFLICT(id) DO UPDATE SET spec=excluded.spec,priority=MAX(catalogue_jobs.priority,excluded.priority)",(key,canonical_json(spec).decode(),'{"page":1}',priority,now,now,spec['type']))
        return key

    def seed(self,installed):
        from catalogue_sources import base_sources
        sources=base_sources(installed)
        with self.store.lock,self.store.db:
            # The old HentaiChan feed was the home page, not its full catalogue.
            # Retire only that listing; retained cards and detail jobs stay intact.
            for key,raw in self.store.db.execute("SELECT id,spec FROM catalogue_jobs WHERE kind='html'").fetchall():
                old=json.loads(raw)
                # ReManga's HTML front is CAPTCHA-gated; its JSON catalogue replaces it.
                if old.get('domain')=='hentaichan.cc' and not old.get('term') and old.get('url','').rstrip('/')=='https://hentaichan.cc' or old.get('domain')=='remanga.org':
                    self.store.db.execute('DELETE FROM catalogue_page_fingerprints WHERE job=?',(key,));self.store.db.execute('DELETE FROM catalogue_jobs WHERE id=?',(key,))
            # Retire superseded bridge/homepage feeds, not their stored cards.
            replacements={s['domain']:s for s in sources}
            for key,raw in self.store.db.execute("SELECT id,spec FROM catalogue_jobs WHERE kind IN ('bridge','html') AND json_extract(spec,'$.term') IS NULL").fetchall():
                old=json.loads(raw);new=replacements.get(old.get('domain'))
                if new and (new['type']!=old['type'] or old['type']=='html' and new.get('url')!=old.get('url')):
                    self.store.db.execute('DELETE FROM catalogue_page_fingerprints WHERE job=?',(key,));self.store.db.execute('DELETE FROM catalogue_jobs WHERE id=?',(key,))
            for spec in sources:
                self.enqueue(spec)
                # Each source's own genre/tag list becomes owner vocabulary and
                # a filtered catalogue route for that label.
                if spec['type'] in {'lib','bridge','remanga'}:self.enqueue({**spec,'type':spec['type']+'-vocabulary'},30)

    def prioritize(self,values):
        policy=current();keys={policy.key(value) for value in values if isinstance(value,str)}-{''}
        if not keys:return
        with self.store.lock,self.store.db:
            for source,label,target in self.store.db.execute('SELECT source,label,target FROM catalogue_tag_targets').fetchall():
                if policy.key(label,source) in keys:self.enqueue(json.loads(target),80)

    def claim(self):
        now=self.clock()
        with self.store.lock,self.store.db:
            self.turn+=1
            order='due,priority,id' if self.turn%4==0 else 'priority DESC,due,id'
            # Reserve every third turn for a base catalogue page. A large detail
            # queue must not delay discovery of the rest of the source for days.
            preference="CASE WHEN kind IN ('lib','bridge','remanga','html') AND json_extract(spec,'$.term') IS NULL THEN 0 ELSE 1 END,updated," if self.turn%3==1 else ''
            busy=[host for host,count in self.inflight.items() if count>=2]
            exclude=" AND CASE WHEN kind LIKE 'lib%' THEN 'api.cdnrulib.link' ELSE json_extract(spec,'$.domain') END NOT IN ("+','.join('?' for _ in busy)+')' if busy else ''
            cursor=self.store.db.execute("SELECT id,spec,cursor,pages,records,attempts,state FROM catalogue_jobs WHERE state IN ('queued','retry','done','partial') AND due<=?"+exclude+" ORDER BY "+preference+order+" LIMIT 1",(now,*busy))
            names=[c[0] for c in cursor.description];row=None
            for candidate in cursor.fetchall():
                parsed=json.loads(candidate[1]);host='api.cdnrulib.link' if parsed['type'].startswith('lib') else parsed['domain']
                if self.inflight.get(host,0)<2:row=candidate;break
            if not row:return None
            job=dict(zip(names,row));job['spec']=json.loads(job['spec']);job['cursor']=json.loads(job['cursor']);job['host']=host
            self.inflight[host]=self.inflight.get(host,0)+1
            if job['state'] in {'done','partial'}:
                job['cursor']={'page':1};self.store.db.execute('DELETE FROM catalogue_page_fingerprints WHERE job=?',(job['id'],))
                self.store.db.execute('UPDATE catalogue_jobs SET pages=0,records=0,expected=NULL WHERE id=?',(job['id'],))
            job['lease']=os.urandom(12).hex()
            self.store.db.execute("UPDATE catalogue_jobs SET state='running',lease=?,updated=? WHERE id=?",(job['lease'],now,job['id']))
            return job

    def run_once(self):
        job=self.claim()
        if not job:return False
        spec=job['spec'];now=self.clock()
        try:
            data_dir=Path(os.getenv('DATA_DIR','/data'))
            if data_dir.exists() and shutil.disk_usage(data_dir).free<512*1024*1024:raise RuntimeError('storage')
            # One request per host per second, even across both workers.
            host=job['host']
            with self.rate_lock:
                next_time=max(time.monotonic(),self.rate.get(host,0));self.rate[host]=next_time+self.interval
            if self.stop.wait(max(0,next_time-time.monotonic())):return False
            result=self.fetch(spec,job['cursor']);rows=result.get('rows') or []
            if not rows and result.get('next'):raise RuntimeError('empty-page')
            digest=hashlib.sha256(canonical_json(sorted(str(r.get('sourceUrl') or r.get('url') or r.get('id')) for r in rows))).hexdigest()
            with self.store.lock,self.store.db:
                active=self.store.db.execute('SELECT lease FROM catalogue_jobs WHERE id=?',(job['id'],)).fetchone()
                if not active or active[0]!=job['lease']:return True
                if rows and self.store.db.execute('SELECT 1 FROM catalogue_page_fingerprints WHERE job=? AND digest=?',(job['id'],digest)).fetchone():raise RuntimeError('repeated-page')
                if rows:self.store.db.execute('INSERT INTO catalogue_page_fingerprints VALUES(?,?)',(job['id'],digest))
                from manga_catalog_index import upsert
                from content_catalog import ingest
                manga=[r for r in rows if r.get('kind')=='manga' and str(r.get('provider','')).split(':')[0] not in {'anilist','kitsu','jikan','shikimori'}]
                other=[r for r in rows if r not in manga]
                count=upsert(self.store.db,manga)+ingest(self.store.db,other)
                if count!=len(rows):raise RuntimeError('incomplete-write')
                for detail in result.get('details') or []:
                    row=detail['row'];known=self.store.db.execute("SELECT inspected,json_extract(metadata,'$.sourceMetadataVersion'),json_extract(metadata,'$.description') FROM catalog_titles WHERE provider=? AND source_url=?",(row['provider'],row.get('sourceUrl') or row.get('url'))).fetchone()
                    missing=(known[1] or 0)<2 if known and spec['domain']=='hentaichan.cc' else not known or not known[2]
                    if not known or known[0]<self.clock()-7*86400 or missing:self.enqueue(detail,int(spec.get('detailPriority',15)))
                from content_vocabulary import add,bump
                vocabulary_added=0
                if spec['type'] in {'anilist','books'}:
                    for row in rows:
                        for field in ('genres','tags'):
                            for label in row.get(field) or []:
                                target={**spec,'term':{'field':'genre' if field=='genres' else 'tag','label':label}}
                                self.store.db.execute('INSERT OR IGNORE INTO catalogue_tag_targets VALUES(?,?,?)',(spec['domain'],label,canonical_json(target).decode()))
                for term in result.get('vocabulary') or []:
                    field='genres' if term.get('category')=='genre' else 'tags'
                    vocabulary_added+=add(self.store.db,term['label'],spec['domain'],field,'manga')
                    if spec['type'] in {'lib-vocabulary','bridge-vocabulary','remanga-vocabulary'}:target={**spec,'type':spec['type'].removesuffix('-vocabulary'),'term':term}
                    elif term.get('url'):target={**spec,'type':'html','url':term['url'],'term':term}
                    else:continue
                    self.store.db.execute('INSERT OR IGNORE INTO catalogue_tag_targets VALUES(?,?,?)',(spec['domain'],term['label'],canonical_json(target).decode()))
                if vocabulary_added:bump(self.store.db)
                next_cursor=result.get('next');state='queued' if next_cursor else result.get('state') or ('partial' if spec['type']=='html' else 'done')
                due=self.clock()+(2 if next_cursor else 86400 if '-detail' in spec['type'] else 21600)
                self.store.db.execute('UPDATE catalogue_jobs SET cursor=?,state=?,due=?,pages=pages+1,records=records+?,expected=COALESCE(?,expected),attempts=0,error=?,updated=?,lease=\'\' WHERE id=?',(canonical_json(next_cursor or {'page':1}).decode(),state,due,count,result.get('total'),result.get('reason',''),self.clock(),job['id']))
                if '-detail' in spec['type'] and not next_cursor:
                    self.store.db.execute('DELETE FROM catalogue_jobs WHERE id=?',(job['id'],));self.store.db.execute('DELETE FROM catalogue_page_fingerprints WHERE job=?',(job['id'],))
        except Exception as error:
            code=getattr(getattr(error,'response',None),'status_code',None)
            reason='Недостаточно свободного места' if str(error)=='storage' else 'Источник повторяет страницу каталога' if str(error)=='repeated-page' else 'Источник вернул пустую промежуточную страницу' if str(error)=='empty-page' else 'Источник временно не отдаёт метаданные'
            wait=30 if code==429 else min(3600,30*2**min(job['attempts'],7))
            with self.store.lock,self.store.db:self.store.db.execute("UPDATE catalogue_jobs SET state='retry',due=?,attempts=attempts+1,error=?,updated=?,lease='' WHERE id=? AND lease=?",(self.clock()+wait,reason,self.clock(),job['id'],job['lease']))
        finally:
            with self.store.lock:self.inflight[job['host']]=max(0,self.inflight.get(job['host'],1)-1)
        return True

    def start(self):
        if self.threads:return
        def work():
            while not self.stop.is_set():
                try:
                    if not self.run_once():self.stop.wait(2)
                except Exception:self.stop.wait(5)
        for i in range(6):
            thread=threading.Thread(target=work,daemon=True,name='catalogue-index-'+str(i));self.threads.append(thread);thread.start()

    def status(self):
        with self.store.lock,self.store.db:
            rows=[]
            pending_details={domain:count for domain,count in self.store.db.execute("SELECT json_extract(spec,'$.domain'),COUNT(*) FROM catalogue_jobs WHERE kind LIKE '%-detail' GROUP BY json_extract(spec,'$.domain')")}
            for spec,state,pages,records,error,due,expected in self.store.db.execute("SELECT spec,state,pages,records,error,due,expected FROM catalogue_jobs WHERE kind IN ('lib','bridge','remanga','html','mirror','unsupported','anilist','kinobox','books') ORDER BY id"):
                spec=json.loads(spec)
                if '-detail' in spec['type'] or spec['type'].endswith('-vocabulary') or spec.get('term'):continue
                details=pending_details.get(spec['domain'],0)
                rows.append({'domain':spec['domain'],'name':spec['name'],'status':'enriching' if state=='done' and details else state,'pages':pages,'indexed':records,'expected':expected,'pendingDetails':details,'error':error,'retryAt':due if state=='retry' else None})
                if spec['type']=='mirror':rows[-1]['mirrorOf']=spec['primary']
            by_domain={r['domain']:r for r in rows}
            for row in rows:
                if row.get('mirrorOf') in by_domain:
                    primary=by_domain[row['mirrorOf']]
                    for field in ('status','pages','indexed','expected','pendingDetails','retryAt'):row[field]=primary[field]
            manga=self.store.db.execute('SELECT COUNT(*) FROM catalog_titles').fetchone()[0]
            from content_catalog import initialize
            initialize(self.store.db)
            other=self.store.db.execute('SELECT COUNT(*) FROM content_titles').fetchone()[0]
            pending=self.store.db.execute("SELECT COUNT(*) FROM catalogue_jobs WHERE state IN ('queued','retry','running')").fetchone()[0]
        completed=sum(r['status'] in {'done','unsupported'} for r in rows)
        return {'state':'running' if pending else 'done','continuous':True,'total':len(rows),'completed':completed,'indexed':manga+other,'pending':pending,'sources':rows}

def ensure(store):
    global _service
    if os.getenv('MEDIA_VAULT_DISABLE_WORKER')=='1':return None
    with _service_lock:
        if _service is None:
            _service=Indexer(store)
            try:
                from suwayomi_bridge import sources
                installed=sources()
            except Exception:installed=[]
            _service.seed(installed);_service.start()
        return _service
