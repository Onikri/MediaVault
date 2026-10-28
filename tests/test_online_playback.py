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
 def test_quality_cap_removes_only_higher_video_variants_preserving_alternate_audio(self):
  text='#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="Ru",URI="ru.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1280x720,AUDIO="a"\n720.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=4000000,RESOLUTION=1920x1080,AUDIO="a"\n1080.m3u8\n'
  links=[]
  out=online.rewrite_manifest(text,'https://source.example/master.m3u8',lambda v:links.append(v) or '/safe/'+str(len(links)),720)
  self.assertNotIn('1920x1080',out);self.assertIn('1280x720',out)
  self.assertEqual(set(links),{'https://source.example/ru.m3u8','https://source.example/720.m3u8'})
  with self.assertRaises(SourceError):online.rewrite_manifest(text,'https://source.example/master.m3u8',str,360)
 def test_first_master_is_reused_without_another_upstream_round_trip(self):
  import time
  token,s=online.create('A',{});key=s.resource('https://source.example/master.m3u8')
  s.manifests[key]=('#EXTM3U\n#EXTINF:2,\npart.ts\n','https://source.example/master.m3u8',time.monotonic()+30)
  app=FastAPI();online.install(app,lambda:'A');client=TestClient(app)
  with patch('online_sessions.PublicHttp._open') as fetch:
   response=client.get('/online/'+token+'/'+key)
  fetch.assert_not_called();self.assertEqual(response.status_code,200);self.assertIn('/online/'+token+'/',response.text);self.assertNotIn('source.example',response.text)
 def test_prepare_checks_one_master_without_preloading_video_or_all_qualities(self):
  from types import SimpleNamespace
  master='#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1280x720\n720.m3u8\n'
  app=FastAPI();online.install(app,lambda:'A');client=TestClient(app)
  with patch('online_sessions.PublicHttp') as http,patch('online_sessions.Resolver') as resolver:
   http.return_value.document.return_value=(master,'https://cdn.example/master.m3u8',{})
   resolver.return_value.resolve.return_value=SimpleNamespace(streams=[{'url':'https://cdn.example/master.m3u8','type':'hls'},{'url':'https://cdn.example/low.mp4','type':'mp4','quality':360}])
   response=client.post('/online/prepare',json={'url':'https://source.example/episode','kind':'video','quality':'720'})
  self.assertEqual(response.status_code,200);http.return_value.document.assert_called_once();http.return_value._open.assert_not_called()
  data=response.json();self.assertEqual(data['type'],'hls');self.assertGreaterEqual(data['preparationMs'],0)
  self.assertEqual(online.sessions[data['id']].max_height,720)
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
