"""HentaiChan parser contracts with neutral generated HTML and tiny PNG pages."""
import base64
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from source_parser import SourceError
from manga_hentaichan import SOURCE,ROOT,parse_search,parse_pages,inspect
from manga_sources import site_for
from manga_download import download_chapter
import manga_discovery

BASE=ROOT
MANGA=BASE+'/manga/123-neutral-story.html'
READER=BASE+'/online/123-neutral-story.html?page=1'
RELATED=BASE+'/related/123-neutral-story.html'
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aSdoAAAAASUVORK5CYII=')


class Http:
    def __init__(self,docs):self.docs=docs;self.calls=[]
    def document(self,url,**kw):
        self.calls.append(url)
        if url not in self.docs:raise AssertionError('Unexpected fixture request '+url)
        return self.docs[url],url,{}
    def download(self,url,target,**kw):
        self.calls.append(url);Path(target).write_bytes(PNG);return len(PNG)


class HentaiChanTests(unittest.TestCase):
    def test_search_and_confirmed_mirror(self):
        rows=parse_search('''<div class="content_row"><div class="manga_images"><img src="https://img.example.com/cover.jpg"></div>
        <a class="title_link" href="https://x17.h-chan.me/manga/123-neutral-story.html">Нейтральная история / Neutral story</a></div>
        <div class="content_row"><a class="title_link" href="https://evil.example/manga/456-other.html">Bad link</a></div>''','https://hentaichan.live/')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['sourceId'],SOURCE['id'])
        self.assertTrue(rows[0]['adult']);self.assertIn('Neutral story',rows[0]['aliases'])
        self.assertEqual(site_for(MANGA).family,'hentaichan')
    def test_series_pagination_preserves_chapter_and_translator(self):
        http=Http({MANGA:'<a class="title_top_a">История</a><img id="cover" src="/covers/one.jpg">',
          RELATED:'''<h1>Все главы</h1><div class="related_info"><h2><a href="/manga/124-chapter.html">Том 2 Глава 3.5</a></h2><span class="translation"><a>Team A</a></span></div><a href="?offset=10">Next</a>''',
          RELATED+'?offset=10':'''<div class="related_info"><h2><a href="/manga/125-chapter.html">Том 2 Глава 4</a></h2></div><a href="?offset=0">Prev</a>''',
          RELATED+'?offset=0':'<div class="related_info"><h2><a href="/manga/124-chapter.html">Том 2 Глава 3.5</a></h2><span class="translation"><a>Team A</a></span></div>'})
        value=inspect(MANGA,http)
        self.assertEqual([x['number'] for x in value['episodes']],[3.5,4])
        self.assertEqual(value['episodes'][0]['translator'],'Team A')
        self.assertEqual(value['episodes'][0]['season'],2)
        self.assertEqual(value['pages'],[],'metadata does not fetch every chapter reader')
        self.assertTrue(all('/online/' in c['url'] for c in value['episodes']))
    def test_similar_titles_are_not_chapters(self):
        http=Http({MANGA:'<a class="title_top_a">Одна история</a>',RELATED:'<title>Похожая манга</title><div class="related_info"><h2><a href="/manga/999-unrelated.html">Другая история Глава 99</a></h2></div>'})
        value=inspect(MANGA,http)
        self.assertEqual(len(value['episodes']),1);self.assertEqual(value['episodes'][0]['url'],READER)
    def test_reader_and_cbz(self):
        html='''<a class="title_top_a">История Глава 2</a><script>var data={"thumbs":[],"fullimg":['https://img.example.com/1.png','https://img.example.com/2.png',]};createGallery(data)</script>'''
        http=Http({READER:html});value=inspect(READER,http)
        self.assertEqual(value['episodes'][0]['number'],2);self.assertEqual(len(value['pages']),2)
        with tempfile.TemporaryDirectory() as directory:
            archive=download_chapter(READER,directory,http)
            with zipfile.ZipFile(archive) as cbz:
                self.assertEqual(cbz.namelist(),['0001.png','0002.png'])
                self.assertEqual(cbz.read('0001.png'),PNG)
    def test_page_data_and_redirect_safety(self):
        for data in ['[__import__("os").system("bad")]','["http://127.0.0.1/page.png"]','["https://img.example.com/video.mp4"]']:
            with self.subTest(data=data),self.assertRaises(SourceError):parse_pages('var data={"fullimg":'+data+'}',READER)
        class Redirect:
            def document(self,url):return '<h1>Redirect</h1>','https://evil.example/manga/123-file.html',{}
        with self.assertRaises(SourceError):inspect(MANGA,Redirect())
    def test_discovery_lists_native_and_dispatches_it(self):
        with patch.object(manga_discovery.bridge,'sources',return_value=[]),patch('manga_source_health.states',return_value={}):
            value=manga_discovery.source_list('ru','HentaiChan')
            self.assertEqual(len(value['sources']),1);self.assertTrue(value['sources'][0]['adult'])
        row=parse_search('<div class="content_row"><a class="title_link" href="'+MANGA+'">Neutral story</a></div>',BASE)[0]
        with patch('manga_hentaichan.search',return_value=[row]) as search:
            result=manga_discovery.search_source(SOURCE,'Neutral story')
            self.assertEqual(result,[row]);search.assert_called_once()

if __name__=='__main__':unittest.main()
