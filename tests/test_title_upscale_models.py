import os,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
import title_upscale_model as models

class TitleModelsTests(unittest.TestCase):
 def test_only_explicit_hash_checked_models_are_exposed(self):
  app=FastAPI();models.install(app);client=TestClient(app)
  with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'TITLE_MODEL_DIR':folder}):
   self.assertEqual(client.get('/models/unknown.onnx').status_code,404)
   for name,(_,size) in models.MODELS.items():
    self.assertEqual(client.get('/models/'+name).status_code,503)
    path=Path(folder)/name;path.write_bytes(b'x'*size)
    self.assertEqual(client.get('/models/'+name).status_code,503)
   name=next(iter(models.MODELS));raw=b'model-fixture';Path(folder,name).write_bytes(raw)
   with patch.dict(models.MODELS,{name:(hashlib.sha256(raw).hexdigest(),len(raw))}):
    response=client.get('/models/'+name);self.assertEqual(response.content,raw);self.assertIn('immutable',response.headers['cache-control'])
 def test_weight_manifests_have_distinct_immutable_content(self):
  self.assertEqual(len(models.MODELS),3);self.assertEqual(len({value[0] for value in models.MODELS.values()}),3)
  self.assertTrue(all(len(value[0])==64 for value in models.MODELS.values()))
