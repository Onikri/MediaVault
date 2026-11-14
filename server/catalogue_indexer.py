"""Durable, fair metadata crawling on the VM; no image or chapter requests."""
import hashlib,json,os,shutil,threading,time
from pathlib import Path
from manga_tag_policy import canonical_json,current

_service=None;_service_lock=threading.Lock()

def identity(spec):
    key={k:spec.get(k) for k in ('type','domain','site','kind','slug','manga','url')}
    key['source']=(spec.get('source') or {}).get('id');key['term']=None if spec.get('type','').endswith('-detail') else spec.get('term')
    return hashlib.sha256(canonical_json(key)).hexdigest()[:32]

# Every LibGroup site (MangaLib, HentaiLib, SlashLib) is one API host.
LIB_HOST='api.cdnrulib.link'
HOST_SQL="CASE WHEN kind LIKE 'lib%' THEN '"+LIB_HOST+"' ELSE COALESCE(json_extract(spec,'$.domain'),'') END"
CLAIMABLE="state IN ('queued','retry','done','partial') AND due<=?"
BASE_KINDS=('lib','bridge','remanga','html')
# Per-host request spacing in seconds; LibGroup tolerates a faster pace and
# slows down again by itself on 429.
PACE={LIB_HOST:0.6}
HOST_SLOTS=2
# Bridge jobs all run inside the one local Suwayomi process.
BRIDGE_SLOTS=4
# Consecutive transport failures that pause a whole host.
TRIP_AFTER=5
JOB_ERRORS={'storage','repeated-page','empty-page','incomplete-write'}

def host_of(spec):
    return LIB_HOST if str(spec.get('type','')).startswith('lib') else spec.get('domain') or ''

class Indexer:
    def __init__(self,store,fetch=None,clock=time.time,interval=1.1):
        self.store=store;self.clock=clock;self.fetch=fetch or __import__('catalogue_sources').fetch;self.stop=threading.Event();self.threads=[];self.rate={};self.rate_lock=threading.Lock();self.interval=interval;self.turn=0;self.inflight={}
        self.pace={};self.failures={};self.trips={};self.paused={};self.served={};self.bridges=0;self.hosts=set();self.hosts_at=None
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
            # The request host is stored so a claim reads one indexed row per
            # host instead of sorting the whole queue through JSON.
            if 'host' not in columns:store.db.execute("ALTER TABLE catalogue_jobs ADD COLUMN host TEXT NOT NULL DEFAULT ''")
            store.db.execute("UPDATE catalogue_jobs SET host="+HOST_SQL+" WHERE host=''")
            store.db.execute('CREATE INDEX IF NOT EXISTS catalogue_jobs_host_priority ON catalogue_jobs(host,priority DESC,due,id)')
            store.db.execute('CREATE INDEX IF NOT EXISTS catalogue_jobs_host_due ON catalogue_jobs(host,due,priority,id)')
            store.db.execute('CREATE TABLE IF NOT EXISTS catalogue_page_fingerprints(job TEXT NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(job,digest))')
            store.db.execute('CREATE TABLE IF NOT EXISTS catalogue_page_items(job TEXT NOT NULL,url TEXT NOT NULL,PRIMARY KEY(job,url))')
            store.db.execute('CREATE TABLE IF NOT EXISTS catalogue_tag_targets(source TEXT NOT NULL,label TEXT NOT NULL,target TEXT NOT NULL,PRIMARY KEY(source,label,target))')
            store.db.execute("UPDATE catalogue_jobs SET state='queued',lease='' WHERE state='running'")

    def enqueue(self,spec,priority=10):
        key=identity(spec);now=self.clock()
        host=host_of(spec)
        self.store.db.execute("INSERT INTO catalogue_jobs(id,spec,cursor,state,priority,due,updated,kind,host) VALUES(?,?,?,'queued',?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET spec=excluded.spec,priority=MAX(catalogue_jobs.priority,excluded.priority),host=excluded.host",(key,canonical_json(spec).decode(),'{"page":1}',priority,now,now,spec['type'],host))
        self.hosts.add(host)
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

    def open_hosts(self,now):
        if self.hosts_at is None or time.monotonic()-self.hosts_at>30:
            self.hosts|={host for (host,) in self.store.db.execute('SELECT DISTINCT host FROM catalogue_jobs')};self.hosts_at=time.monotonic()
        return [host for host in self.hosts if self.inflight.get(host,0)<HOST_SLOTS and self.paused.get(host,0)<=now]

    def claim(self):
        now=self.clock()
        with self.store.lock,self.store.db:
            self.turn+=1
            due_first=self.turn%4==0
            hosts=self.open_hosts(now)
            if not hosts:return None
            # Suwayomi runs every bridge source; keep it to a few requests.
            bridge='' if self.bridges<BRIDGE_SLOTS else " AND kind NOT LIKE 'bridge%'"
            columns='id,spec,cursor,pages,records,attempts,state,host,priority,due'
            row=None
            # Reserve every third turn for a base catalogue page. A large detail
            # queue must not delay discovery of the rest of the source for days.
            if self.turn%3==1:
                allowed=set(hosts)
                for candidate in self.store.db.execute('SELECT '+columns+' FROM catalogue_jobs INDEXED BY catalogue_jobs_kind WHERE kind IN ('+','.join('?'*len(BASE_KINDS))+") AND json_extract(spec,'$.term') IS NULL AND "+CLAIMABLE+bridge+' ORDER BY updated,id',(*BASE_KINDS,now)):
                    if candidate[7] in allowed:row=candidate;break
            if not row:
                # One best job per open host, then the host's priority decides;
                # equal priorities go to the host served longest ago, so every
                # source moves at its own pace instead of waiting behind the
                # oldest queue.
                # The planner would pick the due index and sort a deep host queue.
                order,index=('due,priority,id','catalogue_jobs_host_due') if due_first else ('priority DESC,due,id','catalogue_jobs_host_priority')
                candidates=[]
                for host in hosts:
                    found=self.store.db.execute('SELECT '+columns+' FROM catalogue_jobs INDEXED BY '+index+' WHERE host=? AND '+CLAIMABLE+bridge+' ORDER BY '+order+' LIMIT 1',(host,now)).fetchone()
                    if found:candidates.append(found)
                if not candidates:return None
                fair=lambda r:(self.inflight.get(r[7],0),self.served.get(r[7],0))
                row=min(candidates,key=(lambda r:(fair(r)[0],r[9],r[8],fair(r)[1],r[0])) if due_first else (lambda r:(-r[8],*fair(r),r[9],r[0])))
            names=columns.split(',')[:7]
            job=dict(zip(names,row));job['spec']=json.loads(job['spec']);job['cursor']=json.loads(job['cursor']);host=job['host']=row[7]
            self.inflight[host]=self.inflight.get(host,0)+1;self.served[host]=self.turn
            job['bridge']=job['spec'].get('type','').startswith('bridge')
            if job['bridge']:self.bridges+=1
            if job['state'] in {'done','partial'}:
                job['cursor']={'page':1};self.store.db.execute('DELETE FROM catalogue_page_fingerprints WHERE job=?',(job['id'],))
                self.store.db.execute('DELETE FROM catalogue_page_items WHERE job=?',(job['id'],))
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
            # One request per host per pace step, even across all workers.
            host=job['host']
            with self.rate_lock:
                next_time=max(time.monotonic(),self.rate.get(host,0));self.rate[host]=next_time+self.pace.get(host,self.base_pace(host))
            if self.stop.wait(max(0,next_time-time.monotonic())):return False
            result=self.fetch(spec,job['cursor']);rows=result.get('rows') or []
            if not rows and result.get('next'):raise RuntimeError('empty-page')
            if not rows and not result.get('catalogues') and job['cursor'].get('page',1)==1 and not spec.get('term') and spec['type'] in {'lib','bridge','remanga','html'}:raise RuntimeError('empty-page')
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
                for child in result.get('catalogues') or []:self.enqueue(child,70)
                for detail in result.get('details') or []:
                    row=detail['row'];known=self.store.db.execute("SELECT inspected,json_extract(metadata,'$.sourceMetadataVersion'),json_extract(metadata,'$.description') FROM catalog_titles WHERE provider=? AND source_url=?",(row['provider'],row.get('sourceUrl') or row.get('url'))).fetchone()
                    missing=(known[1] or 0)<2 if known and spec['domain']=='hentaichan.cc' else not known or not known[0]
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
                if rows and '-detail' not in spec['type']:
                    before=self.store.db.total_changes
                    self.store.db.executemany('INSERT OR IGNORE INTO catalogue_page_items VALUES(?,?)',[(job['id'],str(r.get('sourceUrl') or r.get('url') or r.get('id'))) for r in rows])
                    count=self.store.db.total_changes-before
                due=self.clock()+(2 if next_cursor else 86400 if '-detail' in spec['type'] else 21600)
                self.store.db.execute('UPDATE catalogue_jobs SET cursor=?,state=?,due=?,pages=pages+1,records=records+?,expected=COALESCE(?,expected),priority=CASE WHEN ? THEN priority ELSE MIN(priority,10) END,attempts=0,error=?,updated=?,lease=\'\' WHERE id=?',(canonical_json(next_cursor or {'page':1}).decode(),state,due,count,result.get('total'),bool(next_cursor),result.get('reason',''),self.clock(),job['id']))
                if '-detail' in spec['type'] and not next_cursor:
                    self.store.db.execute('DELETE FROM catalogue_jobs WHERE id=?',(job['id'],));self.store.db.execute('DELETE FROM catalogue_page_fingerprints WHERE job=?',(job['id'],))
            self.answered(host)
        except Exception as error:
            code=getattr(getattr(error,'response',None),'status_code',None)
            reason='Недостаточно свободного места' if str(error)=='storage' else 'Источник повторяет страницу каталога' if str(error)=='repeated-page' else 'Источник вернул пустую промежуточную страницу' if str(error)=='empty-page' else 'Источник временно не отдаёт метаданные'
            wait=30 if code==429 else min(3600,30*2**min(job['attempts'],7))
            if str(error) not in JOB_ERRORS:self.failed(job['host'],code)
            with self.store.lock,self.store.db:self.store.db.execute("UPDATE catalogue_jobs SET state='retry',due=?,attempts=attempts+1,error=?,updated=?,lease='' WHERE id=? AND lease=?",(self.clock()+wait,reason,self.clock(),job['id'],job['lease']))
        finally:
            with self.store.lock:
                self.inflight[job['host']]=max(0,self.inflight.get(job['host'],1)-1)
                if job['bridge']:self.bridges=max(0,self.bridges-1)
        return True

    def base_pace(self,host):
        return min(self.interval,PACE.get(host,self.interval))

    def answered(self,host):
        with self.rate_lock:
            self.failures[host]=0;self.trips.pop(host,None)
            # Ease back towards the base pace after a slowdown.
            if host in self.pace:
                self.pace[host]=max(self.base_pace(host),self.pace[host]*0.9)
                if self.pace[host]<=self.base_pace(host):del self.pace[host]

    def failed(self,host,code):
        with self.rate_lock:
            if code==429:
                # Too many requests: halve this host's rate, not the queue's.
                self.pace[host]=min(30,max(self.pace.get(host,0),self.base_pace(host),0.5)*2);return
            # A missing title is that title's problem, not the host's.
            if code in {404,410}:return
            self.failures[host]=self.failures.get(host,0)+1
            if self.failures[host]>=TRIP_AFTER:
                # A failing host rests as a whole so its timeouts stop holding
                # workers that other sources could use.
                trips=self.trips.get(host,0);self.trips[host]=trips+1;self.failures[host]=0
                self.paused[host]=self.clock()+min(3600,900*2**trips)

    def start(self):
        if self.threads:return
        def work():
            while not self.stop.is_set():
                try:
                    if not self.run_once():self.stop.wait(2)
                except Exception:self.stop.wait(5)
        # Workers mostly wait on remote hosts; per-host slots and pacing, not
        # the worker count, bound the load on each source.
        for i in range(int(os.getenv('MEDIA_VAULT_CATALOGUE_WORKERS','12'))):
            thread=threading.Thread(target=work,daemon=True,name='catalogue-index-'+str(i));self.threads.append(thread);thread.start()

    def status(self):
        with self.store.lock,self.store.db:
            rows=[]
            pending_details={domain:count for domain,count in self.store.db.execute("SELECT json_extract(spec,'$.domain'),COUNT(*) FROM catalogue_jobs WHERE kind LIKE '%-detail' GROUP BY json_extract(spec,'$.domain')")}
            pending_catalogues={domain:count for domain,count in self.store.db.execute("SELECT json_extract(spec,'$.domain'),COUNT(*) FROM catalogue_jobs WHERE kind IN ('html','lib','bridge','remanga') AND json_extract(spec,'$.term') IS NOT NULL AND state IN ('queued','retry','running') GROUP BY json_extract(spec,'$.domain')")}
            stored=dict(self.store.db.execute('SELECT provider,COUNT(*) FROM catalog_titles GROUP BY provider'))
            from catalogue_sources import source_provider
            for spec,state,pages,records,error,due,expected in self.store.db.execute("SELECT spec,state,pages,records,error,due,expected FROM catalogue_jobs WHERE kind IN ('lib','bridge','remanga','html','mirror','unsupported','anilist','kinobox','books') ORDER BY id"):
                spec=json.loads(spec)
                if '-detail' in spec['type'] or spec['type'].endswith('-vocabulary') or spec.get('term'):continue
                details=pending_details.get(spec['domain'],0)
                catalogues=pending_catalogues.get(spec['domain'],0)
                rows.append({'domain':spec['domain'],'name':spec['name'],'status':'enriching' if state in {'done','partial'} and (details or catalogues) else state,'pages':pages,'indexed':records,'storedTitles':stored.get(source_provider(spec),0),'expected':expected,'pendingDetails':details,'pendingCatalogues':catalogues,'error':error,'retryAt':due if state=='retry' else None})
                if spec['type']=='mirror':rows[-1]['mirrorOf']=spec['primary']
                if self.paused.get(host_of(spec),0)>self.clock():rows[-1]['pausedUntil']=self.paused[host_of(spec)]
            by_domain={r['domain']:r for r in rows}
            for row in rows:
                if row.get('mirrorOf') in by_domain:
                    primary=by_domain[row['mirrorOf']]
                    for field in ('status','pages','indexed','storedTitles','expected','pendingDetails','pendingCatalogues','retryAt'):row[field]=primary[field]
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
