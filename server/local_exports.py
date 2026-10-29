"""Owner-requested temporary CBZ/MP4 exports; no Drive writes or permanent files.

One worker shares byte/cancellation limits across all downloader HTTP forks.
Completed files are streamed through short-lived, unguessable capabilities.
"""
from dataclasses import dataclass,field
from pathlib import Path
from urllib.parse import urlsplit
import os,re,secrets,shutil,subprocess,tempfile,threading,time
from fastapi import Depends,HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,ConfigDict,Field
from source_parser import PublicHttp,Resolver,SourceError,public_url

GiB=1024**3
class ExportCancelled(RuntimeError):pass
class ExportProblem(RuntimeError):pass
class ExportMissing(LookupError):pass
class ExportLimit(RuntimeError):pass

class LeaseFileResponse(FileResponse):
    """Release the file lease on success, disconnect and streaming errors."""
    def __init__(self,*args,release,**kwargs):super().__init__(*args,**kwargs);self.release=release
    async def __call__(self,scope,receive,send):
        complete=False
        try:
            await super().__call__(scope,receive,send)
            complete=scope.get('method')=='GET' and not any(k.lower()==b'range' for k,v in scope.get('headers',[]))
        finally:self.release(complete)

def validate_request(url,kind,quality):
    if kind not in {'video','manga'} or quality!='best' and not re.fullmatch(r'[1-9][0-9]{1,3}',str(quality)):raise ValueError('Некорректный формат или качество скачивания.')
    public_url(url,resolve_dns=False)
    if kind=='manga':
        from manga_sources import site_for
        from suwayomi_bridge import parse_reference
        if not site_for(url):raise ValueError('Эта читалка пока не поддерживает скачивание.')
        reference=parse_reference(url)
        if reference and (reference[1] is None or reference[2] is not None):raise ValueError('Выбери конкретную главу манги.')
        if quality not in {'best','1280','1920'}:raise ValueError('Для манги выбери оригинал, 1280 или 1920 px.')
    else:
        from site_adapters import site_for
        from anime_dl_core import AniboomPlayer,AnimediaPlayer,SibnetPlayer,CvhPlayer,VkPlayer,AnilibriaPlayer,SovetRomanticaPlayer
        from player_compat import KodikPlayer
        site=site_for(url);host=urlsplit(url).hostname or ''
        player=any(p.matches(url) for p in (KodikPlayer,AniboomPlayer,AnimediaPlayer,SibnetPlayer,CvhPlayer,VkPlayer,AnilibriaPlayer,SovetRomanticaPlayer))
        cvh=host=='plapi.cdnvideohub.com' and bool(re.fullmatch(r'/api/v1/player/sv/video/\d+',urlsplit(url).path))
        if not (site and site.kind=='anime' or player or cvh or host.endswith(('.stravers.live','.thealloha.club','.alloha.tv'))):raise ValueError('Выбери серию в поддерживаемом источнике или плеере.')

@dataclass
class Export:
    id:str
    owner:str
    url:str
    kind:str
    quality:str
    created:float
    expires:float
    directory:Path
    referer:str|None=None
    state:str='queued'
    progress:dict=field(default_factory=lambda:{'phase':'queued'})
    error:str=''
    file:Path|None=None
    capability:str=''
    capability_expires:float=0
    running:bool=False
    leases:int=0
    cancel:threading.Event=field(default_factory=threading.Event)

class Budget:
    def __init__(self,job,maximum,reserve=GiB,deadline=1800):
        self.job=job;self.maximum=maximum;self.reserve=reserve;self.downloaded=0;self.lock=threading.Lock();self.deadline=time.monotonic()+deadline
    def check(self):
        if self.job.cancel.is_set():raise ExportCancelled()
        if time.monotonic()>self.deadline:raise ExportProblem('Подготовка превысила 30 минут. Выбери меньший файл или качество.')
        if shutil.disk_usage(self.job.directory).free<self.reserve:raise ExportProblem('Недостаточно свободного места на сервере для временного файла.')
    def consume(self,size):
        self.check()
        with self.lock:
            self.downloaded+=size
            if self.downloaded>self.maximum:raise ExportProblem('Файл превышает лимит временного скачивания. Выбери меньшее качество.')
    def run(self,args,*,capture_output=True,text=False,timeout=900,check=False,**kwargs):
        """Monitor remux/ffprobe rather than leaving a cancelled ffmpeg alive."""
        self.check();started=time.monotonic();process=None
        with tempfile.TemporaryDirectory(dir=self.job.directory,prefix='process-') as logs,open(Path(logs)/'stdout','w+b') as out,open(Path(logs)/'stderr','w+b') as err:
            try:
                process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=out,stderr=err,**kwargs)
                while process.poll() is None:
                    self.check()
                    if time.monotonic()-started>timeout:raise ExportProblem('Не удалось собрать файл за отведённое время.')
                    target=Path(args[-1])
                    if target.is_file() and target.stat().st_size>self.maximum:raise ExportProblem('Готовый файл превышает лимит временного скачивания.')
                    if out.tell()>8*1024**2 or err.tell()>8*1024**2:raise ExportProblem('Источник не удалось собрать в проверенный файл.')
                    self.job.cancel.wait(.2)
                out.seek(0);err.seek(0);stdout=out.read(1024**2);stderr=err.read(1024**2)
                if text:stdout=stdout.decode('utf-8',errors='replace');stderr=stderr.decode('utf-8',errors='replace')
                result=subprocess.CompletedProcess(args,process.returncode,stdout,stderr)
                if check and result.returncode:raise subprocess.CalledProcessError(result.returncode,args,stdout,stderr)
                return result
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)

class BoundedResponse:
    def __init__(self,response,budget):self.response=response;self.budget=budget
    def __getattr__(self,name):return getattr(self.response,name)
    def iter_content(self,*args,**kwargs):
        for block in self.response.iter_content(*args,**kwargs):
            self.budget.consume(len(block));yield block
    def close(self):return self.response.close()

class ExportHttp(PublicHttp):
    def __init__(self,budget):super().__init__(timeout=(4,12),deadline=budget.deadline);self.budget=budget
    def fork(self):return ExportHttp(self.budget)
    def _open(self,*args,**kwargs):
        self.budget.check();response,final=super()._open(*args,**kwargs)
        return BoundedResponse(response,self.budget),final
    def download(self,value,target,*,headers=None,byte_range=None,maximum=2*GiB):
        self.budget.check()
        return super().download(value,target,headers=headers,byte_range=byte_range,maximum=min(maximum,self.budget.maximum))

def produce(job,progress,maximum,reserve):
    budget=Budget(job,maximum,reserve);http=ExportHttp(budget)
    def update(value):
        budget.check();progress({**value,'downloadedBytes':budget.downloaded})
    try:
        if job.kind=='manga':
            from manga_download import download_chapter
            result=download_chapter(job.url,job.directory,http,progress=update,quality=job.quality)
        else:
            from media_download import download_episode,pick_stream
            page=Resolver(http).resolve(job.url,referer=job.referer) if job.referer else Resolver(http).resolve(job.url);budget.check()
            stream=pick_stream(page.streams,job.quality)
            result=download_episode(stream,job.directory,http=http,quality=job.quality,progress=update,run=budget.run)
        budget.check()
        if result.stat().st_size>maximum:raise ExportProblem('Файл превышает лимит временного скачивания.')
        return result
    finally:http.close()

class Exports:
    def __init__(self,directory,*,clock=time.time,producer=produce,ttl=3600,reserve=GiB,start_worker=True):
        self.root=(Path(directory)/'local-exports').resolve();self.root.mkdir(parents=True,exist_ok=True,mode=0o700);self.root.chmod(0o700)
        self.clock=clock;self.producer=producer;self.ttl=ttl;self.reserve=reserve;self.jobs={};self.lock=threading.RLock();self.condition=threading.Condition(self.lock);self.stopping=False
        # Previous process capabilities no longer exist: remove only this
        # service's generated directories, never arbitrary neighboring files.
        for path in self.root.iterdir():
            if re.fullmatch(r'[0-9a-f]{32}',path.name):self._remove(path)
        self.thread=threading.Thread(target=self._worker,daemon=True,name='local-export')
        if start_worker:self.thread.start()
    def _remove(self,path):
        if path.parent!=self.root or not re.fullmatch(r'[0-9a-f]{32}',path.name):raise RuntimeError('Unsafe export cleanup path')
        if path.is_symlink():path.unlink()
        elif path.exists():shutil.rmtree(path)
    def _cleanup(self):
        now=self.clock()
        for identity,job in list(self.jobs.items()):
            if job.expires<now:
                job.cancel.set()
                if job.running or job.leases:continue
                self._remove(job.directory);del self.jobs[identity]
            elif job.state in {'cancelled','error','downloaded'} and not job.running and not job.leases:self._remove(job.directory)
    def _snapshot(self,job):
        value={'id':job.id,'kind':job.kind,'state':job.state,'progress':dict(job.progress),'expiresAt':job.expires}
        if job.error:value['error']=job.error
        if job.state=='done' and job.file:
            if job.capability_expires<=self.clock():job.capability=secrets.token_urlsafe(32);job.capability_expires=self.clock()+900
            value.update(downloadUrl='/online/exports/file/'+job.capability,downloadExpiresAt=job.capability_expires,
                         filename='MediaVault-'+job.id[:8]+('.cbz' if job.kind=='manga' else '.mp4'),bytes=job.file.stat().st_size)
        return value
    def _owned(self,owner,identity):
        job=self.jobs.get(identity)
        if job is None or job.owner!=owner or job.expires<self.clock():raise ExportMissing()
        return job
    def start(self,owner,url,kind,quality='best',referer=None):
        validate_request(url,kind,quality)
        referer=public_url(referer,resolve_dns=False) if referer else None
        with self.condition:
            self._cleanup()
            same=next((j for j in self.jobs.values() if j.owner==owner and j.url==url and j.kind==kind and j.quality==quality and j.referer==referer and j.state in {'queued','running','done'}),None)
            if same:return self._snapshot(same)
            active=[j for j in self.jobs.values() if j.running or j.state=='queued']
            if len(active)>=4 or sum(j.owner==owner for j in active)>=2:raise ExportLimit('Дождись скачивания или останови предыдущее задание.')
            ready=[j for j in self.jobs.values() if j.state=='done']
            if len(ready)>=8 or sum(j.owner==owner for j in ready)>=4:raise ExportLimit('Скачай готовые файлы и убери их из списка перед новым заданием.')
            if shutil.disk_usage(self.root).free<self.reserve+32*1024**2:raise ExportLimit('На сервере недостаточно места для временного скачивания.')
            identity=secrets.token_hex(16);now=self.clock();job=Export(identity,owner,url,kind,quality,now,now+self.ttl,self.root/identity,referer=referer)
            self.jobs[identity]=job;self.condition.notify_all();return self._snapshot(job)
    def status(self,owner,identity):
        with self.lock:self._cleanup();return self._snapshot(self._owned(owner,identity))
    def cancel(self,owner,identity):
        with self.condition:
            job=self._owned(owner,identity);job.cancel.set();job.state='cancelled';job.progress={'phase':'cancelled'};job.capability=''
            if not job.running and not job.leases:self._remove(job.directory)
            self.condition.notify_all();return self._snapshot(job)
    def acquire(self,capability):
        with self.lock:
            self._cleanup();job=next((j for j in self.jobs.values() if j.capability==capability and j.state=='done' and j.capability_expires>self.clock()),None)
            if not job or not job.file or not job.file.is_file():raise ExportMissing()
            job.leases+=1;return job,self._snapshot(job)
    def release(self,job,completed=False):
        with self.lock:
            job.leases=max(0,job.leases-1)
            if completed and not job.leases and job.state=='done':
                job.state='downloaded';job.capability='';job.file=None;self._remove(job.directory)
            self._cleanup()
    def _worker(self):
        while True:
            with self.condition:
                self._cleanup()
                if self.stopping:return
                job=next((j for j in self.jobs.values() if j.state=='queued'),None)
                if job is None:self.condition.wait(timeout=10);continue
                job.state='running';job.running=True;job.progress={'phase':'preparing'};job.directory.mkdir(mode=0o700)
            def progress(value):
                if job.cancel.is_set():raise ExportCancelled()
                with self.lock:
                    job.progress={k:v for k,v in value.items() if k in {'phase','loaded','total','downloadedBytes','pagesLoaded','pagesTotal'} and isinstance(v,(str,int,float))}
            try:
                maximum=min(GiB if job.kind=='manga' else 2*GiB,max(0,(shutil.disk_usage(self.root).free-self.reserve-128*1024**2)//2))
                if maximum<16*1024**2:raise ExportProblem('На сервере недостаточно места для временного файла.')
                path=Path(self.producer(job,progress,maximum,self.reserve)).resolve()
                if job.cancel.is_set():raise ExportCancelled()
                if path.parent!=job.directory or not path.is_file() or path.stat().st_size<=0 or path.stat().st_size>maximum:raise ExportProblem('Не удалось проверить готовый файл.')
                with self.lock:
                    if job.cancel.is_set():raise ExportCancelled()
                    job.file=path;job.state='done';job.progress={'phase':'done','downloadedBytes':path.stat().st_size};job.expires=self.clock()+self.ttl
                    job.capability=secrets.token_urlsafe(32);job.capability_expires=self.clock()+900
                # Downloader inputs are not an archive: retain only the finished
                # single file, and only until expiry/cancellation.
                for child in job.directory.iterdir():
                    if child.resolve()!=path:
                        if child.is_dir() and not child.is_symlink():shutil.rmtree(child)
                        else:child.unlink()
            except ExportCancelled:
                with self.lock:job.state='cancelled';job.progress={'phase':'cancelled'}
            except Exception as error:
                with self.lock:
                    job.state='error';job.progress={'phase':'error'}
                    job.error=str(error) if isinstance(error,ExportProblem) else 'Источник не предоставил проверенный файл. Проверь главу или серию и повтори.'
            finally:
                with self.condition:
                    job.running=False;self._cleanup();self.condition.notify_all()
    def close(self):
        with self.condition:
            self.stopping=True
            for job in self.jobs.values():
                if job.running or job.state=='queued':job.cancel.set()
            self.condition.notify_all()
        if self.thread.is_alive():self.thread.join(timeout=6)

_manager=None;_manager_lock=threading.Lock()
def manager():
    global _manager
    with _manager_lock:
        if _manager is None:_manager=Exports(os.getenv('DATA_DIR','/data'))
        return _manager

class ExportRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    url:str=Field(min_length=1,max_length=8192)
    referer:str|None=Field(default=None,max_length=8192)
    kind:str=Field(pattern='^(video|manga)$')
    quality:str=Field(default='best',pattern='^(best|[1-9][0-9]{1,3})$')

def install(app,owner):
    @app.post('/online/exports',status_code=202)
    def create_export(body:ExportRequest,subject=Depends(owner)):
        try:return manager().start(subject,body.url,body.kind,body.quality,referer=body.referer)
        except (ValueError,SourceError) as error:raise HTTPException(422,str(error)) from None
        except ExportLimit as error:raise HTTPException(429,str(error)) from None
    @app.get('/online/exports/file/{capability}')
    def export_file(capability:str):
        try:job,value=manager().acquire(capability)
        except ExportMissing:raise HTTPException(410,'Ссылка скачивания истекла. Открой готовое задание снова.') from None
        try:
            return LeaseFileResponse(job.file,filename=value['filename'],media_type='application/vnd.comicbook+zip' if job.kind=='manga' else 'video/mp4',
                                headers={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'},release=lambda completed:manager().release(job,completed))
        except BaseException:manager().release(job);raise
    @app.get('/online/exports/{identity}')
    def export_status(identity:str,subject=Depends(owner)):
        try:return manager().status(subject,identity)
        except ExportMissing:raise HTTPException(404,'Задание скачивания не найдено или срок хранения истёк.') from None
    @app.delete('/online/exports/{identity}')
    def cancel_export(identity:str,subject=Depends(owner)):
        try:return manager().cancel(subject,identity)
        except ExportMissing:raise HTTPException(404,'Задание скачивания не найдено или срок хранения истёк.') from None


def shutdown():
    global _manager
    with _manager_lock:
        if _manager is not None:_manager.close();_manager=None
