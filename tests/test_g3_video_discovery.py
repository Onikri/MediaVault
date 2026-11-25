"""G3: AniList/OMDb metadata cards find a playing source through /sources/discover; no network.

Pairs are the ones measured live on 2026-11-26 (out/G3/discovery.csv): an anime
site dates a TV season by its last airing year («Паразит … [1-24 из 24]» 2015
for the 2014 card), so the exact same name one year apart is the same work,
while a film, a sequel season or a far year under a similar name is not.
Sites measured dead or with a search that ignores the query are left out of the
search (a catalogued page of theirs still opens), hentai sites are searched for
adult cards only, the owner-token Kodik API is not part of discovery, and a card
whose Shikimori name did not reach the client is searched by its Russian name.
"""
import sys, unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import source_discovery
from player_catalog import choice
from site_adapters import BY_ID, SITES
from source_parser import SourceError
from title_identity import match_title

FIXTURES = Path(__file__).parent / 'fixtures'
SEARCH = (FIXTURES / 'animevost-search-parasyte.html').read_text(encoding='utf-8')
TV = 'https://animevost.org/tip/tv/987-kiseijuu-sei-no-kakuritsu.html'
PARASYTE = {'id': 'anilist:20623', 'kind': 'anime', 'year': 2014, 'startDate': '2014-10-09', 'format': 'TV',
            'ids': {'anilist': '20623', 'mal': '22535'}, 'title': 'Паразит: Учение о жизни',
            'titles': {'en': 'Parasyte -the maxim-', 'native': '寄生獣 セイの格率', 'ru': 'Паразит: Учение о жизни'},
            'aliases': ['Parasyte -the maxim-', '寄生獣 セイの格率', 'Паразит: Учение о жизни', 'Kiseijuu: Sei no Kakuritsu']}
JUJUTSU = {'kind': 'anime', 'year': 2020, 'title': 'Магическая битва', 'aliases': ['JUJUTSU KAISEN', 'Магическая битва', 'Sorcery Fight']}
EMPTY = {'name': 'x', 'status': 'empty', 'complete': True, 'sources': []}


class Http:
    def __init__(self, pages):
        self.pages = pages; self.calls = []; self.deadline = None
    def document(self, url, headers=None, **_):
        self.calls.append(url)
        for prefix, text in self.pages.items():
            if url.startswith(prefix):
                return text, url, {}
        raise SourceError('Источник вернул HTTP 404.')
    def close(self):
        pass


class NeighbouringYear(unittest.TestCase):
    def test_measured_pairs(self):
        near = lambda card, name, year, slack=1: match_title(card, {'aliases': [name], 'year': year}, year_slack=slack)
        # Accepted only with the slack and only under the very same name.
        self.assertEqual(near(PARASYTE, 'Паразит / Kiseijuu: Sei no Kakuritsu [1-24 из 24]', 2015), (True, 'exact_title_near_year'))
        self.assertEqual(near(JUJUTSU, 'Магическая битва / Jujutsu Kaisen [1-24 из 24]', 2021), (True, 'exact_title_near_year'))
        panzer = {'kind': 'anime', 'year': 2026, 'title': 'Девушки и танки: Операция «Больше любви!»', 'aliases': []}
        self.assertEqual(near(panzer, 'Девушки и танки: Операция «Больше любви!»', 2025), (True, 'exact_title_near_year'))
        self.assertEqual(near(PARASYTE, 'Паразит / Kiseijuu: Sei no Kakuritsu [1-24 из 24]', 2015, 0), (False, 'different_year'))
        # A film, a sequel season, a zero film and a far year stay different works.
        for name, year in [('Магическая битва (фильм) / Gekijouban Jujutsu Kaisen 0 [1 из 1]', 2021), ('Магическая битва 0', 2021),
                           ('Магическая битва (второй сезон) / Jujutsu Kaisen 2nd Season [1-23 из 23]', 2021),
                           ('Магическая битва 2 сезон', 2019), ('Магическая битва / Jujutsu Kaisen', 2023)]:
            self.assertEqual(near(JUJUTSU, name, year), (False, 'different_year'), name)
        bleach = {'kind': 'anime', 'year': 2004, 'title': 'Блич', 'aliases': ['Bleach']}
        self.assertEqual(near(bleach, 'Блич / Bleach', 2018), (False, 'different_year'))
        # The default (manga, ranobe and every other caller) is unchanged.
        self.assertEqual(match_title(JUJUTSU, {'aliases': ['Магическая битва'], 'year': 2021}), (False, 'different_year'))


class Discover(unittest.TestCase):
    def start(self, sites, pages, inspect=None, **extra):
        self.searched = []
        real = source_discovery.search_site
        def search(site, query, http=None):
            self.searched.append((site.id, query))
            return real(site, query, http=Http(pages))
        self.kodik = MagicMock(return_value=EMPTY)
        self.inspected = []
        def inspect_source(url, **kw):
            self.inspected.append(url)
            return inspect(url)
        guards = [patch.object(source_discovery, 'SITES', sites), patch('kodik_api.discover', self.kodik),
                  patch('kinobox_source.discover', return_value={**EMPTY, 'provider': 'kinobox'}),
                  patch('source_index.save'), patch.dict(source_discovery._cache, {}, clear=True),
                  patch.object(source_discovery, 'index_anchors', lambda selected: {}),
                  patch.object(source_discovery, 'search_site', search),
                  patch.object(source_discovery, 'inspect_source', inspect_source), *extra.get('more', [])]
        for guard in guards:
            guard.start(); self.addCleanup(guard.stop)

    def test_search_candidates_match_and_inspect_a_season_dated_a_year_later(self):
        page = lambda url: {'provider': 'animevost', 'url': url, 'title': 'Паразит / Kiseijuu: Sei no Kakuritsu [1-24 из 24]', 'year': 2015,
                            'dubs': [choice('AnimeVost', url + '#1', player='AnimeVost', episodes=[{'number': n, 'url': url + '#' + str(n)} for n in range(1, 25)])],
                            'episodes': [], 'complete': True}
        self.start([BY_ID['animevost']], {'https://animevost.org/index.php': SEARCH}, page)
        result = source_discovery._discover(PARASYTE, refresh=True)
        [source] = result['sources']
        self.assertEqual((source['url'], source['matchEvidence'], len(source['dubs'])), (TV, 'exact_title_near_year', 1))
        # The film and «Серые» of the same answer are never opened.
        self.assertEqual(self.inspected, [TV])
        self.assertEqual(self.searched[0], ('animevost', 'Паразит: Учение о жизни'))
        self.assertEqual({p['provider']: p['status'] for p in result['providers']}, {'animevost': 'ok', 'kinobox': 'empty'})

    def test_a_page_of_another_year_still_fails_the_verification(self):
        page = lambda url: {'provider': 'animevost', 'url': url, 'title': 'Паразит', 'year': 2017, 'dubs': [choice('AnimeVost', url + '#1')], 'episodes': [], 'complete': True}
        self.start([BY_ID['animevost']], {'https://animevost.org/index.php': SEARCH}, page)
        self.assertEqual(source_discovery._discover(PARASYTE, refresh=True)['sources'], [])

    def test_films_and_serials_keep_the_exact_year(self):
        star = {'kind': 'movie', 'year': 1978, 'title': 'Star Trek: The Motion Picture', 'ids': {'imdb': 'tt0079945'}}
        listing = ('<div id="dle-content"><div class="short"><a class="short_title" href="https://eneyida.tv/1-star-trek.html">Зоряний шлях: Фільм</a>'
                   '<div class="short_subtitle">1979 • Star Trek: The Motion Picture</div></div></div>')
        self.start([BY_ID['eneyida']], {'https://eneyida.tv/': listing}, lambda url: self.fail('a film of another year was opened'))
        self.assertEqual(source_discovery._discover(star, refresh=True)['sources'], [])
        self.assertTrue(self.searched)

    def test_kodik_token_api_is_not_part_of_discovery(self):
        self.start([BY_ID['animevost']], {}, lambda url: self.fail())
        result = source_discovery._discover(PARASYTE, refresh=True)
        self.kodik.assert_not_called()
        self.assertNotIn('kodik', {p['provider'] for p in result['providers']})

    def test_placeholder_is_never_searched_and_the_russian_name_comes_by_mal_id(self):
        card = {'id': 'anilist:1', 'kind': 'anime', 'year': 2025, 'ids': {'anilist': '1', 'mal': '61994'},
                'title': 'Название уточняется', 'titles': {'en': 'Azarashi no Eru Aru', 'ru': 'Название уточняется'},
                'aliases': ['Azarashi no Eru Aru', 'あざらしのえるあーる', 'Название уточняется']}
        shikimori = MagicMock(return_value={'id': 61994, 'russian': 'Тюлень Эру-Ару', 'name': 'Azarashi no Eru Aru', 'english': [], 'synonyms': []})
        self.start([BY_ID['animevost']], {}, lambda url: self.fail(), more=[patch('metadata_catalog.metadata', shikimori)])
        source_discovery._discover(card, refresh=True)
        queries = [q for _, q in self.searched]
        self.assertEqual(queries[0], 'Тюлень Эру-Ару')
        self.assertNotIn('Название уточняется', queries)
        shikimori.assert_called_once_with('shikimori', identity='61994', kind='anime')
        # A card that already has its Russian name never asks Shikimori.
        shikimori.reset_mock(); source_discovery.search_card(PARASYTE); shikimori.assert_not_called()

    def test_shikimori_failure_leaves_the_card_names(self):
        with patch('metadata_catalog.metadata', side_effect=SourceError('Каталог ограничил частоту запросов.')):
            card = source_discovery.search_card({**JUJUTSU, 'title': 'JUJUTSU KAISEN', 'aliases': ['JUJUTSU KAISEN'], 'ids': {'mal': '40748'}})
        self.assertEqual(card['title'], 'JUJUTSU KAISEN')


class Sites(unittest.TestCase):
    ids = staticmethod(lambda sites: [s.id for s in sites])

    def test_dead_sites_and_broken_searches_are_left_out_with_a_reason(self):
        for kind in ('anime', 'movie', 'tv'):
            self.assertFalse(set(self.ids(source_discovery.discovery_sites(kind))) & set(source_discovery.OFF))
        self.assertTrue(all(source_discovery.OFF.values()))
        self.assertTrue(set(source_discovery.OFF) <= {s.id for s in SITES})
        # A catalogued page of such a site still opens.
        self.assertIn('hentasis', self.ids(source_discovery.discovery_sites('anime', None, {'hentasis': ['https://v5.hentasis5.top/x']})))

    def test_order_and_adult_sites(self):
        plain = self.ids(source_discovery.discovery_sites('anime', False))
        self.assertEqual(plain[:4], ['anilibria', 'animedia', 'yummy', 'animejoy'])
        self.assertFalse(set(plain) & source_discovery.ADULT)
        adult = self.ids(source_discovery.discovery_sites('anime', True))
        self.assertTrue(set(adult[:6]) <= source_discovery.ADULT)
        self.assertIn('anilibria', adult)
        unknown = self.ids(source_discovery.discovery_sites('anime', None))
        self.assertEqual(unknown[0], 'anilibria')
        self.assertTrue(set(unknown[-6:]) <= source_discovery.ADULT)
        self.assertEqual(self.ids(source_discovery.discovery_sites('movie', False)), ['eneyida', 'uaserials'])
        # An indexed hentai page opens even when the client marks the card not adult.
        self.assertIn('ohentai', self.ids(source_discovery.discovery_sites('anime', False, {'ohentai': ['https://ohentai.org/x']})))


if __name__ == '__main__':
    unittest.main()
