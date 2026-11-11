import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import suwayomi_bridge as bridge
import manga_discovery as discovery

COMICI='<html><title>アクセスを制限しております</title><p>現在、一部の通信環境からのアクセスを制限しております。</p></html>'

class Reply:
    def __init__(self,status,text):self.status_code=status;self.body=text.encode()
    def iter_content(self,size):yield self.body
    def close(self):pass

class OriginBlockTest(unittest.TestCase):
    def setUp(self):bridge._origins.clear()
    def probe(self,status,text,url='https://comic-ryu.jp'):
        calls=[]
        def fetch(u):calls.append(u);return Reply(status,text)
        with patch.object(bridge,'public_url',lambda value,**_:value):
            first=bridge.origin_block(url,fetch=fetch,clock=lambda:100)
            second=bridge.origin_block(url,fetch=fetch,clock=lambda:200)
        return first,second,calls

    def test_cloudfront_geo_wall_becomes_region(self):
        first,second,calls=self.probe(403,COMICI)
        self.assertEqual(first.code,'region')
        self.assertIs(second,first)
        self.assertEqual(calls,['https://comic-ryu.jp/'])  # one request per host per TTL

    def test_plain_forbidden_stays_restricted_and_reachable_site_explains_nothing(self):
        self.assertEqual(self.probe(403,'<h1>Forbidden</h1>')[0].code,'restricted')
        bridge._origins.clear()
        self.assertIsNone(self.probe(200,'<html>ok</html>')[0])

    def test_private_or_invalid_base_url_is_never_fetched(self):
        def fetch(u):raise AssertionError('must not fetch')
        self.assertIsNone(bridge.origin_block('http://suwayomi:4567',fetch=fetch))
        self.assertIsNone(bridge.origin_block('',fetch=fetch))

    def test_discovery_reports_region_instead_of_bare_500(self):
        class Client:
            def get(self,*a,**k):raise bridge.bridge_error(500,'server error')
            def close(self):pass
        region=bridge.BridgeError('region','Источник открыт только из своей страны (обычно Япония) и закрыт для сервера.')
        source={'id':'7','name':'Comic Ryu','lang':'ja','baseUrl':'https://comic-ryu.jp'}
        with patch.object(bridge,'Client',Client),patch.object(bridge,'origin_block',return_value=region) as probe:
            with self.assertRaises(bridge.BridgeError) as caught:discovery.search_source(source,'jujutsu')
        self.assertEqual(caught.exception.code,'region');probe.assert_called_once_with('https://comic-ryu.jp')

    def test_discovery_keeps_original_error_when_origin_is_fine(self):
        class Client:
            def get(self,*a,**k):raise bridge.bridge_error(500,'server error')
            def close(self):pass
        source={'id':'8','name':'HDoujin','lang':'ja','baseUrl':'https://hdoujin.org'}
        with patch.object(bridge,'Client',Client),patch.object(bridge,'origin_block',return_value=None):
            with self.assertRaises(bridge.BridgeError) as caught:discovery.search_source(source,'x')
        self.assertEqual(caught.exception.code,'upstream')

if __name__=='__main__':unittest.main()
