"""Offline schema/quota/auth contracts. These tests do not run ML inference."""
import asyncio,base64,io,json,os,sqlite3,sys,tempfile
from pathlib import Path
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import patch
import httpx
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from gemma_translate import Batch,Page,Gateway,Quotas,packs,request_body,validate_reply,check_images
from gemma_jobs import GemmaJobs
from lmt_service import EncryptedCache
from fastapi import HTTPException

def page(id='P1',count=1):
 return Page(id=id,width=100,height=100,image='YQ=='*10,regions=[{'id':id+'_B'+str(i),'bbox':[1,2,80,90],'class':'text'} for i in range(count)])
def row(id='P1_B0',text='Привет'):
 return {'id':id,'translation':text,'status':'translated','font_style':'standard_comic','speech_style':'neutral_conversational','text_category':'dialogue','speaker_gender':'unknown','connected_to_id':None,'appearance':{'bold':False,'italic':False,'fill_color':'#000000','stroke_color':'none','stroke_width':0,'alignment':'center','rotation':0}}

class ProtocolTests(TestCase):
 def test_coordinate_and_id_integrity(self):
  with self.assertRaises(ValueError):Page(id='p',width=100,height=100,image='x'*20,regions=[{'id':'a','bbox':[0,0,101,20]}])
  with self.assertRaises(ValueError):Batch(pages=[page('same'),page('same')])
  with self.assertRaises(ValueError):Batch(pages=[page()],url='https://attacker.invalid')
 def test_dense_page_is_split_without_changing_placement(self):
  source=[page('P1',100),page('P2',20),page('P3',20),page('P4',20)]
  groups=list(packs(source));self.assertTrue(all(len(g)<=4 and sum(len(p.regions) for p in g)<=65 for g in groups))
  self.assertEqual([r.id for g in groups for p in g for r in p.regions],[r.id for p in source for r in p.regions])
 def test_duplicate_missing_and_empty_translations_are_rejected(self):
  pages=[page(count=2)]
  for rows in [[row(),row()],[row()],[row(),row('P1_B1','')]]:
   with self.assertRaises(ValueError):validate_reply(json.dumps(rows),pages)
  rows=[row(),{**row('P1_B1',''),'status':'non_text'}]
  self.assertEqual(len(validate_reply(json.dumps(rows),pages)),2)
 def test_style_cannot_inject_css_or_nonfinite_geometry(self):
  for field,value in [('fill_color','url(https://attacker.invalid)'),('rotation',float('nan')),('stroke_width',-1)]:
   r=row();r['appearance'][field]=value
   with self.assertRaises(ValueError):validate_reply(json.dumps([r]),[page()])
 def test_image_type_is_verified_against_bytes(self):
  image=io.BytesIO();Image.new('RGB',(10,10),'white').save(image,'PNG')
  p=page().model_copy(update={'image':base64.b64encode(image.getvalue()).decode(),'mime':'image/png'})
  check_images(Batch(pages=[p]))
  with self.assertRaises(ValueError):check_images(Batch(pages=[p.model_copy(update={'mime':'image/webp'})]))
 def test_no_source_transcription_or_client_key_in_request(self):
  body=request_body([page()],'Japanese','');text=json.dumps(body)
  self.assertNotIn('sourceText',text);self.assertNotIn('api_key',text)
  self.assertEqual(body['generationConfig']['maxOutputTokens'],16384)
  self.assertEqual(body['generationConfig']['responseJsonSchema']['properties']['regions']['type'],'array')

class QuotaTests(IsolatedAsyncioTestCase):
 async def test_reservation_survives_restart_and_accounts_for_actual_usage(self):
  with tempfile.TemporaryDirectory() as root:
   clock=[1000.];path=Path(root)/'quota.sqlite';q=Quotas(path,lambda:clock[0])
   id=await q.reserve('a',8000,lambda _:None);q.settle(id,9000);clock[0]+=13
   q=Quotas(path,lambda:clock[0]);self.assertGreater(q.wait_seconds('a',6000),40)
   self.assertEqual(q.wait_seconds('b',6000),0)
   with self.assertRaises(ValueError):q.wait_seconds('b',14501)
   clock[0]+=60;self.assertEqual(q.wait_seconds('a',6000),0)
 async def test_server_owned_key_fallback_and_reply_validation(self):
  calls=[]
  def handle(request):
   self.assertEqual(request.headers['x-goog-api-key'],'fixture-key');calls.append(request.url.path)
   if request.url.path.endswith(':countTokens'):return httpx.Response(200,json={'totalTokens':100})
   if '31b' in request.url.path:return httpx.Response(503,json={'error':{'message':'busy'}})
   return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps([row()])}]}}],'usageMetadata':{'promptTokenCount':95,'candidatesTokenCount':25,'totalTokenCount':120}})
  with tempfile.TemporaryDirectory() as root:
   key=Path(root)/'key';key.write_text('fixture-key')
   client=httpx.AsyncClient(transport=httpx.MockTransport(handle),headers={'x-goog-api-key':'fixture-key'})
   with patch.dict(os.environ,{'GEMMA_API_KEY_FILE':str(key)}),patch('gemma_translate.httpx.AsyncClient',return_value=client):
    result=await Gateway(root).translate(Batch(pages=[page()]),lambda _:None)
   self.assertEqual(result['pages'][0]['regions'][0]['translation'],'Привет')
   self.assertEqual([u['httpStatus'] for u in result['usage']],[503,200])
   self.assertEqual(sum(p.endswith(':generateContent') for p in calls),2)
   self.assertNotIn('fixture-key',json.dumps(result))

class JobTests(IsolatedAsyncioTestCase):
 async def test_owner_isolation_duplicate_submission_and_encrypted_cache(self):
  # Mock only inference; run the production queue and AES-GCM cache.
  started=asyncio.Event();release=asyncio.Event();calls=[]
  async def infer(batch,progress):
   calls.append(batch);started.set();await release.wait()
   return {'kind':'gemma-vision','pages':[{'id':'P1','regions':[row()]}]}
  with tempfile.TemporaryDirectory() as root:
   jobs=GemmaJobs(root,EncryptedCache);jobs.gateway.translate=infer;batch=Batch(pages=[page()])
   id=await jobs.submit(batch,'owner');await started.wait()
   self.assertEqual(await jobs.submit(batch,'owner'),id)
   with self.assertRaises(HTTPException) as denied:jobs.get(id,'another-owner')
   self.assertEqual(denied.exception.status_code,404)
   release.set();await jobs.queue.join();self.assertEqual(len(calls),1)
   self.assertNotIn('batch',jobs.get(id,'owner'))
   files=list((Path(root)/'gemma/results').glob('*.cache'));self.assertEqual(len(files),1)
   self.assertNotIn('Привет'.encode(),files[0].read_bytes());await jobs.close()
   restarted=GemmaJobs(root,EncryptedCache)
   cached=await restarted.submit(batch,'owner');self.assertTrue(restarted.get(cached,'owner')['result']['cacheHit'])
   await restarted.close()
 async def test_cancellation_removes_pending_page_and_result(self):
  started=asyncio.Event()
  async def infer(batch,progress):started.set();await asyncio.Event().wait()
  with tempfile.TemporaryDirectory() as root:
   jobs=GemmaJobs(root,EncryptedCache);jobs.gateway.translate=infer
   id=await jobs.submit(Batch(pages=[page()]),'owner');await started.wait();jobs.cancel(jobs.get(id,'owner'));await jobs.queue.join()
   value=jobs.get(id,'owner');self.assertEqual(value['state'],'cancelled');self.assertNotIn('batch',value);self.assertNotIn('result',value)
   await jobs.close()
