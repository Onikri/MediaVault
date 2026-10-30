import json,sys,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from reader_network import ReaderNetwork

class ReaderNetworkTests(unittest.TestCase):
 def test_activity_is_owner_scoped_and_only_accepts_public_metadata(self):
  network=ReaderNetwork();a=network.begin('owner',0,'fixture-model');network.begin('another',1,'private-other-model')
  network.update(a,'translating');value=network.snapshot('owner')
  self.assertEqual(value['active'],1);self.assertEqual(len(value['jobs']),1);self.assertNotIn('private-other-model',json.dumps(value));self.assertNotIn('owner',json.dumps(value))
  network.update(a,'done',200);self.assertEqual(network.snapshot('owner')['active'],0);self.assertEqual(network.snapshot('owner')['jobs'][0]['httpStatus'],200)
 def test_history_is_bounded_and_expired_requests_are_hidden(self):
  network=ReaderNetwork()
  for i in range(80):network.begin('owner',i%3,'model')
  self.assertEqual(len(network.jobs),64)
  for row in network.jobs.values():row['updated']=time.time()-601
  self.assertEqual(network.snapshot('owner')['jobs'],[])
