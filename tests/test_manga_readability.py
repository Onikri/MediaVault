"""Real health DB/caches; upstream page bytes and API responses are fixtures."""
import json,os,tempfile,time,unittest
from unittest.mock import patch,MagicMock
import manga_source_health as health
import manga_readability as readable
import mangaball_reader as reserve
import manga_discovery as discovery
from source_parser import SourceError

class ReadabilityTests(unittest.TestCase):
    def setUp(self):readable._cache.clear();reserve._cache.clear()
    def test_chapter_metadata_alone_does_not_mark_reader_working(self):
        value={'url':'https://source.example/title','episodes':[{'url':'https://source.example/chapter'}]}
        with patch('manga_sources.inspect',return_value={'url':value['episodes'][0]['url'],'pages':['https://pages.example/1.jpg']}),patch.object(readable,'PublicHttp') as http:
            http.return_value.deadline=time.monotonic()+60
            response=MagicMock();response.iter_content.return_value=[b'<html>blocked</html>'];http.return_value._open.return_value=(response,'https://pages.example/1.jpg')
            result=readable.verify(value);self.assertFalse(result['readable']);self.assertEqual(result['verifiedPages'],0)
            self.assertNotIn('blocked',result['readabilityError']);response.close.assert_called_once()
            response.iter_content.return_value=[b'\xff\xd8\xffpage-fixture']
            result=readable.verify(value,refresh=True);self.assertTrue(result['readable']);self.assertEqual(result['verifiedPages'],1)
            self.assertTrue(readable.verify(value)['readable']);self.assertEqual(http.return_value._open.call_count,2)

    def test_failed_reader_is_filtered_but_a_different_language_is_not(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'DISCOVERY_CACHE_DIR':folder}):
            health.record('1','Manga Ball','en','restricted','image','Источник не отдаёт страницы.')
            self.assertTrue(health.blocked('1'));self.assertFalse(health.blocked('2'))
            with patch.object(discovery,'installed_sources',return_value=[{'id':'1','name':'Manga Ball','lang':'en'},{'id':'2','name':'Manga Ball','lang':'ru'}]):
                rows=discovery.source_list()['sources'];self.assertEqual([r['id'] for r in rows],['2'])
            self.assertEqual(health.report()['unavailable'],1)
            with patch.object(health.time,'time',return_value=time.time()+health.TTL+1):self.assertFalse(health.blocked('1'))

    def test_reserve_server_preserves_selected_work_language_and_page_order(self):
        tid='685183da0b95030249822109';cid='68dde53b1ec6dc083a2f8069'
        saved={'realUrl':'https://mangaball.com/title-detail/'+tid};source={'lang':'en'};client=MagicMock();client.get.return_value=[{'index':2,'url':cid}]
        chapter={'id':cid,'title_id':tid,'lang':'en','pages':['https://cdn.example/first.webp','https://cdn.example/second.webp']}
        with patch.object(reserve,'public_url',side_effect=lambda url,**kw:url),patch.object(reserve,'PublicHttp') as http:
            http.return_value.document.return_value=(json.dumps({'data':{'chapter':chapter}}),'','')
            response=MagicMock();response.iter_content.return_value=[b'\xff\xd8\xffimage-fixture'];http.return_value._open.return_value=(response,'')
            raw,mime=reserve.page(client,saved,source,9,2,1);self.assertEqual(mime,'image/jpeg')
            self.assertIn('second.webp',http.return_value._open.call_args.args[0]);self.assertTrue(raw.startswith(b'\xff\xd8\xff'))
            with self.assertRaisesRegex(SourceError,'другую главу или язык'):reserve.page(client,saved,{'lang':'ru'},9,2,1)
            with self.assertRaises(SourceError):reserve.page(client,saved,source,9,3,0)

    def test_health_cache_is_not_an_account_or_page_store(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'DISCOVERY_CACHE_DIR':folder}):
            health.record('1','Reader','en','working','image')
            row=health.report()['sources'][0]
            self.assertEqual(set(row),{'id','name','language','status','phase','message','checked'})
