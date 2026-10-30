"""Real server Chromium against fulfilled public-shaped responses, no external network."""
import asyncio
from pathlib import Path
import shutil
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from browser_player import _extract, _render, observed_streams, browser_destination,published_quality_streams
from source_parser import SourceError

class BrowserPlayerTests(unittest.TestCase):
    def test_active_quality_map_validates_each_url_and_never_retains_credentials(self):
        values={'2160':'https://cdn.example.com/4k.m3u8','480':'https://cdn.example.com/480.m3u8',
                '1080':'https://127.0.0.1/private.m3u8','720':'javascript:alert(1)','bad':'https://cdn.example.com/fake.mp4'}
        result=published_quality_streams(values,{'Authorization':'private-key','Cookie':'private-cookie','Referer':'https://publisher.example.com/'},validate=lambda u:browser_destination(u,resolve_dns=False))
        self.assertEqual([v['quality'] for v in result],[2160,480])
        self.assertNotIn('private-key',str(result));self.assertNotIn('private-cookie',str(result))

    @unittest.skipUnless(shutil.which('chromium') or shutil.which('google-chrome'),'Chromium required for active source contract')
    def test_alloha_active_source_map_preserves_4k_without_waiting_for_quality_switches(self):
        import json
        parent='https://publisher.example.com/film';url='https://embed.thealloha.club/?translation=66'
        heights=[360,480,720,1080,1440,2160]
        source={str(q):'https://cdn.example.com/russian-'+str(q)+'.m3u8' for q in heights}
        markup='<video></video><script>window.player={currentSource:{audioId:"ru",quality:'+json.dumps(source)+'},otherAudio:{quality:{"2160":"https://cdn.example.com/wrong-audio.m3u8"}}};fetch("'+source['480']+'");</script>'
        # No higher-quality request has completed. The active source map must
        # provide the full ladder immediately, retaining this Russian track.
        fixture={parent:('<html>Film</html>','text/html'),url:(markup,'text/html'),source['480']:('#EXTM3U','application/vnd.apple.mpegurl')}
        result=asyncio.run(_extract(url,parent,validate=lambda u:browser_destination(u,resolve_dns=False),fixture=fixture,timeout=1))
        self.assertEqual(sorted(s['quality'] for s in result),heights)
        self.assertEqual({s['url'] for s in result},set(source.values()))

    @unittest.skipUnless(shutil.which('chromium') or shutil.which('google-chrome'),'Chromium required for a real iframe contract')
    def test_alloha_uses_public_parent_and_play_button_and_never_returns_plyr_blank_video(self):
        parent='https://publisher.example.com/title'
        url='https://embed.thealloha.club/?season=1&episode=3&translation=10'
        stream='https://cdn.example.com/selected-episode-3.m3u8'
        markup='<video src="https://cdn.plyr.io/static/blank.mp4"></video><button data-plyr="play" onclick="fetch(\''+stream+'\')">Play</button><script>if(window===window.top)document.body.innerHTML="Not an iframe";</script>'
        fixture={parent:('<html><body>Publisher</body></html>','text/html'),url:(markup,'text/html'),stream:('#EXTM3U','application/vnd.apple.mpegurl'),'https://cdn.plyr.io/static/blank.mp4':('blank','video/mp4')}
        result=asyncio.run(_extract(url,parent,validate=lambda value:browser_destination(value,resolve_dns=False),fixture=fixture,timeout=4))
        self.assertEqual([r['url'] for r in result],[stream])

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

    @unittest.skipUnless(shutil.which('chromium') or shutil.which('google-chrome'),'Chromium is required for dynamic catalogue integration')
    def test_render_discovers_a_published_lazy_iframe_without_media_or_user_session(self):
        url='https://catalog.example.com/title'
        frame='https://player.example.com/embed/7'
        fixture={url:('<html><h1>Exact show</h1><script>setTimeout(()=>{const f=document.createElement("iframe");f.src="'+frame+'";document.body.appendChild(f)},40)</script></html>','text/html'),frame:('<html></html>','text/html')}
        # The deadline includes cold Chromium startup, not only the 40 ms fixture.
        text,target=asyncio.run(_render(url,validate=lambda u:browser_destination(u,resolve_dns=False),fixture=fixture,timeout=8))
        self.assertIn(frame,text);self.assertEqual(target,url)

    @unittest.skipUnless(shutil.which('chromium') or shutil.which('google-chrome'),'Chromium is required for dynamic catalogue integration')
    def test_render_does_not_treat_a_challenge_as_an_empty_catalogue(self):
        url='https://catalog.example.com/title'
        with self.assertRaises(SourceError):asyncio.run(_render(url,validate=lambda u:browser_destination(u,resolve_dns=False),fixture={url:('<title>Just a moment</title>','text/html')},timeout=1))

    @unittest.skipUnless(shutil.which('chromium') or shutil.which('google-chrome'),'Chromium is required for dynamic player integration')
    def test_visible_jutplus_gate_is_not_replaced_with_an_unrelated_stream(self):
        url='https://public.example.com/plus'
        with self.assertRaisesRegex(SourceError,'JutPlus'):
            asyncio.run(_extract(url,validate=lambda u:browser_destination(u,resolve_dns=False),fixture={url:('<div class="tab_need_plus">JutPlus</div>','text/html')},timeout=1))

    @unittest.skipUnless(shutil.which('chromium') or shutil.which('google-chrome'),'Chromium is required for dynamic player integration')
    def test_every_dom_quality_is_preserved_even_when_only_one_stream_was_requested(self):
        url='https://public.example.com/qualities'
        heights=[144,240,360,480,720,1080,1440,2160,4320]
        markup='<video>'+''.join('<source src="https://cdn.example.com/'+str(q)+'.mp4" res="'+str(q)+'">' for q in heights)+'</video>'
        result=asyncio.run(_extract(url,validate=lambda u:browser_destination(u,resolve_dns=False),fixture={url:(markup,'text/html')},timeout=1))
        self.assertEqual(sorted(s['quality'] for s in result),heights)

    @unittest.skipUnless(shutil.which('chromium') or shutil.which('google-chrome'),'Chromium required for quality menu contract')
    def test_alloha_quality_menu_exposes_every_real_stream_without_changing_audio_or_episode(self):
        parent='https://publisher.example.com/film'
        url='https://embed.thealloha.club/?translation=66'
        heights=[360,480,720,1080,1440,2160]
        def stream(q):return 'https://cdn.example.com/translation-66-'+str(q)+'.m3u8'
        markup='<video></video><button data-allplay="play" onclick="fetch(\''+stream(480)+'\')">Play</button>'
        markup+=''.join('<button data-allplay="quality" value="'+str(q)+'" aria-checked="'+str(q==480).lower()+'" onclick="fetch(\''+stream(q)+'\')">'+str(q)+'</button>' for q in heights)
        # A menu label with no stream must never manufacture a CDN URL.
        markup+='<button data-allplay="quality" value="4320">8K unavailable</button>'
        markup+='<button data-allplay="audio" onclick="fetch(\'https://cdn.example.com/wrong-translation.m3u8\')">Other audio</button>'
        fixture={parent:('<html>Film</html>','text/html'),url:(markup,'text/html'),**{stream(q):('#EXTM3U','application/vnd.apple.mpegurl') for q in heights}}
        result=asyncio.run(_extract(url,parent,validate=lambda u:browser_destination(u,resolve_dns=False),fixture=fixture,timeout=4))
        self.assertEqual(sorted(s['quality'] for s in result),heights)
        self.assertEqual({s['url'] for s in result},{stream(q) for q in heights})

if __name__=='__main__':unittest.main()
