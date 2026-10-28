"""Contract tests: catalog/install calls are fixtures, journal and thread are real."""
import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import suwayomi_installer as packs
from source_parser import SourceError

class LanguagePackTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DATA_DIR':self.temp.name});self.env.start()
 def tearDown(self):
  if packs._worker:packs._worker.join(2)
  self.env.stop();self.temp.cleanup()
 def test_all_requested_languages_multilingual_resume_and_isolated_failures(self):
  installed={'ru'};attempted=[]
  def catalog():return [{'pkgName':lang,'name':lang,'lang':lang,'installed':lang in installed,'obsolete':lang=='ko'} for lang in ['ru','en','ja','ko','all','fr']]
  def install(name):
   attempted.append(name)
   if name=='ja':raise RuntimeError('Never log sensitive-provider-detail')
   installed.add(name)
  with patch.object(packs,'extensions',side_effect=catalog),patch.object(packs,'install',side_effect=install):
   started=packs.start(['ru','en','ja','ko']);packs._worker.join(3);state=packs.status()
   self.assertEqual(state['state'],'partial');self.assertEqual(state['total'],4);self.assertEqual(state['completed'],4)
   self.assertEqual(state['alreadyInstalled'],1);self.assertEqual(state['installed'],2);self.assertEqual(attempted,['all','en','ja'])
   self.assertEqual(state['failed'][0]['package'],'ja');self.assertNotIn('sensitive',packs.journal().read_text())
   attempted.clear();packs.start(['ru','en','ja','ko']);packs._worker.join(3)
   self.assertEqual(attempted,['ja']);self.assertEqual(packs.status()['alreadyInstalled'],3)
 def test_interrupted_journal_is_visible_and_unsupported_language_is_rejected(self):
  packs.save({'state':'running','completed':20,'total':50})
  self.assertEqual(packs.status()['state'],'interrupted')
  with self.assertRaises(SourceError):packs.start(['fr'])
