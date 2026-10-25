import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from vault_drive import VaultDrive,open_chunk,CHUNK_SIZE
from task_store import TaskStore
from library_enrichment import preview_existing
from public_page_data import releases,episode_streams
from test_vault_drive import FakeDrive,PHRASE

class EnrichmentPerformance(unittest.TestCase):
    def test_queue_yields_between_files_and_restart_marks_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(folder)
            first=store.add('owner',{'job':{},'vault_key':'private-fixture-key'},'first')
            second=store.add('owner',{'job':{},'vault_key':'private-fixture-key'},'second')
            self.assertEqual(store.next()['id'],first['id'])
            store.update(first['id'],status='queued',progress={'cursor':1})
            self.assertEqual(store.next()['id'],second['id'])
            self.assertNotIn('private-fixture-key',json.dumps(store.list('owner')))
            store.close();store=TaskStore(folder)
            self.assertTrue(store.get(second['id'])['progress']['recover_needed']);store.close()

    def test_parallel_upload_keeps_chunk_order_and_authentication(self):
        class ConcurrentDrive(FakeDrive):
            supports_parallel=True
            def __init__(self):super().__init__();self.lock=threading.Lock();self.active=0;self.peak=0
            def allocate_id(self):
                with self.lock:return super().allocate_id()
            def upload_bytes(self,identity,name,data,parent):
                if name.startswith('part-'):
                    with self.lock:self.active+=1;self.peak=max(self.peak,self.active)
                    time.sleep(.04 if '000000' in name else .01)
                    try:return super().upload_bytes(identity,name,data,parent)
                    finally:
                        with self.lock:self.active-=1
                return super().upload_bytes(identity,name,data,parent)
        with tempfile.TemporaryDirectory() as folder:
            drive=ConcurrentDrive();vault=VaultDrive(drive);vault.initialize(PHRASE)
            raw=b'a'*CHUNK_SIZE+b'b'*CHUNK_SIZE+b'c'*31;p=Path(folder)/'video.mp4';p.write_bytes(raw)
            events=[];item=vault.upload_file(p,progress=events.append)
            rebuilt=b''.join(open_chunk(drive.download(c['fileId']),vault._key,item['id'],i,c['iv']) for i,c in enumerate(item['chunks']))
            self.assertEqual(rebuilt,raw);self.assertEqual(drive.peak,2)
            self.assertTrue(any('encryptionMs' in event and 'mbps' in event for event in events));vault.close()

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg required')
    def test_existing_encrypted_video_gets_its_own_authenticated_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'episode.mp4'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=96x64:rate=10','-t','2',
                            '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart',str(path)],check=True,capture_output=True)
            drive=FakeDrive();vault=VaultDrive(drive);vault.initialize(PHRASE);item=vault.upload_file(path,collection='Тайтл',section='anime',episode=1)
            chunks=item['chunks'];image=preview_existing(vault,item)
            self.assertTrue(image and image.startswith(b'\xff\xd8\xff'))
            asset=vault.save_preview(item['id'],image)
            self.assertEqual(open_chunk(drive.download(asset['fileId']),vault._key,asset['id'],0,asset['iv']),image)
            self.assertEqual(vault.catalog['items'][0]['chunks'],chunks);vault.close()

    def test_only_published_nuxt_release_and_episode_entries_are_exposed(self):
        nodes=[]
        def add(value):
            index=len(nodes);nodes.append(None)
            nodes[index]={k:add(v) for k,v in value.items()} if isinstance(value,dict) else [add(v) for v in value] if isinstance(value,list) else value
            return index
        add({'release':{'alias':'real-title','name':{'main':'Настоящий тайтл'},'episodes':[{'ordinal':1,'hls_720':'https://cdn.example.com/1.m3u8'},{'ordinal':3,'hls_720':'https://cdn.example.com/3.m3u8'}]}})
        html='<script id="__NUXT_DATA__" type="application/json">'+json.dumps(nodes)+'</script>'
        self.assertEqual([e['number'] for e in episode_streams(html,'https://aniliberty.top/')],[1,3])
        values=releases(html,'https://aniliberty.top/','Настоящий')
        self.assertEqual(len(values),1);self.assertTrue(values[0]['url'].endswith('/real-title'))
