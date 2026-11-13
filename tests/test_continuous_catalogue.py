"""Neutral cursor, automatic vocabulary and exclusion visibility contracts."""
import copy,json,os,sqlite3,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from manga_tag_policy import current,canonical_json
from manga_catalog_index import initialize,upsert,browse,tags
from content_management import save,public_policy
from catalogue_indexer import Indexer
import content_catalog

BASE={'schemaVersion':1,'includeDiscovered':True,'hiddenTags':[],'excludedTerms':['Hidden word'],'excludedPrefixes':[], 'tags':[]}

class ContinuousTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'manga-tag-policy.json';self.path.write_bytes(canonical_json(BASE))
  self.env=patch.dict(os.environ,{'DATA_DIR':self.temp.name,'MANGA_TAG_POLICY_FILE':str(self.path),'MEDIA_VAULT_DISABLE_WORKER':'1'});self.env.start()
  self.db=sqlite3.connect(':memory:',check_same_thread=False);initialize(self.db);content_catalog.initialize(self.db);self.store=SimpleNamespace(db=self.db,lock=threading.RLock());self.now=10000
 def tearDown(self):self.db.close();self.env.stop();self.temp.cleanup()
 def row(self,page=1):return {'provider':'fixture','kind':'manga','title':'Garden '+str(page),'url':'https://fixture.example/title/'+str(page),'sourceUrl':'https://fixture.example/title/'+str(page),'genres':['Ecology'],'tags':['Hidden word'],'language':'en'}
 def seed(self):
  upsert(self.db,[self.row()])
  content_catalog.ingest(self.db,[{**self.row(),'id':'fixture:movie','kind':'movie'}]);self.db.commit()
 def test_unconfigured_source_tags_are_visible_and_exclusions_hide_only_names(self):
  self.seed();self.assertEqual(browse(self.db,genre='Ecology')['total'],1)
  self.assertEqual(content_catalog.browse(self.db,kind='movie',genre='Ecology')['total'],1)
  self.assertEqual(browse(self.db)['total'],1);self.assertEqual(browse(self.db)['items'][0]['tags'],[])
  public=public_policy(self.store)
  self.assertIn('Ecology',[r['label'] for r in public['policy']['tags']]);self.assertNotIn('Hidden word',json.dumps(public))
  self.assertEqual(current().data['tags'],[])
 def test_unblocking_a_name_restores_all_retained_matches_without_network_or_corpus_rewrite(self):
  self.seed();data=copy.deepcopy(BASE);data['excludedTerms']=[]
  with patch('manga_catalog_index.reindex',side_effect=AssertionError('must not rebuild')),patch('content_catalog.reindex',side_effect=AssertionError('must not rebuild')):save(self.store,data,current().revision)
  self.assertEqual(browse(self.db,tag='Hidden word')['total'],1)
  self.assertEqual(content_catalog.browse(self.db,kind='movie',tag='Hidden word')['total'],1)
  self.assertIn('Hidden word',[r['label'] for r in public_policy(self.store)['policy']['tags']])
  data['hiddenTags']=['Ecology'];save(self.store,data,current().revision)
  self.assertEqual(browse(self.db)['total'],1);self.assertEqual(browse(self.db)['items'][0]['genres'],[])
  self.assertNotIn('ecology',{r['key'] for r in tags(self.db)['tags']})
  data['hiddenTags']=[];save(self.store,data,current().revision);self.assertEqual(browse(self.db,genre='Ecology')['total'],1)
 def test_deleting_a_custom_rule_cannot_reappear_as_an_automatic_alias(self):
  data=copy.deepcopy(BASE);data['tags']=[{'key':'journey','label':'Путь','aliases':['Journey']}]
  save(self.store,data,current().revision)
  upsert(self.db,[{**self.row(),'genres':['Journey']}]);self.db.commit()
  data['tags']=[];save(self.store,data,current().revision)
  self.assertEqual(browse(self.db)['items'][0]['genres'],[])
  self.assertIn('Journey',current().data['hiddenTags'])
 def test_cursor_crawls_beyond_first_batches_and_survives_recreation(self):
  called=[]
  def fetch(spec,cursor):
   p=cursor['page'];called.append(p);return {'rows':[self.row(p)],'next':{'page':p+1} if p<7 else None}
  worker=Indexer(self.store,fetch,lambda:self.now,interval=0)
  with self.store.lock,self.db:worker.enqueue({'type':'lib','domain':'fixture.example','name':'Fixture','site':1})
  for _ in range(3):self.assertTrue(worker.run_once());self.now+=3
  worker=Indexer(self.store,fetch,lambda:self.now,interval=0)
  for _ in range(4):self.assertTrue(worker.run_once());self.now+=3
  self.assertEqual(called,list(range(1,8)));self.assertEqual(browse(self.db)['total'],7)
  self.assertEqual(worker.status()['sources'][0]['status'],'done')
 def test_repeated_or_empty_intermediate_pages_are_not_marked_as_completed(self):
  worker=Indexer(self.store,lambda s,c:{'rows':[self.row()],'next':{'page':c['page']+1}},lambda:self.now,interval=0)
  with self.store.lock,self.db:worker.enqueue({'type':'lib','domain':'fixture.example','name':'Fixture','site':1})
  worker.run_once();self.now+=3;worker.run_once()
  self.assertEqual(worker.status()['sources'][0]['status'],'retry');self.assertEqual(browse(self.db)['total'],1)
 def test_generic_catalogue_sql_filter_and_paging_preserve_total(self):
  # A small indexed fixture checks SQL paging/total independently of the result
  # limit; no artificial source corpus or network request is needed.
  content_catalog.ingest(self.db,[{**self.row(p),'id':str(p),'kind':'book'} for p in range(1,9)]);self.db.commit()
  result=content_catalog.browse(self.db,kind='book',genre='Ecology',limit=2,offset=4)
  self.assertEqual(result['total'],8);self.assertEqual(len(result['items']),2);self.assertEqual(result['offset'],4)

class Http2Contracts(unittest.TestCase):
 def test_lib_catalogue_keeps_cover_and_detail_summary_without_fetching_images(self):
  from content_sources import lib_titles,lib_metadata
  payload={'slug_url':'1--garden','rus_name':'Сад','eng_name':'Garden','cover':{'default':'https://covers.example/garden.jpg'},'summary':'<p>A peaceful garden.</p>'}
  row=lib_titles({'data':[payload]},1,'','tag')[0]
  self.assertEqual(row['cover'],'https://covers.example/garden.jpg');self.assertEqual(row['description'],'A peaceful garden.')
  self.assertIn('Garden',row['aliases']);self.assertEqual(lib_metadata({'summary':'<p>Updated.</p>'})['description'],'Updated.')
  self.assertEqual(lib_metadata({'summary':{'type':'doc','content':[{'type':'paragraph','content':[{'type':'text','text':'A garden.'}]}]}})['description'],'A garden.')
 def test_book_catalogue_has_a_stable_sort_and_advances_offset(self):
  from catalogue_sources import fetch
  with patch('metadata_catalog.get_json',return_value={'numFound':100,'docs':[{'key':'/works/OL1W','title':'Garden','subject':['Ecology']}]}) as get:
   result=fetch({'type':'books','kind':'book'},{'page':2})
  self.assertEqual(get.call_args.kwargs['params']['sort'],'key');self.assertEqual(get.call_args.kwargs['params']['offset'],40)
  self.assertEqual(result['next'],{'page':3})
 def test_required_http2_transport_can_be_created_without_network(self):
  import httpx
  with httpx.Client(http2=True):pass
 def test_catalogue_route_uses_tag_id_and_never_requests_invalid_list_fields(self):
  import httpx
  from catalogue_sources import fetch
  seen=[]
  spec={'type':'lib','site':1,'domain':'mangalib.org','referer':'https://mangalib.me/','term':{'category':'tag','sourceId':12,'label':'Ecology'}}
  def getter(client,url,hosts,headers=None):
   self.assertEqual(client.headers['Site-id'],'1');self.assertEqual(client.headers['Referer'],'https://mangalib.me/')
   request=httpx.Request('GET',url);seen.append(request)
   return json.dumps({'data':[{'slug_url':'123--garden','rus_name':'Garden'}],'meta':{'has_next_page':False}}).encode(),url
  with patch('catalogue_sources.checked_get',side_effect=getter):result=fetch(spec,{'page':1})
  self.assertEqual(seen[-1].url.params['tags[]'],'12');self.assertNotIn('fields[]',seen[-1].url.params)
  self.assertEqual(result['rows'][0]['tags'],['Ecology']);self.assertIsNone(result['next'])

if __name__=='__main__':unittest.main()
