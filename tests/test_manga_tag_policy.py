"""Neutral tag facts across all registered domains; no upstream/media requests."""
import hashlib,hmac,json,os,sqlite3,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from manga_tag_policy import Policy,current,canonical_json
from manga_tag_deploy import apply,authenticate,DeployError,atomic_write
from manga_catalog_index import initialize,upsert,browse,tags,reindex
from manga_source_coverage import SOURCES

BASE={'schemaVersion':1,'excludedTerms':[],'excludedPrefixes':[], 'tags':[
 {'key':'fantasy','label':'Фэнтези','aliases':['Fantasy','幻想','판타지']},
 {'key':'drama','label':'Драма','aliases':['Drama']}]}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'manga-tag-policy.json'
        atomic_write(self.path,canonical_json(BASE))
        self.env=patch.dict(os.environ,{'DATA_DIR':self.temp.name,'MANGA_TAG_POLICY_FILE':str(self.path)});self.env.start()
        self.db=sqlite3.connect(':memory:');initialize(self.db)
        self.store=SimpleNamespace(db=self.db,lock=threading.RLock())

    def tearDown(self):self.db.close();self.env.stop();self.temp.cleanup()

    def put(self,data):
        with patch('manga_tag_deploy.committed_policy',return_value=Policy(data)):
            return apply({'commit':'a'*40,'policy':data},self.store)

    def seed(self):
        for i,(domain,*_) in enumerate(SOURCES):
            upsert(self.db,[{'title':'Garden World','provider':'fixture:'+str(i),'sourceId':str(i+1),
                'sourceUrl':'https://'+domain+'/catalog/neutral','kind':'manga','tags':[['Fantasy','幻想','판타지'][i%3],'Journey'],
                'genres':['Drama'],'language':'en'}])
        self.db.commit()

    def test_delete_and_restore_rebuild_all_18_source_projections(self):
        self.seed();self.assertEqual(browse(self.db,tag='Fantasy')['total'],18)
        removed={**BASE,'tags':[BASE['tags'][1]]}
        result=self.put(removed);self.assertEqual(result['reindexedTitles'],18)
        self.assertEqual(browse(self.db,tag='Fantasy')['total'],0)
        self.assertTrue(all(not row['tags'] for row in browse(self.db)['items']))
        self.assertNotIn('fantasy',{r['key'] for r in tags(self.db)['tags']})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM catalog_tags WHERE tag_key='fantasy'").fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM catalog_tag_facts').fetchone()[0],54)
        restored={**BASE,'tags':[{**BASE['tags'][0],'label':'Чудесные миры'},BASE['tags'][1],
            {'key':'journey','label':'Путешествие','aliases':['Journey','旅','여행']}]}
        self.put(restored)
        self.assertEqual(browse(self.db,tag='Journey')['total'],18)
        self.assertEqual(browse(self.db,tag='幻想')['total'],18)
        self.assertTrue(all('Чудесные миры' in row['tags'] for row in browse(self.db)['items']))
        self.assertTrue(self.put(restored)['unchanged'])

    def test_exclusion_of_any_alias_hides_all_language_variants(self):
        self.seed();self.put({**BASE,'excludedTerms':['Fantasy']})
        for name in ('Fantasy','幻想','판타지','Фэнтези'):
            self.assertEqual(current().key(name),'')
            self.assertEqual(browse(self.db,tag=name)['total'],0)
        self.put(BASE);self.assertEqual(browse(self.db,tag='Fantasy')['total'],18)

    def test_source_specific_alias_is_not_assigned_to_other_sources(self):
        data={**BASE,'tags':[{**BASE['tags'][0],'sourceAliases':{'one.example':['Special label']}},BASE['tags'][1]]}
        policy=Policy(data)
        self.assertEqual(policy.key('Special label','one.example'),'fantasy')
        self.assertEqual(policy.key('Special label','two.example'),'')

    def test_invalid_or_superseded_config_does_not_mutate_index(self):
        self.seed();old=current().revision
        invalid={**BASE,'tags':[BASE['tags'][0],{**BASE['tags'][1],'aliases':['Fantasy']}]}
        with self.assertRaises(DeployError):apply({'commit':'a'*40,'policy':invalid},self.store,verify_commit=False)
        self.assertEqual(current().revision,old)
        self.assertEqual(browse(self.db,tag='Fantasy')['total'],18)
        with patch('manga_tag_deploy.committed_policy',return_value=Policy(BASE)),self.assertRaises(DeployError) as raised:
            apply({'commit':'b'*40,'policy':{**BASE,'tags':[]}},self.store)
        self.assertEqual(raised.exception.status,409)

    def test_failed_reindex_rolls_back_database_and_keeps_active_policy(self):
        self.seed();old=self.path.read_bytes()
        def fail(db,policy):db.execute('DELETE FROM catalog_tags');raise sqlite3.OperationalError('fixture rollback')
        with patch('manga_catalog_index.reindex',side_effect=fail),self.assertRaises(sqlite3.OperationalError):
            self.put({**BASE,'tags':[]})
        self.assertEqual(self.path.read_bytes(),old)
        self.assertEqual(browse(self.db,tag='Fantasy')['total'],18)

    def test_signature_covers_entire_body_and_expires(self):
        key=b'fixture-deploy-key-only';stamp='1800000000';body={'commit':'a'*40,'policy':BASE}
        signature=hmac.new(key,stamp.encode()+b'.'+canonical_json(body),hashlib.sha256).hexdigest()
        authenticate(body,stamp,signature,key=key,now=int(stamp))
        for value,when in [({**body,'commit':'b'*40},int(stamp)),(body,int(stamp)+301)]:
            with self.assertRaises(DeployError):authenticate(value,stamp,signature,key=key,now=when)

    def test_startup_rebuilds_when_policy_changed_and_old_discovery_cannot_resurrect_it(self):
        self.seed();atomic_write(self.path,canonical_json({**BASE,'tags':[BASE['tags'][1]]}))
        initialize(self.db)
        upsert(self.db,[{'title':'Garden World','provider':'fixture:0','sourceUrl':'https://'+SOURCES[0][0]+'/catalog/neutral','tags':['Fantasy'],'genres':[]}])
        self.assertEqual(browse(self.db,tag='Fantasy')['total'],0)


if __name__=='__main__':unittest.main()
