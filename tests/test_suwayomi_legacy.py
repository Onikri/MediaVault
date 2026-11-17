"""Old Suwayomi numeric links keep opening after Suwayomi is gone."""
import csv
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import api
import manga_mangashi
import suwayomi_bridge
import suwayomi_legacy
import suwayomi_legacy_migrate
from manga_mangashi import ROOT, SOURCE_ID
from source_parser import SourceError

PUBLIC = 'https://vault.example'
TITLE = ROOT + '/manga/bluelock/'
SECOND = TITLE + 'glava-1,5/'
OLD_TITLE = PUBLIC + '/__manga/suwayomi/m/75'
OLD_CHAPTER = OLD_TITLE + '/c/2'
PORTLESS = '777'  # a source without any direct reader yet


def write_export(directory, chapters=True):
    def table(name, header, rows):
        with open(Path(directory) / name, 'w', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle, quoting=csv.QUOTE_NONNUMERIC)
            writer.writerow(header)
            writer.writerows(rows)

    table('source.csv', ['ID', 'NAME', 'LANG', 'PKG_NAME', 'EXT_NAME', 'IS_INSTALLED', 'VERSION_NAME'], [
        ['0', 'Local source', 'localsourcelang', '', '', 'TRUE', '1'],
        [SOURCE_ID, 'Manga-shi', 'ru', 'eu.kanade.tachiyomi.extension.ru.mangashi', 'Manga-shi', 'TRUE', '1.4'],
        [PORTLESS, 'Closed Reader', 'en', 'eu.kanade.tachiyomi.extension.en.closed', 'Closed', 'TRUE', '1.0'],
    ])
    table('manga.csv', ['ID', 'SOURCE', 'URL', 'REAL_URL', 'TITLE', 'THUMBNAIL_URL', 'IN_LIBRARY', 'INITIALIZED'], [
        ['75', SOURCE_ID, '/manga/bluelock/', TITLE, 'Blue Lock', 'https://img.example/c.jpg', 'FALSE', 'TRUE'],
        ['76', PORTLESS, '/series/x', 'https://closed.example/series/x', 'Closed', '', 'FALSE', 'TRUE'],
    ])
    rows = [['75', '1', '900', '/manga/bluelock/glava-1/', TITLE + 'glava-1/', 'Глава 1', '1.0', '', '20'],
            ['75', '2', '901', '/manga/bluelock/glava-1,5/', SECOND, 'Глава 1,5', '1.5', '', '18'],
            ['76', '1', '950', '/series/x/1', 'https://closed.example/series/x/1', 'One', '1.0', '', '']]
    table('chapter.csv', ['MANGA', 'SOURCE_ORDER', 'ID', 'URL', 'REAL_URL', 'NAME', 'CHAPTER_NUMBER', 'SCANLATOR', 'PAGE_COUNT'],
          rows if chapters else rows[:1])
    sources = Path(directory) / 'sources.json'
    sources.write_text(json.dumps([{'id': SOURCE_ID, 'name': 'Manga-shi', 'lang': 'ru', 'baseUrl': ROOT, 'isNsfw': False},
                                   {'id': PORTLESS, 'name': 'Closed Reader', 'lang': 'en', 'baseUrl': 'https://closed.example'}]))
    return sources


class LegacyMap(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.data = Path(self.directory.name)
        self.environment = patch.dict(os.environ, {'DATA_DIR': str(self.data), 'PUBLIC_URL': PUBLIC, 'SUWAYOMI_URL': '',
                                                   'SUWAYOMI_AUTH_FILE': '', 'MEDIA_VAULT_DISABLE_WORKER': '1'})
        self.environment.start()
        suwayomi_legacy._cache.clear()
        export = self.data / 'export'
        export.mkdir()
        self.counts = suwayomi_legacy.build(export, write_export(export))

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def test_export_merges_and_never_drops_an_old_row(self):
        self.assertEqual((self.counts['manga'], self.counts['chapters'], self.counts['sources']), (2, 3, 2))
        later = self.data / 'later'
        later.mkdir()
        counts = suwayomi_legacy.build(later, write_export(later, chapters=False))
        self.assertEqual((counts['total_manga'], counts['total_chapters']), (2, 3))
        with closing(sqlite3.connect(suwayomi_legacy.map_path())) as db:
            self.assertEqual(len(json.loads(db.execute("SELECT value FROM meta WHERE key='exports'").fetchone()[0])), 2)

    def test_old_title_chapter_and_page_resolve_to_the_same_direct_reader(self):
        self.assertEqual(suwayomi_legacy.resolve(75), TITLE)
        self.assertEqual(suwayomi_legacy.resolve(75, 2), SECOND)
        self.assertEqual(suwayomi_legacy.explain(75, 9), (None, 'unknown-chapter'))
        self.assertEqual(suwayomi_legacy.explain(99), (None, 'unknown-title'))
        self.assertEqual(suwayomi_legacy.explain(76, 1), (None, 'no-direct-reader'))
        self.assertEqual(suwayomi_legacy.parse(OLD_CHAPTER + '/p/3'), (75, 2, 3))
        listed = [{'url': 'https://r.example/t/chapter-4?cid=9', 'number': 4}, {'url': 'https://r.example/t/chapter-5/', 'number': 5}]
        self.assertEqual(suwayomi_legacy.episode_url('https://r.example/t/chapter-4.0', listed), listed[0]['url'])
        self.assertEqual(suwayomi_legacy.episode_url('https://r.example/t/chapter-5', listed), listed[1]['url'])
        self.assertEqual(suwayomi_legacy.episode_url('https://r.example/t/other', listed, 5), listed[1]['url'])
        self.assertIsNone(suwayomi_legacy.episode_url('https://r.example/t/other', listed))
        self.assertIsNone(suwayomi_legacy.parse('https://elsewhere.example/__manga/suwayomi/m/75'))

    def test_bridge_opens_old_links_without_suwayomi(self):
        self.assertEqual(suwayomi_bridge.parse_reference(OLD_CHAPTER), (75, 2, None))
        self.assertEqual(suwayomi_bridge.parse_reference(OLD_TITLE + '/c/1'), (75, 1, None))
        self.assertIsNone(suwayomi_bridge.parse_reference(PUBLIC + '/__manga/suwayomi/m/99'))
        with patch('suwayomi_bridge.Client', side_effect=AssertionError('Suwayomi must stay offline')), \
                patch('manga_sources.inspect', return_value={'url': SECOND, 'pages': ['p']}) as native, \
                patch('suwayomi_bridge.native_page_image', return_value=(b'img', 'image/png')) as image:
            self.assertEqual(suwayomi_bridge.inspect(OLD_CHAPTER)['url'], SECOND)
            native.assert_called_with(SECOND)
            suwayomi_bridge.inspect(OLD_TITLE)
            native.assert_called_with(TITLE)
            self.assertEqual(suwayomi_bridge.page_image(OLD_CHAPTER + '/p/4'), (b'img', 'image/png'))
            image.assert_called_once_with(SECOND, 4)

    def test_a_source_without_a_direct_reader_says_so(self):
        old = PUBLIC + '/__manga/suwayomi/m/76/c/1'
        self.assertEqual(suwayomi_bridge.parse_reference(old), (76, 1, None))
        with self.assertRaisesRegex(SourceError, 'пока не подключён напрямую'):
            suwayomi_bridge.inspect(old)

    def test_running_suwayomi_is_the_fallback_when_the_direct_reader_fails(self):
        class Bridge:
            def close(self):
                pass

            def get(self, path, *args, **kwargs):
                if path == '/manga/75/chapter/2/page/0':
                    return b'png', 'image/png'
                raise AssertionError(path)

        with patch.dict(os.environ, {'SUWAYOMI_URL': 'http://suwayomi:4567', 'SUWAYOMI_AUTH_FILE': '/x'}), \
                patch('suwayomi_bridge.Client', Bridge), \
                patch('suwayomi_bridge.native_page_image', side_effect=SourceError('origin down')):
            self.assertEqual(suwayomi_bridge.page_image(OLD_CHAPTER + '/p/0'), (b'png', 'image/png'))


class LegacyMigration(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.data = Path(self.directory.name)
        self.environment = patch.dict(os.environ, {'DATA_DIR': str(self.data), 'PUBLIC_URL': PUBLIC, 'SUWAYOMI_URL': '',
                                                   'MEDIA_VAULT_DISABLE_WORKER': '1'})
        self.environment.start()
        suwayomi_legacy._cache.clear()
        export = self.data / 'export'
        export.mkdir()
        suwayomi_legacy.build(export, write_export(export))
        self.client = TestClient(api.app)
        self.client.__enter__()
        self.catalogue()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.environment.stop()
        self.directory.cleanup()

    def catalogue(self):
        from manga_discovery import Discovery

        discovery = Discovery(self.data, start_workers=False)
        rows = [{'id': 'suwayomi:%s:75' % SOURCE_ID, 'kind': 'manga', 'title': 'Blue Lock', 'provider': 'suwayomi:' + SOURCE_ID,
                 'providerName': 'Manga-shi', 'sourceId': SOURCE_ID, 'sourceUrl': TITLE, 'url': OLD_TITLE,
                 'sourceURL': OLD_TITLE, 'language': 'ru', 'aliases': ['Blue Lock']},
                {'id': 'suwayomi:%s:76' % PORTLESS, 'kind': 'manga', 'title': 'Closed', 'provider': 'suwayomi:' + PORTLESS,
                 'providerName': 'Closed Reader', 'sourceId': PORTLESS, 'sourceUrl': 'https://closed.example/series/x',
                 'url': PUBLIC + '/__manga/suwayomi/m/76', 'language': 'en', 'aliases': ['Closed']}]
        from manga_catalog_index import upsert
        with discovery.lock, discovery.db:
            upsert(discovery.db, rows)
            for row in rows:
                discovery.db.execute('INSERT INTO titles VALUES (?,?,?,?,?,?)',
                                     (row['id'], row['sourceId'], row['language'], row['title'].casefold(), json.dumps(row), time.time()))
        discovery.db.close()

    def sync(self, subject, since=0, entries=()):
        headers = {'Authorization': 'Bearer ' + api.session_token(subject)}
        response = self.client.post('/places', json={'since': since, 'entries': list(entries)}, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def catalogue_urls(self):
        with closing(sqlite3.connect(self.data / 'manga-discovery.sqlite')) as db:
            return (sorted(json.loads(m)['url'] for (m,) in db.execute('SELECT metadata FROM catalog_titles')),
                    sorted(json.loads(m)['url'] for (m,) in db.execute('SELECT metadata FROM titles')),
                    db.execute('SELECT count(*) FROM catalog_titles').fetchone()[0])

    def test_migration_rewrites_once_keeps_progress_and_counts(self):
        now = int(time.time() * 1000)
        from urllib.parse import quote
        old_key = 'm:' + quote('online:' + OLD_CHAPTER, safe="-_.!~*'()")
        closed_key = 'm:' + quote('online:' + PUBLIC + '/__manga/suwayomi/m/76/c/1', safe="-_.!~*'()")
        history = {'id': 'manga:owner-a:suwayomi:%s:75' % SOURCE_ID, 'label': 'Blue Lock', 'kind': 'reader',
                   'route': '#watch=manga', 'at': now}
        self.sync('owner-a', 0, [
            {'k': old_key, 'at': now - 50, 'v': {'itemId': 'online:' + OLD_CHAPTER, 'page': 7, 'pages': 18, 'updatedAt': now - 50}},
            {'k': closed_key, 'at': now - 40, 'v': {'itemId': 'online:' + PUBLIC + '/__manga/suwayomi/m/76/c/1', 'page': 1, 'pages': 9}},
            {'k': 'h:' + history['id'], 'at': now, 'v': history},
        ])
        before = self.catalogue_urls()
        offline = suwayomi_legacy_migrate.run(self.data, apply=True, only=['places'])
        self.assertEqual(offline['places']['kept:needs-online-match'], 1)
        self.assertEqual(offline['places']['rows_after'], offline['places']['rows_before'])
        # The reader lists the chapter with its own tracking parameter: that exact URL is the key.
        listed = SECOND + '?cid=5'
        episodes = {'episodes': [{'url': TITLE + 'glava-1/', 'number': 1}, {'url': listed, 'number': 1.5}]}
        with patch('manga_sources.inspect', return_value=episodes) as reader:
            first = suwayomi_legacy_migrate.run(self.data, apply=True, online=True)
        reader.assert_called_once_with(TITLE)
        self.assertEqual(first['catalog_titles']['rewritten'], 1)
        self.assertEqual(first['catalog_titles']['kept_old_links'], {'no-direct-reader': 1})
        self.assertEqual(first['titles']['rewritten'], 1)
        self.assertEqual(first['places']['added'], 1)
        self.assertEqual(first['places']['kept:no-direct-reader'], 1)
        self.assertEqual(first['places']['rows_after'], first['places']['rows_before'] + 1)
        self.assertEqual(first['network_refused'] if 'network_refused' in first else 0, 0)
        after = self.catalogue_urls()
        self.assertEqual(after[2], before[2])
        self.assertIn(TITLE, after[0])
        self.assertIn(PUBLIC + '/__manga/suwayomi/m/76', after[0])
        # Another device receives the same page under the direct chapter's key; the old place stays.
        places = {e['k']: e for e in self.sync('owner-a')['entries']}
        new_key = 'm:' + quote('online:' + listed, safe="-_.!~*'()")
        self.assertEqual((places[new_key]['v']['page'], places[new_key]['v']['itemId'], places[new_key]['at']),
                         (7, 'online:' + listed, now - 50))
        self.assertEqual(places[old_key]['v']['page'], 7)
        # A second run changes nothing.
        with patch('manga_sources.inspect', return_value=episodes):
            second = suwayomi_legacy_migrate.run(self.data, apply=True, online=True)
        self.assertEqual((second['catalog_titles']['rewritten'], second['titles']['rewritten'], second['places'].get('added', 0)), (0, 0, 0))
        self.assertEqual(second['places']['already-migrated'], 1)
        self.assertEqual(second['places']['rows_after'], first['places']['rows_after'])
        self.assertEqual(self.catalogue_urls(), after)

    def test_dry_run_writes_nothing(self):
        before = self.catalogue_urls()
        report = suwayomi_legacy_migrate.run(self.data, apply=False)
        self.assertEqual(report['catalog_titles']['rewritten'], 1)
        self.assertEqual(self.catalogue_urls(), before)


if __name__ == '__main__':
    unittest.main()
