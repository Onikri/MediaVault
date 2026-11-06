import unittest
from unittest.mock import Mock, patch

from dynamic_video_sources import provider_for
from site_adapters import inspect_source
from source_parser import Resolver, SourceError


class DynamicVideoSourcesTests(unittest.TestCase):
    def test_site_inspection_returns_the_selected_public_episode(self):
        url = 'https://v4.hentasis.me/category/14-episode.html'
        http = Mock()
        http.document.return_value = ('<title>Example</title>', url, {})
        result = inspect_source(url, http=http)
        self.assertEqual(result['provider'], 'hentasis')
        self.assertEqual(result['dubs'][0]['episodes'][0]['url'], url)
        self.assertIsNone(provider_for('https://hentasis.me.example.com/14-episode.html'))
        self.assertIsNone(provider_for('https://hentasis.me/'))

    def test_hentasis_numbered_mirrors_are_recognised(self):
        for url in ('https://v5.hentasis5.top/1079-mujikaku-na-osananajimi.html',
                    'https://hentasis1.top/1034-sister-breeder.html',
                    'https://www.hentasis1.top/1034-sister-breeder.html',
                    'https://v4.hentasis.me/1175-ikusei.html'):
            self.assertEqual(provider_for(url), ('hentasis', 'Hentasis'), url)
        for url in ('https://hentasis5.top.example.com/1-x.html', 'https://nothentasis5.top/1-x.html',
                    'https://v5.hentasis5.top/', 'https://hentasis5.xyz/1-x.html'):
            self.assertIsNone(provider_for(url), url)

    def test_hentasis_checks_range_with_browser_headers_and_rejects_html(self):
        url = 'https://hentasis1.top/123-episode.html'
        stream = {'url': 'https://cdn.example.com/episode.mp4', 'type': 'mp4', 'headers': {'Referer': url}}
        response = Mock(status_code=206, headers={'Content-Range': 'bytes 0-1023/2048', 'Content-Type': 'video/mp4'})
        http = Mock()
        http._open.return_value = (response, stream['url'])
        with patch('browser_player.extract', return_value={'streams': [stream]}) as browser:
            self.assertEqual(Resolver(http).resolve(url).streams, [stream])
            browser.assert_called_once_with(url, None, details=True, mode='mp4')
            http._open.assert_called_once_with(stream['url'], headers=stream['headers'], byte_range='bytes=0-1023')
            response.close.assert_called_once()
            response.headers['Content-Type'] = 'text/html'
            with self.assertRaises(SourceError):
                Resolver(http).resolve(url)

    def test_hanime_browser_runs_only_when_plugin_fails(self):
        url = 'https://hanime.tv/videos/hentai/example-1'
        stream = {'url': 'https://cdn.example.com/episode.m3u8', 'type': 'hls'}
        with patch('hanime_player.extract', return_value=[stream]) as plugin, patch(
            'browser_player.extract', return_value={'streams': [stream]}
        ) as browser:
            self.assertEqual(Resolver(Mock()).resolve(url).streams, [stream])
            browser.assert_not_called()
            plugin.side_effect = SourceError('Plugin did not return a stream')
            self.assertEqual(Resolver(Mock()).resolve(url).streams, [stream])
            browser.assert_called_once_with(url, None, details=True, mode='auto')

    def test_v4_mirror_uses_its_published_hls(self):
        url = 'https://v4.hentasis.me/123-episode.html'
        stream = {'url': 'https://cdn.example.com/episode.m3u8', 'type': 'hls'}
        with patch('browser_player.extract', return_value={'streams': [stream]}) as browser:
            self.assertEqual(Resolver(Mock()).resolve(url).streams, [stream])
            browser.assert_called_once_with(url, None, details=True, mode='hentasis-mirror')
