import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives import hashes
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import api

def b64(value):return base64.urlsafe_b64encode(value).decode().rstrip('=')

class DeviceSessions(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.environment=patch.dict(os.environ,{'DATA_DIR':self.directory.name,'MEDIA_VAULT_DISABLE_WORKER':'1'})
        self.environment.start()
        self.secret=patch.object(api,'CLIENT_SECRET','server-only-secret');self.secret.start()
        self.url=patch.object(api,'PUBLIC_URL','https://import.example.test');self.url.start()
        self.identity={'sub':'owner-fixture','email':'roma.shevchenko2020@gmail.com','email_verified':True}
        self.google=patch.object(api,'google_identity',side_effect=lambda _:self.identity);self.google.start()
        self.client=TestClient(api.app);self.client.__enter__()
        self.key=ec.generate_private_key(ec.SECP256R1())
        p=self.key.public_key().public_numbers()
        self.jwk={'kty':'EC','crv':'P-256','x':b64(p.x.to_bytes(32,'big')),'y':b64(p.y.to_bytes(32,'big'))}

    def tearDown(self):
        self.client.__exit__(None,None,None);self.google.stop();self.url.stop();self.secret.stop();self.environment.stop();self.directory.cleanup()

    def register(self):
        api.store.setting('google:'+self.identity['sub'],{'refresh_token':'never-expose-refresh-token'})
        r=self.client.post('/devices/register',json={'public_key':self.jwk},headers={'Authorization':'Bearer short-google-fixture'})
        self.assertEqual(r.status_code,200,r.text);self.assertNotIn('never-expose',r.text)
        return r.json()['id']

    def proof(self,identity,key=None):
        challenge=self.client.post('/devices/challenge',json={'id':identity});self.assertEqual(challenge.status_code,200)
        nonce=challenge.json()['nonce'];raw=(key or self.key).sign(('MediaVault device session\n'+identity+'\n'+nonce).encode(),ec.ECDSA(hashes.SHA256()))
        r,s=decode_dss_signature(raw)
        return {'id':identity,'nonce':nonce,'signature':b64(r.to_bytes(32,'big')+s.to_bytes(32,'big'))}

    def test_real_device_signature_restores_only_short_token_and_replay_is_denied(self):
        identity=self.register();proof=self.proof(identity)
        def refresh(credentials,request):credentials.token='fresh-short-google-token'
        with patch('google.oauth2.credentials.Credentials.refresh',refresh):
            r=self.client.post('/devices/restore',json=proof);self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()['access_token'],'fresh-short-google-token')
            self.assertNotIn('refresh_token',r.text);self.assertNotIn('server-only-secret',r.text)
            self.assertEqual(self.client.post('/devices/restore',json=proof).status_code,401)

    def test_wrong_private_key_and_account_mismatch_never_restore(self):
        identity=self.register()
        proof=self.proof(identity,ec.generate_private_key(ec.SECP256R1()))
        self.assertEqual(self.client.post('/devices/restore',json=proof).status_code,401)
        proof=self.proof(identity)
        def refresh(credentials,request):credentials.token='another-token'
        self.identity={**self.identity,'sub':'other-user'}
        with patch('google.oauth2.credentials.Credentials.refresh',refresh):self.assertEqual(self.client.post('/devices/restore',json=proof).status_code,401)

    def test_device_removal_does_not_delete_server_import_consent(self):
        identity=self.register()
        self.assertEqual(self.client.post('/devices/remove',json=self.proof(identity)).status_code,200)
        self.assertEqual(self.client.post('/devices/challenge',json={'id':identity}).status_code,401)
        self.assertEqual(api.store.setting('google:'+self.identity['sub'])['refresh_token'],'never-expose-refresh-token')

    def test_viewer_gets_readonly_consent_and_cannot_authenticate_as_import_owner(self):
        self.identity={'sub':'reader','email':'reader@example.test','email_verified':True}
        r=self.client.post('/devices/register',json={'public_key':self.jwk},headers={'Authorization':'Bearer reader-token'})
        self.assertEqual(r.status_code,200,r.text)
        from urllib.parse import parse_qs,urlsplit
        args=parse_qs(urlsplit(r.json()['url']).query)
        self.assertIn('drive.readonly',args['scope'][0]);self.assertNotIn('refresh_token',r.text)
        self.assertEqual(self.client.post('/auth/session',headers={'Authorization':'Bearer reader-token'}).status_code,403)

    def test_unsupported_keys_are_rejected_before_storage(self):
        for jwk in [{'kty':'RSA'},{**self.jwk,'crv':'P-384'},{**self.jwk,'x':'not-a-key'}]:
            r=self.client.post('/devices/register',json={'public_key':jwk},headers={'Authorization':'Bearer short-google-fixture'})
            self.assertEqual(r.status_code,422)

    def test_expired_device_requires_new_google_login(self):
        identity=self.register();value=api.store.setting('device:'+identity);value['expires']=0;api.store.setting('device:'+identity,value)
        self.assertEqual(self.client.post('/devices/challenge',json={'id':identity}).status_code,401)
