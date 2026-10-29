# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authenticated cancellable vision jobs and encrypted translation cache."""
import asyncio,secrets,time
from pathlib import Path
from fastapi import Depends,HTTPException
from gemma_translate import Batch,Gateway,VERSION,check_images,status

class GemmaJobs:
    def __init__(self,directory,cache_class):
        root=Path(directory)/'gemma';root.mkdir(parents=True,exist_ok=True,mode=0o700)
        from google_pool import saved
        self.gateway=Gateway(root,credentials=saved);self.cache=cache_class(root/'results',limit=128*1024*1024)
        self.jobs={};self.queue=asyncio.Queue(maxsize=4);self.workers=[];self.submit_lock=asyncio.Lock()
    def cleanup(self):
        for key,j in list(self.jobs.items()):
            if j['state'] in ['done','error','cancelled'] and time.monotonic()-j['updated']>600:self.jobs.pop(key)
    async def submit(self,batch,subject):
        async with self.submit_lock:return await self._submit(batch,subject)
    async def _submit(self,batch,subject):
        self.cleanup();key=self.cache.identity(subject,batch.model_dump_json().encode(),{'pipeline':'gemma-vision','prompt':VERSION})
        for id,j in self.jobs.items():
            if j['key']==key and j['subject']==subject and j['state'] in ['queued','running','done']:return id
        if self.queue.full() or len(self.jobs)>=20:raise HTTPException(429,'Очередь Google заполнена. Дождись текущего пакета.')
        hit=await asyncio.to_thread(self.cache.read,key);id=secrets.token_urlsafe(24)
        self.jobs[id]={'key':key,'subject':subject,'state':'done' if hit else 'queued','status':'Готово · из кэша ВМ' if hit else 'В очереди Google','updated':time.monotonic(),**({'result':{**hit,'cacheHit':True}} if hit else {'batch':batch})}
        if not hit:
            self.queue.put_nowait(id)
            self.workers=[w for w in self.workers if not w.done()]
            while len(self.workers)<2:self.workers.append(asyncio.create_task(self.run()))
        return id
    def get(self,id,subject):
        self.cleanup();j=self.jobs.get(id)
        if not j or j['subject']!=subject:raise HTTPException(404,'Задание перевода не найдено.')
        return j
    def cancel(self,j):
        j.pop('batch',None);j.pop('result',None);j.update(state='cancelled',status='Отменено',updated=time.monotonic())
        if j.get('task'):j['task'].cancel()
    async def run(self):
        while not self.queue.empty():
            id=await self.queue.get();j=self.jobs[id]
            try:
                if j['state']=='cancelled':continue
                j.update(state='running',status='Подготавливаем пакет Google')
                def progress(text):j.update(status=text,updated=time.monotonic())
                task=asyncio.create_task(self.gateway.translate(j['batch'],progress));j['task']=task
                result=await asyncio.wait_for(task,900)
                if j['state']=='cancelled':continue
                await asyncio.to_thread(self.cache.write,j['key'],result)
                j.update(state='done',status='Перевод и стили готовы · очищаем страницу на устройстве',result=result)
            except asyncio.CancelledError:j.update(state='cancelled',status='Отменено')
            except Exception as e:
                msg=str(e) if isinstance(e,ValueError) else 'Не удалось получить перевод Google. Повтори пакет.'
                j.update(state='error',status=msg[:300])
            finally:j.pop('batch',None);j.pop('task',None);j['updated']=time.monotonic();self.queue.task_done()
    async def close(self):
        for j in self.jobs.values():self.cancel(j)
        if self.workers:await asyncio.gather(*self.workers)
        self.jobs.clear()

def install_routes(app,owner):
    @app.post('/reader/lmt/gemma/jobs',status_code=202)
    async def submit(body:Batch,subject=Depends(owner)):
        if not status()['ready']:raise HTTPException(503,'На ВМ ещё не установлен ключ Google API.')
        try:await asyncio.to_thread(check_images,body)
        except Exception:raise HTTPException(422,'Некорректное подготовленное изображение страницы.') from None
        return {'id':await app.state.gemma.submit(body,subject)}
    @app.get('/reader/lmt/gemma/jobs/{job_id}')
    async def poll(job_id:str,subject=Depends(owner)):
        j=app.state.gemma.get(job_id,subject)
        return {'state':j['state'],'status':j['status'],**({'result':j['result']} if j['state']=='done' else {})}
    @app.post('/reader/lmt/gemma/jobs/{job_id}/cancel')
    async def cancel(job_id:str,subject=Depends(owner)):
        app.state.gemma.cancel(app.state.gemma.get(job_id,subject));return {'state':'cancelled'}
