import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import m3u8
from adaptive_playback import adaptive_master

class AdaptivePlaybackTests(unittest.TestCase):
 def test_individual_masters_flatten_without_losing_distinct_audio_subtitles_or_headers(self):
  calls=[]
  class Http:
   def document(self,url,**options):
    calls.append(options)
    height=2160 if '2160' in url else 720
    return '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="Russian",DEFAULT=YES,URI="audio.m3u8"\n#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="s",NAME="Russian",URI="sub.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=4000000,RESOLUTION='+str(height*16//9)+'x'+str(height)+',AUDIO="a",SUBTITLES="s"\nmedia.m3u8\n',url,{}
  streams=[{'quality':q,'type':'hls','url':'https://cdn.example.com/'+str(q)+'/master.m3u8','headers':{'Referer':'https://player.example.com/'}} for q in (720,2160)]
  text=adaptive_master(streams,Http());result=m3u8.loads(text)
  self.assertEqual(len(result.playlists),2)
  self.assertEqual(result.playlists[1].uri,'https://cdn.example.com/2160/media.m3u8')
  self.assertEqual(result.playlists[1].stream_info.audio,'q2160-a')
  self.assertEqual({m.group_id for m in result.media},{'q720-a','q2160-a','q720-s','q2160-s'})
  self.assertIn('NAME="2160p"',text)
  self.assertTrue(all(c['headers']==streams[0]['headers'] for c in calls))

 def test_media_only_sources_keep_publisher_labels_and_do_not_fabricate_resolution(self):
  class Http:
   def document(self,url,**_):return '#EXTM3U\n#EXTINF:5,\nfirst.ts\n#EXT-X-ENDLIST\n',url,{}
  streams=[{'quality':q,'type':'hls','url':'https://cdn.example.com/'+str(q)+'.m3u8'} for q in (360,480,720)]
  text=adaptive_master(streams,Http(),480);result=m3u8.loads(text)
  self.assertEqual(len(result.playlists),2);self.assertIn('NAME="480p"',text);self.assertNotIn('RESOLUTION=',text)
  self.assertIsNone(adaptive_master(streams,Http(),360))

 def test_encrypted_sources_are_rejected_and_single_master_is_not_rewritten(self):
  from source_parser import SourceError
  class Http:
   def document(self,url,**_):return '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key"\n#EXTINF:5,\nx.ts\n',url,{}
  streams=[{'quality':q,'type':'hls','url':'https://cdn.example.com/'+str(q)+'.m3u8'} for q in (360,720)]
  with self.assertRaises(SourceError):adaptive_master(streams,Http())
  self.assertIsNone(adaptive_master([{'type':'hls','quality':None,'url':'https://cdn.example.com/master.m3u8'}],Http()))
