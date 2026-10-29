"""Signed outbound device transport for the same public NovelCool reader.

Only fixed reader/image hosts are allowed. No account headers, cookies, private
addresses, arbitrary proxy destinations, or persistent manga bytes are accepted.
"""
import base64,hashlib,json,os,re,secrets,threading,time
from pathlib import Path
from urllib.parse import urlsplit
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
from source_parser import SourceError,public_url

class DeviceError(SourceError):
    def __init__(self,status,detail):self.status=status;self.detail=detail;super().__init__(detail)

MAXIMUM=12*1024*1024
CHUNK=256*1024
def allowed(url,kind='document',resolve_dns=False):
    value=public_url(url,resolve_dns=resolve_dns);p=urlsplit(value)
    if kind=='document':
        good=p.hostname=='ru.novelcool.com' and bool(re.fullmatch(r'/(?:novel/[^/]+\.html|chapter/[^/]+/\d+(?:-\d+(?:-\d+)?)?(?:\.html|/))',p.path))
    else:
        good=kind=='image' and p.hostname.endswith('.movietop.cc') and p.path.startswith('/comics/')
    if not good:raise SourceError('Этот адрес не входит в транспорт читалки.')
    return value

def message(method,path,timestamp,nonce,body=b'',meta=''):
    return '\n'.join([method,path,timestamp,nonce,hashlib.sha256(body).hexdigest(),meta]).encode()

class Relay:
    def __init__(self,keyfile,clock=time.time):
        self.keyfile=Path(keyfile);self.clock=clock;self.condition=threading.Condition();self.jobs={};self.nonces={};self.seen={}
    def authenticate(self,request,body=b''):
        try:
            identity=request.headers['x-source-device'];timestamp=request.headers['x-source-time'];nonce=request.headers['x-source-nonce'];signature=request.headers['x-source-signature'];meta=request.headers.get('x-source-meta','')
            if not re.fullmatch(r'[a-z0-9-]{1,64}',identity) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',nonce) or abs(self.clock()-int(timestamp))>60:raise ValueError()
            keys=json.loads(self.keyfile.read_text());key=Ed25519PublicKey.from_public_bytes(base64.b64decode(keys[identity],validate=True))
            key.verify(base64.b64decode(signature,validate=True),message(request.method,request.url.path,timestamp,nonce,body,meta))
        except (OSError,KeyError,ValueError,TypeError,InvalidSignature):raise DeviceError(401,'Device signature required.') from None
        with self.condition:
            now=self.clock();self.nonces={k:v for k,v in self.nonces.items() if v>now}
            if (identity,nonce) in self.nonces:raise DeviceError(401,'Signature already used.')
            if len(self.nonces)>4096:raise DeviceError(429,'Device request limit.')
            self.nonces[identity,nonce]=now+120;self.seen[identity]=now
        return identity
    def available(self):
        with self.condition:return any(self.clock()-stamp<35 for stamp in self.seen.values())
    def fetch(self,url,kind='document',referer='',timeout=28):
        url=allowed(url,kind)
        if referer:referer=allowed(referer,'document')
        with self.condition:
            if not self.available():raise SourceError('Транспорт чтения на устройстве не подключён.')
            if len(self.jobs)>=12:raise SourceError('Загрузка страниц занята. Повтори запрос.')
            identity=secrets.token_urlsafe(24);job={'id':identity,'url':url,'kind':kind,'referer':referer,'device':None,'result':None,'error':None,'upload':bytearray(),'expires':self.clock()+timeout};self.jobs[identity]=job;self.condition.notify_all()
            end=time.monotonic()+timeout
            try:
                while job['result'] is None and job['error'] is None:
                    remaining=end-time.monotonic()
                    if remaining<=0:raise SourceError('Устройство не успело получить страницу источника.')
                    self.condition.wait(remaining)
                if job['error']:raise SourceError(job['error'])
                return job['result']
            finally:self.jobs.pop(identity,None)
    def poll(self,device,timeout=15):
        with self.condition:
            end=time.monotonic()+timeout
            while True:
                for job in self.jobs.values():
                    if job['device'] is None:
                        job['device']=device
                        return {k:job[k] for k in ['id','url','kind','referer']}
                remaining=end-time.monotonic()
                if remaining<=0:return None
                self.condition.wait(remaining)
    def finish(self,device,identity,raw,meta):
        with self.condition:
            job=self.jobs.get(identity)
            if not job or job['device']!=device:raise DeviceError(404,'Task expired.')
            if len(raw)>CHUNK:raise DeviceError(413,'Source chunk too large.')
            try:
                info=json.loads(base64.b64decode(meta,validate=True));final=allowed(info['url'],job['kind'])
                if final!=job['url']:raise ValueError()
                if info.get('ok') is not True:job['upload'].clear();job['error']='Устройство не получило публичную страницу источника.'
                else:
                    offset=info.get('offset',0);complete=info.get('complete',True)
                    if type(offset) is not int or type(complete) is not bool or offset!=len(job['upload']) or len(job['upload'])+len(raw)>MAXIMUM:raise ValueError()
                    job['upload'].extend(raw)
                    if not complete:return
                    raw=bytes(job['upload']);job['upload'].clear()
                if job['error']:pass
                elif job['kind']=='image':
                    from manga_download import image_extension
                    extension=image_extension(raw[:32])
                    if not extension:raise ValueError()
                    job['result']=(raw,final,{'Content-Type':'image/'+('jpeg' if extension=='jpg' else extension)})
                else:
                    if len(raw)>4*1024*1024 or not raw:raise ValueError()
                    job['result']=(raw,final,{'Content-Type':'text/html; charset=utf-8'})
            except (ValueError,KeyError,TypeError):raise DeviceError(422,'Invalid public source response.') from None
            self.condition.notify_all()

relay=Relay(Path(os.getenv('DATA_DIR','/data'))/'source-device-public-keys.json')

def document(url,referer='',timeout=28):
    raw,final,headers=relay.fetch(url,'document',referer,timeout)
    return raw.decode('utf-8',errors='replace'),final,headers

def image(url,referer):
    return relay.fetch(url,'image',referer)

def install(app):
    from fastapi import HTTPException,Request
    @app.exception_handler(DeviceError)
    async def device_error(request,error):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':error.detail},status_code=error.status)
    @app.get('/source-device/poll')
    def poll(request:Request):
        device=relay.authenticate(request)
        return {'task':relay.poll(device)}
    @app.post('/source-device/result/{identity}')
    async def result(identity:str,request:Request):
        raw=await request.body();device=relay.authenticate(request,raw)
        relay.finish(device,identity,raw,request.headers.get('x-source-meta',''))
        return {'accepted':True}
