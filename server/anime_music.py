"""Public song credits with exact MAL identity; no audio downloads or credentials."""
import re,threading,time
from fastapi import HTTPException
from metadata_catalog import get_json
from source_parser import SourceError
_cache={};_pending={};lock=threading.RLock()
GRAPHQL='https://graphql.animethemes.moe/'
# Current public schema: structured titles and performance credits.
QUERY='''query($ids:[Int!]!){findAnimeByExternalSite(site:MAL,id:$ids){
 slug resources{nodes{site externalId}}
 animethemes{id type song{title{romaji native} performances{artist{name{main native}}}}
 animethemeentries{episodes nsfw}}
}}'''

def theme_tracks(identity):
    response=get_json(GRAPHQL,body={'query':QUERY,'variables':{'ids':[int(identity)]}})
    rows=(response.get('data') or {}).get('findAnimeByExternalSite')
    if response.get('errors') or not isinstance(rows,list):raise SourceError('AnimeThemes не вернул список песен.')
    tracks=[]
    for anime in rows:
        if not any(v.get('site')=='MAL' and str(v.get('externalId'))==identity for v in (anime.get('resources') or {}).get('nodes',[])):continue
        for theme in anime.get('animethemes',[]):
            song=theme.get('song') or {};names=song.get('title') or {};title=str(names.get('romaji') or names.get('native') or '').strip()[:250]
            if not title or theme.get('type') not in {'OP','ED'}:continue
            artists=[]
            for performance in song.get('performances',[]):
                name=(performance.get('artist') or {}).get('name') or {}
                artist=str(name.get('main') or name.get('native') or '').strip()[:180]
                if artist and artist not in artists:artists.append(artist)
            episodes=list(dict.fromkeys(str(v['episodes'])[:120] for v in theme.get('animethemeentries',[]) if v.get('episodes') and not v.get('nsfw')))
            tracks.append({'id':'animethemes:'+str(theme['id']),'title':title,'artists':artists,'type':theme['type'],'episodes':episodes,'animeId':identity,'source':'AnimeThemes','sourceUrl':'https://animethemes.moe/anime/'+str(anime.get('slug','')),'timing':None})
    return list({v['id']:v for v in tracks}.values())[:40]

def mal_tracks(identity):
    response=get_json('https://api.jikan.moe/v4/anime/'+identity+'/full')
    anime=response.get('data') or {}
    if str(anime.get('mal_id'))!=identity:raise SourceError('Музыкальный каталог вернул другой тайтл.')
    if not isinstance(anime.get('theme'),dict):raise SourceError('Каталог не предоставил музыкальные титры.')
    tracks=[]
    for key,kind in [('openings','OP'),('endings','ED')]:
        for index,credit in enumerate(anime['theme'].get(key,[])[:40]):
            if not isinstance(credit,str):continue
            credit=re.sub(r'^\d+:\s*','',credit.strip())
            # MAL publishes credit strings rather than structured artist names.
            match=re.fullmatch(r'"(.+?)"(?: by (.*?))?(?: \(eps? ([^)]+)\))?',credit)
            title=match[1] if match else credit
            if not title:continue
            tracks.append({'id':f'mal-theme:{identity}:{kind}:{index+1}','title':title[:250],
                           'artists':[match[2][:180]] if match and match[2] else [],'type':kind,
                           'episodes':[match[3][:120]] if match and match[3] else [],'animeId':identity,
                           'source':'MyAnimeList / Jikan','sourceUrl':'https://myanimelist.net/anime/'+identity,'timing':None})
    return tracks[:40]

def songs(identity):
    identity=str(identity)
    if not re.fullmatch(r'[1-9]\d{0,9}',identity) or int(identity)>2147483647:raise HTTPException(422,'Нужен точный ID аниме.')
    with lock:
        hit=_cache.get(identity)
        if hit and hit[0]>time.monotonic():return hit[1]
        pending=_pending.get(identity);leader=pending is None
        if leader:pending=_pending[identity]=threading.Event()
    if not leader:
        if pending.wait(28):
            with lock:hit=_cache.get(identity)
            if hit:return hit[1]
        raise HTTPException(503,'Музыкальный каталог пока не ответил. Повтори загрузку.')
    try:
        tracks=None;source='AnimeThemes'
        try:tracks=theme_tracks(identity)
        except SourceError:pass
        if not tracks:
            try:
                fallback=mal_tracks(identity)
                if fallback or tracks is None:tracks=fallback;source='MyAnimeList / Jikan'
            except SourceError:pass
        if tracks is None:
            if hit:return {**hit[1],'stale':True}
            raise HTTPException(502,'Не удалось загрузить музыкальные титры из AnimeThemes и MyAnimeList. Повтори немного позже.')
        result={'identity':identity,'tracks':tracks,'source':source,'checkedAt':int(time.time()),'audioDownloaded':False}
        with lock:
            if len(_cache)>256:_cache.pop(next(iter(_cache)))
            _cache[identity]=(time.monotonic()+(21600 if tracks else 90),result)
        return result
    finally:
        with lock:_pending.pop(identity,None)
        pending.set()

def install(app):
    @app.get('/music/anime/{identity}')
    def music(identity:str):return songs(identity)
