"""MangaDex catalogue walk past the 10 000 offset limit, on recorded API records (no network)."""
import copy
import json
import sqlite3
import sys
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import manga_mangadex_native as dex
import manga_native_sources
from catalogue_sources import base_sources, fetch
from source_parser import SourceError, SourceRateLimitError

# A real /manga?order[createdAt]=asc&includes[]=cover_art page, recorded 2026-11-24.
RECORDED = json.loads((Path(__file__).parent / 'fixtures/mangadex/manga-created-asc.json').read_text(encoding='utf-8'))
TEMPLATE = RECORDED['data'][0]
PROFILES = {lang: next(a for a in dex.SOURCES if a.LANGUAGE == lang) for lang in ('ru', 'all', 'ja')}


def uuid(number):
    return f'{number:08x}-0000-4000-8000-{number:012x}'


class FakeApi:
    """The /manga contract the walk relies on: inclusive createdAtSince, asc order, 10 000 window."""

    def __init__(self, count, tie_at=None, tie_size=0):
        start, self.rows = datetime(2018, 1, 18), []
        for number in range(count):
            # One second holds tie_size titles, more than a page; others have their own second
            # (and some pairs share one) so the edge skip list is exercised.
            second = tie_at if tie_at is not None and tie_at <= number < tie_at + tie_size else number - number % 3 // 2
            row = copy.deepcopy(TEMPLATE)
            row['id'] = uuid(number + 1)
            row['attributes']['createdAt'] = (start + timedelta(seconds=second)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
            self.rows.append(row)
        self.calls = []

    def __call__(self, url, http):
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        self.calls.append(query)
        limit, offset = int(query['limit'][0]), int(query['offset'][0])
        if offset + limit > dex.MAX_OFFSET:
            raise SourceError('HTTP 400: offset + limit must be <= 10000')
        rows = self.rows
        if 'createdAtSince' in query:
            since = query['createdAtSince'][0]
            rows = [row for row in rows if row['attributes']['createdAt'][:19] >= since]
        return {'result': 'ok', 'data': rows[offset:offset + limit], 'total': len(rows), 'limit': limit, 'offset': offset}


class WalkTests(unittest.TestCase):
    def setUp(self):
        self.pace = patch.object(dex.PACE, 'interval', 0)
        self.pace.start()

    def tearDown(self):
        self.pace.stop()

    def walk(self, api, adapter):
        found, cursor, pages = [], {}, 0
        with patch.object(dex, 'get', api):
            while True:
                rows, cursor = adapter.index_page(SimpleNamespace(deadline=None), cursor)
                found += [row['ids']['mangadex'] for row in rows]
                pages += 1
                self.assertLess(pages, 400)
                if cursor is None:
                    return found
                # The cursor is stored as JSON in catalogue_jobs between restarts.
                cursor = json.loads(json.dumps(cursor))
                self.assertLessEqual(len(cursor['seen']), dex.WALK_LIMIT)

    def test_walk_reads_every_title_beyond_ten_thousand(self):
        api = FakeApi(12345)
        found = self.walk(api, PROFILES['all'])
        self.assertEqual(sorted(set(found)), sorted(row['id'] for row in api.rows))
        self.assertLess(len(found) - len(set(found)), 50)
        self.assertTrue(all(int(q['offset'][0]) + int(q['limit'][0]) <= dex.MAX_OFFSET for q in api.calls))
        self.assertTrue(any(q.get('createdAtSince', [''])[0] > '2018-01-18T02:46' for q in api.calls))

    def test_second_with_more_than_a_page_pages_inside_its_window(self):
        api = FakeApi(1000, tie_at=300, tie_size=250)
        found = self.walk(api, PROFILES['all'])
        self.assertEqual(set(found), {row['id'] for row in api.rows})
        self.assertTrue(any(int(q['offset'][0]) > 0 for q in api.calls))

    def test_walk_filters_language_and_asks_for_every_rating_and_cover(self):
        api = FakeApi(5)
        with patch.object(dex, 'get', api):
            PROFILES['ru'].index_page(SimpleNamespace(deadline=None), {})
            PROFILES['all'].index_page(SimpleNamespace(deadline=None), {})
        ru, every = api.calls
        self.assertEqual(ru['contentRating[]'], ['safe', 'suggestive', 'erotica', 'pornographic'])
        self.assertEqual(ru['includes[]'], ['cover_art'])
        self.assertEqual(ru['order[createdAt]'], ['asc'])
        self.assertEqual(ru['availableTranslatedLanguage[]'], ['ru'])
        self.assertNotIn('availableTranslatedLanguage[]', every)

    def test_bad_cursor_is_refused(self):
        for cursor in ({'since': '2018-01-18 00:00'}, {'since': '2018-01-18T00:00:00', 'offset': 9950}, {'offset': '5'}):
            with self.assertRaises(SourceError):
                PROFILES['all'].index_page(SimpleNamespace(deadline=None), cursor)


class RowTests(unittest.TestCase):
    def test_recorded_row_has_tags_genres_cover_format_and_link(self):
        row = PROFILES['all'].row(TEMPLATE)
        a = TEMPLATE['attributes']
        self.assertEqual(row['genres'], [t['attributes']['name']['en'] for t in a['tags']
                                         if t['attributes']['group'] == 'genre'])
        self.assertIn('Long Strip', row['tags'])
        self.assertIn('Supernatural', row['tags'])
        self.assertEqual(row['format'], 'manhwa')
        self.assertEqual(row['readingMode'], 'scroll')
        cover = next(r['attributes']['fileName'] for r in TEMPLATE['relationships'] if r['type'] == 'cover_art')
        self.assertEqual(row['cover'], f'https://uploads.mangadex.org/covers/{TEMPLATE["id"]}/{cover}.256.jpg')
        self.assertIn('/title/' + TEMPLATE['id'], row['sourceUrl'])
        self.assertEqual((row['year'], row['status'], row['adult']), (a['year'], a['status'], False))
        self.assertTrue(set(row['aliases']) >= {v for alt in a['altTitles'] for v in alt.values()})

    def test_original_language_and_rating_map_to_format_and_adult(self):
        for original, rating, media, adult in (('ja', 'pornographic', 'manga', True), ('zh', 'erotica', 'manhua', True),
                                               ('ko', 'suggestive', 'manhwa', False)):
            item = copy.deepcopy(TEMPLATE)
            item['attributes'].update(originalLanguage=original, contentRating=rating)
            row = PROFILES['ja'].row(item)
            self.assertEqual((row['format'], row['adult'], row['age']), (media, adult, 18 if adult else None))


class PolitenessTests(unittest.TestCase):
    def test_pace_and_retry_after_hold_every_caller(self):
        self.assertGreaterEqual(dex.API_PACE_SECONDS, 0.4)
        self.assertEqual(dex.PACE.interval, dex.API_PACE_SECONDS)
        self.assertIn('MediaVault', dex.DEX_USER_AGENT)

        def limited(url, http):
            raise SourceRateLimitError('7')

        with patch.object(dex.PACE, 'interval', 0), patch.object(dex, 'get', limited), \
                patch.object(dex.PACE, 'next_request', 0):
            with self.assertRaises(SourceRateLimitError):
                dex.request(SimpleNamespace(deadline=None), '/manga')
            self.assertGreater(dex.PACE.next_request - dex.time.monotonic(), 6)


class QueueTests(unittest.TestCase):
    INSTALLED = {'id': PROFILES['ru'].SOURCE_ID, 'name': 'MangaDex', 'lang': 'ru', 'baseUrl': 'https://mangadex.org',
                 'isNsfw': True}

    def test_activated_profile_gets_a_catalogue_job_with_a_stored_cursor(self):
        adapter = PROFILES['ru']
        with patch.dict(manga_native_sources.ADAPTERS, {adapter.SOURCE_ID: adapter}):
            jobs = [j for j in base_sources([self.INSTALLED]) if j['type'] == 'bridge']
            self.assertEqual([(j['domain'], j['source']['id']) for j in jobs], [('mangadex.org', adapter.SOURCE_ID)])
            from catalogue_indexer import Indexer
            from manga_catalog_index import initialize
            import content_catalog
            db = sqlite3.connect(':memory:', check_same_thread=False)
            initialize(db)
            content_catalog.initialize(db)
            indexer = Indexer(SimpleNamespace(db=db, lock=threading.RLock()), fetch=lambda spec, cursor: {})
            indexer.seed([self.INSTALLED])
            queued = db.execute("SELECT cursor,state FROM catalogue_jobs WHERE kind='bridge' AND host='mangadex.org'").fetchall()
            self.assertEqual(queued, [('{"page":1}', 'queued')])
            api = FakeApi(150)
            with patch.object(dex, 'get', api), patch.object(dex.PACE, 'interval', 0):
                first = fetch(jobs[0], {'page': 1})
                second = fetch(jobs[0], json.loads(json.dumps(first['next'])))
            self.assertEqual(len(first['rows']), 100)
            self.assertEqual(first['next']['page'], 2)
            self.assertEqual(second['next'], None)
            ids = {r['ids']['mangadex'] for r in first['rows'] + second['rows']}
            self.assertEqual(ids, {row['id'] for row in api.rows})
            db.close()

    def test_activated_search_keeps_the_russian_alias_route(self):
        import manga_discovery
        adapter, source = PROFILES['ru'], {**self.INSTALLED}
        alias = [{'url': 'https://mangadex.org/title/' + TEMPLATE['id'] + '?lang=ru', 'title': 'Башня Бога'}]
        with patch.dict(manga_native_sources.ADAPTERS, {adapter.SOURCE_ID: adapter}), \
                patch.object(manga_native_sources, 'search', return_value=[]) as direct, \
                patch.object(manga_discovery, 'native_search_source', return_value=alias) as fallback:
            self.assertEqual(manga_discovery.search_source(source, 'Башня Бога'), alias)
            self.assertEqual(manga_discovery.search_source(source, 'Tower of God'), [])
        self.assertEqual(direct.call_count, 2)
        fallback.assert_called_once_with(source, 'Башня Бога')

    def test_unactivated_profile_is_not_queued(self):
        adapters = {sid: a for sid, a in manga_native_sources.ADAPTERS.items() if sid != PROFILES['ru'].SOURCE_ID}
        with patch.object(manga_native_sources, 'ADAPTERS', adapters):
            self.assertFalse([j for j in base_sources([self.INSTALLED]) if j['type'] == 'bridge'])


if __name__ == '__main__':
    unittest.main()
