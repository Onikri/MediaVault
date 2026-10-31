import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from anime_biography import biography
class BiographyTests(unittest.TestCase):
 def test_birth_match_is_required_before_using_same_named_person_summary(self):
  summary={'wikibase_item':'Q1','extract':'Published biography','content_urls':{'desktop':{'page':'https://en.wikipedia.org/wiki/Person'}}}
  entity={'entities':{'Q1':{'claims':{'P569':[{'mainsnak':{'datavalue':{'value':{'time':'+1973-02-09T00:00:00Z'}}}}]}}}}
  with patch('anime_biography.get_json',side_effect=[summary,entity]):self.assertEqual(biography('Person',birth={'year':1973,'month':2,'day':9})['description'],'Published biography')
  with patch('anime_biography.get_json',side_effect=[summary,entity]):self.assertEqual(biography('Person',birth={'year':1970,'month':1,'day':1}),{})
 def test_studio_requires_both_exact_published_name_and_studio_classification(self):
  summary={'wikibase_item':'Q2','description':'Japanese animation film studio','extract':'Published history'}
  entity={'entities':{'Q2':{'labels':{'en':{'value':'Studio Name'}},'claims':{}}}}
  with patch('anime_biography.get_json',side_effect=[summary,entity]):self.assertEqual(biography('Studio Name',studio=True)['description'],'Published history')
  with patch('anime_biography.get_json',side_effect=[summary,entity]):self.assertEqual(biography('Another Name',studio=True),{})
