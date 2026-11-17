"""Contract tests for the eighth direct-source migration batch."""

import csv
from base64 import b64encode
from io import BytesIO
import json
from pathlib import Path
from runpy import run_path
from unittest import TestCase
from unittest.mock import Mock
from urllib.parse import urlsplit

from PIL import Image

import manga_alphapolis
import manga_clipstudio
import manga_clipstudio_sources
import manga_coronaex
import manga_drecomics
import manga_ebookrenta
import manga_flower_comics
import manga_hakusensha
import manga_honto
import manga_mangaplaza
from manga_speedbinb import grant
from manga_webcomics import param
from source_parser import SourceError

ROOT = Path(__file__).resolve().parents[1]
MODULES = (manga_clipstudio_sources, manga_hakusensha, manga_honto, manga_mangaplaza, manga_ebookrenta,
           manga_drecomics, manga_flower_comics, manga_alphapolis, manga_coronaex)
PROFILES = tuple(profile for module in MODULES for profile in module.SOURCES)


class EighthBatchTests(TestCase):
    def test_inventory_and_endpoint_registration(self):
        candidates, active = run_path(str(ROOT / 'scripts/probe-native-source-batch.py'))['candidates']()
        with (ROOT / 'docs/native-source-inventory.csv').open(newline='', encoding='utf-8') as file:
            rows = {row['source_id']: row for row in csv.DictReader(file)}
        self.assertEqual(len(PROFILES), 10)
        self.assertEqual(len({rows[adapter.SOURCE_ID]['package'] for adapter in PROFILES}), 10)
        for adapter in PROFILES:
            row = rows[adapter.SOURCE_ID]
            self.assertNotIn(adapter.SOURCE_ID, active)
            self.assertIs(type(adapter), type(candidates[adapter.SOURCE_ID]))
            self.assertEqual((adapter.NAME, adapter.LANGUAGE), (row['source'], row['language']))
            self.assertTrue(row['evidence'].endswith('#восьмая-партия'))

    def test_clip_studio_retries_vertical_and_keeps_both_halves(self):
        url = 'https://viewer.example.org/csr/view.cgi'
        stable = 'https://books.example.org/chapter/10'

        def document(target, **options):
            self.assertTrue(manga_clipstudio.cgi_route(target, options['headers']['Referer']))
            if param(target, 'mode') == '999':
                code = '2005' if param(target, 'vm') == '4' else '1000'
                payload = f'<Result><Code>{code}</Code><Content>secret-issue-key</Content></Result>'
            elif param(target, 'mode') == '7':
                payload = ('<Face><TotalPage>2</TotalPage><Scramble><Width>2</Width><Height>2</Height></Scramble>'
                           '<OptionId>Omf</OptionId><DoublePagesMap>0</DoublePagesMap><Binding>0</Binding></Face>')
            else:
                raise AssertionError(target)
            return payload, target, {}

        http = Mock(document=Mock(side_effect=document))
        operations = manga_clipstudio.comic_pages(http, url, 'seed', '0_1')
        refs = manga_clipstudio.unique_links(stable, operations)
        self.assertEqual(http.document.call_count, 3)
        self.assertEqual([grant(ref)[2].half for ref in refs], ['R', 'L', ''])
        self.assertEqual(len(set(refs)), 3)
        self.assertFalse(any('secret-issue-key' in ref for ref in refs))
        self.assertEqual({param(grant(ref)[2].target, 'vm') for ref in refs}, {'2'})

    def test_clip_studio_public_authority_and_tile_crop(self):
        url = ('https://viewer.example.org/csr/view.cgi?'
               'mode=8&reqtype=0&vm=4&param=issued&file=0002.xml')
        self.assertFalse(manga_clipstudio.cgi_route(url, 'https://other.example.org/csr/'))
        self.assertFalse(manga_clipstudio.epub_route('https://viewer.example.org/unknown', 'test-token'))
        with self.assertRaises(SourceError):
            manga_clipstudio.xml('<!DOCTYPE test SYSTEM "file:///etc/passwd"><test/>')
        raw = BytesIO()
        bitmap = Image.new('RGB', (16, 8), 'blue')
        bitmap.paste('red', (0, 0, 8, 8))
        bitmap.save(raw, 'PNG')
        image = manga_clipstudio.arrange(raw.getvalue(), 1, 2, [1, 0], 'L')
        with Image.open(BytesIO(image)) as tiled:
            self.assertEqual(tiled.size, (8, 8))
            self.assertEqual(tiled.getpixel((3, 2)), (0, 0, 255))

    def test_alphapolis_form_owned_by_title_and_chapter(self):
        root = manga_alphapolis.SCRIPT
        title = root + '/12'
        chapter = title + '/32'
        body = {'manga_sele_id': 12, 'episode_no': 32, 'hide_page': False, 'preview': False, 'resolution': 'standard'}
        def allowed(value):
            return manga_alphapolis.public_transport(root + '/viewer.json', 'POST', json.dumps(value).encode(),
                                                    chapter, 'alphapolis-guest-form')
        self.assertTrue(allowed(body))
        self.assertFalse(allowed({**body, 'episode_no': 33}))
        self.assertFalse(allowed({**body, 'preview': True}))
        self.assertFalse(manga_alphapolis.public_transport(root + '/episodes.json', 'POST', b'{"manga_id":99}',
                                                          title, 'alphapolis-guest-form'))

    def test_open_catalogues_limit_transport_to_read_operations(self):
        key = manga_hakusensha.READER + '/keys/free/t1?viewer=bs&platform=web'
        parts = urlsplit(key)
        self.assertTrue(manga_hakusensha.public_api(parts.netloc, parts.path, parts.query))
        self.assertFalse(manga_hakusensha.public_api(parts.netloc, parts.path.replace('free', 'bookshelf'), parts.query))
        self.assertTrue(manga_drecomics.viewer_form(manga_drecomics.API + '/viewer/volumes/26/trial-session', b''))
        self.assertFalse(manga_drecomics.viewer_form(manga_drecomics.API + '/login', b''))
        self.assertFalse(manga_honto.public_form(manga_honto.ROOT + '/view_interface.php',
                                                {'className': 'OrdDownloadListPc', 'prdId': '123456'}))

    def test_corona_and_renta_tile_orders(self):
        packed = b64encode(bytes((2, 1, 1, 0))).decode()
        self.assertEqual(manga_coronaex.read_grid(packed), bytes((2, 1, 1, 0)))
        with self.assertRaises(SourceError):
            manga_coronaex.read_grid(b64encode(bytes((2, 1, 1, 1))).decode())
        for page, title in ((2, 17003), (100, 5140)):
            self.assertEqual(sorted(manga_ebookrenta.layout(page, title)), list(range(49)))
