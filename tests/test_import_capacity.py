import tempfile,unittest
from task_store import TaskStore
from api import import_auth_error,VaultError
from fastapi import HTTPException
from google.auth.exceptions import RefreshError,TransportError
class ImportCapacityTests(unittest.TestCase):
 def test_resumable_auth_wait_does_not_block_active_capacity(self):
  with tempfile.TemporaryDirectory()as directory:
   store=TaskStore(directory)
   waiting=[]
   for i in range(30):
    row=store.add('owner',{'kind':'import'},'waiting-'+str(i));waiting.append(row['id']);store.update(row['id'],status='waiting_auth')
   for i in range(30):store.add('owner',{'kind':'import'},'active-'+str(i))
   with self.assertRaises(ValueError):store.add('owner',{'kind':'import'},'over-limit')
   self.assertEqual(sum(store.get(i)['status']=='waiting_auth'for i in waiting),30)
   store.database.close()
 def test_upstream_or_transport_errors_do_not_request_google_reconsent(self):
  for error in [HTTPException(502,'Source failed'),HTTPException(403,'Источник не ответил'),TransportError('network'),RefreshError('try later',retryable=True)]:self.assertFalse(import_auth_error(error))
  for error in [RefreshError('invalid_grant'),VaultError('Подключи Google Drive к серверу один раз в настройках импорта.'),HTTPException(401,'Google session')]:self.assertTrue(import_auth_error(error))
if __name__=='__main__':unittest.main()
