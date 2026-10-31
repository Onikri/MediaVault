"""Public metadata gateway contracts; upstream HTTP is mocked, no media/ML inference."""
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import requests
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import jikan_metadata as gateway
from source_parser import SourceError


class JikanMetadataTests(unittest.TestCase):
    def setUp(self):
        for state in (gateway._cache,gateway._pending,gateway._failed_until,gateway._next_request):
            state.clear()

    def test_allowlist_and_bounds_are_checked_before_network(self):
        with patch.object(gateway,'_fetch',return_value={'data':[]}) as get:
            for path in ('https://internal/','anime/../../secret','anime/0/full','users/admin'):
                with self.assertRaises(SourceError):gateway.jikan_json(path)
            with self.assertRaises(SourceError):gateway.jikan_json('anime',{'q':'a'*161})
            with self.assertRaises(SourceError):gateway.jikan_json('anime',{'page':'bad'})
            get.assert_not_called()
            gateway.jikan_json('anime',{'q':'Наруто','limit':999,'page':0,'token':'secret'})
            self.assertEqual(get.call_args.args[2],{'q':'Наруто','limit':'25','page':'1'})

    def test_compatibility_fallback_and_shared_resource_cache(self):
        with patch.object(gateway,'_fetch',side_effect=[requests.Timeout(),{'data':{'mal_id':20}}]) as get:
            self.assertEqual(gateway.jikan_json('anime/20/full',{'page':1})['data']['mal_id'],20)
            self.assertEqual(gateway.jikan_json('anime/20/full')['data']['mal_id'],20)
            self.assertEqual(get.call_count,2)
            self.assertEqual(get.call_args.args[0],gateway.BASES[1])

    def test_simultaneous_identical_queries_have_one_upstream_request(self):
        entered,release=threading.Event(),threading.Event()
        def fetch(*args):
            entered.set();release.wait(2)
            return {'data':[{'mal_id':20}]}
        with patch.object(gateway,'_fetch',side_effect=fetch) as get,ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(gateway.jikan_json,'anime',{'q':'Наруто'})
            self.assertTrue(entered.wait(2))
            second=pool.submit(gateway.jikan_json,'anime',{'q':'Наруто'})
            release.set()
            self.assertEqual(first.result(),second.result())
            self.assertEqual(get.call_count,1)

    def test_expired_public_metadata_survives_upstream_outage(self):
        value={'data':{'mal_id':20}}
        with patch.object(gateway,'_fetch',return_value=value):gateway.jikan_json('anime/20/full')
        key=('anime/20/full',())
        gateway._cache[key]=(0,value)
        with patch.object(gateway,'_fetch',side_effect=requests.Timeout()):
            self.assertEqual(gateway.jikan_json('anime/20/full'),value)

    def test_season_feed_excludes_mismatched_year_and_season(self):
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc);season=('winter','spring','summer','fall')[(now.month-1)//3]
        current=[{'mal_id':1,'season':season,'year':now.year},{'mal_id':2,'season':'invalid','year':now.year},{'mal_id':3,'season':season,'year':now.year-1}]
        with patch.object(gateway,'jikan_json',side_effect=lambda path,params:{'data':current if path.startswith('seasons/') else []}),patch('metadata_helpers.localize'):
            result=gateway.home_feed()
        self.assertEqual([row['mal_id'] for row in result['current']],[1])
        self.assertEqual(result['season']['year'],now.year)


if __name__=='__main__':unittest.main()
