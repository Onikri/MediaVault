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
    def test_lobby_preview_shows_title_but_never_tokens(self):
        room=self.create();self.join(room['id'])
        data=self.client.get('/rooms/'+room['id']+'/preview').json()
        self.assertEqual(data['title'],'Fixture video');self.assertNotIn(room['token'],str(data));self.assertNotIn('memberId',data)
        self.assertEqual(self.client.get('/rooms/missing/preview').status_code,410)
    def test_guest_photo_is_validated_and_served_from_its_own_url(self):
        room=self.create();webp=b'RIFF'+(20).to_bytes(4,'little')+b'WEBPVP8 '+bytes(12)
        bad=self.client.post('/rooms/'+room['id']+'/join',json={'password':'room-secret','name':'Аня','avatar':'data:image/svg+xml;base64,PHN2Zz4='})
        self.assertEqual(bad.status_code,422)
        fake=self.client.post('/rooms/'+room['id']+'/join',json={'password':'room-secret','name':'Аня','avatar':'data:image/webp;base64,'+base64.b64encode(b'<svg onload=x>').decode()})
        self.assertEqual(fake.status_code,422)
        big=self.client.post('/rooms/'+room['id']+'/join',json={'password':'room-secret','name':'Аня','avatar':'data:image/jpeg;base64,'+base64.b64encode(bytes.fromhex('ffd8ff')+bytes(33*1024)).decode()})
        self.assertIn(big.status_code,(413,422))
        joined=self.client.post('/rooms/'+room['id']+'/join',json={'password':'room-secret','name':'Аня','avatar':'data:image/webp;base64,'+base64.b64encode(webp).decode()})
        self.assertEqual(joined.status_code,200,joined.text)
        member=next(m for m in joined.json()['room']['members'] if m['id']==joined.json()['memberId'])
        self.assertTrue(member['avatar'].startswith('/rooms/'+room['id']+'/avatar/'));self.assertNotIn(joined.json()['token'],member['avatar'])
        image=self.client.get(member['avatar'])
        self.assertEqual(image.status_code,200);self.assertEqual(image.content,webp);self.assertEqual(image.headers['content-type'],'image/webp');self.assertEqual(image.headers['x-content-type-options'],'nosniff')
        self.assertEqual(self.client.get('/rooms/'+room['id']+'/avatar/guess').status_code,404)
        plain=self.join(room['id']).json();self.assertEqual(next(m for m in plain['room']['members'] if m['id']==plain['memberId'])['avatar'],'')
    def test_ice_requires_membership_and_signs_short_lived_turn_credentials(self):
        import hashlib,hmac,os
        from unittest.mock import patch
        room=self.create();guest=self.join(room['id']).json()
        self.assertEqual(self.client.post('/rooms/'+room['id']+'/ice',json={'token':'x'*32}).status_code,403)
        plain=self.client.post('/rooms/'+room['id']+'/ice',json={'token':guest['token']}).json()
        self.assertFalse(plain['relay']);self.assertTrue(all('credential' not in s for s in plain['iceServers']))
        with patch.dict(os.environ,{'MEDIA_VAULT_TURN_SECRET':'s3cret','MEDIA_VAULT_TURN_HOST':'turn.example.com'}):
            data=self.client.post('/rooms/'+room['id']+'/ice',json={'token':guest['token']}).json()
        turn=next(s for s in data['iceServers'] if 'credential' in s);expiry,member=turn['username'].split(':')
        self.assertEqual(member,guest['memberId']);self.assertGreater(int(expiry),time.time()+3600)
        self.assertEqual(turn['credential'],base64.b64encode(hmac.new(b's3cret',turn['username'].encode(),hashlib.sha1).digest()).decode())
        self.assertNotIn('s3cret',str(data))
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


class ConversationTests(RoomTests):
    def test_chat_and_voice_signals_stay_inside_authenticated_room(self):
        room=self.create();guest=self.join(room['id']).json();path='/rooms/'+room['id']+'/socket'
        with self.client.websocket_connect(path) as host:
            host.send_json({'token':room['token']});next_type(host,'state')
            with self.client.websocket_connect(path) as peer:
                peer.send_json({'token':guest['token']});next_type(peer,'state');next_type(host,'state')
                host.send_json({'type':'chat','text':'Привет'})
                self.assertEqual(next_type(peer,'chat')['text'],'Привет');next_type(host,'chat')
                host.send_json({'type':'voice','enabled':True});next_type(host,'state');next_type(peer,'state')
                peer.send_json({'type':'voice','enabled':True});next_type(host,'state');next_type(peer,'state')
                host.send_json({'type':'signal','to':guest['memberId'],'payload':{'description':{'type':'offer','sdp':'fixture'}}})
                message=next_type(peer,'signal');self.assertEqual(message['from'],room['memberId']);self.assertNotIn('token',message)
                peer.send_json({'type':'voice','enabled':False});next_type(host,'state');next_type(peer,'state')
                host.send_json({'type':'signal','to':guest['memberId'],'payload':{'description':{'type':'offer','sdp':'not delivered'}}})
                peer.send_json({'type':'ping'});self.assertEqual(peer.receive_json()['type'],'pong')

class ChatTests(RoomTests):
    def test_history_replies_reactions_deletion_typing_and_gifs(self):
        room=self.create();guest=self.join(room['id']).json();path='/rooms/'+room['id']+'/socket'
        gif={'url':'https://media2.giphy.com/media/abc123/200w.webp?cid=x1&rid=200w.webp&ct=g','width':200,'height':150,'title':'wave'}
        with self.client.websocket_connect(path) as host:
            host.send_json({'token':room['token']});next_type(host,'state');self.assertEqual(next_type(host,'history')['messages'],[])
            host.send_json({'type':'chat','text':'Начинаем'});first=next_type(host,'chat')
            self.assertEqual(first['reactions'],{});self.assertIsNone(first['reply']);self.assertIsNone(first['gif'])
            time.sleep(.55);host.send_json({'type':'chat','text':'','gif':{**gif,'url':'https://evil.example/x.gif'}})
            time.sleep(.55);host.send_json({'type':'chat','text':'','gif':gif});second=next_type(host,'chat')
            self.assertEqual(second['gif']['url'],gif['url']);self.assertEqual(second['text'],'')
            with self.client.websocket_connect(path) as peer:
                peer.send_json({'token':guest['token']});next_type(peer,'state')
                history=next_type(peer,'history')['messages'];self.assertEqual([m['id'] for m in history],[first['id'],second['id']])
                peer.send_json({'type':'chat','text':'Да!','reply':first['id']});answer=next_type(peer,'chat')
                self.assertEqual(answer['reply'],{'id':first['id'],'name':'Ведущий','text':'Начинаем'})
                peer.send_json({'type':'react','id':first['id'],'emoji':'🔥'})
                self.assertEqual(next_type(host,'reaction')['reactions'],{'🔥':[guest['memberId']]})
                peer.send_json({'type':'react','id':first['id'],'emoji':'<b>'})
                peer.send_json({'type':'react','id':first['id'],'emoji':'🔥'})
                self.assertEqual(next_type(host,'reaction')['reactions'],{})
                peer.send_json({'type':'typing'});typing=next_type(host,'typing');self.assertEqual(typing['from'],guest['memberId']);self.assertNotIn('token',typing)
                peer.send_json({'type':'delete','id':first['id']})
                peer.send_json({'type':'delete','id':answer['id']});self.assertEqual(next_type(host,'deleted')['id'],answer['id']);self.assertEqual(next_type(peer,'deleted')['id'],answer['id'])
                host.send_json({'type':'delete','id':second['id']});self.assertEqual(next_type(peer,'deleted')['id'],second['id'])
                self.assertEqual([m['id'] for m in rooms.rooms[room['id']].messages],[first['id']])

    def test_gif_search_requires_membership_and_server_key(self):
        room=self.create();guest=self.join(room['id']).json();url='/rooms/'+room['id']+'/gifs'
        self.assertEqual(self.client.post(url,json={'token':'nope','q':'cat'}).status_code,403)
        import os
        os.environ.pop('GIPHY_API_KEY',None)
        self.assertEqual(self.client.post(url,json={'token':guest['token'],'q':'cat'}).status_code,503)
        class Fake:
            def raise_for_status(self):pass
            def json(self):return {'data':[
                {'id':'g1','title':'cat','images':{'fixed_width':{'webp':'https://media1.giphy.com/media/g1/200w.webp','width':'200','height':'120'},'fixed_width_downsampled':{'webp':'https://media1.giphy.com/media/g1/200w_d.webp'}}},
                {'id':'g2','title':'bad','images':{'fixed_width':{'webp':'https://evil.example/a.webp','width':'200','height':'120'}}}]}
        calls=[]
        import requests
        original=requests.get;requests.get=lambda *a,**k:(calls.append((a,k)),Fake())[1]
        os.environ['GIPHY_API_KEY']='fixture-key';rooms.GIF_CACHE.clear()
        try:
            time.sleep(.4);data=self.client.post(url,json={'token':guest['token'],'q':'кот'}).json()
            self.assertEqual([r['id'] for r in data['results']],['g1']);self.assertNotIn('fixture-key',str(data))
            self.assertTrue(calls[0][0][0].endswith('/search'));self.assertEqual(calls[0][1]['params']['q'],'кот')
        finally:requests.get=original;os.environ.pop('GIPHY_API_KEY',None)
