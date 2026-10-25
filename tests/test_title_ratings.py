from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from title_ratings import fetch_rating,ratings,score,_cache

class TitleRatingTests(unittest.TestCase):
 def setUp(self):_cache.clear()
 def test_exact_mal_identity_is_checked_and_missing_ratings_are_never_fabricated(self):
  with patch('title_ratings.get_json',return_value={'data':{'mal_id':999,'score':9.5,'scored_by':100}}):self.assertIsNone(fetch_rating('mal','57334','anime'))
  self.assertIsNone(score('mal',None,10,'https://myanimelist.net'));self.assertIsNone(score('mal',float('nan'),10,'https://myanimelist.net'))
 def test_kitsu_mapping_preserves_media_kind_and_scales_to_ten(self):
  data={'data':[{'attributes':{'externalSite':'myanimelist/manga','externalId':'135496'},'relationships':{'item':{'data':{'type':'manga','id':'1'}}}}],
        'included':[{'type':'anime','id':'1','attributes':{'averageRating':'99'}},{'type':'manga','id':'1','attributes':{'averageRating':'85.33','ratingFrequencies':{'10':'12','20':'30'}}}]}
  with patch('title_ratings.get_json',return_value=data):
   value=fetch_rating('kitsu','135496','manga');self.assertEqual(value['normalized'],8.53);self.assertEqual(value['votes'],42);self.assertIn('/manga/1',value['url']);self.assertIsNone(fetch_rating('kitsu','135496','anime'))
 def test_partial_platform_failure_keeps_real_scores_and_success_cache(self):
  def fetch(provider,identity,kind):
   if provider=='anilist':raise RuntimeError('Temporary source error')
   return score(provider,8,10,'https://example.com/'+provider,20)
  with patch('title_ratings.fetch_rating',side_effect=fetch) as lookup:
   value=ratings('57334');again=ratings('57334');self.assertEqual(len(value['items']),3);self.assertEqual(lookup.call_count,4)
   self.assertTrue(all(v['checkedAt'] for v in value['items']));self.assertEqual(next(p for p in again['providers'] if p['provider']=='anilist')['status'],'unavailable')
