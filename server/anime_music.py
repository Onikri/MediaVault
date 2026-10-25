"""Song credits, never audio downloads. Exact MAL mapping from AnimeThemes."""
import re,threading,time
from fastapi import HTTPException
from metadata_catalog import get_json
_cache={};lock=threading.RLock()
def songs(identity):
    identity=str(identity)
    if not re.fullmatch(r'[1-9]\d{0,11}',identity):raise HTTPException(422,'Нужен точный ID аниме.')
    with lock:hit=_cache.get(identity)
    if hit and hit[0]>time.monotonic():return hit[1]
    data=get_json('https://api.animethemes.moe/anime',params={'filter[has]':'resources','filter[site]':'MyAnimeList','filter[external_id]':identity,'include':'resources,animethemes.song.artists,animethemes.animethemeentries'})
    tracks=[]
    for anime in data.get('anime',[]):
        if not any(v.get('site')=='MyAnimeList' and str(v.get('external_id'))==identity for v in anime.get('resources',[])):continue
        for theme in anime.get('animethemes',[]):
            song=theme.get('song') or {};title=str(song.get('title') or '').strip()[:250]
            if not title or theme.get('type') not in {'OP','ED'}:continue
            artists=list(dict.fromkeys(str(a.get('name') or '')[:180] for a in song.get('artists',[]) if a.get('name')))
            episodes=list(dict.fromkeys(str(v.get('episodes'))[:120] for v in theme.get('animethemeentries',[]) if v.get('episodes') and not v.get('nsfw')))
            tracks.append({'id':'animethemes:'+str(theme['id']),'title':title,'artists':artists,'type':theme['type'],'episodes':episodes,'animeId':identity,'source':'AnimeThemes','sourceUrl':'https://animethemes.moe/anime/'+str(anime.get('slug','')),'timing':None})
    result={'identity':identity,'tracks':list({v['id']:v for v in tracks}.values())[:40],'checkedAt':int(time.time()),'audioDownloaded':False}
    with lock:
        if len(_cache)>256:_cache.clear()
        _cache[identity]=(time.monotonic()+(21600 if tracks else 90),result)
    return result

def install(app):
    @app.get('/music/anime/{identity}')
    def music(identity:str):return songs(identity)
