"""Cloud Shell request contracts and VM rollback, with explicit CLI fixtures."""
import importlib.util,io,json,tempfile,unittest
from contextlib import redirect_stdout
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

path=Path(__file__).resolve().parents[1]/'deploy/oracle/update-manga-progress.py'
spec=importlib.util.spec_from_file_location('progress_deploy',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
REV='a'*40
INSTANCE='ocid1.instance.oc1.eu-frankfurt-1.example'

class CloudShellContract(unittest.TestCase):
 def test_existing_cli_submits_exactly_one_pinned_command_without_registering_keys(self):
  responses=[{'compartment-id':'compartment'},{'id':'command'},{'lifecycle-state':'SUCCEEDED','content':{'exit-code':0,'text':'{"updated":true}'}}]
  with patch.object(module.shutil,'which',return_value='/cli/oci'),patch.object(module,'cli',side_effect=responses) as cli,redirect_stdout(io.StringIO()):module.cloud_shell(REV,INSTANCE,'eu-frankfurt-1')
  self.assertEqual(cli.call_count,3);create=cli.call_args_list[1].args;self.assertEqual(create[1:4],('instance-agent','command','create'));self.assertNotIn('iam',create)
  target=json.loads(create[create.index('--target')+1]);self.assertEqual(target,{'instanceId':INSTANCE})
  content=json.loads(create[create.index('--content')+1]);self.assertEqual(content['source']['sourceType'],'TEXT');source=content['source']['text'];self.assertLess(len(source.encode()),4096);self.assertIn('/'+REV+'/deploy/oracle/update-manga-progress.py',source)
  compile(source.split("<<'MV_PROGRESS'\n")[1].rsplit('\nMV_PROGRESS',1)[0],'<bootstrap>','exec')
  get=cli.call_args_list[2].args;self.assertEqual(get[1:4],('instance-agent','command-execution','get'));self.assertEqual(get[get.index('--command-id')+1],'command')
 def test_uncertain_or_failed_submission_is_not_repeated(self):
  with patch.object(module.shutil,'which',return_value='/cli/oci'),patch.object(module,'cli',side_effect=[{'compartment-id':'compartment'},module.UpdateError('unknown submission')]) as cli:
   with self.assertRaisesRegex(module.UpdateError,'unknown submission'):module.cloud_shell(REV,INSTANCE,'eu-frankfurt-1')
  self.assertEqual(cli.call_count,2)

class VMUpdateRollback(unittest.TestCase):
 def exercise(self,fail_new):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);data=root/'data';data.mkdir();(data/'google-api-key').write_text('private-fixture-not-a-real-key')
   old={'Id':'batch-old','Config':{'Image':'existing-image'},'NetworkSettings':{'Networks':{'private':{}}},'Mounts':[{'Type':'bind','Source':str(data),'Destination':'/data','RW':True},{'Type':'bind','Source':str(root/'models'),'Destination':'/models','RW':False},{'Type':'bind','Source':str(root/'importer'),'Destination':'/importer','RW':False}]}
   importer={'Id':'original-importer','RestartCount':0};calls=[]
   def inspect(arguments,**kwargs):return json.dumps([importer if arguments[-1]=='oracle-importer-1' else old]).encode()
   def run(arguments,**kwargs):
    calls.append(arguments);returncode=0;stdout=''
    if arguments[:2]==['docker','inspect']:returncode=1
    elif arguments[:2]==['docker','exec'] and arguments[3:5]==['python','-c']:
     returncode=1 if fail_new and arguments[2]=='mediavault-manga-batch' else 0
     stdout=json.dumps({'ready':True,'configured':True,'progressVersion':1})
    return CompletedProcess(arguments,returncode,stdout=stdout,stderr='')
   with patch.object(module.os,'geteuid',return_value=0),patch.object(module.subprocess,'run',side_effect=run),patch.object(module.subprocess,'check_output',side_effect=inspect),patch.object(module.urllib.request,'urlopen',side_effect=lambda *a,**k:io.BytesIO(b'pass\n')),patch.object(module.time,'sleep'),redirect_stdout(io.StringIO()):
    if fail_new:
     with self.assertRaises(module.UpdateError):module.install(REV,root=root)
    else:module.install(REV,root=root)
   self.assertEqual((data/'google-api-key').read_text(),'private-fixture-not-a-real-key')
   self.assertFalse(any('oracle-importer-1' in c for c in calls))
   backup='mediavault-manga-batch-before-progress-'+REV[:8]
   if fail_new:self.assertIn(['docker','rename',backup,'mediavault-manga-batch'],calls);self.assertIn(['docker','start','mediavault-manga-batch'],calls)
   else:
    result=json.loads((root/('live-progress-'+REV[:12])/'result.json').read_text());self.assertTrue(result['importerUnchanged']);self.assertTrue(result['googleKeyPreserved'])
 def test_success_preserves_importer_and_existing_google_key(self):self.exercise(False)
 def test_failed_new_service_restores_previous_container(self):self.exercise(True)
