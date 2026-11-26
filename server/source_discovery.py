"""Exact-title search and translation aggregation with bounded, isolated source requests."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import threading
import time
import re
from title_identity import aliases, match_title, normalized
from site_adapters import SITES, search_site, inspect_source
from player_catalog import group_voices
from source_parser import PublicHttp

_cache={};_lock=threading.Lock();_slots=threading.BoundedSemaphore(2)
_progress={}

# Sites left out of the title search, with the reason seen on the server
# (G3 check, 2026-11-26). Their adapters stay; a catalogued page of such a site
# still opens. Re-check before switching one back on.
OFF={
    'sovet':'выключен ранее', 'anilibriafun':'выключен ранее', 'animevosttv':'выключен ранее',
    'animejet':'домен не существует (DNS)', 'animeone':'домен не существует (DNS)',
    'animebesst':'домен указывает на служебный адрес', 'animeon':'HTTP 526 (сертификат сайта)',
    'animego':'HTTP 500 на поиске', 'animebit':'не отвечает', 'animebuff':'не отвечает',
    'animeonline':'не отвечает', 'freeanime':'не отвечает',
    'shiza':'поиск отдаёт главную страницу на любой запрос',
    'anime365':'поиск отдаёт ленту новинок на любой запрос',
    'animelayer':'торрент-трекер: поиск отдаёт ленту раздач, плееров нет',
    'hentasis':'поиск отдаёт главную страницу на любой запрос',
}
# Hentai video sites: searched for adult cards only (a card the client marks
# adult=False never has its title there). Their indexed pages always open.
ADULT={'hentaichan-video','hanime','hanime1','hentaimama','hentaicomua','watchhentai','ohentai','hentasis','hentaihaven','miohentai'}
# Sites that publish no release year, only upload dates (G5): an exact title
# is accepted when the card's year is not later than the series' first upload.
UNDATED={'miohentai'}
# Sites that found the measured cards most often go first: with six workers the
# first playable answer no longer waits behind dead or empty searches.
ORDER=('anilibria','animedia','yummy','animejoy','anidub','anixart','animegoonline','animevost','jutsu','eneyida','uaserials',
       'ohentai','hentaihaven','hanime1','hanime','hentaimama','watchhentai','miohentai','hentaicomua')
LATIN=re.compile(r'[a-z]',re.I);CYRILLIC=re.compile(r'[а-яёіїєґ]',re.I)
# Hentai sites that list Russian or Ukrainian names keep the card's query order.
CYRILLIC_SITES={'hentaichan-video','hentasis','hentaicomua'}
PLACEHOLDERS={'названиеуточняется'}  # Shikimori's «Название уточняется» is not a title.


def _russian_names(mal):
    """Shikimori names of a MAL id (cached catalogue call), waited for briefly."""
    box={}
    def fetch():
        try:
            from metadata_catalog import metadata
            data=metadata('shikimori',identity=str(mal),kind='anime')
            if isinstance(data,dict) and str(data.get('id'))==str(mal):box['data']=data
        except Exception:pass
    thread=threading.Thread(target=fetch,daemon=True,name='discovery-names');thread.start();thread.join(3)
    data=box.get('data') or {}
    names=[data.get('russian'),data.get('name'),*(data.get('english') or []),*(data.get('synonyms') or [])]
    return [v.strip() for v in names if isinstance(v,str) and v.strip()]


def discovery_sites(kind,adult=None,anchored=None):
    """Sites _discover asks for a card, in the order they are queued.

    OFF sites and, for a card marked not adult, hentai sites are skipped unless
    the card has a catalogued page there; an adult card queues hentai sites first."""
    anchored=anchored or {}
    sites=[s for s in SITES if (s.serves(kind) if hasattr(s,'serves') else s.kind==kind=='anime') and s.kind!='manga'
           and (anchored.get(s.id) or s.id not in OFF and not (adult is False and s.id in ADULT))]
    rank=lambda s:(0 if adult is True and s.id in ADULT else 1,adult is not True and s.id in ADULT,ORDER.index(s.id) if s.id in ORDER else len(ORDER))
    return sorted(sites,key=rank)


def undated_match(site,selected,value,evidence):
    """A site without release years (UNDATED): the very same name, and the
    card's year not after the series' first upload (a work cannot be uploaded
    before it is released). A different name, an unknown upload year or a
    card released after the upload stays unconfirmed."""
    upload=value.get('uploadYear')
    try:year=int(str(selected.get('year'))[:4])
    except ValueError:return False
    return site in UNDATED and evidence=='exact_title' and isinstance(upload,int) and year<=upload


def search_card(selected):
    """The card with the names Russian sites list it under.

    Drops Shikimori's placeholder title. An anime card without any Cyrillic
    name (its Shikimori profile did not reach the client) gets its Russian
    name by its MAL id, the client's own source of that name. IDs, kind and
    year stay the card's, so every match keeps the same identity rules."""
    names=[v for v in aliases(selected) if normalized(v) not in PLACEHOLDERS]
    card={**selected,'title':names[0] if names else selected.get('title'),
          'titles':{k:v for k,v in (selected.get('titles') or {}).items() if normalized(v) not in PLACEHOLDERS} if isinstance(selected.get('titles'),dict) else selected.get('titles'),
          'aliases':names}
    mal=(selected.get('ids') or {}).get('mal')
    if selected.get('kind','anime')=='anime' and mal and str(mal).isdigit() and not any(re.search(r'[а-яё]',v,re.I) for v in names):
        extra=[v for v in _russian_names(mal) if normalized(v) not in PLACEHOLDERS]
        russian=next((v for v in extra if re.search(r'[а-яё]',v,re.I)),'')
        if russian:card={**card,'title':russian,'aliases':list(dict.fromkeys([*names,*extra]))[:30]}
    return card

def voice_suggestions(query='',limit=30,language='all'):
    """Labels observed on real Russian source/player pages; never a studio list.

    An unknown language stays unknown in the response, rather than fabricating
    language verification for a Russian provider's player label.
    """
    language_filter=language if language in {'all','ru','uk'} else 'all'
    query=' '.join(str(query).casefold().split())[:80];now=time.monotonic();groups={}
    with _lock:
        snapshots=[entry[1] for entry in _cache.values() if entry[0]>now]
    for snapshot in snapshots:
        for voice in snapshot.get('voices',[]):
            name=voice.get('name','');kind=voice.get('kind','');language=voice.get('language','und')
            if not name or kind in {'sub','subs','subtitle','subtitles'} or language not in ({'ru','und','uk'} if language_filter=='all' else {'uk'} if language_filter=='uk' else {'ru','und'}) or query not in name.casefold():continue
            variants=[v for v in voice.get('variants',[]) if v.get('named',True) and v.get('sourceUrl')]
            if not variants:continue
            key=(name.casefold(),kind,language)
            group=groups.setdefault(key,{'id':voice['id'],'name':name,'kind':kind,'language':language,'observed':True,'providers':set(),'sourceCount':0})
            group['providers'].update(v.get('providerName') or v.get('provider','') for v in variants)
            group['sourceCount']+=len(variants)
    values=[{**v,'providers':sorted(v['providers'])} for v in groups.values()]
    values.sort(key=lambda v:(not v['name'].casefold().startswith(query),v['name'].casefold()))
    return {'query':query,'voices':values[:max(1,min(int(limit),50))],'total':len(values),'observedOnly':True}


def indexed_sources(selected):
    """provider -> index page URLs of the card's catalogued video sources.

    A catalogue row of HanimeTV, Hanime1, HentaiMama, WatchHentai, OHentai or HentaiHaven
    is that site's own series page: it is inspected directly instead of being
    re-found by title search (the sites' search omits years and spells titles
    differently, so the exact-title rule turned those cards down)."""
    from dynamic_video_sources import catalogued_source
    rows=[(selected.get('provider'),selected.get('sourceURL'))]
    extra=selected.get('indexedSources')
    if isinstance(extra,list):rows.extend((v.get('provider'),v.get('url')) for v in extra[:8] if isinstance(v,dict))
    found={}
    for provider,url in rows:
        if url:=catalogued_source(provider,url):
            if url not in found.setdefault(provider,[]):found[provider].append(url)
    return found

def index_anchors(selected):
    """provider -> series pages of the card's work found in the index by name.

    A metadata card (AniList …) and the catalogued site's row of the same work
    are separate works in the index (the sites have no MAL/AniList IDs). The
    row is accepted by the live search's own rule: match_title plus the year
    rule of _discover (a card's year must be stated by the row). Read-only;
    {} when the index cannot be read."""
    from dynamic_video_sources import catalogued_source
    from content_names import matches
    if selected.get('kind', 'anime') != 'anime':return {}
    found={}
    # The neighbouring-year rule of the live anime search (exact name only).
    for row in matches(selected,'anime',year_required=True,year_slack=1):
        if url:=catalogued_source(row.get('provider'),row.get('sourceUrl') or row.get('url')):
            if url not in found.setdefault(row['provider'],[]):found[row['provider']].append(url)
    return {provider:urls[:4] for provider,urls in found.items() if urls}

def _key(selected):
    anchors=tuple(sorted((p,tuple(u)) for p,u in indexed_sources(selected).items()))
    return repr((selected.get('ids'),aliases(selected),selected.get('startDate') or selected.get('year'),selected.get('kind'))+((anchors,) if anchors else ()))

def _discover(selected,*,refresh=False,continuing=False):
    if not aliases(selected):raise ValueError('Выбери конкретный тайтл из каталога.')
    key=_key(selected)
    with _lock:
        hit=_cache.get(key)
        if not refresh and hit and hit[0]>time.monotonic():return hit[1]
        if refresh and not continuing:
            hit=None
            for stale in [k for k in _progress if k[0]==key]:_progress.pop(stale,None)
        known={s['url']:s for s in hit[1]['sources'] if s.get('complete',True)} if hit and hit[0]>time.monotonic() else {}
    if not _slots.acquire(blocking=False):raise ValueError('Поиск источников уже выполняется. Повтори через несколько секунд.')
    try:
        card=search_card(selected)
        names=aliases(card)
        # Anime sites date a season by its last airing year or another
        # catalogue's premiere; film catalogues publish the release year, and
        # same-name films a year apart (remakes, TV versions) are common.
        slack=1 if selected.get('kind','anime')=='anime' else 0
        same=lambda candidate:match_title(card,candidate,year_slack=slack)
        # Search engines rarely match a catalogue's full localized film title.
        # Broaden the query only; all results still pass exact title/year/ID.
        stems=[v.split(':',1)[0].split('. Фильм',1)[0].strip() for v in names if re.search(r'[а-яё]',v,re.I)]
        keywords=[v.split()[-1].strip(' .:!?') for v in names if ':' in v and re.search(r'[а-яё]',v,re.I)]
        queries=list(dict.fromkeys([*names[:2],*[v for v in keywords if len(v)>=4],*[v for v in stems if len(v)>=4]]))[:4]
        anchored=indexed_sources(selected)
        for provider,urls in index_anchors(selected).items():
            anchored[provider]=list(dict.fromkeys([*anchored.get(provider,[]),*urls]))[:8]
        def work(site):
            http=PublicHttp(timeout=(2,4),deadline=time.monotonic()+15)
            try:
                matches=[{**s,'kind':selected.get('kind','anime'),'matchEvidence':s.get('matchEvidence','exact_title')} for s in (hit[1]['sources'] if hit and hit[0]>time.monotonic() else []) if s.get('provider')==site.id]
                status='empty';message='Точное совпадение тайтла и сезона не найдено.'
                site_queries = [] if anchored.get(site.id) else queries
                for url in anchored.get(site.id,[]):
                    if not any(m['url']==url for m in matches):
                        matches.insert(0,{'url':url,'title':selected.get('title',''),'provider':site.id,'matchEvidence':'catalogue_source'})
                if site.id in ADULT-CYRILLIC_SITES and site_queries:
                    # These hentai sites list English/romaji names: a Russian name
                    # from Shikimori would spend the first request for nothing.
                    latin = [v for v in names if LATIN.search(v) and not CYRILLIC.search(v)]
                    site_queries = list(dict.fromkeys([*latin[:3], *[v for v in queries if not CYRILLIC.search(v)], *queries]))[:4]
                if site.id in {'eneyida', 'uaserials'} and site_queries:
                    # These catalogues index original and Ukrainian names.
                    localized = [v for v in names if re.search(r'[іїєґ]', v, re.I)]
                    original = [v for v in names if re.search(r'[a-z]', v, re.I) and not re.search(r'[а-яіїєґ]', v, re.I)]
                    site_queries = list(dict.fromkeys([*localized[:1], *original[:2], *queries]))[:4]
                for query in site_queries:
                    response=search_site(site,query,http=http)
                    status=response['status'];message=response.get('message',message)
                    for candidate in response['results']:
                        accepted,evidence=same(candidate)
                        if accepted and not any(m['url']==candidate['url'] for m in matches):
                            matches.append({**candidate,'matchEvidence':evidence})
                    if matches:break  # Leave the request budget for its players.
                inspected=[];provider_pending=False
                for candidate in matches:
                    if candidate['url'] not in known and http.deadline and time.monotonic()>=http.deadline:
                        provider_pending=True;break
                    try:
                        if candidate['url'] in known:value=known[candidate['url']]
                        else:
                            progress_key=(key,candidate['url'])
                            with _lock:
                                for stale in [k for k,v in _progress.items() if v['expires']<time.monotonic()]:_progress.pop(stale,None)
                                if progress_key not in _progress:
                                    if len(_progress)>=64:_progress.pop(next(iter(_progress)))
                                    _progress[progress_key]={'state':{},'lock':threading.Lock(),'expires':time.monotonic()+300}
                                progress=_progress[progress_key]
                            with progress['lock']:
                                value=inspect_source(candidate['url'],http=http,kind=selected.get('kind','anime'),state=progress['state'])
                                progress['expires']=time.monotonic()+300
                            if not value.get('pending'):
                                with _lock:_progress.pop(progress_key,None)
                        if candidate['matchEvidence']=='catalogue_source':
                            # The card is this page's own index row: its identity needs no title search.
                            inspected.append({**value,'title':candidate['title'] or value.get('title',''),'providerName':site.name,'matchEvidence':'catalogue_source'})
                            continue
                        verified={**candidate,'ids':value.get('ids') or candidate.get('ids') or {},'year':value.get('year') or candidate.get('year')}
                        accepted,evidence=same(verified)
                        if not accepted:continue
                        if selected.get('year') and not verified.get('year') and evidence!='external_id':
                            if not undated_match(site.id,selected,value,evidence):
                                status='unverified';message='Название совпадает, но год или внешний ID не подтверждён страницей.';continue
                            candidate={**candidate,'matchEvidence':'exact_title_undated'}
                        # HTML title must not contradict the selected identity. Search snippets can be stale.
                        page_title=re.split(r'\s+(?:смотреть|watch)\b|\s+[|–—]\s+',value.get('title',''),flags=re.I)[0]
                        detail = {'title': page_title, 'aliases': value.get('aliases', []),
                                  'ids': value.get('ids') or {}, 'kind': selected.get('kind', 'anime')}
                        if page_title and not same(detail)[0]:
                            # Some older Ukrainian pages publish only their localized
                            # heading. The card has already passed the identity check.
                            if value.get('aliases') or site.id not in {'eneyida', 'uaserials'} or not re.search(r'[іїєґ]', page_title, re.I):
                                continue
                        inspected.append({**value,'title':candidate['title'],'providerName':site.name,'matchEvidence':candidate['matchEvidence']})
                    except Exception:
                        status='unavailable';message='Страница найдена, плееры временно не ответили.'
                count=sum(len(v.get('dubs',[])) for v in inspected)
                provider_status='ok' if count else 'no_players' if inspected else status if status in {'unavailable','unverified'} else 'no_match'
                if count:message='Найдено вариантов плееров: '+str(count)+'. Доступность серии проверяется перед просмотром.'
                elif inspected:message='Тайтл найден, но доступные плееры не подтверждены.'
                return {'provider':site.id,'name':site.name,'status':provider_status,'pending':provider_pending,'complete':not provider_pending and all(v.get('complete',True) for v in inspected) and status!='unavailable','message':message,'sources':inspected}
            except Exception:
                return {'provider':site.id,'name':site.name,'status':'unavailable','message':'Источник не ответил или изменил разметку.','sources':[]}
            finally:http.close()
        wanted=selected.get('kind','anime')
        sites=discovery_sites(wanted,selected.get('adult'),anchored)
        providers=[]
        def snapshot(unfinished=False):
            sources=[s for p in providers for s in p.get('sources',[])]
            for previous in known.values():
                if not any(s['url']==previous['url'] for s in sources):sources.append(previous)
            return {'title':selected,'voices':group_voices(sources),'sources':sources,
                'providers':[{k:v for k,v in p.items() if k!='sources'} for p in providers],
                'progress':len(providers)+sum(s.get('scannedPages',1) for s in sources),
                'pending':unfinished or any(s.get('pending') for s in sources) or any(p.get('pending') for p in providers),
                'complete':not unfinished and all(p.get('complete',False) for p in providers),'checkedAt':int(time.time())}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures=[]
            if selected.get('kind','anime') in {'anime','movie'} and str((selected.get('ids') or {}).get('mal'))=='57555':
                from yummy_anime_source import discover_reze
                futures.append(pool.submit(discover_reze))
            from kinobox_source import discover as kinobox_discover
            # Sites with an indexed page of this work answer with one inspection:
            # they go first instead of queueing behind searches of other sites.
            first=[pool.submit(work,site) for site in sites if anchored.get(site.id)]
            # Kodik plays from the players the sites embed (player_catalog); the
            # owner-token Kodik API is not part of discovery.
            futures.extend([*first,pool.submit(kinobox_discover,card),*[pool.submit(work,site) for site in sites if not anchored.get(site.id)]])
            for future in as_completed(futures):
                providers.append(future.result());result=snapshot(len(providers)<len(futures))
                with _lock:_cache[key]=(time.monotonic()+(300 if result['sources'] else 30),result)
                with _jobs_lock:job=_jobs.get(key)
                if job and result['voices']:job['changed'].set()
        result=snapshot()
        with _lock:
            if len(_cache)>=80:_cache.pop(next(iter(_cache)))
            _cache[key]=(time.monotonic()+(300 if result['sources'] else 30),result)
        from source_index import save
        save(key,result)
        return result
    finally:_slots.release()


_jobs={};_jobs_lock=threading.RLock()

def discover(selected,*,refresh=False,continuing=False):
    source_url = selected.get('sourceURL')
    if selected.get('provider') == 'hentaichan-video' and isinstance(source_url, str):
        from hentaichan_video import video_page
        if video_page(source_url):
            source = inspect_source(source_url, kind='anime')
            available = bool(source['episodes'])
            return {'title': selected, 'sources': [source], 'voices': group_voices([source]),
                    'providers': [{'provider': source['provider'], 'name': source['providerName'],
                                   'status': 'ok' if available else 'no_players', 'complete': True}],
                    'progress': 1, 'pending': False, 'complete': True, 'checkedAt': int(time.time())}
    if not aliases(selected):raise ValueError('Выбери конкретный тайтл из каталога.')
    key=_key(selected)
    with _lock:hit=_cache.get(key)
    with _jobs_lock:
        job=_jobs.get(key)
        if job is None and (not refresh or continuing) and hit and hit[0]>time.monotonic() and not hit[1].get('pending'):return hit[1]
        if job is None:
            if len(_jobs)>=2:
                if hit:return {**hit[1],'pending':True,'complete':False,'refreshing':True}
                raise ValueError('Поиск других тайтлов уже выполняется. Повтори через несколько секунд.')
            if not hit and not refresh:
                from source_index import load
                old=load(key)
                if old:
                    hit=(time.monotonic()+30,{**old,'title':selected})
                    with _lock:_cache[key]=hit
            job=_jobs[key]={'changed':threading.Event(),'done':threading.Event()}
            def run():
                try:_discover(selected,refresh=True,continuing=continuing or bool(hit) and not refresh)
                except Exception:job['error']=True
                finally:
                    job['done'].set();job['changed'].set()
                    with _jobs_lock:_jobs.pop(key,None)
            threading.Thread(target=run,daemon=True,name='voice-discovery').start()
    if hit and hit[1].get('voices'):return {**hit[1],'pending':True,'complete':False,'refreshing':True}
    # Fast providers can unlock playback before slow providers finish. Subsequent
    # polling joins the same job; it never starts a second catalogue crawl.
    job['changed'].wait(1.5)
    with _lock:current=_cache.get(key)
    if current:return {**current[1],'refreshing':not job['done'].is_set()}
    if job.get('error'):raise ValueError('Источники пока не ответили. Повтори поиск.')
    return {'title':selected,'voices':[],'sources':[],'providers':[],'progress':0,'pending':not job['done'].is_set(),'complete':job['done'].is_set(),'checkedAt':int(time.time())}
