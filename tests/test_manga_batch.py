"""Real image/ZIP/cache operations; Google calls are explicit SDK fixtures."""
import asyncio,base64,hashlib,hmac,io,json,os,sqlite3,sys,tempfile,time,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image
from manga_batch.detector import combine_boxes
from manga_batch.contracts import validate_reply
from manga_batch.cache import JsonCache
from manga_batch.quota import QuotaPacer,Deferred
from manga_batch.source import Archive,ReadOnlySettings,manifest
from manga_batch.orchestrator import RealtimeChapterOrchestrator
from manga_batch.provider import GemmaBatchTranslator
from vault_drive import seal_chunk,CHUNK_SIZE

def row(uid):return {'uid':uid,'source_lang':'en','text_category':'dialogue','font_style':'standard_comic','speech_register':'neutral_conversational','speaker_gender':'unknown','source_text':'Hello','ru_translation':'Привет'}
def box(label,b,confidence=.9):return {'label':label,'bbox':b,'confidence':confidence}
class Geometry(unittest.TestCase):
 def test_nested_bubble_is_not_translated_twice_and_layout_partitions(self):
  r=combine_boxes([box(0,[0,0,200,200]),box(1,[30,20,80,60]),box(1,[30,120,90,160]),box(1,[30,20,80,60],.8),box(2,[250,40,290,90]),box(2,[0,0,5,5]),box(1,[5,6,45,46],.2)],300,300,7)
  self.assertEqual(len(r),3);self.assertEqual(r[0]['uid'],'P7_B1');self.assertEqual(r[0]['bubble_bbox'],[0,0,200,200]);self.assertLessEqual(r[0]['layout_bbox'][3],r[2]['layout_bbox'][1]);self.assertIsNone(r[1]['bubble_bbox'])
 def test_model_cannot_add_duplicate_or_missing_boxes(self):
  for values in [[row('P1_B1')]*2,[row('P1_B2')],[]]:
   with self.assertRaises(ValueError):validate_reply(values,['P1_B1'])
  a=row('P1_B1');a['connected_to_uid']='P1_B2';b=row('P1_B2');b['connected_to_uid']='P1_B1'
  with self.assertRaises(ValueError):validate_reply([a,b],['P1_B1','P1_B2'])
 def test_real_encrypted_range_cbz_no_temporary_images(self):
  data=io.BytesIO()
  with zipfile.ZipFile(data,'w',compression=zipfile.ZIP_STORED) as z:
   z.writestr('1.png',b'first');z.writestr('2.png',os.urandom(CHUNK_SIZE+20))
  raw=data.getvalue();key=os.urandom(32);chunks=[];parts={}
  for i in range(0,len(raw),CHUNK_SIZE):
   n=i//CHUNK_SIZE;c=seal_chunk(raw[i:i+CHUNK_SIZE],key,'book',n);parts[str(n)]=c['ciphertext'];chunks.append({'fileId':str(n),'iv':c['iv']})
  class Drive:
   def download(self,id):return parts[id]
  item={'id':'book','size':len(raw),'chunks':chunks};archive=Archive(Drive(),key,item)
  self.assertEqual(archive.names(),['1.png','2.png']);self.assertEqual(archive.page('1.png'),b'first');self.assertEqual(len(archive.page('2.png')),CHUNK_SIZE+20);self.assertLessEqual(len(archive.chunks),4)
  archive.acquire();archive.close();self.assertEqual(archive.page('1.png'),b'first');archive.release();self.assertIsNone(archive.key)
 def test_readonly_importer_setting_and_auth_do_not_mutate_tasks(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);key=os.urandom(32);(root/'service.key').write_bytes(key)
   db=sqlite3.connect(root/'tasks.sqlite');db.executescript("CREATE TABLE settings(name TEXT,value BLOB);CREATE TABLE tasks(status TEXT);INSERT INTO tasks VALUES('running');")
   nonce=os.urandom(12);name='google:123';db.execute('INSERT INTO settings VALUES(?,?)',(name,nonce+AESGCM(key).encrypt(nonce,b'{"refresh_token":"private"}',name.encode())));db.commit()
   settings=ReadOnlySettings(d);self.assertEqual(settings.setting(name)['refresh_token'],'private')
   body=base64.urlsafe_b64encode(json.dumps({'sub':'123','exp':time.time()+60}).encode()).rstrip(b'=');sig=base64.urlsafe_b64encode(hmac.digest(key,body,'sha256')).rstrip(b'=')
   self.assertEqual(settings.owner((body+b'.'+sig).decode()),'123');self.assertEqual(db.execute('SELECT status FROM tasks').fetchone()[0],'running')
   with self.assertRaises(PermissionError):settings.owner('bad.bad')
   db.close()

class AsyncTests(unittest.IsolatedAsyncioTestCase):
 async def test_cache_is_persistent_private_json_only_and_scope_bound(self):
  with tempfile.TemporaryDirectory() as d:
   c=JsonCache(d);key=c.identity('a','m',1,'p');await c.put(key,'a',{'ru':'Секрет'});self.assertEqual((await c.get(key,'a'))['ru'],'Секрет');self.assertIsNone(await c.get(key,'b'));await c.close()
   self.assertNotIn('Секрет'.encode(),(Path(d)/'translations.sqlite').read_bytes());c=JsonCache(d);self.assertIsNotNone(await c.get(key,'a'))
   with self.assertRaises(ValueError):await c.put(key,'a',{'image':'bytes'})
   await c.close()
 async def test_quota_shared_by_default_and_only_explicit_model_switch(self):
  now=[0];q=QuotaPacer(tpm=100,rpm=2,clock=lambda:now[0]);await q.reserve(['a'],80)
  with self.assertRaises(Deferred):await q.reserve(['b'],40)
  now[0]=61;await q.reserve(['b'],40);await q.limited('a',10,project_wide=True)
  with self.assertRaises(Deferred):await q.reserve(['b'],1)
  q=QuotaPacer(tpm=100,independent=True);await q.reserve(['a'],90);self.assertEqual((await q.reserve(['a','b'],20)).model,'b')
 async def test_sdk_fixture_four_separate_images_and_exact_ids(self):
  calls=[]
  class Models:
   async def count_tokens(self,**kwargs):return NS(total_tokens=100)
   async def generate_content(self,**kwargs):
    calls.append(kwargs);return NS(text=json.dumps([row('P'+str(i)+'_B1') for i in range(1,5)]),candidates=[NS(finish_reason='STOP')],usage_metadata=NS(prompt_token_count=90,candidates_token_count=50))
  provider=GemmaBatchTranslator(QuotaPacer(),'/no-key',client=NS(aio=NS(models=Models())))
  pages=[{'page':i,'width':100,'height':100,'regions':[{'uid':'P'+str(i)+'_B1'}],'som':b'image-fixture'} for i in range(1,5)]
  values,meta=await provider.translate(pages);self.assertEqual(len(values),4);self.assertEqual(meta['model'],'gemma-4-31b-it');self.assertEqual(sum(p.inline_data is not None for p in calls[0]['contents'][0].parts),4);self.assertEqual(calls[0]['config'].thinking_config.thinking_level,'MINIMAL')
  schema=calls[0]['config'].response_schema
  self.assertEqual(schema['items']['properties']['uid']['enum'],[f'P{i}_B1' for i in range(1,5)])
  self.assertEqual(calls[0]['config'].max_output_tokens,2048)
  self.assertIn('never deduplicate',calls[0]['contents'][0].parts[0].text)
 async def test_429_shared_quota_does_not_rotate_and_independent_does(self):
  from google.genai.errors import ClientError
  class Models:
   def __init__(self):self.calls=[]
   async def count_tokens(self,**kw):return NS(total_tokens=10)
   async def generate_content(self,**kw):
    self.calls.append(kw['model'])
    if len(self.calls)==1:raise ClientError(429,{'error':{'message':'quota','details':[{'retryDelay':'2s'}]}})
    return NS(text=json.dumps([row('P1_B1')]),candidates=[NS(finish_reason='STOP')],usage_metadata=None)
  m=Models();p=GemmaBatchTranslator(QuotaPacer(),'/x',client=NS(aio=NS(models=m)))
  with self.assertRaises(Deferred):await p.translate([{'page':1,'width':1,'height':1,'regions':[{'uid':'P1_B1'}],'som':b'x'}])
  self.assertEqual(len(m.calls),1)
  class PerModel(Models):
   async def generate_content(self,**kw):
    if not self.calls:
     self.calls.append(kw['model'])
     raise ClientError(429,{'error':{'message':'quota','details':[{'retryDelay':'2s','quotaDimensions':{'model':kw['model']}}]}})
    return await super().generate_content(**kw)
  m=PerModel();p=GemmaBatchTranslator(QuotaPacer(independent=True),'/x',client=NS(aio=NS(models=m)))
  values,meta=await p.translate([{'page':1,'width':1,'height':1,'regions':[{'uid':'P1_B1'}],'som':b'x'}]);self.assertEqual(meta['model'],'gemma-4-26b-a4b-it');self.assertEqual(len(values),1)
 async def test_rejected_model_budget_does_not_block_shared_pool_fallback(self):
  from google.genai.errors import ClientError
  class Models:
   def __init__(self):self.calls=[]
   async def count_tokens(self,**kw):return NS(total_tokens=7000)
   async def generate_content(self,**kw):
    self.calls.append(kw['model'])
    if len(self.calls)==1:raise ClientError(429,{'error':{'message':'quota','details':[{'violations':[{'quotaDimensions':{'model':kw['model']}}]},{'retryDelay':'2s'}]}})
    return NS(text=json.dumps([row('P1_B1')]),candidates=[NS(finish_reason='STOP')],usage_metadata=NS(prompt_token_count=6500,candidates_token_count=80))
  models=Models();q=QuotaPacer();p=GemmaBatchTranslator(q,'/unused',client=NS(aio=NS(models=models)))
  values,meta=await p.translate([{'page':1,'width':100,'height':100,'regions':[{'uid':'P1_B1'}],'som':b'x'}])
  self.assertEqual(meta['model'],'gemma-4-26b-a4b-it');self.assertEqual(len(values),1)
  window=q.snapshot()['groups']['google-project'];self.assertEqual(window['reservedInputTokens'],6500);self.assertEqual(window['requests'],2)
 async def test_singleflight_batches_dense_split_and_cache_replay(self):
  class Files:
   def __init__(self):self.leases=0
   def acquire(self):self.leases+=1
   def release(self):self.leases-=1
   def page(self,name):
    out=io.BytesIO();Image.new('RGB',(100,100),'white').save(out,format='PNG');return out.getvalue()
  class Detector:
   def detect(self,data,page,rtl):return Image.new('RGB',(100,100),'white'),[{'uid':f'P{page}_B{i+1}','text_bbox':[1,1,50,50],'bubble_bbox':None,'layout_bbox':[1,1,50,50]} for i in range(70 if page==1 else 1)],{}
  class Provider:
   def __init__(self):self.calls=[];self.deferred=False;self.oversized=False
   async def translate(self,pages):
    from manga_batch.provider import BatchTooLarge
    if len(pages)>1 and not self.oversized:self.oversized=True;raise BatchTooLarge('fixture input limit')
    if len(self.calls)==1 and not self.deferred:self.deferred=True;raise Deferred(.05)
    await asyncio.sleep(.005);ids=[r['uid'] for p in pages for r in p['regions']];self.calls.append((len(pages),len(ids)));return {id:row(id) for id in ids},{'model':'fixture'}
  with tempfile.TemporaryDirectory() as d:
   cache=JsonCache(d);provider=Provider();engine=RealtimeChapterOrchestrator(None,Detector(),provider,cache);files=Files();s={'scope':'u:lib','manifest':'m','names':[str(i) for i in range(4)],'archive':files}
   _,jobs=await engine.window(s,1);_,other=await engine.window(s,1);self.assertIs(jobs[0]['future'],other[0]['future']);out=await asyncio.gather(*(j['future'] for j in jobs));self.assertEqual(len(out[0]['regions']),70);self.assertTrue(all(p<=4 and n<=65 for p,n in provider.calls));self.assertEqual(sum(n for p,n in provider.calls),73,'Quota retry must not translate successful fragments twice');calls=len(provider.calls);hits,waiting=await engine.window(s,1);self.assertEqual(len(hits),4);self.assertEqual(waiting,[]);self.assertEqual(len(provider.calls),calls);self.assertEqual(files.leases,0);await engine.close();await cache.close()

 async def test_unsupported_schema_or_json_mime_retries_with_strict_local_validation(self):
  from google.genai.errors import ClientError
  for message in ['response_schema is unsupported','response_mime_type is unsupported']:
   class Models:
    def __init__(self):self.calls=[];self.parts=[]
    async def count_tokens(self,**kw):return NS(total_tokens=100)
    async def generate_content(self,**kw):
     self.calls.append(kw['config']);self.parts.append(kw['contents'][0].parts)
     if len(self.calls)==1:raise ClientError(400,{'error':{'message':message}})
     return NS(text=json.dumps([row('P1_B1')]),candidates=[NS(finish_reason='STOP')],usage_metadata=None)
   m=Models();p=GemmaBatchTranslator(QuotaPacer(),'/x',client=NS(aio=NS(models=m)))
   pages=[{'page':1,'width':100,'height':100,'regions':[{'uid':'P1_B1'}],'som':b'x'}]
   with self.assertRaises(Deferred):await p.translate(pages)
   rows,meta=await p.translate(pages);self.assertEqual(len(rows),1);self.assertFalse(meta['structuredOutput']);self.assertIsNone(m.calls[-1].response_schema)
   self.assertTrue(any('"ru_translation"' in (part.text or '') and 'Output JSON matching' in part.text for part in m.parts[-1]))
   if 'mime' in message:self.assertIsNone(m.calls[-1].response_mime_type)

 async def test_real_google_sdk_serializes_count_and_generate_contracts(self):
  import httpx
  from google import genai
  from google.genai import types
  calls=[]
  def response(request):
   body=json.loads(request.content);calls.append((request.url.path,body))
   if request.url.path.endswith(':countTokens'):return httpx.Response(200,json={'totalTokens':100})
   return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'text':json.dumps([row('P1_B1')])}]}}],'usageMetadata':{'promptTokenCount':110,'candidatesTokenCount':80}})
  client=genai.Client(api_key='explicit-sdk-fixture',http_options=types.HttpOptions(async_client_args={'transport':httpx.MockTransport(response)}))
  try:
   provider=GemmaBatchTranslator(QuotaPacer(),'/not-used',client=client)
   result,meta=await provider.translate([{'page':1,'width':100,'height':100,'regions':[{'uid':'P1_B1'}],'som':b'fixture'}])
   self.assertEqual(len(result),1);self.assertEqual(len(calls),2);self.assertNotIn('systemInstruction',calls[0][1]);self.assertIn('systemInstruction',calls[1][1]);self.assertIn('LOCALIZATION',calls[0][1]['contents'][0]['parts'][0]['text']);self.assertEqual(meta['inputTokens'],110)
  finally:await client.aio.aclose()

class HttpContracts(unittest.IsolatedAsyncioTestCase):
 async def test_authentication_and_sse_cache_order(self):
  import httpx
  from manga_batch.app import app,owner
  class Engine:
   async def window(self,s,current):
    f=asyncio.get_running_loop().create_future();f.set_result({'page':2,'policy':'p'})
    return [{'page':1,'cacheHit':True}],[{'future':f,'page':2}]
  app.state.engine=Engine()
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://test') as client:
   response=await client.post('/api/v1/chapters',json={});self.assertEqual(response.status_code,401)
   response=await client.post('/api/v1/chapters',headers={'Content-Length':'524289'});self.assertEqual(response.status_code,413)
   app.dependency_overrides[owner]=lambda:'subject'
   import manga_batch.app as module
   original=module.session
   async def fake_session(id,subject):return {'names':['a','b']}
   module.session=fake_session
   try:
    response=await client.get('/api/v1/chapters/session/stream?currentPage=1',headers={'Origin':'https://onikri.github.io'})
    self.assertEqual(response.status_code,200);self.assertIn('text/event-stream',response.headers['content-type']);self.assertEqual(response.headers['access-control-allow-origin'],'https://onikri.github.io');self.assertLess(response.text.index('"page":1'),response.text.index('"page":2'));self.assertIn('event: complete',response.text);self.assertEqual(response.headers['cache-control'],'no-store')
   finally:module.session=original;app.dependency_overrides.clear()
