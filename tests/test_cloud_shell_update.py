import importlib.util
import json
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('cloud_update',Path(__file__).resolve().parents[1]/'deploy/oracle/update-from-cloud-shell.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class UpdateTests(unittest.TestCase):
    def test_uses_existing_vm_and_only_enables_requested_plugin(self):
        calls=[]
        def cli(args,region):
            calls.append(args)
            if args[:3]==['search','resource','structured-search']:return {'items':[{'identifier':'ocid1.instance.oc1.fixture'}]}
            if args[:3]==['compute','instance','get']:return {'lifecycle-state':'RUNNING','compartment-id':'compartment','agent-config':{'plugins-config':[{'name':'Monitoring','desired-state':'DISABLED'}]}}
            if args[:3]==['compute','instance','update']:return {}
            if args[:3]==['instance-agent','command','create']:
                content=json.loads(args[args.index('--content')+1]);self.assertIn('sudo -n',content['source']['text']);self.assertEqual(content['source']['sourceType'],'TEXT');return {'id':'command-1'}
            return {'lifecycle-state':'SUCCEEDED','exit-code':0,'content':{'text':'health version 6 confirmed'}}
        value=module.deploy('a'*40,'eu-frankfurt-1',enable_plugin=True,cli=cli,report=lambda _:None,pause=lambda _:None)
        self.assertTrue(value['updated'])
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
