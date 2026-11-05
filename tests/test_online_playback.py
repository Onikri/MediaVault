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
 def test_alloha_labelled_4k_master_is_selected_instead_of_480_boot_stream(self):
  from types import SimpleNamespace
  app=FastAPI();online.install(app,lambda:'fixture-owner');client=TestClient(app)
  streams=[{'url':'https://cdn.example.com/'+str(q)+'.m3u8','type':'hls','quality':q,'headers':{}} for q in [480,2160,1440,1080,720,360]]
  with patch('online_sessions.Resolver') as resolver,patch('online_sessions.PublicHttp') as http:
   resolver.return_value.resolve.return_value=SimpleNamespace(streams=streams)
   http.return_value.fork.return_value=http.return_value
   http.return_value.document.side_effect=lambda url,**_:('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=3840x1604\n4k.m3u8\n',url,{})
   r=client.post('/online/prepare',json={'url':'https://embed.thealloha.club/?translation=66','kind':'video'})
   self.assertEqual(r.status_code,200,r.text)
   self.assertEqual(http.return_value.document.call_count,6)
   http.return_value.document.assert_any_call('https://cdn.example.com/2160.m3u8',headers={})
   self.assertIn('https://cdn.example.com/2160.m3u8',online.sessions[r.json()['id']].resources.values())
   self.assertEqual(r.json()['qualities'],[2160,1440,1080,720,480,360])
 def test_online_preparation_keeps_the_selected_public_parent(self):
  from types import SimpleNamespace
  app=FastAPI();online.install(app,lambda:'fixture-owner');client=TestClient(app)
  selected='https://embed.thealloha.club/?episode=3&translation=10';parent='https://yummyanime.tv/fixture-title.html'
  with patch('online_sessions.Resolver') as resolver:
   resolver.return_value.resolve.return_value=SimpleNamespace(streams=[{'url':'https://cdn.example.com/episode-3.mp4','type':'mp4','quality':720,'headers':{}}])
   response=client.post('/online/prepare',json={'url':selected,'kind':'video','referer':parent})
   self.assertEqual(response.status_code,200,response.text);resolver.return_value.resolve.assert_called_once_with(selected,referer=parent)
   client.delete('/online/'+response.json()['id'])
  with self.assertRaises(SourceError):client.post('/online/prepare',json={'url':selected,'kind':'video','referer':'http://127.0.0.1/private'})
 def test_real_socket_disconnect_through_buffered_body_middleware_releases_sessions(self):
  import socket,threading,time,uvicorn
  app=FastAPI()
  @app.middleware('http')
  async def buffered(request,next):
   await request.body();return await next(request)
  online.install(app,lambda:'socket-owner')
  def inspect(*args):
   time.sleep(.15)
   return {'url':'https://source.example/chapter/1','language':'ru','pages':['https://images.example/1.png']}
  sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
  server=uvicorn.Server(uvicorn.Config(app,log_level='critical',lifespan='off'))
  thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True)
  with patch('manga_sources.inspect',side_effect=inspect):
   thread.start()
   try:
    for _ in range(300):
     if server.started:break
     time.sleep(.01)
    self.assertTrue(server.started)
    for _ in range(6):
     body=json.dumps({'url':'https://source.example/chapter/1','kind':'manga'}).encode()
     with socket.create_connection(('127.0.0.1',port),timeout=3) as connection:
      connection.sendall(b'POST /online/prepare HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body);time.sleep(.05)
     time.sleep(.25)
     self.assertEqual(online.sessions,{})
   finally:server.should_exit=True;thread.join(3)
 def test_aborted_hover_preparations_do_not_fill_owner_playback_slots(self):
  app=FastAPI();online.install(app,lambda:'A');client=TestClient(app)
  data={'url':'https://source.example/chapter/1','language':'ru','pages':['https://images.example/1.png']}
  async def disconnected(request,event):event.set()
  with patch('manga_sources.inspect',return_value=data),patch('online_sessions.watch_disconnect',side_effect=disconnected):
   for _ in range(8):
    self.assertEqual(client.post('/online/prepare',json={'url':data['url'],'kind':'manga'}).status_code,499)
    self.assertEqual(online.sessions,{})
  with patch('manga_sources.inspect',return_value=data):
   response=client.post('/online/prepare',json={'url':data['url'],'kind':'manga'})
   self.assertEqual(response.status_code,200);self.assertEqual(len(online.sessions),1)
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
   repeated=client.get('/online/'+token+'/'+key)
  self.assertEqual(repeated.text,response.text)
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
 def test_synthetic_master_does_not_point_to_itself_when_highest_variant_is_media(self):
  from types import SimpleNamespace
  import m3u8
  media='#EXTM3U\n#EXTINF:5,\nfirst.ts\n#EXT-X-ENDLIST\n'
  app=FastAPI();online.install(app,lambda:'A');client=TestClient(app)
  with patch('online_sessions.PublicHttp') as http,patch('online_sessions.Resolver') as resolver:
   http.return_value.fork.return_value=http.return_value
   http.return_value.document.side_effect=lambda url,**_: (media,url,{})
   response=SimpleNamespace(headers={'Content-Type':'application/vnd.apple.mpegurl'},iter_content=lambda size:iter([media.encode()]),close=lambda:None)
   http.return_value._open.side_effect=lambda url,**_: (response,url)
   resolver.return_value.resolve.return_value=SimpleNamespace(streams=[{'url':f'https://cdn.example/{height}.m3u8','type':'hls','quality':height} for height in (720,1080)])
   prepared=client.post('/online/prepare',json={'url':'https://source.example/episode','kind':'video','quality':'1080'}).json()
   master=m3u8.loads(client.get(prepared['url']).text)
   highest=master.playlists[-1].uri
   self.assertNotEqual(highest,prepared['url'])
   self.assertEqual(len(m3u8.loads(client.get(highest).text).segments),1)
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
 def test_original_official_mv_ranks_before_lyric_uploads_and_instrumental_is_not_an_exact_match(self):
  def row(identity,title,artist):return {'videoRenderer':{'videoId':identity,'title':{'simpleText':title},'ownerText':{'simpleText':artist},'lengthText':{'simpleText':'3:15'}}}
  raw='var ytInitialData = '+json.dumps({'contents':[row('CB2_qBzSft8','English Lyric Video Creepy Nuts - Otonoke','Creepy Nuts'),row('VD5rOrHN1Dg','Otonoke (Instrumental)','Creepy Nuts'),row('FCoQMD_qVNo','Otonoke by Creepy Nuts lyrics','Someone'),row('tRwHpyOq4P4','MV Creepy Nuts オトノケ(Otonoke)','Creepy Nuts')]})+';'
  result=parse_recordings(raw,'Otonoke','Creepy Nuts');self.assertEqual(result[0]['id'],'tRwHpyOq4P4');self.assertFalse(next(r for r in result if r['id']=='VD5rOrHN1Dg')['match'])
 def test_katana_reads_only_published_image_array_and_exact_search_cards(self):
  self.assertEqual(parse_pages("<script>var thzq=['https://images.example/1.jpg','https://images.example/2.jpg',];</script>",'https://mangakatana.com/manga/a/c1'),['https://images.example/1.jpg','https://images.example/2.jpg'])
  s=next(v for v in SITES if v.id=='mangakatana');rows=parse_search('<div id="book_list"><div class="item"><h3 class="title"><a href="/manga/demo.1">Demo</a></h3><img src="/cover.jpg"></div></div>',s.root,s);self.assertEqual(rows[0]['language'],'en');self.assertEqual(rows[0]['title'],'Demo')

class PreviewLeasePriority(unittest.TestCase):
 def setUp(self):online.sessions.clear();online.preparations.clear()
 def test_playback_evicts_only_owners_preview_slots_and_keeps_music_and_manga(self):
  music,_=online.create('A',{},kind='music');manga,_=online.create('A',{},kind='manga');foreign,_=online.create('B',{},kind='preview')
  previews=[online.create('A',{},kind='preview')[0] for _ in range(2)]
  video,_=online.create('A',{},kind='video')
  self.assertIn(video,online.sessions);self.assertIn(music,online.sessions);self.assertIn(manga,online.sessions);self.assertIn(foreign,online.sessions)
  self.assertTrue(all(p not in online.sessions for p in previews))
 def test_alloha_renews_expired_cached_urls_once_and_backs_off_on_fresh_refusal(self):
  from types import SimpleNamespace
  from source_parser import SourceAccessError
  url='https://alloha.yani.tv/?translation=66';master='#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=3840x1604\n4k.m3u8\n'
  for stale,resolves in ((True,2),(False,1)):
   with self.subTest(stale=stale):
    online.sessions.clear()
    app=FastAPI();online.install(app,lambda:'A');client=TestClient(app)
    replies=[SourceAccessError('refused'),(master,'https://cdn.example/m.m3u8',{})]
    def document(*_,**__):
     value=replies.pop(0)
     if isinstance(value,Exception):raise value
     return value
    with patch('online_sessions.PublicHttp') as http,patch('online_sessions.Resolver') as resolver,patch('browser_player.rejected',return_value=stale) as rejected:
     http.return_value.document.side_effect=document
     resolver.return_value.resolve.return_value=SimpleNamespace(streams=[{'url':'https://cdn.example/m.m3u8','type':'hls'}])
     body={'url':url,'kind':'video','referer':'https://ru.yummyani.me/catalog/item/x'}
     if stale:self.assertEqual(client.post('/online/prepare',json=body).status_code,200)
     else:
      with self.assertRaises(SourceAccessError):client.post('/online/prepare',json=body)
    self.assertEqual(resolver.return_value.resolve.call_count,resolves)
    rejected.assert_called_once_with(url,'https://ru.yummyani.me/catalog/item/x')
 def test_device_download_refuses_an_empty_remux_and_streams_a_named_mp4(self):
  import io
  from types import SimpleNamespace
  token,s=online.create('A',{});resource=s.resource('https://cdn.example/master.m3u8')
  app=FastAPI();online.install(app,lambda:'A');client=TestClient(app,raise_server_exceptions=False)
  for output,status in ((b'',502),(b'\x00\x00\x00\x18ftypmp42'+b'x'*64,200)):
   process=SimpleNamespace(stdout=io.BytesIO(output),poll=lambda:0,wait=lambda:0,kill=lambda:None)
   with patch('subprocess.Popen',return_value=process),patch('shutil.which',return_value='/usr/bin/ffmpeg'),patch('online_sessions.hls_extension_option',return_value=True):
    response=client.get('/online/'+token+'/'+resource+'/download',params={'name':'Серия 1'})
   self.assertEqual(response.status_code,status)
   if status==200:self.assertIn("filename*=UTF-8''%D0%A1%D0%B5%D1%80%D0%B8%D1%8F%201.mp4",response.headers['content-disposition']);self.assertTrue(response.content[4:8]==b'ftyp')
