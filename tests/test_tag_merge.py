"""Batched owner-approved tag merges: only affected titles, resumable, additive."""
import copy,json,os,sqlite3,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import content_catalog,manga_catalog_index,tag_merge
from manga_tag_policy import Policy,current,canonical_json
from manga_catalog_index import initialize,upsert,browse as manga_browse,tags as manga_tags

BASE={'schemaVersion':1,'includeDiscovered':True,'hiddenTags':[],'excludedTerms':[],'excludedPrefixes':[],'tags':[
 {'key':'большая грудь','label':'Большая грудь','aliases':['Большая грудь']}]}
NEW=copy.deepcopy(BASE)
NEW['tags'][0]['aliases'].append('Big Breasts')
NEW['tags'].append({'key':'accidents','label':'Accidents','aliases':['Accident']})
NEW['hiddenTags']=['Leak Title Tag']
MANGA=[('A',['Big Breasts']),('B',['Большая грудь']),('C',['Accident']),('D',['Accidents','Unrelated']),('E',['Unrelated','Leak Title Tag'])]

class MergeFixture:
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.path=self.root/'manga-tag-policy.json';self.path.write_bytes(canonical_json(BASE))
  self.env=patch.dict(os.environ,{'DATA_DIR':self.temp.name,'MANGA_TAG_POLICY_FILE':str(self.path)});self.env.start()
  self.db=sqlite3.connect(':memory:',check_same_thread=False);initialize(self.db)
  self.store=SimpleNamespace(db=self.db,lock=threading.RLock())
  upsert(self.db,[{'provider':'fixture','kind':'manga','title':'Work '+name if name!='E' else 'Leak Title Tag','sourceUrl':'https://fixture.example/'+name,'tags':values} for name,values in MANGA])
  content_catalog.ingest(self.db,[{'id':'fixture:'+name,'provider':'fixture','kind':'anime','title':'Show '+name,'sourceUrl':'https://fixture.example/a'+name,'tags':values,'genres':[]} for name,values in [('1',['Big Breasts']),('2',['Unrelated'])]])
  self.db.commit()
  patch.object(tag_merge,'PAUSE',0).start()
 def tearDown(self):patch.stopall();self.db.close();self.env.stop();self.temp.cleanup()
 def facts(self):
  return (sorted(self.db.execute('SELECT * FROM catalog_tag_facts')),sorted(self.db.execute('SELECT * FROM content_tag_facts')),
          self.db.execute('SELECT COUNT(*) FROM catalog_titles').fetchone()[0],self.db.execute('SELECT COUNT(*) FROM content_titles').fetchone()[0])
 def drop(self,policy=NEW):(self.root/tag_merge.PENDING).write_text(json.dumps(policy,ensure_ascii=False),encoding='utf-8')
 def run_all(self):
  while tag_merge.step(self.store,pause=0):pass
 def total(self,tag):return manga_browse(self.db,tag=tag)['total']

class TagMergeTests(MergeFixture,unittest.TestCase):
 def test_only_affected_titles_are_recomputed_and_every_member_finds_the_group(self):
  self.assertEqual(self.total('Большая грудь'),1);self.assertEqual(self.total('Accidents'),1)
  before=self.facts();seen=[]
  real_manga,real_content=manga_catalog_index.reproject_title,content_catalog._index
  def manga(conn,identity,raw,policy,**kw):seen.append(json.loads(raw)['title']);return real_manga(conn,identity,raw,policy,**kw)
  def content(db,identity,row,policy):seen.append(row['title']);return real_content(db,identity,row,policy)
  with patch('manga_catalog_index.reindex',side_effect=AssertionError('full reindex')),patch('content_catalog.reindex',side_effect=AssertionError('full reindex')),\
       patch.object(manga_catalog_index,'reproject_title',manga),patch.object(content_catalog,'_index',content):
   self.drop();self.run_all()
  self.assertEqual(sorted(seen),['Show 1','Work A','Work C'])
  for label in ('Большая грудь','Big Breasts','big breasts'):self.assertEqual(self.total(label),2,label)
  for label in ('Accident','Accidents'):self.assertEqual(self.total(label),2,label)
  self.assertEqual(self.total('Unrelated'),2)
  for label in ('Большая грудь','Big Breasts'):self.assertEqual(content_catalog.browse(self.db,kind='anime',tag=label)['total'],1)
  self.assertEqual(self.facts(),before)
  job=tag_merge.read_job();self.assertEqual((job['state'],job['total'],job['processed']),('done',3,3))
  self.assertEqual(tag_merge.status()['tagMerge']['remaining'],0)

 def test_policy_revision_is_stored_like_save_and_restart_needs_no_reindex(self):
  self.drop();self.run_all();revision=Policy(NEW).revision
  self.assertEqual(current().revision,revision)
  self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')),NEW)
  self.assertEqual(self.db.execute("SELECT value FROM catalog_policy_state WHERE name='revision'").fetchone()[0],revision)
  self.assertEqual(self.db.execute("SELECT value FROM content_catalog_state WHERE name='policy'").fetchone()[0],revision)
  with patch('manga_catalog_index.reindex',side_effect=AssertionError('full reindex')):initialize(self.db)
  with patch('content_catalog._index',side_effect=AssertionError('full reindex')):content_catalog.initialize(self.db)
  self.assertFalse((self.root/tag_merge.PENDING).exists());self.assertTrue((self.root/'tag-merge-applied.json').exists())
  saved=json.loads((self.root/tag_merge.PREVIOUS).read_text(encoding='utf-8'))
  self.assertEqual(saved['policy'],BASE)

 def test_hidden_labels_apply_at_publication_and_titles_stay_searchable(self):
  self.drop();self.assertTrue(tag_merge.step(self.store,pause=0))
  self.assertEqual(tag_merge.read_job()['phase'],'collect')
  from content_vocabulary import public
  self.assertNotIn('Leak Title Tag',json.dumps(public(self.store),ensure_ascii=False))
  self.run_all()
  listed={row['key'] for row in manga_tags(self.db,limit=500)['tags']}
  self.assertEqual(listed,{'большая грудь','accidents','unrelated'})
  self.assertEqual(self.total('Leak Title Tag'),0)
  self.assertEqual(manga_browse(self.db,q='Leak Title Tag')['total'],1)
  self.assertIn(('Leak Title Tag',),list(self.db.execute("SELECT original FROM catalog_tag_facts WHERE original='Leak Title Tag'")))
  for key in ('большая грудь','accidents'):self.assertNotIn(key,current().hidden)

 def test_interrupted_batches_resume_without_losing_or_repeating_titles(self):
  self.drop()
  with patch.object(tag_merge,'BATCH',1):
   tag_merge.step(self.store,pause=0);tag_merge.step(self.store,pause=0)
   self.assertEqual(tag_merge.read_job()['total'],3)
   crash=RuntimeError('crash')
   with patch.object(manga_catalog_index,'reproject_title',side_effect=crash),patch.object(content_catalog,'_index',side_effect=crash),self.assertRaises(RuntimeError):tag_merge.step(self.store,pause=0)
   self.assertEqual(self.db.execute('SELECT COUNT(*) FROM tag_merge_queue').fetchone()[0],3)
   tag_merge.step(self.store,pause=0)
   self.assertEqual(self.db.execute('SELECT COUNT(*) FROM tag_merge_queue').fetchone()[0],2)
   self.assertEqual(tag_merge.read_job()['processed'],1)
   # A restart re-reads only the job file and the queue.
   self.run_all()
  job=tag_merge.read_job();self.assertEqual((job['state'],job['processed']),('done',3))
  self.assertEqual(self.total('Большая грудь'),2);self.assertEqual(self.total('Accidents'),2)

 def test_restart_after_publication_before_job_record_continues(self):
  self.drop()
  with patch.object(tag_merge,'collect',side_effect=SystemExit):
   tag_merge.step(self.store,pause=0)
   with self.assertRaises(SystemExit):tag_merge.step(self.store,pause=0)
  (self.root/tag_merge.JOB).unlink();(self.root/'tag-merge-applied.json').replace(self.root/tag_merge.PENDING)
  self.run_all()
  self.assertEqual(tag_merge.read_job()['state'],'done');self.assertEqual(self.total('Big Breasts'),2)

 def test_policies_that_remove_or_change_anything_are_rejected(self):
  before=self.path.read_bytes();facts=self.facts()
  for change in (lambda p:p['tags'].pop(0),lambda p:p['tags'][0]['aliases'].remove('Большая грудь'),
                 lambda p:p.update(excludedTerms=['x']),lambda p:p['tags'][0].update(label='Грудь')):
   policy=copy.deepcopy(NEW);change(policy);self.drop(policy);self.run_all()
   self.assertEqual(tag_merge.read_job()['state'],'rejected');self.assertEqual(self.path.read_bytes(),before)
   self.assertFalse((self.root/tag_merge.PENDING).exists())
  self.assertEqual(self.facts(),facts);self.assertEqual(self.total('Big Breasts'),1)
  self.assertEqual(tag_merge.additive_problems(BASE,NEW),[])
  shrink=copy.deepcopy(NEW);self.drop(NEW);self.run_all();shrink['hiddenTags']=[]
  self.assertEqual(tag_merge.additive_problems(NEW,shrink),['hidden labels removed'])

if __name__=='__main__':unittest.main()
