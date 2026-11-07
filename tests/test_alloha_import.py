"""Real HLS/remux/encryption, mocked browser CDN and Drive. No external accounts."""
import asyncio
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from alloha_import import AllohaImporter, AllohaImportHttp, PREFIX
from alloha_delivery import AllohaDelivery
from alloha_browser import SourceRefused
from source_parser import Resolver, SourceError
from run_import import run_job
from media_download import verify_video
from test_alloha_delivery import Profiles
from test_vault_drive import FakeDrive, PHRASE
from vault_drive import VaultDrive, open_chunk

IFRAME='https://alloha.yani.tv/?translation=66'


class NativeSource:
    sources=[]
    fixture=None
    fail_second=False
    fail_always=False
    expired=False
    duration_changed=False
    master=False
    calls=Counter()

    def __init__(self,profile,iframe,*,referer=None):
        self.referer=referer
        self.index=len(self.sources);self.sources.append(self)
        self.closed=self.socket_closed=False
        self.playback=[]
    async def open(self,audio=None):self.audio=audio or '1'
    async def metadata(self):
        return {'active_id':str(self.index),'active':self.audio,'sources':[
            {'audioId':self.audio,'label':'Dub','quality':{'720':f'https://cdn.example.com/s{self.index}/'+('master.m3u8' if self.master else 'index.m3u8')}}]}
    async def fetch(self,url,byte_range=''):
        name=Path(urlsplit(url).path).name
        self.calls[(self.index,name,byte_range)]+=1
        if name=='master.m3u8':
            return b'#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="dub",NAME="Dub",DEFAULT=YES,URI="index.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=100000,RESOLUTION=96x64,AUDIO="dub"\nindex.m3u8\n',{'content-type':'application/vnd.apple.mpegurl'},200,url
        if name=='index.m3u8':
            text=(self.fixture/name).read_text()
            if self.index and self.duration_changed:text=text.replace('#EXTINF:1.000000,','#EXTINF:1.100000,')
            return text.encode(),{'content-type':'application/vnd.apple.mpegurl'},200,url
        if name=='part-1.m4s' and (self.fail_always or (self.fail_second and self.index==0)):
            raise SourceRefused('injected CDN refusal')
        return (self.fixture/name).read_bytes(),{'content-type':'video/mp4'},200,url
    async def close(self):self.closed=True
    async def update_playback(self,state):self.playback.append(state)


@unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg required')
class AllohaImportTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name);fixture=cls.root/'hls';fixture.mkdir()
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=96x64:rate=10',
                        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','2.4',
                        '-c:v','libx264','-preset','ultrafast','-g','10','-sc_threshold','0','-c:a','aac',
                        '-f','hls','-hls_time','1','-hls_playlist_type','vod','-hls_segment_type','fmp4',
                        '-hls_segment_filename','part-%d.m4s','index.m3u8'],cwd=fixture,capture_output=True,check=True)
        NativeSource.fixture=fixture
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    async def asyncSetUp(self):
        NativeSource.sources=[];NativeSource.calls=Counter();NativeSource.fail_second=False;NativeSource.fail_always=False;NativeSource.duration_changed=False;NativeSource.master=False
        self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
        self.service=AllohaDelivery(self.root/'service',profiles=Profiles(),factory=NativeSource,queue_timeout=.02)
        self.service.external_address='1.1.1.1'
        self.importer=AllohaImporter(self.service,asyncio.get_running_loop(),interval=0)
    async def asyncTearDown(self):
        await self.service.close();self.directory.cleanup()
    async def download(self,name='out'):
        return await asyncio.to_thread(self.importer.download,IFRAME,self.root/name,quality='720',checkpoint=self.root/'checkpoint',referer='https://publisher.example.com/show')
    async def test_master_with_separate_audio(self):
        NativeSource.master=True
        output=await self.download()
        info=verify_video(output)
        self.assertTrue(any(s['codec_type']=='audio' for s in info['streams']))
        self.assertEqual(len(NativeSource.sources),1)
        self.assertEqual(NativeSource.sources[0].referer,'https://publisher.example.com/show')

    async def test_stream_to_encrypted_drive_without_materializing_movie(self):
        drive=FakeDrive();vault=VaultDrive(drive,sleep=lambda _:None);library=vault.initialize(PHRASE)
        job={'version':3,'library_id':library,'sources':[IFRAME],'collection':'Stream import','quality':'720',
             'section':'anime','entries':[{'number':1,'season':1,'url':IFRAME}]}
        try:
            cache=self.root/'stream-cache'
            result=await asyncio.to_thread(run_job,job,vault,alloha_streamer=self.importer.stream,alloha_cache=cache,temporary_dir=self.root,log=lambda _:None)
            self.assertEqual(result['saved'],1)
            item=vault.refresh()['items'][0]
            decrypted=b''.join(open_chunk(drive.download(c['fileId']),vault._key,item['id'],n,c['iv']) for n,c in enumerate(item['chunks']))
            output=self.root/'stream-decrypted.mp4';output.write_bytes(decrypted)
            info=verify_video(output)
            self.assertTrue(any(s['codec_type']=='audio' for s in info['streams']))
            self.assertEqual(item['quality'],'720p')
            self.assertEqual(item['mediaInfo']['height'],64)
            self.assertEqual(list((self.root/'service'/'segments').iterdir()),[])
            self.assertEqual(list(self.root.glob('mediavault-episode-*')),[])
            self.assertEqual(list(cache.iterdir()),[])
        finally:vault.close()

    async def test_failed_stream_validation_never_publishes_truncated_film(self):
        import io
        drive=FakeDrive();vault=VaultDrive(drive,sleep=lambda _:None);vault.initialize(PHRASE)
        def fail():raise SourceError('incomplete film')
        try:
            with self.assertRaisesRegex(SourceError,'incomplete'):
                vault.upload_stream(io.BytesIO(b'partial video'),validate=fail,name='incomplete.mp4',collection='Incomplete')
            self.assertEqual(vault.refresh()['items'],[])
            self.assertTrue(drive.trashed)
        finally:vault.close()

    async def test_stream_session_renewal_preserves_continuous_mp4(self):
        NativeSource.fail_second=True
        await self.test_stream_to_encrypted_drive_without_materializing_movie()
        self.assertEqual(len(NativeSource.sources),2)

    async def test_sealed_stream_checkpoint_reuses_remote_chunks_after_restart(self):
        import io
        from vault_drive import CHUNK_SIZE
        drive=FakeDrive();vault=VaultDrive(drive,sleep=lambda _:None);library=vault.initialize(PHRASE)
        raw=b'private-payload-'*(CHUNK_SIZE//8)
        checkpoint=self.root/'resume'/'stream.enc.json'
        class Broken(io.BytesIO):
            def read(self,size=-1):
                if self.tell()>=CHUNK_SIZE:raise SourceError('injected interruption')
                return super().read(size)
        options={'name':'resume.mp4','collection':'Resume','checkpoint':checkpoint,'stream_identity':'verified-layout'}
        try:
            with self.assertRaisesRegex(SourceError,'interruption'):
                vault.upload_stream(Broken(raw),validate=lambda:None,**options)
            self.assertTrue(checkpoint.exists())
            self.assertNotIn(b'private-payload',checkpoint.read_bytes())
            self.assertEqual(vault.refresh()['items'],[])
            previous=sum(name.startswith('part-') for _,name in drive.upload_calls)
            vault.close();vault=VaultDrive(drive,sleep=lambda _:None);vault.unlock(library,PHRASE)
            item=vault.upload_stream(io.BytesIO(raw),validate=lambda:None,**options)
            self.assertEqual(sum(name.startswith('part-') for _,name in drive.upload_calls),previous+1)
            self.assertEqual(b''.join(open_chunk(drive.download(c['fileId']),vault._key,item['id'],n,c['iv']) for n,c in enumerate(item['chunks'])),raw)
            self.assertFalse(checkpoint.exists())
        finally:vault.close()
    async def test_refusal_reopens_without_fetching_saved_segments(self):
        NativeSource.fail_second=True
        output=await self.download();info=verify_video(output)
        self.assertTrue(any(s['codec_type']=='audio' for s in info['streams']))
        self.assertEqual(len(NativeSource.sources),2)
        self.assertEqual(NativeSource.calls[(1,'part-0.m4s','')],0,'previous segment is not fetched again')
        self.assertEqual(self.service.profiles.failures,1)
        self.assertEqual(self.service.sessions,{})
        self.assertTrue(all(source.closed for source in NativeSource.sources))
    async def test_checkpoint_resumes_after_failed_job(self):
        NativeSource.fail_always=True
        with self.assertRaises(SourceError):await self.download()
        self.assertTrue((self.root/'checkpoint'/'root-segment-0').exists())
        NativeSource.fail_always=False;before=len(NativeSource.sources)
        output=await self.download('retry');verify_video(output)
        self.assertEqual(NativeSource.calls[(before,'part-0.m4s','')],0)
        for record in (self.root/'checkpoint').glob('*.json'):
            self.assertNotIn('https://',record.read_text())
    async def test_changed_media_is_not_mixed(self):
        NativeSource.fail_second=True;NativeSource.duration_changed=True
        with self.assertRaisesRegex(SourceError,'Состав видео'):await self.download()
        self.assertFalse((self.root/'out'/'episode.mp4').exists())
    async def test_expired_session_reopens_without_quarantining_profile(self):
        original=self.service.session;expired=False
        def lookup(sid):
            nonlocal expired
            source=original(sid)
            if not expired and any(name=='part-0.m4s' and not interval for _,name,interval in NativeSource.calls):
                source.expires=0;expired=True
                return original(sid)
            return source
        with patch.object(self.service,'session',side_effect=lookup):output=await self.download()
        verify_video(output);self.assertEqual(self.service.profiles.failures,0)
        self.assertEqual(len(NativeSource.sources),2)
    async def test_drive_dispatch_encryption_and_other_sources_unchanged(self):
        drive=FakeDrive();vault=VaultDrive(drive,sleep=lambda _:None);library=vault.initialize(PHRASE)
        job={'version':2,'library_id':library,'sources':[IFRAME],'collection':'Native import','quality':'720',
             'section':'anime','entries':[{'number':1,'season':1,'url':IFRAME}]}
        cache=self.root/'task-cache'
        try:
            result=await asyncio.to_thread(run_job,job,vault,alloha_downloader=self.importer.download,alloha_cache=cache,log=lambda _:None)
            self.assertEqual(result['saved'],1)
            item=vault.refresh()['items'][0]
            decrypted=b''.join(open_chunk(drive.download(c['fileId']),vault._key,item['id'],n,c['iv']) for n,c in enumerate(item['chunks']))
            output=self.root/'decrypted.mp4';output.write_bytes(decrypted);verify_video(output)
            self.assertEqual(list(cache.iterdir()),[])
            for remote in drive.files.values():
                if remote['name'].startswith('part-'):self.assertNotIn(b'ftyp',remote['data'][:32])
            before=len(NativeSource.sources)
            result=await asyncio.to_thread(run_job,job,vault,alloha_downloader=self.importer.download,alloha_cache=cache,log=lambda _:None)
            self.assertEqual(result['skipped'],1);self.assertEqual(len(NativeSource.sources),before)
            resolver=Resolver(native_alloha=True)
            self.assertEqual(resolver.resolve(IFRAME).streams[0]['type'],'alloha-native')
            ordinary=resolver.resolve('https://cdn.example.com/file.mp4').streams[0]
            self.assertEqual(ordinary['type'],'mp4')
            self.assertEqual(len(NativeSource.sources),before)
        finally:vault.close()

if __name__=='__main__':unittest.main()
