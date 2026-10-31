import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import anime_browse as module
from source_parser import SourceError
class AnimeBrowseTests(unittest.TestCase):
 def setUp(self):module._cache.clear()
 def test_season_studio_genre_and_status_are_real_upstream_filters(self):
  with patch.object(module,'get_json',return_value=[]) as get:
   module.browse('season','fall_2026');self.assertEqual(get.call_args.kwargs['params']['season'],'fall_2026')
   module.browse('genre',identity='8');self.assertEqual(get.call_args.kwargs['params']['genre'],'8')
   module.browse('status','released');self.assertEqual(get.call_args.kwargs['params']['status'],'released')
   module.browse('studio',identity='3');self.assertEqual(get.call_args.kwargs['params']['studio'],'3')
 def test_character_attributes_only_include_explicit_published_values_and_filmography(self):
  def get(url,**_):
   if 'shikimori' in url:return {'id':17,'russian':'Герой','animes':[]}
   return {'data':{'name':'Hero','about':'Age: 18\nHeight: 170 cm\nGender: Female\nBiography','anime':[{'anime':{'mal_id':77,'title':'Title'}}]}}
  with patch.object(module,'get_json',side_effect=get):
   data=module.browse('character',identity='17');self.assertEqual(data['items'][0]['id'],77)
   self.assertEqual(dict(data['entity']['facts']),{'Возраст':'18','Рост':'170 cm','Пол':'Женский'})
 def test_unavailable_jikan_preserves_published_shikimori_person_works(self):
  def get(url,**_):
   if 'jikan' in url:raise SourceError('Unavailable')
   return {'id':1117,'russian':'Макото Синкай','animes':[{'id':32281,'name':'Your Name'}]}
  with patch.object(module,'get_json',side_effect=get):self.assertEqual(module.browse('person',identity='1117')['items'][0]['id'],32281)
 def test_rejects_arbitrary_filters_and_invalid_ids_before_network(self):
  with patch.object(module,'get_json') as get:
   for args in [('url','https://internal'),('year','evil'),('season','autumn_0'),('person','','../1')]:
    with self.assertRaises(SourceError):module.browse(*args)
   get.assert_not_called()
