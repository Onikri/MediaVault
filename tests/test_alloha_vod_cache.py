"""Disk/HTTP contracts with a deterministic source, not live Alloha tests."""
import asyncio
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server'))
from alloha_cache import VodCache, identity
from alloha_archive import DriveArchive
from alloha_delivery import AllohaDelivery
from alloha_browser import SourceRefused
from test_alloha_delivery import Source, Profiles, IFRAME


class DiskCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = [1000.]
        self.cache = VodCache(self.temp.name, reserve=0, clock=lambda: self.now[0])
        self.key = identity('owner', IFRAME, '720')
        self.cache.pin(self.key)
        self.value = (b'0123456789', {'content-type': 'video/mp4'}, 200, 'https://cdn.example/video')

    def tearDown(self):
        self.temp.cleanup()

    def test_multiple_paused_viewers_pin_until_twenty_minutes_after_last_close(self):
        self.cache.pin(self.key)
        self.cache.put(self.key, 'url', '', self.value)
        self.now[0] += 3600
        self.cache.prune()
        self.assertEqual(self.cache.get(self.key, 'url'), self.value)
        self.cache.release(self.key)
        self.now[0] += 3600
        self.cache.prune()
        self.assertIsNotNone(self.cache.get(self.key, 'url'))
        self.cache.release(self.key)
        self.now[0] += 1199
        self.cache.prune()
        self.assertIsNotNone(self.cache.get(self.key, 'url'))
        self.now[0] += 1
        self.cache.prune()
        self.assertIsNone(self.cache.get(self.key, 'url'))

    def test_ranges_integrity_budget_and_variant_isolation(self):
        self.cache.put(self.key, 'url', '', self.value)
        raw, headers, status, _ = self.cache.get(self.key, 'url', 'bytes=2-5')
        self.assertEqual((raw, status, headers['content-range']), (b'2345', 206, 'bytes 2-5/10'))
        self.assertEqual(self.cache.get(self.key, 'url', 'bytes=-3')[0], b'789')
        for args in [('owner', IFRAME, '1080'), ('other', IFRAME, '720'), ('owner', IFRAME+'&translation=2', '720')]:
            self.assertIsNone(self.cache.get(identity(*args), 'url'))
        (self.cache.folder(self.key)/self.cache.name('url')).write_bytes(b'X123456789')
        self.assertIsNone(self.cache.get(self.key, 'url'))
        self.cache.maximum = 1
        self.assertFalse(self.cache.put(self.key, 'another', '', self.value))

    def test_complete_archive_encrypted_roundtrip_and_tamper_rejection(self):
        self.cache.put(self.key, 'url', '', self.value)
        record = {'resources': [['url', '']], 'manifests': {}, 'quality': '720'}
        self.assertTrue(self.cache.complete(self.key, record))
        values = {'google:owner': {'configured': True}}
        class Store:
            key = b'x'*32
            def setting(self, name, value=None):
                if value is not None: values[name] = value
                return values.get(name)
        archive = DriveArchive(self.cache, Store, lambda owner: None)
        uploaded = {}
        def upload(owner, key, path):
            uploaded['bytes'] = path.read_bytes()
            return 'private-file'
        def download(owner, file_id, path, size): path.write_bytes(uploaded['bytes'])
        archive.upload, archive.download = upload, download
        self.assertTrue(archive.save('owner', self.key))
        self.assertNotIn(b'0123456789', uploaded['bytes'])
        folder = self.cache.folder(self.key)
        for p in folder.iterdir():
            if p.name != 'lease': p.unlink()
        self.assertTrue(archive.restore('owner', self.key))
        self.assertEqual(self.cache.get(self.key, 'url'), self.value)
        for p in folder.iterdir():
            if p.name != 'lease': p.unlink()
        uploaded['bytes'] = uploaded['bytes'][:-1]+bytes([uploaded['bytes'][-1]^1])
        with self.assertRaises(ValueError): archive.restore('owner', self.key)
        self.assertIsNone(self.cache.load(self.key))
        self.assertFalse(archive.restore('other', self.key))


class VodDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.profiles = Profiles()
        self.service = AllohaDelivery(self.temp.name, profiles=self.profiles, factory=Source, default_mode='browser')
        self.service.vod.reserve = 0
        self.service.external_address = '1.1.1.1'
        self.body = SimpleNamespace(url=IFRAME, quality='720', referer=None, client_id='tab', purpose='playback')
        Source.opened, Source.fail, Source.html = [], False, False

    async def asyncTearDown(self):
        await self.service.close()
        self.temp.cleanup()

    async def complete(self):
        data = await self.service.prepare_online(self.body, 'owner')
        session = self.service.session(data['id'])
        await self.service.play(session.sid, session.active, session.online_quality)
        for _ in range(400):
            if not session.prefetches: break
            await asyncio.sleep(.01)
        self.assertTrue(session.cache_complete)
        return session

    async def test_whole_vod_survives_source_failure_reopen_and_uncached_range(self):
        first = await self.complete()
        count = len(Source.opened)
        Source.fail = True
        await self.service.close_session(first)
        replay = await self.service.prepare_online(self.body, 'owner')
        self.assertTrue(replay['serverCached'])
        self.assertEqual(len(Source.opened), count, 'No extraction, probes or upstream media on repeat open')
        session = self.service.session(replay['id'])
        root = session.translations[session.active]['qualities'][session.online_quality]
        text, _ = await self.service.playlist(session, root)
        rewritten = self.service.rewrite(session, text, root)
        uri = next(x for x in rewritten.splitlines() if x.startswith('/hls/'))
        token = uri.split('?u=')[1]
        result = await self.service.resource(session.sid, token, 'bytes=0-3')
        self.assertEqual(result.status_code, 206)
        self.assertEqual(len(result.body), 4)

    async def test_long_pause_heartbeat_extends_both_bridge_and_media_lease(self):
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        import online_sessions
        app = FastAPI(); app.state.alloha_delivery = self.service
        online_sessions.install(app, lambda: 'owner')
        now = [self.service.clock()]
        self.service.clock = lambda: now[0]
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://service') as client:
            data = (await client.post('/online/prepare', json={'url': IFRAME, 'kind': 'video', 'quality': '720'})).json()
            session = self.service.session(data['id'])
            session.source.socket_closed = True
            for _ in range(121):  # One hour paused, including disconnected WS telemetry.
                now[0] += 30
                response = await client.post('/online/'+data['id']+'/heartbeat')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['expiresIn'], self.service.ttl)
                await self.service.expire()
                self.assertIs(self.service.session(data['id']), session)
            await client.delete('/online/'+data['id'])
        online_sessions.sessions.clear()

    async def test_failed_speculation_does_not_close_foreground_or_publish_partial(self):
        original = Source.fetch
        async def failure(source, url, byte_range):
            if url.endswith('second.m4s'): raise SourceRefused('background fixture failure')
            return await original(source, url, byte_range)
        with patch.object(Source, 'fetch', failure):
            data = await self.service.prepare_online(self.body, 'owner')
            session = self.service.session(data['id'])
            await self.service.play(session.sid, session.active, '720')
            for _ in range(200):
                if not session.prefetches: break
                await asyncio.sleep(.01)
            self.assertFalse(session.closed)
            self.assertFalse(session.cache_complete)
            self.assertIsNone(self.service.vod.load(session.cache_key))
            self.assertFalse(session.source.closed)

    async def test_failed_replacement_preserves_old_viewer(self):
        data = await self.service.prepare_online(self.body, 'owner')
        old = self.service.session(data['id'])
        self.body.url += '&unavailable=1'
        with patch.object(Source, 'open', side_effect=SourceRefused('fixture refusal')):
            with self.assertRaises(Exception): await self.service.prepare_online(self.body, 'owner')
        self.assertFalse(old.closed)
        self.assertIs(self.service.session(old.sid), old)

    async def test_nested_vod_caches_only_selected_quality_default_audio_and_subtitles(self):
        original = Source.fetch
        async def nested(source, url, byte_range):
            if url.endswith('1-720.m3u8'):
                raw = ('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="selected",DEFAULT=YES,URI="audio.m3u8"\n'
                       '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="other",DEFAULT=NO,URI="other.m3u8"\n'
                       '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="s",NAME="sub",URI="sub.m3u8"\n'
                       '#EXT-X-STREAM-INF:BANDWIDTH=9000000,RESOLUTION=1920x1080,AUDIO="a",SUBTITLES="s"\nhigh.m3u8\n'
                       '#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1280x720,AUDIO="a",SUBTITLES="s"\nlow.m3u8\n')
                return raw.encode(), {'content-type': 'application/vnd.apple.mpegurl'}, 200, url
            if url.endswith(('low.m3u8', 'audio.m3u8', 'sub.m3u8')):
                name = url.rsplit('/', 1)[-1].replace('.m3u8', '.vtt' if url.endswith('sub.m3u8') else '.m4s')
                raw = '#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\n'+name+'\n#EXT-X-ENDLIST\n'
                return raw.encode(), {'content-type': 'application/vnd.apple.mpegurl'}, 200, url
            return await original(source, url, byte_range)
        with patch.object(Source, 'fetch', nested):
            session = await self.complete()
        record = self.service.vod.load(session.cache_key)
        self.assertTrue(any('sub.vtt' in url for url, _ in record['resources']))
        self.assertTrue(any('audio.m4s' in url for url, _ in record['resources']))
        self.assertFalse(any('high.m3u8' in url or 'other.m3u8' in url for url in record['manifests']))
        self.assertTrue(record['subtitles'])

    async def test_live_media_rebuilds_expired_bridge_and_foreign_owner_cannot_close_it(self):
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        import online_sessions
        app = FastAPI(); app.state.alloha_delivery = self.service
        who = ['owner']; online_sessions.install(app, lambda: who[0])
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://service') as client:
            data = (await client.post('/online/prepare', json={'url': IFRAME, 'kind': 'video', 'quality': '720'})).json()
            session = self.service.session(data['id'])
            online_sessions.sessions[data['id']].expires = 0
            self.assertEqual((await client.post('/online/'+data['id']+'/heartbeat')).status_code, 200)
            who[0] = 'other'
            self.assertEqual((await client.post('/online/'+data['id']+'/heartbeat')).status_code, 410)
            await client.delete('/online/'+data['id'])
            self.assertFalse(session.closed)
        online_sessions.sessions.clear()

    async def test_foreground_seek_does_not_wait_for_bnsi_background_transfer(self):
        data = await self.service.prepare_online(self.body, 'owner')
        session = self.service.session(data['id']); session.mode = 'bnsi'
        started, release = asyncio.Event(), asyncio.Event()
        original = Source.fetch
        async def delayed(source, url, byte_range='', **kwargs):
            if url.endswith('slow.m4s'):
                started.set(); await release.wait()
            return await original(source, url, byte_range)
        with patch.object(Source, 'fetch', delayed):
            task = asyncio.create_task(self.service.transfer(session, 'https://cdn.example/slow.m4s', 'media', background=True))
            await started.wait()
            try:
                result = await asyncio.wait_for(self.service.transfer(session, 'https://cdn.example/seek.m4s', 'media'), .5)
                self.assertEqual(result[2], 200)
            finally:
                release.set(); await task
