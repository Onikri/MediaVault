"""Network contracts are fixtures; live GraphQL and playback checked separately."""
import unittest,time,threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
import anime_music as music
from source_parser import SourceError

class ThemeCatalogTests(unittest.TestCase):
 def setUp(self):music._cache.clear();music._pending.clear()
 def fallback(self,mal_id=99):return {'data':{'mal_id':mal_id,'theme':{'openings':['1: "again" by YUI (eps 1-14)'],'endings':['"Uso" by SID']}}}
 def test_graphql_errors_fall_back_to_exact_mal_credits_and_cache(self):
  with patch.object(music,'get_json',side_effect=[{'errors':[{'message':'unavailable'}]},self.fallback()]) as fetch:
   result=music.songs(99);self.assertEqual(music.songs(99),result);self.assertEqual(fetch.call_count,2)
  self.assertEqual([(t['title'],t['artists'],t['episodes']) for t in result['tracks']],[('again',['YUI'],['1-14']),('Uso',['SID'],[])])
  self.assertEqual(result['source'],'MyAnimeList / Jikan');self.assertFalse(result['audioDownloaded'])
 def test_wrong_fallback_identity_is_not_shown_as_successful_empty_catalog(self):
  with patch.object(music,'get_json',side_effect=[SourceError('offline'),self.fallback(100)]):
   app=FastAPI();music.install(app);r=TestClient(app).get('/music/anime/99')
  self.assertEqual(r.status_code,502);self.assertNotIn('tracks',r.json());self.assertFalse(music._pending)
 def test_saved_credits_survive_both_upstream_failures(self):
  old={'identity':'99','tracks':[{'title':'Saved'}],'source':'AnimeThemes'};music._cache['99']=(time.monotonic()-1,old)
  with patch.object(music,'get_json',side_effect=SourceError('offline')):r=music.songs(99)
  self.assertTrue(r['stale']);self.assertEqual(r['tracks'],old['tracks'])
 def test_parallel_consumers_share_catalog_request(self):
  entered=threading.Event();release=threading.Event()
  def fetch(*args,**kwargs):
   entered.set();release.wait(2)
   return {'data':{'findAnimeByExternalSite':[{'slug':'x','resources':{'nodes':[{'site':'MAL','externalId':99}]},'animethemes':[{'id':1,'type':'OP','song':{'title':{'native':'Song'},'performances':[]},'animethemeentries':[]}]}]}}
  with patch.object(music,'get_json',side_effect=fetch) as request,ThreadPoolExecutor(max_workers=2) as pool:
   a=pool.submit(music.songs,99);self.assertTrue(entered.wait(1));b=pool.submit(music.songs,99);release.set();self.assertEqual(a.result(),b.result())
  self.assertEqual(request.call_count,1)
 def test_exact_empty_catalog_is_truthful_when_backup_also_has_no_themes(self):
  with patch.object(music,'get_json',side_effect=[{'data':{'findAnimeByExternalSite':[]}}, {'data':{'mal_id':99,'theme':{'openings':[],'endings':[]}}}]):r=music.songs(99)
  self.assertEqual(r['tracks'],[])
 def test_malformed_and_out_of_graphql_int_range_ids_do_not_fetch(self):
  with patch.object(music,'get_json') as fetch:
   for identity in ['0','1/x','2147483648']:
    with self.assertRaises(Exception) as context:music.songs(identity)
    self.assertEqual(context.exception.status_code,422)
   fetch.assert_not_called()
