import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from PIL import Image,ImageDraw
from reader_bubbles import speech_regions
class SpeechBubbles(unittest.TestCase):
 def test_rows_are_grouped_inside_their_speech_bubbles_and_noise_does_not_cover_art(self):
  image=Image.new('RGB',(800,1000),(255,244,223));draw=ImageDraw.Draw(image);draw.ellipse((50,50,340,450),outline='black',width=4);draw.ellipse((460,60,760,470),outline='black',width=4)
  rows=[{'x':.12,'y':.17,'w':.21,'h':.025,'original':'I DO NOT','confidence':95},{'x':.12,'y':.21,'w':.21,'h':.025,'original':'BELIEVE IN ALIENS','confidence':94},{'x':.65,'y':.2,'w':.2,'h':.025,'original':'OTHER DIALOGUE','confidence':94},{'x':.47,'y':.7,'w':.04,'h':.01,'original':'BSS','confidence':42}]
  result=speech_regions(image,rows);self.assertEqual(len(result),2);self.assertTrue(all(r['placement']=='bubble' for r in result));self.assertIn('I DO NOT BELIEVE IN ALIENS',[r['original'] for r in result]);self.assertTrue(all(r['color']==[255,244,223] for r in result))
  self.assertTrue(all(0<=p[0]<=1 and 0<=p[1]<=1 for r in result for p in r['shape']))
 def test_unbounded_text_becomes_a_note_instead_of_erasing_the_drawing(self):
  image=Image.new('RGB',(800,1000),'white');result=speech_regions(image,[{'x':.3,'y':.4,'w':.1,'h':.04,'original':'A REAL SENTENCE','confidence':90}]);self.assertEqual(result[0]['placement'],'note')
 def test_separate_paragraphs_in_a_connected_region_do_not_merge_columns(self):
  image=Image.new('RGB',(800,1000),'white');draw=ImageDraw.Draw(image);draw.rectangle((50,50,360,900),outline='black',width=4)
  result=speech_regions(image,[{'x':.12,'y':.17,'w':.2,'h':.04,'original':'THE FIRST SENTENCE','confidence':95},{'x':.14,'y':.57,'w':.2,'h':.04,'original':'ANOTHER SENTENCE','confidence':95}]);self.assertEqual(len(result),2);self.assertTrue(all('FIRST ANOTHER' not in r['original'] for r in result))

 def test_refinement_cannot_silently_drop_a_negation_from_the_source(self):
  import tempfile
  from unittest.mock import patch
  from types import SimpleNamespace
  from reader_translation import refine_bubbles
  regions=[{'x':.1,'y':.1,'w':.3,'h':.3,'original':'I DO NOT BELIEVE IN ALIENS'}]
  tsv='page_num\tline_num\tconf\ttext\n'+''.join('1\t1\t95\t'+w+'\n' for w in ['BELIEVE','IN','ALIENS'])
  with tempfile.TemporaryDirectory() as work,patch('reader_translation.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=tsv.encode())):
   result=refine_bubbles(Image.new('RGB',(300,500),'white'),regions,work)
  self.assertIn('NOT',result[0]['original']);self.assertEqual(result[0]['placement'],'note');self.assertTrue(result[0]['ocrUncertain'])
