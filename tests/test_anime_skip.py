from pathlib import Path
import sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import anime_skip
from source_parser import SourceError

class AnimeSkipTests(unittest.TestCase):
    def setUp(self):anime_skip._cache.clear()
    def test_not_found_is_distinct_from_a_network_failure(self):
        from unittest.mock import MagicMock
        response=MagicMock();response.status_code=404;response.ok=False;response.iter_content.return_value=[b'{"found":false,"results":[]}']
        response.__enter__.return_value=response
        with patch('anime_skip.requests.get',return_value=response):self.assertFalse(anime_skip.get_json('https://api.aniskip.com/v2/skip-times/1/1')['found'])
    def test_release_matching_rejects_non_finite_and_different_cuts_and_chooses_nearest(self):
        def row(start,end,length,kind='op'):return {'skipType':kind,'interval':{'startTime':start,'endTime':end},'episodeLength':length}
        rows=[row(10,100,1500),row(15,105,1471),row(0,90,1800),row(float('nan'),90,1470),row(1400,1471,1470,'ed')]
        result=anime_skip.choose_intervals({'results':rows},1470)
        self.assertEqual(result[0]['start'],15);self.assertFalse(result[0]['needsReview']);self.assertEqual(result[1]['end'],1470)
    def test_cross_season_numbering_and_success_cache(self):
        def response(url,params=None):
            if 'relation-rules' in url:return {'found':True,'rules':[{'from':{'start':14,'end':38},'to':{'malId':33486,'start':1,'end':25}}]}
            self.assertIn('/33486/1',url)
            return {'found':True,'results':[{'skipType':'op','interval':{'startTime':20,'endTime':110},'episodeLength':1470}]}
        with patch('anime_skip.get_json',side_effect=response) as mocked:
            one=anime_skip.skip_times(31964,14,1470);two=anime_skip.skip_times(31964,14,1470)
            self.assertEqual(mocked.call_count,2);self.assertEqual(one,two);self.assertEqual(one['animeId'],33486);self.assertEqual(one['episode'],1)
    def test_failure_has_retry_message_and_never_invents_an_interval(self):
        with patch('anime_skip.get_json',side_effect=SourceError('offline')):
            result=anime_skip.skip_times(31964,1,1470)
        self.assertEqual(result['intervals'],[]);self.assertTrue(result['unavailable'])
    def test_small_release_difference_is_visible_and_is_not_scaled(self):
        result=anime_skip.choose_intervals({'results':[{'skipType':'op','interval':{'startTime':15,'endTime':105},'episodeLength':1483.6}]},1470)
        self.assertTrue(result[0]['needsReview']);self.assertEqual(result[0]['start'],15);self.assertEqual(result[0]['end'],105)
