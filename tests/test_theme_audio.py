import sys,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from fastapi import HTTPException
import anime_music


def reply(payload,status=200):
    response=MagicMock(status_code=status);response.json.return_value=payload;response.raise_for_status.return_value=None;return response


class ThemeAudio(unittest.TestCase):
    def setUp(self):anime_music._audio.clear()

    def test_graphql_audio_is_primary_and_cached(self):
        payload={'data':{'animethemePagination':{'data':[{'animethemeentries':[{'nsfw':True,'videos':{'nodes':[{'audio':{'link':'https://a.animethemes.moe/Nsfw.ogg'}}]}},
                 {'nsfw':False,'videos':{'nodes':[{'audio':{'link':'https://evil.example/x.ogg'}},{'audio':{'link':'https://a.animethemes.moe/Show-OP2.ogg'}}]}}]}]}}}
        with patch('requests.post',return_value=reply(payload)) as post,patch('requests.get') as get:
            self.assertEqual(anime_music.theme_audio(9),'https://a.animethemes.moe/Show-OP2.ogg')
            self.assertEqual(anime_music.theme_audio(9),'https://a.animethemes.moe/Show-OP2.ogg')
        self.assertEqual(post.call_count,1);get.assert_not_called()

    def test_graphql_unknown_theme_is_404_without_rest(self):
        with patch('requests.post',return_value=reply({'data':{'animethemePagination':{'data':[]}}})),patch('requests.get') as get:
            with self.assertRaises(HTTPException) as caught:anime_music.theme_audio(10)
        self.assertEqual(caught.exception.status_code,404);get.assert_not_called()

    def test_returns_first_safe_animethemes_audio_and_caches_it(self):
        payload={'animetheme':{'animethemeentries':[{'nsfw':True,'videos':[{'audio':{'link':'https://a.animethemes.moe/Nsfw.ogg'}}]},
                                                    {'nsfw':False,'videos':[{'audio':{'link':'https://evil.example/x.ogg'}},{'audio':{'link':'https://a.animethemes.moe/Show-OP1.ogg'}}]}]}}
        with patch('requests.post',side_effect=__import__('requests').ConnectionError()),patch('requests.get',return_value=reply(payload)) as get:
            self.assertEqual(anime_music.theme_audio(7),'https://a.animethemes.moe/Show-OP1.ogg')
            self.assertEqual(anime_music.theme_audio(7),'https://a.animethemes.moe/Show-OP1.ogg')
        self.assertEqual(get.call_count,1)

    def test_missing_audio_is_a_clear_404(self):
        with patch('requests.post',side_effect=__import__('requests').ConnectionError()),patch('requests.get',return_value=reply({'animetheme':{'animethemeentries':[{'videos':[]}]}})):
            with self.assertRaises(HTTPException) as caught:anime_music.theme_audio(8)
        self.assertEqual(caught.exception.status_code,404)

class ThemeSearch(unittest.TestCase):
    def setUp(self):anime_music._theme_search.clear()

    def payload(self):
        row=lambda i,title,artist,link,nsfw=False:{'id':i,'type':'OP','song':{'title':{'romaji':title,'native':None},'performances':[{'artist':{'name':{'main':artist}}}]},'animethemeentries':[{'nsfw':nsfw,'videos':{'nodes':[{'audio':{'link':link}}]}}]}
        return {'data':{'search':{'animethemes':[row(1,'LOVE THE WORLD','Other','https://a.animethemes.moe/Other.ogg'),row(2,'THE WORLD','Nightmare','https://a.animethemes.moe/DeathNote-OP1.ogg'),row(3,'THE WORLD','Cover Band','https://a.animethemes.moe/Cover.ogg')]}}}

    def test_exact_song_and_artist_from_a_tv_size_title(self):
        with patch('requests.post',return_value=reply(self.payload())) as post:
            found=anime_music.search_theme('The WORLD (TV Size)','Nightmare')
            self.assertEqual(found['audio'],'https://a.animethemes.moe/DeathNote-OP1.ogg')
            self.assertEqual(found['id'],'animethemes:2')
            anime_music.search_theme('The WORLD (TV Size)','Nightmare')
        self.assertEqual(post.call_count,1)

    def test_wrong_artist_or_partial_title_is_not_a_match(self):
        with patch('requests.post',return_value=reply(self.payload())):
            self.assertIsNone(anime_music.search_theme('THE WORLD','Unknown Artist'))
            self.assertIsNone(anime_music.search_theme('WORLD',''))

    def test_words_containing_ed_or_op_survive_normalisation(self):
        self.assertEqual(anime_music.song_key('Red (TV Size)'),'red')
        self.assertEqual(anime_music.song_key('Hope Opening'),'hope')


if __name__=='__main__':unittest.main()
