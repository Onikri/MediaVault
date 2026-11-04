import base64
from io import BytesIO
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from fastapi import HTTPException
from chapter_thumbnails import ChapterThumbnails,thumbnail


def page():
    output=BytesIO()
    with Image.new('RGB',(600,4000),'#a4b5c6') as image:image.save(output,'PNG')
    return output.getvalue()


class ChapterThumbnailTests(unittest.TestCase):
    def test_http_route_requires_owner_before_fetching_any_page(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from chapter_thumbnails import install
        app=FastAPI()
        def owner():raise HTTPException(401,'Required')
        install(app,owner)
        with TestClient(app) as client,patch('chapter_thumbnails.first_image') as upstream:
            self.assertEqual(client.post('/manga/thumbnail',json={'url':'https://mangapill.com/chapters/1'}).status_code,401)
            upstream.assert_not_called()

    def test_tall_page_is_a_small_top_panel_not_a_resized_original(self):
        raw=page();result=thumbnail(raw)
        with Image.open(BytesIO(result)) as image:
            self.assertEqual(image.size,(240,360));self.assertEqual(image.format,'JPEG')
        self.assertNotEqual(raw,result)

    def test_cache_survives_restart_is_owner_scoped_and_contains_only_small_jpeg(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder,patch('chapter_thumbnails.first_image',return_value=page()) as upstream:
            cache=ChapterThumbnails(folder);result=cache.get('owner-a','https://mangapill.com/chapters/1')
            self.assertFalse(result['cached']);self.assertTrue(result['image'].startswith('data:image/jpeg;base64,'))
            restored=ChapterThumbnails(folder);self.assertTrue(restored.get('owner-a','https://mangapill.com/chapters/1')['cached']);self.assertEqual(upstream.call_count,1)
            restored.get('owner-b','https://mangapill.com/chapters/1');self.assertEqual(upstream.call_count,2)
            for path in Path(folder).iterdir():
                self.assertEqual(path.suffix,'.jpg');self.assertLess(path.stat().st_size,100000)
                with Image.open(path) as image:self.assertLessEqual(image.width,240);self.assertLessEqual(image.height,360)

    def test_failure_does_not_poison_other_chapters_or_leak_work_slots(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=ChapterThumbnails(folder)
            with patch('chapter_thumbnails.first_image',return_value=b'not an image'):
                with self.assertRaises(HTTPException):cache.get('a','https://mangapill.com/chapters/bad')
            self.assertEqual(cache.pending,{})
            with patch('chapter_thumbnails.first_image',return_value=page()):self.assertTrue(cache.get('a','https://mangapill.com/chapters/good')['image'])

    def test_saturation_returns_429_instead_of_creating_an_unbounded_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=ChapterThumbnails(folder);cache.slots.acquire();cache.slots.acquire()
            try:
                with self.assertRaises(HTTPException) as caught:cache.get('a','https://mangapill.com/chapters/1')
                self.assertEqual(caught.exception.status_code,429);self.assertEqual(cache.pending,{})
            finally:cache.slots.release();cache.slots.release()
