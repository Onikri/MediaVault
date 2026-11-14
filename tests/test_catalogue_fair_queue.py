"""Queue fairness for the catalogue crawler; neutral fixture hosts only."""
import json,os,sys,tempfile,threading,sqlite3,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from catalogue_indexer import Indexer,LIB_HOST,TRIP_AFTER
from manga_catalog_index import initialize

class Response:
 def __init__(self,code):self.status_code=code
class HttpError(Exception):
 def __init__(self,code):super().__init__('http');self.response=Response(code)

class FairQueueTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DATA_DIR':self.temp.name,'MEDIA_VAULT_DISABLE_WORKER':'1'});self.env.start()
  self.db=sqlite3.connect(':memory:',check_same_thread=False);initialize(self.db);self.db.commit()
  self.store=SimpleNamespace(db=self.db,lock=threading.RLock());self.now=1000
 def tearDown(self):self.db.close();self.env.stop();self.temp.cleanup()
 def worker(self,fetch=None):return Indexer(self.store,fetch or (lambda s,c:{}),lambda:self.now,interval=0)
 def detail(self,worker,domain,n,priority=15,kind='html-detail'):
  with self.db:
   for i in range(n):worker.enqueue({'type':kind,'domain':domain,'url':f'https://{domain}/t/{i}','slug':str(i),'site':1,'row':{'provider':'fixture','url':f'https://{domain}/t/{i}'}},priority)

 def test_every_source_with_work_gets_a_worker_before_any_gets_a_second(self):
  worker=self.worker()
  # The old global order claimed the oldest queue first: a single source
  # with a deep, older backlog held every slot.
  self.detail(worker,'old.example',50);self.now+=10
  for domain in ('a.example','b.example','c.example'):self.detail(worker,domain,5)
  hosts=[worker.claim()['host'] for _ in range(4)]
  self.assertEqual(set(hosts),{'old.example','a.example','b.example','c.example'})

 def test_a_failing_host_rests_and_stops_holding_workers(self):
  def fetch(spec,cursor):
   if spec['domain']=='down.example':raise HttpError(502)
   return {'rows':[]}
  worker=self.worker(fetch);self.detail(worker,'down.example',20)
  for _ in range(TRIP_AFTER):self.assertTrue(worker.run_once())
  self.assertGreater(worker.paused['down.example'],self.now)
  self.assertIsNone(worker.claim())
  self.detail(worker,'up.example',1)
  self.assertEqual(worker.claim()['host'],'up.example')
  # The pause ends and the host is tried again.
  self.now=worker.paused['down.example']+1
  self.assertEqual(worker.claim()['host'],'down.example')

 def test_missing_titles_do_not_pause_their_source(self):
  worker=self.worker(lambda s,c:(_ for _ in ()).throw(HttpError(404)));self.detail(worker,'fixture.example',TRIP_AFTER+2)
  for _ in range(TRIP_AFTER+2):worker.run_once()
  self.assertNotIn('fixture.example',worker.paused)

 def test_too_many_requests_slows_only_that_host_and_recovers(self):
  worker=Indexer(self.store,lambda s,c:{},lambda:self.now,interval=1.1)
  self.assertEqual(worker.base_pace(LIB_HOST),0.6);self.assertEqual(worker.base_pace('other.example'),1.1)
  worker.failed(LIB_HOST,429);self.assertEqual(worker.pace[LIB_HOST],1.2);self.assertNotIn('other.example',worker.pace)
  for _ in range(20):worker.answered(LIB_HOST)
  self.assertNotIn(LIB_HOST,worker.pace)

 def test_bridge_sources_share_the_suwayomi_slots(self):
  worker=self.worker()
  for n in range(4):self.detail(worker,f'bridge{n}.example',3,kind='bridge-detail')
  self.detail(worker,'direct.example',3)
  jobs=[worker.claim() for _ in range(6)]
  bridges=[j for j in jobs if j and j['bridge']]
  self.assertEqual(len(bridges),4)
  self.assertIn('direct.example',{j['host'] for j in jobs if j})

 def test_existing_queue_gets_hosts_without_losing_jobs(self):
  with self.db:
   self.db.execute("CREATE TABLE catalogue_jobs(id TEXT PRIMARY KEY,spec TEXT NOT NULL,cursor TEXT NOT NULL,state TEXT NOT NULL,priority INTEGER NOT NULL,due REAL NOT NULL,pages INTEGER NOT NULL DEFAULT 0,records INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',updated REAL NOT NULL,lease TEXT NOT NULL DEFAULT '',kind TEXT NOT NULL DEFAULT '',expected INTEGER)")
   for key,spec in (('a',{'type':'lib-detail','domain':'hentailib.me','slug':'1'}),('b',{'type':'bridge-detail','domain':'fixture.example','manga':1})):
    self.db.execute("INSERT INTO catalogue_jobs(id,spec,cursor,state,priority,due,updated,kind) VALUES(?,?,'{}','queued',15,0,0,?)",(key,json.dumps(spec),spec['type']))
  worker=self.worker()
  self.assertEqual(dict(self.db.execute('SELECT id,host FROM catalogue_jobs')),{'a':LIB_HOST,'b':'fixture.example'})
  self.assertEqual({worker.claim()['id'] for _ in range(2)},{'a','b'})

if __name__=='__main__':unittest.main()
