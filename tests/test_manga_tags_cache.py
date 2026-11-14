import json,tempfile,threading,unittest
from pathlib import Path
from unittest import mock
import manga_catalog_index as index

class TagFacetCache(unittest.TestCase):
    def setUp(self):
        index._tag_cache.clear();index._tag_refreshing.clear();index._tag_loaded[0]=False
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.path=Path(self.folder.name)/'facets.json'
        self.calls=[];self.now=[0.0]
        def fake(conn,**kwargs):
            self.calls.append(kwargs);return {'tags':[{'key':'k%d'%len(self.calls)}]}
        patch=mock.patch.object(index,'tags',side_effect=fake);patch.start();self.addCleanup(patch.stop)
        self.lock=threading.RLock()
    def read(self,**kwargs):
        return index.cached_tags(None,self.lock,clock=lambda:self.now[0],background=False,path=self.path,**kwargs)
    def test_repeated_reads_are_served_from_memory(self):
        first=self.read(limit=500,language='all')
        self.assertEqual(self.read(limit=500,language='all'),first)
        self.assertEqual(len(self.calls),1)
    def test_filters_have_their_own_answers(self):
        self.read(limit=500,language='all');self.read(limit=500,language='ru')
        self.assertEqual(len(self.calls),2)
    def test_stale_answer_is_returned_while_one_refresh_replaces_it(self):
        first=self.read(limit=500)
        self.now[0]=index.TAGS_TTL+1
        self.assertEqual(self.read(limit=500),first)
        self.assertEqual(len(self.calls),2)
        self.assertNotEqual(self.read(limit=500),first)
    def test_policy_change_is_a_new_key(self):
        self.read(limit=500)
        with mock.patch.object(index,'current') as policy:
            policy.return_value.revision='other'
            self.read(limit=500)
        self.assertEqual(len(self.calls),2)

    def test_restart_answers_from_disk_without_recounting(self):
        first=self.read(limit=500)
        self.assertEqual(len(json.loads(self.path.read_text(encoding='utf-8'))),1)
        index._tag_cache.clear();index._tag_loaded[0]=False
        self.assertEqual(self.read(limit=500),first)
        self.assertEqual(len(self.calls),1)
    def test_broken_file_is_ignored(self):
        self.path.write_text('{not json',encoding='utf-8')
        self.read(limit=500)
        self.assertEqual(len(self.calls),1)

if __name__=='__main__':unittest.main()
