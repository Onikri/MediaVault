import sys,time,threading,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import manga_inspection as cache
from source_parser import SourceError

class MangaInspectionTests(unittest.TestCase):
 def setUp(self):
  cache._cache.clear();cache._running.clear()
 def tearDown(self):cache._cache.clear()
 def test_request_readability_does_not_mutate_cached_metadata(self):
  with patch('manga_sources.inspect',return_value={'episodes':[{'number':1,'url':'chapter'}],'seasons':[]} ) as upstream:
   first=cache.inspect('https://manga.example/title');first['readable']=True;first['episodes'][0]['url']='changed'
   second=cache.inspect('https://manga.example/title')
   self.assertNotIn('readable',second);self.assertEqual(second['episodes'][0]['url'],'chapter');self.assertEqual(upstream.call_count,1)
 def test_explicit_retry_refreshes_metadata_then_verification_reuses_it(self):
  with patch('manga_sources.inspect',return_value={'episodes':[],'seasons':[]}) as upstream:
   cache.inspect('https://manga.example/title');cache.inspect('https://manga.example/title',refresh=True);cache.inspect('https://manga.example/title')
   self.assertEqual(upstream.call_count,2)
 def test_summary_and_chapter_selection_share_one_actual_inspection(self):
  data={'episodes':[{'season':1,'number':1,'translator':'A'},{'season':1,'number':1,'translator':'B'},{'season':2,'number':2}], 'seasons':[{'number':1},{'number':2}]}
  calls=[]
  def inspect(url):calls.append(url);time.sleep(.03);return data
  with patch('manga_sources.inspect',side_effect=inspect),ThreadPoolExecutor(max_workers=3) as pool:
   results=list(pool.map(cache.inspect,['https://manga.example/title']*3))
  self.assertEqual(len(calls),1);self.assertTrue(all(v['chapterCount']==2 and v['volumeCount']==2 for v in results))
 def test_failure_is_retryable_without_negative_caching(self):
  with patch('manga_sources.inspect',side_effect=SourceError('HTTP 500')):
   with self.assertRaises(SourceError):cache.inspect('https://manga.example/title')
  with patch('manga_sources.inspect',return_value={'episodes':[],'seasons':[]}):
   self.assertEqual(cache.inspect('https://manga.example/title')['chapterCount'],0)
 def test_summary_uses_the_same_owner_and_exact_title_validation_as_inspection(self):
  import api
  from fastapi.testclient import TestClient
  client=TestClient(api.app)
  self.assertEqual(client.post('/manga/summary',json={'url':'https://manga.example/title'}).status_code,401)
  with patch('manga_sources.inspect',return_value={'title':'Other manga','episodes':[],'seasons':[]}):
   with self.assertRaisesRegex(Exception,'другому произведению'):api.manga_summary(api.MangaInspection(url='https://manga.example/title',title={'kind':'manga','title':'Selected manga'}),subject='owner')
 def test_english_alias_and_matching_year_open_the_same_russian_source(self):
  import api
  title={'kind':'manga','title':'Moon Road','year':2020}
  value={'title':'Лунная дорога','identityTitles':['Лунная дорога'],'aliases':['Лунная дорога','Moon Road'],'year':2020,'episodes':[],'seasons':[]}
  with patch('manga_sources.inspect',return_value=value):
   result=api.manga_inspect(api.MangaInspection(url='https://manga.example/title',title=title),subject='owner')
  self.assertEqual(result['title'],'Лунная дорога')
  for selected,upstream in [(title,{**value,'year':1990}),({**title,'year':None},{**value,'year':None}),({**title,'ids':{'mal':'1'}},{**value,'ids':{'mal':'2'}})]:
   cache._cache.clear()
   with patch('manga_sources.inspect',return_value=upstream),self.assertRaisesRegex(Exception,'другому произведению'):
    api.manga_inspect(api.MangaInspection(url='https://manga.example/title',title=selected),subject='owner')
