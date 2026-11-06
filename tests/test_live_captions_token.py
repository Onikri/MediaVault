import unittest
from unittest.mock import patch,AsyncMock,MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
import google_pool


class LiveToken(unittest.TestCase):
    def client(self,rows):
        app=FastAPI();google_pool.install(app,lambda:'owner',lambda:None)
        patcher=patch('google_pool.saved',return_value=rows);patcher.start();self.addCleanup(patcher.stop)
        return TestClient(app)

    def test_needs_a_key_and_never_returns_it(self):
        self.assertEqual(self.client([]).post('/reader/google/live-token',json={}).status_code,422)
        reply=MagicMock(status_code=200);reply.json.return_value={'name':'auth_tokens/abc'}
        session=MagicMock();session.post=AsyncMock(return_value=reply)
        context=MagicMock();context.__aenter__=AsyncMock(return_value=session);context.__aexit__=AsyncMock(return_value=False)
        with patch('google_pool.httpx.AsyncClient',return_value=context):
            response=self.client([{'slot':0,'key':'server-secret-key-123456789'}]).post('/reader/google/live-token',json={})
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['token'],'auth_tokens/abc')
        self.assertNotIn('server-secret-key',response.text)
        body=session.post.call_args.kwargs['json'];self.assertEqual(body['uses'],1)
        self.assertEqual(session.post.call_args.kwargs['headers']['x-goog-api-key'],'server-secret-key-123456789')

if __name__=='__main__':unittest.main()
