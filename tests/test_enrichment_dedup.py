import tempfile,unittest
from task_store import TaskStore

class EnrichmentDedup(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.store=TaskStore(self.temp.name)
 def tearDown(self):self.store.close();self.temp.cleanup()
 def job(self,scope='all',key='fixture-key',**extra):return {'kind':'enrich','library_id':'library-A','vault_key':key,**({'title_id':scope} if scope!='all' else {}),**extra}
 def test_repeated_enrichment_reuses_live_job_before_capacity_check(self):
  a=self.store.add('A',self.job(),'first');self.store.next()
  b=self.store.add('A',self.job(),'different-click');self.assertEqual(a['id'],b['id'])
  self.assertEqual(len(self.store.list('A')),1)
 def test_scope_owner_and_key_are_not_merged(self):
  for owner,scope,key in [('A','all','one'),('B','all','one'),('A','manga:one','one'),('A','all','two')]:self.store.add(owner,self.job(scope,key),owner+scope+key)
  self.assertEqual(self.store.database.execute('SELECT count(*) FROM tasks').fetchone()[0],4)
 def test_legacy_duplicates_resume_earliest_cursor_and_keep_history(self):
  original=self.store.add('A',self.job(),'first');self.store.update(original['id'],progress={'cursor':18,'saved':18})
  # Represent records from releases predating scope-based deduplication.
  import time
  second='legacy-second';data=self.job();p={'cursor':16,'saved':16,'taskType':'enrich'}
  self.store.database.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)',(second,'A','running',time.time(),time.time(),self.store.seal(data,second),self.store.seal(p,second),'legacy'))
  self.store.database.commit();self.store.close();self.store=TaskStore(self.temp.name)
  self.assertEqual(self.store.get(original['id'])['status'],'merged');self.assertEqual(self.store.get(original['id'])['progress']['mergedInto'],second)
  self.assertEqual(self.store.next()['id'],second);self.assertEqual(self.store.get(second)['progress']['cursor'],16)
  self.assertEqual(self.store.database.execute('SELECT count(*) FROM tasks').fetchone()[0],2)
 def test_import_runs_ahead_of_background_decoration(self):
  self.store.add('A',self.job(),'decoration');i=self.store.add('A',{'kind':'import'},'import')
  self.assertEqual(self.store.next()['id'],i['id'])
