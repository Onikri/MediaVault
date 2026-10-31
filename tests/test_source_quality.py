from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from source_quality import inspect_qualities
from source_parser import Page
from media_download import pick_stream,expand_stream_qualities
from run_import import validate_job,run_job


class SourceQualityTests(unittest.TestCase):
    def test_metadata_cache_coalesces_simultaneous_probes_and_returns_independent_lists(self):
        import threading,time
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        import source_quality
        entered=threading.Event()
        def probe(*args,**kwargs):
            entered.set();time.sleep(.05)
            return {'qualities':[2160,1080],'best':2160,'original':False,'streamCount':2}
        with patch('source_quality.inspect_qualities',side_effect=probe) as mocked:
            with ThreadPoolExecutor(3) as pool:
                pending=[pool.submit(source_quality.cached_qualities,'https://unique-cache.example.com/film',referer='https://catalog.example.com/') for _ in range(3)]
                results=[p.result() for p in pending]
            self.assertEqual(mocked.call_count,1)
            results[0]['qualities'].clear()
            self.assertEqual(results[1]['qualities'],[2160,1080])
            self.assertNotIn('https://',str(results))

    def test_quality_inspection_preserves_public_parent(self):
        from unittest.mock import Mock
        resolver=Mock();resolver.http=object();resolver.resolve.return_value=Page(streams=[{'quality':2160,'type':'mp4','url':'https://cdn.example.com/4k.mp4'}])
        self.assertEqual(inspect_qualities('https://embed.example.com/film',referer='https://catalog.example.com/film',resolver=resolver)['best'],2160)
        resolver.resolve.assert_called_once_with('https://embed.example.com/film',referer='https://catalog.example.com/film')
    def test_all_published_heights_are_returned_without_signed_urls_or_a_1080_cap(self):
        heights=[144,240,360,480,720,1080,1440,2160,4320]
        class Http:pass
        class Resolver:
            http=Http()
            def resolve(self,url):return Page(streams=[{'quality':q,'type':'mp4','url':'https://cdn.example.com/'+str(q)+'.mp4?signature=private-source-fixture'} for q in heights])
        result=inspect_qualities('https://player.example.com/episode-3',resolver=Resolver())
        self.assertEqual(result['qualities'],sorted(heights,reverse=True));self.assertEqual(result['best'],4320)
        self.assertNotIn('signature',str(result));self.assertNotIn('https://',str(result))

    def test_unknown_hls_master_is_expanded_in_full(self):
        class Http:
            def document(self,url,**kwargs):return '#EXTM3U\n'+''.join('#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=3840x'+str(q)+'\n'+str(q)+'.m3u8\n' for q in [360,1080,1440,2160]),url,{}
        class Resolver:
            http=Http()
            def resolve(self,url):return Page(streams=[{'quality':None,'type':'hls','url':'https://cdn.example.com/master.m3u8','headers':{'Referer':'https://player.example.com/'}}])
        self.assertEqual(inspect_qualities('https://player.example.com/episode-3',resolver=Resolver())['qualities'],[2160,1440,1080,360])

    def test_best_is_default_and_4k_can_be_explicitly_selected(self):
        raw={'version':3,'library_id':'catalog-123','sources':['https://player.example.com/episode-3']}
        self.assertEqual(validate_job(raw)['quality'],'best')
        self.assertEqual(validate_job({**raw,'version':2})['quality'],'720')
        self.assertEqual(validate_job({**raw,'quality':'2160'})['quality'],'2160')
        streams=[{'quality':q,'type':'mp4','url':'https://cdn.example.com/'+str(q)+'.mp4'} for q in [360,1080,2160]]
        self.assertEqual(pick_stream(streams)['quality'],2160)
        self.assertEqual(pick_stream(streams,'1080')['quality'],1080)

    def test_master_4k_beats_a_labelled_720_stream_without_losing_audio_groups(self):
        master={'quality':None,'type':'hls','url':'https://cdn.example.com/master.m3u8','headers':{'Referer':'https://player.example.com/'}}
        class Http:
            def document(self,url,**kwargs):
                self_outer.assertEqual(kwargs['headers'],master['headers'])
                return '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="Original",URI="audio.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=3840x2160,AUDIO="a"\n2160.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=500,RESOLUTION=640x360,AUDIO="a"\n360.m3u8\n',url,{}
        self_outer=self
        streams=expand_stream_qualities([{'quality':720,'type':'mp4','url':'https://cdn.example.com/720.mp4'},master],Http())
        best=pick_stream(streams)
        self.assertEqual(best['quality'],2160);self.assertEqual(best['url'],master['url'])
        self.assertEqual(pick_stream(streams,'720')['quality'],720)

    def test_new_qualities_have_distinct_resume_identities_and_old_jobs_keep_theirs(self):
        seen=[]
        class Vault:
            library_id='catalog-123'
            def completed(self,identity,**kwargs):seen.append(identity);return {'id':'already-saved'}
        class Resolver:
            def inspect(self,url):return Page(episodes=[{'number':1,'url':url}])
        raw={'version':2,'library_id':'catalog-123','sources':['https://player.example.com/episode-1'],'collection':'Show','quality':'720'}
        for version,quality in [(2,'720'),(3,'720'),(3,'2160'),(3,'best')]:
            result=run_job({**raw,'version':version,'quality':quality},Vault(),resolver=Resolver(),log=lambda _:None)
            self.assertEqual(result['skipped'],1)
        self.assertNotIn(':quality=',seen[0])
        self.assertEqual(len(set(seen)),4)
        self.assertTrue(seen[2].endswith(':quality=2160'))

    def test_quality_endpoint_requires_owner_auth_and_returns_metadata_only(self):
        import os
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        import api
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DATA_DIR':directory,'MEDIA_VAULT_DISABLE_WORKER':'1'}):
            with TestClient(api.app) as client:
                self.assertEqual(client.post('/sources/qualities',json={'url':'https://player.example.com/episode-3'}).status_code,401)
                api.app.dependency_overrides[api.owner]=lambda:'owner-fixture'
                try:
                    with patch('source_quality.inspect_qualities',return_value={'qualities':[2160,1080,720],'best':2160,'original':False,'streamCount':3}):
                        response=client.post('/sources/qualities',json={'url':'https://player.example.com/episode-3'})
                    self.assertEqual(response.status_code,200);self.assertEqual(response.json()['qualities'],[2160,1080,720])
                    self.assertNotIn('https://',response.text)
                finally:api.app.dependency_overrides.pop(api.owner,None)
