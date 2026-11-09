"""Offline API/session/cache contracts. Live Chromium/ffmpeg checks are separate."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from alloha_browser import NativeSession, SourceInvalid, SourceRefused
from alloha_delivery import AllohaDelivery, SegmentCache, install
from alloha_profiles import NativeProfiles, Profile, playback_available

IFRAME = 'https://alloha.yani.tv/?translation=66'
ORIGIN = 'https://cdn.example.com/'


class Profiles:
    def __init__(self):
        self.profiles = [Profile('native-fixture', '/fixture', '1.2.3.4', 'fixture')]
        self.promotions, self.failures, self.unavailable_urls = 0, 0, []

    async def refresh(self):
        pass

    def choose(self, iframe):
        return self.profiles[0] if self.profiles else None

    def ready(self, profile):
        self.promotions += 1

    def refused(self, profile, iframe):
        self.failures += 1

    def unavailable(self, profile, iframe):
        self.unavailable_urls.append(iframe)


class Source:
    opened = []
    fail = False
    html = False

    def __init__(self, profile, iframe, *, referer=None):
        self.referer = referer
        self.closed, self.requests = False, []
        self.socket_closed, self.playback = False, []

    async def open(self, audio=None):
        self.audio = audio or '1'
        self.opened.append(self)

    async def metadata(self):
        return {'active_id': str(len(self.opened)), 'active': self.audio, 'skip': [[1, 30]],
                'sources': [{'audioId': audio, 'label': 'Audio ' + audio, 'default': audio == '1',
                             'quality': {q: ORIGIN + audio + '-' + q + '.m3u8' for q in ('1080', '720')}}
                            for audio in ('1', '2')], 'subtitles': [{'label': 'Русский', 'lang': 'ru', 'src': ORIGIN + 'ru.vtt'}]}

    async def fetch(self, url, byte_range):
        self.requests.append((url, byte_range))
        if self.fail:
            raise SourceRefused('forced source refusal')
        if url.endswith('.m3u8'):
            body = b'#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:6,\nfirst.m4s\n#EXTINF:6,\nsecond.m4s\n#EXT-X-ENDLIST\n'
            return body, {'content-type': 'application/vnd.apple.mpegurl'}, 200, url
        if url.endswith('.vtt'):
            return b'WEBVTT\n', {'content-type': 'text/vtt'}, 200, url
        if self.html and not url.endswith('init.mp4'):
            return b'<html>Denied</html>', {'content-type': 'text/html'}, 200, url
        return b'\x00\x00\x00\x18ftypisom', {'content-type': 'video/mp4'}, 200, url

    async def close(self):
        self.closed = True

    async def update_playback(self, state):
        self.playback.append(state)


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.profiles = Profiles()
        self.service = AllohaDelivery(self.temp.name, profiles=self.profiles, factory=Source, queue_timeout=.03)
        self.service.external_address = '1.1.1.1'
        self.app = FastAPI()
        install(self.app, self.service)
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url='http://service')
        Source.opened, Source.fail, Source.html = [], False, False

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.service.close()
        self.temp.cleanup()

    async def resolve(self):
        response = await self.client.get('/resolve', params={'iframe': IFRAME})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_authenticated_viewer_state_and_closed_native_lease(self):
        import online_sessions
        subject = {'id': 'viewer'}
        online_sessions.install(self.app, lambda: subject['id'])
        response = await self.client.post('/online/prepare', json={
            'url': IFRAME, 'kind': 'video', 'quality': '720', 'clientId': 'state-viewer'})
        data = response.json()
        self.assertTrue(data['playbackTelemetry'])
        sid = data['id'];native = self.service.sessions[sid]
        state = {'time': 123.75, 'paused': False, 'rate': 1.5, 'seeking': False, 'buffering': False}
        result = await self.client.post('/online/'+sid+'/playback', json=state)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(native.source.playback[-1]['time'], 123.75)
        self.assertEqual(native.source.playback[-1]['quality'], '720')
        state.update(time=500, paused=True, seeking=True)
        self.assertEqual((await self.client.post('/online/'+sid+'/playback', json=state)).status_code, 200)
        self.assertTrue(native.source.playback[-1]['paused'])
        for invalid in [{'time': -1}, {'rate': 100}, {'paused': 'false'}, {'quality': '2160'}]:
            r = await self.client.post('/online/'+sid+'/playback', json={**state, **invalid})
            self.assertEqual(r.status_code, 422)
        subject['id'] = 'other-viewer'
        self.assertEqual((await self.client.post('/online/'+sid+'/playback', json=state)).status_code, 404)
        subject['id'] = 'viewer'
        await self.service.close_session(native)
        self.assertEqual((await self.client.post('/online/'+sid+'/heartbeat')).status_code, 410,
                         'A stale bridge must not renew a closed native Alloha session')
        self.assertEqual((await self.client.post('/online/'+sid+'/playback', json=state)).status_code, 404)
        online_sessions.sessions.pop(sid, None)

    async def test_expired_and_disconnected_native_lease_are_reported(self):
        import online_sessions
        online_sessions.install(self.app, lambda: 'viewer')
        for reason in ['expired', 'socket']:
            r = await self.client.post('/online/prepare', json={'url': IFRAME, 'kind': 'video', 'quality': '720'})
            sid = r.json()['id'];native = self.service.sessions[sid]
            if reason == 'expired':native.expires = self.service.clock()-1
            else:native.source.socket_closed = True
            self.assertEqual((await self.client.post('/online/'+sid+'/heartbeat')).status_code, 410)
            await self.service.close_session(native)
            online_sessions.sessions.pop(sid, None)

    async def test_site_prepares_only_selected_audio_and_quality(self):
        body = SimpleNamespace(url=IFRAME, quality='720', client_id='viewer', referer='https://publisher.example.com/show')
        data = await self.service.prepare_online(body, 'owner')
        session = self.service.sessions[data['id']]
        self.assertEqual(session.source.referer, body.referer)
        self.assertEqual(session.referer, body.referer)
        self.assertEqual(data['qualities'], [1080, 720], 'Other published qualities remain visible in settings')
        self.assertEqual(list(session.translations), ['1'])
        self.assertEqual(list(session.translations['1']['qualities']), ['720'])
        requests = Source.opened[-1].requests
        self.assertEqual([url for url, _ in requests if url.endswith('.m3u8')], [ORIGIN + '1-720.m3u8'])
        self.assertTrue(any(url.endswith('first.m4s') for url, _ in requests))
        self.assertEqual((await self.client.get('/play/'+data['id']+'/1/720.m3u8')).status_code, 200)

    async def test_contract_rewrites_every_resource_and_checks_actual_segments(self):
        data = await self.resolve()
        self.assertEqual(set(data), {'sid', 'active_id', 'skip', 'subtitles', 'translations'})
        self.assertEqual(len(data['translations']), 2)
        self.assertEqual(data['translations'][0]['qualities'], ['1080', '720'])
        self.assertTrue(any(url.endswith('first.m4s') for url, _ in Source.opened[0].requests))
        self.assertEqual(self.profiles.promotions, 1)
        playlist = await self.client.get(data['translations'][0]['play']['1080'])
        self.assertEqual(playlist.status_code, 200)
        self.assertNotIn(ORIGIN, playlist.text)
        self.assertIn('#EXT-X-MAP:URI="/hls/', playlist.text)
        urls = [line for line in playlist.text.splitlines() if line.startswith('/hls/')]
        before = len(Source.opened[0].requests)
        for url in (urls[0], urls[1], urls[0]):
            response = await self.client.get(url)
            self.assertEqual(response.status_code, 200)
        self.assertEqual(len(Source.opened[0].requests) - before, 2, 'backwards seek should use the disk cache')
        denied = await self.client.get('/hls/' + data['sid'], params={'u': 'https://internal.example/private'})
        self.assertEqual(denied.status_code, 404)

    async def test_manifest_and_init_are_insufficient_when_first_media_is_html(self):
        Source.html = True
        response = await self.client.get('/resolve', params={'iframe': IFRAME})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.profiles.failures, 0, 'Invalid content must not quarantine a browser for other titles')
        self.assertEqual(self.profiles.unavailable_urls, [IFRAME])
        self.assertEqual(self.profiles.promotions, 0)
        self.assertFalse(self.service.sessions)
        self.assertTrue(Source.opened[0].closed)

    async def test_source_refusal_is_409_without_retry_and_releases_slot(self):
        Source.fail = True
        response = await self.client.get('/resolve', params={'iframe': IFRAME})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(Source.opened[0].requests), 1)
        self.assertEqual(self.profiles.failures, 1)
        Source.fail = False
        await self.resolve()

    async def test_two_sessions_third_waits_then_503_with_retry_after(self):
        results = await asyncio.gather(*(self.client.get('/resolve', params={'iframe': IFRAME}) for _ in range(3)))
        self.assertEqual(sorted(r.status_code for r in results), [200, 200, 503])
        rejected = next(r for r in results if r.status_code == 503)
        self.assertEqual(rejected.headers['retry-after'], '30')

    async def test_audio_change_creates_new_sid_and_native_source_selection(self):
        referer = 'https://publisher.example.com/show'
        data = (await self.client.get('/resolve', params={'iframe': IFRAME, 'referer': referer})).json()
        response = await self.client.get(data['translations'][1]['play']['720'], follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertNotIn(data['sid'], response.headers['location'])
        self.assertEqual(Source.opened[-1].audio, '2')
        self.assertEqual(Source.opened[-1].referer, referer)
        self.assertTrue(Source.opened[0].closed)
        self.assertEqual((await self.client.get(response.headers['location'])).status_code, 200)
        expired = await self.client.get(data['translations'][0]['play']['720'])
        self.assertEqual(expired.status_code, 404)

    async def test_expiry_shutdown_and_quality_degradation(self):
        data = await self.resolve()
        sid = data['sid']
        degraded = await self.client.get(f'/play/{sid}/1/900.m3u8')
        self.assertEqual(degraded.headers['x-alloha-quality'], '720')
        self.assertEqual(degraded.headers['x-alloha-degradation'], 'quality-unavailable')
        self.service.sessions[sid].expires = self.service.clock() - 1
        expired = await self.client.get(data['translations'][0]['play']['720'])
        self.assertEqual(expired.status_code, 404)
        await self.service.expire()
        self.assertTrue(Source.opened[0].closed)
        await self.resolve()
        await self.service.close()
        self.assertTrue(all(s.closed for s in Source.opened))

    async def test_other_providers_are_rejected_before_browser_start(self):
        response = await self.client.get('/resolve', params={'iframe': 'https://kodik.info/seria/1'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(Source.opened, [])

    async def test_existing_player_uses_the_alloha_bridge_and_releases_it(self):
        import online_sessions
        online_sessions.install(self.app, lambda: 'fixture-owner')
        response = await self.client.post('/online/prepare', json={
            'kind': 'video', 'url': IFRAME, 'quality': '720', 'clientId': 'same-player'})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertRegex(data['url'], r'^/online/[\w-]{20,80}/[\w-]{10,40}$')
        playlist = await self.client.get(data['url'])
        self.assertEqual(playlist.status_code, 200, playlist.text)
        self.assertEqual(playlist.headers['x-alloha-quality'], '720')
        self.assertTrue((await self.client.post('/online/' + data['id'] + '/heartbeat')).json()['expiresIn'] > 0)
        await self.client.delete('/online/' + data['id'])
        self.assertNotIn(data['id'], online_sessions.sessions)
        self.assertTrue(Source.opened[-1].closed)


class BootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_iframe_fails_without_waiting_for_player_timeout(self):
        session = NativeSession(None, IFRAME)
        async def waiting(*args, **kwargs):
            await asyncio.Event().wait()
        session.frame = SimpleNamespace(wait_for_function=waiting)
        response = SimpleNamespace(url=IFRAME, status=404, request=SimpleNamespace(resource_type='document'))
        await session.observe(response)
        with self.assertRaises(SourceInvalid) as error:
            await asyncio.wait_for(session.wait_player(), .5)
        self.assertEqual(error.exception.status, 404)

    async def test_refused_iframe_stays_a_real_access_refusal(self):
        session = NativeSession(None, IFRAME)
        async def waiting(*args, **kwargs):
            await asyncio.Event().wait()
        session.frame = SimpleNamespace(wait_for_function=waiting)
        await session.observe(SimpleNamespace(url=IFRAME, status=403, request=SimpleNamespace(resource_type='document')))
        with self.assertRaises(SourceRefused):
            await asyncio.wait_for(session.wait_player(), .5)


class ProfileRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_pool_keeps_legacy_health_and_refreshes_channels_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1000]
            pool = NativeProfiles(directory, clock=lambda: now[0])
            debian = Profile('debian-original', '/fixture', '1.2.3.4', 'debian-security/bookworm')
            playwright = Profile('playwright-original', '/fixture', '2.3.4.5', 'playwright/1')
            debian.retired = True
            pool.save(debian)
            debian.retired = False
            with patch.object(pool, '_debian_profile', AsyncMock(return_value=debian)), patch.object(
                    pool, '_playwright_profile', AsyncMock(return_value=playwright)):
                await pool.refresh()
            self.assertEqual(len(pool.profiles), 12)
            self.assertEqual(len({profile.id for profile in pool.profiles}), 12)
            self.assertTrue(next(profile for profile in pool.profiles if profile.id == debian.id).retired)
            first = pool.choose(IFRAME)
            pool.refused(first, IFRAME)
            self.assertEqual(pool.choose(IFRAME).channel, playwright.channel)

            fallback = next(profile for profile in pool.profiles if profile.id == playwright.id)
            now[0] += 3601
            upgrade = Profile('debian-updated', '/fixture', '3.4.5.6', debian.channel)
            with patch.object(pool, '_debian_profile', AsyncMock(return_value=upgrade)), patch.object(
                    pool, '_playwright_profile', AsyncMock(side_effect=RuntimeError('release unavailable'))):
                await pool.refresh()
            self.assertEqual(len(pool.profiles), 12)
            self.assertNotIn(debian.id, {profile.id for profile in pool.profiles})
            self.assertIs(next(profile for profile in pool.profiles if profile.id == playwright.id), fallback)
            self.assertTrue(playback_available(directory))
            for profile in pool.profiles:
                profile.retired = True
                pool.save(profile)
            self.assertFalse(playback_available(directory))


class ProfileTests(unittest.TestCase):
    def test_missing_title_does_not_quarantine_profile_for_other_titles(self):
        with tempfile.TemporaryDirectory() as directory:
            pool = NativeProfiles(directory)
            profile = Profile('native', '/fixture', '1.2.3.4', 'signed-fixture')
            pool.profiles = [profile]
            for _ in range(3):
                pool.unavailable(profile, IFRAME)
            self.assertEqual(profile.refusals, 0)
            self.assertEqual(profile.quarantine_until, 0)
            self.assertIsNone(pool.choose(IFRAME))
            self.assertIs(pool.choose(IFRAME+'&other=1'), profile)

    def test_three_refusals_quarantine_and_eighteen_successes_retire(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1000]
            pool = NativeProfiles(directory, clock=lambda: now[0])
            profile = Profile('native', '/fixture', '1.2.3.4', 'signed-fixture')
            pool.profiles = [profile]
            for _ in range(3):
                pool.refused(profile, IFRAME)
            self.assertIsNone(pool.choose(IFRAME))
            now[0] += 901
            self.assertIs(pool.choose(IFRAME), profile)
            for _ in range(18):
                pool.ready(profile)
            self.assertTrue(profile.retired)
            self.assertIsNone(pool.choose(IFRAME))

    def test_profile_health_survives_restart_and_pending_sessions_reserve_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            pool = NativeProfiles(directory)
            profile = Profile('native', '/fixture', '1.2.3.4', 'signed-fixture')
            pool.profiles = [profile]
            for _ in range(17):
                pool.ready(profile)
            profile.reservations = 1
            self.assertIsNone(pool.choose(IFRAME))
            pool.ready(profile)
            restarted = NativeProfiles(directory)
            reloaded = restarted.restore(Profile('native', '/fixture', '1.2.3.4', 'signed-fixture'))
            self.assertEqual(reloaded.successes, 18)
            self.assertTrue(reloaded.retired)

    def test_segment_cache_ttl_and_range_separation(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = SegmentCache(directory, ttl=3600)
            url = ORIGIN + 'one.m4s'
            value = (b'bytes', {'content-type': 'video/mp4'}, 200, url)
            cache.put(url, '', value)
            self.assertEqual(cache.get(url), value)
            self.assertIsNone(cache.get(url, 'bytes=0-1'))
            _, metadata = cache.paths(url, '')
            record = json.loads(metadata.read_text())
            record['created'] -= 3601
            metadata.write_text(json.dumps(record))
            self.assertIsNone(cache.get(url))
