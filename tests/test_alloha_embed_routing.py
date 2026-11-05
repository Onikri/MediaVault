"""The iframe-only player must not be rejected by a top-level HTTP preflight."""
import unittest
from unittest.mock import Mock,patch
from source_parser import Resolver

class AllohaRoutingTests(unittest.TestCase):
    def test_public_embed_keeps_selected_dub_episode_parent_and_full_quality_ladder(self):
        http=Mock();http.document.side_effect=AssertionError('Plain document preflight must not run for an iframe-only player')
        http.refresh_playback=False
        url='https://embed.thealloha.club/?token_movie=fixture&season=2&episode=3&translation=66';parent='https://publisher.example.com/film'
        streams=[{'url':f'https://cdn.example.com/{q}.m3u8','type':'hls','quality':q,'headers':{'Referer':parent}} for q in [2160,1440,1080,720]]
        with patch('browser_player.extract',return_value={'streams':streams,'subtitles':[]}) as extract:
            page=Resolver(http).resolve(url,referer=parent)
        extract.assert_called_once_with(url,parent,details=True)
        self.assertEqual([s['quality'] for s in page.streams],[2160,1440,1080,720]);http.document.assert_not_called()
    def test_unrelated_domain_never_uses_the_public_embed_adapter(self):
        http=Mock();http.document.return_value=('<video src="https://cdn.example.com/film.mp4"></video>','https://example.com/film',{})
        with patch('browser_player.extract') as extract:
            self.assertTrue(Resolver(http).resolve('https://example.com/film').streams)
        extract.assert_not_called()
