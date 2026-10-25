#!/usr/bin/env python3
"""Live source-only checks. No Google session, private data volume or full video download."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from source_parser import PublicHttp,Resolver
from media_download import expand_stream_qualities,pick_stream

SAMPLES={
    'Aniboom':'https://aniboom.one/embed/9G1MJ6NMV8z?episode=1&translation=30',
    'CVH':'https://animego.me/cdn-iframe/40748/1/1',
    'Kodik':'https://kodikplayer.com/seria/1304528/932d5da818729ec5ccc9be7968ee3717/720p',
    'Sibnet':'https://video.sibnet.ru/shell.php?videoid=2589828',
    'Animedia':'https://aser.pro/vod/20182',
    'AniLiberty':'https://aniliberty.top/anime/releases/release/bleach/episodes/1',
    'VK':'https://vk.com/video_ext.php?oid=-33905270&id=456239024',
}

def verify_stream(http,stream):
    headers=stream.get('headers') or {}
    if stream['type']=='hls':
        text,final,_=http.document(stream['url'],headers=headers)
        if not text.lstrip().startswith('#EXTM3U'):raise ValueError('The source did not return an HLS manifest.')
        import m3u8
        playlist=m3u8.loads(text,uri=final)
        if playlist.is_variant:
            if not playlist.playlists:raise ValueError('The master playlist has no variants.')
            text,final,_=http.document(playlist.playlists[0].absolute_uri,headers=headers)
            if not text.lstrip().startswith('#EXTM3U'):raise ValueError('The source did not return an HLS media playlist.')
            playlist=m3u8.loads(text,uri=final)
        if not playlist.segments:raise ValueError('The media playlist has no published segments.')
        media=playlist.segments[0].absolute_uri
    else:media=stream['url']
    response,_=http._open(media,headers=headers,byte_range='bytes=0-1023')
    try:
        if 'text/html' in response.headers.get('Content-Type','').lower():raise ValueError('The media endpoint returned HTML.')
        block=next(response.iter_content(1024),b'')
        if not block:raise ValueError('The media endpoint returned no bytes.')
        return {'http':response.status_code,'sampleBytes':len(block),'manifest':stream['type']=='hls'}
    finally:response.close()

def check(sample):
    name,url=sample;http=PublicHttp(timeout=(5,10),deadline=time.monotonic()+45)
    result={'player':name,'sourceUrl':url}
    try:
        page=Resolver(http).resolve(url)
        result['streams']=len(page.streams)
        if not page.streams:raise ValueError('The player returned no MP4/HLS streams.')
        streams=expand_stream_qualities(page.streams,http)
        result['qualities']=sorted({int(s['quality']) for s in streams if s.get('quality')},reverse=True)
        stream=pick_stream(streams,'best')
        result.update(status='verified',kind=stream['type'],**verify_stream(http,stream))
    except Exception as error:
        result.update(status='failed',errorClass=type(error).__name__,message=re.sub(r'https?://[^\s]+','[URL]',str(error))[:350])
    finally:http.close()
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample',action='append',default=[],metavar='PLAYER=PUBLIC_URL',help='Override/add a current public episode; use this for Alloha/Jut.su or stale reference samples.')
    parser.add_argument('--only',action='append',default=[],help='Check only these named players.')
    parser.add_argument('--catalog',action='store_true',help='Also verify exact-title discovery for Dandadan / MAL 57334 / 2024.')
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();samples=dict(SAMPLES)
    for value in args.sample:
        name,separator,url=value.partition('=')
        if not separator or not name or not url:parser.error('--sample needs PLAYER=PUBLIC_URL')
        samples[name]=url
    if args.only:
        if set(args.only)-samples.keys():parser.error('Every selected player needs a public sample URL.')
        samples={k:v for k,v in samples.items() if k in args.only}
    report={'observedAt':datetime.now(timezone.utc).isoformat(),'players':[]}
    with ThreadPoolExecutor(max_workers=4) as pool:report['players']=list(pool.map(check,samples.items()))
    if args.catalog:
        from source_discovery import discover
        selected={'title':'Дандадан','aliases':['Dandadan'],'year':2024,'kind':'anime','ids':{'mal':'57334'}}
        for attempt in range(6):
            report['catalog']=discover(selected,refresh=attempt>0)
            if not report['catalog'].get('pending'):break
    # Full reports can contain short-lived public source signatures; keep them private.
    descriptor=os.open(args.report,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    os.fchmod(descriptor,0o600)
    with os.fdopen(descriptor,'w') as saved:json.dump(report,saved,ensure_ascii=False,indent=2)
    for row in report['players']:
        print(row['player']+': '+row['status']+' '+(str(row.get('streams',0))+' streams, '+str(row.get('sampleBytes',0))+' media bytes' if row['status']=='verified' else row['errorClass']+' '+row['message'][:100]))
    if 'catalog' in report:
        catalog=report['catalog'];print('Exact-title catalogue: '+str(len(catalog['sources']))+' sources, '+str(len(catalog['voices']))+' translations')
        print('Catalogue sites: '+', '.join(p['provider']+':'+p['status'] for p in catalog['providers'] if p['provider'] in {'animego','yummy','anilibria','animedia','freeanime','anixart'}))
    return 0 if all(p['status']=='verified' for p in report['players']) else 1

if __name__=='__main__':sys.exit(main())
