"""Metadata-only global manga search: one SQLite queue, four shared workers.

No page bytes, credentials or account library data are stored here. Upstream
search responses are candidates, not claims that chapters are readable.
"""
from pathlib import Path
from urllib.parse import urljoin
import hashlib,json,os,re,secrets,sqlite3,threading,time,unicodedata
from source_parser import SourceAccessError,SourceError,SourceTemporaryError,public_url
import suwayomi_bridge as bridge

LANGUAGES={'all',*bridge.LANGUAGES}
DISCOVERY_VERSION=4
# A source that failed its search twice in a row (challenge, login wall,
# timeout, DNS, HTTP 5xx) is left out of ordinary searches for a growing
# pause. It stays installed and listed with the reason; «Повторить поиск»
# (refresh) or choosing it explicitly asks it at once. One failure never
# removes a source: an empty answer or a single outage is not evidence.
SEARCH_BACKOFF=(3600,6*3600,24*3600)
NATIVE_SOURCES={'MangaLib':1,'HentaiLib':4,'SlashLib':2,'MangaDex':0,'Senkognito':None}
def language_queries(values,language):
    pattern={'ru':r'[а-яё]','uk':r'[а-яіїєґ]','en':r'[a-z]','ja':r'[ぁ-ヿ一-鿿]','ko':r'[가-힣]','all':r'.'}[language]
    # Native title first; Latin title/romanization is the useful second query
    # on Japanese/Korean catalogues, not the first Russian display-name alias.
    def rank(value):
        if re.search(pattern,value,re.I):return 0
        return 1 if re.search(r'[a-z]',value,re.I) else 2
    return sorted(dict.fromkeys(values),key=rank)[:2]
def public_aliases(row):
    values=[row.get('title'),*(row.get('aliases') or [])]
    text=str(row.get('description') or '')[:20000]
    match=re.search(r'(?:Альтернативные названия|Alternative (?:names|titles))\*?\*?\s*:\s*(.*)',text,re.I|re.S)
    if match:
        for line in match[1].splitlines()[:30]:
            if re.match(r'^\s*[-•]\s+',line):values.append(re.sub(r'^\s*[-•]\s+','',line).strip())
            elif line.strip():break
    return list(dict.fromkeys(v.strip()[:300] for v in values if isinstance(v,str) and len(v.strip())>1))[:30]

def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC',value).casefold().split())

def installed_sources():
    from manga_hentaichan import SOURCE
    from manga_hentaichan_cc import SOURCE as CHAN_CC
    from manga_hitomi import SOURCES as HITOMI
    return [*bridge.sources(),dict(SOURCE),dict(CHAN_CC),*(dict(s) for s in HITOMI)]

def source_list(language='all',query=''):
    if language not in LANGUAGES:raise ValueError('Выбери язык источников.')
    query=normalize(query)[:80]
    rows=[{'id':str(s['id']),'name':s['name'],'language':s['lang'],'adult':bool(s.get('isNsfw'))}
          for s in installed_sources() if s.get('lang') in bridge.LANGUAGES and (language=='all' or s['lang']==language)]
    rows.sort(key=lambda s:(s['language'],s['name'].casefold(),s['id']))
    from manga_source_health import states,blocked
    health=states();usable=[s for s in rows if not blocked(s['id'],health)]
    return {'sources':[s for s in usable if query in normalize(s['name'])],'total':len(usable),'unavailableCount':len(rows)-len(usable)}

def result_row(source,row):
    identity=row.get('id');title=row.get('title')
    if isinstance(identity,bool) or not isinstance(identity,int) or not 0<identity<10**10 or not isinstance(title,str) or not title.strip():return None
    canonical=cover=''
    try:canonical=public_url(row.get('realUrl') or urljoin(source.get('baseUrl',''),row.get('url','')),resolve_dns=False)
    except (SourceError,TypeError,ValueError):pass
    # Only genuinely public thumbnail metadata is exposed. Internal Suwayomi
    # thumbnails need Basic auth and are never presented as public image URLs.
    thumb=row.get('thumbnailUrl') or ''
    if isinstance(thumb,str) and thumb.startswith('https://'):
        try:cover=public_url(thumb,resolve_dns=False)
        except SourceError:pass
    language=source['lang'];sid=str(source['id'])
    return {'id':f'suwayomi:{sid}:{identity}','kind':'manga','title':title.strip()[:500],'aliases':public_aliases(row),
            'provider':'suwayomi:'+sid,'providerName':source['name'],'sourceId':sid,'sourceUrl':canonical,
            'url':bridge.reference(identity),'sourceURL':bridge.reference(identity),'sourceOnly':True,
            'language':language,'cover':cover,'format':'manhwa' if language=='ko' else 'manga','ids':{},'genres':[],'tags':[],
            'adult':bool(source.get('isNsfw'))}

def native_search_source(source,query):
    from title_identity import aliases,match_title,normalized
    from manga_catalog_adapters import lib_search,dex_search
    from source_parser import PublicHttp
    http=PublicHttp(timeout=(3,6),deadline=time.monotonic()+18)
    selected=source.get('_title') or source.get('_alias_title');found={}
    try:
        terms=source.get('_queries',[query])
        for term in terms:
            if source['name']=='MangaDex':
                rows=dex_search(term,source['lang'],http)
            elif source['name']=='Senkognito':
                from manga_senkognito import search
                rows=search(term,http)
            else:
                rows=lib_search(term,http,NATIVE_SOURCES[source['name']],details=True)
            for row in rows:
                candidate={**row,'aliases':row.get('identityTitles') or row.get('aliases') or [row['title']]}
                if source['name']=='Senkognito' and not selected and not any(normalized(term) in normalized(name) for name in candidate['aliases']):continue
                matched=not selected or match_title(selected,candidate)[0]
                # A matching publication year permits the documented English alias,
                # while unrelated fan works with a franchise alias remain rejected.
                if selected and not matched and selected.get('year') and selected['year']==row.get('year'):matched=match_title(selected,row)[0]
                if not matched:continue
                if selected:row={**row,'aliases':list(dict.fromkeys([*row.get('aliases',[]),selected['title']]))}
                found[row['url']]=row
            if found:break
        if not found and source['name']=='MangaDex' and not selected and re.search(r'[а-яё]',query,re.I):
            # Resolve public title aliases even with MangaDex-only filters. The
            # result remains a MangaDex result, never a replacement provider.
            for site_id in [4,1]:
                for identity in lib_search(query,http,site_id,details=True):
                    if normalized(query) not in {normalized(v) for v in identity.get('identityTitles',[])}:continue
                    for term in language_queries(aliases(identity),'en'):
                        if normalized(term)==normalized(query):continue
                        for row in dex_search(term,source['lang'],http):
                            if match_title(identity,row)[0]:found[row['url']]={**row,'aliases':list(dict.fromkeys([*row.get('aliases',[]),*aliases(identity)]))}
                    if found:break
                if found:break
    finally:http.close()
    sid=str(source['id'])
    return [{**row,'id':'suwayomi:'+sid+':native:'+hashlib.sha256(row['url'].encode()).hexdigest()[:20],
             'providerName':source['name'],'sourceId':sid,'sourceUrl':row['url'],'sourceURL':row['url'],
             'sourceOnly':True,'ids':{},'genres':[],'tags':[]} for row in found.values()][:40]

def search_source(source,query):
    if source.get('name') in {'HentaiChan','HenChan','HentaiChan.cc','Hitomi'}:
        from title_identity import match_title
        from source_parser import PublicHttp
        from functools import partial
        if source['name'] in {'HentaiChan','HenChan'}:
            from manga_hentaichan import search
            if source['name']=='HenChan':search=partial(search,root='https://xxl.hentaichan.live')
        elif source['name']=='HentaiChan.cc':
            from manga_hentaichan_cc import search
        else:
            from manga_hitomi import search as hitomi_search
            search=partial(hitomi_search,language=source['lang'])
        http=PublicHttp(timeout=(3,18),deadline=time.monotonic()+38)
        try:
            found={}
            for term in source.get('_queries',[query]):
                for row in search(term,http):
                    selected=source.get('_title') or source.get('_alias_title')
                    if selected and not match_title(selected,row)[0]:continue
                    if source['name'] in {'HentaiChan','HenChan'} and not selected and not any(normalize(term) in normalize(v) for v in row['aliases']):continue
                    if source['name']=='HenChan':
                        row={**row,'id':'henchan:'+row['id'].split(':')[-1],'sourceId':str(source['id']),'providerName':'HenChan'}
                    found[row['id']]=row
                if found:break
            return list(found.values())
        finally:http.close()
    if source.get('name') in NATIVE_SOURCES:
        try:return native_search_source(source,query)
        except SourceError:
            # The installed extension can reach the same catalogue when the
            # public API redirects to an edge challenge or its alias API fails.
            if source['name'] not in {'MangaDex','SlashLib','Senkognito'}:raise
    client=bridge.Client()
    try:
        from title_identity import match_title
        found={};selected=source.get('_title') or source.get('_alias_title')
        responded=False;query_error=None
        for term in source.get('_queries',[query]):
            try:data=client.get('/source/'+str(source['id'])+'/search',{'searchTerm':term,'pageNum':1},timeout=12)
            except bridge.BridgeError as error:
                if error.code!='query':raise
                query_error=error;continue
            responded=True
            rows=data.get('mangaList',[])
            if not isinstance(rows,list):raise ValueError('Invalid source result')
            for row in rows[:40]:
                if isinstance(row,dict) and (value:=result_row(source,row)):
                    if selected:
                        if not match_title(selected,value)[0]:continue
                        value['aliases']=list(dict.fromkeys([*value['aliases'],selected['title']]))
                    elif not any(normalize(term) in normalize(v) for v in value['aliases']):continue
                    if source.get('name')=='Manga Ball':
                        languages=bridge.mangaball_languages(client,row['id'])
                        if languages is not None and source['lang'] not in languages:continue
                    found[value['id']]=value
            if found:break
        if not responded and query_error:raise query_error
        return list(found.values())
    except SourceError as error:
        # A failing extension must not make its still-readable public HTML
        # catalogue disappear. Reuse only the adapter for the SAME source host.
        from manga_sources import MANGACHAN_HEADERS,site_for,search_url,parse_search
        from source_parser import PublicHttp
        site=site_for(source.get('baseUrl',''))
        if not site or site.family not in {'pill','katana','poisk','hub','chan','buff'}:
            # Suwayomi reports the origin's 403/404 as a bare HTTP 500.
            if isinstance(error,bridge.BridgeError) and error.code=='upstream' and 'http 500' in str(error).casefold():
                raise bridge.origin_block(source.get('baseUrl')) or error
            raise
        http=PublicHttp(timeout=(3,6),deadline=time.monotonic()+12)
        try:
            rows=[]
            for term in source.get('_queries',[query]):
                options={'headers':MANGACHAN_HEADERS} if site.family=='chan' else {}
                text,final,_=http.document(search_url(site,term),**options)
                if site_for(final)!=site:raise SourceError('Источник перенаправил поиск на другой сайт.')
                for value in parse_search(text,final,site):
                    if selected and not match_title(selected,value)[0]:continue
                    if not selected and not any(normalize(term) in normalize(v) for v in value.get('aliases',[value['title']])):continue
                    rows.append({**value,'id':'suwayomi:'+str(source['id'])+':native:'+hashlib.sha256(value['url'].encode()).hexdigest()[:20],'sourceId':str(source['id']),'sourceUrl':value['url'],'sourceURL':value['url'],'sourceOnly':True,'ids':{},'genres':[],'tags':[]})
                if rows:break
            return rows
        finally:http.close()
    finally:client.close()

class SearchLimit(ValueError):pass
class SearchMissing(LookupError):pass

class Discovery:
    def __init__(self,directory,*,workers=4,cache_ttl=900,max_jobs=8,per_owner=2,fetch=None,clock=time.time,start_workers=True):
        self.path=Path(directory)/'manga-discovery.sqlite';self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db=sqlite3.connect(self.path,check_same_thread=False);self.path.chmod(0o600)
        self.db.row_factory=sqlite3.Row;self.lock=threading.RLock();self.condition=threading.Condition(self.lock)
        self.clock=clock;self.cache_ttl=cache_ttl;self.max_jobs=max_jobs;self.per_owner=per_owner
        self.fetch=fetch or search_source;self.stopping=False;self.threads=[]
        with self.db:
            self.db.executescript('''
              PRAGMA journal_mode=DELETE;
              CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,owner TEXT NOT NULL,signature TEXT NOT NULL,
                query TEXT NOT NULL,language TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,expires REAL NOT NULL,dispatched REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS jobs_owner_signature ON jobs(owner,signature,state,expires);
              CREATE TABLE IF NOT EXISTS work(job TEXT NOT NULL,source_id TEXT NOT NULL,source TEXT NOT NULL,state TEXT NOT NULL,
                results TEXT NOT NULL DEFAULT '[]',cached INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(job,source_id));
              CREATE INDEX IF NOT EXISTS work_queue ON work(state,job);
              CREATE TABLE IF NOT EXISTS work_diagnostics(job TEXT NOT NULL,source_id TEXT NOT NULL,
                details TEXT NOT NULL,PRIMARY KEY(job,source_id));
              CREATE TABLE IF NOT EXISTS query_cache(query TEXT NOT NULL,source_id TEXT NOT NULL,results TEXT NOT NULL,expires REAL NOT NULL,
                PRIMARY KEY(query,source_id));
              CREATE TABLE IF NOT EXISTS titles(id TEXT PRIMARY KEY,source_id TEXT NOT NULL,language TEXT NOT NULL,title_norm TEXT NOT NULL,
                metadata TEXT NOT NULL,updated REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS titles_source_name ON titles(source_id,title_norm);
              CREATE INDEX IF NOT EXISTS titles_language_name ON titles(language,title_norm);
              CREATE TABLE IF NOT EXISTS reachability(source_id TEXT PRIMARY KEY,name TEXT NOT NULL,language TEXT NOT NULL,
                failures INTEGER NOT NULL,code TEXT NOT NULL,message TEXT NOT NULL,last_ok REAL NOT NULL,last_fail REAL NOT NULL,skip_until REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS network_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            ''')
            if self.db.execute('PRAGMA user_version').fetchone()[0]<1:
                stale=[];sources=set()
                for row in self.db.execute('SELECT id,source_id,metadata FROM titles'):
                    value=json.loads(row['metadata'])
                    if value.get('provider')=='mangalib' and not value.get('identityTitles'):
                        stale.append((row['id'],));sources.add(row['source_id'])
                self.db.executemany('DELETE FROM titles WHERE id=?',stale)
                self.db.executemany('DELETE FROM query_cache WHERE source_id=?',[(sid,) for sid in sources])
                self.db.executemany("UPDATE jobs SET state='interrupted' WHERE id IN (SELECT job FROM work WHERE source_id=?)",[(sid,) for sid in sources])
                self.db.execute('PRAGMA user_version=1')
            if self.db.execute('PRAGMA user_version').fetchone()[0]<2:
                # Drop only the old, unverified multilingual Manga Ball results.
                # Reading URLs and cached pages belong to Suwayomi and stay intact.
                stale=[];sources=set()
                for row in self.db.execute('SELECT id,source_id,metadata FROM titles'):
                    if json.loads(row['metadata']).get('providerName')=='Manga Ball':
                        stale.append((row['id'],));sources.add(row['source_id'])
                for row in self.db.execute('SELECT source_id,source FROM work'):
                    if json.loads(row['source']).get('name')=='Manga Ball':sources.add(row['source_id'])
                self.db.executemany('DELETE FROM titles WHERE id=?',stale)
                self.db.executemany('DELETE FROM query_cache WHERE source_id=?',[(sid,) for sid in sources])
                self.db.executemany("UPDATE jobs SET state='interrupted' WHERE id IN (SELECT job FROM work WHERE source_id=?)",[(sid,) for sid in sources])
                self.db.executemany("UPDATE work SET results='[]',state='cancelled' WHERE source_id=?",[(sid,) for sid in sources])
                self.db.execute('PRAGMA user_version=2')
            self.db.execute("UPDATE jobs SET state='interrupted',updated=? WHERE state='running'",(self.clock(),))
            self.db.execute("UPDATE work SET state='cancelled' WHERE state IN ('queued','running')")
        if start_workers:
            for i in range(max(1,min(workers,8))):
                thread=threading.Thread(target=self._worker,daemon=True,name='manga-discovery-'+str(i));self.threads.append(thread);thread.start()

    def _prune(self,now):
        self.db.execute('DELETE FROM work WHERE job IN (SELECT id FROM jobs WHERE expires<?)',(now,))
        self.db.execute('DELETE FROM jobs WHERE expires<?',(now,))
        self.db.execute('DELETE FROM query_cache WHERE expires<?',(now,))
        self.db.execute('DELETE FROM titles WHERE updated<?',(now-7*86400,))
        self.db.execute('DELETE FROM titles WHERE id IN (SELECT id FROM titles ORDER BY updated DESC LIMIT -1 OFFSET 50000)')
        self.db.execute('DELETE FROM query_cache WHERE rowid IN (SELECT rowid FROM query_cache ORDER BY expires DESC LIMIT -1 OFFSET 10000)')
        stale=[r[0] for r in self.db.execute("SELECT id FROM jobs WHERE state!='running' ORDER BY updated DESC LIMIT -1 OFFSET 32")]
        for identity in stale:
            self.db.execute('DELETE FROM work WHERE job=?',(identity,));self.db.execute('DELETE FROM jobs WHERE id=?',(identity,))
        self.db.execute('DELETE FROM work_diagnostics WHERE job NOT IN (SELECT id FROM jobs)')

    def start(self,owner,query,language='all',source_ids=None,refresh=False,title=None):
        if not isinstance(query,str) or not 2<=len(query.strip())<=160 or any(unicodedata.category(c)=='Cc' for c in query):raise ValueError('Укажи запрос от 2 до 160 символов.')
        query=' '.join(query.split());key=normalize(query)
        from title_identity import aliases
        if title is not None and (not isinstance(title,dict) or title.get('kind')!='manga' or not aliases(title) or len(json.dumps(title).encode())>50000):raise ValueError('Выбери конкретную мангу из каталога.')
        if language not in LANGUAGES:raise ValueError('Выбери язык источников.')
        if source_ids is not None and (not isinstance(source_ids,list) or not 1<=len(source_ids)<=1000 or any(not isinstance(v,str) or not re.fullmatch(r'[1-9][0-9]{0,19}',v) for v in source_ids)):raise ValueError('Выбери хотя бы один установленный источник.')
        # Persist only public source identity, never an upstream response's
        # optional preference/authentication fields.
        active=[{k:s.get(k) for k in ('id','name','lang','baseUrl','isNsfw')} for s in installed_sources() if s.get('lang') in bridge.LANGUAGES]
        installed={str(s['id']) for s in active}
        if source_ids and any(v not in installed for v in source_ids):raise ValueError('Выбранный источник не установлен. Обнови каталог источников.')
        selected=list({str(s['id']):s for s in active if (language=='all' or s['lang']==language) and (not source_ids or str(s['id']) in source_ids)}.values())
        with self.condition,self.db:self._sync_network(active)
        from manga_network_routes import configuration,routed
        routes=configuration()
        for source in selected:
            if routed(source.get('baseUrl'),routes):source['_routeRevision']=routes['revision']
        from manga_source_health import states,blocked
        health=states()
        if not refresh and not source_ids:selected=[s for s in selected if not blocked(s['id'],health)]
        else:
            for source in selected:source['_retryHealth']=True
        preferred='uk' if re.search(r'[іїєґ]',query,re.I) else 'ru' if re.search(r'[а-яё]',query,re.I) else 'ko' if re.search(r'[가-힣]',query) else 'ja' if re.search(r'[ぁ-ヿ一-鿿]',query) else 'en'
        selected.sort(key=lambda s:(s['lang']!=preferred,s['lang'],s['name'].casefold(),str(s['id'])))
        if title:
            # Use the selected title's own aliases in each source's language.
            # Searching a romanized name alone misses Russian, Japanese and Korean editions.
            clean_title={k:title.get(k) for k in ('kind','title','titles','aliases','ids','year')}
            for source in selected:
                source['_queries']=language_queries(aliases(title),source['lang'])
                source['_title']=clean_title
        signature=hashlib.sha256(json.dumps([DISCOVERY_VERSION,key,language,[str(s['id']) for s in selected],title and aliases(title),routes.get('revision','direct')],ensure_ascii=False).encode()).hexdigest()
        now=self.clock()
        with self.condition,self.db:
            self._prune(now)
            paused={} if refresh or source_ids else {r['source_id']:dict(r) for r in self.db.execute('SELECT * FROM reachability WHERE skip_until>?',(now,))}
            hit=self.db.execute("SELECT id FROM jobs WHERE owner=? AND signature=? AND (state='running' OR state='done' AND updated>? AND ?=0) AND expires>? ORDER BY created DESC LIMIT 1",(owner,signature,now-self.cache_ttl,int(bool(refresh)),now)).fetchone()
            if hit:return self._snapshot(owner,hit['id'])
            if self.db.execute("SELECT count(*) FROM jobs WHERE state='running'").fetchone()[0]>=self.max_jobs or self.db.execute("SELECT count(*) FROM jobs WHERE state='running' AND owner=?",(owner,)).fetchone()[0]>=self.per_owner:raise SearchLimit('Поиск уже выполняется. Дождись результата или останови предыдущий.')
            identity=secrets.token_urlsafe(24)
            self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',(identity,owner,signature,query,language,'running' if selected else 'done',now,now,now+86400,now))
            for source in selected:
                sid=str(source['id']);cache_key=self._cache_key(key,source);hit=None if refresh else self.db.execute('SELECT results FROM query_cache WHERE query=? AND source_id=? AND expires>?',(cache_key,sid,now)).fetchone()
                # A stale metadata index is useful immediately, but is not counted
                # as a fresh provider response and never suppresses its refresh.
                seed=self._indexed(key,sid) if not hit else json.loads(hit['results'])
                pause=paused.get(sid) if not hit else None
                self.db.execute('INSERT INTO work VALUES(?,?,?,?,?,?)',(identity,sid,json.dumps(source,ensure_ascii=False),'done' if hit else 'skipped' if pause else 'queued',json.dumps([{**v,'stale':True} for v in seed] if pause else seed,ensure_ascii=False),int(bool(hit))))
                if pause:
                    until=time.strftime('%d.%m %H:%M',time.gmtime(pause['skip_until']))
                    self.db.execute('INSERT OR REPLACE INTO work_diagnostics VALUES(?,?,?)',(identity,sid,json.dumps({'code':'paused','reason':pause['code'],'failures':pause['failures'],'retryAt':pause['skip_until'],
                        'message':f"Пропущен: {pause['failures']} отказа подряд ({pause['message'].rstrip('.')}). Снова спросим после {until} UTC или сразу по кнопке «Повторить».",'elapsedMs':0},ensure_ascii=False)))
            if selected and self.db.execute("SELECT count(*) FROM work WHERE job=? AND state='queued'",(identity,)).fetchone()[0]==0:self.db.execute("UPDATE jobs SET state='done' WHERE id=?",(identity,))
            self.condition.notify_all()
            return self._snapshot(owner,identity)

    @staticmethod
    def _cache_key(key,source):
        versioned=f'native-v{DISCOVERY_VERSION}:{key}'
        if source.get('_queries'):versioned+='|aliases:'+hashlib.sha256(json.dumps(source['_queries'],ensure_ascii=False).encode()).hexdigest()
        if source.get('_routeRevision'):versioned+='|route:'+source['_routeRevision']
        return versioned if not source.get('_title') else versioned+'|title:'+hashlib.sha256(json.dumps(source['_title'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()

    def _sync_network(self,sources):
        from manga_network_routes import configuration,routed
        routes=configuration();revision=routes.get('revision','direct')
        previous=self.db.execute("SELECT value FROM network_state WHERE key='routes'").fetchone()
        if previous and json.loads(previous[0]).get('revision','direct')==revision:return
        old=json.loads(previous[0]) if previous else {}
        identities=[str(s['id']) for s in sources if routed(s.get('baseUrl'),routes) or routed(s.get('baseUrl'),old)]
        if identities:
            from manga_source_health import reset_failures
            reset_failures(identities)
            self.db.executemany('DELETE FROM reachability WHERE source_id=?',[(sid,) for sid in identities])
            self.db.executemany('DELETE FROM query_cache WHERE source_id=?',[(sid,) for sid in identities])
            self.db.executemany("UPDATE jobs SET state='interrupted' WHERE state='done' AND id IN (SELECT job FROM work WHERE source_id=? AND state IN ('skipped','unavailable'))",[(sid,) for sid in identities])
        self.db.execute("INSERT OR REPLACE INTO network_state VALUES('routes',?)",(json.dumps(routes),))

    def _indexed(self,key,sid):
        # Parameterized escaped LIKE supports raw Japanese/Korean substring
        # matching as well as Latin/Cyrillic prefixes without SQL/FTS syntax.
        escaped=key.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        return [json.loads(r[0]) for r in self.db.execute("SELECT metadata FROM titles WHERE source_id=? AND title_norm LIKE ? ESCAPE '\\' ORDER BY updated DESC LIMIT 40",(sid,'%'+escaped+'%'))]

    def _snapshot(self,owner,identity):
        job=self.db.execute('SELECT * FROM jobs WHERE id=? AND owner=? AND expires>?',(identity,owner,self.clock())).fetchone()
        if not job:raise SearchMissing('Поиск не найден или срок хранения истёк.')
        results={};providers=[];complete=failed=cached=0
        from manga_source_health import states,blocked
        health=states()
        for row in self.db.execute('SELECT w.*,d.details FROM work w LEFT JOIN work_diagnostics d USING(job,source_id) WHERE w.job=? ORDER BY source_id',(identity,)):
            source=json.loads(row['source']);items=json.loads(row['results'])
            if not blocked(row['source_id'],health) or source.get('_retryHealth'):
                for value in items:results[value['id']]=value
            providers.append({'id':row['source_id'],'name':source['name'],'language':source['lang'],'state':row['state'],'count':len(items),'cached':bool(row['cached']),**(json.loads(row['details']) if row['details'] else {})})
            complete+=row['state'] in {'done','unavailable','skipped','cancelled'};failed+=row['state']=='unavailable';cached+=row['cached']
        key=normalize(job['query']);tokens=key.split()
        def rank(value):
            title=normalize(value['title']);return (title!=key,not title.startswith(key),key not in title,-sum(t in title for t in tokens),title,value['id'])
        ordered=sorted(results.values(),key=rank)
        return {'id':identity,'state':job['state'],'query':job['query'],'language':job['language'],
                'progress':{'completed':complete,'total':len(providers),'failed':failed,'cached':cached},
                'results':ordered[:3000],'resultCount':len(ordered),'truncated':len(ordered)>3000,'providers':providers,'updated':job['updated'],'expiresAt':job['expires']}

    def status(self,owner,identity):
        with self.lock:return self._snapshot(owner,identity)

    def cancel(self,owner,identity):
        with self.condition,self.db:
            self._snapshot(owner,identity)
            self.db.execute("UPDATE jobs SET state='cancelled',updated=? WHERE id=? AND state='running'",(self.clock(),identity))
            self.db.execute("UPDATE work SET state='cancelled' WHERE job=? AND state IN ('queued','running')",(identity,))
            self.condition.notify_all();return self._snapshot(owner,identity)

    def _take(self):
        row=self.db.execute("SELECT w.*,j.query,j.owner FROM work w JOIN jobs j ON j.id=w.job WHERE w.state='queued' AND j.state='running' AND NOT EXISTS (SELECT 1 FROM work busy WHERE busy.source_id=w.source_id AND busy.state='running') ORDER BY j.dispatched,j.created,CASE WHEN json_extract(w.source,'$.name') IN ('MangaLib','HentaiLib','MangaDex') THEN 0 ELSE 1 END,w.rowid LIMIT 1").fetchone()
        if row:
            with self.db:
                self.db.execute("UPDATE work SET state='running' WHERE job=? AND source_id=?",(row['job'],row['source_id']))
                self.db.execute('UPDATE jobs SET dispatched=? WHERE id=?',(self.clock(),row['job']))
        return row

    def _expand_aliases(self,job,query,values):
        from title_identity import aliases,normalized
        for value in values:
            canonical=value.get('identityTitles') or [value.get('title','')]
            if normalized(query) not in {normalized(v) for v in canonical}:continue
            names=aliases(value)
            if not any(normalized(v)!=normalized(query) for v in names):continue
            identity={k:value.get(k) for k in ('title','kind','aliases','year','ids','format')}
            for work in self.db.execute('SELECT source_id,source,state FROM work WHERE job=?',(job,)).fetchall():
                source=json.loads(work['source'])
                if source.get('_title') or source.get('_alias_title'):continue
                terms=language_queries(names,source['lang'])
                if terms==source.get('_queries',[query]):continue
                source['_queries']=terms;source['_alias_title']=identity
                self.db.execute('UPDATE work SET source=?,state=? WHERE job=? AND source_id=?',(json.dumps(source,ensure_ascii=False),'running' if work['state']=='running' else 'queued',job,work['source_id']))
            break

    def _worker(self):
        while True:
            with self.condition:
                if self.stopping:return
                row=self._take()
                if row is None:self.condition.wait(timeout=1);continue
            started=time.monotonic();details={}
            try:
                values=self.fetch(json.loads(row['source']),row['query']);state='done'
                if not isinstance(values,list):raise ValueError('Invalid result')
            except bridge.BridgeError as error:
                values=[{**v,'stale':True} for v in json.loads(row['results'])]
                state='skipped' if error.code=='link-required' else 'unavailable'
                details={'code':error.code,'message':str(error)}
            except SourceAccessError:
                values=[{**v,'stale':True} for v in json.loads(row['results'])];state='unavailable'
                details={'code':'restricted','message':'Источник требует вход, проверку браузера или ограничивает доступ.'}
            except SourceTemporaryError as error:
                values=[{**v,'stale':True} for v in json.loads(row['results'])];state='unavailable'
                status = re.fullmatch(r'Источник вернул HTTP (\d{3})\.', str(error))
                details = ({'code': 'upstream', 'message': f'Источник вернул HTTP {status[1]}.'} if status else
                           {'code': 'network', 'message': 'Источник не ответил по сети в пределах лимита.'})
            except SourceError:
                values=[{**v,'stale':True} for v in json.loads(row['results'])];state='unavailable'
                details={'code':'source','message':'Не удалось получить данные публичного каталога.'}
            except Exception:
                values=[{**v,'stale':True} for v in json.loads(row['results'])];state='unavailable'
                details={'code':'format','message':'Расширение вернуло данные в неизвестном формате.'}
            details['elapsedMs']=round((time.monotonic()-started)*1000)
            now=self.clock()
            with self.condition,self.db:
                job=self.db.execute('SELECT state FROM jobs WHERE id=?',(row['job'],)).fetchone()
                if not job or job['state']!='running':continue
                self._expand_aliases(row['job'],row['query'],values)
                latest=self.db.execute('SELECT source FROM work WHERE job=? AND source_id=?',(row['job'],row['source_id'])).fetchone()
                changed=latest and latest['source']!=row['source']
                if changed:
                    from title_identity import match_title
                    expected=json.loads(latest['source']).get('_alias_title')
                    if expected and not any(match_title(expected,v)[0] for v in values):state='queued'
                encoded=json.dumps(values,ensure_ascii=False)
                if state in {'done','unavailable'}:self._reachability(json.loads(row['source']),row['source_id'],state=='done',details,now)
                self.db.execute('UPDATE work SET state=?,results=? WHERE job=? AND source_id=?',(state,encoded,row['job'],row['source_id']))
                if state!='queued':self.db.execute('INSERT OR REPLACE INTO work_diagnostics VALUES(?,?,?)',(row['job'],row['source_id'],json.dumps(details,ensure_ascii=False)))
                # Failed upstream requests are not persisted as successful empty
                # cache entries for other owners or refreshed searches.
                if state=='done':
                    self.db.execute('INSERT OR REPLACE INTO query_cache VALUES(?,?,?,?)',(self._cache_key(normalize(row['query']),json.loads(row['source'])),row['source_id'],encoded,now+self.cache_ttl))
                    for value in values:self.db.execute('INSERT OR REPLACE INTO titles VALUES(?,?,?,?,?,?)',(value['id'],row['source_id'],value['language'],normalize(' '.join(public_aliases(value))),json.dumps(value,ensure_ascii=False),now))
                remaining=self.db.execute("SELECT count(*) FROM work WHERE job=? AND state IN ('queued','running')",(row['job'],)).fetchone()[0]
                self.db.execute('UPDATE jobs SET updated=?,state=? WHERE id=?',(now,'running' if remaining else 'done',row['job']))
                self.condition.notify_all()

    def _reachability(self,source,sid,ok,details,now):
        # A rejected search term says nothing about the source's availability.
        if not ok and details.get('code')=='query':return
        old=self.db.execute('SELECT failures,last_ok FROM reachability WHERE source_id=?',(sid,)).fetchone()
        failures=0 if ok else (old['failures'] if old else 0)+1
        pause=SEARCH_BACKOFF[min(failures-2,len(SEARCH_BACKOFF)-1)] if failures>=2 else 0
        # A regional wall is the origin's own statement, not a flaky outage.
        if not ok and details.get('code')=='region':pause=SEARCH_BACKOFF[-1]
        self.db.execute('INSERT OR REPLACE INTO reachability VALUES(?,?,?,?,?,?,?,?,?)',(sid,str(source.get('name',''))[:120],str(source.get('lang',''))[:8],failures,
            '' if ok else str(details.get('code','source'))[:40],'' if ok else str(details.get('message',''))[:300],now if ok else (old['last_ok'] if old else 0),0 if ok else now,now+pause if pause else 0))

    def reachability(self):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT * FROM reachability WHERE failures>0 ORDER BY language,name')]

    def close(self):
        with self.condition:self.stopping=True;self.condition.notify_all()
        for thread in self.threads:thread.join(timeout=6)
        with self.lock:
            if not any(t.is_alive() for t in self.threads):self.db.close()

_manager=None;_manager_lock=threading.Lock()
def manager():
    global _manager
    with _manager_lock:
        if _manager is None:_manager=Discovery(os.getenv('DATA_DIR','/data'),workers=max(1,min(8,int(os.getenv('MANGA_DISCOVERY_WORKERS','8')))))
        return _manager

def shutdown():
    global _manager
    with _manager_lock:
        if _manager is not None:_manager.close();_manager=None
