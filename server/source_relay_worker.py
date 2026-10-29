"""Outbound public-source device worker; private signing key never leaves device."""
import argparse,base64,json,os,secrets,threading,time
from pathlib import Path
from urllib.parse import urlsplit
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PrivateFormat,PublicFormat,NoEncryption
from source_relay import allowed,message,MAXIMUM
from source_parser import PublicHttp,SourceError

def load_key(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():return Ed25519PrivateKey.from_private_bytes(path.read_bytes())
    key=Ed25519PrivateKey.generate()
    descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(descriptor,'wb') as out:out.write(key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption()))
    return key

def retrieve(task):
    url=allowed(task['url'],task['kind'],resolve_dns=True)
    validate=lambda value:allowed(value,task['kind'],resolve_dns=True)
    http=PublicHttp(validate=validate,timeout=(3,15),deadline=time.monotonic()+23)
    try:
        headers={'Referer':allowed(task['referer'],resolve_dns=True)} if task.get('referer') else None
        if task['kind']=='document':
            text,final,_=http.document(url,headers=headers)
            if final!=url or '<title>404 Not Found</title>' in text:raise SourceError('Source response unavailable')
            return text.encode('utf-8'),final
        response,final=http._open(url,headers=headers)
        try:
            raw=bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw)>MAXIMUM:raise SourceError('Image too large')
            from manga_download import image_extension
            if not image_extension(raw[:32]):raise SourceError('Invalid image')
            return bytes(raw),final
        finally:response.close()
    finally:http.close()

def run(server,identity,key,stop=None):
    parsed=urlsplit(server)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.path not in ['','/'] or parsed.query or parsed.fragment:raise ValueError('Expected HTTPS backend origin')
    session=requests.Session();session.trust_env=False
    def request(path,raw=None,meta=''):
        method='GET' if raw is None else 'POST';stamp=str(int(time.time()));nonce=secrets.token_urlsafe(18)
        signature=base64.b64encode(key.sign(message(method,path,stamp,nonce,raw or b'',meta))).decode()
        headers={'X-Source-Device':identity,'X-Source-Time':stamp,'X-Source-Nonce':nonce,'X-Source-Signature':signature,'X-Source-Meta':meta,'Content-Type':'application/octet-stream'}
        response=session.request(method,server.rstrip('/')+path,data=raw,headers=headers,timeout=(4,22));response.raise_for_status();return response.json()
    while stop is None or not stop.is_set():
        try:
            task=request('/source-device/poll').get('task')
            if not task:continue
            try:raw,final=retrieve(task);info={'ok':True,'url':final}
            except Exception:raw=b'';info={'ok':False,'url':task['url']}
            meta=base64.b64encode(json.dumps(info,separators=(',',':')).encode()).decode()
            request('/source-device/result/'+task['id'],raw,meta)
        except (requests.RequestException,ValueError,KeyError):
            if stop is None:time.sleep(2)
            else:stop.wait(2)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--server');parser.add_argument('--identity',default='mediavault-desktop');parser.add_argument('--key',required=True);parser.add_argument('--public-key',action='store_true');args=parser.parse_args();key=load_key(args.key)
    if args.public_key:print(json.dumps({'identity':args.identity,'publicKey':base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()}))
    else:
        if not args.server:parser.error('--server is required')
        threads=[threading.Thread(target=run,args=(args.server,args.identity,key),daemon=True) for _ in range(3)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
