import sys,unittest,io,tempfile,zipfile,shutil
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import reader_translation as reader
import anime_music
from manga_sources import parse_pages,parse_search,parse_chapters,site_for
class ReaderMusicTests(unittest.TestCase):
 def test_ocr_groups_words_normalizes_coordinates_and_drops_uncertain_noise(self):
  t='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t2\t1\t1\t1\t10\t20\t40\t12\t98\tHello\n5\t1\t2\t1\t1\t2\t55\t20\t45\t12\t94\tfriend\n5\t1\t3\t1\t1\t1\t0\t0\t2\t2\t2\tx\n'
  result=reader.ocr_regions(t,100,200);self.assertEqual(len(result),1);self.assertEqual(result[0]['original'],'Hello friend');self.assertLessEqual(result[0]['x']+result[0]['w'],1)
 def test_short_negations_and_prepositions_are_not_lost(self):
  t='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t10\t20\t15\t12\t96\tNO\n5\t1\t2\t1\t1\t1\t10\t40\t15\t12\t94\tIN\n'
  self.assertEqual([r['original'] for r in reader.ocr_regions(t,100,200)],['NO','IN'])
 def test_speech_lines_join_into_sentences_without_merging_columns(self):
  rows=[{'x':.7,'y':.1,'w':.16,'h':.02,'original':'PRESIDENT'},{'x':.7,'y':.12,'w':.16,'h':.02,'original':'OBAMA HAS'},{'x':.72,'y':.14,'w':.12,'h':.02,'original':'ALREADY'},{'x':.1,'y':.12,'w':.15,'h':.02,'original':'OTHER BUBBLE'}]
  self.assertEqual(reader.translation_input("I DON’T BELIEVE IN UFOS OR ALIENS."),"I don't believe in UFOs or aliens.")
  joined=reader.merge_bubbles(rows);self.assertEqual(len(joined),2);self.assertEqual(joined[0]['original'],'PRESIDENT OBAMA HAS ALREADY');self.assertEqual(reader.translation_input(joined[0]['original']),'President obama has already')
  hyphens=reader.merge_bubbles([{'x':.1,'y':.1,'w':.1,'h':.02,'original':'PARA-'},{'x':.1,'y':.12,'w':.1,'h':.02,'original':'NORMAL'}]);self.assertEqual(hyphens[0]['original'],'PARANORMAL')
 def test_music_requires_exact_catalogue_mapping_and_never_downloads_audio(self):
  rows={'anime':[{'slug':'wrong','resources':[{'site':'MyAnimeList','external_id':2}],'animethemes':[{'id':1,'type':'OP','song':{'title':'Wrong'}}]},{'slug':'real','resources':[{'site':'MyAnimeList','external_id':99}],'animethemes':[{'id':2,'type':'OP','song':{'title':'Real','artists':[{'name':'Artist'}]},'animethemeentries':[{'episodes':'1-12','nsfw':False}]}]}]}
  anime_music._cache.clear()
  with patch('anime_music.get_json',return_value=rows):r=anime_music.songs('99')
  self.assertEqual([v['title'] for v in r['tracks']],['Real']);self.assertFalse(r['audioDownloaded']);self.assertIsNone(r['tracks'][0]['timing'])
 def test_english_reader_uses_published_images_and_exact_chapter_links(self):
  self.assertEqual(parse_pages('<img class="js-page" data-src="https://images.example/1.jpeg">','https://mangapill.com/chapters/11-x/a'),['https://images.example/1.jpeg'])
  rows=parse_chapters('<a href="/chapters/11-1/a-chapter-1.5">Chapter 1.5</a>','https://mangapill.com/manga/11/a');self.assertEqual(rows[0]['number'],1.5)
 def test_translation_endpoint_is_private_and_model_status_is_public(self):
  from fastapi import FastAPI,HTTPException
  from fastapi.testclient import TestClient
  def denied():raise HTTPException(401,'Login')
  app=FastAPI();reader.install(app,'/nonexistent',denied);client=TestClient(app)
  self.assertFalse(client.get('/reader/translation').json()['ready']);self.assertEqual(client.post('/reader/translate',json={'image':'a'*100}).status_code,401)

class ReaderCompressionTests(unittest.TestCase):
 @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg unavailable')
 def test_economy_import_resizes_before_cbz_encryption(self):
  from PIL import Image
  from manga_download import download_chapter
  image=io.BytesIO();Image.new('RGB',(2560,1800),'white').save(image,format='PNG');data=image.getvalue()
  class Http:
   def document(self,url):return '<img class="page-image" src="https://images.example/page.png">',url,{}
   def download(self,url,target,**kwargs):Path(target).write_bytes(data)
  with tempfile.TemporaryDirectory() as directory:
   path=download_chapter('https://mangapoisk.me/chapter/1-1',directory,Http(),quality='1280')
   with zipfile.ZipFile(path) as z:
    page=Image.open(io.BytesIO(z.read(z.namelist()[0])));self.assertEqual(page.width,1280);self.assertEqual(page.format,'JPEG')

class PrivateTranslationCacheTests(unittest.TestCase):
 def test_translation_cache_is_partitioned_by_owner_and_unauthenticated_requests_are_rejected(self):
  import base64
  from fastapi import FastAPI
  from fastapi.testclient import TestClient
  subject=['first'];app=FastAPI();reader._cache.clear();reader.install(app,'/unused',lambda:subject[0]);client=TestClient(app)
  payload={'image':base64.b64encode(b'fixture image bytes').decode()}
  with patch('reader_translation.ready',return_value=True),patch('reader_translation.translate_image',return_value={'regions':[]}) as translate:
   self.assertEqual(client.post('/reader/translate',json=payload).status_code,200)
   self.assertEqual(client.post('/reader/translate',json=payload).status_code,200);self.assertEqual(translate.call_count,1)
   subject[0]='second';self.assertEqual(client.post('/reader/translate',json=payload).status_code,200);self.assertEqual(translate.call_count,2)

class BubbleRefinementTests(unittest.TestCase):
 def test_second_pass_restores_missed_lines_without_moving_the_bubble(self):
  from PIL import Image
  from types import SimpleNamespace
  regions=[{'x':.1,'y':.1,'w':.3,'h':.3,'original':'I DO NOT BELIEVE ALIENS'}]
  header='page_num\tline_num\tconf\ttext\n'
  rows=''.join(f'1\t1\t95\t{word}\n' for word in ['I','DO','NOT','BELIEVE','IN','UFOs','OR','ALIENS'])
  with tempfile.TemporaryDirectory() as work,patch('reader_translation.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=(header+rows).encode())):
   result=reader.refine_bubbles(Image.new('RGB',(300,500),'white'),regions,work)
  self.assertEqual(result[0]['original'],'I DO NOT BELIEVE IN UFOs OR ALIENS');self.assertEqual((result[0]['x'],result[0]['y']),(.1,.1))
 def test_refinement_failure_keeps_first_pass_text(self):
  from PIL import Image
  regions=[{'x':.1,'y':.1,'w':.3,'h':.3,'original':'Original words'}]
  with tempfile.TemporaryDirectory() as work,patch('reader_translation.subprocess.run',side_effect=OSError('unavailable')):
   self.assertEqual(reader.refine_bubbles(Image.new('RGB',(300,500),'white'),regions,work)[0]['original'],'Original words')
