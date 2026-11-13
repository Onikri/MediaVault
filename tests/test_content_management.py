"""Neutral private administration, global projections and source contracts."""
import copy,json,os,sqlite3,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from fastapi import HTTPException
from content_management import save,inventory,public_policy
import content_catalog
from manga_tag_policy import current,canonical_json
from manga_catalog_index import initialize,upsert,browse as manga_browse
from content_sources import html_terms,lib_terms,html_titles,lib_titles
from content_metadata import anilist_rows,movie_rows

BASE={'schemaVersion':1,'excludedTerms':['Hidden term'],'excludedPrefixes':[], 'tags':[
 {'key':'journey','label':'Путешествие','aliases':['Journey','旅','여행'],'category':'genre'},
 {'key':'private term','label':'Private term','aliases':['Hidden term']} ]}

class ContentFixture:
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'manga-tag-policy.json';self.path.write_bytes(canonical_json(BASE))
  self.env=patch.dict(os.environ,{'DATA_DIR':self.temp.name,'MANGA_TAG_POLICY_FILE':str(self.path)});self.env.start()
  self.db=sqlite3.connect(':memory:',check_same_thread=False);initialize(self.db);self.store=SimpleNamespace(db=self.db,lock=threading.RLock())
 def tearDown(self):self.db.close();self.env.stop();self.temp.cleanup()
 def seed(self):
  rows=[{'id':'fixture:'+kind,'provider':'fixture','kind':kind,'title':'Garden World','sourceUrl':'https://fixture.example/'+kind,'tags':['旅','Ecology'],'genres':[]} for kind in content_catalog.KINDS]
  content_catalog.ingest(self.db,rows)
  upsert(self.db,[{'provider':'fixture','kind':'manga','title':'Garden World','sourceUrl':'https://fixture.example/manga','tags':['여행','Ecology']}]);self.db.commit()

class ContentTests(ContentFixture,unittest.TestCase):
 def test_public_response_never_contains_private_exclusions_or_hidden_rules(self):
  value=public_policy();self.assertNotIn('Hidden term',json.dumps(value));self.assertNotIn('private term',json.dumps(value))
  self.assertEqual(value['policy']['excludedTerms'],[]);self.assertEqual(value['scope'],'all')
 def test_owner_edits_reclassify_all_kinds_delete_restore_and_match_retained_unknown_facts(self):
  self.seed()
  for kind in content_catalog.KINDS:self.assertEqual(content_catalog.browse(self.db,kind=kind,genre='Journey')['total'],1)
  policy=copy.deepcopy(BASE);policy['tags'][0]['category']='tag'
  result=save(self.store,policy,current().revision);self.assertEqual(result['reindexedTitles'],7)
  self.assertEqual(manga_browse(self.db,genre='Journey')['total'],0)
  for kind in content_catalog.KINDS:
   self.assertEqual(content_catalog.browse(self.db,kind=kind,genre='Journey')['total'],0)
   self.assertEqual(content_catalog.browse(self.db,kind=kind,tag='Journey')['total'],1)
  policy['tags']=[];save(self.store,policy,current().revision)
  for kind in content_catalog.KINDS:self.assertEqual(content_catalog.browse(self.db,kind=kind,tag='Journey')['total'],0)
  policy['tags']=[{'key':'ecology','label':'Экология','aliases':['Ecology'],'category':'genre'}]
  save(self.store,policy,current().revision)
  for kind in content_catalog.KINDS:self.assertEqual(content_catalog.browse(self.db,kind=kind,genre='Ecology')['total'],1)
  self.assertEqual(manga_browse(self.db,genre='Ecology')['total'],1)
  self.assertEqual(current().data['excludedTerms'],BASE['excludedTerms'])
 def test_conflicts_and_failures_preserve_saved_settings_and_index(self):
  self.seed();before=self.path.read_bytes();policy={**BASE,'tags':[]}
  with self.assertRaises(HTTPException) as result:save(self.store,policy,'a'*64)
  self.assertEqual(result.exception.status_code,409)
  with patch('content_catalog.reindex',side_effect=RuntimeError('fixture rollback')),self.assertRaises(RuntimeError):save(self.store,policy,current().revision)
  self.assertEqual(self.path.read_bytes(),before);self.assertEqual(manga_browse(self.db,tag='Journey')['total'],1)
 def test_inventory_preserves_unmatched_source_facts_and_suggests_without_auto_merging(self):
  self.seed();value=inventory(self.store,'Ecolog')
  self.assertEqual(value['items'][0]['label'],'Ecology');self.assertEqual(value['items'][0]['works'],7)
  self.assertEqual(value['items'][0]['keys'],[])
 def test_private_writes_reject_invalid_aliases_and_do_not_accept_commands(self):
  bad=copy.deepcopy(BASE);bad['tags'].append({'key':'duplicate','label':'Duplicate','aliases':['Journey']})
  for value in (bad,{**BASE,'shell':'echo test'}):
   with self.assertRaises(HTTPException) as result:save(self.store,value,current().revision)
   self.assertEqual(result.exception.status_code,422)
 def test_partial_provider_answers_preserve_raw_genres_for_later_alias_matching(self):
  self.seed()
  content_catalog.ingest(self.db,[{'id':'fixture:movie','provider':'fixture','kind':'movie','title':'Garden World','genres':[],'tags':[]}]);self.db.commit()
  self.assertEqual(content_catalog.browse(self.db,kind='movie',genre='Journey')['total'],1)
  data={**BASE,'tags':[{'key':'ecology','label':'Экология','aliases':['Ecology'],'category':'genre'}]}
  save(self.store,data,current().revision)
  row=content_catalog.browse(self.db,kind='movie',genre='Ecology')['items'][0]
  self.assertEqual(row['sourceUrl'],'https://fixture.example/movie')
 def test_source_taxonomy_extracts_exact_links_and_membership_without_images(self):
  terms=html_terms(b'<a rel="tag" href="/tags/ecology/">Ecology</a><a rel="tag" href="https://evil.example/a">Other</a>','https://hmanga.me/',{'hmanga.me'})
  self.assertEqual(len(terms),1);self.assertEqual(terms[0]['url'],'https://hmanga.me/tags/ecology/')
  raw=json.dumps({'data':{'tags':[{'id':12,'name':{'en':'Ecology'},'site_ids':[4]},{'id':13,'name':'Other','site_ids':[1]}]}}).encode()
  self.assertEqual(lib_terms(raw,4),[{'label':'Ecology','category':'tag','sourceId':12}])
  rows=lib_titles({'data':[{'slug_url':'123--garden','rus_name':'Garden'}]},4,'Ecology','tag')
  self.assertEqual(rows[0]['tags'],['Ecology']);self.assertNotIn('pages',rows[0])
 def test_generic_source_results_keep_source_provided_tags_and_types(self):
  rows=anilist_rows({'data':{'Page':{'media':[{'id':7,'idMal':8,'title':{'english':'Garden'},'genres':['Journey'],'tags':[{'name':'Ecology'}]}]}}},'ranobe')
  self.assertEqual(rows[0]['kind'],'ranobe');self.assertEqual(rows[0]['tags'],['Ecology'])
  rows=movie_rows({'data':{'items':[{'id':9,'title':{'russian':'Garden'},'type':'Series','genres':[{'name':'Journey'}]}]}},'tv')
  self.assertEqual(rows[0]['kind'],'tv');self.assertEqual(rows[0]['genres'],['Journey'])
 def test_explicit_aliases_follow_only_approved_source_mirrors(self):
  from manga_tag_policy import Policy
  data=copy.deepcopy(BASE);data['tags'][0]['sourceAliases']={'mangalib.org':['Road trip']}
  policy=Policy(data)
  self.assertEqual(policy.key('Road trip','mangalib.me'),'journey')
  self.assertEqual(policy.key('Road trip','other.example'),'')
  self.assertIn('mangalib.me',policy.public()['tags'][0]['sourceAliases'])
 def test_interrupted_refresh_recovers_saved_keys_without_changing_rules(self):
  from content_management import recover
  Path(self.temp.name,'content-index-job.json').write_text(json.dumps({'state':'running','keys':['journey']}))
  Path(self.temp.name,'content-pending-keys.json').write_text(json.dumps({'all':False,'keys':['ecology']}))
  with patch('content_management.start_scan') as start:recover(lambda:self.store)
  start.assert_called_once_with(self.store,['ecology','journey'])
  self.assertEqual(current().data,BASE)

class ContentHttpTests(ContentFixture,unittest.TestCase):
 def setUp(self):
  super().setUp();import api
  from fastapi.testclient import TestClient
  self.api=api;self.overrides=dict(api.app.dependency_overrides);self.client=TestClient(api.app)
  self.manager=patch('manga_discovery.manager',return_value=self.store);self.manager.start()
 def tearDown(self):self.client.close();self.api.app.dependency_overrides=self.overrides;self.manager.stop();super().tearDown()
 def test_only_owner_can_read_edit_refresh_or_submit_shared_facts(self):
  for path in ('/admin/content','/admin/content/vocabulary','/admin/content/job'):
   self.assertIn(self.client.get(path).status_code,(401,403))
  with patch.object(self.api,'token_payload',return_value={'sub':'viewer:fixture','role':'viewer'}):
   self.assertEqual(self.client.get('/admin/content').status_code,403)
   self.assertEqual(self.client.post('/admin/content/refresh').status_code,403)
  self.api.app.dependency_overrides[self.api.content_owner]=lambda:'fixture-owner'
  response=self.client.get('/admin/content');self.assertEqual(response.status_code,200);self.assertEqual(response.json()['policy'],BASE)
  with patch('content_management.start_scan',return_value={'state':'queued'}) as scan:
   data={**BASE,'tags':[{'key':'ecology','label':'Ecology','aliases':[]}]}
   result=self.client.put('/admin/content/policy',json={'revision':current().revision,'policy':data})
   self.assertEqual(result.status_code,200);scan.assert_called_once()
  self.assertEqual(self.client.get('/admin/content').json()['policy'],data)
  self.assertEqual(self.client.post('/ops/manga-tags/update',json={'commit':'a'*40,'policy':BASE}).status_code,410)
 def test_guest_and_share_roles_are_denied_even_with_a_valid_signed_payload(self):
  for role in ('guest','share','viewer'):
   with patch.object(self.api,'token_payload',return_value={'sub':role+':fixture','role':role}):
    self.assertEqual(self.client.get('/admin/content').status_code,403)
    self.assertEqual(self.client.put('/admin/content/policy',json={'revision':current().revision,'policy':BASE}).status_code,403)
    self.assertEqual(self.client.post('/catalog/content/facts',json={'items':[]}).status_code,403)

if __name__=='__main__':unittest.main()
