"""Owner control center contracts: room listing/closing and editable site rules.

Real FastAPI routes and WebSocket close messages; media is a fixture size only.
"""
import sys, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
import guest_profiles, site_rules
import watch_rooms as rooms
from test_guest_profiles import Store, sign, decode, owner as profile_owner


class RoomConsole(unittest.TestCase):
    def setUp(self):
        rooms.rooms.clear(); rooms.attempts.clear()
        self.rules = dict(rooms.DEFAULT_RULES)

        def viewer(authorization: str = Header(default='')):
            if authorization == 'Bearer owner': return 'owner'
            if authorization == 'Bearer guest': return 'guest:abc123'
            raise HTTPException(401)

        def admin(authorization: str = Header(default='')):
            if authorization != 'Bearer owner': raise HTTPException(403, 'owner only')
            return 'owner'

        self.app = FastAPI(); rooms.install(self.app, viewer, admin, lambda: self.rules)
        self.client = TestClient(self.app); self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None); rooms.rooms.clear(); rooms.attempts.clear()

    def create(self, who='owner', title='Fixture video'):
        return self.client.post('/rooms', headers={'Authorization': 'Bearer ' + who}, json={'title': title, 'password': 'room-secret', 'media': {'size': 16}})

    def test_owner_lists_rooms_without_secrets_and_guests_cannot(self):
        created = self.create().json()
        self.client.post('/rooms/' + created['id'] + '/join', json={'password': 'room-secret', 'name': 'Аня'})
        listed = self.client.get('/rooms', headers={'Authorization': 'Bearer owner'})
        self.assertEqual(listed.status_code, 200, listed.text)
        room = listed.json()['rooms'][0]
        self.assertEqual(room['title'], 'Fixture video')
        self.assertEqual([m['name'] for m in room['members']], ['Ведущий', 'Аня'])
        self.assertGreater(room['expiresAt'], time.time() + 5 * 3600)
        text = listed.text
        self.assertNotIn(created['token'], text); self.assertNotIn('room-secret', text); self.assertNotIn('digest', text)
        self.assertEqual(self.client.get('/rooms', headers={'Authorization': 'Bearer guest'}).status_code, 403)

    def test_owner_closes_room_and_members_are_told(self):
        created = self.create().json()
        joined = self.client.post('/rooms/' + created['id'] + '/join', json={'password': 'room-secret', 'name': 'Аня'}).json()
        with self.client.websocket_connect('/rooms/' + created['id'] + '/socket') as socket:
            socket.send_json({'type': 'hello', 'token': joined['token']})
            closed = self.client.delete('/rooms/' + created['id'], headers={'Authorization': 'Bearer owner'})
            self.assertEqual(closed.status_code, 200, closed.text)
            for _ in range(15):
                if socket.receive_json()['type'] == 'closed': break
            else: self.fail('Members were not told the room closed')
        self.assertEqual(self.client.get('/rooms/' + created['id'] + '/preview').status_code, 410)
        self.assertEqual(self.client.get('/rooms', headers={'Authorization': 'Bearer owner'}).json()['rooms'], [])

    def test_rules_limit_rooms_members_lifetime_and_guest_hosting(self):
        self.rules.update(perOwner=1, members=1, hours=2, guestsMayHost=False)
        first = self.create().json()
        self.assertEqual(self.create(title='Second').status_code, 429)
        self.assertEqual(self.create('guest').status_code, 403)
        self.assertLess(self.client.get('/rooms', headers={'Authorization': 'Bearer owner'}).json()['rooms'][0]['expiresAt'], time.time() + 2 * 3600 + 5)
        join = lambda name: self.client.post('/rooms/' + first['id'] + '/join', json={'password': 'room-secret', 'name': name})
        self.assertEqual(join('Аня').status_code, 200)
        self.assertEqual(join('Боря').status_code, 429)


class Rules(unittest.TestCase):
    def test_defaults_merge_and_damaged_values_fall_back(self):
        store = Store()
        self.assertEqual(site_rules.current(store), site_rules.DEFAULTS)
        store.setting(site_rules.KEY, {'rooms': {'members': 4}})
        self.assertEqual(site_rules.current(store)['rooms']['members'], 4)
        self.assertEqual(site_rules.current(store)['rooms']['limit'], 16)
        store.setting(site_rules.KEY, {'rooms': {'members': 999}})
        self.assertEqual(site_rules.current(store), site_rules.DEFAULTS)
        with self.assertRaises(ValueError):
            site_rules.Rules.model_validate({'rooms': {'hours': 0}})

    def test_new_guests_receive_default_rights(self):
        store = Store(); app = FastAPI()
        guest_profiles.install(app, profile_owner, lambda: store, sign, decode)
        client = TestClient(app); admin = {'Authorization': 'Bearer ' + sign({'sub': 'owner', 'exp': time.time() + 600})}
        site_rules.save(store, site_rules.Rules.model_validate({'guests': {'read': False}}))
        made = client.post('/guests', json={'name': 'Аня'}, headers=admin).json()
        self.assertEqual(made['guest']['access']['scope'], 'all')
        self.assertTrue(made['guest']['access']['watch']); self.assertFalse(made['guest']['access']['read'])


if __name__ == '__main__':
    unittest.main()
