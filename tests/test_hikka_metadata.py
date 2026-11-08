"""Hikka shapes as returned on 2026-11-08 (trimmed)."""
import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import hikka_metadata as h
from source_parser import PublicHttp, SourceError, public_url


class Http(PublicHttp):
    def document(self,value,*,headers=None,**_):
        public_url(value,resolve_dns=False)
        if '/integrations/mal/anime/20' in value:return json.dumps({'slug':'naruto-d8ec41','title_ua':'Наруто'}),value,'application/json'
        if value.endswith('/anime/naruto-d8ec41'):return json.dumps({'synopsis_ua':'Демон **Дев\'ятихвостий Лис** напав на [Коноху](https://hikka.io/x).\n\nДжерело [MyAnimeList](https://myanimelist.net/x)','translated_ua':True}),value,'application/json'
        raise SourceError('404')


class HikkaTests(unittest.TestCase):
    def setUp(self):h._cache.clear()

    def test_ukrainian_title_and_clean_synopsis(self):
        value=h.ukrainian('tv','20',Http())
        self.assertEqual(value['title'],'Наруто')
        self.assertEqual(value['description'],"Демон Дев'ятихвостий Лис напав на Коноху.")
        self.assertEqual(value['url'],'https://hikka.io/anime/naruto-d8ec41')

    def test_unknown_title_and_bad_input(self):
        self.assertIsNone(h.ukrainian('anime','999',Http()))
        with self.assertRaises(SourceError):h.ukrainian('anime','../x',Http())
        with self.assertRaises(SourceError):h.ukrainian('book','1',Http())


if __name__=='__main__':unittest.main()
