import base64
import io
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from manga_sources import chapter_ranges,parse_chapters,parse_pages,selected,inspect
from run_import import validate_job,run_job,plan_sources
from source_parser import SourceError
from vault_drive import VaultDrive,open_chunk
from test_vault_drive import FakeDrive,PHRASE
from test_server_import import FixtureHttp

class MangaImportTests(unittest.TestCase):
 def test_zero_decimal_chapters_and_inclusive_published_ranges(self):
  ranges=chapter_ranges('0, 1-3, 12.5');self.assertTrue(selected(0,ranges));self.assertTrue(selected(2.5,ranges));self.assertTrue(selected(12.5,ranges));self.assertFalse(selected(4,ranges))
  for value in ['2-1','1.0001','-1','10000']:
   with self.assertRaises(SourceError):chapter_ranges(value)
 def test_current_html_families_preserve_volumes_numbers_and_page_order(self):
  text='<div class="chapter-item"><a href="/manga/a/chapter/2-12.5"><span class="chapter-title">Том 2 Глава 12.5 Экстра</span></a></div><a class="chapters__item" href="/manga/a/chapter/1-0">Том 1 Глава 0</a>'
  chapters=parse_chapters(text,'https://mangapoisk.me/manga/a');self.assertEqual([(c['season'],c['number']) for c in chapters],[(1,0),(2,12.5)])
  text='<script>rm_h.readerInit([["img.example.com","https://","/one.jpg"],["https://images.example.com","https://mirror.example/manga/","/two.jpg"]]);</script>'
  self.assertEqual(parse_pages(text,'https://a.zazaza.me/a'),['https://img.example.com/one.jpg','https://images.example.com/two.jpg'])
  self.assertEqual(parse_pages('<script>var p={"fullimg":["https://images.example/2.jpg","https://images.example/1.jpg",]};</script>','https://manga-chan.me/a'),['https://images.example/2.jpg','https://images.example/1.jpg'])
 def test_paid_chapters_are_rejected_instead_of_saving_their_placeholder(self):
  with self.assertRaises(SourceError):parse_pages('<form class="purchase-form"></form><img class="page-image" src="/premium.jpg">','https://mangapoisk.me/a')
 def test_server_cbz_import_encrypts_pages_and_resumes_without_downloading_them_again(self):
  png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a+kkAAAAASUVORK5CYII=')
  source='https://mangapoisk.me/manga/story/chapter/2-12.5';image='https://images.example/one.png'
  http=FixtureHttp({source:'<html lang="ru"><img class="page-image" src="'+image+'"></html>'},{image:png})
  drive=FakeDrive();vault=VaultDrive(drive,sleep=lambda _:None);library=vault.initialize(PHRASE)
  job={'version':3,'library_id':library,'sources':[source],'section':'manga','collection':'Русская манга','quality':'best','episodes':'12.5',
       'metadata':{'title':'Русская манга','kind':'manga','ids':{'mal':'135496'}},'entries':[{'number':12.5,'season':2,'url':source,'title':'Глава 12.5 — Экстра'}]}
  with patch('manga_download.chapter_preview',return_value=None):
   result=run_job(job,vault,resolver=SimpleNamespace(http=http),log=lambda _:None)
   self.assertEqual(result['saved'],1);item=vault.refresh()['items'][0];self.assertEqual(item['episode'],12.5);self.assertEqual(item['season'],2);self.assertEqual(item['category'],'manga')
   self.assertTrue(item['name'].endswith('12.5.cbz'));self.assertEqual(vault.catalog['storage']['collections'][0]['metadata']['ids']['mal'],'135496')
   raw=b''.join(open_chunk(drive.download(c['fileId']),vault._key,item['id'],n,c['iv']) for n,c in enumerate(item['chunks']))
   with zipfile.ZipFile(io.BytesIO(raw)) as archive:self.assertEqual(archive.read('0001.png'),png)
   calls=len(http.calls);again=run_job(job,vault,resolver=SimpleNamespace(http=http),log=lambda _:None);self.assertEqual(again['skipped'],1);self.assertEqual(len(http.calls),calls)
   self.assertNotIn(png,drive.download(item['chunks'][0]['fileId']))
 def test_decimal_video_episode_is_rejected_while_decimal_manga_is_retained(self):
  job={'version':3,'library_id':'library-123','sources':['https://mangapoisk.me/manga/a'],'entries':[{'number':1.5,'url':'https://mangapoisk.me/manga/a/chapter/1-1.5'}]}
  with self.assertRaises(SourceError):validate_job(job)
  self.assertEqual(validate_job({**job,'section':'manga'})['entries'][0]['number'],1.5)
