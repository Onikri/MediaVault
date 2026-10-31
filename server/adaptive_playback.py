"""Combine published per-quality HLS sources into one adaptive master."""
import copy
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin
import m3u8
from source_parser import SourceError


def adaptive_master(streams,http,max_quality=None):
    choices={int(s['quality']):s for s in streams if s.get('type')=='hls' and str(s.get('quality','')).isdigit()
             and (max_quality is None or int(s['quality'])<=max_quality)}
    if len(choices)<2:return None
    def read(pair):
        quality,stream=pair;client=http.fork() if hasattr(http,'fork') else http
        try:
            text,final,_=client.document(stream['url'],headers=stream.get('headers'))
            if not text.lstrip().startswith('#EXTM3U'):raise SourceError('Источник не предоставил HLS.')
            return quality,stream,m3u8.loads(text,uri=final),final
        finally:
            if client is not http:client.close()
    # Failures must not silently remove a published quality from the menu.
    with ThreadPoolExecutor(max_workers=3 if hasattr(http,'fork') else 1) as pool:
        rows=list(pool.map(read,sorted(choices.items())))
    master=m3u8.M3U8();master.is_variant=True
    for quality,stream,playlist,final in rows:
        if playlist.session_keys or any(k and k.method not in (None,'NONE') for k in playlist.keys):
            raise SourceError('Зашифрованные и DRM-потоки в онлайн-режиме не поддерживаются.')
        prefix='q'+str(quality)+'-'
        if playlist.is_variant:
            source=max(playlist.playlists,key=lambda p:((p.stream_info.resolution or (0,0))[1],p.stream_info.bandwidth or 0))
            selected=copy.deepcopy(source);selected.uri=source.absolute_uri
            selected.media=[]
            for attribute in ('audio','subtitles','video','closed_captions'):
                group=getattr(selected.stream_info,attribute,None)
                if group and group!='NONE':setattr(selected.stream_info,attribute,prefix+group)
            for media in playlist.media:
                item=copy.deepcopy(media)
                if item.uri:item.uri=urljoin(final,item.uri)
                if not item.group_id:continue
                item.group_id=prefix+item.group_id
                master.media.append(item)
                selected.media.append(item)
        else:
            # Resolution is unknown for a media-only playlist. Its publisher's
            # quality label stays in NAME; bandwidth is an ABR starting estimate.
            estimate=int(450000*(quality/360)**2)
            selected=m3u8.Playlist(final,{'bandwidth':estimate},[],final)
        selected.stream_info.name=str(quality)+'p'
        # m3u8's StreamInfo serializer does not retain arbitrary NAME attributes.
        master.playlists.append(selected)
    text=master.dumps().splitlines();index=0
    for n,line in enumerate(text):
        if line.startswith('#EXT-X-STREAM-INF:'):
            quality=rows[index][0];text[n]=line+',NAME="'+str(quality)+'p"';index+=1
    return '\n'.join(text)+'\n'
