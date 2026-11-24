"""Indexer throughput contracts (A2): Suwayomi slots, refresh intervals,
unchanged-row skips, page-item purge, retry hygiene and writer pragmas.
Temporary SQLite only; no network."""
import json,os,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import catalogue_indexer
from catalogue_indexer import (Indexer,REFRESH_BASE,REFRESH_TAG,STALL_AFTER,STALL_RETRY,
                               junk_title,failure_text,refresh_interval,suwayomi_route,suwayomi_sql)
from manga_catalog_index import initialize,upsert,browse
from manga_tag_policy import canonical_json
import content_catalog

POLICY={'schemaVersion':1,'includeDiscovered':True,'hiddenTags':[],'excludedTerms':[],'excludedPrefixes':[],'tags':[]}

def native_id():
    from manga_native_sources import ADAPTERS
    return str(next(iter(ADAPTERS)))

class Base(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();policy=Path(self.temp.name)/'manga-tag-policy.json';policy.write_bytes(canonical_json(POLICY))
        self.env=patch.dict(os.environ,{'DATA_DIR':self.temp.name,'MANGA_TAG_POLICY_FILE':str(policy),'MEDIA_VAULT_DISABLE_WORKER':'1'});self.env.start()
        self.db=sqlite3.connect(':memory:',check_same_thread=False);initialize(self.db);content_catalog.initialize(self.db);self.db.commit()
        self.store=SimpleNamespace(db=self.db,lock=threading.RLock());self.now=100000
    def tearDown(self):self.db.close();self.env.stop();self.temp.cleanup()
    def worker(self,fetch=None):return Indexer(self.store,fetch or (lambda s,c:{}),lambda:self.now,interval=0)
    def enqueue(self,worker,spec,priority=10):
        with self.store.lock,self.db:return worker.enqueue(spec,priority)
    def row(self,n,title=None):
        url=f'https://fixture.example/title/{n}'
        return {'provider':'fixture','kind':'manga','title':title or f'Garden {n}','url':url,'sourceUrl':url,'genres':['Ecology'],'language':'en'}
    def job(self,key):return self.db.execute('SELECT state,due,attempts,error,reason,records FROM catalogue_jobs WHERE id=?',(key,)).fetchone()

class SuwayomiSlotTests(Base):
    def test_native_bridge_jobs_do_not_take_suwayomi_slots(self):
        worker=self.worker();nid=native_id()
        for n in range(4):
            for i in range(3):self.enqueue(worker,{'type':'bridge-detail','domain':f'suwa{n}.example','manga':i,'source':{'id':'999999999999'}},15)
        for n in range(2):
            for i in range(3):self.enqueue(worker,{'type':'bridge-detail','domain':f'native{n}.example','manga':i,'source':{'id':nid}},15)
        jobs=[job for job in (worker.claim() for _ in range(12)) if job]
        self.assertEqual(sum(job['bridge'] for job in jobs),catalogue_indexer.BRIDGE_SLOTS)
        native=[job for job in jobs if job['host'].startswith('native')]
        # Two hosts, HOST_SLOTS each, none of them counted as Suwayomi work.
        self.assertEqual(len(native),2*catalogue_indexer.HOST_SLOTS)
        self.assertFalse(any(job['bridge'] for job in native))

    def test_route_and_its_sql_twin_agree(self):
        self.worker();nid=native_id();cases=[
            ({'type':'bridge','source':{'id':nid}},{'page':2}),
            ({'type':'bridge','source':{'id':nid}},{'page':2,'route':'suwayomi'}),
            ({'type':'bridge','source':{'id':nid},'route':'suwayomi'},{'page':1}),
            ({'type':'bridge-vocabulary','source':{'id':'999999999999'}},{'page':1}),
            ({'type':'bridge','source':{'id':int(nid)} if nid.isdigit() else {'id':nid}},{'page':1}),
            ({'type':'html','domain':'fixture.example'},{'page':1}),
        ]
        with self.db:
            for n,(spec,cursor) in enumerate(cases):
                self.db.execute("INSERT INTO catalogue_jobs(id,spec,cursor,state,priority,due,updated,kind) VALUES(?,?,?,'queued',10,0,0,?)",(str(n),json.dumps(spec),json.dumps(cursor),spec['type']))
        sql={int(key) for (key,) in self.db.execute('SELECT id FROM catalogue_jobs WHERE '+suwayomi_sql())}
        python={n for n,(spec,cursor) in enumerate(cases) if suwayomi_route(spec,cursor)}
        self.assertEqual(sql,python);self.assertEqual(python,{1,2,3})

class RefreshTests(Base):
    def test_refresh_intervals(self):
        self.assertEqual(refresh_interval({'type':'lib'}),REFRESH_BASE)
        self.assertEqual(refresh_interval({'type':'bridge','term':{'label':'Romance'}}),REFRESH_TAG)
        self.assertEqual(refresh_interval({'type':'anilist','term':{'field':'tag','label':'Romance'}}),REFRESH_TAG)
        self.assertEqual(refresh_interval({'type':'anilist-trending'}),3600)
        self.assertEqual(refresh_interval({'type':'omdb'}),86400)
        self.assertEqual(refresh_interval({'type':'html-detail'}),86400)
        self.assertEqual((REFRESH_BASE,REFRESH_TAG),(48*3600,7*86400))

    def test_finished_tag_route_waits_a_week_unless_the_owner_prioritizes_it(self):
        worker=self.worker(lambda s,c:{'rows':[self.row(1)],'next':None})
        target={'type':'lib','domain':'fixture.example','name':'Fixture','site':1,'term':{'label':'Ecology'}}
        with self.db:self.db.execute('INSERT INTO catalogue_tag_targets VALUES(?,?,?)',('fixture.example','Ecology',canonical_json(target).decode()))
        key=self.enqueue(worker,target,80)
        self.assertTrue(worker.run_once())
        state,due,*_=self.job(key)
        self.assertEqual((state,due),('done',self.now+REFRESH_TAG))
        self.now+=10;worker.prioritize(['Ecology'])
        self.assertEqual(self.job(key)[1],self.now)
        self.assertEqual(worker.claim()['id'],key)

class UnchangedRowTests(Base):
    def trace(self,call):
        seen=[];self.db.set_trace_callback(seen.append)
        try:call()
        finally:self.db.set_trace_callback(None)
        return seen

    def test_manga_repeat_keeps_tags_and_moves_only_last_seen(self):
        upsert(self.db,[self.row(1)],timestamp=1000);self.db.commit()
        first=self.db.execute('SELECT first_seen,updated,metadata FROM catalog_titles').fetchone()
        seen=self.trace(lambda:upsert(self.db,[self.row(1)],timestamp=2000))
        self.assertFalse([s for s in seen if 'DELETE FROM catalog_tags' in s or 'DELETE FROM catalog_work_tags' in s])
        self.assertEqual(self.db.execute('SELECT first_seen,updated,metadata FROM catalog_titles').fetchone(),(first[0],2000.0,first[2]))
        self.assertEqual(browse(self.db,tag='Ecology')['total'],1)
        # A new tag fact is a change and rewrites the title's tags.
        seen=self.trace(lambda:upsert(self.db,[{**self.row(1),'genres':['Ecology','Mystery']}],timestamp=3000))
        self.assertTrue([s for s in seen if 'DELETE FROM catalog_tags' in s])
        self.assertEqual(browse(self.db,genre='Mystery')['total'],1)
        # A changed title moves its work key.
        upsert(self.db,[self.row(1,'Garden Renamed')],timestamp=4000)
        self.assertEqual(self.db.execute('SELECT title,first_seen FROM catalog_titles').fetchone(),('Garden Renamed',1000.0))

    def test_inspected_detail_repeat_still_marks_inspection(self):
        upsert(self.db,[{**self.row(1),'metadataInspected':True}],timestamp=1000)
        upsert(self.db,[{**self.row(1),'metadataInspected':True}],timestamp=5000)
        self.assertEqual(self.db.execute('SELECT inspected,updated FROM catalog_titles').fetchone(),(5000.0,5000.0))

    def test_content_repeat_skips_tag_rewrite(self):
        row={**self.row(1),'id':'fixture:1','kind':'movie'}
        content_catalog.ingest(self.db,[row]);self.db.execute('UPDATE content_titles SET updated=1');self.db.commit()
        seen=self.trace(lambda:content_catalog.ingest(self.db,[row]))
        self.assertFalse([s for s in seen if 'DELETE FROM content_tags' in s or 'DELETE FROM content_work_tags' in s])
        self.assertGreater(self.db.execute('SELECT updated FROM content_titles').fetchone()[0],1)
        seen=self.trace(lambda:content_catalog.ingest(self.db,[{**row,'genres':['Ecology','Mystery']}]))
        self.assertTrue([s for s in seen if 'DELETE FROM content_tags' in s])
        self.assertEqual(content_catalog.browse(self.db,kind='movie',genre='Mystery')['total'],1)

class PurgeTests(Base):
    def test_purge_runs_in_short_batches_and_keeps_other_jobs(self):
        worker=self.worker()
        with self.db:
            self.db.executemany('INSERT INTO catalogue_page_items VALUES(?,?)',(('a',str(n)) for n in range(2500)))
            self.db.executemany('INSERT INTO catalogue_page_items VALUES(?,?)',(('b',str(n)) for n in range(10)))
        statements=[]
        with patch.object(catalogue_indexer,'PURGE_BATCH',1000):
            self.db.set_trace_callback(lambda s:statements.append(s) if s.startswith('DELETE FROM catalogue_page_items') else None)
            try:worker.purge_items('a')
            finally:self.db.set_trace_callback(None)
        self.assertEqual(len(statements),3)
        self.assertEqual(dict(self.db.execute('SELECT job,COUNT(*) FROM catalogue_page_items GROUP BY job')),{'b':10})

    def test_finished_job_drops_its_items_but_keeps_records(self):
        pages={1:[self.row(1),self.row(2)],2:[self.row(2),self.row(3)]}
        worker=self.worker(lambda s,c:{'rows':pages[c['page']],'next':{'page':2} if c['page']==1 else None})
        key=self.enqueue(worker,{'type':'lib','domain':'fixture.example','name':'Fixture','site':1})
        worker.run_once();self.assertEqual(self.db.execute('SELECT COUNT(*) FROM catalogue_page_items').fetchone()[0],2)
        self.now+=3;worker.run_once()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM catalogue_page_items').fetchone()[0],0)
        self.assertEqual(self.job(key)[5],3);self.assertEqual(worker.status()['sources'][0]['indexed'],3)

class RetryHygieneTests(Base):
    def failing(self,error):
        def fetch(spec,cursor):raise error
        return self.worker(fetch)

    def test_error_keeps_the_real_failure_and_status_keeps_the_owner_phrase(self):
        worker=self.failing(ConnectionError('read timed out https://fixture.example/api?token=secret&page=3'))
        key=self.enqueue(worker,{'type':'lib','domain':'fixture.example','name':'Fixture','site':1})
        with self.assertLogs('catalogue_indexer','WARNING') as logs:worker.run_once()
        state,_,attempts,error,reason,_=self.job(key)
        self.assertEqual((state,attempts),('retry',1))
        self.assertEqual(error,'ConnectionError: read timed out https://fixture.example/api')
        self.assertNotIn('secret',error);self.assertEqual(reason,'Источник временно не отдаёт метаданные')
        source=worker.status()['sources'][0]
        self.assertEqual((source['status'],source['error'],source['failure']),('retry',reason,error))
        self.assertEqual(len(logs.output),1)
        for text in ('host='+catalogue_indexer.LIB_HOST,'kind=lib','ConnectionError','attempt=1'):self.assertIn(text,logs.output[0])

    def test_failure_text_drops_headers_and_limits_length(self):
        text=failure_text(RuntimeError('403 Forbidden headers={"Cookie": "sid=1"} '+'x'*500))
        self.assertEqual(text,'RuntimeError: 403 Forbidden …')
        self.assertLessEqual(len(failure_text(RuntimeError('y'*900))),len('RuntimeError: ')+200)

    def test_failure_log_is_throttled_per_host(self):
        worker=self.failing(TimeoutError('slow'))
        for n in range(3):self.enqueue(worker,{'type':'html-detail','domain':'fixture.example','url':f'https://fixture.example/t/{n}','slug':str(n)},15)
        with self.assertLogs('catalogue_indexer','WARNING') as logs:
            for _ in range(3):worker.run_once()
        self.assertEqual(len(logs.output),1)

    def test_long_failing_job_stalls_weekly_and_stays_a_retry_for_the_ui(self):
        worker=self.failing(TimeoutError('slow'))
        key=self.enqueue(worker,{'type':'lib','domain':'fixture.example','name':'Fixture','site':1})
        with self.db:self.db.execute('UPDATE catalogue_jobs SET attempts=? WHERE id=?',(STALL_AFTER-1,key))
        worker.run_once()
        state,due,attempts,*_=self.job(key)
        self.assertEqual((state,due,attempts),('stalled',self.now+STALL_RETRY,STALL_AFTER))
        source=worker.status()['sources'][0]
        self.assertEqual((source['status'],source['stalled'],source['retryAt']),('retry',True,due))
        self.assertEqual(worker.status()['pending'],0)
        worker.paused.clear();worker.failures.clear()
        self.now=due-1;self.assertIsNone(worker.claim())
        self.now=due;self.assertEqual(worker.claim()['id'],key)

    def test_last_page_served_again_ends_the_listing(self):
        # Kinobox keeps offering a next page and repeats its last one.
        last=[self.row(3)]
        pages={1:[self.row(1)],2:[self.row(2)],3:last,4:last}
        worker=self.worker(lambda s,c:{'rows':pages[c['page']],'next':{'page':c['page']+1}})
        key=self.enqueue(worker,{'type':'kinobox','kind':'movie','domain':'fixture.example','name':'Fixture'})
        for _ in range(4):worker.run_once();self.now+=3
        state,due,attempts,error,_,records=self.job(key)
        self.assertEqual((state,attempts,error,records),('done',0,'',3))
        self.assertEqual(due,self.now-3+REFRESH_BASE)

    def test_repeat_without_a_next_page_ends_the_listing(self):
        pages={1:[self.row(1)],2:[self.row(1)]}
        worker=self.worker(lambda s,c:{'rows':pages[c['page']],'next':{'page':2} if c['page']==1 else None})
        key=self.enqueue(worker,{'type':'lib','domain':'fixture.example','name':'Fixture','site':1})
        worker.run_once();self.now+=3;worker.run_once()
        self.assertEqual(self.job(key)[0],'done')

    def test_a_loop_back_to_an_earlier_page_is_still_an_error(self):
        pages={1:[self.row(1)],2:[self.row(2)],3:[self.row(1)]}
        worker=self.worker(lambda s,c:{'rows':pages[c['page']],'next':{'page':c['page']+1}})
        key=self.enqueue(worker,{'type':'lib','domain':'fixture.example','name':'Fixture','site':1})
        for _ in range(3):worker.run_once();self.now+=3
        self.assertEqual(self.job(key)[:1]+self.job(key)[3:5],('retry','RuntimeError: repeated-page','Источник повторяет страницу каталога'))

    def test_server_error_pages_are_not_indexed(self):
        for title in ('MySQL Fatal Error','mysql fatal error: too many connections','Warning: mysqli_connect(): x','502 Bad Gateway','Access denied','Just a moment...'):
            self.assertTrue(junk_title(title),title)
        for title in ('Garden','Access Denied Forever','Moment of Truth'):self.assertFalse(junk_title(title),title)
        worker=self.worker(lambda s,c:{'rows':[self.row(1),self.row(2,'MySQL Fatal Error')],'next':None})
        key=self.enqueue(worker,{'type':'lib','domain':'fixture.example','name':'Fixture','site':1})
        worker.run_once()
        self.assertEqual(self.job(key)[0],'done')
        self.assertEqual([r[0] for r in self.db.execute('SELECT title FROM catalog_titles')],['Garden 1'])

class WriterPragmaTests(unittest.TestCase):
    def test_writer_uses_normal_sync_and_bounded_wal(self):
        from manga_discovery import Discovery
        with tempfile.TemporaryDirectory() as directory:
            store=Discovery(directory,start_workers=False)
            try:
                self.assertEqual(store.db.execute('PRAGMA journal_mode').fetchone()[0],'wal')
                self.assertEqual(store.db.execute('PRAGMA synchronous').fetchone()[0],1)
                self.assertEqual(store.db.execute('PRAGMA journal_size_limit').fetchone()[0],268435456)
            finally:store.db.close()

if __name__=='__main__':unittest.main()
