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

AUDIO_LINK=re.compile(r'https://a\.animethemes\.moe/[A-Za-z0-9._-]{1,200}\.ogg')
_audio={}

THEME_AUDIO_QUERY='query($id:Int){animethemePagination(id:$id,first:1){data{animethemeentries{nsfw videos{nodes{audio{link}}}}}}}'

def _first_audio(entries):
    for entry in entries or []:
        if not isinstance(entry,dict) or entry.get('nsfw'):continue
        videos=entry.get('videos') or []
        if isinstance(videos,dict):videos=videos.get('nodes') or []
        for video in videos:
            candidate=str(((video or {}).get('audio') or {}).get('link') or '')
            if AUDIO_LINK.fullmatch(candidate):return candidate
    return None

def theme_audio(theme_id):
    """AnimeThemes' own audio rip of one OP/ED, played through /music/remote.

    Our server proxy streams it, so OP/ED playback never depends on YouTube
    (which refuses the Oracle datacenter IP without a saved session).
    GraphQL is the primary contract: AnimeThemes' REST host has been answering
    503 for long stretches, which left every OP/ED unplayable.
    """
    now=time.monotonic()
    with lock:
        hit=_audio.get(theme_id)
        if hit and hit[0]>now:return hit[1]
    import requests
    from source_parser import USER_AGENT
    headers={'User-Agent':USER_AGENT,'Accept':'application/json'}
    link=None;found=False;reachable=False
    try:
        response=requests.post(GRAPHQL,json={'query':THEME_AUDIO_QUERY,'variables':{'id':int(theme_id)}},headers=headers,timeout=(4,15))
        response.raise_for_status();data=response.json()
        rows=((data.get('data') or {}).get('animethemePagination') or {}).get('data') if isinstance(data,dict) else None
        if isinstance(rows,list):
            reachable=True;found=bool(rows)
            if rows:link=_first_audio(rows[0].get('animethemeentries'))
    except (requests.RequestException,ValueError,AttributeError,TypeError):pass
    if not link and not reachable:
        try:
            response=requests.get('https://api.animethemes.moe/animetheme/'+str(theme_id),
                                  params={'include':'animethemeentries.videos.audio','fields[video]':'basename','fields[audio]':'link'},
                                  headers=headers,timeout=(4,15))
            if response.status_code==404:raise HTTPException(404,'AnimeThemes не нашёл эту песню.')
            response.raise_for_status();data=response.json()
        except HTTPException:raise
        except (requests.RequestException,ValueError):
            raise HTTPException(502,'AnimeThemes сейчас не отвечает. Повтори немного позже.') from None
        theme=data.get('animetheme') if isinstance(data,dict) else None
        found=bool(theme);link=_first_audio((theme or {}).get('animethemeentries'))
    if not found:raise HTTPException(404,'AnimeThemes не нашёл эту песню.')
    if not link:raise HTTPException(404,'У этой песни нет аудио в AnimeThemes.')
    with lock:
        if len(_audio)>512:_audio.clear()
        _audio[theme_id]=(now+86400,link)
    return link

THEME_SEARCH_QUERY='query($q:String!){search(search:$q,first:8){animethemes{id type song{title{romaji native} performances{artist{... on Artist{name{main}}}}} animethemeentries{nsfw videos{nodes{audio{link}}}}}}}'
_theme_search={}

def song_key(value):
    text=re.sub(r'[\(\[（【][^)\]）】]*(?:tv|size|ver|version|full|short|op|ed|opening|ending)[^)\]）】]*[\)\]）】]','',str(value or ''),flags=re.I)
    text=re.sub(r'\b(?:tv\s*size|full\s*(?:ver(?:sion)?|size)|opening|ending|op\s*\d*|ed\s*\d*)\b','',text,flags=re.I)
    return re.sub(r'[^\w]+','',text.casefold())

def search_theme(title,artist=''):
    """An anime song by name (and artist) -> AnimeThemes' own audio rip.

    Lets the music player avoid YouTube for OP/ED songs whose saved record
    lacks an AnimeThemes id. Only an exact song-title match is accepted.
    """
    wanted=song_key(title)
    if len(wanted)<2:return None
    key=(wanted,song_key(artist))
    now=time.monotonic()
    with lock:
        hit=_theme_search.get(key)
        if hit and hit[0]>now:return hit[1]
    import requests
    from source_parser import USER_AGENT
    query=re.sub(r'[\(\[（【][^)\]）】]*[\)\]）】]',' ',str(title)).strip()+(' '+str(artist).strip() if artist else '')
    try:
        response=requests.post(GRAPHQL,json={'query':THEME_SEARCH_QUERY,'variables':{'q':query[:200]}},headers={'User-Agent':USER_AGENT,'Accept':'application/json'},timeout=(4,15))
        response.raise_for_status();rows=((response.json().get('data') or {}).get('search') or {}).get('animethemes') or []
    except (requests.RequestException,ValueError,AttributeError):
        raise HTTPException(502,'AnimeThemes сейчас не отвечает. Повтори немного позже.') from None
    best=None
    for row in rows:
        song=(row or {}).get('song') or {}
        titles=[song_key(v) for v in (song.get('title') or {}).values() if v]
        if wanted not in titles:continue
        artists=[song_key((p.get('artist') or {}).get('name',{}).get('main')) for p in song.get('performances') or [] if isinstance(p,dict)]
        link=_first_audio(row.get('animethemeentries'))
        if not link:continue
        score=2 if key[1] and key[1] in artists else 1
        if not best or score>best[0]:best=(score,{'id':'animethemes:'+str(row['id']),'audio':link,'type':row.get('type'),'title':(song.get('title') or {}).get('romaji')})
    value=best[1] if best and (best[0]==2 or not key[1]) else None
    with lock:
        if len(_theme_search)>512:_theme_search.clear()
        _theme_search[key]=(now+86400,value)
    return value

def install(app):
    @app.get('/music/anime/{identity}')
    def music(identity:str):return songs(identity)

    @app.get('/music/theme-search')
    def music_theme_search(title:str,artist:str=''):
        if not 1<=len(title)<=200 or len(artist)>200:raise HTTPException(422,'Некорректное название песни.')
        value=search_theme(title,artist)
        if not value:raise HTTPException(404,'Песни нет в AnimeThemes.')
        return value

    @app.get('/music/theme-audio/{theme_id}')
    def music_theme_audio(theme_id:int):
        if not 1<=theme_id<=10**9:raise HTTPException(422,'Некорректная песня AnimeThemes.')
        return {'audio':theme_audio(theme_id)}
