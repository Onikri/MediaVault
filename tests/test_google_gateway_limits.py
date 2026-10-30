"""Deterministic scheduling/error contracts; no real Google calls."""
import asyncio,json,os,sqlite3,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi import FastAPI
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from google_gateway_limits import GoogleGatewayLimits,GatewayLimited,provider_limit
from task_store import TaskStore
import google_pool

def profiles():return [{'slot':i,'key':'fixture-private-credential-'+str(i),'project':'profile-'+str(i),'models':list(google_pool.MODELS)} for i in range(3)]

class GatewayLimitsTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.now=[1000.]
  self.path=Path(self.temp.name)/'gateway.sqlite';self.state=GoogleGatewayLimits(self.path,lambda:self.now[0]);self.rows=profiles();self.model=google_pool.MODELS[0]

 async def test_three_independent_profiles_acquire_together_even_with_same_preferred_slot(self):
  leases=await asyncio.gather(*(self.state.acquire(self.rows,self.model,preferred=0) for _ in range(3)))
  self.assertEqual({r['slot'] for r,_ in leases},{0,1,2});self.assertEqual(len(self.state.busy),3)
  for r,call in leases:self.state.finish(r,self.model,call,200,{'promptTokenCount':100,'candidatesTokenCount':20})
  for row in self.rows:
   status=self.state.snapshot(row)['models'][self.model];self.assertEqual(status['requestsLastMinute'],1);self.assertEqual(status['inputTokensLastMinute'],100);self.assertIsNone(status['providerRemaining'])
  self.assertEqual(self.state.busy,set())

 async def test_unknown_or_shared_projects_do_not_invent_three_budgets(self):
  for row in self.rows:row['project']=''
  row,call=await self.state.acquire(self.rows,self.model)
  with self.assertRaises(GatewayLimited):await self.state.acquire(self.rows,self.model,max_wait=0)
  self.state.finish(row,self.model,call,200);self.now[0]+=4
  row,call=await self.state.acquire(self.rows,self.model,preferred=1);self.assertEqual(row['slot'],1);self.state.finish(row,self.model,call,200)

 async def test_google_retry_info_survives_restart_and_other_independent_profile_can_proceed(self):
  row,call=await self.state.acquire(self.rows,self.model,preferred=0)
  response=httpx.Response(429,headers={'Retry-After':'5'},json={'error':{'message':'fixture-private-credential-must-not-leak','details':[{'@type':'type.googleapis.com/google.rpc.RetryInfo','retryDelay':'12.5s'},{'@type':'type.googleapis.com/google.rpc.QuotaFailure','violations':[{'quotaId':'GenerateRequestsPerMinutePerProject','quotaValue':'15'}]}]}})
  self.state.finish(row,self.model,call,429,response=response)
  fresh=GoogleGatewayLimits(self.path,lambda:self.now[0]);self.assertEqual(fresh.snapshot(row)['models'][self.model]['cooldownSeconds'],13)
  other,other_call=await fresh.acquire(self.rows,self.model,preferred=0);self.assertNotEqual(other['slot'],0);fresh.finish(other,self.model,other_call,200)
  self.assertNotIn(b'fixture-private-credential',self.path.read_bytes());self.assertNotIn('must-not-leak',json.dumps(fresh.snapshot(row)))

 async def test_request_pacing_is_durable_per_profile_and_cancelled_wait_does_not_take_a_key(self):
  row,call=await self.state.acquire(self.rows,self.model,preferred=0);self.state.finish(row,self.model,call,200)
  fresh=GoogleGatewayLimits(self.path,lambda:self.now[0]);self.assertEqual(fresh.delay(row,self.model),4)
  async def disconnected():return True
  with self.assertRaises(asyncio.CancelledError):await fresh.acquire(self.rows,self.model,disconnected=disconnected)
  self.assertEqual(fresh.busy,set())

 async def test_http_date_retry_and_invalid_credentials_are_recorded_without_error_text(self):
  delay,_=provider_limit(httpx.Response(503,headers={'Retry-After':'Thu, 01 Jan 1970 00:17:00 GMT'}),1000);self.assertEqual(delay,20)
  delay,_=provider_limit(httpx.Response(403,json={'error':{'message':'private'}}),1000);self.assertEqual(delay,900)

class GatewayApiParallelTests(unittest.IsolatedAsyncioTestCase):
 async def test_three_requests_are_concurrent_without_token_counting_or_client_secret_export(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);directory=temp.name
  with patch.dict(os.environ,{'DATA_DIR':directory}):
   store=TaskStore(directory);self.addCleanup(store.database.close);store.setting(google_pool.SETTING,{'slots':profiles()})
   previous=google_pool._store;self.addCleanup(setattr,google_pool,'_store',previous)
   app=FastAPI();google_pool.install(app,lambda:'owner',lambda:store);seen=[];all_started=asyncio.Event();real=httpx.AsyncClient
   body={'contents':[{'role':'user','parts':[{'text':'Two fixture manga pages with labels'}]}],'generationConfig':{'responseMimeType':'application/json'}}
   async def provider(request):
    self.assertTrue(request.url.path.endswith(':generateContent'));self.assertEqual(json.loads(request.content),body)
    seen.append(request.headers['x-goog-api-key'])
    if len(seen)==3:all_started.set()
    await asyncio.wait_for(all_started.wait(),3)
    return httpx.Response(200,json={'candidates':[],'usageMetadata':{'promptTokenCount':10}})
   async with real(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
    with patch('google_pool.httpx.AsyncClient',lambda **kw:real(transport=httpx.MockTransport(provider),**kw)):
     responses=await asyncio.gather(*(client.post('/reader/google/generate',json={'slot':0,'model':google_pool.MODELS[0],'request':body}) for _ in range(3)))
    self.assertEqual([r.status_code for r in responses],[200,200,200]);self.assertEqual(len(set(seen)),3)
    self.assertEqual({r.json()['mediavaultGateway']['slot'] for r in responses},{0,1,2})
    status=await client.get('/reader/google/keys');self.assertEqual(status.json()['keyCount'],3)
    self.assertNotIn('fixture-private',status.text);self.assertNotIn('fixture-private',''.join(r.text for r in responses))
    for row in status.json()['slots']:self.assertEqual(row['runtime']['models'][google_pool.MODELS[0]]['lastHttpStatus'],200)


 async def test_personal_request_never_falls_back_to_saved_server_credentials(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);store=TaskStore(temp.name);self.addCleanup(store.database.close);store.setting(google_pool.SETTING,{'slots':profiles()})
  previous=google_pool._store;self.addCleanup(setattr,google_pool,'_store',previous);app=FastAPI();google_pool.install(app,lambda:'owner',lambda:store);real=httpx.AsyncClient;seen=[]
  def provider(request):
   seen.append(request.headers['x-goog-api-key']);return httpx.Response(401,json={'error':{'message':'fixture-personal-secret must not leak'}})
  async with real(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
   with patch('google_pool.httpx.AsyncClient',lambda **kw:real(transport=httpx.MockTransport(provider),**kw)):
    response=await client.post('/reader/google/generate',json={'key':'fixture-personal-secret','model':google_pool.MODELS[0],'request':{'contents':[]}})
  self.assertEqual(response.status_code,401);self.assertEqual(seen,['fixture-personal-secret']);self.assertNotIn('fixture-personal-secret',response.text)
