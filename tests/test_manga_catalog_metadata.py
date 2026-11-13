"""Neutral metadata contracts; no real sources, images or account sessions."""
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from manga_catalog_index import initialize, upsert, browse
from manga_catalog_metadata import enrich
from source_parser import SourceError


class MetadataTests(unittest.TestCase):
    def row(self):
        return {'title':'Garden World','kind':'manga','provider':'suwayomi:1','sourceId':'1',
                'sourceUrl':'https://example.org/garden','url':'https://media.example/__manga/suwayomi/m/42',
                'tags':[],'language':'en'}

    def test_bridge_fetches_only_title_metadata_and_preserves_identity(self):
        client=MagicMock()
        client.get.return_value={'sourceId':1,'title':'Garden World','genre':['Drama']}
        with patch('suwayomi_bridge.parse_reference',return_value=(42,None,None)), patch('suwayomi_bridge.Client',return_value=client):
            result=enrich(self.row())
        client.get.assert_called_once_with('/manga/42?onlineFetch=true',timeout=35)
        client.close.assert_called_once()
        self.assertTrue(result['metadataInspected'])
        self.assertEqual(result['genres'],['Drama'])
        self.assertEqual(result['url'],self.row()['url'])

    def test_wrong_bridge_source_rejected(self):
        client=MagicMock();client.get.return_value={'sourceId':2,'title':'Other'}
        with patch('suwayomi_bridge.parse_reference',return_value=(42,None,None)), patch('suwayomi_bridge.Client',return_value=client), self.assertRaises(SourceError):enrich(self.row())

    def test_native_errors_do_not_turn_into_empty_success(self):
        with patch('manga_sources.site_for',return_value={}), self.assertRaises(SourceError):
            enrich({**self.row(),'url':'https://example.org/garden'})


class CatalogHttpTests(unittest.TestCase):
    def setUp(self):
        import api
        import tempfile,os,shutil
        from fastapi.testclient import TestClient
        self.api=api
        self.policy_directory=tempfile.TemporaryDirectory()
        policy_file=Path(self.policy_directory.name)/'manga-tag-policy.json'
        shutil.copyfile(Path(__file__).parent/'fixtures/manga-tag-policy.json',policy_file)
        self.policy_env=patch.dict(os.environ,{'MANGA_TAG_POLICY_FILE':str(policy_file),'DATA_DIR':self.policy_directory.name});self.policy_env.start()
        self.db=sqlite3.connect(':memory:',check_same_thread=False);initialize(self.db)
        row=MetadataTests().row();row['genres']=['Drama'];row['year']=2024
        upsert(self.db,[row]);self.key=browse(self.db)['items'][0]['catalogId']
        self.mock=patch('manga_discovery.manager',return_value=SimpleNamespace(db=self.db,lock=threading.RLock()))
        self.mock.start();self.before=dict(api.app.dependency_overrides)
        api.app.dependency_overrides[api.viewer]=lambda:{'sub':'fixture-viewer'}
        self.client=TestClient(api.app)

    def tearDown(self):
        self.client.close();self.api.app.dependency_overrides=self.before
        self.mock.stop();self.db.close()
        self.policy_env.stop();self.policy_directory.cleanup()

    def test_viewer_can_filter_browse_and_read_facets_but_not_backfill(self):
        response=self.client.get('/manga/catalog',params={'genre':'драма','language':'en','year':'2024','sourceIds':'1'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['total'],1)
        self.assertEqual(self.client.get('/manga/catalog/tags?sourceIds=1').json()['tags'][0]['works'],1)
        self.assertEqual(self.client.get('/manga/catalog/'+self.key).status_code,200)
        self.assertIn(self.client.post('/manga/catalog/backfill',json={}).status_code,(401,403))
        for params in ({'sourceIds':'http://localhost'},{'language':'invalid'},{'year':'bad'},{'age':'bad'}):
            self.assertEqual(self.client.get('/manga/catalog',params=params).status_code,422)

    def test_enrichment_accepts_only_known_ids_then_reuses_metadata(self):
        with patch('manga_catalog_metadata.enrich',return_value={**MetadataTests().row(),'tags':['Time Travel'],'metadataInspected':True}) as fetch:
            self.assertEqual(self.client.post('/manga/catalog/enrich',json={'ids':[self.key]}).json()['items'][0]['status'],'indexed')
            self.assertEqual(self.client.post('/manga/catalog/enrich',json={'ids':[self.key]}).json()['items'][0]['status'],'cached')
            fetch.assert_called_once()
        self.assertEqual(self.client.post('/manga/catalog/enrich',json={'ids':['a'*32]}).json()['items'][0]['status'],'missing')
        self.assertEqual(self.client.post('/manga/catalog/enrich',json={'ids':['https://example.org']}).status_code,422)
        self.assertEqual(self.client.post('/manga/catalog/enrich',json={'ids':[self.key]*4}).status_code,422)

    def test_public_projection_hides_private_rules_and_legacy_deployment_is_disabled(self):
        from manga_tag_policy import current
        value=self.client.get('/manga/tag-policy').json()
        self.assertEqual(value['scope'],'all')
        self.assertEqual(value['policy']['excludedTerms'],[])
        self.assertEqual(value['policy']['excludedPrefixes'],[])
        self.assertTrue(self.client.get('/manga/tag-policy',params={'revision':value['revision']}).json()['unchanged'])
        before=current().revision
        result=self.client.post('/ops/manga-tags/update',json={'commit':'a'*40,'policy':current().data})
        self.assertEqual(result.status_code,410)
        self.assertEqual(current().revision,before)


if __name__=='__main__':unittest.main()
