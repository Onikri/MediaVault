"""Real player pages captured from the Oracle VM on 2026-11-08 (tokens scrubbed)."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from ua_players import (playerjs_entries,playerjs_choices,playerjs_stream,split_selectors,is_playerjs,is_collaps,
                        collaps_choices,collaps_stream,prefer_audio)
FIXTURES=Path(__file__).parent/'fixtures'/'players'
read=lambda name:(FIXTURES/name).read_text(encoding='utf-8')


class PlayerjsTests(unittest.TestCase):
    def test_serial_playlist_lists_voices_seasons_and_episodes(self):
        rows=playerjs_entries(read('hdvbua_serial.html'))
        self.assertTrue(rows)
        self.assertEqual(rows[0]['voice'],'одноголосий')
        self.assertEqual((rows[0]['season'],rows[0]['episode']),(1,1))
        self.assertTrue(all(r['file'].startswith('https://') and r['file'].endswith('.m3u8') for r in rows))

    def test_choices_use_embed_selectors_not_signed_media(self):
        embed='https://hdvbua.pro/embd/1876'
        choices=playerjs_choices(embed,read('hdvbua_serial.html'))
        self.assertTrue(choices)
        voice=choices[0]
        self.assertEqual((voice['player'],voice['language']),('HDVB UA','uk'))
        first=voice['episodes'][0]
        self.assertTrue(first['url'].startswith(embed+'?'))
        clean,selected=split_selectors(first['url'])
        self.assertEqual(clean,embed)
        self.assertEqual(playerjs_stream(clean,read('hdvbua_serial.html'),selected),playerjs_entries(read('hdvbua_serial.html'))[0]['file'])

    def test_film_and_ashdi_single_file(self):
        self.assertEqual(len(playerjs_entries(read('hdvbua_film.html'))),1)
        ashdi=playerjs_entries(read('ashdi_vod.html'))
        self.assertEqual(len(ashdi),1);self.assertIn('ashdi.vip',ashdi[0]['file'])
        self.assertIsNone(playerjs_stream('x',read('hdvbua_serial.html'),{'mv_voice':'missing','mv_season':'1','mv_episode':'1'}))

    def test_hosts(self):
        self.assertTrue(is_playerjs('https://ashdi.vip/vod/97433'))
        self.assertTrue(is_playerjs('https://hdvbua.pro/embed/6448/b0c42c552'))
        self.assertFalse(is_playerjs('https://hdvbua.pro/trailer/6448'))
        self.assertTrue(is_collaps('https://api.nextembed.ws/embed/movie/163'))


class CollapsTests(unittest.TestCase):
    def test_movie_dubs_become_audio_selectors(self):
        choices={c['name']:c for c in collaps_choices('https://api.nextembed.ws/embed/movie/163',read('collaps_movie.html'))}
        self.assertIn('Так Треба Продакшн',choices)
        self.assertEqual(choices['Так Треба Продакшн']['language'],'uk')
        self.assertEqual(choices['Eng.Original']['language'],'en')
        self.assertEqual(choices['Ю. Сербин']['language'],'ru')
        clean,selected=split_selectors(choices['Так Треба Продакшн']['episodes'][0]['url'])
        hls,audio=collaps_stream(read('collaps_movie.html'),selected)
        self.assertTrue(hls.startswith('https://'));self.assertEqual(audio,8)

    def test_serial_episodes_keep_lostfilm_and_seasons(self):
        choices={c['name']:c for c in collaps_choices('https://api.nextembed.ws/embed/movie/255',read('collaps_serial.html'))}
        self.assertIn('LostFilm',choices)
        lost=choices['LostFilm']['episodes']
        self.assertEqual([(e['season'],e['number']) for e in lost],[(1,1),(1,2),(3,1)])  # the source publishes no season 2
        self.assertEqual(choices['AMC (укр)']['language'],'uk')
        clean,selected=split_selectors(lost[1]['url'])
        hls,audio=collaps_stream(read('collaps_serial.html'),selected)
        self.assertIn('master.m3u8',hls);self.assertEqual(audio,2)

    def test_prefer_audio_marks_only_the_chosen_rendition_default(self):
        master='\n'.join(['#EXTM3U',
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="rus0",DEFAULT=YES,AUTOSELECT=YES,URI="a1.m3u8"',
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="ukr1",DEFAULT=NO,AUTOSELECT=NO,URI="a2.m3u8"',
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="f",NAME="rus0",DEFAULT=YES,AUTOSELECT=YES,URI="b1.m3u8"',
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="f",NAME="ukr1",DEFAULT=NO,AUTOSELECT=NO,URI="b2.m3u8"',
            '#EXT-X-STREAM-INF:BANDWIDTH=1,AUDIO="a"','v.m3u8'])
        out=prefer_audio(master,1)
        self.assertEqual(out.count('NAME="ukr1",DEFAULT=YES,AUTOSELECT=YES'),2)
        self.assertEqual(out.count('NAME="rus0",DEFAULT=NO,AUTOSELECT=NO'),2)
        self.assertEqual(prefer_audio(master,9),master)


if __name__=='__main__':unittest.main()


class CatalogCrawlTests(unittest.TestCase):
    def test_site_page_with_hdvb_iframe_yields_ukrainian_voices(self):
        from source_parser import PublicHttp
        from player_catalog import inspect_catalog
        page='<html><h1>Відьмак</h1><iframe src="https://hdvbua.pro/embd/1876"></iframe><iframe src="https://hdvbua.pro/vid/87267?tr=1"></iframe></html>'
        class Http(PublicHttp):
            def __init__(self):super().__init__();self.requested=[]
            def document(self,value,*,headers=None,**_):
                self.requested.append(value)
                if 'embd/1876' in value:return read('hdvbua_serial.html'),value,'text/html'
                raise AssertionError('unexpected request '+value)
        http=Http()
        result=inspect_catalog('https://eneyida.tv/8503-vidmak.html',page,'https://eneyida.tv/8503-vidmak.html',http,provider='eneyida',provider_name='Eneyida')
        names=[d['name'] for d in result['dubs']]
        self.assertIn('одноголосий',names)
        self.assertTrue(all(d['language']=='uk' for d in result['dubs']))
        self.assertNotIn('https://hdvbua.pro/vid/87267?tr=1',http.requested)


class UkrainianSiteSearchTests(unittest.TestCase):
    def test_cards_carry_original_title_alias_and_match_catalogue_titles(self):
        from site_adapters import BY_ID, parse_search
        from title_identity import match_title
        rows=parse_search(BY_ID['eneyida'],read('eneyida_search.html'),'https://eneyida.tv/')
        interstellar=next(r for r in rows if r['url']=='https://eneyida.tv/1430-interstellar.html')
        self.assertIn('Interstellar',interstellar['aliases'])
        self.assertTrue(match_title({'title':'Интерстеллар','aliases':['Interstellar'],'kind':'movie','year':2014},interstellar)[0])
        rows=parse_search(BY_ID['uaserials'],read('uaserials_search.html'),'https://uaserials.my/')
        nightmare=next(r for r in rows if '6448' in r['url'])
        self.assertEqual(nightmare['aliases'],['Відьмак: Кошмар вовка','The Witcher: Nightmare of the Wolf'])
        self.assertIsNone(nightmare['kind'])

    def test_sites_serve_films_and_serials(self):
        from site_adapters import BY_ID
        self.assertTrue(BY_ID['eneyida'].serves('movie') and BY_ID['uaserials'].serves('tv'))
        self.assertFalse(BY_ID['animego'].serves('movie'))
