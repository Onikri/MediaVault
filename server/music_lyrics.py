"""Authenticated, bounded lyrics relay. Provider secrets never reach the browser."""
import asyncio,contextlib,json,os,sqlite3,time
from pathlib import Path
import httpx
from fastapi import Depends
from pydantic import BaseModel,ConfigDict,Field
from lyric_identity import identity,cache_key,match

MOBILE='https://apic-appmobile.musixmatch.com/ws/1.1/'
OFFICIAL='https://api.musixmatch.com/ws/1.1/'
LRCLIB='https://lrclib.net/api/'
HEADERS={'X-Cookie':'x-mxm-token-guid=','x-mxm-app-version':'10.1.1',
         'X-User-Agent':'Musixmatch/2025120901 CFNetwork/3860.300.31 Darwin/25.2.0','Accept':'application/json'}
DECOY='wob gopini den tefe woxica fero gogoh vudob wiya'

class Upstream(Exception):
    def __init__(self,status):self.status=status

class Query(BaseModel):
    model_config=ConfigDict(extra='forbid')
    titles:list[str]=Field(min_length=1,max_length=8)
    artists:list[str]=Field(min_length=1,max_length=8)
    duration:float=Field(gt=0,le=7200,allow_inf_nan=False)
    rich:bool=True
    refresh:bool=False

class LyricsRelay:
    def __init__(self,directory=None,budget=4,client=None):
        self.directory=Path(directory or os.getenv('LYRICS_CACHE_DIR') or Path(__file__).resolve().parent/'.codex-local'/'lyrics')
        self.budget=budget;self.client=client;self.owns_client=client is None
        self.key=os.getenv('MUSIXMATCH_API_KEY','');self.token='';self.token_expires=0;self.token_retry=0
        self.token_lock=asyncio.Lock();self.slots=asyncio.Semaphore(8);self.http_slots=asyncio.Semaphore(12)
        self.pending={};self.keeper=None

    @contextlib.contextmanager
    def db(self):
        connection=sqlite3.connect(self.directory/'cache.sqlite3',timeout=.2)
        try:
            with connection:yield connection
        finally:connection.close()

    async def start(self):
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        def setup():
            with self.db() as db:
                db.execute('CREATE TABLE IF NOT EXISTS lyrics(k TEXT PRIMARY KEY,payload TEXT,expires REAL)')
                db.execute('CREATE TABLE IF NOT EXISTS token(id INTEGER PRIMARY KEY,value TEXT,expires REAL)')
                row=db.execute('SELECT value,expires FROM token WHERE id=1').fetchone()
            with contextlib.suppress(OSError):os.chmod(self.directory/'cache.sqlite3',0o600)
            return row
        row=await asyncio.to_thread(setup)
        if row and row[1]>time.time():self.token,self.token_expires=row
        if self.client is None:self.client=httpx.AsyncClient(timeout=3,follow_redirects=False,limits=httpx.Limits(max_connections=12,max_keepalive_connections=8))
        if not self.key:self.keeper=asyncio.create_task(self.keep_token())

    async def close(self):
        tasks=[*self.pending.values(),*([self.keeper] if self.keeper else [])]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        self.pending.clear()
        if self.owns_client and self.client:await self.client.aclose()

    async def get_json(self,url,params,headers=None):
        async with self.http_slots:
            async with self.client.stream('GET',url,params=params,headers=headers or {'User-Agent':'MediaVault/1.0 lyrics relay'}) as response:
                if response.status_code==404:return None
                if response.status_code in (401,403):raise Upstream('restricted')
                if response.status_code!=200:raise Upstream('unavailable')
                chunks=[];size=0
                async for chunk in response.aiter_bytes():
                    size+=len(chunk)
                    if size>1500000:raise Upstream('unavailable')
                    chunks.append(chunk)
                return json.loads(b''.join(chunks))

    async def refresh_token(self):
        async with self.token_lock:
            if self.token_expires-time.time()>20 or self.token_retry>time.monotonic():return
            try:
                data=await self.get_json(MOBILE+'token.get',{'app_id':'mac-ios-v2.0'},HEADERS)
                value=((data or {}).get('message',{}).get('body') or {}).get('user_token','')
                if not isinstance(value,str) or not 24<=len(value)<=2048 or len(set(value))<=1:raise Upstream('unavailable')
                self.token=value;self.token_expires=time.time()+55
                def save():
                    with self.db() as db:db.execute('INSERT OR REPLACE INTO token VALUES(1,?,?)',(self.token,self.token_expires))
                await asyncio.to_thread(save)
            except (httpx.HTTPError,Upstream,ValueError,TypeError,sqlite3.Error):self.token_retry=time.monotonic()+15

    async def keep_token(self):
        while True:
            await self.refresh_token()
            await asyncio.sleep(15)

    async def mxm(self,endpoint,params):
        # Cold starts never mint a token on a user's request path.
        if not self.key and (not self.token or self.token_expires<=time.time()):raise Upstream('warming')
        auth={'apikey':self.key} if self.key else {'app_id':'mac-ios-v2.0','usertoken':self.token}
        data=await self.get_json((OFFICIAL if self.key else MOBILE)+endpoint,{**params,**auth},None if self.key else HEADERS)
        if not isinstance(data,dict):raise Upstream('unavailable')
        message=data.get('message') or {};status=(message.get('header') or {}).get('status_code')
        if status==404:return {}
        if status!=200:
            if status==401 and not self.key:self.token_expires=0
            raise Upstream('restricted' if status in (401,402,403) else 'unavailable')
        body=message.get('body') or {}
        if not isinstance(body,dict):raise Upstream('unavailable')
        return body

    async def musixmatch(self,query):
        title=query['titles'][0];artist=next((a for a in query['artists'] if a.isascii()),query['artists'][0])
        params={'q_track':title,'q_artist':artist,'q_duration':round(query['duration']),'f_subtitle_length':round(query['duration']),
                'f_subtitle_length_max_deviation':2,'subtitle_format':'lrc','namespace':'lyrics_richsynched'}
        if self.key:
            track=(await self.mxm('matcher.track.get',params)).get('track') or {};calls={}
        else:
            calls=(await self.mxm('macro.subtitles.get',params)).get('macro_calls') or {}
            track=(((calls.get('matcher.track.get') or {}).get('message') or {}).get('body') or {}).get('track') or {}
        matched=match(query,track.get('track_name'),track.get('artist_name'),track.get('track_length'))
        if not matched:return {'phase':'empty'}
        common={'source':'Musixmatch','url':track.get('track_share_url') if str(track.get('track_share_url','')).startswith('https://www.musixmatch.com/') else 'https://www.musixmatch.com/',
                'identity':{'title':track.get('track_name'),'artist':track.get('artist_name'),'duration':track.get('track_length')},'timingMismatch':matched['timingMismatch']}
        track_id=track.get('track_id')
        if self.key:
            lyrics_body,subtitle_body=await asyncio.gather(self.mxm('track.lyrics.get',{'track_id':track_id}),self.mxm('track.subtitle.get',{'track_id':track_id,'subtitle_format':'lrc'}),return_exceptions=True)
            lyrics=lyrics_body.get('lyrics',{}) if isinstance(lyrics_body,dict) else {}
            sub=subtitle_body.get('subtitle',{}) if isinstance(subtitle_body,dict) else {}
        else:
            lyrics=(((calls.get('track.lyrics.get') or {}).get('message') or {}).get('body') or {}).get('lyrics') or {}
            subs=(((calls.get('track.subtitles.get') or {}).get('message') or {}).get('body') or {}).get('subtitle_list') or []
            sub=(subs[0].get('subtitle') or {}) if isinstance(subs,list) and subs else {}
        if lyrics.get('restricted') or sub.get('restricted'):return {**common,'phase':'restricted'}
        plain=str(lyrics.get('lyrics_body') or '')[:100000]
        if DECOY in plain:raise Upstream('unavailable')
        if lyrics.get('instrumental'):return {**common,'phase':'instrumental'}
        result={**common,'phase':'ready','plainText':plain,'lrc':str(sub.get('subtitle_body') or '')[:300000] if not matched['timingMismatch'] else ''}
        if query.get('rich') and track.get('has_richsync') and not matched['timingMismatch']:
            try:
                body=(await self.mxm('track.richsync.get',{'track_id':track_id})).get('richsync') or {}
                raw=json.loads(body.get('richsync_body') or '[]');lines=[]
                for row in raw[:2000]:
                    start=float(row['ts']);end=float(row['te']);text=str(row['x'])[:3000]
                    if not 0<=start<end<=query['duration']+2:continue
                    words=[];parts=row.get('l') or []
                    for i,word in enumerate(parts[:500]):
                        begin=start+float(word.get('o',0));stop=start+float(parts[i+1].get('o',0)) if i+1<len(parts) else end
                        if start<=begin<stop<=end:words.append({'text':str(word['c'])[:1000],'start':begin,'end':stop})
                    lines.append({'start':start,'end':end,'text':text,'words':words})
                if any(l['words'] for l in lines):result.update(lines=lines,precision='word')
            except (Upstream,httpx.HTTPError,ValueError,TypeError,KeyError):pass
        return result if result.get('lines') or result['lrc'] or plain else {**common,'phase':'empty'}

    async def lrclib(self,query):
        rows=[];failed=False
        queries=[('get',{'track_name':query['titles'][0],'artist_name':query['artists'][0],'duration':round(query['duration'])})]
        queries += [('search',{'q':t+' '+a}) for t in query['titles'][:2] for a in query['artists'][:3]]
        # No title-only fuzzy result is accepted without matching artist/version.
        async def fetch_one(endpoint,params):
            nonlocal failed
            try:
                data=await self.get_json(LRCLIB+endpoint,params)
                return data if isinstance(data,list) else [data] if isinstance(data,dict) else []
            except (httpx.HTTPError,Upstream,ValueError):failed=True;return []
        for offset in range(0,len(queries),2):
            for batch in await asyncio.gather(*(fetch_one(*q) for q in queries[offset:offset+2])):rows.extend(batch[:200])
            valid=[]
            for row in rows:
                if not isinstance(row,dict):continue
                matched=match(query,row.get('trackName'),row.get('artistName'),row.get('duration'))
                if matched and (row.get('syncedLyrics') or row.get('plainLyrics') or row.get('instrumental')):valid.append((row,matched))
            if valid:
                row,matched=max(valid,key=lambda v:(not v[1]['timingMismatch'],bool(v[0].get('syncedLyrics')),-v[1]['delta']))
                plain=str(row.get('plainLyrics') or '')[:100000]
                return {'phase':'instrumental' if row.get('instrumental') else 'ready','source':'LRCLIB','url':'https://lrclib.net/api/get/'+str(int(row['id'])),
                        'plainText':plain,'lrc':str(row.get('syncedLyrics') or '')[:300000] if not matched['timingMismatch'] else '',
                        'timingMismatch':matched['timingMismatch'],'identity':{'title':row.get('trackName'),'artist':row.get('artistName'),'duration':row.get('duration')}}
        return {'phase':'error' if failed else 'empty'}

    @staticmethod
    def rank(value):
        return 3 if value.get('precision')=='word' else 2 if value.get('lrc') else 1 if value.get('plainText') else 0

    async def search(self,query,budget=None):
        start=time.monotonic();tasks=set();best=None;statuses=[]
        async def delayed():
            await asyncio.sleep(.3)
            return await self.lrclib(query)
        try:
            async with asyncio.timeout(self.budget if budget is None else budget):
                async with self.slots:
                    tasks={asyncio.create_task(self.musixmatch(query)),asyncio.create_task(delayed())}
                    while tasks:
                        done,tasks=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
                        for task in done:
                            try:value=task.result()
                            except Upstream as e:statuses.append(e.status);continue
                            except (httpx.HTTPError,ValueError,TypeError,KeyError):statuses.append('error');continue
                            statuses.append(value.get('phase'))
                            if not best or self.rank(value)>self.rank(best):best=value
                        if best and self.rank(best)==3:break
        except TimeoutError:statuses.append('timeout')
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
        if not best or not self.rank(best):
            phase='instrumental' if 'instrumental' in statuses else 'restricted' if 'restricted' in statuses else 'error' if any(s in statuses for s in ('error','timeout','unavailable','warming')) else 'empty'
            best={'phase':phase,'lines':[]}
        return {**best,'elapsedMs':round((time.monotonic()-start)*1000)}

    async def lookup(self,query):
        start=time.monotonic()
        query={**query,**identity(query['titles'],query['artists'])}
        if not query['titles'] or not query['artists']:return {'phase':'empty','lines':[]}
        key=cache_key(query)
        def read():
            with self.db() as db:row=db.execute('SELECT payload FROM lyrics WHERE k=? AND expires>?',(key,time.time())).fetchone()
            return json.loads(row[0]) if row else None
        hit=await asyncio.to_thread(read)
        if hit is not None and not query.get('refresh'):return {**hit,'cached':True,'elapsedMs':round((time.monotonic()-start)*1000)}
        if key not in self.pending:
            if len(self.pending)>=32:return {'phase':'busy','lines':[]}
            async def work():
                try:
                    result=await self.search(query,max(.05,self.budget-(time.monotonic()-start)-.2))
                    ttl=86400 if self.rank(result)==3 else 300 if self.rank(result) else 600 if result['phase'] in ('empty','instrumental') else 10
                    def save():
                        with self.db() as db:
                            db.execute('DELETE FROM lyrics WHERE expires<?',(time.time(),))
                            db.execute('INSERT OR REPLACE INTO lyrics VALUES(?,?,?)',(key,json.dumps(result,ensure_ascii=False),time.time()+ttl))
                            db.execute('DELETE FROM lyrics WHERE k IN (SELECT k FROM lyrics ORDER BY expires DESC LIMIT -1 OFFSET 2000)')
                    await asyncio.to_thread(save)
                    return result
                finally:self.pending.pop(key,None)
            self.pending[key]=asyncio.create_task(work())
        return {**await asyncio.shield(self.pending[key]),'cached':False,'elapsedMs':round((time.monotonic()-start)*1000)}

def install(app,owner,relay):
    @app.post('/music/lyrics')
    async def lyrics(body:Query,subject=Depends(owner)):
        if any(len(v)>300 for v in [*body.titles,*body.artists]):return {'phase':'empty','lines':[]}
        return await relay.lookup(body.model_dump())
