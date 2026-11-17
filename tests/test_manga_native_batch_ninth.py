"""Contract tests for the ninth (final) migration batch and live-checked activation."""

import base64
import csv
import hashlib
import json
import os
from pathlib import Path
import time
from unittest import TestCase
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import manga_kisslove
import manga_native_registry
import manga_native_sources
import manga_ninth_routes
import manga_ninth_sources
import manga_taddyink
import manga_tappytoon
import manga_webcomicsapp
import manga_yaoime
from source_parser import SourceError

ROOT = Path(__file__).resolve().parents[1]


def inventory():
    with (ROOT / 'docs/native-source-inventory.csv').open(newline='', encoding='utf-8') as file:
        return {row['source_id']: row for row in csv.DictReader(file)}


class NinthBatchTests(TestCase):
    def test_profiles_match_the_installed_inventory(self):
        rows = inventory()
        # 38 profiles of the batch plus the four Japan-routed readers.
        self.assertEqual(len(manga_ninth_sources.SOURCES), 42)
        for adapter in manga_ninth_sources.SOURCES:
            row = rows[adapter.SOURCE_ID]
            self.assertEqual((adapter.NAME, adapter.LANGUAGE), (row['source'], row['language']))
            self.assertIs(manga_native_registry.profiles()[adapter.SOURCE_ID], adapter)

    def test_activation_lists_only_registered_profiles(self):
        listed = json.loads((ROOT / 'server/manga_native_activation.json').read_text(encoding='utf-8'))['sourceIds']
        self.assertEqual(len(listed), len(set(listed)))
        profiles = manga_native_registry.profiles()
        self.assertTrue(set(listed) <= set(profiles))
        for sid in listed:
            self.assertIs(manga_native_sources.ADAPTERS[sid], profiles[sid])
        rows = inventory()
        for sid in listed:
            self.assertEqual(rows[sid]['pages'], 'verified', sid)

    def test_route_policy_rejects_requests_outside_the_declared_routes(self):
        with self.assertRaises(SourceError):
            manga_ninth_routes.prepare('n9:unknown', 'https://example.com/', 'GET', None, {})
        with self.assertRaises(SourceError):
            manga_ninth_routes.prepare('n9:tappytoon', 'https://api-global.tappytoon.com/admin', 'GET', None, {})
        with self.assertRaises(SourceError):
            # A POST is allowed only for a declared form.
            manga_ninth_routes.prepare('n9:kisslove', 'https://klz9.com/api/genres', 'POST', {'a': 1}, {})

    def test_kisslove_signature_must_be_fresh_and_valid(self):
        stamp, signed = manga_kisslove.signature()
        route = manga_ninth_routes.prepare('n9:kisslove', 'https://klz9.com/api/genres', 'GET', None,
                                           {'Kisslove-Time': stamp, 'Kisslove-Signature': signed})
        self.assertEqual(route.headers['X-Client-Sig'], signed)
        old = str(int(time.time()) - 3600)
        stale = hashlib.sha256(f'{old}.{manga_kisslove.CLIENT_ID}'.encode()).hexdigest()
        with self.assertRaises(SourceError):
            manga_ninth_routes.prepare('n9:kisslove', 'https://klz9.com/api/genres', 'GET', None,
                                       {'Kisslove-Time': old, 'Kisslove-Signature': stale})

    def test_yaoime_unseals_pages_like_the_site_reader(self):
        hashes = ['abcdEFGH1234', 'zyxw_9876-AB']
        salt, nonce = os.urandom(16), os.urandom(12)
        key = hashlib.sha256(manga_yaoime.SEAL_KEY + salt).digest()
        sealed = salt + nonce + AESGCM(key).encrypt(nonce, json.dumps({'p': hashes}).encode(), None)
        self.assertEqual(manga_yaoime.unseal(base64.urlsafe_b64encode(sealed).decode().rstrip('=')), hashes)
        with self.assertRaises(SourceError):
            manga_yaoime.unseal(base64.urlsafe_b64encode(sealed[:-1]).decode())

    def test_yaoime_reader_request_carries_a_valid_signature(self):
        path = manga_yaoime.reader_path(12, 34)
        stamp = str(int(time.time() * 1000))
        route = manga_ninth_routes.prepare('n9:yaoime', 'https://yaoi.me' + path, 'GET', None,
                                           {'Yaoime-Time': stamp, 'Yaoime-Signature': manga_yaoime.sign(path, stamp)})
        self.assertEqual(route.headers['x-yf-t'], stamp)
        with self.assertRaises(SourceError):
            manga_ninth_routes.prepare('n9:yaoime', 'https://yaoi.me' + path, 'GET', None,
                                       {'Yaoime-Time': stamp, 'Yaoime-Signature': 'forged'})

    def test_yaoime_chapter_links_keep_their_series(self):
        source = manga_yaoime.SOURCES[0]
        url = 'https://yaoi.me/chapter/55/66?mv_series=77'
        self.assertTrue(source.is_chapter(url))
        self.assertEqual(source.title_for(url), 'https://yaoi.me/series/77')

    def test_webcomics_payload_is_unflattened_with_reactive_wrappers(self):
        values = [{'data': 1}, ['ShallowReactive', 2], {'list': 3, 'pagination': 5}, [4], {'book_id': 6}, {'next': 7},
                  '0123456789abcdef01234567', True]
        self.assertEqual(manga_webcomicsapp.unflatten(values, 0),
                         {'data': {'list': [{'book_id': '0123456789abcdef01234567'}], 'pagination': {'next': True}}})
        self.assertTrue(manga_webcomicsapp.valid_form('/chapter/list', {
            'book_id': '0123456789abcdef01234567', 'page': 1, 'size': 9999, 'sort': 'desc'}))
        self.assertFalse(manga_webcomicsapp.valid_form('/chapter/list', {
            'book_id': '../', 'page': 1, 'size': 9999, 'sort': 'desc'}))

    def test_saved_suwayomi_links_map_to_direct_urls(self):
        taddy = manga_taddyink.SOURCES[0]
        feed = 'https://taddy.org/feeds/sss/comicseries/fd65354f-d249-403c-860b-9bd80dd33362'
        chapter = taddy.saved_chapter({'url': feed + '#e6f80eaf-87ca-4b76-bf22-1342056b6709'}, 'https://taddy.org', feed)
        self.assertTrue(taddy.is_chapter(chapter))
        tappy = manga_tappytoon.SOURCES[0]
        title = tappy.saved_title_url('light-and-shadow|48')
        self.assertTrue(tappy.is_title(title))
        self.assertTrue(tappy.is_chapter(tappy.saved_chapter({'url': '316979852'}, tappy.ROOT, title)))
        kiss = manga_kisslove.SOURCES[0]
        target = kiss.saved_chapter({'url': '123/some-title-chapter-5'}, kiss.ROOT, 'https://klz9.com/some-title.html')
        self.assertEqual(urlsplit(kiss.title_for(target)).path, '/some-title.html')
