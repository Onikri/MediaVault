import sys,unittest
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import manga_sources as source
class MangaLanguages(unittest.TestCase):
 def setUp(self):source._cache.clear();self.calls=[]
 def search(self,language):
  calls=self.calls
  class Http:
   def __init__(self,**kwargs):pass
   def close(self):pass
   def document(self,url):
    calls.append(url);host=urlsplit(url).hostname
    if host=='mangahub.ru':text='<div class="item-grid"><a class="fw-medium" href="/title/demo">Demo Manga</a></div>'
    elif host=='mangapill.com':text='<div><div><a class="mb-2" href="/manga/42/demo"><div class="font-black">Demo Manga</div></a></div></div>'
    else:text='<html></html>'
    return text,url,{}
  with patch('manga_sources.PublicHttp',Http),patch('manga_catalog_adapters.PublicHttp',Http),patch('manga_raw_adapters.PublicHttp',Http):return source.search_title({'title':'Тестовая манга','aliases':['Demo Manga'],'kind':'manga'},language)
 def test_all_languages_includes_english_even_when_russian_exists(self):
  result=self.search('all');self.assertEqual({v['language'] for v in result['results']},{'ru','en'})
 def test_english_does_not_contact_russian_sites(self):
  result=self.search('en');self.assertEqual({urlsplit(v).hostname for v in self.calls},{'mangapill.com','mangakatana.com','api.mangadex.org','www.webtoons.com'});self.assertEqual(result['results'][0]['language'],'en')
 def test_russian_does_not_contact_english_and_cache_is_partitioned(self):
  result=self.search('ru');self.assertTrue(all(urlsplit(v).hostname!='mangapill.com' for v in self.calls));self.assertEqual({v['language'] for v in result['results']},{'ru'});self.calls.clear();self.assertEqual(self.search('en')['results'][0]['language'],'en')
 def test_legacy_auto_preserves_fallback_behavior(self):
  self.assertEqual({v['language'] for v in self.search('auto')['results']},{'ru'})
