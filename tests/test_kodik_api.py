"""Kodik response contracts are fixtures; no third-party credentials used."""
import concurrent.futures,tempfile,time,unittest
from unittest.mock import patch
from fastapi import FastAPI,Header,HTTPException
from fastapi.testclient import TestClient
import kodik_api,metadata_catalog
from task_store import TaskStore

ROW={'id':'serial-42','type':'anime-serial','title':'Тестовое аниме','title_orig':'Fixture anime','year':2024,'shikimori_id':'123','link':'https://kodikplayer.com/serial/42/abc/720p','translation':{'id':9,'title':'Studio A','type':'voice'},'seasons':{'1':{'link':'https://kodikplayer.com/serial/42/abc/720p?season=1','episodes':{'1':'//kodikplayer.com/serial/42/abc/720p?season=1&episode=1','3':'//kodikplayer.com/serial/42/abc/720p?season=1&episode=3'}}}}

class KodikTests(unittest.TestCase):
 def setUp(self):kodik_api._cache.clear();kodik_api._inspections.clear()
 def test_only_published_episodes_and_named_translations(self):
  value=kodik_api.inspect_result(ROW,'anime')
  self.assertEqual([e['number'] for e in value['episodes']],[1,3])
  self.assertEqual(value['seasons'][0]['number'],1)
  self.assertIsNone(kodik_api.inspect_result({**ROW,'link':'https://127.0.0.1/private'},'anime'))
  self.assertIsNone(kodik_api.inspect_result({**ROW,'translation':{'title':'Неизвестный автор'}},'anime'))
  self.assertIsNone(kodik_api.inspect_result({**ROW,'seasons':{}},'anime'))
 def test_exact_ids_and_short_catalogue_cache_skip_repeat_scraping(self):
  with patch.object(kodik_api,'token',return_value='owner-fixture'),patch.object(kodik_api,'call',return_value={'results':[ROW,{**ROW,'shikimori_id':'999'}]}) as network:
   selected={'title':'Different localized name','kind':'anime','ids':{'mal':'123'}}
   first=kodik_api.discover(selected);second=kodik_api.discover(selected)
   self.assertEqual(len(first['sources']),1);self.assertEqual(first,second);self.assertEqual(network.call_count,1)
   self.assertEqual(kodik_api.cached_inspection(ROW['link'],1)['episodes'][1]['number'],3)
   self.assertNotIn('owner-fixture',str(first))
 def test_tv_series_kind_and_season_parser(self):
  row={**ROW,'type':'foreign-serial','imdb_id':'tt123','shikimori_id':None}
  with patch.object(kodik_api,'token',return_value='owner-fixture'),patch.object(kodik_api,'call',return_value={'results':[row]}) as call:
   result=kodik_api.discover({'title':row['title'],'kind':'tv','ids':{'imdb':'tt123'}})
   self.assertEqual(result['sources'][0]['kind'],'tv');self.assertEqual(call.call_args[0][2]['imdb_id'],'tt123')
 def test_owner_key_is_validated_then_encrypted_and_never_returned(self):
  with tempfile.TemporaryDirectory() as directory:
   store=TaskStore(directory);app=FastAPI()
   def owner(authorization:str=Header(default='')):
    if authorization!='Bearer owner':raise HTTPException(401)
    return 'owner'
   with patch.object(kodik_api,'_store',lambda:store):
    kodik_api.install(app,owner,lambda:store)
    with TestClient(app) as client,patch.object(kodik_api,'call',return_value={'results':[]}):
     key='fixture_key_not_a_real_token'
     self.assertEqual(client.put('/integrations/kodik',json={'token':key}).status_code,401)
     response=client.put('/integrations/kodik',headers={'Authorization':'Bearer owner'},json={'token':key})
     self.assertEqual(response.status_code,200);self.assertNotIn(key,response.text)
     self.assertEqual(store.setting('configuration:kodik')['token'],key)
     raw=store.database.execute("SELECT value FROM settings WHERE name='configuration:kodik'").fetchone()[0]
     self.assertNotIn(key.encode(),raw)
     self.assertNotIn(key,client.get('/integrations/kodik',headers={'Authorization':'Bearer owner'}).text)
    store.close()

class MetadataJoinTests(unittest.TestCase):
 def test_identical_requests_join_but_unrelated_requests_run_in_parallel(self):
  def load(provider,**options):time.sleep(.08);return options['identity']
  with patch.object(metadata_catalog,'_metadata',side_effect=load) as work,concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
   futures=[pool.submit(metadata_catalog.metadata,'fixture',identity='1') for _ in range(5)]
   other=pool.submit(metadata_catalog.metadata,'fixture',identity='2')
   self.assertEqual([f.result() for f in futures],['1']*5);self.assertEqual(other.result(),'2');self.assertEqual(work.call_count,2)
