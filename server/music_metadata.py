"""Small, expiring MusicBrainz metadata cache. Artwork stays on Cover Art Archive."""
from collections import OrderedDict
import re,threading,time,unicodedata
from fastapi import HTTPException
from music_artists import musicbrainz
from source_parser import SourceError

_cache=OrderedDict();_lock=threading.RLock();_slot=threading.BoundedSemaphore(1);_last_request=0.0
_uuid=re.compile(r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$',re.I)
def words(value):return set(re.findall(r'[^\W_]+',unicodedata.normalize('NFKC',str(value)).casefold()))
def quoted(value):return '"'+re.sub(r'([+\-!(){}\[\]^"~*?:\\/])',r'\\\1',value)+'"'

def select_recording(data,title,artist):
    wanted=words(title);performer=words(artist);candidates=[]
    for row in data.get('recordings',[])[:12]:
        identity=row.get('id','');name=row.get('title','')
        if not _uuid.fullmatch(identity):continue
        artists=[c.get('artist',{}).get('name') for c in row.get('artist-credit',[]) if isinstance(c,dict)]
        artists=[x for x in artists if isinstance(x,str) and x]
        title_score=len(wanted&words(name))/max(1,len(wanted));artist_score=len(performer&words(' '.join(artists)))/max(1,len(performer)) if performer else 1
        if title_score<.8 or artist_score<.5:continue
        candidates.append((title_score*.7+artist_score*.3,row,artists))
    if not candidates:return {'found':False,'provider':'MusicBrainz','artworkDownloaded':False}
    score,row,artists=max(candidates,key=lambda x:x[0]);releases=sorted(row.get('releases',[]),key=lambda r:(r.get('status')!='Official',r.get('date') or '9999'))
    release=next((r for r in releases if _uuid.fullmatch(r.get('id',''))),{})
    group=release.get('release-group') or {};group_id=group.get('id','')
    cover=('https://coverartarchive.org/release-group/'+group_id+'/front-250') if _uuid.fullmatch(group_id) else ('https://coverartarchive.org/release/'+release['id']+'/front-250' if release else '')
    return {'found':True,'id':row['id'],'title':str(row['title'])[:300],'artists':artists[:12],
        'album':str(release.get('title',''))[:300],'date':str(release.get('date',''))[:16],
        'durationMs':row.get('length') if isinstance(row.get('length'),int) else None,
        'cover':cover,'url':'https://musicbrainz.org/recording/'+row['id'],'provider':'MusicBrainz',
        'artworkProvider':'Cover Art Archive' if cover else '', 'artworkDownloaded':False,'confidence':round(score,3)}

def metadata(title,artist=''):
    global _last_request
    title=title.strip();artist=artist.strip()
    if not title or len(title)>250 or len(artist)>300:raise HTTPException(422,'Укажи название песни и исполнителя.')
    key=(title.casefold(),artist.casefold());now=time.monotonic()
    with _lock:
        hit=_cache.get(key)
        if hit and hit[0]>now:_cache.move_to_end(key);return hit[1]
    if not _slot.acquire(False):raise HTTPException(429,'Поиск музыкальных сведений занят. Попробуй позже.')
    try:
        # MusicBrainz permits an average of one request per second per IP.
        if now-_last_request<1.1:raise HTTPException(429,'Следующий запрос музыкальных сведений доступен через секунду.')
        _last_request=now
        query='recording:'+quoted(title)+(' AND artist:'+quoted(artist) if artist else '')
        try:result=select_recording(musicbrainz('recording/',{'query':query,'limit':12}),title,artist)
        except SourceError:result={'found':False,'provider':'MusicBrainz','artworkDownloaded':False,'unavailable':True}
        with _lock:
            _cache[key]=(time.monotonic()+(60 if result.get('unavailable') else 21600 if result['found'] else 300),result)
            while len(_cache)>256:_cache.popitem(last=False)
        return result
    finally:_slot.release()
