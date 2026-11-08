"""RanobeHub, Zenko and Smakolyky API answers captured from the VM on 2026-11-08."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import ranobe_sources as rs
from source_parser import PublicHttp, SourceError, public_url
F=Path(__file__).parent/'fixtures'/'ranobe'
read=lambda name:(F/name).read_text(encoding='utf-8')


class Http(PublicHttp):
    def document(self,value,*,headers=None,**_):
        public_url(value,resolve_dns=False)  # every request must pass the allowlist
        for key,name in {'ranobehub.org/api/search':'hub_search.json','ranobehub.org/api/books/206/chapters':'hub_chapters.json',
                         'ranobehub.org/api/chapters/':'hub_chapter.json','smakolykytl.site/api/user/projects/15/books':'smak_books.json',
                         'smakolykytl.site/api/user/projects':'smak_projects.json','smakolykytl.site/api/user/chapters/':'smak_chapter.json',
                         'api.zenko.online/titles?':'zenko_search.json','api.zenko.online/titles/2951/chapters':'zenko_chapters.json',
                         'api.zenko.online/titles/2951':'zenko_title.json','api.zenko.online/chapters/':'zenko_chapter.json'}.items():
            if key in value:return read(name),value,'application/json'
        raise SourceError('offline fixture '+value)


class RanobeTests(unittest.TestCase):
    def setUp(self):rs._cache.clear()

    def test_ranobehub_book_chapters_and_text(self):
        hit=next(rs._hub_search('Overlord',Http()))
        self.assertIn('Overlord',hit['aliases'])
        book=rs.inspect(hit['url'],Http())
        self.assertEqual(book['language'],'ru');self.assertEqual(len(book['episodes']),5)
        text=rs.chapter(book['episodes'][2]['url'],Http())
        self.assertGreater(len(text['paragraphs']),5)
        self.assertFalse(any('<' in p and '>' in p and 'img' in p for p in text['paragraphs']))

    def test_zenko_novel_and_smakolyky_ukrainian_text(self):
        zenko=rs.inspect('https://zenko.online/titles/2951',Http())
        self.assertEqual(zenko['language'],'uk');self.assertTrue(zenko['episodes'])
        first=rs.chapter('https://zenko.online/titles/2951?mv_chapter=49579',Http())
        self.assertTrue(any('завдання' in p for p in first['paragraphs']))
        smak=rs.inspect('https://smakolykytl.site/projects/15',Http())
        self.assertEqual(smak['title'],'86 - Вісімдесят шість');self.assertIn('86 - Eighty Six',smak['aliases'])
        text=rs.chapter(smak['episodes'][2]['url'],Http())
        self.assertEqual(text['paragraphs'][0],'<Запуск системи>')

    def test_search_matches_catalogue_aliases_only(self):
        from unittest.mock import patch
        with patch.object(rs,'PublicHttp',lambda **_:Http()):
            value=rs.search({'title':'Только я повышаю уровень','aliases':['Solo Leveling'],'kind':'ranobe'},'uk')
        self.assertEqual({r['provider'] for r in value['results']},{'zenko-novel'})
        self.assertTrue(all(r['language']=='uk' for r in value['results']))

    def test_paragraph_cleaning(self):
        self.assertEqual(rs.html_paragraphs('<p>Один<br>Два</p><script>x()</script><p>=====</p><div><p>Три</p></div>'),['Один','Два','Три'])
        doc='[{"type":"paragraph","content":[{"type":"text","text":"А"},{"type":"hardBreak"},{"type":"text","text":"Б"}]}]'
        self.assertEqual(rs.tiptap_paragraphs(doc),['А','Б'])

    def test_unknown_links_are_rejected(self):
        with self.assertRaises(SourceError):rs.inspect('https://example.com/ranobe/1')


if __name__=='__main__':unittest.main()
