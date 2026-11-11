"""Title capability boundaries. External sources and Google are mocked."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server'))
from task_store import TaskStore
from title_shares import Create, install
from online_sessions import Prepare
from starlette.requests import Request


class TitleSharesTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store=TaskStore(temp.name)
        self.addCleanup(self.store.database.close)
        app=FastAPI()
        self.shares=install(app,lambda:'owner',lambda:self.store,json.dumps,json.loads)
        self.client=TestClient(app)
        self.body={'title':{'name':'Example','ids':{'mal':1}},'kind':'manga',
                   'entries':[{'number':1,'url':'https://reader.example/chapter/1'},
                              {'number':2,'url':'https://reader.example/chapter/2'}],
                   'initial':1,'translate':True,'translation':{'directModel':'gemini-3.5-flash-lite','key':'private'}}

    def test_shared_link_opens_selected_translation_and_is_revocable(self):
        created=self.client.post('/shares/title',json=self.body)
        self.assertEqual(created.status_code,201,created.text)
        link=created.json()
        opened=self.client.get('/shares/title/'+link['token']).json()
        self.assertEqual(opened['initial'],1)
        self.assertTrue(opened['translate'])
        self.assertNotIn('private',json.dumps(opened))
        self.assertNotIn('owner',opened)
        self.assertEqual(opened['translation'],{'directModel':'gemini-3.5-flash-lite'})
        subject='share:'+link['id']
        allowed=Prepare(url=self.body['entries'][1]['url'],kind='manga')
        self.shares.authorize_source(subject,allowed)
        with self.assertRaises(HTTPException) as caught:
            self.shares.authorize_source(subject,Prepare(url='https://reader.example/chapter/3',kind='manga'))
        self.assertEqual(caught.exception.status_code,403)
        self.assertEqual(self.client.delete('/shares/title/'+link['id']).status_code,200)
        self.assertEqual(self.client.get('/shares/title/'+link['token']).status_code,410)
        with self.assertRaises(HTTPException):
            self.shares.authorize_source(subject,allowed)

    def test_shared_session_cannot_be_used_for_downloads_settings_or_other_sources(self):
        row=self.client.post('/shares/title',json=self.body).json()
        token=self.client.get('/shares/title/'+row['token']).json()['token']
        def request(path,method='GET'):
            return Request({'type':'http','path':path,'method':method,'headers':[]})
        for path,method in [('/online/prepare','POST'),('/reader/google/keys','GET'),('/reader/google/generate','POST')]:
            self.assertEqual(self.shares.subject(token,request(path,method)),'share:'+row['id'])
        for path,method in [('/jobs','POST'),('/reader/google/keys','POST'),('/online/exports','POST'),
                            ('/sources/search','GET'),('/online/example/video/download','GET')]:
            with self.assertRaises(HTTPException) as caught:self.shares.subject(token,request(path,method))
            self.assertEqual(caught.exception.status_code,403)

    def test_invalid_urls_and_empty_selection_are_rejected(self):
        for changed in [{'entries':[]},{'initial':4},{'entries':[{'number':1,'url':'http://localhost/private'}]}]:
            response=self.client.post('/shares/title',json={**self.body,**changed})
            self.assertIn(response.status_code,(400,422))
