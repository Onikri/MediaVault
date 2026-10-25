import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from aniliberty_source import search,inspect,API,SITE
from site_adapters import BY_ID,search_site,inspect_source
from source_parser import public_url,SourceError


RELEASE={'id':1,'alias':'dandadan','name':{'main':'Дандадан','english':'Dandadan'},'year':2024,
         'episodes':[{'ordinal':1,'hls_720':'https://cdn.example.com/1.m3u8'},
                     {'ordinal':2,'hls_720':None},{'ordinal':3,'hls_480':'https://cdn.example.com/3.m3u8'}]}

class Http:
    def __init__(self,release=None):self.calls=[];self.release=release or RELEASE
    def document(self,url,**kwargs):
        self.calls.append(url)
        data=[self.release] if '/app/search/releases?' in url else self.release
        return json.dumps(data),url,{}


class AniLibertySourceTests(unittest.TestCase):
    def test_search_uses_public_catalogue_with_exact_identity_metadata(self):
        http=Http();result=search_site(BY_ID['anilibria'],'Дандадан',http=http)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['results'][0]['aliases'],['Дандадан','Dandadan'])
        self.assertEqual(result['results'][0]['year'],2024)
        self.assertEqual(result['results'][0]['ids'],{},'A provider release ID is not a MAL ID')
        self.assertTrue(http.calls[0].startswith(API+'/app/search/releases?'))

    def test_inspect_exposes_only_published_episode_links_and_studio(self):
        http=Http();result=inspect_source(SITE+'/anime/releases/release/dandadan',http=http)
        self.assertEqual([e['number'] for e in result['episodes']],[1,3])
        self.assertEqual(result['dubs'][0]['name'],'AniLibria.TV')
        self.assertEqual(result['dubs'][0]['player'],'AniLiberty')
        self.assertTrue(all('/episodes/' in e['url'] for e in result['episodes']))
        self.assertEqual(http.calls,[API+'/anime/releases/dandadan'])

    def test_selected_episode_or_translation_is_not_replaced_by_another(self):
        base=SITE+'/anime/releases/release/dandadan'
        result=inspect(base+'/episodes/3',Http())
        self.assertEqual([e['number'] for e in result['episodes']],[3])
        with self.assertRaises(SourceError):inspect(base,Http(),dub_url=base+'/episodes/2')

    def test_geoblocked_release_is_not_presented_as_available(self):
        with self.assertRaises(SourceError):inspect(SITE+'/anime/releases/release/dandadan',Http({**RELEASE,'is_blocked_by_geo':True}))

    def test_only_the_named_public_catalogue_route_is_added_to_api_allowlist(self):
        self.assertEqual(public_url(API+'/app/search/releases?query=test',resolve_dns=False),API+'/app/search/releases?query=test')
        for url in [API+'/accounts/users/auth/login',API+'/app/search/accounts','https://api.other.example.com/app/search/releases']:
            with self.assertRaises(SourceError):public_url(url,resolve_dns=False)
