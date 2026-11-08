"""Ranobe browse asks every catalogue for novels only; films browse Kinobox (offline)."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import metadata_catalog as mc


class Requests(unittest.TestCase):
    def setUp(self):
        self.calls, self.original = [], mc.get_json
        mc._cache.clear()
        mc.get_json = lambda url, *, params=None, body=None: self.calls.append((url, params, body)) or ({'data': []} if 'kitsu' in url else [] if 'shikimori' in url else {'data': {'items': []}})

    def tearDown(self):
        mc.get_json = self.original
        mc._cache.clear()

    def test_ranobe_uses_novel_filters(self):
        import metadata_helpers
        original = metadata_helpers.localize
        metadata_helpers.localize = lambda provider, value, kind: value
        try:
            mc._metadata('shikimori', kind='ranobe')
            mc._metadata('kitsu', kind='ranobe')
            mc._metadata('anilist', kind='ranobe')
            mc._metadata('jikan', kind='ranobe', query='overlord')
        except Exception:
            pass
        finally:
            metadata_helpers.localize = original
        urls = {c[0].split('/')[2]: c for c in self.calls}
        self.assertTrue(urls['shikimori.io'][0].endswith('/api/ranobe'))
        self.assertEqual(urls['kitsu.io'][1]['filter[subtype]'], 'novel')
        self.assertIn('format_in:[NOVEL]', urls['graphql.anilist.co'][2]['query'])

    def test_manga_excludes_novels_on_anilist(self):
        try:
            mc._metadata('anilist', kind='manga')
        except Exception:
            pass
        self.assertIn('format_not_in:[NOVEL]', self.calls[0][2]['query'])

    def test_kinobox_popular_search_and_details(self):
        mc._metadata('kinobox', kind='movie')
        mc._metadata('kinobox', kind='tv', page=2)
        mc._metadata('kinobox', kind='movie', query='дюна')
        self.assertEqual(mc._metadata('kinobox', kind='movie', query='дюна', page=2), {'data': {'items': []}})
        mc._metadata('kinobox', kind='movie', identity='409424')
        self.assertEqual(self.calls[0][:2], ('https://fbphdplay.top/api/popular', {'page': 1, 'type': 'films'}))
        self.assertEqual(self.calls[1][:2], ('https://fbphdplay.top/api/popular', {'page': 2, 'type': 'series'}))
        self.assertEqual(self.calls[2][:2], ('https://fbphdplay.top/api/movies/search', {'query': 'дюна'}))
        self.assertEqual(self.calls[3][0], 'https://fbphdplay.top/api/movies/409424')
        with self.assertRaises(mc.SourceError):
            mc._metadata('kinobox', kind='anime')


if __name__ == '__main__':
    unittest.main()
