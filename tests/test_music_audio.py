"""Audio resolver/proxy contracts; yt-dlp and upstream media are fixtures here."""
import io,json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
import music_audio as music
import online_sessions as online
from source_parser import SourceError
IDENTITY='dQw4w9WgXcQ';WATCH='https://www.youtube.com/watch?v='+IDENTITY
CDN='https://rr1---sn-example.googlevideo.com/videoplayback?expire='+str(int(time.time())+3600)

class MusicAudio(unittest.TestCase):
 def setUp(self):
  music.cache.clear();online.sessions.clear();cookies=patch('youtube_auth.cookie_text',return_value='');cookies.start();self.addCleanup(cookies.stop)
 def test_only_exact_youtube_recordings_not_arbitrary_urls_or_options_are_accepted(self):
  for url in [WATCH,WATCH+'&list=ignored','https://youtu.be/'+IDENTITY+'?t=10','https://music.youtube.com/watch?v='+IDENTITY,'https://www.youtube.com/shorts/'+IDENTITY]:self.assertEqual(music.youtube_id(url),IDENTITY)
  for url in ['--exec=command','http://youtube.com/watch?v='+IDENTITY,'https://youtube.com.evil/watch?v='+IDENTITY,'https://user:pass@youtube.com/watch?v='+IDENTITY,'https://www.youtube.com/playlist?list=123',WATCH+'&v=abcdefghijk','https://youtube.com:444/watch?v='+IDENTITY]:
   with self.assertRaises(SourceError):music.youtube_id(url)
 def test_audio_destinations_allow_only_public_googlevideo_playback_including_redirects(self):
  with patch.object(music,'public_url',side_effect=lambda value:value):
   self.assertEqual(music.audio_url(CDN),CDN)
   for url in ['https://evil.example/videoplayback','https://googlevideo.com.evil/videoplayback','https://rr.googlevideo.com/private']:
    with self.assertRaises(SourceError):music.audio_url(url)
 def data(self):return {'url':CDN,'headers':{},'mime':'audio/mp4','duration':213,'title':'A real title from fixture'}
 def test_authenticated_prepare_returns_only_expiring_owner_capability(self):
  app=FastAPI();online.install(app,lambda:'A');music.install(app,lambda:'A');client=TestClient(app)
  with patch.object(music,'extract',return_value=(self.data(),300)) as extract:
   response=client.post('/music/play',json={'url':WATCH})
  self.assertEqual(response.status_code,200);data=response.json();self.assertNotIn('googlevideo',json.dumps(data));self.assertEqual(data['mime'],'audio/mp4');self.assertTrue(data['streamUrl'].startswith('/online/'+data['id']+'/'));self.assertLess(online.sessions[data['id']].expires-time.monotonic(),301)
  client.delete('/online/'+data['id']);self.assertNotIn(data['id'],online.sessions);extract.assert_called_once_with(IDENTITY,False)
 def test_anonymous_cannot_launch_extractor(self):
  def denied():raise HTTPException(401,'Sign in')
  app=FastAPI();music.install(app,denied)
  with patch.object(music,'extract') as extract:self.assertEqual(TestClient(app).post('/music/play',json={'url':WATCH}).status_code,401);extract.assert_not_called()
 def test_cancelled_preparation_does_not_allocate_a_playback_slot(self):
  async def disconnected(request,event):event.set()
  app=FastAPI();music.install(app,lambda:'A')
  with patch.object(music,'extract',return_value=(self.data(),300)),patch.object(online,'watch_disconnect',side_effect=disconnected):
   # install captured the watcher: install a fresh app under this patch.
   app=FastAPI();music.install(app,lambda:'A');response=TestClient(app).post('/music/play',json={'url':WATCH})
  self.assertEqual(response.status_code,499);self.assertEqual(online.sessions,{})
 def test_audio_proxy_preserves_ranges_real_mime_and_releases_connections(self):
  token,s=online.create('A',{},'music');s.audio_mime='audio/mp4';resource=s.resource(CDN)
  app=FastAPI();online.install(app,lambda:'A');client=TestClient(app)
  response=MagicMock();response.status_code=206;response.headers={'Content-Type':'video/mp4','Content-Range':'bytes 10-13/100','Accept-Ranges':'bytes','Content-Length':'4'};response.iter_content.return_value=[b'abcd']
  with patch.object(online.PublicHttp,'_open',return_value=(response,CDN)) as upstream:
   result=client.get('/online/'+token+'/'+resource,headers={'Range':'bytes=10-13'})
  self.assertEqual(result.status_code,206);self.assertEqual(result.content,b'abcd');self.assertEqual(result.headers['content-type'],'audio/mp4');self.assertEqual(result.headers['content-range'],'bytes 10-13/100');self.assertEqual(upstream.call_args.kwargs['byte_range'],'bytes=10-13');response.close.assert_called_once();self.assertTrue(s.slots.acquire(False));s.slots.release()
 def test_audio_html_error_page_is_never_served_as_music(self):
  token,s=online.create('A',{},'music');s.audio_mime='audio/webm';resource=s.resource(CDN);app=FastAPI();online.install(app,lambda:'A')
  response=MagicMock();response.headers={'Content-Type':'text/html'}
  with patch.object(online.PublicHttp,'_open',return_value=(response,CDN)):
   self.assertEqual(TestClient(app,raise_server_exceptions=False).get('/online/'+token+'/'+resource).status_code,500)
  response.close.assert_called_once()
 def extract_fixture(self,data):
  def start(command,**kwargs):
   kwargs['stdout'].write(json.dumps(data).encode());kwargs['stdout'].flush()
   process=MagicMock();process.poll.return_value=0;process.returncode=0;return process
  return start
 def test_extraction_uses_no_shell_cookie_or_download_and_caches_bounded_metadata(self):
  data={'id':IDENTITY,'title':'Fixture','duration':213,'url':CDN,'ext':'m4a','vcodec':'none','acodec':'mp4a','protocol':'https','http_headers':{'Authorization':'secret','Cookie':'secret','User-Agent':'public'}}
  with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DATA_DIR':directory}),patch.object(music,'audio_url',side_effect=lambda url:url),patch.object(music,'verify_audio'),patch.object(music.subprocess,'Popen',side_effect=self.extract_fixture(data)) as spawn:
   value,ttl=music.extract(IDENTITY);music.extract(IDENTITY)
   self.assertEqual(value['mime'],'audio/mp4');self.assertNotIn('Cookie',value['headers']);self.assertNotIn('Authorization',value['headers']);self.assertEqual(spawn.call_count,1);self.assertGreater(ttl,600);self.assertLessEqual(ttl,3600)
   # A ten-minute metadata refresh must not expire playback of a long recording.
   cached=music.cache[IDENTITY];self.assertLessEqual(cached[0]-time.monotonic(),600);self.assertGreater(cached[2]-time.monotonic(),600)
   with patch.object(music.time,'monotonic',return_value=cached[0]-1):
    _,remaining=music.extract(IDENTITY);self.assertGreater(remaining,600)
   with patch.object(music.time,'monotonic',return_value=cached[0]+1):music.extract(IDENTITY)
   self.assertEqual(spawn.call_count,2,'Stale metadata is extracted again without cutting off existing playback')
   command=spawn.call_args.args[0];self.assertIn('--ignore-config',command);self.assertIn('--no-cache-dir',command);self.assertIn('--no-plugin-dirs',command);self.assertNotIn('shell',spawn.call_args.kwargs);self.assertEqual(command[-1],WATCH)
   self.assertEqual(list((Path(directory)/'temporary').iterdir()),[])
 def test_combined_video_live_and_overlong_tracks_are_rejected(self):
  base={'id':IDENTITY,'title':'Fixture','duration':213,'url':CDN,'ext':'m4a','vcodec':'none','protocol':'https'}
  for changes in [{'vcodec':'avc1'},{'is_live':True},{'duration':7201},{'id':'other'},{'protocol':'m3u8_native'}]:
   with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DATA_DIR':directory}),patch.object(music.subprocess,'Popen',side_effect=self.extract_fixture({**base,**changes})),self.assertRaises(HTTPException):music.extract(IDENTITY,True)
 def test_extractor_errors_do_not_expose_raw_signed_urls_or_untrusted_diagnostics(self):
  text=music.failure('ERROR Sign in to confirm not a bot Cookie=private-secret '+CDN)
  self.assertNotIn('private-secret',text);self.assertNotIn('googlevideo',text);self.assertIn('Oracle',text)
 def test_future_availability_is_observed_before_testing_or_caching_audio(self):
  data={'id':IDENTITY,'title':'Fixture','duration':213,'url':CDN,'ext':'m4a','vcodec':'none','protocol':'https','available_at':1005}
  events=[]
  with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DATA_DIR':directory}),patch.object(music.time,'time',return_value=1000),patch.object(music.time,'sleep',side_effect=lambda delay:events.append(('wait',delay))),patch.object(music,'audio_url',side_effect=lambda url:url),patch.object(music,'verify_audio',side_effect=lambda *args:events.append(('probe',None))),patch.object(music.subprocess,'Popen',side_effect=self.extract_fixture(data)):
   music.extract(IDENTITY);music.extract(IDENTITY)
  self.assertEqual([e[0] for e in events],['wait','probe']);self.assertGreaterEqual(events[0][1],5)
 def test_invalid_or_excessive_availability_never_sleeps_without_bound(self):
  for timestamp in [True,'tomorrow',float('inf'),float('nan'),time.time()+120]:
   with patch.object(music.time,'sleep') as sleep,self.assertRaises(HTTPException):music.wait_available(timestamp,time.monotonic()+65)
   sleep.assert_not_called()
 def test_preflight_checks_actual_audio_bytes_range_and_closes_upstream(self):
  for ext,raw in [('m4a',b'\0\0\0\x20ftyp'+b'0'*24),('webm',b'\x1a\x45\xdf\xa3'+b'0'*28)]:
   response=MagicMock();response.status_code=206;response.headers={'Content-Type':'application/octet-stream','Content-Range':'bytes 0-31/1000'};response.iter_content.return_value=[raw[:8],raw[8:]]
   with patch.object(music,'PublicHttp') as client:
    client.return_value._open.return_value=(response,CDN);music.verify_audio(CDN,{},ext,time.monotonic()+10)
   response.close.assert_called_once();client.return_value.close.assert_called_once();self.assertEqual(client.return_value._open.call_args.kwargs['byte_range'],'bytes=0-31')
 def test_denied_or_html_audio_is_not_cached_or_given_a_playback_capability(self):
  for failure in ['denied','html']:
   response=MagicMock();response.status_code=206;response.headers={'Content-Type':'text/html','Content-Range':'bytes 0-31/1000'}
   with patch.object(music,'PublicHttp') as client,self.assertRaises(HTTPException) as caught:
    if failure=='denied':client.return_value._open.side_effect=SourceError('HTTP403 '+CDN)
    else:client.return_value._open.return_value=(response,CDN)
    music.verify_audio(CDN,{},'m4a',time.monotonic()+10)
   self.assertEqual(caught.exception.status_code,502);self.assertNotIn('googlevideo',caught.exception.detail);client.return_value.close.assert_called_once()
   if failure=='html':response.close.assert_called_once()
 def test_remote_file_requires_public_url_audio_signature_range_and_bounded_size(self):
  response=MagicMock();response.status_code=206;response.headers={'Content-Type':'audio/mpeg','Content-Range':'bytes 0-31/1000'};response.iter_content.return_value=[b'ID3'+b'0'*29]
  with patch.object(music,'public_url',return_value='https://music.example/song.mp3') as validate,patch.object(music,'PublicHttp') as client:
   client.return_value._open.return_value=(response,'https://cdn.example/song.mp3');data=music.remote_audio('https://music.example/song.mp3')
   self.assertEqual(data['url'],'https://cdn.example/song.mp3');self.assertEqual(data['mime'],'audio/mpeg');validate.assert_called_once();response.close.assert_called_once();client.return_value.close.assert_called_once()
  for changes in [{'Content-Type':'text/html'},{'Content-Range':'bytes 0-31/999999999'},{'Content-Range':'invalid'}]:
   response.headers={'Content-Type':'audio/mpeg','Content-Range':'bytes 0-31/1000',**changes}
   with patch.object(music,'public_url',return_value='https://music.example/song.mp3'),patch.object(music,'PublicHttp') as client,self.assertRaises(SourceError):
    client.return_value._open.return_value=(response,'https://cdn.example/song.mp3');music.remote_audio('https://music.example/song.mp3')
  self.assertTrue(music.slots.acquire(False));music.slots.release()
 def test_remote_file_api_auth_capability_and_cancellation(self):
  app=FastAPI();online.install(app,lambda:'A');music.install(app,lambda:'A');client=TestClient(app)
  with patch.object(music,'remote_audio',return_value=self.data()):
   data=client.post('/music/remote',json={'url':'https://music.example/song.mp3'}).json()
  self.assertEqual(online.sessions[data['id']].kind,'music-file');self.assertNotIn('music.example',json.dumps(data));client.delete('/online/'+data['id'])
  def denied():raise HTTPException(401,'Sign in')
  app=FastAPI();music.install(app,denied)
  with patch.object(music,'remote_audio') as resolver:self.assertEqual(TestClient(app).post('/music/remote',json={'url':'https://music.example/song.mp3'}).status_code,401);resolver.assert_not_called()
  async def disconnected(request,event):event.set()
  with patch.object(online,'watch_disconnect',side_effect=disconnected),patch.object(music,'remote_audio',return_value=self.data()):
   app=FastAPI();music.install(app,lambda:'A');self.assertEqual(TestClient(app).post('/music/remote',json={'url':'https://music.example/song.mp3'}).status_code,499)
  self.assertEqual(online.sessions,{})

if __name__=='__main__':unittest.main()
