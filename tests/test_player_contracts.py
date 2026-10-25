"""All eight reference players through MediaVault's source-only resolver bridge."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from source_parser import PublicHttp,Resolver,public_url,playback_headers,parse_page
from player_compat import KodikPlayer
from anime_dl_core.errors import ExtractionError

FIXTURES=Path(__file__).parent/'fixtures/players'

class FixtureHttp(PublicHttp):
    def __init__(self,routes):self.routes=routes;self.calls=[]
    def document(self,url,**kwargs):
        public_url(url,resolve_dns=False);self.calls.append((url,kwargs))
        for pattern,name in self.routes.items():
            if pattern in url:return (FIXTURES/name).read_text(),url,{}
        raise AssertionError('Unexpected source request: '+url)
    def close(self):pass


class PlayerContractTests(unittest.TestCase):
    def test_all_eight_real_response_formats_return_media_and_required_headers(self):
        samples=[
            ('Aniboom','https://aniboom.one/embed/9G1MJ6NMV8z?episode=1&translation=30',{'/embed/':'aniboom_embed.html','master.m3u8':'aniboom_master.m3u8'}),
            ('CVH','https://animego.me/cdn-iframe/51019/AniDub%20Online/1/1',{'/playlist?':'cvh_playlist.json','/video/':'cvh_video.json'}),
            ('Kodik','https://kodikplayer.com/seria/1304528/932d5da818729ec5ccc9be7968ee3717/720p',{'/seria/':'kodik_embed.html','/assets/js/':'kodik_player_script.js','/ftor':'kodik_ftor.json'}),
            ('Sibnet','https://video.sibnet.ru/shell.php?videoid=2589828',{'shell.php':'sibnet_shell.html'}),
            ('Animedia','https://aser.pro/vod/20182',{'/vod/':'animedia_vod.html','index.m3u8':'animedia_master.m3u8'}),
            ('AniLiberty','https://aniliberty.top/anime/releases/release/bleach/episodes/1',{'/api/v1/anime/releases/':'anilibria_release.json'}),
            ('VK','https://vk.com/video_ext.php?oid=-33905270&id=456239024',{'video_ext.php':'vk_video_ext.html','.m3u8':'vk_master.m3u8'}),
            ('SovetRomantica','https://sovetromantica.com/embed/episode_1073_1-dubbed',{'/embed/':'sovetromantica_dubbed.html'}),
        ]
        for name,url,routes in samples:
            with self.subTest(player=name):
                http=FixtureHttp(routes);page=Resolver(http).resolve(url)
                self.assertTrue(page.streams)
                for stream in page.streams:
                    self.assertIn(stream['type'],{'mp4','hls'})
                    self.assertTrue(stream['url'].startswith('https://'))
                    self.assertIn('User-Agent',stream['headers'])
                    self.assertNotIn('Cookie',stream['headers']);self.assertNotIn('Authorization',stream['headers'])
                if name=='Kodik':
                    post=next(args for target,args in http.calls if '/ftor' in target)
                    self.assertEqual(post['data']['ref'],'https://animego.org/')
                    self.assertTrue(post['data']['ref_sign'])

    def test_animedia_published_cross_origin_episode_links_keep_actual_numbers(self):
        page=parse_page((FIXTURES/'animedia_title.html').read_text(),'https://amd.online/14-boruto.html')
        self.assertEqual([e['number'] for e in page.episodes],[1,2,3,4,5])
        self.assertEqual(page.episodes[0]['url'],'https://aser.pro/vod/1067')
        self.assertEqual(page.episodes[-1]['url'],'https://aser.pro/vod/1071')

    def test_headers_never_carry_owner_authentication_to_players(self):
        value=playback_headers({'Cookie':'private-google-fixture','Authorization':'Bearer private-fixture','Referer':'https://animego.org/'})
        self.assertNotIn('Cookie',value);self.assertNotIn('Authorization',value)
        self.assertEqual(value['Referer'],'https://animego.org/')

    def test_kodik_endpoint_handles_whitespace_quotes_and_rejects_ambiguous_or_foreign_paths(self):
        for script in ['url:atob("L2Z0b3I=")', '"url" : window.atob( "L2Z0b3I=" )', r'url:atob(\"L2Z0b3I=\")']:
            self.assertEqual(KodikPlayer._parse_post_path(script,'https://kodikplayer.com/assets/js/player.js'),'/ftor')
        for script in ['url:atob("aHR0cHM6Ly9vdGhlci5leGFtcGxlLmNvbS8=")','url:atob("L2Z0b3I="), url:atob("L290aGVy")']:
            with self.assertRaises(ExtractionError):KodikPlayer._parse_post_path(script,'https://kodikplayer.com/assets/js/player.js')

    def test_kodik_split_scripts_keep_ref_and_selected_video_in_the_real_post(self):
        from unittest.mock import patch
        html=(FIXTURES/'kodik_embed.html').read_text()
        html+='<script src="https://127.0.0.1/assets/js/private.js"></script><script src="/assets/js/app.request.js"></script>'
        class SplitHttp(FixtureHttp):
            def document(self,url,**kwargs):
                if '/seria/' in url:return html,url,{}
                if '/assets/js/' in url and not url.endswith('app.request.js'):return '/* renderer only */',url,{}
                return super().document(url,**kwargs)
        http=SplitHttp({'app.request.js':'kodik_player_script.js','/ftor':'kodik_ftor.json'})
        page=Resolver(http).resolve('https://kodikplayer.com/seria/1304528/932d5da818729ec5ccc9be7968ee3717/720p')
        self.assertTrue(page.streams)
        post=next(kwargs for url,kwargs in http.calls if '/ftor' in url)
        self.assertEqual(post['data']['id'],'1304528')
        self.assertEqual(post['data']['ref'],'https://animego.org/')
        self.assertFalse(any('127.0.0.1' in url for url,_ in http.calls))

    def test_all_published_embeds_and_translations_survive_enumeration(self):
        from player_catalog import inspect_catalog,group_voices
        class Http:
            def document(self,url,**kwargs):
                if 'kodikplayer.com' in url:return '<title>Player</title>',url,{}
                number=int(url.rsplit('/',1)[1])
                return '<select name="translation"><option value="https://kodikplayer.com/serial/'+str(number)+'/hash/720p">Studio '+str(number)+'</option></select>',url,{}
        root='https://catalog.example.com/show'
        text=''.join('<iframe src="https://player.example.com/embed/'+str(i)+'"></iframe>' for i in range(60))
        result=inspect_catalog(root,text,root,Http())
        self.assertEqual(len(result['dubs']),60)
        self.assertEqual(len(group_voices([result])),60)
        self.assertTrue(result['complete'])

    def test_large_graph_continues_instead_of_losing_players_after_a_batch(self):
        from player_catalog import inspect_catalog
        class Http:
            def __init__(self):self.calls=[]
            def document(self,url,**kwargs):
                self.calls.append(url)
                if 'kodikplayer.com' in url:return '<title>Player</title>',url,{}
                i=url.rsplit('/',1)[1]
                return '<select name="translation"><option value="https://kodikplayer.com/serial/'+i+'/hash/720p">Studio '+i+'</option></select>',url,{}
        root='https://catalog.example.com/show';text=''.join('<iframe src="https://player.example.com/embed/'+str(i)+'"></iframe>' for i in range(180))
        state={};http=Http();value=inspect_catalog(root,text,root,http,state=state)
        self.assertTrue(value['pending']);self.assertFalse(value['complete'])
        while value['pending']:value=inspect_catalog(root,text,root,http,state=state)
        self.assertEqual(len(value['dubs']),180);self.assertTrue(value['complete'])
        self.assertEqual(len(http.calls),len(set(http.calls)),'Previously inspected public pages are not fetched again')
