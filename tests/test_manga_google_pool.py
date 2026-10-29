"""Concurrent routing contract only; no real Google inference."""
import asyncio,sys,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from manga_batch.pool import GooglePool
from manga_batch.quota import QuotaPacer,Deferred
class PoolTests(unittest.IsolatedAsyncioTestCase):
 async def test_quota_retry_reuses_successful_parallel_siblings(self):
  class Settings:
   def setting(self,name):return {'slots':[{'slot':i,'key':'fixture-'+str(i)} for i in range(3)]}
  calls={}
  class Worker:
   def __init__(self,*args,**kwargs):self.models=[]
   async def translate(self,pages):
    page=pages[0]['page'];calls[page]=calls.get(page,0)+1
    if page==2 and calls[page]==1:raise Deferred(1)
    return {pages[0]['regions'][0]['uid']:{'ru_translation':'Привет!'}},{'cloudMs':2,'inputTokens':100,'outputTokens':20}
  pool=GooglePool(QuotaPacer(tpm=13000,rpm=14),'missing-fixture-file',Settings());pages=[{'page':i,'regions':[{'uid':'P'+str(i)+'_B1'}]} for i in range(1,4)]
  with patch('google.genai.Client',return_value=object()),patch('manga_batch.pool.GemmaBatchTranslator',Worker):
   with self.assertRaises(Deferred):await pool.translate(pages)
   self.assertEqual(len(pool.partial),2);result,metadata=await pool.translate(pages)
  self.assertEqual(calls,{1:1,2:2,3:1});self.assertEqual(len(result),3);self.assertEqual(metadata['inputTokens'],300);self.assertEqual(pool.partial,{})
 async def test_explicitly_removed_keys_never_reactivate_the_legacy_file(self):
  class Settings:
   def setting(self,name):return {'slots':[]}
  with tempfile.TemporaryDirectory() as directory:
   key=Path(directory)/'key';key.write_text('fixture-legacy-key')
   self.assertFalse(GooglePool(QuotaPacer(tpm=13000,rpm=14),key,Settings()).configured())
 async def test_independent_configured_credentials_split_three_pages(self):
  rows=[{'slot':i,'key':'fixture-'+str(i),'project':'project-'+str(i),'models':['gemini-3.5-flash-lite']} for i in range(3)]
  class Settings:
   def setting(self,name):return {'slots':rows}
  seen=[];ready=asyncio.Event()
  class Worker:
   def __init__(self,pacer,key_file,client,models):self.models=models;self.identity=client
   async def translate(self,pages):
    seen.append((self.identity,self.models[0]));
    if len(seen)==3:ready.set()
    await asyncio.wait_for(ready.wait(),2)
    return {pages[0]['regions'][0]['uid']:{'ru_translation':'Привет!'}},{'model':self.models[0],'cloudMs':5,'inputTokens':100,'outputTokens':20}
  pool=GooglePool(QuotaPacer(tpm=13000,rpm=14),'missing-fixture-file',Settings())
  with patch('google.genai.Client',side_effect=lambda api_key,**_:api_key),patch('manga_batch.pool.GemmaBatchTranslator',Worker):
   result,metadata=await pool.translate([{'page':i,'regions':[{'uid':'P'+str(i)+'_B1'}]} for i in range(1,4)])
  self.assertEqual(len({key for key,_ in seen}),3);self.assertTrue(all(model=='gemini-3.5-flash-lite' for _,model in seen));self.assertEqual(len(result),3);self.assertEqual(metadata['inputTokens'],300)
