"""Caddy configuration regression; live >512KB proof is recorded separately."""
import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('reader_google_route',Path(__file__).resolve().parents[1]/'deploy/oracle/enable-reader-google.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class GoogleRouteTests(unittest.TestCase):
 def test_existing_google_route_excludes_small_generic_body_limit(self):
  original='''server {
    @nonLmt not path /reader/lmt/*
    request_body @nonLmt { max_size 512KB }
    @readerGoogle path /reader/google/generate
    request_body @readerGoogle { max_size 20MB }
    @lmt path /reader/lmt/*
}
'''
  result=module.configuration(original)
  self.assertIn('@nonLmt not path /reader/lmt/* /reader/google/generate\n',result)
  self.assertIn('max_size 512KB',result)
  self.assertEqual(module.configuration(result),result)
 def test_new_route_keeps_unrelated_limits(self):
  result=module.configuration('    @nonLmt not path /reader/lmt/*\n    @lmt path /reader/lmt/*\n')
  self.assertEqual(result.count('@readerGoogle path'),1)
  self.assertIn('max_size 20MB',result)
