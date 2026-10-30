"""Playback lifetime contracts, no external provider requests."""
import sys,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
import online_sessions as online

class OnlineLeases(unittest.TestCase):
 def setUp(self):
  online.sessions.clear();online.preparations.clear()
  self.app=FastAPI();self.subject='owner';online.install(self.app,lambda:self.subject);self.client=TestClient(self.app)
 def tearDown(self):online.sessions.clear();online.preparations.clear()
 def test_reloading_and_twelve_chapter_switches_replace_only_same_viewer(self):
  other,_=online.create('other',{},client_id='tab:viewer')
  preview,_=online.create('owner',{},client_id='tab:preview')
  fixture={'url':'https://source.example/chapter','language':'en','pages':['https://images.example/page.png']}
  with patch('manga_sources.inspect',return_value=fixture):
   for _ in range(12):
    response=self.client.post('/online/prepare',json={'url':fixture['url'],'kind':'manga','clientId':'tab:viewer'})
    self.assertEqual(response.status_code,200,response.text);self.assertEqual(len(online.sessions),3)
  self.assertIn(other,online.sessions);self.assertIn(preview,online.sessions);self.assertEqual(online.preparations,{})
 def test_abandoned_lease_expires_and_heartbeat_requires_same_owner(self):
  token,s=online.create('owner',{},client_id='tab:viewer')
  self.assertLessEqual(s.expires-time.monotonic(),120)
  self.subject='other';self.assertEqual(self.client.post('/online/'+token+'/heartbeat').status_code,410)
  self.subject='owner';s.expires=time.monotonic()+1
  self.assertEqual(self.client.post('/online/'+token+'/heartbeat').status_code,200)
  self.assertGreater(s.expires-time.monotonic(),100)
  with patch('online_sessions.time.monotonic',return_value=s.expires+1):online.expire()
  self.assertNotIn(token,online.sessions)
 def test_old_inflight_preparation_cannot_replace_new_chapter(self):
  online.preparations[('owner','tab')]=('new',time.monotonic()+60)
  token,_=online.create('owner',{},client_id='tab',reservation='new')
  with self.assertRaises(HTTPException) as raised:online.create('owner',{},client_id='tab',reservation='old')
  self.assertEqual(raised.exception.status_code,409);self.assertIn(token,online.sessions)
 def test_invalid_resource_during_preparation_does_not_leak_session(self):
  fixture={'url':'https://source.example/chapter','language':'en','pages':['https://images.example/page.png','http://127.0.0.1/private']}
  with patch('manga_sources.inspect',return_value=fixture):
   with self.assertRaises(Exception):self.client.post('/online/prepare',json={'url':fixture['url'],'kind':'manga','clientId':'tab:viewer'})
  self.assertEqual(online.sessions,{});self.assertEqual(online.preparations,{})
 def test_four_independent_live_viewers_still_enforce_owner_limit(self):
  for i in range(4):online.create('owner',{},client_id='tab'+str(i))
  with self.assertRaises(HTTPException):online.create('owner',{},client_id='fifth')
  online.create('owner',{},client_id='tab0');self.assertEqual(len(online.sessions),4)
