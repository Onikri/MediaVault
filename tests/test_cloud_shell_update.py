import importlib.util
import json
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('cloud_update',Path(__file__).resolve().parents[1]/'deploy/oracle/update-from-cloud-shell.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class UpdateTests(unittest.TestCase):
    def test_resuming_active_jobs_requires_an_explicit_option(self):
        self.assertNotIn('--resume-active-jobs',module.remote_script('a'*40))
        self.assertIn('--resume-active-jobs',module.remote_script('a'*40,resume_active=True))
    def test_read_only_inspection_does_not_run_the_updater_or_print_container_credentials(self):
        def cli(args,region):
            if args[:3]==['compute','instance','get']:return {'lifecycle-state':'RUNNING','compartment-id':'compartment','agent-config':{'plugins-config':[{'name':'Compute Instance Run Command','desired-state':'ENABLED'}]}}
            if args[:3]==['instance-agent','command','create']:
                script=json.loads(args[args.index('--content')+1])['source']['text']
                self.assertNotIn('update-existing.sh',script);self.assertNotIn('git fetch',script)
                self.assertNotIn("get('Env')",script);self.assertIn('com.docker.compose.project.working_dir',script)
                return {'id':'inspect-command'}
            return {'lifecycle-state':'SUCCEEDED','content':{'text':'installation inspection complete'}}
        result=module.deploy(None,'region',instance_id='ocid1.instance.oc1.eu-frankfurt-1.fixture',inspect=True,cli=cli,report=lambda _:None,pause=lambda _:None)
        self.assertEqual(result,{'inspected':True})
    def test_uses_existing_vm_and_only_enables_requested_plugin(self):
        calls=[]
        # Real regional instance OCIDs contain hyphens; global IAM fixtures do not.
        instance_id='ocid1.instance.oc1.eu-frankfurt-1.anthfixture123456789'
        def cli(args,region):
            calls.append(args)
            if args[:3]==['search','resource','structured-search']:return {'items':[{'identifier':instance_id}]}
            if args[:3]==['compute','instance','get']:return {'lifecycle-state':'RUNNING','compartment-id':'compartment','agent-config':{'plugins-config':[{'name':'Monitoring','desired-state':'DISABLED'}]}}
            if args[:3]==['compute','instance','update']:return {}
            if args[:3]==['instance-agent','command','create']:
                content=json.loads(args[args.index('--content')+1]);self.assertIn('sudo -n',content['source']['text']);self.assertEqual(content['source']['sourceType'],'TEXT');return {'id':'command-1'}
            return {'lifecycle-state':'SUCCEEDED','exit-code':0,'content':{'text':'health version 6 confirmed'}}
        value=module.deploy('a'*40,'eu-frankfurt-1',enable_plugin=True,cli=cli,report=lambda _:None,pause=lambda _:None)
        self.assertTrue(value['updated'])
        get=next(c for c in calls if c[:3]==['compute','instance','get'])
        self.assertEqual(get[get.index('--instance-id')+1],instance_id)
        update=next(c for c in calls if c[:3]==['compute','instance','update'])
        config=json.loads(update[update.index('--agent-config')+1])
        self.assertIn({'name':'Monitoring','desiredState':'DISABLED'},config['pluginsConfig'])
        self.assertTrue(all(c[:3] in [['search','resource','structured-search'],['compute','instance','get'],['compute','instance','update'],['instance-agent','command','create'],['instance-agent','command-execution','get']] for c in calls))
    def test_ambiguous_vm_or_missing_permissions_never_confirm_deployment(self):
        with self.assertRaises(module.UpdateError):module.deploy('a'*40,'region',cli=lambda *a:{'items':[]})
        with self.assertRaises(module.UpdateError):module.remote_script('main; rm -rf /')
        def cli(args,region):
            if args[:3]==['compute','instance','get']:return {'lifecycle-state':'RUNNING','compartment-id':'compartment','agent-config':{'plugins-config':[{'name':'Compute Instance Run Command','desired-state':'ENABLED'}]}}
            if args[:3]==['instance-agent','command','create']:return {'id':'command'}
            return {'lifecycle-state':'FAILED','content':{'text':'sudo denied'}}
        with self.assertRaises(module.UpdateError):module.deploy('a'*40,'region',instance_id='ocid1.instance.oc1.fixture',cli=cli,report=lambda _:None,pause=lambda _:None)
    def test_eventual_command_execution_visibility_is_retried_without_a_second_deploy(self):
        attempts=[];created=[]
        def cli(args,region):
            if args[:3]==['compute','instance','get']:return {'lifecycle-state':'RUNNING','compartment-id':'compartment','agent-config':{'plugins-config':[{'name':'Compute Instance Run Command','desired-state':'ENABLED'}]}}
            if args[:3]==['instance-agent','command','create']:created.append(args);return {'id':'command'}
            attempts.append(args)
            if len(attempts)==1:raise module.UpdateError('Oracle: NotAuthorizedOrNotFound')
            return {'lifecycle-state':'SUCCEEDED','exit-code':0,'content':{'text':'health version 6 confirmed'}}
        value=module.deploy('a'*40,'region',instance_id='ocid1.instance.oc1.fixture',cli=cli,report=lambda _:None,pause=lambda _:None)
        self.assertTrue(value['updated']);self.assertEqual(len(created),1);self.assertEqual(len(attempts),2)
