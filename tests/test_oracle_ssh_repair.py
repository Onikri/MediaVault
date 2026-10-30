import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('ssh_repair', Path(__file__).resolve().parents[1] / 'deploy/oracle/allow-ssh-from-cloud-shell.py')
repair = importlib.util.module_from_spec(spec);spec.loader.exec_module(repair)


class SshRepairTests(unittest.TestCase):
    def run_repair(self, *, public='141.144.225.42', nsg=False, rules=None):
        calls=[]
        def cli(args, region):
            calls.append(args)
            if args[0]=='search':return {'data':{'items':[{'identifier':'ocid1.instance.oc1.example'}]}}
            if args[:3]==['compute','instance','list-vnics']:
                return {'data':[{'public-ip':public,'subnet-id':'subnet','nsg-ids':['nsg'] if nsg else []}]}
            if args[:3]==['network','subnet','get']:return {'data':{'security-list-ids':['list']}}
            if args[:3]==['network','security-list','get']:
                return {'etag':'version-123','data':{'ingress-security-rules':rules or [{'protocol':'6','source':'0.0.0.0/0','tcp-options':{'destination-port-range':{'min':443,'max':443}}}]}}
            if args[:4]==['network','nsg','rules','list']:return {'data':[]}
            return {'data':{}}
        message=repair.repair('141.144.225.42','192.0.2.10/32','eu-frankfurt-1',request=cli)
        return calls,message

    def test_add_preserves_existing_https_and_etag_without_replacing_egress(self):
        calls,_=self.run_repair();update=calls[-1]
        self.assertEqual(update[:3],['network','security-list','update'])
        self.assertEqual(update[update.index('--if-match')+1],'version-123')
        rules=json.loads(update[update.index('--ingress-security-rules')+1])
        self.assertEqual(rules[0]['tcpOptions']['destinationPortRange'],{'min':443,'max':443})
        self.assertEqual(rules[1]['source'],'192.0.2.10/32')
        self.assertNotIn('--egress-security-rules',update)

    def test_nsg_add_is_additive_and_existing_rule_is_idempotent(self):
        calls,_=self.run_repair(nsg=True)
        self.assertEqual(calls[-1][:4],['network','nsg','rules','add'])
        calls,message=self.run_repair(rules=[{'protocol':'6','source':'192.0.2.0/24','tcp-options':{'destination-port-range':{'min':22,'max':22}}}])
        self.assertIn('already permitted',message)
        self.assertFalse(any('update' in c or 'add' in c for c in calls))

    def test_wrong_vm_or_broad_source_cannot_be_modified(self):
        with self.assertRaises(repair.RepairError):self.run_repair(public='198.51.100.1')
        with self.assertRaises(repair.RepairError):repair.repair('141.144.225.42','0.0.0.0/0','eu-frankfurt-1',request=lambda *_:self.fail('Must not call OCI'))
