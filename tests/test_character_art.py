"""Character portraits from every catalogue. Fixtures only: no network, no ML inference."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import character_art as art
import jikan_metadata
from source_parser import SourceError

STUB_SHIKI = '/assets/globals/missing_original.jpg'
MAL_IMG = 'https://cdn.myanimelist.net/images/characters/9/{}.jpg'
ANI_IMG = 'https://s4.anilist.co/file/anilistcdn/character/large/b{}.png'


def role(identity, name, image=STUB_SHIKI, main=False):
    return {'roles': ['Main'] if main else ['Supporting'], 'roles_russian': [], 'character': {'id': identity, 'name': name, 'russian': '', 'image': {'original': image}}}


def jikan_row(identity, name, image, main=False):
    return {'role': 'Main' if main else 'Supporting', 'character': {'mal_id': identity, 'name': name, 'images': {'jpg': {'image_url': image}}}}


def anilist(identity, nodes):
    return {'data': {'Media': {'id': 900000 + int(identity), 'idMal': int(identity), 'characters': {'edges': [
        {'role': 'MAIN' if main else 'SUPPORTING', 'node': {'id': index, 'name': {'full': full, 'native': native, 'alternative': alt}, 'image': {'large': image}}}
        for index, (full, native, alt, image, main) in enumerate(nodes)]}}}}


class Catalogues:
    """Fixture catalogues keyed by (kind, title id); records every call."""
    def __init__(self, roles=None, jikan=None, anilist=None, kitsu=None):
        self.roles, self.jikan, self.anilist, self.kitsu, self.calls = roles or {}, jikan or {}, anilist or {}, kitsu or {}, []

    def metadata(self, provider, *, kind, identity, part=''):
        self.calls.append(('shikimori', kind, identity, part))
        assert provider == 'shikimori' and part == 'roles'
        return self.roles.get((kind, identity), [])

    def jikan_json(self, path, params=None):
        self.calls.append(('jikan', path))
        kind, identity, _ = path.split('/')
        value = self.jikan.get((kind, identity))
        if isinstance(value, Exception):
            raise value
        return {'data': value or []}

    def get_json(self, url, *, params=None, body=None):
        if 'anilist' in url:
            variables = body['variables']
            kind = 'anime' if variables['type'] == 'ANIME' else 'manga'
            self.calls.append(('anilist', kind, str(variables['id'])))
            return self.anilist.get((kind, str(variables['id'])), {'data': {'Media': None}})
        self.calls.append(('kitsu', url))
        if url.endswith('/mappings'):
            kind = params['filter[externalSite]'].split('/')[1]
            item = self.kitsu.get((kind, params['filter[externalId]']))
            return {'included': [{'type': kind, 'id': item[0]}]} if item else {'included': []}
        for (kind, _), (item, rows) in self.kitsu.items():
            if url.endswith(f'/{kind}/{item}/characters'):
                return {'included': [{'type': 'characters', 'attributes': {'malId': mal, 'image': {'original': image}}} for mal, image in rows]}
        return {}

    def __enter__(self):
        art._cache.clear()
        self.patches = [mock.patch.object(art, 'metadata', self.metadata), mock.patch.object(art, 'get_json', self.get_json),
                        mock.patch.object(jikan_metadata, 'jikan_json', self.jikan_json)]
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *_):
        for patch in self.patches:
            patch.stop()
        art._cache.clear()


class PortraitChainTests(unittest.TestCase):
    def test_shikimori_placeholder_takes_mal_portrait_by_character_id(self):
        with Catalogues(roles={('anime', '38000'): [role(146156, 'Tanjirou Kamado', '/system/characters/original/146156.jpg', True), role(246846, 'Blue-Haired Demon')]},
                        jikan={('anime', '38000'): [jikan_row(146156, 'Kamado, Tanjirou', MAL_IMG.format(1), True), jikan_row(246846, 'Blue-Haired Demon', MAL_IMG.format(2))]}) as fake:
            result = art.portraits('anime', '38000')
        self.assertEqual(result, {'portraits': {'246846': {'image': MAL_IMG.format(2), 'source': 'myanimelist', 'match': 'id'}}, 'missing': []})
        self.assertEqual([c[0] for c in fake.calls], ['shikimori', 'jikan'])  # one request per source per title; AniList not needed

    def test_without_mal_portrait_anilist_matches_the_exact_name(self):
        with Catalogues(roles={('anime', '21'): [role(1, 'Tabuhachirou'), role(2, 'Tailor Zombie')]},
                        jikan={('anime', '21'): [jikan_row(1, 'Tabuhachirou', 'https://cdn.myanimelist.net/images/questionmark_23.gif?s=1')]},
                        anilist={('anime', '21'): anilist('21', [('Tabuhachirō', None, [], ANI_IMG.format(1), False),
                                                                 ('Zombie Tailor', None, [], ANI_IMG.format(2), False)])}) as fake:
            result = art.portraits('anime', '21')
        # MAL knows character 1 only with a placeholder; AniList has it under the same normalised name.
        # «Zombie Tailor» = «Tailor Zombie» as an order-free name; nobody else in the title has that name.
        self.assertEqual(result['portraits'], {'1': {'image': ANI_IMG.format(1), 'source': 'anilist', 'match': 'name'},
                                               '2': {'image': ANI_IMG.format(2), 'source': 'anilist', 'match': 'name'}})
        self.assertIn(('anilist', 'anime', '21'), fake.calls)

    def test_jikan_outage_still_reaches_anilist_and_kitsu(self):
        with Catalogues(roles={('anime', '5'): [role(10, 'Ada'), role(11, 'Bob Stone')]},
                        jikan={('anime', '5'): SourceError('down')},
                        anilist={('anime', '5'): anilist('5', [('Bob Stone', None, [], ANI_IMG.format(11), False)])},
                        kitsu={('anime', '5'): ('77', [(10, 'https://media.kitsu.app/characters/images/10/original.jpg')])}):
            result = art.portraits('anime', '5')
        self.assertEqual({k: v['source'] for k, v in result['portraits'].items()}, {'11': 'anilist', '10': 'kitsu'})

    def test_same_name_from_another_title_is_never_taken(self):
        with Catalogues(roles={('anime', '1'): [role(99, 'Hiro')], ('anime', '2'): [role(20, 'Hiro')]},
                        jikan={('anime', '1'): [jikan_row(99, 'Hiro', MAL_IMG.format(99))], ('anime', '2'): []},
                        # AniList answers with a different title for this MAL id: ignored entirely.
                        anilist={('anime', '2'): {'data': {'Media': {'id': 5, 'idMal': 1, 'characters': {'edges': [
                            {'role': 'MAIN', 'node': {'id': 1, 'name': {'full': 'Hiro'}, 'image': {'large': ANI_IMG.format(1)}}}]}}}}}):
            self.assertEqual(art.portraits('anime', '1')['portraits']['99']['source'], 'myanimelist')  # title 1 has its own «Hiro»
            result = art.portraits('anime', '2')
        self.assertEqual(result, {'portraits': {}, 'missing': ['20']})

    def test_ambiguous_names_and_role_conflicts_are_refused(self):
        with Catalogues(roles={('anime', '3'): [role(30, 'Narrator'), role(31, 'Mika Sato', main=True)]},
                        jikan={('anime', '3'): [jikan_row(70, 'Narrator', MAL_IMG.format(70)), jikan_row(71, 'Narrator', MAL_IMG.format(71)),
                                                jikan_row(72, 'Sato, Mika', MAL_IMG.format(72), main=False)]},
                        anilist={('anime', '3'): anilist('3', [])}):
            result = art.portraits('anime', '3')
        self.assertEqual(result['portraits'], {})
        self.assertEqual(sorted(result['missing']), ['30', '31'])

    def test_manga_character_gets_a_portrait(self):
        with Catalogues(roles={('manga', '642'): [role(1001, 'Thorfinn', '/system/characters/original/1001.jpg', True), role(1002, 'Bjorn')]},
                        jikan={('manga', '642'): [jikan_row(1002, 'Bjorn', MAL_IMG.format(1002))]}) as fake:
            self.assertEqual(art.portraits('ranobe', '642')['portraits']['1002']['image'], MAL_IMG.format(1002))
        self.assertEqual(fake.calls[:2], [('shikimori', 'manga', '642', 'roles'), ('jikan', 'manga/642/characters')])

    def test_requested_ids_refresh_saved_placeholders(self):
        with Catalogues(roles={('manga', '7'): [role(1, 'Ann', '/system/characters/original/1.jpg'), role(2, 'Ben')]},
                        jikan={('manga', '7'): [jikan_row(2, 'Ben', MAL_IMG.format(2)), jikan_row(3, 'Cid', MAL_IMG.format(3))]}):
            result = art.portraits('manga', '7', ['1', '2', '3', 'x'])
        self.assertEqual({k: (v['source'], v['image']) for k, v in result['portraits'].items()},
                         {'1': ('shikimori', 'https://shikimori.io/system/characters/original/1.jpg'), '2': ('myanimelist', MAL_IMG.format(2)), '3': ('myanimelist', MAL_IMG.format(3))})

    def test_every_catalogue_placeholder_is_no_picture(self):
        for url in ['https://shikimori.io/assets/globals/missing_original.jpg', 'https://shikimori.io/assets/globals/missing/main.png',
                    'https://cdn.myanimelist.net/images/questionmark_23.gif?s=f7dcbc4a4603d18356d3dfef8abd655c',
                    'https://s4.anilist.co/file/anilistcdn/character/large/default.jpg', 'https://st.kp.yandex.net/images/no-poster.gif',
                    'https://media.kitsu.app/images/original/missing.png', 'https://example.com/a.jpg', 'http://cdn.myanimelist.net/images/characters/1/2.jpg']:
            self.assertEqual(art.real(url), '', url)
        for url in ['https://shikimori.io/system/characters/original/40.jpg?1', MAL_IMG.format(5), ANI_IMG.format('40-default'),
                    'https://avatars.mds.yandex.net/get-kinopoisk-image/1898899/6adbc365-d35f-4607-bd3b-9ea4ae143185/360']:
            self.assertEqual(art.real(url), url, url)

    def test_names_normalise_order_macrons_and_long_vowels_only(self):
        self.assertEqual(art.name_key('Kamado, Tanjirou'), art.name_key('Tanjirō Kamado'))
        self.assertEqual(art.name_key('Yuuko Ichihara'), art.name_key('Ichihara Yūko'))
        self.assertNotEqual(art.name_key('Mika Sato'), art.name_key('Mika Saito'))
        self.assertEqual(art.name_key('1'), '')

    def test_fill_keeps_the_client_profile_format(self):
        characters = [{'id': '1', 'name': 'Анна', 'role': 'Главный герой', 'image': 'https://shikimori.io/system/characters/original/1.jpg', 'description': ''},
                      {'id': '2', 'name': 'Бен', 'role': 'Персонаж', 'image': '', 'description': ''},
                      {'id': '3', 'name': 'Сид', 'role': 'Персонаж', 'image': 'https://shikimori.io/assets/globals/missing_original.jpg', 'description': ''}]
        keys = [set(c) for c in characters]
        with Catalogues(roles={('anime', '9'): [role(1, 'Ann', '/system/characters/original/1.jpg', True), role(2, 'Ben'), role(3, 'Cid')]},
                        jikan={('anime', '9'): [jikan_row(2, 'Ben', MAL_IMG.format(2))]}, anilist={('anime', '9'): anilist('9', [])}):
            art.fill(characters, 'anime', '9')
        self.assertEqual([set(c) for c in characters], keys)
        self.assertEqual([c['image'] for c in characters], ['https://shikimori.io/system/characters/original/1.jpg', MAL_IMG.format(2), ''])


class LibraryProfileTests(unittest.TestCase):
    def test_server_profile_fills_portraits_and_keeps_its_format(self):
        import library_enrichment as enrichment
        roles = [role(1, 'Ann', '/system/characters/original/1.jpg', True), role(2, 'Ben')]
        roles[0]['roles_russian'] = ['Главная роль']

        def shikimori(provider, *, kind, identity, part=''):
            if kind == 'character':
                return {'id': identity, 'description': 'Описание', 'seyu': []}
            return {'roles': roles, 'related': [], 'screenshots': []}[part] if part else {'id': 7, 'russian': 'Тайтл', 'description': 'Описание тайтла', 'kind': 'manga', 'image': {}}
        with Catalogues(jikan={('manga', '7'): [jikan_row(2, 'Ben', MAL_IMG.format(2))]}) as fake, \
                mock.patch.object(enrichment, 'metadata', shikimori), mock.patch('title_ratings.known_ratings', return_value=None), \
                mock.patch('poster_assets.posters', return_value={}):
            profile = enrichment.load_profile('7', 'manga')
        self.assertEqual([set(c) for c in profile['characters']], [{'id', 'name', 'role', 'image', 'description', 'actors', 'voiceActors'}, {'id', 'name', 'role', 'image', 'description'}])
        self.assertEqual([c['image'] for c in profile['characters']], ['https://shikimori.io/system/characters/original/1.jpg', MAL_IMG.format(2)])
        self.assertNotIn(('shikimori', 'manga', '7', 'roles'), fake.calls)  # the roles already loaded are reused


class CharacterDossierTests(unittest.TestCase):
    def test_dossier_placeholder_never_replaces_a_found_portrait(self):
        import character_profile
        mal = {'mal_id': 42, 'images': {'jpg': {'image_url': MAL_IMG.format(42)}}}
        self.assertEqual(character_profile.build('42', {'id': 42, 'image': {'original': STUB_SHIKI}}, mal)['image'], MAL_IMG.format(42))
        self.assertEqual(character_profile.build('42', {'id': 42}, {'mal_id': 42, 'images': {'jpg': {'image_url': 'https://cdn.myanimelist.net/images/questionmark_23.gif'}}})['image'], '')
        self.assertEqual(character_profile.build('42', {'id': 42, 'image': {'original': '/system/characters/original/42.jpg?1'}}, mal)['image'],
                         'https://shikimori.io/system/characters/original/42.jpg?1')


class KinopoiskPhotoTests(unittest.TestCase):
    def setUp(self):
        art._cache.clear()

    def test_only_a_redirect_to_a_kinopoisk_photo_counts(self):
        answers = {'27459': (302, 'https://avatars.mds.yandex.net/get-kinopoisk-image/1898899/6adbc365-d35f-4607-bd3b-9ea4ae143185/360'),
                   '99': (302, 'https://st.kp.yandex.net/images/no-poster.gif'), '5': (200, '')}
        seen = []

        class Response:
            def __init__(self, status, location): self.status_code, self.headers = status, {'Location': location}

        class Session:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def head(self, url, **kw):
                self.kw = kw; seen.append((url, kw['allow_redirects']))
                return Response(*answers[url.rsplit('_', 1)[1][:-4]])
        with mock.patch('requests.Session', Session), mock.patch.object(art.time, 'sleep'):
            result = art.kinopoisk_photos(['27459', '99', '5', '../x', '27459'])
            again = art.kinopoisk_photos(['27459'])
        self.assertEqual(result, {'27459': answers['27459'][1]})
        self.assertEqual(again, result)
        self.assertEqual(len(seen), 3)  # cached, deduplicated, invalid ids never requested
        self.assertTrue(all(url.startswith('https://st.kp.yandex.net/images/actor_iphone/iphone360_') and not follow for url, follow in seen))


class ArtworkHostTests(unittest.TestCase):
    def test_proxy_hosts_are_exact_and_shared_cdns_are_namespaced(self):
        import artwork
        self.assertTrue(artwork.allowed('https://avatars.mds.yandex.net/get-kinopoisk-image/1/2/360'))
        self.assertFalse(artwork.allowed('https://avatars.mds.yandex.net/get-direct/1/2/orig'))
        self.assertFalse(artwork.allowed('https://cdn.myanimelist.net.evil.example/images/a.jpg'))
        self.assertFalse(artwork.allowed('https://user@cdn.myanimelist.net/images/a.jpg'))
        self.assertFalse(artwork.allowed('https://cdn.myanimelist.net:8443/images/a.jpg'))
        self.assertTrue(artwork.allowed('https://cdn.myanimelist.net/images/characters/9/1.jpg'))
        self.assertTrue(artwork.allowed('https://s4.anilist.co/file/anilistcdn/character/large/b1.png'))


if __name__ == '__main__':
    unittest.main()
