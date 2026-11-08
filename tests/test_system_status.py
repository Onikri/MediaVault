import json,os,tempfile,time,unittest
from unittest import mock
import system_status


class SystemStatusTests(unittest.TestCase):
    def test_host_metrics_have_disk_and_memory_shape(self):
        with tempfile.TemporaryDirectory() as data:
            host=system_status.host(data)
        self.assertGreater(host['disk']['total'],0)
        self.assertEqual(set(host),{'cpu','cores','load','memory','disk','uptime'})

    def test_host_report_reads_helper_file_and_flags_stale_data(self):
        with tempfile.TemporaryDirectory() as data:
            self.assertEqual(system_status.host_report(data),{'available':False})
            with open(os.path.join(data,'host-status.json'),'w') as handle:
                json.dump({'at':1000,'containers':[{'name':'importer'}],'processes':[],'disk':{'total':1,'used':1,'free':0}},handle)
            fresh=system_status.host_report(data,now=1030);old=system_status.host_report(data,now=1200)
        self.assertTrue(fresh['available']);self.assertFalse(fresh['stale']);self.assertTrue(old['stale'])
        self.assertEqual(fresh['containers'][0]['name'],'importer')

    def test_drive_quota_is_cached_per_owner(self):
        system_status._quota.clear()
        credential=mock.Mock(valid=True,token='t')
        response=mock.Mock();response.json.return_value={'storageQuota':{'limit':'100','usage':'40','usageInDrive':'30','usageInDriveTrash':'5'}}
        with mock.patch.object(system_status.requests,'get',return_value=response) as get:
            first=system_status.drive_quota('owner',lambda subject:credential,now=10)
            second=system_status.drive_quota('owner',lambda subject:credential,now=20)
        self.assertEqual(get.call_count,1)
        self.assertEqual(first,{'limit':100,'usage':40,'drive':30,'trash':5,'checkedAt':10})
        self.assertIs(first,second)

    def test_unlimited_drive_reports_no_limit(self):
        system_status._quota.clear()
        response=mock.Mock();response.json.return_value={'storageQuota':{'usage':'7'}}
        with mock.patch.object(system_status.requests,'get',return_value=response):
            value=system_status.drive_quota('o',lambda subject:mock.Mock(valid=True,token='t'),now=1)
        self.assertIsNone(value['limit']);self.assertEqual(value['usage'],7)


if __name__=='__main__':
    unittest.main()
