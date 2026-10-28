"""Real application CORS/auth/session lifecycle; no external provider requests."""
import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import api
import online_sessions as online

class OnlineCorsTests(unittest.TestCase):
 def test_owner_site_can_close_sessions_repeatedly_without_exhausting_slots(self):
  client=TestClient(api.app)
  headers={'Origin':api.ORIGIN,'Access-Control-Request-Method':'DELETE','Access-Control-Request-Headers':'authorization,content-type'}
  response=client.options('/online/fixture',headers=headers)
  self.assertEqual(response.status_code,200)
  self.assertEqual(response.headers['access-control-allow-origin'],api.ORIGIN)
  self.assertIn('DELETE',response.headers['access-control-allow-methods'])
  with patch.object(api,'store',SimpleNamespace(key=b'x'*32)):
   authorization='Bearer '+api.session_token('cors-owner')
   for _ in range(6):
    token,session=online.create('cors-owner',{},'manga')
    try:
     response=client.delete('/online/'+token,headers={'Origin':api.ORIGIN,'Authorization':authorization})
     self.assertEqual(response.status_code,200)
     self.assertEqual(response.headers['access-control-allow-origin'],api.ORIGIN)
     self.assertNotIn(token,online.sessions)
    finally:online.sessions.pop(token,None)
 def test_other_origins_and_unauthenticated_deletion_still_fail(self):
  client=TestClient(api.app)
  response=client.options('/online/fixture',headers={'Origin':'https://untrusted.example','Access-Control-Request-Method':'DELETE'})
  self.assertEqual(response.status_code,400)
  self.assertNotIn('access-control-allow-origin',response.headers)
  with patch.object(api,'store',SimpleNamespace(key=b'x'*32)):
   token,session=online.create('cors-owner',{},'manga')
   try:
    self.assertEqual(client.delete('/online/'+token).status_code,401)
    self.assertIn(token,online.sessions)
   finally:online.sessions.pop(token,None)
