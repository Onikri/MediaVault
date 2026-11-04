"""Actual FastAPI/WebSocket/password/Range contracts; media bytes are fixtures."""
import base64,concurrent.futures,time,unittest
from fastapi import FastAPI,Header,HTTPException
from fastapi.testclient import TestClient
import watch_rooms as rooms
from online_sessions import Session,sessions

def next_type(socket,kind):
    for _ in range(15):
        value=socket.receive_json()
        if value['type']==kind:return value
    raise AssertionError('Missing '+kind)

class RoomTests(unittest.TestCase):
    def setUp(self):
        rooms.rooms.clear();rooms.attempts.clear()
        def owner(authorization:str=Header(default='')):
            if authorization!='Bearer owner':raise HTTPException(401)
            return 'owner'
        self.app=FastAPI();rooms.install(self.app,owner);self.client=TestClient(self.app);self.client.__enter__()
    def tearDown(self):self.client.__exit__(None,None,None);rooms.rooms.clear();rooms.attempts.clear()
    def create(self,media=None):
        response=self.client.post('/rooms',headers={'Authorization':'Bearer owner'},json={'title':'Fixture video','password':'room-secret','media':media or {'size':16}})
        self.assertEqual(response.status_code,201,response.text);return response.json()
    def join(self,identity,password='room-secret'):
        return self.client.post('/rooms/'+identity+'/join',json={'password':password,'name':'Друг'})
    def test_password_and_scoped_capability_do_not_grant_owner_access(self):
        self.assertEqual(self.client.post('/rooms',json={'title':'X','password':'secret','media':{'size':16}}).status_code,401)
        room=self.create();self.assertEqual(self.join(room['id'],'wrong').status_code,403)
        guest=self.join(room['id']).json();self.assertNotEqual(guest['token'],room['token'])
        self.assertNotIn('owner',guest);self.assertNotIn('password',guest);self.assertNotIn('salt',guest)
        self.assertEqual(self.client.get('/rooms/'+room['id']+'/media/invalid/file').status_code,403)
    def test_foreign_or_arbitrary_streams_are_rejected(self):
        response=self.client.post('/rooms',headers={'Authorization':'Bearer owner'},json={'title':'X','password':'secret','media':{'path':'https://127.0.0.1/private'}})
        self.assertEqual(response.status_code,422)
        token='s'*32;session=Session('other',{},time.monotonic()+60);resource=session.resource('https://cdn.example/movie.mp4');sessions[token]=session
        try:
            response=self.client.post('/rooms',headers={'Authorization':'Bearer owner'},json={'title':'X','password':'secret','media':{'path':'/online/'+token+'/'+resource}})
            self.assertEqual(response.status_code,403)
        finally:sessions.pop(token,None)
    def test_roles_and_wait_for_everyone_are_server_enforced(self):
        room=self.create();identity=room['id'];guest=self.join(identity).json()
        with self.client.websocket_connect('/rooms/'+identity+'/socket') as host:
            host.send_json({'token':room['token']});next_type(host,'state')
            host.send_json({'type':'state','position':12,'duration':100,'playing':True,'intent':True});next_type(host,'state')
            with self.client.websocket_connect('/rooms/'+identity+'/socket') as peer:
                peer.send_json({'token':guest['token']});state=next_type(peer,'state')['room'];self.assertTrue(state['held']);self.assertFalse(state['playing']);next_type(host,'state')
                peer.send_json({'type':'buffer','value':False});state=next_type(peer,'state')['room'];self.assertTrue(state['playing']);self.assertFalse(state['held']);next_type(host,'state')
                peer.send_json({'type':'command','action':'seek','position':50});self.assertEqual(next_type(peer,'error')['message'],'Управление доступно ведущему.')
                host.send_json({'type':'settings','everyone':True});next_type(host,'state');next_type(peer,'state')
                peer.send_json({'type':'command','action':'seek','position':50});self.assertAlmostEqual(next_type(host,'command')['position'],50,delta=.1);state=next_type(peer,'state')['room'];self.assertGreaterEqual(state['position'],50)
                host.send_json({'type':'close'});next_type(peer,'closed');next_type(host,'closed')
        self.assertEqual(self.client.get('/rooms/'+identity+'/media/'+guest['token']+'/file').status_code,410)
    def test_drive_chunk_is_bounded_range_data_and_never_a_library_key(self):
        room=self.create();identity=room['id'];guest=self.join(identity).json()
        with self.client.websocket_connect('/rooms/'+identity+'/socket') as host:
            host.send_json({'token':room['token']});next_type(host,'state')
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result=pool.submit(self.client.get,'/rooms/'+identity+'/media/'+guest['token']+'/file',headers={'Range':'bytes=4-9'})
                read=next_type(host,'read');self.assertEqual((read['start'],read['end']),(4,9));self.assertNotIn('url',read)
                host.send_json({'type':'data','id':read['id'],'data':base64.b64encode(b'456789').decode()});response=result.result(5)
                self.assertEqual(response.status_code,206);self.assertEqual(response.content,b'456789');self.assertEqual(response.headers['content-range'],'bytes 4-9/16')
                self.assertEqual(response.headers['cache-control'],'private, no-store')
            self.assertEqual(self.client.get('/rooms/'+identity+'/media/'+guest['token']+'/file',headers={'Range':'bytes=100-200'}).status_code,416)
    def test_range_suffix_and_multi_range_rejection(self):
        self.assertEqual(rooms.range_bounds('bytes=-4',16),(12,15));self.assertEqual(rooms.range_bounds('bytes=0-',5*1024**2),(0,rooms.MAX_CHUNK-1))
        with self.assertRaises(HTTPException):rooms.range_bounds('bytes=0-1,4-5',16)

    def test_selected_audio_and_captions_have_room_scoped_aliases(self):
        from fastapi.responses import Response
        token='t'*32;session=Session('owner',{},time.monotonic()+60)
        resource=session.resource('https://cdn.example/audio.m3u8');sessions[token]=session
        try:
            room=self.create({'size':16,'tracks':[{'kind':'audio','type':'hls','path':'/online/'+token+'/'+resource}],'audioOffset':1.5})
            guest=self.join(room['id']).json();track=guest['room']['tracks'][0]
            self.assertEqual(track['alias'],'track0');self.assertNotIn('path',track);self.assertNotIn('session',track)
            self.assertEqual(guest['room']['audioOffset'],1.5)
            self.app.state.online_stream=lambda *args:Response('#EXTM3U\n/online/'+token+'/'+resource,media_type='application/vnd.apple.mpegurl')
            with self.client.websocket_connect('/rooms/'+room['id']+'/socket') as host:
                host.send_json({'token':room['token']});next_type(host,'state')
                response=self.client.get('/rooms/'+room['id']+'/media/'+guest['token']+'/track0')
                self.assertEqual(response.status_code,200);self.assertNotIn(token,response.text)
                self.assertIn('/track0-'+resource,response.text)
                self.assertEqual(response.headers['cache-control'],'private, no-store')
        finally:sessions.pop(token,None)
