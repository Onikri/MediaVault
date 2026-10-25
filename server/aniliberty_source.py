"""Public AniLiberty catalogue and published episodes; no account or API token."""
import json
import re
from urllib.parse import urlencode, urlsplit
from source_parser import SourceError

API='https://aniliberty.top/api/v1'
SITE='https://aniliberty.top'


def candidate(release):
    name=release.get('name') or {}
    names=[v for v in name.values() if isinstance(v,str) and v.strip()]
    alias=release.get('alias')
    if not names or not isinstance(alias,str) or not re.fullmatch(r'[a-zA-Z0-9_-]+',alias):return None
    ids={}
    for key in ('mal_id','shikimori_id'):
        value=release.get(key)
        if value and str(value).isdigit():ids['mal']=str(value)
    return {'provider':'anilibria','providerName':'AniLiberty / AniLibria','title':name.get('main') or names[0],
            'aliases':names,'url':SITE+'/anime/releases/release/'+alias,'kind':'anime',
            'year':release.get('year'),'ids':ids,'dubs':[],'releaseDates':[]}


def search(query,http):
    text,_,_=http.document(API+'/app/search/releases?'+urlencode({'query':query,'limit':20}))
    data=json.loads(text);rows=data.get('data',[]) if isinstance(data,dict) else data
    if not isinstance(rows,list):raise SourceError('AniLiberty вернул неизвестный формат каталога.')
    return [item for row in rows[:20] if isinstance(row,dict) and (item:=candidate(row))]


def inspect(url,http,*,dub_url=None):
    from player_catalog import choice
    match=re.fullmatch(r'/anime/releases/release/([a-zA-Z0-9_-]+)(?:/episodes/(\d+))?/?',urlsplit(url).path)
    if not match:raise SourceError('Нужна страница конкретного релиза AniLiberty.')
    text,_,_=http.document(API+'/anime/releases/'+match[1]);release=json.loads(text)
    item=candidate(release)
    if not item:raise SourceError('AniLiberty не подтвердил выбранный релиз.')
    if release.get('is_blocked_by_geo'):raise SourceError('AniLiberty ограничил доступ к этому релизу в регионе сервера.')
    episodes=[]
    for episode in release.get('episodes') or []:
        number=episode.get('ordinal')
        if not isinstance(number,(int,float)) or not 1<=number<=10000 or int(number)!=number:continue
        if not any(episode.get('hls_'+str(q)) for q in (480,720,1080)):continue
        episodes.append({'number':int(number),'season':1,'title':episode.get('name') or 'Серия '+str(int(number)),
                         'url':item['url']+'/episodes/'+str(int(number))})
    episodes.sort(key=lambda e:e['number'])
    if match[2]:episodes=[e for e in episodes if e['number']==int(match[2])]
    if dub_url and not any(e['url']==dub_url for e in episodes):raise SourceError('Выбранная серия AniLiberty больше не опубликована.')
    voices=[choice('AniLibria.TV',episodes[0]['url'],player='AniLiberty',language='ru',episodes=episodes)] if episodes else []
    return {**item,'providerName':'AniLiberty / AniLibria','dubs':voices,'seasons':[{'number':1,'name':'Сезон релиза'}] if episodes else [],
            'episodes':episodes,'releases':[],'available':bool(episodes),'diagnostics':[]}
