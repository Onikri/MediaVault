"""Current-page priority, three-page/65-box batches and page-level singleflight."""
from __future__ import annotations
import asyncio, hashlib, itertools, json, time
from .contracts import SCHEMA_VERSION, MODEL_IDS
from .detector import MODEL_SHA256
from .prompt import PROMPT_VERSION
from .quota import Deferred
from .provider import BatchTooLarge
from .som import compose
from .progress import observing
from PIL import Image, ImageOps
import io

POLICY=hashlib.sha256(json.dumps([SCHEMA_VERSION,MODEL_IDS,PROMPT_VERSION,MODEL_SHA256,.35,640,1280,"three-pages-v1"],separators=(',',':')).encode()).hexdigest()[:24]

class RealtimeChapterOrchestrator:
    def __init__(self,sources,detector,translator,cache,*,batch_timeout=45):
        self.sources=sources;self.detector=detector;self.translator=translator;self.cache=cache
        self.pending={};self.queue=asyncio.PriorityQueue();self.serial=itertools.count();self.workers=[];self.detector_gate=asyncio.Semaphore(1);self.delayed=set();self.closed=False;self.batch_timeout=batch_timeout
    def update(self,job,phase,message,**details):
        previous=job.get('progress',{})
        job['progress']={**previous,'phase':phase,'message':message,'retryAtMs':None,**details,'revision':previous.get('revision',0)+1,'updatedAtMs':int(time.time()*1000)}
    def snapshot(self,job):
        value=dict(job.get('progress',{'phase':'queued','message':'Страница в очереди ВМ','revision':0}))
        prepared=job.get('prepared',{})
        value.update(page=job['page'],completedRegions=len(job.get('partial',{})),totalRegions=len(prepared['regions']) if 'regions' in prepared else value.get('totalRegions',0),attempt=job['attempts'],serverTimeMs=int(time.time()*1000),elapsedSeconds=round(time.monotonic()-job['created'],1))
        return value
    def pack_progress(self,owners,pack,value):
        touched={r['uid']:owners[r['uid']] for p in pack for r in p['regions']}
        jobs={j['key']:j for j in touched.values()}
        for j in jobs.values():
            if j['future'].done():continue
            if value['phase']=='google':j['attempts']+=1
            details={k:v for k,v in value.items() if k not in ('phase','message','retryAfterSeconds')}
            if 'retryAfterSeconds' in value:details['retryAtMs']=int((time.time()+value['retryAfterSeconds'])*1000)
            self.update(j,value['phase'],value['message'],**details)
    async def publish_ready(self,jobs,pages,output):
        for j,p in zip(jobs,pages):
            if j['future'].done() or any(r['uid'] not in output for r in p['regions']):continue
            self.update(j,'saving','Сохраняем готовый перевод в кэш')
            value={'schemaVersion':SCHEMA_VERSION,'policy':POLICY,'manifest':j['source']['manifest'],'page':p['page'],'width':p['width'],'height':p['height'],'regions':[{**r,**output[r['uid']]} for r in p['regions']],'timings':p['timings'],'usage':j.get('usage',[]),'machineTranslation':True}
            await self.cache.put(j['key'],j['source']['scope'],value)
            self.update(j,'ready','Страница переведена')
            j['future'].set_result(value);j.pop('prepared',None);self.pending.pop(j['key'],None);j['source']['archive'].release()
    def start(self):
        if not self.workers:self.workers=[asyncio.create_task(self.work()) for _ in range(3)]
    def key(self,s,page):return self.cache.identity(s['scope'],s['manifest'],page,POLICY+':'+s.get('direction','ltr')+':'+s.get('model','gemini-3.5-flash-lite'))
    async def window(self,s,current):
        hits=[];waiting=[];new=[]
        for page in range(current,min(len(s['names'])+1,current+9)):
            key=self.key(s,page);hit=await self.cache.get(key,s['scope'])
            if hit is not None:hits.append({**hit,'cacheHit':True});continue
            priority=(page-current)//3
            job=self.pending.get(key)
            if not job:
                if len(self.pending)>=128:raise ValueError('Очередь перевода заполнена. Дождись текущих страниц.')
                s['archive'].acquire()
                future=asyncio.get_running_loop().create_future();future.add_done_callback(lambda f:None if f.cancelled() else f.exception())
                job={'future':future,'page':page,'key':key,'source':s,'priority':priority,'started':False,'created':time.monotonic(),'attempts':0}
                self.pending[key]=job;new.append(job);self.update(job,'queued','Страница в очереди ВМ')
            elif not job['started'] and priority<job['priority']:
                job['priority']=priority;self.queue.put_nowait((priority,next(self.serial),[job]))
            waiting.append(job)
        # Three packs of three pages, with a separate credential lease per pack.
        for priority in sorted({j['priority'] for j in new}):
            same=[j for j in new if j['priority']==priority]
            for offset in range(0,len(same),3):
                group=same[offset:offset+3];self.queue.put_nowait((priority,next(self.serial),group))
        self.start();return hits,waiting
    def requeue(self,jobs,seconds):
        async def later():
            await asyncio.sleep(seconds)
            if not self.closed:
                for j in jobs:j['started']=False
                self.queue.put_nowait((min(j['priority'] for j in jobs),next(self.serial),jobs))
        t=asyncio.create_task(later());self.delayed.add(t);t.add_done_callback(self.delayed.discard)
    async def prepare(self,job):
        if 'prepared' in job:return job['prepared']
        start=time.perf_counter();s=job['source'];self.update(job,'drive','Читаем и расшифровываем страницу с Google Drive')
        data=await asyncio.to_thread(s['archive'].page,s['names'][job['page']-1]);fetch_ms=(time.perf_counter()-start)*1000
        def detect_compose():
            image,regions,timings=self.detector.detect(data,job['page'],s.get('direction')=='rtl')
            try:
                som,som_timings=compose(image,regions)
                return {'model':s.get('model','gemini-3.5-flash-lite'),'source_bytes':data,'page':job['page'],'width':image.width,'height':image.height,'regions':regions,'som':som,'timings':{**timings,**som_timings,'driveMs':round(fetch_ms,2)}}
            finally:image.close()
        self.update(job,'waiting_detector','Ожидаем детектор текста на ВМ')
        async with self.detector_gate:
            self.update(job,'detecting','Определяем текстовые области и готовим разметку')
            p=await asyncio.to_thread(detect_compose)
        job['prepared']=p;self.update(job,'prepared','Разметка готова · найдено областей: '+str(len(p['regions'])),totalRegions=len(p['regions']));return p
    async def translate_group(self,jobs):
        pages=await asyncio.gather(*(self.prepare(j) for j in jobs))
        output={};usage=[];batch=[];count=0
        owners={r['uid']:j for j,p in zip(jobs,pages) for r in p['regions']}
        for j in jobs:output.update(j.get('partial',{}));usage.extend(j.get('usage',[]))
        async def fragment(p,rows):
            part={**p,'regions':rows}
            if len(rows)!=len(p['regions']):
                if 'source_bytes' not in p:
                    j=owners[rows[0]['uid']];s=j['source'];p['source_bytes']=await asyncio.to_thread(s['archive'].page,s['names'][j['page']-1])
                def remark():
                    with Image.open(io.BytesIO(p['source_bytes'])) as image:return compose(ImageOps.exif_transpose(image).convert('RGB'),rows)[0]
                part['som']=await asyncio.to_thread(remark)
            return part
        async def translate(pack):
            try:
                with observing(lambda value:self.pack_progress(owners,pack,value)):
                    return_value=await self.call_provider(pack)
                rows,meta=return_value
            except (BatchTooLarge,TimeoutError):
                self.pack_progress(owners,pack,{'phase':'splitting','message':'Делим запрос на меньшие фрагменты для надёжного перевода'})
                if len(pack)>1:
                    half=len(pack)//2;await translate(pack[:half]);await translate(pack[half:]);return
                p=pack[0];regions=p['regions']
                if len(regions)<2:raise ValueError('Даже одна область превышает лимит токенов Google. Нужен меньший скан или больший подтверждённый бюджет.')
                half=len(regions)//2
                await translate([await fragment(p,regions[:half])]);await translate([await fragment(p,regions[half:])]);return
            output.update(rows);usage.append(meta)
            # Quota deferral after a successful fragment must not translate it
            # again on retry. Partial results live only in bounded RAM; no page
            # is persisted/emitted until every expected uid is present.
            touched=set()
            for uid,row in rows.items():
                j=owners[uid];j.setdefault('partial',{})[uid]=row
                if j['key'] not in touched:j.setdefault('usage',[]).append(meta);touched.add(j['key'])
            for key in touched:
                j=self.pending.get(key)
                if j:self.update(j,'partial','Проверенная часть перевода готова')
            await self.publish_ready(jobs,pages,output)
        async def flush():
            nonlocal batch,count
            if batch:await translate(batch);batch=[];count=0
        await self.publish_ready(jobs,pages,output)
        for j,p in zip(jobs,pages):
            remaining=[r for r in p['regions'] if r['uid'] not in j.get('partial',{})]
            for offset in range(0,len(remaining),65):
                rows=remaining[offset:offset+65]
                if batch and (len(batch)>=3 or count+len(rows)>65):await flush()
                batch.append(await fragment(p,rows));count+=len(rows)
        await flush()
        await self.publish_ready(jobs,pages,output)
    async def call_provider(self,pack):
        if len(pack)>1:
            async with asyncio.timeout(self.batch_timeout):return await self.translator.translate(pack)
        return await self.translator.translate(pack)
    async def work(self):
        while True:
            _,_,group=await self.queue.get()
            jobs=[j for j in group if not j['started'] and not j['future'].done()]
            if not jobs:self.queue.task_done();continue
            for j in jobs:j['started']=True
            try:await self.translate_group(jobs)
            except Deferred as e:
                jobs=[j for j in jobs if not j['future'].done()]
                if not jobs:continue
                for j in jobs:self.update(j,'waiting','Пауза Google · готовые фрагменты сохранены',retryAtMs=int((time.time()+e.seconds)*1000))
                # Keep coordinates, SoM and completed text, not up to128 full
                # compressed originals while a quota window is closed.
                for j in jobs:j.get('prepared',{}).pop('source_bytes',None)
                if any(time.monotonic()-j['created']>900 for j in jobs):self.fail(jobs,ValueError('Google не завершил перевод за 15 минут. Повтори позже.'))
                else:self.requeue(jobs,e.seconds)
            except asyncio.CancelledError:raise
            except Exception as e:self.fail(jobs,e)
            finally:self.queue.task_done()
    def fail(self,jobs,error):
        for j in jobs:
            if self.pending.get(j['key']) is not j:continue
            if not j['future'].done():
                self.update(j,'error',str(error)[:500]);j['future'].set_exception(error)
            self.pending.pop(j['key'],None);j.pop('prepared',None);j['source']['archive'].release()
    async def close(self):
        self.closed=True
        for t in [*self.workers,*self.delayed]:t.cancel()
        await asyncio.gather(*self.workers,*self.delayed,return_exceptions=True)
        self.fail(list(self.pending.values()),ValueError('Сервис перевода перезапускается.'))
