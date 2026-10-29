"""Sanitized HTML contracts; real website/image runs are recorded separately."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from manga_novelcool import inspect
from source_parser import SourceError

ROOT='https://ru.novelcool.com'
BOOK=ROOT+'/novel/Наруто.html'
CHAPTER=ROOT+'/chapter/1-0/123/'
OPTIONS='<select><option value="'+CHAPTER+'">1 - 0 Начало</option></select>'

class Http:
    def __init__(self,rows):self.rows=rows;self.calls=[]
    def document(self,url):self.calls.append(url);return self.rows[url],url,{}

class NovelCoolTests(unittest.TestCase):
    def test_title_chapter_zero_fraction_and_volume_are_preserved(self):
        text='<h1 class="bookinfo-title">Наруто</h1><div class="chp-item"><a href="/chapter/1-0/123/" title="1 - 0 Начало"></a></div><div class="chp-item"><a href="/chapter/2-12.5/124/" title="2 - 12.5 Экстра"></a></div>'
        data=inspect(BOOK,Http({BOOK:text}))
        self.assertEqual(data['title'],'Наруто');self.assertEqual([(r['season'],r['number']) for r in data['episodes']],[(1,0),(2,12.5)])
    def test_pages_follow_same_chapter_only_and_exclude_logo(self):
        first=ROOT+'/chapter/1-0/123-10-1.html';second=ROOT+'/chapter/1-0/123-10-11.html'
        heading='<a href="/novel/Наруто.html">Наруто</a>'+OPTIONS
        http=Http({first:heading+'<img src="https://images.example/logo.png"><img class="manga_pic" src="https://images.example/1.webp"><script>next_page="'+second+'";</script>',second:heading+'<img class="manga_pic" src="https://images.example/2.webp"><script>next_page="'+ROOT+'/chapter/1-1/124-10-1.html";</script>'})
        value=inspect(CHAPTER,http)
        self.assertEqual(value['pages'],['https://images.example/1.webp','https://images.example/2.webp'])
        self.assertEqual(http.calls,[first,second]);self.assertEqual(value['episodes'][0]['number'],0)
    def test_external_navigation_images_and_title_redirects_are_rejected(self):
        first=ROOT+'/chapter/1-0/123-10-1.html';heading='<a href="/novel/Наруто.html">Наруто</a>'+OPTIONS
        for tail in ['<img class="manga_pic" src="https://images.example/1.webp"><script>next_page="https://evil.example/chapter/1-0/123-10-11.html";</script>','<img class="manga_pic" src="https://127.0.0.1/private">']:
            http=Http({first:heading+tail})
            with self.assertRaises(SourceError):inspect(CHAPTER,http)
            self.assertEqual(http.calls,[first])
        for value in ['http://ru.novelcool.com/novel/A.html','https://evil.example/novel/A.html',BOOK+'?next=https://evil.example']:
            with self.assertRaises(SourceError):inspect(value,Http({}))
    def test_page_limit_does_not_return_a_silently_truncated_chapter(self):
        first=ROOT+'/chapter/1-0/123-10-1.html'
        text='<a href="/novel/Наруто.html">Наруто</a>'+OPTIONS+''.join('<img class="manga_pic" src="https://images.example/'+str(i)+'.webp">' for i in range(501))
        with self.assertRaisesRegex(SourceError,'500'):inspect(CHAPTER,Http({first:text}))
