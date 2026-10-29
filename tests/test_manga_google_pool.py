"""Concurrent routing contract only; no real Google inference."""
import asyncio,sys,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from manga_batch.pool import GooglePool
from manga_batch.quota import QuotaPacer,Deferred
class PoolTests(unittest.IsolatedAsyncioTestCase):
 async def test_explicitly_removed_keys_never_reactivate_the_legacy_file(self):
  class Settings:
   def setting(self,name):return {'slots':[]}
  with tempfile.TemporaryDirectory() as directory:
   key=Path(directory)/'key';key.write_text('fixture-legacy-key')
   self.assertFalse(GooglePool(QuotaPacer(tpm=13000,rpm=14),key,Settings()).configured())
 async def test_three_credentials_each_receive_one_pack_of_three_pages(self):
  rows=[{'slot':i,'key':'fixture-'+str(i),'project':'project-'+str(i),'models':['gemini-3.5-flash-lite']} for i in range(3)]
  class Settings:
   def setting(self,name):return {'slots':rows}
  seen=[];ready=asyncio.Event()
  class Worker:
   def __init__(self,pacer,key_file,client,models):self.models=models;self.identity=client
   async def translate(self,pages):
    seen.append((self.identity,[p['page'] for p in pages]))
    if len(seen)==3:ready.set()
    await asyncio.wait_for(ready.wait(),2)
    return {r['uid']:{'ru_translation':'Привет!'} for p in pages for r in p['regions']},{'cloudMs':5}
  pool=GooglePool(QuotaPacer(tpm=13000,rpm=14),'missing-fixture-file',Settings())
  with patch('google.genai.Client',side_effect=lambda api_key,**_:api_key),patch('manga_batch.pool.GemmaBatchTranslator',Worker):
   results=await asyncio.gather(*(pool.translate([{'page':i,'regions':[{'uid':'P'+str(i)+'_B1'}]} for i in range(start,start+3)]) for start in [1,4,7]))
  self.assertEqual(len({key for key,_ in seen}),3);self.assertEqual(sorted(pack for _,pack in seen),[[1,2,3],[4,5,6],[7,8,9]]);self.assertTrue(all(len(result)==3 for result,_ in results))
 async def test_quota_error_is_propagated_without_switching_accounts(self):
  class Settings:
   def setting(self,name):return {'slots':[{'slot':i,'key':'fixture-'+str(i)} for i in range(3)]}
  calls=[]
  class Worker:
   def __init__(self,*args,**kwargs):pass
   async def translate(self,pages):calls.append(len(pages));raise Deferred(30)
  pool=GooglePool(QuotaPacer(tpm=13000,rpm=14),'missing-fixture-file',Settings())
  with patch('google.genai.Client',return_value=object()),patch('manga_batch.pool.GemmaBatchTranslator',Worker):
   with self.assertRaises(Deferred):await pool.translate([{'page':i} for i in range(3)])
  self.assertEqual(calls,[3])
 async def test_same_credential_serializes_whole_packs(self):
  class Settings:
   def setting(self,name):return {'slots':[{'slot':0,'key':'fixture-key'}]}
  active=0;peak=0;calls=[]
  class Worker:
   def __init__(self,*args,**kwargs):pass
   async def translate(self,pages):
    nonlocal active,peak
    active+=1;peak=max(peak,active);calls.append(len(pages));await asyncio.sleep(.01);active-=1;return {},{}
  pool=GooglePool(QuotaPacer(),'missing-fixture-file',Settings())
  with patch('google.genai.Client',return_value=object()),patch('manga_batch.pool.GemmaBatchTranslator',Worker):
   await asyncio.gather(*(pool.translate([{'page':i}]*3) for i in range(3)))
  self.assertEqual(peak,1);self.assertEqual(calls,[3,3,3])
