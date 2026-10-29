import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import music_metadata as music
from fastapi import HTTPException
ID='11111111-1111-1111-1111-111111111111'
RELEASE='22222222-2222-2222-2222-222222222222'
class MusicMetadataTests(unittest.TestCase):
 def setUp(self):music._cache.clear();music._last_request=0
 def record(self,title='Otonoke',artist='Creepy Nuts'):
  return {'id':ID,'title':title,'length':187000,'artist-credit':[{'artist':{'name':artist}}],'releases':[{'id':RELEASE,'title':'Otonoke','date':'2024-10-04','status':'Official'}]}
 def test_exact_song_artist_and_external_artwork_metadata_only(self):
  row=music.select_recording({'recordings':[self.record('Otonoke','Wrong Artist'),self.record()]},'Otonoke','Creepy Nuts')
  self.assertTrue(row['found']);self.assertEqual(row['artists'],['Creepy Nuts'])
  self.assertEqual(row['cover'],'https://coverartarchive.org/release/'+RELEASE+'/front-250')
  self.assertFalse(row['artworkDownloaded']);self.assertNotIn('audio',row)
 def test_uncertain_match_is_not_presented_as_song_metadata(self):
  self.assertFalse(music.select_recording({'recordings':[self.record()]},'Another Song','Creepy Nuts')['found'])
  self.assertFalse(music.select_recording({'recordings':[self.record()]},'Otonoke','Someone Else')['found'])
 def test_cache_avoids_repeated_external_calls_and_rate_limit(self):
  with patch.object(music,'musicbrainz',return_value={'recordings':[self.record()]}) as get:
   first=music.metadata('Otonoke','Creepy Nuts');self.assertEqual(first,music.metadata('otonoke','creepy nuts'));get.assert_called_once()
   with self.assertRaises(HTTPException) as error:music.metadata('Other','Creepy Nuts')
   self.assertEqual(error.exception.status_code,429);get.assert_called_once()
 def test_upstream_failure_does_not_break_playback_or_repeatedly_query_catalogue(self):
  from source_parser import SourceError
  with patch.object(music,'musicbrainz',side_effect=SourceError('unavailable')) as get:
   data=music.metadata('Otonoke','Creepy Nuts');self.assertFalse(data['found']);self.assertTrue(data['unavailable'])
   self.assertEqual(data,music.metadata('Otonoke','Creepy Nuts'));get.assert_called_once()
 def test_queries_are_escaped_and_invalid_ids_never_become_artwork(self):
  self.assertIn('\\"',music.quoted('name" OR *:*'))
  row=self.record();row['releases'][0]['id']='https://private.example'
  self.assertEqual(music.select_recording({'recordings':[row]},'Otonoke','Creepy Nuts')['cover'],'')
  for title,artist in [('', ''),('x'*251,''),('Song','x'*301)]:
   with self.assertRaises(HTTPException):music.metadata(title,artist)
