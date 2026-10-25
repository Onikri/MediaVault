"""Real server Chromium against fulfilled public-shaped responses, no external network."""
import asyncio
from pathlib import Path
import shutil
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from browser_player import _extract, observed_streams, browser_destination
from source_parser import SourceError

class BrowserPlayerTests(unittest.TestCase):
    def test_websocket_streams_are_urls_not_arbitrary_scripts_or_private_addresses(self):
        text='{"file":"https:\\/\\/cdn.example.com/show.m3u8?token=public-source-signature","other":"javascript:alert(1)"}'
        self.assertEqual(observed_streams(text),['https://cdn.example.com/show.m3u8?token=public-source-signature'])
        for value in ['file:///etc/passwd','http://127.0.0.1/x','https://127.0.0.1/x','https://[::1]/x','wss://internal.local/ws']:
            with self.assertRaises(SourceError):browser_destination(value,resolve_dns=False)
        self.assertEqual(browser_destination('wss://player.example.com/ws',resolve_dns=False),'https://player.example.com/ws')

    @unittest.skipUnless(shutil.which('chromium') or shutil.which('google-chrome'),'Chromium is required for dynamic player integration')
    def test_executes_actual_page_js_and_observes_hls_without_device_or_google_context(self):
        url='https://public.example.com/episode-3'
        fixture={url:('<html><script>setTimeout(()=>fetch("https://cdn.example.com/episode-3.m3u8"),40)</script></html>','text/html'),
                 'https://cdn.example.com/episode-3.m3u8':('#EXTM3U\n#EXT-X-ENDLIST','application/vnd.apple.mpegurl')}
        result=asyncio.run(_extract(url,validate=lambda u:browser_destination(u,resolve_dns=False),fixture=fixture,timeout=3))
        self.assertEqual(result[0]['url'],'https://cdn.example.com/episode-3.m3u8')
        self.assertEqual(result[0]['type'],'hls')
        self.assertNotIn('Cookie',result[0]['headers']);self.assertNotIn('Authorization',result[0]['headers'])

    @unittest.skipUnless(shutil.which('chromium') or shutil.which('google-chrome'),'Chromium is required for dynamic player integration')
    def test_challenge_page_is_not_bypassed(self):
        url='https://public.example.com/challenge'
        with self.assertRaises(SourceError):
            asyncio.run(_extract(url,validate=lambda u:browser_destination(u,resolve_dns=False),fixture={url:('<title>Just a moment</title>','text/html')},timeout=1))

if __name__=='__main__':unittest.main()
