"""Scheduler contracts, not live Chromium or network performance measurements."""
import asyncio
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import browser_player as player
from source_parser import SourceError


class ParallelPlayerTests(unittest.TestCase):
    def setUp(self):
        player._playback_cache.clear()
        player._pending.clear()

    def test_distinct_players_overlap_but_identical_player_uses_one_browser(self):
        barrier=threading.Barrier(2)
        state={'active':0,'peak':0,'calls':0}
        lock=threading.Lock()
        async def probe(url,referer=None,metadata=None):
            with lock:
                state['active']+=1;state['peak']=max(state['peak'],state['active']);state['calls']+=1
            barrier.wait(timeout=3)
            await asyncio.sleep(.08)
            with lock:state['active']-=1
            return [{'url':'https://cdn.example.com/stream.m3u8','type':'hls','quality':1080}]
        with patch.object(player,'_slots',threading.BoundedSemaphore(2)),patch.object(player,'_extract',side_effect=probe):
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures=[pool.submit(player.extract,'https://embed.example.com/'+name) for name in ['one','one','two']]
                values=[future.result(timeout=5) for future in futures]
        self.assertEqual(state,{'active':0,'peak':2,'calls':2})
        values[0][0]['quality']=1
        self.assertEqual(values[1][0]['quality'],1080)
        self.assertEqual(player._pending,{})

    def test_failed_leader_releases_pending_and_slot_for_retry(self):
        async def fail(*args,**kwargs):raise SourceError('Источник временно недоступен.')
        async def succeed(*args,**kwargs):return [{'url':'https://cdn.example.com/video.mp4','type':'mp4'}]
        with patch.object(player,'_slots',threading.BoundedSemaphore(1)),patch.object(player,'_extract',side_effect=fail):
            with self.assertRaises(SourceError):player.extract('https://embed.example.com/retry')
        self.assertFalse(player._pending)
        with patch.object(player,'_extract',side_effect=succeed):self.assertEqual(len(player.extract('https://embed.example.com/retry')),1)

    def test_worker_configuration_is_bounded(self):
        for raw,expected in [('0',1),('1',1),('2',2),('200',2),('bad',1)]:
            with patch.dict('os.environ',{'MEDIA_VAULT_BROWSER_WORKERS':raw}):self.assertEqual(player.browser_workers(),expected)
