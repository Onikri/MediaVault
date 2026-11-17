import csv
import base64
from io import BytesIO
import json
from pathlib import Path
import runpy
import struct
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

from bs4 import BeautifulSoup
from PIL import Image

import manga_additional_catalogues
import manga_alpha_manga
import manga_catalogue_api_ports
import manga_comic_museum
import manga_gallery_archive_ports
import manga_klto9
import manga_luscious_native
import manga_mangaplus
import manga_mangamee
import manga_manta_native
import manga_niadd_novelcool
import manga_omega
import manga_pandachaika
import manga_public_zip
import manga_rinko
import manga_scan_api_ports
import manga_simply_native
import manga_sixth_profiles
import manga_small_readers
import manga_speedbinb as speed
import manga_speedbinb_sources
import manga_toonlook
import manga_unicomics
import manga_webnex
import manga_webtoons_native
import manga_wordpress_locales
import manga_yellownote
from manga_page_media import fetch_page, page_reference
from source_parser import SourceError, public_url


ROOT = Path(__file__).resolve().parents[1]
PROFILES = (*manga_speedbinb_sources.SOURCES, *manga_webtoons_native.SOURCES,
            *manga_niadd_novelcool.SOURCES, *manga_sixth_profiles.SOURCES,
            *manga_wordpress_locales.SOURCES, *manga_simply_native.SOURCES,
            *manga_luscious_native.SOURCES, *manga_additional_catalogues.SOURCES,
            *manga_pandachaika.SOURCES, *manga_toonlook.SOURCES, *manga_alpha_manga.SOURCES,
            *manga_catalogue_api_ports.SOURCES, *manga_gallery_archive_ports.SOURCES,
            *manga_klto9.SOURCES, *manga_mangaplus.SOURCES, *manga_small_readers.SOURCES,
            *manga_scan_api_ports.SOURCES, *manga_manta_native.SOURCES, *manga_mangamee.SOURCES,
            *manga_comic_museum.SOURCES, *manga_omega.SOURCES, *manga_rinko.SOURCES,
            *manga_unicomics.SOURCES, *manga_webnex.SOURCES, *manga_yellownote.SOURCES)


def fixture(routes):
    def document(url, **kwargs):
        value = routes[url]
        return value if isinstance(value, str) else json.dumps(value), url, {}

    return Mock(document=Mock(side_effect=document), deadline=None)


def encode_table(cid, key, values):
    state = sum(ord(char) << (index % 16) for index, char in enumerate(f'{cid}:{key}')) & 0x7fffffff
    encoded = []
    for char in json.dumps(values, separators=(',', ':')):
        state = state >> 1 ^ (1210056708 & -(state & 1))
        encoded.append(chr(32 + (ord(char) - 32 - state % 94) % 94))
    return ''.join(encoded)


def wire_integer(value):
    data = bytearray()
    while value >= 128:
        data.append((value & 127) | 128)
        value >>= 7
    data.append(value)
    return bytes(data)


def wire_field(number, value):
    if isinstance(value, int):
        return wire_integer(number << 3) + wire_integer(value)
    if isinstance(value, str):
        value = value.encode()
    return wire_integer((number << 3) | 2) + wire_integer(len(value)) + value


class SixthBatchTests(TestCase):
    def source(self, name, language=None):
        profile = next(item for item in PROFILES if item.NAME == name and (language is None or language == item.LANGUAGE))
        profile.origin.interval = 0
        return profile

    def test_inventory_and_probe_use_consistent_identities(self):
        candidates, active = runpy.run_path(str(ROOT / 'scripts/probe-native-source-batch.py'))['candidates']()
        with (ROOT / 'docs/native-source-inventory.csv').open(encoding='utf-8', newline='') as file:
            rows = {row['source_id']: row for row in csv.DictReader(file)}
        self.assertEqual(len(PROFILES), 128)
        self.assertEqual(len({rows[profile.SOURCE_ID]['package'] for profile in PROFILES}), 50)
        for profile in PROFILES:
            row = rows[profile.SOURCE_ID]
            self.assertEqual((profile.NAME, profile.LANGUAGE), (row['source'], row['language']))
            self.assertIs(type(candidates[profile.SOURCE_ID]), type(profile))
            # Checked profiles go live through manga_native_activation.json.
            self.assertTrue(profile.SOURCE_ID not in active or profile.SOURCE_ID in __import__('manga_native_sources').activated_profiles())
            self.assertTrue(row['evidence'].endswith('#шестая-партия'))

    def test_unicomics_saved_chapter_and_deferred_image(self):
        profile = self.source('UniComics')
        root = profile.ROOT
        title = root + '/comics/series/example'
        reader = root + '/comics/online/example/issue/1'
        first_page = reader + '/2'
        http = fixture({
            title: f'<div class="series-main"><h1>Тест</h1></div><div class="comics-grid">'
                   f'<div class="comic-card"><span class="comic-title-ru">Тест №1</span>'
                   f'<div class="buttons-grid"><a href="{reader}">Читать</a></div></div></div>',
            reader: f'<select class="mobilePageSelector"><option value="{first_page}">2</option></select>',
            first_page: '<img class="image_online" src="/img/example.png">',
        })
        info = profile.inspect(title, http)
        chapter = info['episodes'][0]['url']
        pages = profile.inspect(chapter, http)['pages']
        self.assertEqual(pages, [first_page + '#mv_unicomics_page'])
        target, _, _, action = page_reference(pages[0])
        self.assertEqual((target, action), (first_page, 'unicomics-image'))
        self.assertEqual(manga_unicomics.lazy_image(http, target), root + '/img/example.png')

    def test_rinko_locked_chapter_and_ajax_scope(self):
        profile = self.source('Rinko Comics')
        title = profile.ROOT + '/comic/example/'
        http = fixture({title: '<div class="comic-info-upper"><h1>Example</h1></div>'
                        '<li class="chapter" data-reason="coins" data-permalink="/example-chapter-1/">'
                        '<a href="#"><span class="chapter-number">Chapter 1</span></a></li>'})
        chapter = profile.inspect(title, http)['episodes'][0]
        self.assertFalse(chapter['available'])
        form = {'action': 'load_more_chapters', 'nonce': 'public123', 'comic_id': '9', 'offset': '10'}
        self.assertTrue(manga_rinko.public_form(manga_rinko.AJAX, form, title))
        self.assertFalse(manga_rinko.public_form(manga_rinko.AJAX, form, 'https://example.com/comic/example/'))

    def test_speedbinb_selects_page_keys_and_preserves_order(self):
        cid, key = 'title-1', 'A' * 32
        referer = 'https://www.yomonga.com/titles/story/?cid=title-1&u0=1'
        info = 'https://www.yomonga.com/binb/sws/apis/bibGetCntntInfo.php'
        reader = BeautifulSoup(f'<div id="content" data-ptbinb="{info}"></div>', 'html.parser')
        data = {'result': 1, 'items': [{'ContentsServer': 'https://media.example/story/', 'ServerType': 2,
                                      'ViewMode': 2, 'ContentDate': '1750000000000',
                                      'ptbl': encode_table(cid, key, [''] * 8),
                                      'ctbl': encode_table(cid, key, [''] * 8)}]}
        http = fixture({
            f'{info}?u0=1&cid=title-1&k={key}&dmytime=1750000000000': data,
            'https://media.example/story/content': {'result': 1, 'ttx':
                '<t-case><t-img src="part/0002"><t-img src="part/0001"></t-case><t-nocase><t-img src="locked">'}
        })
        with patch.object(speed, 'shared_key', return_value=key), patch.object(speed, 'time', return_value=1750000000):
            pages = speed.reader_pages(http, reader, referer)
        self.assertEqual([urlsplit(page).path for page in pages], ['/story/img/part/0002', '/story/img/part/0001'])
        self.assertEqual(parse_qs(urlsplit(pages[0]).query), {'dmytime': ['1750000000000'], 'u0': ['1']})
        self.assertEqual(speed.grant(pages[0])[1:], (referer, ('', '')))
        with self.assertRaises(SourceError):
            page_reference(pages[0].replace('/0002?', '/9876?'))

    def test_speedbinb_ptimg_reorders_two_tiles_for_reader_and_archive(self):
        referer = 'https://webcomic.ohtabooks.com/story/'
        manifest = 'https://images.example/vol/a.ptimg.json'
        reader = BeautifulSoup(f'<div id="content"><span data-ptimg="{manifest}"></span></div>', 'html.parser')
        http = fixture({manifest: {'resources': {'i': {'src': 'a.png'}},
                                    'views': [{'width': 24, 'height': 12, 'coords': ['i:0,0+12,12>12,0', 'i:12,0+12,12>0,0']}]}})
        with Image.new('RGB', (24, 12), 'red') as image:
            image.paste((0, 0, 255), (12, 0, 24, 12))
            buffer = BytesIO()
            image.save(buffer, 'PNG')
        ref = page_reference(speed.reader_pages(http, reader, referer)[0])
        response = Mock(headers={'Content-Type': 'image/png'}, iter_content=Mock(return_value=[buffer.getvalue()]))
        http._open.return_value = (response, 'https://images.example/vol/a.png')
        output = fetch_page(http, ref, {})
        raw = output[0] if isinstance(output, tuple) else output
        with Image.open(BytesIO(raw)) as result:
            self.assertGreater(result.getpixel((5, 5))[2], 200)
            self.assertGreater(result.getpixel((19, 5))[0], 200)
        http._open.assert_called_once_with('https://images.example/vol/a.png', headers={'Referer': referer}, action='speedbinb-image')

    def test_speedbinb_grid_variants_validate_and_cover_canvas(self):
        alphabet = speed.ALPHABET
        layout = (alphabet[7] * 16) + alphabet
        w, h, pieces = speed.grid_f('=8-8-2-' + layout, '=8-8+2-' + layout, 521, 474)
        self.assertEqual((w, h, len(pieces)), (489, 442, 64))
        self.assertEqual(pieces[0], (2, 2, 62, 56, 0, 0))
        self.assertEqual(sum(piece[2] * piece[3] for piece in pieces), w * h)
        self.assertEqual(speed.grid_a('1-1-aa', '1-1-aa', 640, 480)[:2], (640, 480))
        with self.assertRaises(ValueError):
            speed.grid_f('=8-8-2-' + layout, '=8-8+2-' + 'A' * 80, 521, 474)

    def test_webtoon_reads_canvas_on_requested_locale(self):
        source = self.source('Webtoons.com', 'fr')
        title = source.ROOT + '/fr/canvas/story/list?title_no=42'
        head = source.ROOT + '/fr/canvas/story/episode-1/viewer?title_no=42&episode_no=77'
        other = head.replace('/fr/', '/en/')
        api = 'https://m.webtoons.com/api/v1/canvas/42/episodes?pageSize=10000&readingLanguageCode=fr'
        http = fixture({title: '<h1 class="subj">Story</h1>',
                        api: {'result': {'episodeList': [{'viewerLink': head, 'episodeTitle': 'Saison 1 Ep. 1'},
                                                        {'viewerLink': other, 'episodeTitle': 'Ep. 2'}]}},
                        head: '<div id="_imageList"><img data-url="https://cdn.example/1.jpg"></div>'})
        row = source.inspect(title, http)
        self.assertEqual((row['format'], len(row['episodes'])), ('webtoon', 1))
        self.assertEqual(source.inspect(row['episodes'][0]['url'], http)['pages'], ['https://cdn.example/1.jpg'])
        self.assertTrue(public_url(api, resolve_dns=False))
        with self.assertRaises(SourceError):
            public_url(api + '&account=1', resolve_dns=False)

    def test_niadd_keeps_original_reader_mode_for_saved_chapter(self):
        source = self.source('Niadd', 'en')
        with manga_niadd_novelcool.JUMP_LOCK:
            manga_niadd_novelcool.JUMPS.pop(source.SOURCE_ID, None)
        title = source.ROOT + '/original/story.html'
        chapter = source.ROOT + '/chapter/story/42.html'
        archive = title.removesuffix('.html') + '/chapters.html'
        ad = source.ROOT + '/go/rds/link'
        jump = 'https://jump.example/reader?cid=42&type=ogniadd'
        http = fixture({
            title: f'<h1 class="book-headline-name">Story</h1><a href="{ad}">Read</a>',
            archive: f'<ul class="chapter-list"><li><a class="hover-underline" href="{chapter}"><span class="chp-title">Chapter 1</span></a></li></ul>',
            ad: "<script>document.location='https://jump.example/reader?cid=17';</script>",
            jump: '<script>const reader={all_imgs_url: ["https://images.example/two.webp","https://images.example/one.webp"]};</script>',
        })
        index = source.inspect(title, http)['episodes']
        self.assertEqual(source.inspect(index[0]['url'], http)['pages'],
                         ['https://images.example/two.webp', 'https://images.example/one.webp'])

    def test_novelcool_reads_public_partner_image_array(self):
        source = self.source('NovelCool', 'pt-BR')
        chapter = source.ROOT + '/chapter/story/42.html'
        partner = 'https://reader.example/story/42'
        http = fixture({
            chapter: f'<a class="vision-button" href="{partner}">Read</a>',
            partner: r'<script>const viewer={all_imgs_url: ["https:\/\/images.example\/a.webp"]};</script>',
        })
        self.assertEqual(source.pages(http, chapter), ['https://images.example/a.webp'])

    def test_desu_maps_saved_chapter_id_and_excludes_closed_entries(self):
        source = self.source('Desu')
        title = source.ROOT + '/manga/51'
        chapter = title + '/chapter/25'
        http = fixture({source.API + '51/': {'manga': {'id': 51, 'russian': 'Тайтл', 'kind': 'manhwa'}},
                        source.API + '51/chapters': {'chapters': [{'id': 25, 'number': '1.5', 'volume': '2'},
                                                                 {'id': 26, 'is_readable': False}]},
                        source.API + '51/chapters/25': {'chapter': {'pages': [{'url': 'https://cdn.example/a.webp'}]}}})
        canonical = source.saved_chapter({'url': '/25'}, source.ROOT, title)
        self.assertEqual(canonical, chapter)
        row = source.inspect(title, http)
        self.assertEqual([(x['season'], x['number']) for x in row['episodes']], [(2, 1.5)])
        self.assertEqual(source.inspect(canonical, http)['pages'], ['https://cdn.example/a.webp'])

    def test_webtoonclub_sorts_payload_by_provider_order(self):
        source = self.source('WebtoonClub')
        chapter = source.ROOT + '/webtoon/story/chapter/1'
        rows = {'comicId': 41, 'images': [{'filename': 'a/2.png', 'sortOrder': 20},
                                         {'filename': 'a/1.png', 'sortOrder': 10}]}
        text = 'a:' + json.dumps(rows) + '\n'
        http = fixture({chapter: '<script>self.__next_f.push(' + json.dumps([1, text]) + ')</script>'})
        self.assertEqual(source.pages(http, chapter), [source.ROOT + '/uploads/a/1.png', source.ROOT + '/uploads/a/2.png'])

    def test_wordpress_locale_preserves_first_part_and_paginates_archive(self):
        source = self.source('MyReadingManga', 'ja')
        parent = source.ROOT + '/manga-story/'
        bill = '<h1>[Author] Story (Japanese)</h1><a class="page-numbers">3</a>'
        http = fixture({parent: bill + '<div class="entry-content"><img data-src="/1.webp"></div>',
                        parent + '2/': '<div class="entry-content"><img src="/2.webp"></div>'})
        title = source.inspect(parent, http)
        self.assertEqual((title['title'], title['authors'], len(title['episodes'])), ('Story', ['Author'], 3))
        self.assertEqual(source.inspect(title['episodes'][0]['url'], http)['pages'], [source.ROOT + '/1.webp'])
        self.assertEqual(source.inspect(title['episodes'][1]['url'], http)['pages'], [source.ROOT + '/2.webp'])

    def test_simply_keeps_language_and_order_of_full_images(self):
        source = self.source('Simply Hentai', 'ru')
        title = source.ROOT + '/series-one/story'
        api = manga_simply_native.API
        entry = {'series': {'slug': 'series-one'}, 'slug': 'story', 'title': 'Story'}
        http = fixture({api + '/tag/russian?type=language&page=1': {'data': {'albums': [entry]}},
                        api + '/manga/story': {'data': entry},
                        api + '/manga/story/pages': {'data': {'pages': [
                            {'page_num': 2, 'sizes': {'full': 'https://cdn.example/2.png'}},
                            {'page_num': 1, 'sizes': {'full': 'https://cdn.example/1.png'}}]}}})
        self.assertEqual(source.catalogue(http)[0][0]['language'], 'ru')
        row = source.inspect(title, http)
        self.assertEqual(source.inspect(row['episodes'][0]['url'], http)['pages'],
                         ['https://cdn.example/1.png', 'https://cdn.example/2.png'])

    def test_luscious_allows_only_the_published_read_queries(self):
        source = self.source('Luscious', 'es')
        def document(url, **kwargs):
            self.assertTrue(public_url(url, resolve_dns=False))
            query = parse_qs(urlsplit(url).query)
            self.assertEqual(query['operationName'], ['AlbumList'])
            body = json.loads(query['variables'][0])['input']
            self.assertIn({'name': 'language_ids', 'value': '+3'}, body['filters'])
            self.assertIn({'name': 'search_query', 'value': 'Story'}, body['filters'])
            return ('{"data":{"album":{"list":{"items":[]}}}}', url, {})
        http = Mock(document=Mock(side_effect=document), deadline=None)
        self.assertEqual(source.catalogue(http, query='Story'), ([], False))
        with self.assertRaises(SourceError):
            public_url(manga_luscious_native.API + '?operationName=UpdateAlbum&query=mutation', resolve_dns=False)

    def test_mangamen_preserves_translator_volume_and_native_order(self):
        source = self.source('MangaMen')
        title = source.ROOT + '/story'
        chapter = title + '/chapter-2'
        http = fixture({title: '<h1 itemprop="name">Story</h1><div class="chapter-item" data-volume="2" data-number="2.5">'
                               f'<div class="chapter-item__name"><a href="{chapter}">Chapter</a></div>'
                               '<div class="chapter-item__added"><span>Group</span></div></div>',
                        chapter: '<script>window.__pg = [{"p":2,"u":"/2.png"},{"p":1,"u":"/1.png"}];</script>'})
        row = source.inspect(title, http)
        self.assertEqual((row['episodes'][0]['season'], row['episodes'][0]['number'], row['episodes'][0]['translator']),
                         (2, 2.5, 'Group'))
        self.assertEqual(source.inspect(row['episodes'][0]['url'], http)['pages'], [source.ROOT + '/1.png', source.ROOT + '/2.png'])

    def test_public_zip_read_is_range_bounded_and_supports_cbz_page_transport(self):
        image = BytesIO()
        with Image.new('RGB', (8, 8), 'green') as source:
            source.save(image, 'PNG')
        payload = BytesIO()
        with ZipFile(payload, 'w') as archive:
            archive.writestr('02.png', image.getvalue())
            archive.writestr('01.png', image.getvalue())
            archive.writestr('padding.txt', b'\0' * (manga_public_zip.DIRECTORY_LIMIT + 1))
        raw = payload.getvalue()
        archive_url = 'https://panda.chaika.moe/archive/14/download/'
        referer = 'https://panda.chaika.moe/archive/14'
        requested = []
        def open_range(url, headers, byte_range):
            self.assertEqual((url, headers['Referer']), (archive_url, referer))
            low, high = map(int, byte_range.removeprefix('bytes=').split('-'))
            requested.append((low, high))
            return Mock(status_code=206, headers={'Content-Range': f'bytes {low}-{high}/{len(raw)}'},
                        iter_content=Mock(return_value=[raw[low:high + 1]])), url
        http = Mock(_open=Mock(side_effect=open_range), deadline=None)
        refs = manga_public_zip.download_refs(http, archive_url, referer)
        self.assertEqual(len(refs), 2)
        self.assertEqual(manga_public_zip.grant(refs[0])[3], '01.png')
        self.assertEqual(fetch_page(http, page_reference(refs[0]), {}), (image.getvalue(), 'image/png'))
        self.assertLess(max(end - start + 1 for start, end in requested), len(raw))
        with self.assertRaises(SourceError):
            page_reference(refs[0].replace('/14/', '/15/'))

    def test_toonlook_exposes_only_selected_language_manifest(self):
        source = self.source('ToonLook', 'zh')
        title = source.ROOT + '/manhwa/story/'
        chapter = source.ROOT + '/story-1?lang=zh'
        pages = base64.b64encode(b'[{"src":"series/zh/story/1/01.webp"}]').decode()
        manifest = {'base': 'https://cdn.example', 'lang': 'zh', 'data': pages}
        http = fixture({title: '<div class="manga-titles"><h1>Story</h1></div>'
                               '<a href="/story-1" class="chapter-item" data-langs="en zh" data-title-en="Chapter 1" data-title-zh="第1話"></a>',
                        chapter: '<script>chapterData = ' + json.dumps(manifest) + ';</script>'})
        row = source.inspect(title, http)
        self.assertEqual(len(row['episodes']), 1)
        self.assertEqual(row['episodes'][0]['language'], 'zh')
        self.assertEqual(source.inspect(row['episodes'][0]['url'], http)['pages'],
                         ['https://cdn.example/series/zh/story/1/01.webp'])

    def test_alpha_manga_restores_an_explicit_tile_order(self):
        tile = 16
        body = struct.pack('<IIII', 0, (tile << 24) | (1 << 16), 16 << 15, tile << 24)
        placeholder = b'\x89PNG\r\n\x1a\n' + b'\0' * 25 + b'\x02\0' + body
        keys = manga_alpha_manga.keys('data:image/png;base64,' + base64.b64encode(placeholder).decode())
        with Image.new('RGB', (32, 16), 'red') as image:
            image.paste((0, 0, 255), (16, 0, 32, 16))
            raw = BytesIO()
            image.save(raw, 'PNG')
        output = manga_alpha_manga.AlphaTileLayout(keys[0]).decode(raw.getvalue())
        with Image.open(BytesIO(output)) as image:
            self.assertEqual(image.getpixel((5, 5)), (0, 0, 255))
            self.assertEqual(image.getpixel((25, 5)), (255, 0, 0))

    def test_ysk_localization_and_chapter_page_contract(self):
        source = self.source('YSK Comics', 'ar')
        title = source.ROOT + '/ar/comic/test-series'
        http = fixture({
            source.ROOT + '/api/comic/test-series': {'data': {'slug': 'test-series', 'full_name': 'Story',
                                                            'language_code': 'ar', 'genres': [{'name': 'Action'}]}},
            source.ROOT + '/api/comic/chapter/test-series?page=1':
                {'data': {'data_messages': [{'slug': 'xyz', 'rank': '2'}], 'meta': {'link_next': None}}},
            source.ROOT + '/api/chapters/images/xyz': {'data': ['https://cdn.example/01.png']},
        })
        card = source.inspect(title, http)
        self.assertEqual((card['language'], card['genres']), ('ar', ['Action']))
        self.assertEqual(source.inspect(card['episodes'][0]['url'], http)['pages'], ['https://cdn.example/01.png'])
        self.assertTrue(all(call.kwargs['headers']['x-localization'] == 'ar' for call in http.document.call_args_list))

    def test_manga_plus_returns_signed_public_pages_and_skips_non_image_frames(self):
        source = self.source('MANGA Plus by SHUEISHA', 'ru')
        url = source.ROOT + '/viewer/88?mv_title=11'
        image_url = 'https://jumpg-assets.tokyo-cdn.com/page.png'
        image = BytesIO()
        with Image.new('RGB', (12, 12), 'blue') as original:
            original.save(image, 'PNG')
        page = wire_field(1, image_url) + wire_field(5, '0a0b')
        confirmed = wire_field(1, wire_field(1, page)) + wire_field(1, wire_field(2, b'')) + wire_field(9, 11) + wire_field(19, 'public-token')
        binary = wire_field(1, wire_field(10, confirmed))
        mock = Mock(status_code=200, iter_content=Mock(return_value=[binary]))
        route = (manga_mangaplus.API + '/manga_viewer_v3?chapter_id=88&split=yes&img_quality=super_high&clang=rus')
        self.assertEqual(public_url(route, resolve_dns=False), route)
        http = Mock(_open=Mock(return_value=(mock, route)), deadline=None)
        pages = source.pages(http, url)
        self.assertEqual(len(pages), 1)
        request = http._open.call_args
        self.assertEqual((request.args[0], request.kwargs['action']), (route, 'mangaplus-proto'))
        encrypted = bytes(byte ^ (10, 11)[idx % 2] for idx, byte in enumerate(image.getvalue()))
        http._open.return_value = (Mock(iter_content=Mock(return_value=[encrypted])), image_url)
        self.assertEqual(fetch_page(http, page_reference(pages[0]), {}), (image.getvalue(), 'image/png'))
        self.assertEqual(http._open.call_args.kwargs['headers']['Plus-Vw-Token'], 'public-token')
        with self.assertRaises(SourceError):
            page_reference(pages[0].replace('/page.png', '/other.png'))

    def test_klto9_restores_old_fragment_and_uses_real_chapter_id(self):
        source = self.source('Klto9')
        title = source.ROOT + '/teap-story.html'
        list_path = 'A' * 25 + '.lst'
        page_path = 'A' * 30 + '.iog'
        http = fixture({title: '<h1 class="cinema-title">Story</h1>',
                        source.ROOT + '/' + list_path + '?manga=story':
                            [{'id': '91', 'manga': 'story', 'chapter': '1.5'}],
                        source.ROOT + '/' + page_path + '?cid=91':
                            '<img data-pagespeed-lazy-src="https://cdn.example/1.png">'})
        with patch.object(manga_klto9, 'suffix', side_effect=lambda length, extension: '/' + 'A' * length + extension):
            old = source.saved_chapter({'url': '91#story#1.5'}, source.ROOT, title)
            self.assertEqual(old, source.ROOT + '/zmqs-story-chapter-1.5.html?cid=91')
            self.assertEqual(source.inspect(old, http)['pages'], ['https://cdn.example/1.png'])
