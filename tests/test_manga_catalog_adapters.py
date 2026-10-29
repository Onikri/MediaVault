import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from manga_catalog_adapters import api_url,dex_search,inspect_catalog,get
from source_parser import SourceError
class MangaCatalogAdapters(unittest.TestCase):
 def test_lib_inspection_keeps_original_aliases_for_english_metadata_identity(self):
  from title_identity import match_title
  with patch('manga_catalog_adapters.get',side_effect=[{'data':{'rus_name':'Наруто','eng_name':'Naruto','otherNames':['ナルト']}},{'data':[]}]):
   value=inspect_catalog('https://mangalib.me/ru/195--naruto',None)
  self.assertEqual(value['aliases'],['Наруто','Naruto','ナルト'])
  self.assertTrue(match_title({'title':'Naruto','kind':'manga'},value)[0])
 def test_lib_public_api_identifies_catalogue_without_account_credentials(self):
  with patch('manga_catalog_adapters.PublicHttp') as client:
   instance=client.return_value;instance.session.headers={};instance.document.return_value=('{}','','')
   get('https://api.cdnlibs.org/api/manga?q=Naruto',None)
   self.assertEqual(instance.session.headers,{'Site-Id':'1','Accept':'application/json'})
   instance.document.assert_called_once_with('https://api.cdnlibs.org/api/manga?q=Naruto',headers={'Referer':'https://mangalib.me/'})
   self.assertNotIn('Authorization',instance.session.headers);self.assertNotIn('Cookie',instance.session.headers)
 def test_api_reader_cannot_request_unrelated_api_or_internal_address(self):
  for url in ['https://api.mangadex.org/auth/login','https://api.cdnlibs.org/api/auth/me','https://127.0.0.1/api/manga','https://evil.example/api/manga']:
   with self.assertRaises(SourceError):api_url(url)
 def test_dex_language_variants_share_aliases_and_keep_language_explicit(self):
  rows={'data':[{'id':'demo','attributes':{'title':{'en':'Demo Manga'},'altTitles':[{'ru':'Тестовая манга'}],'availableTranslatedLanguages':['ru','en'],'year':2021,'contentRating':'safe'},'relationships':[]}]}
  with patch('manga_catalog_adapters.get',return_value=rows):values=dex_search('Demo','all',None)
  self.assertEqual({v['language'] for v in values},{'ru','en'});self.assertTrue(all(v['title']=='Тестовая манга' and 'Demo Manga' in v['aliases'] for v in values))
 def test_mangalib_excludes_closed_branches_and_preserves_translation_team(self):
  detail={'data':{'rus_name':'Тестовая манга'}};chapters={'data':[{'number':'0','volume':'1','branches':[{'branch_id':10,'teams':[{'name':'Команда'}],'restricted_view':{'is_open':True}},{'branch_id':11,'restricted_view':{'is_open':False}}]}]}
  with patch('manga_catalog_adapters.get',side_effect=[detail,chapters]):value=inspect_catalog('https://mangalib.me/ru/1--demo',None)
  self.assertEqual(len(value['episodes']),1);self.assertEqual(value['episodes'][0]['number'],0);self.assertEqual(value['episodes'][0]['translator'],'Команда');self.assertTrue(value['episodes'][0]['url'].endswith('?bid=10'))
 def test_mangalib_pages_use_published_compression_server_and_order(self):
  detail={'data':{'rus_name':'Тест'}};chapter={'data':{'pages':[{'slug':2,'url':'/two.jpg'},{'slug':1,'url':'/one.jpg'}]}};constants={'data':{'imageServers':[{'id':'compress','site_ids':[1],'url':'https://images.example'}]}}
  with patch('manga_catalog_adapters.get',side_effect=[detail,chapter,constants]):value=inspect_catalog('https://mangalib.me/ru/1--demo/read/v2/c1.5?bid=10',None)
  self.assertEqual(value['pages'],['https://images.example/one.jpg','https://images.example/two.jpg']);self.assertEqual(value['episodes'][0]['number'],1.5)
 def test_dex_never_replaces_removed_chapters_with_external_licensed_links(self):
  identity='68112dc1-2b80-4f20-beb8-2f2a8716a430';detail={'data':{'attributes':{'title':{'en':'Dandadan'},'contentRating':'safe'}}};feed={'total':1,'data':[{'id':'chapter','attributes':{'chapter':'1','pages':1,'externalUrl':'https://licensed.example/read'},'relationships':[]}]}
  with patch('manga_catalog_adapters.get',side_effect=[detail,feed]):value=inspect_catalog('https://mangadex.org/title/'+identity+'?lang=en',None)
  self.assertEqual(value['episodes'],[]);self.assertFalse(value['available'])
