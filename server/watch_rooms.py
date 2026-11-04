"""Password rooms with scoped read-only media and server-authoritative playback.

Online media delegates only to a creator-owned video session. Drive/local media
is range-relayed by the host browser: keys, Drive tokens and files never leave
that browser. Relay chunks live only in bounded RAM, never on disk.
"""
import asyncio,base64,hashlib,hmac,math,os,re,secrets,time
from dataclasses import dataclass,field
from fastapi import Depends,HTTPException,Request,WebSocket,WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field
from starlette.concurrency import run_in_threadpool

MAX_CHUNK=1024*1024
rooms={};attempts={}

class Track(BaseModel):
    model_config=ConfigDict(extra='forbid')
    path:str=Field(max_length=300)
    kind:str=Field(pattern='^(audio|caption)$')
    type:str=Field(default='mp4',pattern='^(mp4|hls|webm|vtt)$')
    name:str=Field(default='',max_length=100)
    language:str=Field(default='ru',max_length=12)

class Media(BaseModel):
    model_config=ConfigDict(extra='forbid')
    path:str=Field(default='',max_length=300)
    tracks:list[Track]=Field(default_factory=list,max_length=6)
    audioOffset:float=Field(default=0,ge=-30,le=30)
    size:int=Field(default=0,ge=0,le=50*1024**3)
    mime:str=Field(default='video/mp4',pattern=r'^video/(mp4|webm|ogg)$')
    type:str=Field(default='mp4',pattern='^(mp4|hls|webm)$')
class Create(BaseModel):
    model_config=ConfigDict(extra='forbid')
    password:str=Field(min_length=6,max_length=128)
    title:str=Field(min_length=1,max_length=300)
    malId:str=Field(default='',pattern=r'^\d{0,10}$')
    media:Media
class Join(BaseModel):
    model_config=ConfigDict(extra='forbid')
    password:str=Field(min_length=1,max_length=128)
    name:str=Field(default='Гость',min_length=1,max_length=40)

@dataclass
class Member:
    id:str;token:str;name:str;host:bool=False
    ws:object=None
    seen:float=field(default_factory=time.monotonic)
    buffering:bool=False
    voice:bool=False
    last_chat:float=0
    slots:object=field(default_factory=lambda:asyncio.Semaphore(2))
@dataclass
class Room:
    id:str;owner:str;salt:bytes;digest:bytes;title:str;mal_id:str;media:dict
    expires:float=field(default_factory=lambda:time.monotonic()+6*3600)
    members:dict=field(default_factory=dict)
    position:float=0;duration:float=0;rate:float=1
    playing:bool=False;wanted:bool=False;held:bool=False
    updated:float=field(default_factory=time.monotonic)
    leader:str='';everyone:bool=False;wait_all:bool=True;epoch:int=0;revision:int=0
    pending:dict=field(default_factory=dict)
    closed:bool=False

def lookup(identity):
    room=rooms.get(identity)
    if not room or room.closed or room.expires<time.monotonic():raise HTTPException(410,'Комната закрыта или срок ссылки истёк.')
    return room
def membership(room,token):
    member=next((m for m in room.members.values() if secrets.compare_digest(m.token,token)),None)
    if not member or member.seen<time.monotonic()-90:raise HTTPException(403,'Войди в комнату по паролю.')
    return member
def validated_media(media,owner):
    value=media.model_dump()
    if media.path:
        from online_sessions import sessions,lock,expire
        match=re.fullmatch(r'/online/([A-Za-z0-9_-]{20,80})/([A-Za-z0-9_-]{10,40})',media.path)
        if not match:raise HTTPException(422,'Комната принимает только текущий видеопоток.')
        with lock:
            expire();session=sessions.get(match[1])
            if not session or session.owner!=owner or session.kind!='video' or match[2] not in session.resources:raise HTTPException(403,'Поток не принадлежит создателю комнаты.')
        value.update(session=match[1],resource=match[2])
    for index,track in enumerate(media.tracks):
        proof=validated_media(Media(path=track.path),owner)
        value['tracks'][index].update(session=proof['session'],resource=proof['resource'],alias='track'+str(index))
    if not media.path and not media.size:raise HTTPException(422,'Неизвестен размер файла для совместного просмотра.')
    return value
def position(room):return min(room.duration or 1e9,room.position+(time.monotonic()-room.updated)*room.rate if room.playing else room.position)
def snapshot(room):
    return {'id':room.id,'title':room.title,'malId':room.mal_id,'position':position(room),'duration':room.duration,'rate':room.rate,'playing':room.playing,'held':room.held,'epoch':room.epoch,'revision':room.revision,
            'leader':room.leader,'everyone':room.everyone,'waitAll':room.wait_all,'type':room.media['type'],'resource':room.media.get('resource','file'),
            'tracks':[{k:v for k,v in t.items() if k in {'kind','type','name','language','alias'}} for t in room.media.get('tracks',[])],'audioOffset':room.media.get('audioOffset',0),
            'members':[{'id':m.id,'name':m.name,'host':m.host,'online':m.ws is not None,'buffering':m.buffering,'voice':m.voice} for m in room.members.values()]}
async def send(member,value):
    if member.ws is not None:
        try:await asyncio.wait_for(member.ws.send_json(value),timeout=5)
        except Exception:member.ws=None
async def broadcast(room):
    room.revision+=1
    await asyncio.gather(*(send(m,{'type':'state','room':snapshot(room)}) for m in list(room.members.values())))
def recompute(room):
    held=room.wait_all and any(m.buffering for m in room.members.values() if m.ws is not None)
    room.position=position(room);room.updated=time.monotonic();room.held=held;room.playing=room.wanted and not held
def controls(room,member):return member.host or room.everyone or room.leader==member.id
def number(value,minimum=0,maximum=1e9):
    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):raise ValueError()
    return min(maximum,max(minimum,float(value)))
def range_bounds(header,size):
    if not header:return 0,min(size,MAX_CHUNK)-1
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',header)
    if not match or not any(match.groups()):raise HTTPException(416)
    a,b=match.groups()
    if not a:start=max(0,size-int(b));end=size-1
    else:start=int(a);end=min(size-1,int(b)) if b else size-1
    if start>=size or end<start:raise HTTPException(416,headers={'Content-Range':'bytes */'+str(size)})
    return start,min(end,start+MAX_CHUNK-1)

def install(app,owner):
    @app.post('/rooms',status_code=201)
    async def create(body:Create,subject=Depends(owner)):
        for identity,r in list(rooms.items()):
            if r.closed or r.expires<time.monotonic() or r.owner==subject and all(m.ws is None and m.seen<time.monotonic()-60 for m in r.members.values() if m.host):rooms.pop(identity,None)
        if len(rooms)>=16 or sum(r.owner==subject for r in rooms.values())>=2:raise HTTPException(429,'Закрой предыдущую комнату.')
        media=validated_media(body.media,subject);salt=secrets.token_bytes(16)
        digest=await run_in_threadpool(hashlib.scrypt,body.password.encode(),salt=salt,n=16384,r=8,p=1)
        if len(rooms)>=16 or sum(r.owner==subject for r in rooms.values())>=2:raise HTTPException(429,'Закрой предыдущую комнату.')
        room=Room(secrets.token_urlsafe(20),subject,salt,digest,body.title,body.malId,media)
        host=Member(secrets.token_urlsafe(8),secrets.token_urlsafe(32),'Ведущий',True);room.members[host.id]=host;room.leader=host.id;rooms[room.id]=room
        return {'id':room.id,'token':host.token,'memberId':host.id,'room':snapshot(room)}

    @app.post('/rooms/{identity}/join')
    async def join(identity:str,body:Join,request:Request):
        key=(request.client.host if request.client else '',identity);now=time.monotonic()
        attempts[key]=[v for v in attempts.get(key,[]) if v>now-60]
        if len(attempts[key])>=8:raise HTTPException(429,'Слишком много попыток. Подожди минуту.')
        attempts[key].append(now)
        if len(attempts)>1000:
            for k in list(attempts):
                if not attempts[k] or attempts[k][-1]<now-60:attempts.pop(k,None)
        room=lookup(identity)
        digest=await run_in_threadpool(hashlib.scrypt,body.password.encode(),salt=room.salt,n=16384,r=8,p=1)
        if not hmac.compare_digest(digest,room.digest):raise HTTPException(403,'Неверный пароль комнаты.')
        lookup(identity)
        for mid,m in list(room.members.items()):
            if not m.host and m.ws is None and m.seen<now-60:room.members.pop(mid,None)
        if len(room.members)>=9:raise HTTPException(429,'В комнате уже восемь гостей.')
        m=Member(secrets.token_urlsafe(8),secrets.token_urlsafe(32),body.name.strip() or 'Гость',buffering=True);room.members[m.id]=m
        return {'id':room.id,'token':m.token,'memberId':m.id,'room':snapshot(room)}

    @app.websocket('/rooms/{identity}/socket')
    async def socket(ws:WebSocket,identity:str):
        origin=ws.headers.get('origin')
        if origin and origin.rstrip('/')!=os.getenv('ALLOWED_ORIGIN','https://onikri.github.io').rstrip('/'):
            await ws.close(code=1008);return
        await ws.accept();member=None;room=None
        try:
            hello=await asyncio.wait_for(ws.receive_json(),timeout=10);room=lookup(identity);member=membership(room,str(hello.get('token','')))
            if member.ws:await member.ws.close(code=1000)
            member.ws=ws;member.seen=time.monotonic();recompute(room);await broadcast(room)
            events=[]
            while not room.closed:
                raw=await asyncio.wait_for(ws.receive_text(),timeout=45)
                if len(raw)>MAX_CHUNK*4//3+4096:raise ValueError()
                if not member.host and len(raw)>12288:raise ValueError()
                data=__import__('json').loads(raw);kind=data.get('type');member.seen=time.monotonic()
                now=time.monotonic();events=[t for t in events if t>now-1];events.append(now)
                if len(events)>60:raise ValueError()
                if kind=='ping':await send(member,{'type':'pong'});continue
                if kind=='chat':
                    text=data.get('text')
                    if not isinstance(text,str) or not text.strip() or len(text)>500:continue
                    if now-member.last_chat<.5:continue
                    member.last_chat=now
                    message={'type':'chat','id':secrets.token_urlsafe(10),'from':member.id,'name':member.name,'text':text.strip(),'at':time.time()}
                    await asyncio.gather(*(send(m,message) for m in room.members.values()))
                    continue
                if kind=='voice':
                    member.voice=data.get('enabled') is True
                    await broadcast(room);continue
                if kind=='signal':
                    target=room.members.get(data.get('to')) if isinstance(data.get('to'),str) else None
                    payload=data.get('payload')
                    if not member.voice or not target or target is member or not target.voice or not isinstance(payload,dict) or len(raw)>12288:continue
                    description=payload.get('description');candidate=payload.get('candidate')
                    if description is not None:
                        if not isinstance(description,dict) or description.get('type') not in {'offer','answer'} or not isinstance(description.get('sdp'),str) or len(description['sdp'])>10000:continue
                        safe={'description':{'type':description['type'],'sdp':description['sdp']}}
                    elif candidate is not None:
                        if not isinstance(candidate,dict) or not isinstance(candidate.get('candidate'),str) or len(candidate['candidate'])>2000:continue
                        safe={'candidate':{k:v for k,v in candidate.items() if k in {'candidate','sdpMid','sdpMLineIndex','usernameFragment'}}}
                    else:continue
                    await send(target,{'type':'signal','from':member.id,'payload':safe});continue

                if kind=='data' and member.host:
                    pending=room.pending.get(data.get('id'))
                    if pending and not pending['future'].done():
                        if data.get('error'):pending['future'].set_exception(ValueError('Host media unavailable'))
                        else:
                            chunk=base64.b64decode(data.get('data',''),validate=True)
                            if len(chunk)!=pending['length'] or len(chunk)>MAX_CHUNK:raise ValueError()
                            pending['future'].set_result(chunk)
                    continue
                if kind=='close' and member.host:
                    room.closed=True
                    for pending in room.pending.values():
                        if not pending['future'].done():pending['future'].set_exception(ValueError('Room closed'))
                    await asyncio.gather(*(send(m,{'type':'closed'}) for m in room.members.values()));break
                if kind=='settings' and member.host:
                    leader=data.get('leader',room.leader)
                    if leader not in room.members:raise ValueError()
                    room.leader=leader;room.everyone=bool(data.get('everyone',room.everyone));room.wait_all=bool(data.get('waitAll',room.wait_all));recompute(room)
                elif kind=='buffer':member.buffering=bool(data.get('value'));recompute(room)
                elif kind=='state' and member.host:
                    room.position=number(data.get('position',room.position));room.duration=number(data.get('duration',room.duration),maximum=7*86400);room.rate=number(data.get('rate',1),.25,3)
                    if data.get('intent') or not room.held:room.wanted=bool(data.get('playing'))
                    room.updated=now;recompute(room)
                elif kind=='media' and member.host:
                    room.media=validated_media(Media.model_validate(data['media']),room.owner);room.epoch+=1;room.title=str(data.get('title',room.title))[:300]
                    for pending in room.pending.values():
                        if not pending['future'].done():pending['future'].set_exception(ValueError('Media changed'))
                    room.pending.clear()
                elif kind=='command':
                    if not controls(room,member):await send(member,{'type':'error','message':'Управление доступно ведущему.'});continue
                    action=data.get('action')
                    if action=='seek':room.position=number(data.get('position'));room.updated=now
                    elif action=='play':room.wanted=True
                    elif action=='pause':room.wanted=False
                    else:continue
                    recompute(room)
                    await asyncio.gather(*(send(m,{'type':'command','action':action,'position':room.position}) for m in room.members.values() if m.host))
                else:continue
                await broadcast(room)
        except (WebSocketDisconnect,asyncio.TimeoutError,ValueError,HTTPException,KeyError):pass
        finally:
            if member and member.ws is ws:
                member.ws=None;member.buffering=False;member.voice=False
                if room:
                    if member.host:room.wanted=False
                    recompute(room);await broadcast(room)
            try:await ws.close()
            except Exception:pass

    @app.api_route('/rooms/{identity}/media/{token}/{resource}',methods=['GET','HEAD'])
    async def media(identity:str,token:str,resource:str,request:Request):
        room=lookup(identity);member=membership(room,token)
        if 'epoch' in request.query_params and request.query_params['epoch']!=str(room.epoch):raise HTTPException(410,'Видео комнаты изменилось.')
        host=next((m for m in room.members.values() if m.host),None)
        if not host or not host.ws or host.seen<time.monotonic()-45:raise HTTPException(410,'Ведущий отключён.')
        headers={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'}
        track=next((t for t in room.media.get('tracks',[]) if resource==t['alias'] or resource.startswith(t['alias']+'-')),None)
        selected=track or room.media
        if track:resource=resource[len(track['alias'])+1:] if resource.startswith(track['alias']+'-') else track['resource']
        if selected.get('session'):
            from online_sessions import sessions
            session=sessions.get(selected['session'])
            if not session or session.owner!=room.owner or resource not in session.resources:raise HTTPException(410,'Поток комнаты изменился.')
            if request.method=='HEAD':return Response(headers=headers)
            response=await run_in_threadpool(app.state.online_stream,selected['session'],resource,request.headers.get('range',''))
            response.headers.update(headers)
            if 'mpegurl' in response.headers.get('content-type',''):
                text=response.body.decode();prefix='/online/'+selected['session']+'/'
                text=text.replace(prefix,f'/rooms/{identity}/media/{token}/'+(track['alias']+'-' if track else ''))
                return Response(text,media_type='application/vnd.apple.mpegurl',headers=headers)
            if hasattr(response,'body_iterator'):
                original=response.body_iterator
                async def guarded():
                    try:
                        async for chunk in original:
                            if room.closed or room.expires<time.monotonic() or member.seen<time.monotonic()-90:break
                            yield chunk
                    finally:
                        if hasattr(original,'aclose'):await original.aclose()
                response.body_iterator=guarded()
            return response
        if resource!='file':raise HTTPException(404)
        size=room.media['size'];headers.update({'Accept-Ranges':'bytes','Content-Type':room.media['mime']})
        if request.method=='HEAD':return Response(headers={**headers,'Content-Length':str(size)})
        start,end=range_bounds(request.headers.get('range',''),size)
        async with member.slots:
            if len(room.pending)>=18:raise HTTPException(429)
            identity_read=secrets.token_urlsafe(12);future=asyncio.get_running_loop().create_future()
            room.pending[identity_read]={'future':future,'length':end-start+1}
            try:
                await send(host,{'type':'read','id':identity_read,'start':start,'end':end,'epoch':room.epoch})
                chunk=await asyncio.wait_for(future,timeout=25)
                return Response(chunk,status_code=206,headers={**headers,'Content-Length':str(len(chunk)),'Content-Range':f'bytes {start}-{end}/{size}'})
            except (asyncio.TimeoutError,ValueError):raise HTTPException(504,'Ведущий не успел передать часть видео.') from None
            finally:room.pending.pop(identity_read,None)
