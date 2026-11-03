"""Catalogue/API fixtures; live video decoding is recorded in the review notes."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
import title_background as background
from player_catalog import group_voices,choice
from source_parser import Resolver,Page
import online_sessions as online
from music_lyrics import LyricsRelay
from lyric_identity import identity


class TitleReview(unittest.TestCase):
    def test_background_only_uses_exact_title_public_nonspoiler_video(self):
        def anime(key,url,**entry):
            return {'resources':{'nodes':[{'site':'MAL','externalId':key}]},'animethemes':[{'type':'OP','animethemeentries':[{'nsfw':False,'spoiler':False,**entry,'videos':{'nodes':[{'link':url,'resolution':720,'size':2000}]}}]}]}
        rows=[anime(16498,'https://v.animethemes.moe/correct.webm'),anime(37450,'https://v.animethemes.moe/wrong-title.webm'),anime(16498,'https://v.animethemes.moe/spoiler.webm',spoiler=True),anime(16498,'http://127.0.0.1/private')]
        with patch('title_background.get_json',return_value={'data':{'findAnimeByExternalSite':rows}}):
            self.assertEqual(background.candidates('16498'),['https://v.animethemes.moe/correct.webm'])

    def test_persistent_background_reopens_after_restart_and_supports_ranges(self):
        app=FastAPI()
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'TITLE_VIDEO_CACHE_DIR':folder}):
            Path(folder,'16498.mp4').write_bytes(b'0123456789abcdef')
            background.install(app,folder)
            with TestClient(app) as client:
                self.assertEqual(client.get('/backgrounds/16498').json()['status'],'ready')
                response=client.get('/backgrounds/16498/video',headers={'Range':'bytes=4-9'})
                self.assertEqual(response.status_code,206);self.assertEqual(response.content,b'456789')
                self.assertEqual(client.get('/backgrounds/not-an-id').status_code,422)

    def test_kodik_specific_opening_and_ending_survive_preparation(self):
        from player_compat import KodikPlayer
        segments=[SimpleNamespace(start=18,end=100,kind='opening'),SimpleNamespace(start=1200,end=1280,kind='ending')]
        result=SimpleNamespace(title='Fixture',streams=[],skip_segments=segments)
        with patch.object(KodikPlayer,'matches',return_value=True),patch.object(KodikPlayer,'extract',return_value=result):
            page=Resolver(SimpleNamespace()).player('https://kodikplayer.com/serial/1/hash/720p')
        self.assertEqual(page.skip_segments,[{'type':'op','start':18,'end':100,'source':'Kodik'},{'type':'ed','start':1200,'end':1280,'source':'Kodik'}])
        page.streams=[{'url':'https://cdn.example/1.mp4','type':'mp4','quality':720,'headers':{}}]
        app=FastAPI();online.install(app,lambda:'review-fixture')
        with patch('online_sessions.Resolver') as resolver,TestClient(app) as client:
            resolver.return_value.resolve.return_value=page
            response=client.post('/online/prepare',json={'url':'https://kodikplayer.com/serial/1/hash/720p','kind':'video'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['sourceIntervals'],page.skip_segments)
            client.delete('/online/'+response.json()['id'])

    def test_unnamed_voice_is_not_a_selectable_studio(self):
        rows=[choice('', 'https://kodikplayer.com/serial/1/h/720p'),choice('Неизвестный автор 33 серия','https://kodikplayer.com/serial/2/h/720p'),choice('AniLibria','https://kodikplayer.com/serial/3/h/720p')]
        groups=group_voices([{'url':'https://site.example/show','dubs':rows}])
        self.assertEqual(len(groups),1);self.assertEqual(groups[0]['name'],'AniLibria')


class LyricsReview(unittest.IsolatedAsyncioTestCase):
    async def test_structured_world_search_before_failed_generic_query(self):
        with tempfile.TemporaryDirectory() as folder:
            relay=LyricsRelay(folder)
            query={**identity(['the WORLD'],['NIGHTMARE']),'duration':234}
            relay.get_json=AsyncMock(side_effect=[{},[{'id':42,'trackName':'the WORLD','artistName':'NIGHTMARE','duration':234,'syncedLyrics':'[00:01.00]Fixture'}],[]])
            result=await relay.lrclib(query)
            self.assertEqual(result['source'],'LRCLIB');self.assertTrue(result['lrc'])
            self.assertTrue(any('track_name' in c.args[1] and 'duration' not in c.args[1] for c in relay.get_json.await_args_list))
