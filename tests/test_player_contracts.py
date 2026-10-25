"""All eight reference players through MediaVault's source-only resolver bridge."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from source_parser import PublicHttp,Resolver,public_url,playback_headers,parse_page

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
