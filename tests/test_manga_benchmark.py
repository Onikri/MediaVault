import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/benchmarks'))
from metrics import match_boxes,cer
from translation_inputs import inputs_for
from translation_requests import segment_request
class Tokenizer:
 def encode(self,text,out_type=str):return text.split()
class BenchmarkContracts(unittest.TestCase):
 def test_one_prediction_cannot_match_two_source_regions(self):
  r=match_boxes([[0,0,100,100],[10,0,110,100]],[[0,0,110,100]])
  self.assertEqual((r['tp'],r['fn'],r['fp']),(1,1,0))
 def test_extra_regions_reduce_precision(self):
  r=match_boxes([[0,0,10,10]],[[0,0,10,10],[30,30,40,40]])
  self.assertEqual(r['recall'],1);self.assertEqual(r['precision'],.5)
 def test_negation_loss_is_not_normalized_away(self):
  self.assertGreater(cer('I DO NOT BELIEVE','I DO BELIEVE'),0)
 def test_marian_requires_source_eos(self):
  tokens,kwargs=inputs_for('opus',[{'source':'Do not open','language':'en'}],Tokenizer())
  self.assertEqual(tokens,[['Do','not','open','</s>']]);self.assertFalse(kwargs)
 def test_nllb_prefix_has_one_example_per_source(self):
  cases=[{'source':'Hello','language':'en'},{'source':'こんにちは','language':'ja'}]
  tokens,kwargs=inputs_for('nllb',cases,Tokenizer())
  self.assertEqual(tokens,[['eng_Latn','Hello','</s>'],['jpn_Jpan','こんにちは','</s>']]);self.assertEqual(kwargs['target_prefix'],[['rus_Cyrl'],['rus_Cyrl']])

class PromptContracts(unittest.TestCase):
 def test_hymt_uses_its_published_single_user_message_and_sampling(self):
  request=segment_request("Do not open!","hymt","hymt2");self.assertEqual([m["role"] for m in request["messages"]],["user"]);self.assertTrue(request["messages"][0]["content"].endswith("Do not open!"));self.assertIn("Russian",request["messages"][0]["content"]);self.assertEqual(request["temperature"],.7);self.assertEqual(request["top_p"],.6)
