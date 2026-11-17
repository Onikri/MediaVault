"""Contract tests for the tenth migration batch (Suwayomi-only extensions, package C1)."""

import csv
from io import BytesIO
from pathlib import Path
from unittest import TestCase
from urllib.parse import urlsplit

from PIL import Image

import manga_comicfuz
import manga_creator_feeds
import manga_mangaz
import manga_mehgazone
import manga_native_registry
import manga_ninth_routes
import manga_pawchive
import manga_tenth_sources
from source_parser import SourceError

ROOT = Path(__file__).resolve().parents[1]


def inventory():
    with (ROOT / 'docs/native-source-inventory.csv').open(newline='', encoding='utf-8') as file:
        return {row['source_id']: row for row in csv.DictReader(file)}


class TenthBatchTests(TestCase):
    def test_profiles_match_the_installed_inventory(self):
        rows = inventory()
        self.assertEqual(len(manga_tenth_sources.SOURCES), 4)
        for adapter in manga_tenth_sources.SOURCES:
            row = rows[adapter.SOURCE_ID]
            self.assertEqual((adapter.NAME, adapter.LANGUAGE), (row['source'], row['language']))
            self.assertIs(manga_native_registry.profiles()[adapter.SOURCE_ID], adapter)

    def test_routes_accept_only_the_extension_requests(self):
        body = manga_comicfuz.request_body('search', 'ゆるキャン', 2)
        route = manga_ninth_routes.prepare('n9:comicfuz', manga_comicfuz.API + 'search', 'POST', body, {})
        self.assertEqual(route.data, body)
        self.assertEqual(route.headers['Content-Type'], 'application/protobuf')
        for name, data in (('search', body + b'\x28\x01'), ('admin', body),
                           ('manga_viewer', manga_comicfuz.request_body('manga_detail', 5))):
            with self.assertRaises(SourceError):
                manga_ninth_routes.prepare('n9:comicfuz', manga_comicfuz.API + name, 'POST', data, {})
        with self.assertRaises(SourceError):
            manga_ninth_routes.prepare('n9:comicfuz', manga_comicfuz.API + 'search', 'GET', None, {})
        manga_ninth_routes.prepare('n9:mangaz', 'https://vw.mangaz.com/virgo/view/44281', 'GET', None, {})
        with self.assertRaises(SourceError):
            manga_ninth_routes.prepare('n9:mangaz', 'https://r18.mangaz.com/attention/r18/yes', 'GET', None, {})
        image = 'https://n4.pawchive.pw/data/264/f1/' + 'a' * 64 + '.png'
        manga_ninth_routes.prepare('n9:pawchive-image', image, 'GET', None, {})
        with self.assertRaises(SourceError):
            manga_ninth_routes.prepare('n9:pawchive-image', 'https://pawchive.pw/api/v1/creators', 'GET', None, {})

    def test_public_apis(self):
        self.assertTrue(manga_mehgazone.public_api('bodysuit23.mehgazone.com', '/wp-json/wp/v2/posts',
                                                   'per_page=100&page=3&_fields=id,title,date_gmt,excerpt'))
        self.assertTrue(manga_mehgazone.public_api('bodysuit23.mehgazone.com', '/wp-json/wp/v2/posts',
                                                   'per_page=1&include=6085&_fields=link,content,excerpt,date,title'))
        self.assertFalse(manga_mehgazone.public_api('bodysuit23.mehgazone.com', '/wp-json/wp/v2/users', ''))
        self.assertFalse(manga_mehgazone.public_api('evil.com', '/wp-json/wp/v2/posts',
                                                    'per_page=100&page=1&_fields=id,title,date_gmt,excerpt'))
        self.assertTrue(manga_creator_feeds.public_api('pawchive.pw', '/api/v1/creators', ''))
        self.assertTrue(manga_creator_feeds.public_api('pawchive.pw', '/api/v1/fanbox/user/1/post/2', ''))

    def test_comic_fuz_encodes_the_extension_messages(self):
        self.assertEqual(manga_comicfuz.request_body('manga_detail', 1818), bytes.fromhex('0a021802') + b'\x10\x9a\x0e')
        viewer = manga_comicfuz.request_body('manga_viewer', 1)
        self.assertEqual(viewer, bytes.fromhex('0a021802') + bytes.fromhex('1001' '1800' '2204' '08001000' '2a020801'))
        self.assertTrue(manga_comicfuz.accepted_body('manga_viewer', viewer))

    def test_mehgazone_keeps_comics_on_separate_subdomains(self):
        adapter = manga_mehgazone.SOURCES[0]
        one, two = 'https://bodysuit23.mehgazone.com/', 'https://a-kats-god-awful-blessing.mehgazone.com/'
        self.assertTrue(adapter.is_title(one) and adapter.is_title(two))
        self.assertNotEqual(adapter.title_identity(one), adapter.title_identity(two))
        chapter = adapter.saved_chapter({'url': 'https://bodysuit23.mehgazone.com/?p=6085'}, '', one)
        self.assertTrue(adapter.is_chapter(chapter))
        self.assertTrue(adapter.saved_chapter_matches(chapter, one))
        self.assertFalse(adapter.saved_chapter_matches(chapter, two))
        self.assertEqual(adapter.site_link('https://www.mehgazone.com.evil.com/'), '')

    def test_mangaz_restores_saved_ids_and_descrambles_tiles(self):
        adapter = manga_mangaz.SOURCES[0]
        title = adapter.saved_title_url('44281')
        self.assertEqual(title, 'https://www.mangaz.com/series/detail/44281')
        chapter = adapter.saved_chapter({'url': '44285'}, '', title)
        self.assertEqual(urlsplit(chapter).path, '/virgo/view/44285')
        self.assertTrue(adapter.saved_chapter_matches(chapter, title))
        # Two 8x8 tiles stored side by side, stacked and swapped on the page.
        strip = Image.new('RGB', (16, 8), (255, 0, 0))
        strip.paste((0, 0, 255), (8, 0, 16, 8))
        raw = BytesIO()
        strip.save(raw, 'PNG')
        page = manga_mangaz.descramble(raw.getvalue(), 8, 16, ((0, 8, 0, 0, 8, 8), (0, 0, 8, 0, 8, 8)))
        with Image.open(BytesIO(page)) as result:
            top, bottom = result.getpixel((4, 4)), result.getpixel((4, 12))
        self.assertGreater(top[2], 200)
        self.assertGreater(bottom[0], 200)
        with self.assertRaises(SourceError):
            manga_mangaz.crops_from({'scramble': {'w': 10, 'h': 10, 'crops': [{'x': -1}]}})

    def test_pawchive_uses_the_file_shard_of_each_attachment(self):
        adapter = manga_pawchive.SOURCES[0]
        path = '/1ca/c1/' + 'c' * 64 + '.jpeg'
        post = {'file': {'path': path, 'server': 'https://n3.pawchive.pw'},
                'attachments': [{'path': path}, {'path': '/x/../etc'}]}
        self.assertEqual(adapter.files(post), ['https://n3.pawchive.pw/data' + path])
        post['file']['server'] = 'https://evil.example'
        self.assertEqual(adapter.files(post), ['https://file.pawchive.pw/data' + path])
