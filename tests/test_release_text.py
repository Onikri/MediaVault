import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from source_parser import decode_document
from release_calendar import collapse


class ReleaseText(unittest.TestCase):
    def test_cp1251_page_without_header_charset_is_readable(self):
        raw='<html><body><h2>Токийские мстители</h2></body></html>'.encode('cp1251')
        self.assertIn('Токийские мстители',decode_document(raw,None))
        self.assertIn('Токийские мстители',decode_document(raw,'ISO-8859-1'))

    def test_meta_charset_and_utf8_are_respected(self):
        self.assertIn('Свадьба','<meta charset="windows-1251"><p>Свадьба</p>'.encode('cp1251').decode('cp1251'))
        self.assertIn('Свадьба',decode_document('<meta charset="windows-1251"><p>Свадьба</p>'.encode('cp1251')))
        self.assertIn('Свадьба',decode_document('<p>Свадьба</p>'.encode('utf-8')))

    def test_entities_unescaped_and_reposts_collapsed(self):
        base={'provider':'AnimeLayer','url':'https://x/1','episode':None,'kind':'translation','datePrecision':'time'}
        rows=collapse([{**base,'title':'Demons&amp;#039; Crest','date':'2026-11-06T23:03:34+03:00'},{**base,'title':'Demons&#039; Crest','date':'2026-11-06T23:03:47+03:00'}])
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['title'],"Demons' Crest");self.assertEqual(rows[0]['date'],'2026-11-06T23:03:47+03:00')


if __name__=='__main__':unittest.main()
