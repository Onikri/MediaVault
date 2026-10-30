import importlib.util,os,tempfile,time,unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('source_cache',Path(__file__).resolve().parents[1]/'deploy/oracle/prune-suwayomi-cache.py')
cache=importlib.util.module_from_spec(spec);spec.loader.exec_module(cache)


class SourceCacheTests(unittest.TestCase):
 def test_expiry_and_capacity_preserve_current_writes_and_downloads(self):
  with tempfile.TemporaryDirectory() as temp:
   project=Path(temp)/'.codex-local';root=project/'cache/suwayomi-reader';root.mkdir(parents=True)
   now=time.time()
   for name,age in [('expired',4000),('oldest',1000),('recent',500),('writing.tmp',10)]:
    p=root/name;p.write_bytes(b'x'*10);os.utime(p,(now-age,now-age))
   download=project/'downloads.cbz';download.write_bytes(b'user data')
   result=cache.prune(root,now=now,max_bytes=20)
   self.assertEqual(result,{'removed':2,'remainingBytes':20})
   self.assertEqual(sorted(p.name for p in root.iterdir()),['recent','writing.tmp'])
   self.assertEqual(download.read_bytes(),b'user data')
 def test_wrong_root_is_never_pruned(self):
  for p in ['/tmp','/opt/downloads','/opt/.codex-local/cache/models']:
   with self.assertRaises(ValueError):cache.prune(p)
