import json
import unittest
from unittest.mock import Mock

from anistar_source import choices, episode_url, player_page
from site_adapters import inspect_source
from source_parser import BLOCKED, SourceError, parse_page

PLAYER = 'https://anistar.org/test/player2/videoas_p2p_new.php?id=123&hash=published'
ARTICLE = 'https://anistar.org/123-example.html'


def document():
    rows = [
        {'title': 'Серия 1', 'media_id': '11', 'type_dub': '1'},
        {'title': 'Серия 2', 'media_id': '12', 'type_dub': '1'},
        {'title': 'Серия 2 Многоголосая озвучка', 'media_id': '22', 'type_dub': '2'},
    ]
    for row in rows:
        row['files'] = [
            {'title': str(height), 'file': 'https://cdn.example.com/' + row['media_id'] + '/' + str(height) + '.m3u8'}
            for height in (360, 720, 1080)
        ]
        row['files_mp4'] = [{'title': '720', 'file': 'https://cdn.example.com/' + row['media_id'] + '/720.mp4'}]
    return '<script>var playlst=' + json.dumps(rows, ensure_ascii=False) + ';</script>'


class AnistarSourceTests(unittest.TestCase):
    def test_passive_cloudflare_measurement_does_not_hide_a_public_page(self):
        script = '<script>src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"</script>'
        self.assertFalse(BLOCKED.search(script))
        self.assertEqual(parse_page('<title>Public episode</title>' + script, ARTICLE).title, 'Public episode')
        for body in ('<title>Just a moment</title>', '/cdn-cgi/challenge-platform', '/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1', '__cf_chl_tk'):
            with self.assertRaises(SourceError):
                parse_page(body, ARTICLE)

    def test_episode_and_voice_selection_never_mixes_other_streams(self):
        groups = choices(document(), PLAYER)
        self.assertEqual([len(group['episodes']) for group in groups], [2, 1])
        selected = groups[1]['episodes'][0]
        page = parse_page(document(), selected['url'])
        self.assertEqual(selected['number'], 2)
        self.assertTrue(all('/22/' in stream['url'] for stream in page.streams))
        self.assertEqual([stream['quality'] for stream in page.streams], [360, 720, 1080, 720])
        self.assertTrue(all(stream['headers']['Referer'] == selected['url'] for stream in page.streams))
        for value in ('missing', '11&mv_anistar_id=12'):
            with self.assertRaises(SourceError):
                player_page(document(), PLAYER + '&mv_anistar_id=' + value)
        self.assertEqual(episode_url(selected['url'], '11').count('mv_anistar_id='), 1)

    def test_javascript_literals_are_parsed_without_execution_and_urls_are_validated(self):
        source = """<script>const playlst=[{title:'Серия 1',media_id:'7',type_dub:'1',
            // Published public formats, including a rejected private address.
            files:[{title:'720',file:'https://cdn.example.com/7.m3u8'},
                   {title:'1080',file:'https://127.0.0.1/private.m3u8'},],
            files_mp4:[],},]; window.unrelated='ignored';</script>"""
        self.assertEqual(len(player_page(source, PLAYER).streams), 1)
        self.assertIsNone(player_page(source, 'https://other.example.com/embed'))
        malicious = source.replace("media_id:'7'", "media_id:fetch('https://other.example.com/execute')")
        with self.assertRaises(SourceError):
            player_page(malicious, PLAYER)

    def test_inspection_keeps_all_published_episodes_and_the_selected_voice(self):
        responses = {
            ARTICLE: ('<h1>Public anime</h1><iframe src="' + PLAYER + '"></iframe>', ARTICLE, {}),
            PLAYER: (document(), PLAYER, {}),
        }
        http = Mock()
        http.deadline = None
        http.document.side_effect = lambda url, **_: responses[url]
        selected = choices(document(), PLAYER)[1]['url']
        result = inspect_source(ARTICLE, http=http, dub_url=selected)
        self.assertEqual(len(result['dubs']), 2)
        self.assertEqual([entry['number'] for entry in result['episodes']], [2])
        self.assertTrue(result['complete'])
