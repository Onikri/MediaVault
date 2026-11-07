import sys, threading, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.testclient import TestClient
import guest_activity
from guest_activity import Activity, Middleware, client_address, stream_owner


class Store:
    def __init__(self):
        self.values, self.lock, self.writes = {}, threading.RLock(), 0

    def setting(self, name, value=None):
        if value is not None:
            self.writes += 1
            self.values[name] = value
        return self.values.get(name)

    def consume(self, name):
        return self.values.pop(name, None)


class Clock:
    def __init__(self):
        self.now = 1_800_000_000

    def __call__(self):
        return self.now


class Session:
    def __init__(self, owner, kind):
        self.owner, self.kind = owner, kind


ABYSS = {'id': 'anime:shikimori:34599', 'kind': 'anime', 'ids': {'mal': '34599'}, 'title': 'Созданный в Бездне'}


class Addresses(unittest.TestCase):
    def test_forwarded_address_is_trusted_only_from_the_private_proxy(self):
        caddy = {'client': ('172.18.0.3', 1), 'headers': [(b'x-forwarded-for', b'203.0.113.9')]}
        self.assertEqual(client_address(caddy), '203.0.113.9')
        spoof = {'client': ('93.184.216.34', 1), 'headers': [(b'x-forwarded-for', b'10.0.0.1')]}
        self.assertEqual(client_address(spoof), '93.184.216.34')
        junk = {'client': ('172.18.0.3', 1), 'headers': [(b'x-forwarded-for', b'not-an-ip')]}
        self.assertEqual(client_address(junk), '172.18.0.3')


class Recording(unittest.TestCase):
    def setUp(self):
        self.store, self.clock = Store(), Clock()
        self.activity = Activity(lambda: self.store, clock=self.clock)
        sessions = {'tokenvideo1': Session('guest:g1', 'video'), 'tokenowner1': Session('owner', 'video')}
        app = FastAPI()

        @app.get('/online/{token}/{resource}')
        def stream(token: str, resource: str):
            return Response(b'x' * 5000, media_type='video/mp2t')

        @app.get('/api')
        def api(request: Request):
            guest_activity.client.get()  # the context reaches sync endpoints
            self.seen = guest_activity.client.get()
            return {'ok': True}

        app.add_middleware(Middleware, activity=self.activity,
                           identify=lambda value: 'guest:g1' if value == 'Bearer guest' else 'owner',
                           stream_owner=stream_owner(sessions))
        self.client = TestClient(app)

    def test_traffic_is_attributed_to_the_guest_and_the_open_title(self):
        self.activity.opened('g1', ABYSS)
        headers = {'x-forwarded-for': '203.0.113.9', 'user-agent': 'Firefox'}
        self.client.get('/online/tokenvideo1/seg1', headers=headers)
        self.client.get('/online/tokenowner1/seg1')
        self.client.get('/api', headers={'Authorization': 'Bearer guest', 'user-agent': 'Firefox'})
        self.client.get('/api', headers={'Authorization': 'Bearer owner'})
        report = self.activity.report('g1')
        self.assertEqual(report['summary']['requests'], 2, 'Owner requests are never recorded')
        self.assertEqual(report['categories']['video'], 5000)
        self.assertEqual(report['titles'][0]['bytes'], 5000)
        self.assertEqual(report['titles'][0]['title'], 'Созданный в Бездне')
        self.assertTrue(report['summary']['watching'])
        self.assertEqual(report['summary']['bytesToday'], report['summary']['bytes'])
        self.assertEqual(report['days'][-1]['requests'], 2)

    def test_reopening_within_ten_minutes_is_one_visit_and_persisted(self):
        self.activity.opened('g1', ABYSS)
        self.clock.now += 60
        self.activity.opened('g1', ABYSS)
        self.activity.started('g1', 'video', 'yummyanime.tv')
        self.clock.now += 3600
        self.activity.opened('g1', ABYSS)
        report = self.activity.report('g1')
        self.assertEqual(report['titles'][0]['opens'], 2)
        self.assertEqual(report['titles'][0]['plays'], 1)
        self.assertEqual([e['action'] for e in report['events']], ['Открыл тайтл', 'Запустил просмотр', 'Открыл тайтл'])
        self.activity.flush()
        fresh = Activity(lambda: self.store, clock=self.clock)
        self.assertEqual(fresh.report('g1')['titles'][0]['opens'], 2)
        self.activity.forget('g1')
        self.assertNotIn('guest-activity:g1', self.store.values)

    def test_writes_are_batched_and_logs_are_bounded(self):
        for index in range(600):
            self.activity.event('g1', 'Действие', detail=str(index))
        self.assertLessEqual(self.store.writes, 2)
        self.assertEqual(len(self.activity.report('g1')['events']), guest_activity.EVENTS)
        self.assertEqual(self.activity.report('g1')['events'][0]['detail'], '599')

    def test_a_new_address_is_logged(self):
        self.activity.request('g1', '203.0.113.9', 'Chrome')
        self.clock.now += 5
        self.activity.request('g1', '198.51.100.1', 'Safari')
        report = self.activity.report('g1')
        self.assertEqual(report['summary']['addresses'], 2)
        self.assertEqual(report['events'][0]['action'], 'Новый IP-адрес')
        self.assertEqual(report['summary']['lastAddress'], '198.51.100.1')


if __name__ == '__main__':
    unittest.main()


class Placeholder(unittest.TestCase):
    def test_loading_placeholder_is_replaced_once_metadata_arrives(self):
        activity = Activity(lambda: Store())
        activity.opened('g1', {**ABYSS, 'title': 'Загружаем тайтл…'})
        activity.opened('g1', ABYSS)
        report = activity.report('g1')
        self.assertEqual(report['events'][0]['title'], 'Созданный в Бездне')
        self.assertEqual(report['titles'][0]['opens'], 1)


class NewAddress(unittest.TestCase):
    def test_new_address_is_logged_even_when_an_endpoint_saw_it_first(self):
        activity = Activity(lambda: Store())
        token = guest_activity.client.set(('203.0.113.9', 'Chrome'))
        activity.opened('g1', ABYSS)
        guest_activity.client.reset(token)
        token = guest_activity.client.set(('198.51.100.1', 'Safari'))
        activity.opened('g1', {**ABYSS, 'ids': {'mal': '5114'}, 'title': 'FMA'})
        guest_activity.client.reset(token)
        activity.request('g1', '198.51.100.1', 'Safari')
        actions = [e['action'] for e in activity.report('g1')['events']]
        self.assertEqual(actions.count('Новый IP-адрес'), 1)
