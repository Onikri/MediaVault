import unittest,tempfile,time
from unittest.mock import patch,Mock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError,TransportError
from task_store import TaskStore
import drive_grants as grants
class DriveGrantTests(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory();self.store=TaskStore(self.folder.name);self.store.setting('google:A',{'refresh_token':'old-private','scope':'drive'})
 def tearDown(self):self.store.close();self.folder.cleanup()
 def test_rejection_preserves_the_secret_and_is_not_a_successful_connection(self):
  grants.rejected(self.store,'A');public=grants.status(self.store,'A');self.assertTrue(public['configured']);self.assertFalse(public['connected']);self.assertNotIn('old-private',str(public));self.assertEqual(self.store.setting('google:A')['refresh_token'],'old-private')
 def test_late_rejection_from_old_credentials_cannot_poison_a_new_grant(self):
  self.store.setting('google:A',{'refresh_token':'new-private'});grants.rejected(self.store,'A','old-private');self.assertTrue(grants.status(self.store,'A')['connected'])
 def test_network_failure_is_not_a_revocation_and_success_clears_known_failure(self):
  for exception in [TransportError('offline'),RefreshError('invalid_grant')]:
   self.store.setting('google:A',{'refresh_token':'old-private'});credential=Mock();credential.refresh.side_effect=exception
   app=FastAPI();grants.install(app,lambda:'A',lambda:self.store,lambda sub:credential)
   with TestClient(app) as client:result=client.post('/google/connection/check').json()
   self.assertEqual(result['needsConsent'],isinstance(exception,RefreshError));self.assertNotIn('old-private',str(result))
  self.store.setting('google:A',{'refresh_token':'fresh-private'});credential=Mock();app=FastAPI();grants.install(app,lambda:'A',lambda:self.store,lambda sub:credential)
  with TestClient(app) as client:result=client.post('/google/connection/check').json()
  self.assertEqual(result['state'],'ready');self.assertTrue(result['connected'])
