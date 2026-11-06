import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import hanime_source  # noqa: E402

ROWS = [
    {'name': 'Kotowari 2', 'slug': 'kotowari-2', 'search_titles': 'Kotowari 2 Rules', 'cover_url': 'c2', 'released_at': '2016-01-01'},
    {'name': 'Kotowari 1', 'slug': 'kotowari-1', 'search_titles': 'Kotowari 1 Rules', 'cover_url': 'c1', 'released_at': '2015-01-01'},
    {'name': 'Overflow Season 1', 'slug': 'overflow-season-1', 'search_titles': 'Overflow Season 1', 'cover_url': 'o1', 'released_at': '2020-01-01'},
    {'name': 'Something Else', 'slug': 'something-else', 'search_titles': 'Something Else', 'cover_url': 's', 'released_at': '2019-01-01'},
]


class Response:
    def __init__(self, body):
        self.body = body

    def iter_content(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start:start + size]

    def close(self):
        pass


class Http:
    def __init__(self, rows):
        self.calls = 0
        self.body = json.dumps({'data': rows, 'ads': []}).encode()

    def _open(self, url, headers=None):
        self.calls += 1
        assert url == hanime_source.CATALOG
        return Response(self.body), url


class HanimeSourceTest(unittest.TestCase):
    def setUp(self):
        hanime_source._cache.update(until=0.0, rows=[])

    def test_search_groups_episodes_into_a_series(self):
        results = hanime_source.search('Kotowari', Http(ROWS))
        self.assertEqual([r['title'] for r in results], ['Kotowari'])
        self.assertEqual(results[0]['url'], hanime_source.VIDEO + 'kotowari-1')
        self.assertEqual(results[0]['episodes'], 2)
        self.assertEqual(results[0]['year'], 2015)

    def test_season_compilations_group_under_the_series(self):
        results = hanime_source.search('Overflow', Http(ROWS))
        self.assertEqual([(r['title'], r['episodes']) for r in results], [('Overflow', 1)])

    def test_search_rejects_loose_matches(self):
        self.assertEqual(hanime_source.search('Kono Subarashii Sekai', Http(ROWS)), [])

    def test_episode_list_follows_the_series_order(self):
        episodes = hanime_source.episodes_for(hanime_source.VIDEO + 'kotowari-2', Http(ROWS))
        self.assertEqual([e['number'] for e in episodes], [1, 2])
        self.assertEqual(episodes[1]['url'], hanime_source.VIDEO + 'kotowari-2')

    def test_catalogue_is_cached(self):
        http = Http(ROWS)
        hanime_source.search('Kotowari', http)
        hanime_source.search('Overflow', http)
        self.assertEqual(http.calls, 1)


if __name__ == '__main__':
    unittest.main()
