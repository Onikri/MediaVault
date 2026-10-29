"""Real signed device API and concurrent queue; source bytes are explicit fixtures."""
import base64,io,json,os,secrets,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from PIL import Image
import source_relay as module
from source_parser import SourceError
BOOK='https://ru.novelcool.com/novel/Наруто.html'
PIC='https://ruwebp.movietop.cc/comics/pic2/1/1.webp'

class RelayTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.keys=Path(self.directory.name)/'keys.json';self.key=Ed25519PrivateKey.generate();self.keys.write_text(json.dumps({'device':base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()}))
        self.relay=module.Relay(self.keys);self.patch=patch.object(module,'relay',self.relay);self.patch.start();app=FastAPI();module.install(app);self.client=TestClient(app)
    def tearDown(self):self.patch.stop();self.directory.cleanup()
    def signed(self,path,raw=None,meta='',nonce=None,timestamp=None):
        stamp=str(timestamp or int(time.time()));nonce=nonce or secrets.token_urlsafe(18);method='GET' if raw is None else 'POST'
        return {'X-Source-Device':'device','X-Source-Time':stamp,'X-Source-Nonce':nonce,'X-Source-Signature':base64.b64encode(self.key.sign(module.message(method,path,stamp,nonce,raw or b'',meta))).decode(),'X-Source-Meta':meta}
    def connect(self):
        from starlette.requests import Request
        path='/source-device/poll';headers=self.signed(path)
        self.relay.authenticate(Request({'type':'http','method':'GET','path':path,'headers':[(k.lower().encode(),v.encode()) for k,v in headers.items()]}))
    def test_scope_rejects_other_sites_api_credentials_private_hosts_and_arbitrary_cdn_paths(self):
        for url,kind in [('https://evil.example/novel/A.html','document'),('https://ru.novelcool.com/api/login','document'),('https://u:p@ru.novelcool.com/novel/A.html','document'),('https://127.0.0.1/comics/a.png','image'),('https://evil.movietop.cc/private','image'),('https://movietop.cc.evil.example/comics/a.png','image')]:
            with self.assertRaises(SourceError):module.allowed(url,kind)
        self.assertEqual(module.allowed(PIC,'image'),PIC)
    def test_unsigned_unknown_tampered_and_replayed_requests_are_rejected(self):
        path='/source-device/result/missing';raw=b'bytes';meta=base64.b64encode(json.dumps({'ok':True,'url':BOOK}).encode()).decode()
        self.assertEqual(self.client.post(path,content=raw).status_code,401)
        headers=self.signed(path,raw,meta);self.assertEqual(self.client.post(path,content=b'changed',headers=headers).status_code,401)
        headers=self.signed(path,raw,meta);self.assertEqual(self.client.post(path,content=raw,headers=headers).status_code,404)
        self.assertEqual(self.client.post(path,content=raw,headers=headers).status_code,401)
        self.assertEqual(self.client.post(path,content=raw,headers=self.signed(path,raw,meta,timestamp=int(time.time())-100)).status_code,401)
    def test_real_binary_transfer_does_not_base64_store_image_and_cleans_completed_jobs(self):
        self.connect();result=[];buffer=io.BytesIO();Image.new('RGB',(4,5),'white').save(buffer,'PNG');raw=buffer.getvalue()
        thread=threading.Thread(target=lambda:result.append(self.relay.fetch(PIC,'image',BOOK,timeout=3)));thread.start()
        path='/source-device/poll';task=self.client.get(path,headers=self.signed(path)).json()['task'];self.assertEqual(task['url'],PIC);self.assertEqual(task['referer'],BOOK)
        path='/source-device/result/'+task['id'];meta=base64.b64encode(json.dumps({'ok':True,'url':PIC}).encode()).decode()
        self.assertEqual(self.client.post(path,content=raw,headers=self.signed(path,raw,meta)).status_code,200)
        thread.join(2);self.assertFalse(thread.is_alive());self.assertEqual(result[0][0],raw);self.assertEqual(result[0][2]['Content-Type'],'image/png');self.assertEqual(self.relay.jobs,{})
    def test_expired_requests_do_not_leave_plaintext_jobs(self):
        self.connect()
        with self.assertRaisesRegex(SourceError,'не успело'):self.relay.fetch(BOOK,timeout=.01)
        self.assertEqual(self.relay.jobs,{})
    def test_large_html_is_uploaded_in_ordered_signed_chunks_below_proxy_limit(self):
        self.connect();result=[];raw=b'<html>'+b'x'*(module.CHUNK*2)+b'</html>'
        thread=threading.Thread(target=lambda:result.append(self.relay.fetch(BOOK,timeout=3)));thread.start();task=self.relay.poll('device',timeout=1)
        path='/source-device/result/'+task['id']
        for offset in range(0,len(raw),module.CHUNK):
            chunk=raw[offset:offset+module.CHUNK];meta=base64.b64encode(json.dumps({'ok':True,'url':BOOK,'offset':offset,'complete':offset+len(chunk)==len(raw)}).encode()).decode()
            self.assertEqual(self.client.post(path,content=chunk,headers=self.signed(path,chunk,meta)).status_code,200)
        thread.join(2);self.assertEqual(result[0][0],raw);self.assertEqual(self.relay.jobs,{})
    def test_remote_failure_wakes_waiter_without_exposing_device_error_details(self):
        self.connect();errors=[]
        def wait():
            try:self.relay.fetch(BOOK,timeout=3)
            except SourceError as error:errors.append(str(error))
        thread=threading.Thread(target=wait);thread.start();task=self.relay.poll('device',timeout=1);meta=base64.b64encode(json.dumps({'ok':False,'url':BOOK,'error':'private-cookie-secret'}).encode()).decode();self.relay.finish('device',task['id'],b'',meta);thread.join(2)
        self.assertEqual(len(errors),1);self.assertNotIn('secret',errors[0]);self.assertEqual(self.relay.jobs,{})
    def test_native_reader_uses_device_bytes_when_transport_is_live(self):
        from manga_novelcool import inspect
        class Http:
            def document(self,*a,**kw):raise AssertionError('Oracle response must not replace device bytes')
        with patch.object(self.relay,'available',return_value=True),patch.object(module,'document',return_value=('<h1 class="bookinfo-title">Наруто</h1>',BOOK,{})) as device:
            self.assertEqual(inspect(BOOK,Http())['title'],'Наруто');device.assert_called_once_with(BOOK,timeout=28)
    def test_existing_reader_capability_serves_device_image_without_direct_oracle_fetch(self):
        import online_sessions as online
        online.sessions.clear();app=FastAPI();online.install(app,lambda:'owner')
        token,session=online.create('owner',{'Referer':BOOK},'manga');resource=session.resource(PIC)
        with patch.object(self.relay,'available',return_value=True),patch.object(module,'image',return_value=(b'image fixture',PIC,{'Content-Type':'image/webp'})) as image,patch('online_sessions.PublicHttp._open') as direct:
            response=TestClient(app).get('/online/'+token+'/'+resource)
            self.assertEqual(response.status_code,200);self.assertEqual(response.content,b'image fixture');image.assert_called_once_with(PIC,BOOK);direct.assert_not_called()
        online.sessions.clear()
    def test_device_html_uses_remaining_chapter_budget(self):
        from manga_novelcool import inspect
        from types import SimpleNamespace
        with patch.object(self.relay,'available',return_value=True),patch.object(module,'document') as device:
            with self.assertRaises(SourceError):inspect(BOOK,SimpleNamespace(deadline=time.monotonic()-1))
            device.assert_not_called()

class WorkerTests(unittest.TestCase):
    def test_worker_revalidates_destination_before_network_and_keeps_key_on_device(self):
        from source_relay_worker import load_key,retrieve
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'key';first=load_key(path);second=load_key(path)
            self.assertEqual(first.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw),second.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw))
        with patch('source_relay_worker.PublicHttp') as http:
            with self.assertRaises(SourceError):retrieve({'url':'https://127.0.0.1/novel/A.html','kind':'document'})
            http.assert_not_called()
