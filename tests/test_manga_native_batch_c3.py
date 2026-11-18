"""Contracts of package C3: English publisher sites ported from Suwayomi-only extensions."""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
import struct
from unittest import TestCase
from urllib.parse import urlencode, urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.padding import PKCS7
from PIL import Image

import manga_azuki
import manga_coolmic
import manga_e4p
import manga_emaqi
import manga_inkr
import manga_jnovel
import manga_kmanga
import manga_mangaup_global
import manga_native_registry
import manga_ninth_routes
import manga_tapas
import manga_tenth_sources
import manga_webnovel
from source_parser import SourceError

C3 = {'8879500923091081231', '8195282477201261072', '5554748812413853237', '3383118804501081522',
      '5279120461134453793', '4081135203808920563', '8143442163119480220', '7689478295161479290',
      '6949560025265725268', '2482510125735992610'}


def prepare(action, url, method='GET', data=None, headers=None):
    return manga_ninth_routes.prepare(action, url, method, data, headers or {})


class PackageC3Tests(TestCase):
    def test_profiles_are_registered(self):
        ids = {adapter.SOURCE_ID for adapter in manga_tenth_sources.SOURCES}
        self.assertLessEqual(C3, ids)
        for sid in C3:
            self.assertIn(sid, manga_native_registry.profiles())

    def test_azuki_routes_and_free_window(self):
        url = manga_azuki.API + '/mangas/v1?' + urlencode({'sort': 'popular', 'series_types': 'comic', 'format': 'digital',
                                                         'count': '24', 'offset': '24'})
        route = prepare('n9:azuki', url, headers={'Azuki-Store': manga_azuki.KODANSHA_KEY})
        self.assertEqual(route.headers['azuki-organization-key'], manga_azuki.KODANSHA_KEY)
        with self.assertRaises(SourceError):
            # Omoi lists its catalogue on its own page, not through the API.
            prepare('n9:azuki', url, headers={'Azuki-Store': manga_azuki.OMOI_KEY})
        with self.assertRaises(SourceError):
            prepare('n9:azuki', manga_azuki.API + '/user/mangas/x/v0', headers={'Azuki-Store': manga_azuki.OMOI_KEY})
        prepare('n9:azuki', 'https://www.omoi.com/discover?page=2&sort=popular&tags%5B%5D=action')
        now = datetime.now(timezone.utc)
        past, future = (now - timedelta(days=1)).isoformat(), (now + timedelta(days=1)).isoformat()
        self.assertTrue(manga_azuki.free_now({'free_published_date': past, 'free_unpublished_date': None}))
        self.assertFalse(manga_azuki.free_now({'free_published_date': past, 'free_unpublished_date': past}))
        self.assertFalse(manga_azuki.free_now({'free_published_date': future}))
        self.assertFalse(manga_azuki.free_now({}))

    def test_azuki_saved_links(self):
        kodansha, omoi = manga_azuki.SOURCES
        uuid = 'e372cc58-11db-4883-b87a-38392c73a87d'
        self.assertEqual(kodansha.saved_title_url('https://kodansha.us/' + uuid), 'https://kodansha.us/series/' + uuid)
        title = omoi.saved_title_url('https://www.omoi.com/fort-of-apocalypse#' + uuid)
        self.assertEqual(title, 'https://www.omoi.com/series/fort-of-apocalypse')
        chapter = omoi.saved_chapter({'url': f'/{uuid}#fort-of-apocalypse'}, omoi.ROOT, title)
        self.assertEqual(chapter, f'https://www.omoi.com/series/fort-of-apocalypse/read/{uuid}')
        self.assertTrue(omoi.saved_chapter_matches(chapter, title))

    def test_tapas_routes(self):
        prepare('n9:tapas', 'https://story-api.tapas.io/cosmos/api/v1/landing/ranking?category_type=COMIC&subtab_id=17&size=25&page=0')
        prepare('n9:tapas', 'https://tapas.io/series/205543/episodes?page=2&sort=OLDEST&since=1794958477880&large=true&last_access=0&=')
        with self.assertRaises(SourceError):
            prepare('n9:tapas', 'https://tapas.io/series/205543/episodes?page=2&sort=NEWEST&since=1&large=true&last_access=0&=')
        adapter = manga_tapas.SOURCES[0]
        chapter = adapter.saved_chapter({'url': '/episode/2135770'}, adapter.ROOT, 'https://tapas.io/series/205543')
        self.assertTrue(adapter.saved_chapter_matches(chapter, 'https://tapas.io/series/205543'))

    def test_emaqi_body_and_page_keys(self):
        body = manga_emaqi.body('Search', {'input': {'keyword': 'OUT', 'tagSlugGroups': [], 'page': 1, 'limit': 50}})
        self.assertTrue(prepare('n9:emaqi', manga_emaqi.API, 'POST', body).post)
        changed = json.loads(body)
        changed['query'] = '{ users { email } }'
        with self.assertRaises(SourceError):
            prepare('n9:emaqi', manga_emaqi.API, 'POST', json.dumps(changed, separators=(',', ':')).encode())
        contents = manga_emaqi.body('FetchChapterContents', {'comicId': '6763d1bb-0d5e-4c6d-a634-a82db649c0c1',
                                                             'chapterNumber': 1})
        with self.assertRaises(SourceError):
            prepare('n9:emaqi', manga_emaqi.API, 'POST', contents)
        public = manga_emaqi.Keys.public()
        self.assertIn('X-Hash', prepare('n9:emaqi', manga_emaqi.API, 'POST', contents, {'X-Hash': public}).headers)
        key = bytes(range(32))
        wrapped = manga_emaqi.Keys.get().public_key().encrypt(
            key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        self.assertEqual(manga_emaqi.Keys.unwrap(base64.b64encode(wrapped).decode()), key)
        iv = bytes(16)
        self.assertEqual(manga_emaqi.decrypt(b'\x02\x00' + iv + AESGCM(key).encrypt(iv, b'page', None), key), b'page')
        padder = PKCS7(128).padder()
        plain = padder.update(b'cbc page') + padder.finalize()
        encoder = Cipher(algorithms.AES(key), modes.CBC(b'\x01' * 16)).encryptor()
        self.assertEqual(manga_emaqi.decrypt(b'\x01' * 16 + encoder.update(plain) + encoder.finalize(), key), b'cbc page')

    def test_coolmic_key_form_and_pbkdf2_pages(self):
        form = json.dumps({'encrypted_key': 'QUJD' * 8, 'file_name': '000084664-001.webp'}, separators=(',', ':')).encode()
        route = prepare('n9:coolmic', 'https://coolmic.me/api/v1/decryption_keys', 'POST', form, {'X-CSRF-TOKEN': 'a' * 40})
        self.assertTrue(route.cookies and route.post)
        with self.assertRaises(SourceError):
            prepare('n9:coolmic', 'https://coolmic.me/api/v1/decryption_keys', 'POST', form)
        salt, iv = b's' * 16, b'i' * 16
        key = hashlib.pbkdf2_hmac('sha256', b'password', salt, 1000, 32)
        padder = PKCS7(128).padder()
        encoder = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        sealed = encoder.update(padder.update(b'\xff\xd8image') + padder.finalize()) + encoder.finalize()
        page = {'salt': base64.b64encode(salt).decode(), 'iv': base64.b64encode(iv).decode(), 'iterations': 1000,
                'encrypted_image': base64.b64encode(sealed).decode()}
        self.assertEqual(manga_coolmic.unwrap(page, 'password'), b'\xff\xd8image')
        self.assertEqual(manga_coolmic.cover_of(3274),
                         'https://en-img.coolmic.me/titles/000/000003/000003274/000003274_large_vertical.jpg')

    def test_webnovel_api_needs_the_guest_token(self):
        prepare('n9:webnovel', 'https://www.webnovel.com/go/pcm/comic/getChapterList?comicId=14279238705852001&_csrfToken=ede4f23a-23fa')
        with self.assertRaises(SourceError):
            prepare('n9:webnovel', 'https://www.webnovel.com/go/pcm/comic/getChapterList?comicId=14279238705852001')
        adapter = manga_webnovel.SOURCES[0]
        title = adapter.saved_title_url('https://www.webnovel.com/14279238705852001')
        self.assertEqual(title, 'https://www.webnovel.com/comic/14279238705852001')
        self.assertEqual(adapter.saved_chapter({'url': '14279238705852001:38330774499412077'}, adapter.ROOT, title),
                         'https://www.webnovel.com/comic/14279238705852001/38330774499412077')

    def test_kmanga_signed_requests_and_tiles(self):
        args = {'title_id': '10011'}
        signature = manga_kmanga.request_hash(args, '2000000000')
        url = manga_kmanga.API + '/web/title/detail?title_id=10011'
        route = prepare('n9:kmanga', url, headers={'Kmanga-Expires': '2000000000', 'X-Kmanga-Hash': signature})
        self.assertEqual(route.headers['x-kmanga-client-id'], '0')
        with self.assertRaises(SourceError):
            prepare('n9:kmanga', url, headers={'Kmanga-Expires': '2000000000', 'X-Kmanga-Hash': '0' * 128})
        order = manga_kmanga.tile_order('mhz9hx1qqm', 10011, 317222)
        self.assertEqual(sorted(order), list(range(16)))
        tile = Image.new('RGB', (64, 64))
        for index in range(16):
            tile.paste((index * 15, 0, 0), (index % 4 * 16, index // 4 * 16, index % 4 * 16 + 16, index // 4 * 16 + 16))
        raw = BytesIO()
        tile.save(raw, 'PNG')
        with Image.open(BytesIO(manga_kmanga.unscramble(raw.getvalue(), order))) as result:
            for dest, origin in enumerate(order):
                self.assertAlmostEqual(result.getpixel((dest % 4 * 16 + 8, dest // 4 * 16 + 8))[0], origin * 15, delta=6)

    def test_mangaup_viewer_is_a_post(self):
        url = manga_mangaup_global.API + 'manga/viewer_v2?app_ver=0&os_ver=0&chapter_id=109239&quality=high&lang=en'
        self.assertTrue(prepare('n9:mangaup-global', url, 'POST', b'').post)
        with self.assertRaises(SourceError):
            prepare('n9:mangaup-global', url)
        with self.assertRaises(SourceError):
            prepare('n9:mangaup-global', manga_mangaup_global.API + 'my_page?app_ver=0&os_ver=0&lang=en')

    def test_inkr_bodies_and_static_page_key(self):
        body = manga_inkr.encode([{'fields': manga_inkr.CHAPTER_FIELDS, 'oids': ['ik-chapter-1']}])
        self.assertTrue(prepare('n9:inkr', manga_inkr.CONTENT, 'POST', body).post)
        with self.assertRaises(SourceError):
            prepare('n9:inkr', manga_inkr.CONTENT, 'POST', manga_inkr.encode([{'fields': ['email'], 'oids': ['ik-user-1']}]))
        plain = b'RIFF' + b'x' * 30
        padded = plain + b'\0' * (-len(plain) % 16)
        encoder = Cipher(algorithms.AES(manga_inkr.KEY), modes.CBC(b'\x07' * 16)).encryptor()
        sealed = struct.pack('<I', len(plain)) + b'\x07' * 16 + encoder.update(padded) + encoder.finalize()
        self.assertEqual(manga_inkr.decrypt(sealed), plain)

    def test_e4p_primitives(self):
        # RFC 6229 RC4 vector (key 0102030405, offset 0).
        self.assertEqual(manga_e4p.rc4(bytes(8), bytes((1, 2, 3, 4, 5))).hex(), 'b2396305f03dc027')
        data = b'chacha8 stream' * 9
        key, nonce = bytes(range(32)), bytes(8)
        self.assertEqual(manga_e4p.chacha8(manga_e4p.chacha8(data, key, nonce, 7), key, nonce, 7), data)
        values = [1, 2, 3, 4]
        self.assertEqual(len(manga_e4p.xxtea_decrypt(values, manga_e4p.XXTEA_KEY)), 4)
        directory = bytearray(manga_e4p.DIR_SIZE)
        directory[:8] = manga_e4p.QSC_MAGIC
        for index, (name, size) in enumerate((('a/0', 10), ('a/1', 20))):
            base = 32 + index * 32
            directory[base:base + 4] = b'XEBP'
            struct.pack_into('<I', directory, base + 4, size)
            directory[base + 8:base + 8 + len(name)] = name.encode()
        self.assertEqual(manga_e4p.qsc_entry(bytes(directory), 'a/1'), (10, 20))
        with self.assertRaises(SourceError):
            manga_e4p.qsc_entry(bytes(directory), 'a/2')

    def test_jnovel_routes_and_saved_links(self):
        prepare('n9:jnovel', 'https://j-novel.club/series?type=manga&page=2&search=god')
        prepare('n9:jnovel', 'https://labs.j-novel.club/embed/v2/PRT-42ZAESA/info.json')
        with self.assertRaises(SourceError):
            prepare('n9:jnovel', 'https://j-novel.club/api/me')
        adapter = manga_jnovel.SOURCES[0]
        title = adapter.saved_title_url('https://j-novel.club/some-series')
        chapter = adapter.saved_chapter({'url': 'some-series-volume-1-chapter-1'}, adapter.ROOT, title)
        self.assertEqual(urlsplit(chapter).path, '/read/some-series-volume-1-chapter-1')
        self.assertTrue(adapter.saved_chapter_matches(chapter, title))
