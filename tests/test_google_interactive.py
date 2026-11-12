"""Deterministic quota/cancellation contracts, no real Google calls."""
import asyncio,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from google_gateway_limits import GoogleGatewayLimits,GatewayLimited
from google_interactive import generate_first_page
from fastapi import FastAPI
from task_store import TaskStore
import google_pool

class InteractiveTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.state=GoogleGatewayLimits(Path(self.temp.name)/'quota.sqlite')
  self.rows=[{'slot':i,'key':'fixture-private-'+str(i),'project':'independent-'+str(i)} for i in range(6)];self.model='gemini-3.5-flash-lite'

 async def test_slow_primary_is_hedged_once_and_loser_cancelled_with_no_lease_leak(self):
  real=httpx.AsyncClient;started=[];cancelled=[]
  async def provider(request):
   key=request.headers['x-goog-api-key'];started.append(key)
   if key==self.rows[0]['key']:
    try:await asyncio.Event().wait()
    except asyncio.CancelledError:cancelled.append(key);raise
   return httpx.Response(200,json={'candidates':[],'usageMetadata':{'promptTokenCount':100}})
  with patch('google_interactive.HEDGE_AFTER',.01),patch('google_interactive.httpx.AsyncClient',lambda **kw:real(transport=httpx.MockTransport(provider),**kw)):
   row,response=await asyncio.wait_for(generate_first_page(self.rows,self.model,{'contents':[]},self.state,preferred=0,tokens=500),2)
  self.assertIn(row['slot'],[1,3,5]);self.assertEqual(response.status_code,200);self.assertEqual(len(started),2);self.assertEqual(cancelled,[self.rows[0]['key']]);self.assertFalse(self.state.busy);self.assertEqual(self.state.interactive_sessions,0)

 async def test_fast_primary_uses_one_call_and_shared_projects_never_race(self):
  real=httpx.AsyncClient;seen=[]
  async def provider(request):seen.append(1);return httpx.Response(200,json={'candidates':[]})
  with patch('google_interactive.httpx.AsyncClient',lambda **kw:real(transport=httpx.MockTransport(provider),**kw)):
   await generate_first_page(self.rows,self.model,{'contents':[]},self.state,preferred=0)
  self.assertEqual(len(seen),1)
  for r in self.rows:r['project']='one-project'
  seen.clear()
  async def slow(request):seen.append(1);await asyncio.sleep(.03);return httpx.Response(200,json={'candidates':[]})
  with patch('google_interactive.HEDGE_AFTER',.001),patch('google_interactive.httpx.AsyncClient',lambda **kw:real(transport=httpx.MockTransport(slow),**kw)):
   await generate_first_page(self.rows,self.model,{'contents':[]},self.state,preferred=0)
  self.assertEqual(len(seen),1);self.assertFalse(self.state.busy)

 async def test_background_cannot_take_the_reserved_interactive_capacity(self):
  with self.state.interactive():
   leases=[await self.state.acquire(self.rows,self.model,preferred=i,background=True) for i in range(4)]
   with self.assertRaises(GatewayLimited):await self.state.acquire(self.rows,self.model,preferred=4,background=True,max_wait=0)
   leases.append(await self.state.acquire(self.rows,self.model,preferred=4,max_wait=0))
   leases.append(await self.state.acquire(self.rows,self.model,preferred=5,max_wait=0))
   self.assertEqual(sum(self.state.busy.values()),6)
   for row,call in leases:self.state.finish(row,self.model,call,200)
  self.assertFalse(self.state.busy)

 async def test_cancelling_the_client_closes_both_workers(self):
  real=httpx.AsyncClient;started=asyncio.Event()
  async def provider(request):started.set();await asyncio.Event().wait()
  with patch('google_interactive.httpx.AsyncClient',lambda **kw:real(transport=httpx.MockTransport(provider),**kw)):
   task=asyncio.create_task(generate_first_page(self.rows,self.model,{'contents':[]},self.state,preferred=0));await started.wait();task.cancel()
   with self.assertRaises(asyncio.CancelledError):await task
  self.assertFalse(self.state.busy);self.assertEqual(self.state.interactive_sessions,0)

 async def test_real_gateway_route_accepts_priority_and_returns_only_the_winning_slot(self):
  store=TaskStore(self.temp.name);self.addCleanup(store.database.close);store.setting(google_pool.SETTING,{'slots':self.rows})
  previous=google_pool._store;self.addCleanup(setattr,google_pool,'_store',previous)
  app=FastAPI();google_pool.install(app,lambda:'owner',lambda:store);real=httpx.AsyncClient
  async def provider(request):
   if request.headers['x-goog-api-key']==self.rows[0]['key']:await asyncio.Event().wait()
   return httpx.Response(200,json={'candidates':[]})
  async with real(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
   with patch('google_interactive.HEDGE_AFTER',.01),patch('google_interactive.httpx.AsyncClient',lambda **kw:real(transport=httpx.MockTransport(provider),**kw)):
    result=await asyncio.wait_for(client.post('/reader/google/generate',json={'slot':0,'pool':True,'priority':'interactive','model':self.model,'request':{'contents':[]}}),2)
  self.assertEqual(result.status_code,200);self.assertNotEqual(result.json()['mediavaultGateway']['slot'],0);self.assertNotIn('fixture-private',result.text)
