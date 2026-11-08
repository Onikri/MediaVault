"""Honey Manga and Zenko API answers captured from the Oracle VM on 2026-11-08."""
import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import manga_ukrainian as uk
from source_parser import PublicHttp, SourceError
F=Path(__file__).parent/'fixtures'/'manga_uk'
read=lambda name:(F/name).read_text(encoding='utf-8')
ZENKO_CHAPTER=read('zenko_chapter_id').strip()


class Http(PublicHttp):
    def document(self,value,*,method='GET',data=None,headers=None,**_):
        routes={'search.api.honey-manga.com.ua/v2/manga/pattern':'honey_search.json','data.api.honey-manga.com.ua/manga/':'honey_manga.json',
                'data.api.honey-manga.com.ua/v2/chapter/cursor-list':'honey_chapters.json','data.api.honey-manga.com.ua/chapter/frames/':'honey_frames.json',
                'api.zenko.online/titles?':'zenko_search.json','api.zenko.online/titles/34/chapters':'zenko_chapters.json',
                'api.zenko.online/titles/34':'zenko_title.json','api.zenko.online/chapters/':'zenko_chapter.json'}
        for key,name in routes.items():
            if key in value:return read(name),value,'application/json'
        raise SourceError('offline fixture '+value)


class UkrainianMangaTests(unittest.TestCase):
    def test_honey_search_inspect_and_free_pages(self):
        found=uk.honey_search('One Piece Fan Letter',Http())
        self.assertIn('One Piece Fan Letter',found[0]['aliases'])
        self.assertEqual(found[0]['language'],'uk')
        title=uk.honey_inspect(found[0]['url'],Http())
        self.assertEqual(len(title['episodes']),1)
        chapter=uk.honey_inspect(title['episodes'][0]['url'],Http())
        self.assertGreater(len(chapter['pages']),5)
        self.assertTrue(chapter['pages'][0].startswith(uk.HONEY_IMAGES))

    def test_honey_chapter_post_body_is_the_only_allowed_shape(self):
        body=json.dumps({'page':1,'pageSize':100,'sortOrder':'ASC','mangaId':'2eab6a0e-8880-4128-8609-b96e68f254a4'}).encode()
        with self.assertRaises(SourceError):
            PublicHttp().document('https://data.api.honey-manga.com.ua/v2/chapter/cursor-list',method='POST',data=body+b' ')

    def test_zenko_comics_chapters_volumes_and_pages(self):
        found=uk.zenko_search('Surviving the Game as a Barbarian',Http())
        barbarian=next(r for r in found if r['url'].endswith('/titles/34'))
        self.assertEqual(barbarian['format'],'manhwa')
        title=uk.zenko_inspect(barbarian['url'],Http())
        self.assertGreater(len(title['episodes']),10)
        self.assertTrue(all(e['language']=='uk' for e in title['episodes']))
        chapter=uk.zenko_inspect('https://zenko.online/titles/34?mv_chapter='+ZENKO_CHAPTER,Http())
        self.assertTrue(chapter['pages'] and chapter['pages'][0].startswith(uk.ZENKO_IMAGES))

    def test_zenko_chapter_name_format(self):
        self.assertEqual(uk.zenko_chapter('1@#%&;№%#&**#!@0.5@#%&;№%#&**#!@Пролог'),(1,'0.5','Пролог'))
        self.assertEqual(uk.zenko_chapter('2@#%&;№%#&**#!@14'),(2,'14',''))


if __name__=='__main__':unittest.main()
