"""HanimeTV through the owner's Worker: fixed requests, validated answers."""
from pathlib import Path
import json
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))

import hanime_relay
import source_parser
from source_parser import PublicHttp, SourceAccessError, SourceError

EPISODE = 'https://hanime.tv/videos/hentai/example-episode-1'
PLAYLIST = 'https://hanime.tv/hls/2491/' + 'a1B2' * 20
PLAYLIST_TEXT = ('#EXTM3U\n#EXT-X-TARGETDURATION:25\n#EXT-X-KEY:METHOD=AES-128,URI="https://ct.htv-services.com/sign.bin"\n'
                 '#EXTINF:21.4,\nhttps://p24.htv-elidibus.com/2/4/9/1/v1x/segs/b0/2/abc.html\n#EXT-X-ENDLIST\n')
SECRET = 'x' * 40
ENV = {'HANIME_RELAY_URL': 'https://relay.example.workers.dev', 'HANIME_RELAY_SECRET': SECRET}


class Player:
    sealed = []

    @classmethod
    def _generate_credentials_local(cls):
        return 'f' * 64, 1793980000

    @classmethod
    def _digest_token(cls, value):
        cls.sealed.append(value)
        return 'sealed'

    @classmethod
    def _parse_token(cls, value):
        return json.loads(value)


class Response:
    def __init__(self, status, body=b'', headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.raw = self
        self.body = body

    def read(self, size=-1, decode_content=False):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **options):
        self.calls.append((method, url, options))
        return self.responses.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def token(sources):
    return {'x-token': json.dumps({'sources': sources})}


class HanimeRelayTests(unittest.TestCase):
    def relay(self, *responses):
        session = Session(responses)
        patches = [mock.patch.dict('os.environ', ENV), mock.patch.object(hanime_relay, 'session', lambda: session),
                   mock.patch('hanime_player.extractor_class', lambda: Player)]
        for value in patches:
            value.start()
            self.addCleanup(value.stop)
        return session

    def test_settings_require_https_origin_and_long_secret(self):
        with mock.patch.dict('os.environ', ENV):
            self.assertEqual(hanime_relay.settings(), ('https://relay.example.workers.dev', SECRET))
        for url, secret in (('http://relay.example', SECRET), ('https://relay.example/path', SECRET),
                            ('https://relay.example', 'short'), ('', SECRET)):
            with mock.patch.dict('os.environ', {'HANIME_RELAY_URL': url, 'HANIME_RELAY_SECRET': secret}):
                self.assertIsNone(hanime_relay.settings(), url)

    def test_signed_handshake_returns_only_free_hanime_playlists(self):
        session = self.relay(Response(200, b'{"status":"OK"}', token([
            {'kind': 'normal', 'label': '720p', 'src': PLAYLIST},
            {'kind': 'normal', 'height': 480, 'src': PLAYLIST.replace('a1B2', 'c3D4', 1)},
            {'kind': 'premium', 'label': '1080p', 'src': PLAYLIST.replace('a1B2', 'e5F6', 1)},
            {'kind': 'normal', 'label': '360p', 'src': 'https://evil.example/hls/1/' + 'a' * 40},
        ])))
        streams = hanime_relay.resolve(EPISODE)
        self.assertEqual([(s['quality'], s['url']) for s in streams],
                         [(720, PLAYLIST), (480, PLAYLIST.replace('a1B2', 'c3D4', 1))])
        self.assertEqual(streams[0]['headers']['Referer'], 'https://hanime.tv/')
        method, url, options = session.calls[0]
        self.assertEqual((method, url), ('POST', 'https://relay.example.workers.dev/handshake'))
        self.assertEqual(options['headers']['Authorization'], 'Bearer ' + SECRET)
        self.assertEqual(options['headers']['X-Signature-Version'], 'web2')
        self.assertEqual(json.loads(options['data']), {'token': 'sealed'})
        self.assertEqual(Player.sealed[-1]['slug'], 'example-episode-1')
        self.assertFalse(options['allow_redirects'])

    def test_failures_are_reported_not_retried(self):
        self.relay(Response(403, b'challenge', {'x-upstream-challenge': '1'}))
        with self.assertRaises(SourceAccessError):
            hanime_relay.resolve(EPISODE)
        self.relay(Response(401, b'Unauthorized'))
        with self.assertRaisesRegex(SourceError, 'HANIME_RELAY_SECRET'):
            hanime_relay.resolve(EPISODE)
        self.relay(Response(200, b'{}', token([{'kind': 'premium', 'src': PLAYLIST}])))
        with self.assertRaisesRegex(SourceError, 'бесплатный'):
            hanime_relay.resolve(EPISODE)
        with self.assertRaises(SourceError):
            hanime_relay.slug('https://hanime.tv/browse/trending')

    def test_without_relay_hanime_explains_the_block_without_a_headless_browser(self):
        from dynamic_video_sources import resolve_dynamic
        with mock.patch.dict('os.environ', {'HANIME_RELAY_URL': '', 'HANIME_RELAY_SECRET': ''}), \
                mock.patch('hanime_player.extract', side_effect=SourceAccessError('blocked')), \
                mock.patch('browser_player.extract') as browser:
            with self.assertRaisesRegex(SourceError, 'HANIME_RELAY_URL'):
                resolve_dynamic(mock.Mock(), EPISODE, None, 'x', provider='hanime')
            browser.assert_not_called()

    def test_with_relay_hanime_never_tries_the_blocked_direct_path(self):
        from dynamic_video_sources import resolve_dynamic
        self.relay(Response(200, b'{}', token([{'kind': 'normal', 'label': '720p', 'src': PLAYLIST}])))
        with mock.patch('hanime_player.extract') as direct:
            page = resolve_dynamic(mock.Mock(), EPISODE, None, 'Эпизод', provider='hanime')
            direct.assert_not_called()
        self.assertEqual(page.streams[0]['url'], PLAYLIST)

    def test_public_http_reads_only_hanime_playlists_through_the_worker(self):
        session = self.relay(Response(200, PLAYLIST_TEXT.encode()))
        with mock.patch.object(source_parser, 'RELAY_ROUTE', hanime_relay.route):
            text, final, _ = PublicHttp(validate=lambda value: value).document(PLAYLIST, headers={'User-Agent': 'UA'})
        self.assertEqual((text, final), (PLAYLIST_TEXT, PLAYLIST))
        self.assertEqual(session.calls[0][1], 'https://relay.example.workers.dev' + PLAYLIST[len('https://hanime.tv'):])
        for url in ('https://p24.htv-elidibus.com/2/segs/abc.html', EPISODE, PLAYLIST + '?x=1',
                    'https://hanime.tv.example.com/hls/1/' + 'a' * 40):
            self.assertIsNone(hanime_relay.route(url), url)
        self.relay(Response(200, b'<html>'))
        with self.assertRaises(SourceError):
            hanime_relay.route(PLAYLIST)


class OnlineHlsTests(unittest.TestCase):
    def test_plain_aes128_is_played_but_drm_is_not(self):
        import online_sessions as online
        links = []
        out = online.rewrite_manifest(PLAYLIST_TEXT, PLAYLIST, lambda value: links.append(value) or '/p/' + str(len(links)))
        self.assertEqual(links, ['https://ct.htv-services.com/sign.bin', 'https://p24.htv-elidibus.com/2/4/9/1/v1x/segs/b0/2/abc.html'])
        self.assertIn('METHOD=AES-128,URI="/p/1"', out)
        for line in ('#EXT-X-KEY:METHOD=SAMPLE-AES,URI="k"', '#EXT-X-KEY:METHOD=AES-128,URI="k",KEYFORMAT="com.apple.streamingkeydelivery"',
                     '#EXT-X-SESSION-KEY:METHOD=AES-128,URI="k"', '#EXT-X-KEY:METHOD=AES-128'):
            with self.assertRaises(SourceError, msg=line):
                online.rewrite_manifest('#EXTM3U\n' + line + '\n#EXTINF:1,\na.ts\n', 'https://x.example/', str)

    def test_adaptive_master_accepts_aes128_variants(self):
        from adaptive_playback import adaptive_master
        streams = [{'type': 'hls', 'quality': 720, 'url': 'https://x.example/720'}, {'type': 'hls', 'quality': 480, 'url': 'https://x.example/480'}]
        text = adaptive_master(streams, mock.Mock(spec=[]), document=lambda client, url, headers=None: (PLAYLIST_TEXT, url, {}))
        self.assertIn('#EXT-X-STREAM-INF', text)
        drm = PLAYLIST_TEXT.replace('AES-128', 'SAMPLE-AES')
        with self.assertRaises(SourceError):
            adaptive_master(streams, mock.Mock(spec=[]), document=lambda client, url, headers=None: (drm, url, {}))

    def test_only_the_known_cdn_may_label_segments_as_html(self):
        import online_sessions as online
        self.assertTrue(online.disguised_segment('https://p24.htv-elidibus.com/2/segs/abc.html'))
        for url in ('https://p24.htv-elidibus.com/2/segs/abc.ts', 'https://htv-elidibus.com.example.com/a.html',
                    'https://example.com/a.html'):
            self.assertFalse(online.disguised_segment(url), url)


if __name__ == '__main__':
    unittest.main()
