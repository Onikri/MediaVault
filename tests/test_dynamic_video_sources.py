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

    def test_hentasis_search_reads_titles_and_years_and_skips_dead_mirrors(self):
        from dynamic_video_sources import search_hentasis
        from site_adapters import BY_ID, search_site
        from title_identity import match_title
        page = ('<html><body><div id="dle-content"><a class="carou img-box" href="https://v5.hentasis5.top/1056-other.html">'
                '<div class="rel-title">Other / Other (2026г.)</div></a>'
                '<a class="sres-wrap clearfix" href="https://v5.hentasis5.top/1070-hamehara-sore-sekuhara-desu.html">'
                '<div class="sres-img"><img src="http://v4.hentasis5.top/t.jpg" alt=""><div class="sres-date">8-07-2026, 22:17</div></div>'
                '<div class="sres-text"><h2>Хамехара: Это же сексуальное домогательство! / Hamehara: Sore sekuhara desu (2023г.)</h2></div></a>'
                '</div></body></html>')
        http = Mock()

        def document(url, **_):
            if url.startswith('https://v5.hentasis5.top/'):
                raise SourceError('down')
            return page.replace('v5.hentasis5.top/1', 'hentasis1.top/1'), url, {}
        http.document.side_effect = document
        rows = search_hentasis('Hamehara', http)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['url'], 'https://hentasis1.top/1070-hamehara-sore-sekuhara-desu.html')
        self.assertEqual(rows[0]['title'], 'Хамехара: Это же сексуальное домогательство!')
        self.assertEqual(rows[0]['aliases'][1], 'Hamehara: Sore sekuhara desu')
        self.assertEqual(rows[0]['year'], 2023, 'the year comes from the title, not the publication date')
        selected = {'title': 'Хамэхара: Это же сексуальное домогательство!', 'aliases': ['Hamehara: Sore Sekuhara desu!'],
                    'kind': 'anime', 'year': 2023}
        self.assertTrue(match_title(selected, {**rows[0], 'kind': 'anime'})[0])
        http.document.side_effect = lambda url, **_: (page, url, {})
        result = search_site(BY_ID['hentasis'], 'Hamehara', http=http)
        self.assertEqual((result['status'], result['results'][0]['provider']), ('ok', 'hentasis'))
        http.document.side_effect = SourceError('all down')
        with self.assertRaises(SourceError):
            search_hentasis('Hamehara', http)
