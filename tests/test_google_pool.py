"""Fixture API contract: encrypted credentials, bounded gateway, no real Google calls."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import httpx
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from task_store import TaskStore
import google_pool as pool

class GooglePoolTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=TaskStore(self.temp.name);self.addCleanup(self.store.database.close)
  self.addCleanup(setattr,pool,'_store',pool._store);app=FastAPI();pool.install(app,lambda:'owner',lambda:self.store);self.client=TestClient(app)
  self.calls=[];real=httpx.AsyncClient
  def handle(request):
   self.calls.append(request)
   if request.method=='GET':return httpx.Response(200,json={'models':[{'name':'models/'+m} for m in pool.MODELS]})
   if request.url.path.endswith(':countTokens'):return httpx.Response(200,json={'totalTokens':100})
   if hasattr(self,'answer'):return self.answer(request)
   return httpx.Response(429,json={'error':{'message':'fixture-secret-must-not-leak'}})
  self.network=patch('google_pool.httpx.AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handle),**kw));self.network.start();self.addCleanup(self.network.stop)
  self.env=patch.dict('os.environ',{'DATA_DIR':self.temp.name});self.env.start();self.addCleanup(self.env.stop)
 def test_three_slots_are_encrypted_and_never_exported(self):
  rows=[{'slot':i,'key':'fixture-secret-key-'+str(i)+'-abcdefghijk','project':'project-'+str(i)} for i in range(3)]
  response=self.client.post('/reader/google/keys',json={'slots':rows});self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['keyCount'],3);self.assertNotIn('fixture-secret',response.text)
  raw=self.store.database.execute('SELECT value FROM settings WHERE name=?',(pool.SETTING,)).fetchone()[0];self.assertNotIn(b'fixture-secret',raw)
  self.assertEqual(len(pool.saved()),3);self.assertNotIn('fixture-secret',self.client.get('/reader/google/keys').text)
  response=self.client.post('/reader/google/keys',json={'slots':[{'slot':0},{'slot':1,'key':''},{'slot':2}]});self.assertEqual(response.json()['keyCount'],2)
 def test_quota_error_is_not_retried_with_another_key(self):
  self.store.setting(pool.SETTING,{'slots':[{'slot':i,'key':'fixture-key-'+str(i),'models':list(pool.MODELS)} for i in range(3)]})
  response=self.client.post('/reader/google/generate',json={'slot':0,'model':pool.MODELS[0],'request':{'contents':[{'role':'user','parts':[{'text':'Fixture page'}]}]}})
  self.assertEqual(response.status_code,429);self.assertNotIn('fixture-secret',response.text);self.assertEqual(sum(r.url.path.endswith(':generateContent') for r in self.calls),1)
  self.assertTrue(all(r.headers.get('x-goog-api-key')=='fixture-key-0' for r in self.calls))
 def daily_quota(self):
  return httpx.Response(429,json={'error':{'message':'fixture-secret-must-not-leak','details':[{'@type':'type.googleapis.com/google.rpc.QuotaFailure','violations':[{'quotaId':'GenerateRequestsPerDayPerProjectPerModel-FreeTier','quotaValue':'20'}]}]}})
 def generate_calls(self):return [r.headers.get('x-goog-api-key') for r in self.calls if r.url.path.endswith(':generateContent')]
 def test_unpinned_request_moves_to_a_key_of_another_project_after_429(self):
  self.store.setting(pool.SETTING,{'slots':[{'slot':i,'key':'fixture-key-'+str(i),'project':'project-'+str(i),'models':list(pool.MODELS)} for i in range(3)]})
  self.answer=lambda request:self.daily_quota() if request.headers.get('x-goog-api-key')=='fixture-key-0' else httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'{}'}]}}]})
  body={'model':pool.MODELS[0],'request':{'contents':[{'role':'user','parts':[{'text':'Narration'}]}]}}
  response=self.client.post('/reader/google/generate',json=body)
  self.assertEqual(response.status_code,200,response.text);self.assertIn(response.json()['mediavaultGateway']['slot'],(1,2))
  calls=self.generate_calls();self.assertEqual(len(calls),2);self.assertEqual(calls[0],'fixture-key-0');self.assertNotEqual(calls[1],'fixture-key-0')
  # The spent project keeps its cooldown: the next request never touches it.
  self.calls.clear();self.assertEqual(self.client.post('/reader/google/generate',json=body).status_code,200)
  self.assertNotIn('fixture-key-0',self.generate_calls())
 def test_keys_of_the_same_project_are_skipped_together(self):
  self.store.setting(pool.SETTING,{'slots':[{'slot':0,'key':'fixture-key-0','project':'shared','models':list(pool.MODELS)},{'slot':1,'key':'fixture-key-1','project':'shared','models':list(pool.MODELS)},{'slot':2,'key':'fixture-key-2','project':'other','models':list(pool.MODELS)}]})
  self.answer=lambda request:self.daily_quota() if request.headers.get('x-goog-api-key')!='fixture-key-2' else httpx.Response(200,json={'candidates':[]})
  response=self.client.post('/reader/google/generate',json={'model':pool.MODELS[0],'request':{'contents':[{'role':'user','parts':[{'text':'x'}]}]}})
  self.assertEqual(response.status_code,200,response.text);self.assertEqual(self.generate_calls(),['fixture-key-0','fixture-key-2'])
 def test_all_projects_spent_answers_429_after_one_try_each(self):
  self.store.setting(pool.SETTING,{'slots':[{'slot':i,'key':'fixture-key-'+str(i),'project':'project-'+str(i),'models':list(pool.MODELS)} for i in range(3)]})
  self.answer=lambda request:self.daily_quota()
  response=self.client.post('/reader/google/generate',json={'model':pool.MODELS[0],'request':{'contents':[{'role':'user','parts':[{'text':'x'}]}]}})
  self.assertEqual(response.status_code,429);self.assertNotIn('fixture-secret',response.text)
  self.assertEqual(sorted(self.generate_calls()),['fixture-key-0','fixture-key-1','fixture-key-2'])
 def test_fixed_destination_and_owner_auth(self):
  body={'model':'https://evil.example','key':'fixture','request':{'contents':[]}}
  self.assertEqual(self.client.post('/reader/google/generate',json=body).status_code,422);self.assertEqual(self.calls,[])
  def denied():raise HTTPException(401,'Login')
  app=FastAPI();pool.install(app,denied,lambda:self.store);client=TestClient(app)
  self.assertEqual(client.get('/reader/google/keys').status_code,401)
  self.assertEqual(client.post('/reader/google/generate',json={**body,'model':pool.MODELS[0]}).status_code,401)
