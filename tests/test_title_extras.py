from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from title_extras import staff_from_roles,trailers_from_details
from trailer_service import install,jobs
from fastapi import FastAPI
from fastapi.testclient import TestClient

class TitleExtrasTests(unittest.TestCase):
 def test_missing_poster_and_genres_are_repaired_by_exact_season_id_without_mutating_cache(self):
  from poster_assets import repair
  original={'id':60543,'image':{'original':'/assets/globals/missing_original.jpg'},'genres':[]}
  genre={'id':'1','russian':'Экшен','name':'Action','kind':'genre'}
  with patch('poster_assets.posters',return_value={'60543':{'cover':'https://shikimori.io/uploads/60543.jpeg','genres':[genre]}}) as lookup:
   fixed=repair(original,'anime');lookup.assert_called_once_with([60543],'anime')
  self.assertEqual(fixed['genres'],[genre]);self.assertIn('60543.jpeg',fixed['image']['original']);self.assertEqual(original['genres'],[])
  self.assertIn('missing_original',original['image']['original'])
 def test_credits_and_trailers_preserve_only_supported_public_metadata(self):
  roles=[{'roles_russian':['Режиссёр'],'person':{'id':41,'russian':'Фуга Ямасиро','image':{'original':'/system/people/original/41.jpg'}}}]
  credits=staff_from_roles(roles);self.assertEqual(credits[0]['name'],'Фуга Ямасиро');self.assertTrue(credits[0]['image'].startswith('https://shikimori.io/'))
  details={'videos':[{'id':2,'kind':'pv','name':'Тизер','url':'http://youtu.be/abcdefghijk','image_url':'http://img.youtube.com/vi/abcdefghijk/hqdefault.jpg'},{'id':3,'kind':'pv','url':'http://127.0.0.1/admin'},{'id':4,'kind':'ed','url':'https://youtu.be/abcdefghijk'}]}
  trailers=trailers_from_details(details);self.assertEqual(len(trailers),1);self.assertEqual(trailers[0]['url'],'https://youtu.be/abcdefghijk')
 def test_native_trailer_range_response_and_expired_id(self):
  app=FastAPI()
  with tempfile.TemporaryDirectory() as folder:
   install(app,folder);clip=Path(folder)/'clip.mp4';clip.write_bytes(b'0123456789abcdef')
   jobs['test-only']={'id':'test-only','status':'ready','path':str(clip)}
   try:
    with TestClient(app) as client:
     response=client.get('/trailers/stream/test-only',headers={'Range':'bytes=4-9'})
     self.assertEqual(response.status_code,206);self.assertEqual(response.content,b'456789');self.assertEqual(response.headers['content-range'],'bytes 4-9/16')
     self.assertEqual(client.get('/trailers/stream/no-such-trailer').status_code,404)
     self.assertEqual(client.post('/trailers/prepare',json={'anime_id':'57334','video_id':'http://127.0.0.1'}).status_code,422)
   finally:jobs.pop('test-only',None)
 def test_catalogue_membership_is_verified_before_starting_a_trailer_download(self):
  from trailer_service import prepare
  from fastapi import HTTPException
  with tempfile.TemporaryDirectory() as folder,patch('trailer_service.metadata',return_value={'videos':[]}):
   with self.assertRaises(HTTPException) as caught:prepare('57334','999999',Path(folder))
   self.assertEqual(caught.exception.status_code,404)
