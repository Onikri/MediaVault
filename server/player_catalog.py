"""Enumerate public translation choices without resolving expiring video links.

AnimeGO provider/episode attributes follow the MIT AnimeParsers reference.
CVH uses only its two public, explicitly allowlisted playback endpoints.
"""
import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, urljoin
from bs4 import BeautifulSoup
from source_parser import SourceError, public_url

KODIK={'kodikplayer.com','kodik.info','kodik.biz','kodik.cc','aniqit.com'}
CVH_API='https://plapi.cdnvideohub.com/api/v1/player/sv'


def player_name(url):
    host=urlsplit(url).hostname or ''
    if host in KODIK:return 'Kodik'
    if 'aniboom' in host:return 'Aniboom'
    if 'sibnet' in host:return 'Sibnet'
    if 'cdnvideohub' in host or '/cdn-iframe/' in url:return 'CVH'
    if host in {'vk.com','vkvideo.ru','vk.ru','m.vk.com','m.vk.ru'}:return 'VK Video'
    if host in {'aser.pro','amd.online','animedia.online'}:return 'Animedia'
    if 'anilibr' in host or 'aniliberty' in host:return 'AniLiberty'
    return host


def translation_kind(name, explicit=''):
    text=str(explicit or name).casefold()
    return 'subtitles' if re.search(r'subtitle|субтит|\bsubs?\b',text) else 'voice'


def normalized_studio(value):
    return re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',value).casefold())


def choice(name, url, *, identity='', kind='', language='und', player='', episodes=None):
    url=public_url(url,resolve_dns=False)
    label=' '.join(str(name or '').split())[:120]
    return {'id':str(identity) or hashlib.sha256(url.encode()).hexdigest()[:20],
            'name':label or 'Название перевода не указано','url':url,'player':player or player_name(url),
            'kind':translation_kind(label,kind),'language':language,'named':bool(label),
            'episodes':episodes or []}


def animego_buttons(text,base):
    result=[]
    for button in BeautifulSoup(text,'html.parser').select('[data-player][data-translation-title]'):
        raw=button.get('data-player')
        if not raw:continue
        try:
            result.append(choice(button.get('data-translation-title'),urljoin(base,raw),
                identity=button.get('data-ptranslation',''),player=button.get('data-provider-title') or '',
                kind=button.get('data-translation-type','')))
        except SourceError:continue
    return result


def animego_episode_pages(text,base):
    result=[]
    for node in BeautifulSoup(text,'html.parser').select('[data-episode][data-episode-number]'):
        identity,number=node.get('data-episode',''),node.get('data-episode-number','')
        if identity.isdigit() and number.isdigit() and 0<int(number)<=10000:
            result.append({'number':int(number),'url':urljoin(base,'/player/videos/'+identity),'title':'Серия '+number})
    return list({(e['number'],e['url']):e for e in result}.values())


def relay_url(url, selected):
    root=urlsplit(url)
    params=dict(parse_qsl(root.query))
    params.update(mv_translation=selected['id'],mv_player=selected['player'])
    return urlunsplit((root.scheme,root.netloc,root.path,urlencode(params),''))


def relay_selection(url):
    parts=urlsplit(url);params=dict(parse_qsl(parts.query))
    identity=params.pop('mv_translation',None);player=params.pop('mv_player',None)
    if identity is None:return None
    if parts.hostname not in {'animego.org','animego.me'} or not re.fullmatch(r'/player/(?:videos/)?\d+',parts.path):
        raise SourceError('Выбор озвучки разрешён только на опубликованной странице AnimeGO.')
    return urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(params),'')),identity,player


def cvh_choices(url,http):
    from anime_dl_core.players.cvh import CvhPlayer
    parsed=CvhPlayer.parse_url(url)
    if not parsed.get('cvh_id'):return []
    text,_,_=http.document(CVH_API+'/playlist?'+urlencode({'pub':'747','aggr':'mali','id':parsed['cvh_id']}),headers={'Referer':'https://animego.org/'})
    import json
    rows=CvhPlayer._parse_playlist(json.loads(text),parsed['cvh_id'])
    groups={}
    for row in rows:
        if not row.video_id.isdigit() or not 1<=row.season<=1000 or not 1<=row.episode<=10000:continue
        # voiceType keeps subtitles distinct even if the studio name is identical.
        key=(row.studio or '',row.voice_type or '')
        group=groups.setdefault(key,[])
        group.append({'number':row.episode,'season':row.season,'url':CVH_API+'/video/'+row.video_id,'title':'Серия '+str(row.episode)})
    return [choice(studio,url,identity='cvh:'+parsed['cvh_id']+':'+studio+':'+kind,kind=kind,player='CVH',episodes=entries)
            for (studio,kind),entries in groups.items()]


def group_voices(inspections):
    groups={}
    for source in inspections:
        for voice in source.get('dubs',[]):
            label=voice['name'];kind=voice.get('kind') or translation_kind(label)
            language=voice.get('language') or 'und'
            name_key=normalized_studio(label)
            if not voice.get('named',True):name_key=source['url']+voice['url']
            key=(name_key,kind,language)
            identifier=hashlib.sha256(repr(key).encode()).hexdigest()[:24]
            group=groups.setdefault(key,{'id':identifier,'name':label,'kind':kind,'language':language,'variants':[]})
            variant={**voice,'sourceUrl':source['url'],'sourceTitle':source.get('title',''),
                     'provider':source.get('provider','public'),'providerName':source.get('providerName') or source.get('provider','public')}
            variant['id']=hashlib.sha256((variant['sourceUrl']+'|'+voice['url']+'|'+voice['id']).encode()).hexdigest()[:24]
            if not any(v['id']==variant['id'] for v in group['variants']):group['variants'].append(variant)
    return sorted(groups.values(),key=lambda g:(g['kind'],g['name'].casefold()))


def inspect_catalog(original,text,final,http,*,dub_url=None,season=None,provider='public',provider_name=''):
    from site_adapters import player_choices
    from source_parser import parse_page, episode_number
    page=parse_page(text,final)
    pending=[(text,final,None,0)]
    # AnimeGO's public player page, not a fabricated list of N episode URLs.
    if provider=='animego':
        match=re.search(r'-(\d+)/?$',urlsplit(final).path)
        if match:pending.append((None,urljoin(final,'/player/'+match[1]),final,1))
    seen=set();choices=[];episodes=list(page.episodes);seasons=[];diagnostics=[];choice_seen=set()
    while pending and len(seen)<24:
        document,url,referer,depth=pending.pop(0)
        if url in seen:continue
        seen.add(url)
        if '/cdn-iframe/' in url:
            try:
                for item in cvh_choices(url,http):
                    # An exact video endpoint is the selector; each translation has its own IDs.
                    item['url']=item['episodes'][0]['url']
                    if item['id'] not in choice_seen:choices.append(item);choice_seen.add(item['id'])
            except Exception:
                diagnostics.append({'player':'CVH','status':'unavailable'})
            continue
        try:
            if document is None:document,url,_=http.document(url,headers={'Referer':referer} if referer else None)
            current=parse_page(document,url)
        except SourceError:
            diagnostics.append({'player':player_name(url),'status':'unavailable'});continue
        published=animego_episode_pages(document,url)
        buttons=animego_buttons(document,url)
        current_choices,current_seasons=player_choices(document,url)
        seasons.extend(current_seasons)
        if not episodes and current.episodes:episodes=current.episodes
        for item in buttons:
            if item['player'].casefold()=='cvh' or '/cdn-iframe/' in item['url']:
                pending.append((None,item['url'],url,depth+1));continue
            # Resolve each episode's own button at download time; never reuse episode one's stream.
            item['episodes']=[{**entry,'url':relay_url(entry['url'],item),'availability':'check_on_download'} for entry in published]
            if published:item['url']=relay_url(url,item)
            item['referer']=url
            current_choices.append(item)
        for value in current_choices:
            item=value if 'player' in value else choice(value['name'],value['url'],identity=value['id'])
            item.setdefault('referer',url)
            key=(item['url'],item['name'],item.get('kind'))
            if key not in choice_seen:choices.append(item);choice_seen.add(key)
        # Report direct/public single-player variants even when the page has no translation name.
        if not current_choices and not buttons and (current.streams or current.episodes and player_name(url) in {'Kodik','Aniboom','AniLiberty','Animedia','VK Video'}):
            item=choice('',url,episodes=current.episodes or [{'number':episode_number(url) or 1,'url':url}])
            if item['url'] not in choice_seen:choices.append(item);choice_seen.add(item['url'])
        if depth<3:
            for child in current.players[:12]:
                if (urlsplit(child).hostname or '').endswith(('youtube.com','youtu.be','youtube-nocookie.com')):continue
                pending.append((None,child,url,depth+1))
    # A selected variant must still be published by this source, including nested players.
    selected=next((item for item in choices if item['url']==dub_url),None) if dub_url else None
    if dub_url and selected is None:raise SourceError('Выбранная озвучка больше не найдена на странице. Обнови список.')
    if selected:
        episodes=selected.get('episodes') or []
        if not episodes:
            selected_text,selected_final,_=http.document(selected['url'],headers={'Referer':selected.get('referer') or final})
            selected_page=parse_page(selected_text,selected_final)
            episodes=selected_page.episodes
            if not episodes and (selected_page.streams or re.search(r'/video/',urlsplit(selected_final).path)):
                episodes=[{'number':episode_number(selected_final) or 1,'title':'Видео','url':selected_final}]
            _,selected_seasons=player_choices(selected_text,selected_final)
            if selected_seasons:seasons=selected_seasons
    if not episodes and page.streams:episodes=[{'number':episode_number(final) or 1,'url':final}]
    for entry in episodes:
        entry.setdefault('season',season or 1)
    # Preserve distinct translated episode links. Only exact duplicates collapse.
    episodes=list({(e.get('season',1),e['number'],e['url']):e for e in episodes}.values())
    season_values={int(e['number']):e for e in seasons}
    for voice in choices:
        for entry in voice.get('episodes',[]):
            number=entry.get('season')
            if number:season_values.setdefault(number,{'number':number,'name':'Сезон '+str(number),'url':None})
    soup=BeautifulSoup(text,'html.parser')
    ids={}
    for namespace,expression in [('mal',r'myanimelist\.net/anime/(\d+)'),('shikimori',r'shikimori\.(?:one|io|me)/animes/(?:[a-z])?(\d+)')]:
        found={re.search(expression,a.get('href',''))[1] for a in soup.select('a[href]') if re.search(expression,a.get('href',''))}
        if len(found)==1:ids[namespace]=next(iter(found))
    # Shikimori anime IDs use the MAL namespace.
    if ids.get('shikimori') and not ids.get('mal'):ids['mal']=ids['shikimori']
    year=None
    for node in soup.select('[data-year], .year, [itemprop="datePublished"], meta[property="video:release_date"], meta[property="og:release_date"]'):
        value=node.get('data-year') or node.get('content') or node.get_text(' ',strip=True)
        matched=re.search(r'\b((?:19|20)\d{2})\b',value)
        if matched:year=int(matched[1]);break
    releases=[{'date':e.get('datetime'),'label':e.parent.get_text(' ',strip=True)[:180]} for e in soup.select('.episode time[datetime], .release time[datetime], .schedule time[datetime], [data-episode] time[datetime]')][:100]
    return {'provider':provider,'providerName':provider_name,'title':page.title,'url':final,'dubs':choices,
            'seasons':sorted(season_values.values(),key=lambda e:e['number']),'episodes':episodes,'releases':releases,
            'available':bool(episodes or choices),'diagnostics':diagnostics,'ids':ids,'year':year}
