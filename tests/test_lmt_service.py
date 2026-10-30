"""Service/cache boundary tests use fake inference; not model-quality evidence."""
import asyncio
import base64
import json
from pathlib import Path
import sys
import tempfile
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from fastapi import HTTPException
from lmt_service import EncryptedCache,Processor,Options,owner
class CacheTests(TestCase):
 def test_intermediate_debug_images_are_memory_only(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=EncryptedCache(tmp);c.write('debug',{'renderedImage':'page','debug':{'cleanedImage':'intermediate'}})
   self.assertNotIn('debug',c.read('debug'))
 def test_ciphertext_scoped_to_image_user_model_font(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=EncryptedCache(tmp);o=Options().model_dump();k=c.identity('u1',b'page',o);r={'renderedImage':'webp','regions':[{'text':'Привет'}]};c.write(k,r)
   self.assertEqual(c.read(k),r);self.assertNotIn(b'webp',Path(tmp,k+'.cache').read_bytes());self.assertNotEqual(k,c.identity('u2',b'page',o));self.assertNotEqual(k,c.identity('u1',b'page',{**o,'font':'neucha'}))
   c.write(c.identity('u1',b'other',o),{**r,'warnings':['inpaint failed']});self.assertEqual(len(list(Path(tmp).glob('*.cache'))),1)
 def test_corrupt_cache_and_limits(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=EncryptedCache(tmp,limit=200);c.write('a',{'renderedImage':'x'*300});self.assertIsNone(c.read('a'))
   Path(tmp,'b.cache').write_bytes(b'corrupt');self.assertIsNone(c.read('b'))
class QueueTests(IsolatedAsyncioTestCase):
 async def test_deduplicates_and_reuses_disk_without_inference(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Processor(tmp);p.runtime.run=AsyncMock(return_value={'renderedImage':'webp','regions':[]})
   a=await p.submit(b'image',Options().model_dump(),'a');await p.worker
   self.assertEqual(a,await p.submit(b'image',Options().model_dump(),'a'));self.assertEqual(p.get(a,'a')['state'],'done')
   with self.assertRaises(HTTPException):p.get(a,'b')
   p.jobs.clear();b=await p.submit(b'image',Options().model_dump(),'a');self.assertTrue(p.get(b,'a')['result']['cacheHit']);self.assertEqual(p.runtime.run.await_count,1);await p.close()
 async def test_cancel_active_and_next_job_still_runs(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Processor(tmp);started=asyncio.Event()
   async def run(data,config,progress):
    if data==b'a':started.set();await asyncio.sleep(60)
    return {'renderedImage':'ok','regions':[]}
   p.runtime.run=run;a=await p.submit(b'a',Options().model_dump(),'u');b=await p.submit(b'b',Options().model_dump(),'u');await started.wait();p.cancel(p.get(a,'u'));await p.worker;self.assertEqual(p.get(a,'u')['state'],'cancelled');self.assertEqual(p.get(b,'u')['state'],'done');await p.close()
 async def test_unverified_sessions_are_rejected(self):
  token=base64.urlsafe_b64encode(json.dumps({'sub':'attacker'}).encode()).decode()+'.fake'
  with patch('httpx.AsyncClient.get',new=AsyncMock(return_value=type('R',(),{'status_code':401})())):
   with self.assertRaises(HTTPException):await owner('Bearer '+token)

class RouteTests(TestCase):
 def test_public_status_protected_jobs_and_sanitized_invalid_input(self):
  from fastapi.testclient import TestClient
  from lmt_service import app
  with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'LMT_DATA_DIR':tmp,'LMT_ASSETS_DIR':tmp}):
   with TestClient(app) as client:
    self.assertFalse(client.get('/reader/lmt/status').json()['ready'])
    self.assertEqual(client.post('/reader/lmt/jobs',json={'image':'x'*20,'options':{}}).status_code,401)
    app.dependency_overrides[owner]=lambda:'fixture-owner'
    try:
     r=client.post('/reader/lmt/jobs',json={'image':'private-page-fixture','options':{'host':'http://attacker.invalid'}})
     self.assertEqual(r.status_code,422);self.assertNotIn('private-page-fixture',r.text);self.assertNotIn('attacker.invalid',r.text)
    finally:app.dependency_overrides.clear()
