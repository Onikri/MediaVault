"""Reuse the owner's existing server-side LibGroup session for title metadata.

Tokens stay in Suwayomi's private preferences. They are never copied into jobs,
catalogue rows, public policy, browser responses or source-control files.
"""
import re,threading,time
from suwayomi_bridge import Client,configured

SOURCES={1:'6111047689498497237',2:'2730544188738947015',4:'6425650164840473547'}
_cache={};_lock=threading.Lock()


def token(site):
    if site not in SOURCES or not configured():return ''
    # LibGroup accounts are shared across its sites. Prefer the requested
    # source's session, then the already-connected HentaiLib account.
    with _lock:
        for candidate in dict.fromkeys((site,4)):
            now=time.monotonic();hit=_cache.get(candidate)
            if hit and hit[0]>now:
                if hit[1]:return hit[1]
                continue
            value='';client=None
            try:
                client=Client()
                for item in client.get('/source/'+SOURCES[candidate]+'/preferences',timeout=10):
                    props=item.get('props') or {}
                    raw=props.get('currentValue')
                    if props.get('key')=='bearer_token' and isinstance(raw,str) and re.fullmatch(r'[A-Za-z0-9._~+/=-]{16,8192}',raw.strip()):value=raw.strip();break
            except Exception:
                # Public metadata remains available without a connected session.
                # Never include an upstream error, which may contain credentials.
                pass
            finally:
                if client:client.close()
            _cache[candidate]=(now+(300 if value else 60),value)
            if value:return value
    return ''
