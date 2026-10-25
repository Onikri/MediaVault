import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
import online_sessions as online
from source_parser import SourceError
from music_playback import parse_recordings
from manga_sources import parse_pages,parse_search,SITES
class OnlinePlayback(unittest.TestCase):
 def setUp(self):online.sessions.clear()
 def test_manifest_rewrites_nested_audio_subtitle_map_and_segments_without_forwarding_secrets(self):
  text='#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,URI="sub/ru.m3u8"\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:8,\npart.ts\n'
  targets=[]
  out=online.rewrite_manifest(text,'https://source.example/video/master.m3u8',lambda u:targets.append(u) or '/safe/'+str(len(targets)))
  self.assertEqual(targets,['https://source.example/video/sub/ru.m3u8','https://source.example/video/init.mp4','https://source.example/video/part.ts']);self.assertNotIn('source.example',out)
  for line in ['#EXT-X-KEY:METHOD=SAMPLE-AES,URI="secret"','#EXT-X-SESSION-KEY:METHOD=AES-128,URI="secret"']:
   with self.assertRaises(SourceError):online.rewrite_manifest('#EXTM3U\n'+line,'https://source.example/a',str)
 def test_expiring_capabilities_are_owner_limited_and_cannot_be_closed_by_another_user(self):
  token,s=online.create('A',{});resource=s.resource('https://source.example/test.mp4');self.assertEqual(resource,s.resource('https://source.example/test.mp4'))
  app=FastAPI();subject=['B'];online.install(app,lambda:subject[0]);client=TestClient(app)
  client.delete('/online/'+token);self.assertIn(token,online.sessions);subject[0]='A';client.delete('/online/'+token);self.assertNotIn(token,online.sessions)
  self.assertEqual(client.get('/online/'+token+'/'+resource).status_code,410)
 def test_unauthenticated_users_cannot_prepare_streams(self):
  def denied():raise HTTPException(401,'Login')
  app=FastAPI();online.install(app,denied);client=TestClient(app)
  self.assertEqual(client.post('/online/prepare',json={'url':'https://source.example/a.mp4','kind':'video'}).status_code,401)
 def test_failed_source_releases_connections_and_slots(self):
  token,s=online.create('A',{});key=s.resource('https://source.example/a.mp4');app=FastAPI();online.install(app,lambda:'A');client=TestClient(app,raise_server_exceptions=False)
  with patch('online_sessions.PublicHttp._open',side_effect=SourceError('Unavailable')):
   for _ in range(12):self.assertEqual(client.get('/online/'+token+'/'+key).status_code,500)
  # No leaked semaphore slots after twelve failures.
  self.assertTrue(s.slots.acquire(False));s.slots.release()
 def test_official_music_search_ranks_exact_song_and_artist_without_extracting_streams(self):
  def row(identity,title,artist):return {'videoRenderer':{'videoId':identity,'title':{'runs':[{'text':title}]},'ownerText':{'runs':[{'text':artist}]},'lengthText':{'simpleText':'3:15'}}}
  raw='var ytInitialData = '+json.dumps({'contents':[row('abcdefghijk','Unrelated song','Someone'),row('01234567890','Otonoke / オトノケ — Official Video','Creepy Nuts')]})+';'
  r=parse_recordings(raw,'Otonoke','Creepy Nuts');self.assertEqual(r[0]['id'],'01234567890');self.assertTrue(r[0]['match']);self.assertNotIn('url',r[0])
 def test_katana_reads_only_published_image_array_and_exact_search_cards(self):
  self.assertEqual(parse_pages("<script>var thzq=['https://images.example/1.jpg','https://images.example/2.jpg',];</script>",'https://mangakatana.com/manga/a/c1'),['https://images.example/1.jpg','https://images.example/2.jpg'])
  s=next(v for v in SITES if v.id=='mangakatana');rows=parse_search('<div id="book_list"><div class="item"><h3 class="title"><a href="/manga/demo.1">Demo</a></h3><img src="/cover.jpg"></div></div>',s.root,s);self.assertEqual(rows[0]['language'],'en');self.assertEqual(rows[0]['title'],'Demo')
