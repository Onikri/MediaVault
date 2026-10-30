"""Enumerate published qualities without sending signed media links to the browser."""
from source_parser import PublicHttp,Resolver,SourceError
from media_download import expand_stream_qualities
import time

def inspect_qualities(url,*,referer=None,http=None,resolver=None):
    own=http is None and resolver is None
    http=http or (resolver.http if resolver else PublicHttp(timeout=(5,10),deadline=time.monotonic()+45))
    resolver=resolver or Resolver(http)
    try:
        page=resolver.resolve(url,referer=referer) if referer else resolver.resolve(url)
        streams=expand_stream_qualities(page.streams,http)
        heights={int(s['quality']) for s in streams if s.get('quality') and str(s['quality']).isdigit()}
        original=any(not s.get('quality') and s['type']=='mp4' for s in page.streams)
        qualities=sorted((h for h in heights if 1<=h<=8640),reverse=True)
        return {'qualities':qualities,'best':qualities[0] if qualities else None,'original':original,
                'streamCount':len(page.streams)}
    finally:
        if own:http.close()
