"""Scoped, signed taxonomy updates; never executes uploaded code or changes sessions."""
from pathlib import Path
import hashlib
import hmac
import json
import os
import re
import tempfile
import threading
import time
import urllib.request

from manga_tag_policy import Policy, canonical_json, current

_update_lock=threading.Lock()


class DeployError(Exception):
    def __init__(self,status,message):super().__init__(message);self.status=status


def authenticate(body,timestamp,signature,key=None,now=None):
    now=time.time() if now is None else now
    if not re.fullmatch(r'[0-9]{10}',str(timestamp)) or abs(now-int(timestamp))>300:
        raise DeployError(401,'Invalid deployment timestamp')
    if key is None:
        try:key=(Path(os.getenv('DATA_DIR','/data'))/'manga-tags-deploy.key').read_bytes().strip()
        except OSError:raise DeployError(503,'Taxonomy deployment is not configured') from None
    expected=hmac.new(key,str(timestamp).encode()+b'.'+canonical_json(body),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,str(signature)):
        raise DeployError(401,'Invalid deployment signature')


def committed_policy():
    # Fixed public repository; no URL, shell command or code comes from the request.
    request=urllib.request.Request('https://raw.githubusercontent.com/Onikri/MediaVault/main/server/manga-tag-policy.json',headers={'User-Agent':'MediaVault-Taxonomy-Deploy','Cache-Control':'no-cache'})
    with urllib.request.urlopen(request,timeout=20) as response:raw=response.read(1_000_001)
    if len(raw)>1_000_000:raise DeployError(422,'Committed policy exceeds size limit')
    return Policy(json.loads(raw))


def atomic_write(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.manga-policy-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
        os.chmod(name,0o600);os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def apply(body,store,*,verify_commit=True):
    if not re.fullmatch(r'[a-f0-9]{40}',body.get('commit','')):raise DeployError(422,'Invalid commit identifier')
    try:policy=Policy(body['policy'])
    except (ValueError,KeyError,TypeError) as error:raise DeployError(422,str(error)) from None
    if verify_commit:
        try:remote=committed_policy()
        except DeployError:raise
        except Exception:raise DeployError(502,'Cannot verify the committed taxonomy') from None
        if remote.revision!=policy.revision:raise DeployError(409,'This taxonomy was superseded on GitHub')
    if not _update_lock.acquire(blocking=False):raise DeployError(409,'A taxonomy update is already running')
    try:
        from manga_catalog_index import reindex
        path=Path(os.getenv('DATA_DIR','/data'))/'manga-tag-policy.json'
        with store.lock:
            if current().revision==policy.revision:
                return {'applied':True,'unchanged':True,'revision':policy.revision,'commit':body['commit']}
            prior=path.read_bytes() if path.exists() else None
            try:
                with store.db:
                    count=reindex(store.db,policy)
                    atomic_write(path,canonical_json(policy.data)+b'\n')
                    store.db.execute("INSERT OR REPLACE INTO catalog_policy_state VALUES('commit',?)",(body['commit'],))
            except BaseException:
                if prior is not None:atomic_write(path,prior)
                elif path.exists():path.unlink()
                raise
            # Startup also compares the policy digest with the DB projection,
            # recovering a process interruption between replace() and commit().
            assert current().revision==policy.revision
        return {'applied':True,'unchanged':False,'revision':policy.revision,'commit':body['commit'],'reindexedTitles':count}
    finally:_update_lock.release()
