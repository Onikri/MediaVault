import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from wtas_ost import Unparsable,WtasOst,parse_sveltekit_data,tracks_from

PAYLOAD='''window.__sveltekit_data = (function(a,b,c,d,e){return {type:a,nodes:[null,{type:a,data:{anime:"show",animeName:"Show \\u003CTV\\u003E",mal:42,spotify:[{name:"OST",link:"https:\\u002F\\u002Fopen.spotify.com\\u002Falbum\\u002Fx"}],spotifyTrackMapping:{"Main Theme":"1234567890abcdefABCDEF",Bad:"nope"},episodes:[1,2],selectedEpisode:1}},{type:a,data:{episodeDuration:1400.5,printData:[{title:"Main Theme",album:c,fromSeconds:10.5,toSeconds:70,fromSecondsMatch:3,toSecondsMatch:4,trackLength:200,confidence:.05},{title:"Bad",album:c,fromSeconds:80,toSeconds:81,fromSecondsMatch:b,toSecondsMatch:b,trackLength:d,confidence:.002},{title:"",album:c,fromSeconds:1,toSeconds:2,confidence:1},{title:"Reverse",album:c,fromSeconds:9,toSeconds:5,confidence:1}],extra:e}}]}}("data",void 0,"Show OST",120,[1,-2.5e1,true,null]));'''


class Parser(unittest.TestCase):
    def test_references_literals_and_escapes_without_execution(self):
        data=parse_sveltekit_data(PAYLOAD)
        self.assertEqual(data['animeName'],'Show <TV>')
        self.assertEqual(data['spotify'][0]['link'],'https://open.spotify.com/album/x')
        self.assertEqual(data['printData'][0]['album'],'Show OST')
        self.assertIsNone(data['printData'][1]['fromSecondsMatch'])
        self.assertEqual(data['extra'],[1,-25.0,True,None])
        self.assertEqual(data['printData'][0]['confidence'],.05)

    def test_rejects_code_instead_of_data(self):
        with self.assertRaises(Unparsable):parse_sveltekit_data('window.x=(function(a){return {v:alert(1)}}(1));')
        with self.assertRaises(Unparsable):parse_sveltekit_data('<html>403 Forbidden</html>')

    def test_tracks_are_sorted_validated_and_flag_uncertain(self):
        rows=tracks_from(parse_sveltekit_data(PAYLOAD))
        self.assertEqual([r['title'] for r in rows],['Main Theme','Bad'])
        self.assertEqual(rows[0]['spotify'],'1234567890abcdefABCDEF')
        self.assertFalse(rows[0]['uncertain']);self.assertTrue(rows[1]['uncertain']);self.assertIsNone(rows[1]['spotify'])


class Service(unittest.TestCase):
    def test_index_by_mal_and_cached_episodes(self):
        calls=[]
        sitemap='<urlset><url><loc>https://wtas.moe/ost/show/1</loc></url><url><loc>https://wtas.moe/ost/show/2</loc></url><url><loc>https://wtas.moe/about</loc></url></urlset>'
        def fetch(url):
            calls.append(url)
            return sitemap if url.endswith('sitemap.xml') else PAYLOAD
        with tempfile.TemporaryDirectory() as folder:
            service=WtasOst(folder,fetch=fetch)
            index=service.index(wait=True)
            self.assertEqual(index['titles']['42']['episodes'],[1,2])
            first=service.episode(42,2)
            self.assertTrue(first['available']);self.assertEqual(first['tracks'][0]['title'],'Main Theme')
            self.assertTrue(first['url'].endswith('/ost/show/2'))
            requests=len(calls)
            self.assertEqual(WtasOst(folder,fetch=fetch).episode(42,2)['tracks'],first['tracks'])
            self.assertEqual(len(calls),requests,'Episode and index come from the disk cache')
            self.assertFalse(service.episode(42,9)['available'])
            self.assertFalse(service.episode(7,1)['available'])


if __name__=='__main__':unittest.main()
