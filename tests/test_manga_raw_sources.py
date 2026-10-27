import base64,json,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import manga_sources as sources
import manga_raw_adapters as raw
from manga_catalog_adapters import dex_search,inspect_catalog
from manga_download import download_chapter
from run_import import source_identity
from source_parser import SourceError,playback_headers

class RawSources(unittest.TestCase):
 def setUp(self):sources._cache.clear()
 def test_japanese_search_contacts_only_japanese_capable_providers_and_prefers_native_alias(self):
  calls=[]
  class Http:
   def __init__(self,**kwargs):pass
   def close(self):pass
  def search(query,site,http):calls.append((query,site.id));return []
  with patch('manga_sources.PublicHttp',Http),patch('manga_raw_adapters.search',side_effect=search),patch('manga_catalog_adapters.dex_search',return_value=[]):
   result=sources.search_title({'kind':'manga','title':'Тест','titles':{'ja':'テスト'},'aliases':['Test Manga']},'ja')
  self.assertEqual({p['provider'] for p in result['providers']},{'mangadex','senmanga','mangaraw'});self.assertTrue(all(next(q for q,s in calls if s==provider)=='テスト' for provider in {'senmanga','mangaraw'}));self.assertEqual(result['language'],'ja')
 def test_webtoon_filter_retains_korean_original_readers(self):
  class Http:
   def __init__(self,**kwargs):pass
   def close(self):pass
  def search(query,site,http):return [raw.record(site,'테스트',site.root+'/demo')]
  with patch('manga_sources.PublicHttp',Http),patch('manga_raw_adapters.search',side_effect=search),patch('manga_catalog_adapters.dex_search',return_value=[]):
   result=sources.search_title({'kind':'manga','title':'테스트','format':'MANHWA'},'ko','webtoon')
  self.assertEqual(len(result['results']),4);self.assertTrue(all(r['language']=='ko' and r['readingMode']=='scroll' for r in result['results']))
 def test_public_api_boundary_rejects_private_endpoints_and_path_traversal(self):
  for url in ['https://comic.naver.com/api/auth/me','https://api.mangarw.com/api/v1/auth','https://raw.senmanga.com/api/manga/..','https://raw.senmanga.com/api/read/a/..','https://127.0.0.1/api/directory','https://api.mangarw.com.evil.example/api/v1/manga/1']:
   with self.subTest(url=url),self.assertRaises(SourceError):raw.api_url(url)
 def test_naver_catalogues_use_their_own_public_search_contract(self):
  for provider,section in [('naver-webtoon','webtoon'),('naver-best','bestChallenge'),('naver-challenge','challenge')]:
   site=next(v for v in sources.SITES if v.id==provider)
   with patch('manga_raw_adapters.get',return_value={'searchList':[{'titleId':42,'titleName':'테스트','thumbnailUrl':'https://cdn.example/cover.jpg'}]}) as get:
    result=raw.search('테스트',site,None)
   url=get.call_args.args[0];self.assertEqual(urlsplit(url).path,'/api/search/'+section);self.assertEqual(parse_qs(urlsplit(url).query)['keyword'],['테스트']);self.assertEqual(result[0]['language'],'ko');self.assertEqual(result[0]['provider'],provider)
 def test_korean_referer_is_encoded_before_http_header_serialization(self):
  value=playback_headers({'Referer':'https://toonkor7.org/화산귀환'})['Referer'];self.assertTrue(value.isascii());self.assertIn('%ED',value)
 def test_provider_languages_and_naver_catalogues_are_distinct(self):
  self.assertEqual(sources.site_for('https://comic.naver.com/webtoon/list?titleId=1').id,'naver-webtoon')
  self.assertEqual(sources.site_for('https://comic.naver.com/bestChallenge/list?titleId=1').id,'naver-best')
  self.assertEqual(sources.site_for('https://comic.naver.com/challenge/detail?titleId=1&no=1').id,'naver-challenge')
  self.assertIsNone(sources.site_for('https://comic.naver.com.evil.example/webtoon/list?titleId=1'))
 def test_naver_keeps_published_numbers_skips_charges_and_stops_repeated_pagination(self):
  detail={'titleName':'테스트 만화'};first={'articleList':[{'no':10,'subtitle':'8화','charge':False},{'no':11,'subtitle':'9화','charge':True}],'pageInfo':{'nextPage':2}};second={'articleList':[{'no':1,'subtitle':'1화','charge':False}],'pageInfo':{'nextPage':2}}
  with patch('manga_raw_adapters.get',side_effect=[detail,first,second]) as get:
   result=sources.inspect('https://comic.naver.com/webtoon/list?titleId=123')
  self.assertEqual([v['number'] for v in result['episodes']],[1,8]);self.assertTrue(result['episodes'][1]['url'].endswith('no=10'));self.assertEqual(get.call_count,3);self.assertTrue(result['truncated']);self.assertEqual((result['language'],result['format'],result['readingMode']),('ko','manhwa','scroll'))
 def test_naver_reader_collects_actual_images_and_not_advertising(self):
  class Http:
   def document(self,url):return '<title>테스트 - 1화</title><img src="https://cdn.example/ad.png"><div class="wt_viewer"><img src="https://cdn.example/2.jpg"><img data-src="https://cdn.example/1.jpg"></div>',url,{}
  with patch('manga_raw_adapters.get',return_value={'titleName':'테스트'}):result=sources.inspect('https://comic.naver.com/webtoon/detail?titleId=1&no=1',Http())
  self.assertEqual(result['pages'],['https://cdn.example/2.jpg','https://cdn.example/1.jpg']);self.assertEqual(result['episodes'][0]['number'],1)
 def test_naver_closed_reader_returns_actionable_error(self):
  class Http:
   def document(self,url):return '<h1>Login</h1><img src="/cover.jpg">',url,{}
  with patch('manga_raw_adapters.get',return_value={'titleName':'테스트'}),self.assertRaisesRegex(SourceError,'Naver'):sources.inspect('https://comic.naver.com/webtoon/detail?titleId=1&no=2',Http())
 def test_raw_japanese_chapters_preserve_zero_decimal_and_aliases(self):
  with patch('manga_raw_adapters.get',side_effect=[{'data':{'title':'テスト','alternative':'Test Manga'}},{'data':[{'id':12,'index':12.5,'title':'第12.5話'},{'id':1,'index':0,'title':'序章'}]}]):result=sources.inspect('https://mangaraw.co.uk/manga/42')
  self.assertEqual([v['number'] for v in result['episodes']],[0,12.5]);self.assertIn('Test Manga',result['aliases']);self.assertEqual(result['language'],'ja')
 def test_reader_templates_and_image_order_are_bounded_and_checked(self):
  data={'data':{'title':'第1話','manga':{'title':'テスト'},'storageUrl':'https://cdn.example','content':[{'type':'selfhosted','data':{'from':0,'to':1,'url':'/p/{page}.webp'}},{'type':'hotlink','data':['https://other.example/2.jpg']},{'type':'external','data':['/3.png']}]}}
  with patch('manga_raw_adapters.get',return_value=data):result=sources.inspect('https://mangaraw.co.uk/chapter/12')
  self.assertEqual(result['pages'],['https://cdn.example/p/0.webp','https://cdn.example/p/1.webp','https://other.example/2.jpg','https://cdn.example/3.png'])
  data['data']['content'][0]['data']['to']=600
  with patch('manga_raw_adapters.get',return_value=data),self.assertRaises(SourceError):sources.inspect('https://mangaraw.co.uk/chapter/12')
 def test_sen_published_chapter_list_and_page_list_are_linked_without_guessed_urls(self):
  detail={'title':'テスト','chapterList':[{'url':'zero','title':'第0話'},{'url':'extra','title':'第12.5話'}]}
  with patch('manga_raw_adapters.get',side_effect=[detail,{'pages':['https://cdn.example/a.jpg']} ]):result=sources.inspect('https://raw.senmanga.com/manga/demo/chapter-extra/')
  self.assertEqual(result['episodes'][0]['number'],12.5);self.assertEqual(result['pages'],['https://cdn.example/a.jpg'])
 def test_toonkor_reads_only_base64_image_markup_without_executing_scripts(self):
  encoded=base64.b64encode(b'<img src="https://cdn.example/a.jpg"><img src="javascript:alert(1)">').decode()
  class Http:
   def document(self,url):return '<h1>테스트 12화</h1><script>var toon_img = \''+encoded+'\'; throw Error("never execute");</script>',url,{}
  result=sources.inspect('https://toonkor0.org/demo-12',Http());self.assertEqual(result['pages'],['https://cdn.example/a.jpg']);self.assertEqual(result['episodes'][0]['number'],12)
 def test_dex_original_languages_and_format_survive_catalog_search_and_inspection(self):
  record={'id':'68112dc1-2b80-4f20-beb8-2f2a8716a430','attributes':{'title':{'ko':'테스트'},'altTitles':[{'ja':'テスト'}],'originalLanguage':'ko','availableTranslatedLanguages':['ja','ko'],'contentRating':'safe'}}
  with patch('manga_catalog_adapters.get',return_value={'data':[record]}):values=dex_search('Test','all',None)
  self.assertEqual({v['language'] for v in values},{'ja','ko'});self.assertTrue(all(v['format']=='manhwa' for v in values))
  feed={'total':1,'data':[{'id':'chapter','attributes':{'chapter':'1','pages':3,'translatedLanguage':'ko'},'relationships':[]}]}
  with patch('manga_catalog_adapters.get',side_effect=[{'data':record},feed]):result=inspect_catalog('https://mangadex.org/title/'+record['id']+'?lang=ko',None)
  self.assertEqual(result['language'],'ko');self.assertEqual(result['episodes'][0]['language'],'ko');self.assertEqual(result['format'],'manhwa')
 def test_naver_title_and_episode_queries_cannot_collapse_in_drive_identity(self):
  a=source_identity('https://comic.naver.com/webtoon/detail?titleId=1&no=2');b=source_identity('https://comic.naver.com/webtoon/detail?titleId=3&no=2');c=source_identity('https://comic.naver.com/webtoon/detail?titleId=1&no=3')
  self.assertEqual(len({a,b,c}),3)
 def test_raw_cbz_download_uses_verified_api_pages_and_preserves_exact_bytes(self):
  data={'data':{'title':'第0話','manga':{'title':'テスト'},'content':[{'type':'hotlink','data':['https://cdn.example/1.png','https://cdn.example/2.png']}]}}
  image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a+kkAAAAASUVORK5CYII=')
  class Http:
   def download(self,url,path,**kwargs):Path(path).write_bytes(image)
  with patch('manga_raw_adapters.get',return_value=data),tempfile.TemporaryDirectory() as directory:
   archive=download_chapter('https://mangaraw.co.uk/chapter/1',directory,Http())
   with zipfile.ZipFile(archive) as cbz:self.assertEqual(cbz.namelist(),['0001.png','0002.png']);self.assertEqual(cbz.read('0002.png'),image)

if __name__=='__main__':unittest.main()
