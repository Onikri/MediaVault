"""Public recording links for the official YouTube embed; never extract audio."""
import json,re,threading,time,unicodedata
from urllib.parse import urlencode
from fastapi import HTTPException
from source_parser import PublicHttp,SourceError
from metadata_catalog import get_json
cache={};lock=threading.RLock();slot=threading.BoundedSemaphore(2)
def text(node):
    if not isinstance(node,dict):return ''
    return str(node.get('simpleText') or ''.join(v.get('text','') for v in node.get('runs',[])))[:300]
def words(value):return set(re.findall(r'[^\W_]+',unicodedata.normalize('NFKC',value).casefold()))
def parse_recordings(html,title,artist):
    mark=re.search(r'(?:var\s+)?ytInitialData\s*=\s*',html)
    if not mark:return []
    try:data,_=json.JSONDecoder().raw_decode(html[mark.end():])
    except ValueError:return []
    stack=[data];results=[];count=0;seen=set();a=words(artist);t=words(title)
    while stack and count<30000:
        node=stack.pop();count+=1
        if isinstance(node,list):stack.extend(reversed(node));continue
        if not isinstance(node,dict):continue
        v=node.get('videoRenderer')
        if isinstance(v,dict):
            identity=v.get('videoId','');name=text(v.get('title'));author=text(v.get('ownerText') or v.get('longBylineText') or v.get('shortBylineText'));duration=text(v.get('lengthText'))
            if re.fullmatch(r'[\w-]{11}',identity) and identity not in seen and name and duration:
                seen.add(identity);combined=words(name+' '+author);title_score=len(t&combined)/max(1,len(t));artist_score=len(a&combined)/max(1,len(a)) if a else 1
                score=title_score*.7+artist_score*.3
                results.append({'id':identity,'title':name,'author':author,'duration':duration,'match':title_score>=.8 and artist_score>=.5,'score':round(score,3)})
        stack.extend(reversed(list(node.values())))
    return sorted(results,key=lambda r:(r['match'],r['score']),reverse=True)[:8]
def recordings(title,artist):
    key=(title,artist);now=time.monotonic()
    with lock:hit=cache.get(key)
    if hit and hit[0]>now:return hit[1]
    if not slot.acquire(False):raise HTTPException(429,'Поиск занят. Повтори через несколько секунд.')
    http=PublicHttp(timeout=(4,12),deadline=now+20)
    try:
        html,_,_=http.document('https://www.youtube.com/results?'+urlencode({'search_query':title+' '+artist+' official audio','hl':'ru'}))
        results=parse_recordings(html,title,artist);value={'results':results,'provider':'YouTube','playback':'official-embed','audioDownloaded':False}
        with lock:
            if len(cache)>128:cache.clear()
            cache[key]=(now+(21600 if results else 60),value)
        return value
    finally:http.close();slot.release()
def skip_times(identity,episode,duration):
    try:
        data=get_json(f'https://api.aniskip.com/v2/skip-times/{identity}/{episode}',params=[('types[]','op'),('types[]','ed'),('episodeLength',round(duration))])
        parts=[]
        for v in data.get('results',[]):
            interval=v.get('interval') or {};start=interval.get('startTime');end=interval.get('endTime')
            if v.get('skipType') in {'op','ed'} and isinstance(start,(int,float)) and isinstance(end,(int,float)) and 0<=start<end<=duration+2:
                parts.append({'type':v['skipType'],'start':start,'end':min(end,duration),'source':'AniSkip'})
        return {'intervals':parts,'source':'AniSkip'}
    except (HTTPException,SourceError,ValueError,TypeError):return {'intervals':[],'source':'AniSkip','message':'Разметки этой серии пока нет.'}
def install(app):
    @app.get('/music/search')
    def search(title:str='',artist:str=''):
        title=title.strip();artist=artist.strip()
        if not title or len(title)>250 or len(artist)>300:raise HTTPException(422,'Нужны название песни и исполнитель.')
        return recordings(title,artist)
    @app.get('/music/timings/{identity}/{episode}')
    def timings(identity:int,episode:int,duration:float=0):
        if not 1<=identity<=10**12 or not 1<=episode<=10000 or not 0<duration<=86400:return {'intervals':[]}
        return skip_times(identity,episode,duration)
