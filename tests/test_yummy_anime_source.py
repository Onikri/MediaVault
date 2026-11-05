import json
import unittest

from source_parser import SourceError, is_alloha_player, public_url
from yummy_anime_source import ORIGIN, REZE_PAGE, inspect


class YummyAnimeSourceTests(unittest.TestCase):
    def test_uses_only_published_alloha_voice_and_exact_video_api(self):
        target = 'https://alloha.yani.tv/?token_movie=public&translation=66'
        html = '<main><div data-id="11541"><h1>История Резе</h1><a href="//myanimelist.net/anime/57555">MAL</a></div></main>'
        rows = [{'iframe_url': target, 'number': '1', 'data': {'dubbing': 'Озвучка Дублированная'}},
                {'iframe_url': target.replace('alloha.yani.tv', 'elsewhere.example'),
                 'number': '1', 'data': {'dubbing': 'Другой'}}]

        class Http:
            def document(self, url, *, headers=None):
                if url == REZE_PAGE:
                    return html, url, {}
                assert url == ORIGIN + '/api/anime/11541/videos'
                assert headers == {'Referer': REZE_PAGE}
                return json.dumps({'response': rows}), url, {}

        result = inspect(REZE_PAGE, Http(), dub_url=target)
        self.assertEqual(result['ids'], {'mal': 57555})
        self.assertEqual([v['name'] for v in result['dubs']], ['Дублированный'])
        self.assertEqual(result['episodes'], [{'number': 1, 'season': 1, 'url': target}])
        self.assertTrue(is_alloha_player(target))
        self.assertFalse(is_alloha_player(target.replace('alloha.yani.tv', 'alloha.yani.tv.example')))
        self.assertEqual(public_url(ORIGIN + '/api/anime/11541/videos', resolve_dns=False),
                         ORIGIN + '/api/anime/11541/videos')
        with self.assertRaises(SourceError):
            public_url(ORIGIN + '/api/anime/11541/edit', resolve_dns=False)
        with self.assertRaises(SourceError):
            inspect(REZE_PAGE, Http(), dub_url=target.replace('66', '79'))
