"""Relay contracts with provider fixtures; live VM checks are documented separately."""
import asyncio,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import httpx
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from lyric_identity import identity,cache_key,match
from music_lyrics import LyricsRelay,install,Upstream

QUERY={'titles':['Otonoke (オトノケ)'],'artists':['Creepy Nuts'],'duration':187,'rich':True}
LINE={'phase':'ready','source':'LRCLIB','lrc':'[00:00.00]Fixture line','plainText':'Fixture line'}

class Identity(unittest.TestCase):
    def test_native_and_latin_names_are_not_lost_or_collapsed(self):
        a={**identity(['光'],['米津玄師']),'duration':150,'rich':True}
        b={**identity(['影'],['米津玄師']),'duration':150,'rich':True}
        self.assertNotEqual(cache_key(a),cache_key(b))
        self.assertNotEqual(cache_key(a),cache_key({**a,'rich':False}))
        self.assertNotEqual(cache_key(a),cache_key({**a,'duration':151}))
        forms=identity(['米津玄師 Kenshi Yonezu – IRIS OUT Kenshi Yonezu (米津玄師)'],['Kenshi Yonezu (米津玄師)'])
        self.assertEqual(forms['titles'][0],'IRIS OUT')
    def test_no_covers_wrong_artists_or_full_track_timing_for_tv_size(self):
        q={**QUERY,**identity(QUERY['titles'],QUERY['artists'])}
        self.assertIsNotNone(match(q,'オトノケ','Creepy Nuts',187))
        for title,artist,duration in [('Otonoke (cover)','Creepy Nuts',187),('Otonoke','Other artist',187),('Otonoke','Creepy Nuts',90)]:
            self.assertIsNone(match(q,title,artist,duration))
        self.assertTrue(match(q,'Otonoke','Creepy Nuts',195)['timingMismatch'])

class Relay(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(404)))
        self.relay=LyricsRelay(self.directory.name,budget=.12,client=self.client);self.relay.key='fixture-key'
        await self.relay.start()
    async def asyncTearDown(self):
        await self.relay.close();await self.client.aclose()
    async def test_fast_provider_failure_is_removed_and_hedge_finishes_without_busy_loop(self):
        self.relay.budget=.8
        self.relay.musixmatch=AsyncMock(side_effect=Upstream('unavailable'))
        self.relay.lrclib=AsyncMock(return_value=LINE)
        result=await self.relay.lookup(QUERY)
        self.assertEqual(result['phase'],'ready');self.assertEqual(self.relay.pending,{})
        self.assertLess(result['elapsedMs'],800)
    async def test_deadline_cancels_slow_upstreams_and_includes_queue_wait(self):
        cancelled=asyncio.Event()
        async def slow(q):
            try:await asyncio.sleep(5)
            finally:cancelled.set()
        self.relay.musixmatch=slow
        start=time.monotonic();result=await self.relay.lookup(QUERY)
        self.assertEqual(result['phase'],'error');self.assertLess(time.monotonic()-start,.3)
        self.assertTrue(cancelled.is_set())
        for _ in range(8):await self.relay.slots.acquire()
        start=time.monotonic();await self.relay.lookup({**QUERY,'duration':188})
        self.assertLess(time.monotonic()-start,.3)
        for _ in range(8):self.relay.slots.release()
    async def test_identical_requests_share_work_and_one_disconnected_caller_does_not_cancel_it(self):
        started=asyncio.Event();release=asyncio.Event()
        async def lookup(q):started.set();await release.wait();return {**LINE,'precision':'word','lines':[{'start':0,'end':2,'text':'Fixture','words':[]}]}
        self.relay.musixmatch=AsyncMock(side_effect=lookup)
        first=asyncio.create_task(self.relay.lookup(QUERY));await started.wait()
        second=asyncio.create_task(self.relay.lookup(QUERY));await asyncio.sleep(.01)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):await first
        release.set();result=await second
        self.assertEqual(result['phase'],'ready');self.relay.musixmatch.assert_awaited_once()
    async def test_cache_survives_restart_and_plain_requests_do_not_poison_word_requests(self):
        self.relay.musixmatch=AsyncMock(return_value={**LINE,'precision':'word'})
        await self.relay.lookup(QUERY)
        await self.relay.close()
        restored=LyricsRelay(self.directory.name,budget=.1,client=self.client);restored.key='fixture-key';await restored.start()
        try:
            restored.search=AsyncMock(return_value=LINE)
            hit=await restored.lookup(QUERY);self.assertTrue(hit['cached']);restored.search.assert_not_awaited()
            await restored.lookup({**QUERY,'rich':False});restored.search.assert_awaited_once()
        finally:await restored.close()
    async def test_cold_request_does_not_mint_tokens_and_does_not_return_authentication(self):
        self.relay.key='';self.relay.token=''
        with self.assertRaises(Upstream):await self.relay.musixmatch(QUERY)
        self.assertEqual(self.relay.token,'')
    async def test_richsync_produces_real_word_times_and_rejects_restricted_and_decoy_lyrics(self):
        q={**QUERY,**identity(QUERY['titles'],QUERY['artists'])}
        self.relay.key=''
        def macro(lyrics):return {'macro_calls':{'matcher.track.get':{'message':{'body':{'track':{'track_name':'Otonoke','artist_name':'Creepy Nuts','track_length':187,'track_id':7,'has_richsync':1}}}},'track.lyrics.get':{'message':{'body':{'lyrics':lyrics}}}}}
        self.relay.mxm=AsyncMock(side_effect=[macro({'lyrics_body':'Fixture lyric'}),{'richsync':{'richsync_body':json.dumps([{'ts':2,'te':5,'x':'Fixture words','l':[{'c':'Fixture ','o':0},{'c':'words','o':1.5}]}])}}])
        result=await self.relay.musixmatch(q)
        self.assertEqual(result['precision'],'word');self.assertEqual(result['lines'][0]['words'][1]['start'],3.5)
        self.relay.mxm=AsyncMock(return_value=macro({'restricted':1,'lyrics_body':'Must not return'}))
        result=await self.relay.musixmatch(q);self.assertEqual(result['phase'],'restricted');self.assertNotIn('plainText',result)
        self.relay.mxm=AsyncMock(return_value=macro({'lyrics_body':'wob gopini den tefe woxica fero gogoh vudob wiya'}))
        with self.assertRaises(Upstream):await self.relay.musixmatch(q)

class Routes(unittest.TestCase):
    def test_auth_and_input_validation_are_required(self):
        app=FastAPI();relay=AsyncMock()
        def denied():raise HTTPException(401)
        install(app,denied,relay)
        with TestClient(app) as client:self.assertEqual(client.post('/music/lyrics',json=QUERY).status_code,401)
        relay.lookup.assert_not_awaited()
        app=FastAPI();install(app,lambda:'owner',relay)
        with TestClient(app) as client:
            for body in [{**QUERY,'duration':0},{**QUERY,'duration':9000},{**QUERY,'titles':[]},{**QUERY,'rich':True,'upstream':'http://localhost'}]:
                self.assertEqual(client.post('/music/lyrics',json=body).status_code,422)
