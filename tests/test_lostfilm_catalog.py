"""LostFilm public catalogue answer captured from the VM on 2026-11-08."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from lostfilm_catalog import parse_rows, catalog
from source_parser import PublicHttp, SourceError
FIXTURE=(Path(__file__).parent/'fixtures'/'players'/'lostfilm_catalog.json').read_text(encoding='utf-8')


class LostFilmTests(unittest.TestCase):
    def test_rows_have_russian_and_original_titles_and_posters(self):
        rows=parse_rows(FIXTURE)
        self.assertGreaterEqual(len(rows),5)
        first=rows[0]
        self.assertTrue(first['title'] and first['original'] and first['url'].startswith('https://www.lostfilm.tv/series/'))
        self.assertTrue(all(r['cover']=='' or r['cover'].startswith('https://www.lostfilm.tv/Static/Images/') for r in rows))

    def test_only_the_catalogue_form_may_be_posted(self):
        http=PublicHttp()
        with self.assertRaises(SourceError):
            http.document('https://www.lostfilm.tv/ajaxik.php',method='POST',data={'act':'users','type':'login','mail':'x','pass':'y','rem':'1'})

    def test_catalogue_uses_the_public_form(self):
        class Http(PublicHttp):
            def document(self,value,*,method='GET',data=None,headers=None,**_):
                assert method=='POST' and data=={'act':'serial','type':'search','o':'10','s':'2','t':'0'}
                return FIXTURE,value,'application/json'
        self.assertTrue(catalog('alpha',10,http=Http())['items'])


if __name__=='__main__':unittest.main()
