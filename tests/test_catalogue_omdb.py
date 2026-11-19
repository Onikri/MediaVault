import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from catalogue_omdb import catalogue, load_snapshot


class OmdbCatalogueTest(unittest.TestCase):
    def test_snapshot_lists_films_and_series_with_searchable_linked_metadata(self):
        files = {
            'all_movies': [
                {'id': '19', 'name': 'Unknown Release', 'date': '\\N'},
                {'id': '3', 'name': 'Road Home', 'date': '1945-02-10'},
            ],
            'all_series': [{'id': '6', 'name': 'Evening Stories', 'date': '2011-01-01'}],
            'all_movie_aliases_iso': [{'movie_id': '3', 'name': 'Дорога домой', 'language_iso_639_1': 'ru', 'official_translation': '1'}],
            'movie_links': [{'movie_id': '3', 'source': 'imdbmovie', 'key': 'tt0001234'}],
            'all_categories': [
                {'id': '41', 'root_id': '1', 'parent_id': '1'},
                {'id': '42', 'root_id': '1', 'parent_id': '41'},
                {'id': '45', 'root_id': '8', 'parent_id': '8'},
            ],
            'category_names': [
                {'category_id': '41', 'name': 'Drama', 'language_iso_639_1': 'en'},
                {'category_id': '42', 'name': 'Historical Drama', 'language_iso_639_1': 'en'},
                {'category_id': '45', 'name': 'Road Trip', 'language_iso_639_1': 'en'},
            ],
            'movie_categories': [{'movie_id': '3', 'category_id': category} for category in ('42', '45')],
        }
        snapshot = load_snapshot(files.__getitem__)
        with patch('catalogue_omdb.PAGE_SIZE', 1):
            first = catalogue('movie', {}, snapshot)
            second = catalogue('movie', first['next'], snapshot)
        film = first['rows'][0]
        self.assertEqual(film['title'], 'Дорога домой')
        self.assertEqual(film['titles']['native'], 'Road Home')
        self.assertEqual(film['year'], 1945)
        self.assertEqual(film['genres'], ['Historical Drama', 'Drama'])
        self.assertEqual(film['tags'], ['Road Trip'])
        self.assertEqual(film['ids']['imdb'], 'tt0001234')
        self.assertEqual((first['total'], second['rows'][0]['id'], second['next']), (2, 'omdb:19', None))
        self.assertEqual(catalogue('tv', {}, snapshot)['rows'][0]['id'], 'omdb:6')
