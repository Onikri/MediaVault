import base64, hashlib, hmac, json, sys, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
import guest_profiles

KEY = b'k' * 32


class Store:
    def __init__(self):
        self.values, self.lock = {}, threading.RLock()

    def setting(self, name, value=None):
        if value is not None:
            self.values[name] = json.loads(json.dumps(value))
        return self.values.get(name)

    def consume(self, name):
        return self.values.pop(name, None)


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def sign(payload):
    body = b64(json.dumps(payload).encode())
    return body + '.' + b64(hmac.digest(KEY, body.encode(), 'sha256'))


def decode(authorization):
    try:
        body, signature = authorization.removeprefix('Bearer ').split('.')
        assert hmac.compare_digest(signature, b64(hmac.digest(KEY, body.encode(), 'sha256')))
        payload = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
        assert payload['exp'] > time.time()
        return payload
    except Exception:
        raise HTTPException(401, 'no') from None


def owner(authorization: str = Header(default='')):
    payload = decode(authorization)
    if payload.get('role') == 'guest':
        raise HTTPException(403, 'owner only')
    return payload['sub']


class GuestProfiles(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        app = FastAPI()
        guest, _, _ = guest_profiles.install(app, owner, lambda: self.store, sign, decode)

        @app.get('/viewer')
        def view(record=Depends(guest)):
            return {'id': record['id']}

        @app.get('/admin-only')
        def admin(subject=Depends(owner)):
            return {'ok': True}

        self.client = TestClient(app)
        self.admin = {'Authorization': 'Bearer ' + sign({'sub': 'owner', 'exp': time.time() + 600})}

    def create(self, **body):
        response = self.client.post('/guests', json={'name': 'Аня', **body}, headers=self.admin)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_invite_enroll_login_and_guest_cannot_use_owner_routes(self):
        created = self.create(days=7)
        self.assertFalse(created['guest']['enrolled'])
        self.assertIsNotNone(created['guest']['expiresAt'])
        preview = self.client.get('/guests/invite/' + created['invite']).json()
        self.assertEqual(preview['name'], 'Аня')
        enrolled = self.client.post('/guests/enroll', json={'invite': created['invite'], 'login': 'Anya', 'password': 'correct horse'})
        self.assertEqual(enrolled.status_code, 200, enrolled.text)
        token = {'Authorization': 'Bearer ' + enrolled.json()['token']}
        self.assertEqual(self.client.get('/viewer', headers=token).status_code, 200)
        self.assertEqual(self.client.get('/admin-only', headers=token).status_code, 403)
        self.assertEqual(self.client.get('/guests', headers=token).status_code, 403)
        # The invite is single-use and the hash, not the password, is stored.
        self.assertEqual(self.client.get('/guests/invite/' + created['invite']).status_code, 404)
        self.assertNotIn('correct horse', json.dumps(self.store.values))
        login = self.client.post('/guests/login', json={'login': 'anya', 'password': 'correct horse'})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.post('/guests/login', json={'login': 'anya', 'password': 'wrong password'}).status_code, 401)

    def test_disable_expire_and_delete_are_immediate(self):
        created = self.create()
        self.assertIsNone(created['guest']['expiresAt'])
        session = self.client.post('/guests/enroll', json={'invite': created['invite'], 'login': 'boris', 'password': '12345678'}).json()
        token, identity = {'Authorization': 'Bearer ' + session['token']}, created['guest']['id']
        self.client.post('/guests/' + identity, json={'disabled': True}, headers=self.admin)
        self.assertEqual(self.client.get('/viewer', headers=token).status_code, 401)
        self.client.post('/guests/' + identity, json={'disabled': False}, headers=self.admin)
        self.assertEqual(self.client.get('/viewer', headers=token).status_code, 200)
        record = self.store.values['guest:' + identity]
        record['expires_at'] = int(time.time()) - 5
        self.assertEqual(self.client.get('/viewer', headers=token).status_code, 401)
        self.assertEqual(self.client.post('/guests/login', json={'login': 'boris', 'password': '12345678'}).status_code, 401)
        self.client.post('/guests/' + identity, json={'unlimited': True}, headers=self.admin)
        self.assertEqual(self.client.get('/viewer', headers=token).status_code, 200)
        self.client.post('/guests/' + identity + '/sessions/reset', headers=self.admin)
        self.assertEqual(self.client.get('/viewer', headers=token).status_code, 401)
        self.client.delete('/guests/' + identity, headers=self.admin)
        self.assertEqual(self.client.get('/guests', headers=self.admin).json()['guests'], [])
        self.assertEqual(self.client.post('/guests/login', json={'login': 'boris', 'password': '12345678'}).status_code, 401)

    def test_login_taken_and_validation(self):
        first, second = self.create(), self.create()
        self.client.post('/guests/enroll', json={'invite': first['invite'], 'login': 'same', 'password': '12345678'})
        taken = self.client.post('/guests/enroll', json={'invite': second['invite'], 'login': 'same', 'password': '12345678'})
        self.assertEqual(taken.status_code, 409)
        short = self.client.post('/guests/enroll', json={'invite': second['invite'], 'login': 'other', 'password': 'short'})
        self.assertEqual(short.status_code, 422)
        reset = self.client.post('/guests/' + first['guest']['id'] + '/invite', headers=self.admin).json()
        self.assertTrue(self.client.get('/guests/invite/' + reset['invite']).json()['reset'])


if __name__ == '__main__':
    unittest.main()
