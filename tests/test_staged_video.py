"""Browser-staged Collaps episodes: real ffmpeg HLS, real remux, fake Drive.

The test plays the browser's part: it posts the two playlists it read, uploads
every resource the server lists and then saves the result locally or to Drive.
"""
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
import local_exports as exports
import online_sessions
from media_download import verify_video
from run_import import run_job, validate_job
from source_parser import SourceError
from staged_video import browser_only, plan
from vault_drive import VaultDrive, open_chunk
from test_vault_drive import FakeDrive, PHRASE

EMBED = 'https://api.nextembed.ws/embed/movie/12345?mv_audio=1'


def wait(manager, owner, identity, states=('done', 'error', 'cancelled')):
    until = time.monotonic() + 30
    while time.monotonic() < until:
        value = manager.status(owner, identity)
        if value['state'] in states and not manager.jobs[identity].running:
            return value
        time.sleep(.02)
    raise AssertionError('Export did not finish')


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg is required')
class StagedVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        common = ['-t', '2.4', '-f', 'hls', '-hls_time', '1', '-hls_playlist_type', 'vod']
        tracks = {
            'video': ['-f', 'lavfi', '-i', 'testsrc2=size=96x64:rate=10', '-c:v', 'libx264', '-preset', 'ultrafast',
                      '-g', '10', '-sc_threshold', '0', '-pix_fmt', 'yuv420p', '-an'],
            'audio': ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-c:a', 'aac', '-b:a', '64k', '-vn'],
        }
        cls.resources, cls.stream = {}, {}
        for name, args in tracks.items():
            directory = root / name
            directory.mkdir()
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', *args, *common, '-hls_segment_filename',
                            str(directory / 'seg-%d.ts'), str(directory / 'index.m3u8')], check=True, capture_output=True)
            base = f'https://cdn.example.com/hls/{name}/'
            cls.stream[name] = {'url': base + 'index.m3u8', 'text': (directory / 'index.m3u8').read_text()}
            cls.resources.update({base + file.name: file.read_bytes() for file in directory.iterdir() if file.suffix == '.ts'})

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.manager = exports.Exports(self.directory.name, reserve=0)
        app = FastAPI()
        online_sessions.install(app, lambda: 'A')
        self.client = TestClient(app)

    def tearDown(self):
        self.manager.close()
        self.directory.cleanup()

    def stage(self, name='Фильм · серия 1'):
        with patch.object(exports, 'manager', return_value=self.manager):
            response = self.client.post('/online/exports', json={'url': EMBED, 'kind': 'video', 'stream': self.stream, 'name': name})
            self.assertEqual(response.status_code, 202, response.text)
            value = response.json()
            self.assertEqual(value['state'], 'staging')
            self.assertEqual(set(value['resources']), set(self.resources))
            early = self.client.post(f"/online/exports/{value['id']}/start")
            self.assertEqual(early.status_code, 422)
            for index, url in enumerate(value['resources']):
                put = self.client.put(f"/online/exports/{value['id']}/segments/{index}", content=self.resources[url])
                self.assertEqual(put.status_code, 200, put.text)
            self.assertEqual(put.json()['segments'], {'received': len(self.resources), 'total': len(self.resources)})
            self.assertEqual(self.client.put(f"/online/exports/{value['id']}/segments/{len(self.resources)}", content=b'x').status_code, 422)
            self.assertEqual(self.client.post(f"/online/exports/{value['id']}/start").json()['state'], 'queued')
        return wait(self.manager, 'A', value['id'])

    def test_browser_segments_become_one_checked_mp4_for_the_device(self):
        done = self.stage()
        self.assertEqual(done['state'], 'done', done.get('error'))
        self.assertEqual(done['filename'], 'Фильм · серия 1.mp4')
        with patch.object(exports, 'manager', return_value=self.manager):
            response = self.client.get(done['downloadUrl'])
        self.assertEqual(response.status_code, 200)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'out.mp4'
            path.write_bytes(response.content)
            kinds = {stream['codec_type'] for stream in verify_video(path)['streams']}
        self.assertEqual(kinds, {'video', 'audio'})

    def test_drive_import_takes_the_staged_file_without_contacting_the_cdn(self):
        done = self.stage()
        drive = FakeDrive()
        vault = VaultDrive(drive, sleep=lambda _: None)
        library = vault.initialize(PHRASE)

        class Offline:
            http = None
            def resolve(self, *args, **kwargs):
                raise AssertionError('The CDN refuses servers: nothing may be resolved')

        job = {'version': 3, 'library_id': library, 'sources': [EMBED], 'collection': 'Фильм', 'quality': 'best',
               'section': 'video', 'entries': [{'number': 1, 'url': EMBED, 'season': 1, 'export': done['id']}]}
        result = run_job(job, vault, resolver=Offline(), log=lambda _: None,
                         staged_source=lambda identity, directory: self.manager.take('A', identity, directory))
        self.assertEqual(result, {'saved': 1, 'skipped': 0, 'failed': 0})
        item = vault.refresh()['items'][0]
        self.assertEqual((item['episode'], item['season'], item['partName']), (1, 1, 'Сезон 1'))
        self.assertTrue(item.get('previewArtwork'))
        raw = b''.join(open_chunk(drive.download(chunk['fileId']), vault._key, item['id'], n, chunk['iv'])
                       for n, chunk in enumerate(item['chunks']))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'decrypted.mp4'
            path.write_bytes(raw)
            self.assertEqual({s['codec_type'] for s in verify_video(path)['streams']}, {'video', 'audio'})
        self.assertEqual(self.manager.status('A', done['id'])['state'], 'taken')
        with self.assertRaises(exports.ExportProblem):
            self.manager.take('A', done['id'], self.directory.name)

    def test_only_collaps_and_only_finished_plain_playlists_are_accepted(self):
        self.assertTrue(browser_only(EMBED))
        self.assertFalse(browser_only('https://example.com/embed/movie/1'))
        with self.assertRaises(ValueError):
            self.manager.start('A', 'https://example.com/embed/movie/1', 'video', stream=self.stream)
        for text in ['#EXTM3U\n#EXTINF:1,\na.ts\n',
                     '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="k"\n#EXTINF:1,\na.ts\n#EXT-X-ENDLIST\n',
                     '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nv.m3u8\n',
                     '#EXTM3U\n#EXT-X-BYTERANGE:10@0\n#EXTINF:1,\na.ts\n#EXT-X-ENDLIST\n',
                     '<html>']:
            with self.assertRaises(SourceError):
                plan({'video': {'url': 'https://cdn.example.com/a/index.m3u8', 'text': text}})
        with self.assertRaises(SourceError):
            plan({'video': {'url': 'http://cdn.example.com/a/index.m3u8', 'text': '#EXTM3U\n#EXTINF:1,\na.ts\n#EXT-X-ENDLIST\n'}})

    def test_drive_job_rejects_malformed_browser_references(self):
        base = {'version': 3, 'library_id': 'library-1', 'sources': [EMBED], 'collection': 'Фильм', 'section': 'video'}
        validate_job({**base, 'entries': [{'number': 1, 'url': EMBED, 'export': 'a' * 32}]})
        for value in ['../etc', 'A' * 32, 7]:
            with self.assertRaises(SourceError):
                validate_job({**base, 'entries': [{'number': 1, 'url': EMBED, 'export': value}]})


if __name__ == '__main__':
    unittest.main()
