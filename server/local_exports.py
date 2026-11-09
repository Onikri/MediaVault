"""Owner-requested temporary CBZ/MP4 exports; no Drive writes or permanent files.

One worker shares byte/cancellation limits across all downloader HTTP forks.
Completed files are streamed through short-lived, unguessable capabilities.
"""
from dataclasses import dataclass,field
from pathlib import Path
from urllib.parse import quote,urlsplit
import hashlib,os,re,secrets,shutil,subprocess,tempfile,threading,time
from fastapi import Depends,HTTPException,Request
from fastapi.responses import FileResponse,StreamingResponse
from anyio import CancelScope,to_thread
from typing import Literal
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel,ConfigDict,Field
from source_parser import PublicHttp,Resolver,SourceError,is_alloha_player,public_url
from manga_export import Options as MangaOptions, cached_path, verify_image

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

class AllohaDownloadResponse(StreamingResponse):
    """Stream a verified MP4 from the remuxer without staging a full 4K file."""
    def __init__(self,job,manager,filename,video,opened):
        self.job,self.manager,self.opened=job,manager,opened
        self.complete=False
        def stream():
            while block:=video.read(1024*1024):
                yield block
            video.validate()  # Fail the HTTP transfer instead of accepting a partial MP4.
            self.complete=True
        super().__init__(stream(),media_type='video/mp4',headers={
            'Content-Disposition':"attachment; filename=video.mp4; filename*=UTF-8''"+quote(filename),
            'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'})

    async def __call__(self,scope,receive,send):
        sent=False
        try:
            await super().__call__(scope,receive,send)
            sent=self.complete
        finally:
            with CancelScope(shield=True):
                if not sent:self.job.cancel.set()
                try:await to_thread.run_sync(self.opened.__exit__,None,None,None)
                finally:self.manager.release(self.job,sent,aborted=not sent)

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
        if not (site and site.kind=='anime' or player or cvh or is_alloha_player(url)):raise ValueError('Выбери серию в поддерживаемом источнике или плеере.')

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
    manga:dict|None=None
    staged:dict|None=None
    name:str=''
    alloha_mode:str|None=None
    alloha_importer:object=None

    @property
    def alloha(self):
        return self.kind=='video' and is_alloha_player(self.url)

    @property
    def pipe_to_device(self):
        return self.alloha and self.alloha_importer is not None and (self.quality=='best' or int(self.quality)>=1440)

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
            if job.manga:
                from manga_export import produce as produce_manga
                result=produce_manga(job,http,budget,update)
            else:
                from manga_download import download_chapter
                result=download_chapter(job.url,job.directory,http,progress=update,quality=job.quality)
        elif job.alloha and job.alloha_importer:
            budget.deadline=time.monotonic()+3*3600
            result=job.directory/'video.mp4'
            def report(value):
                update({**value,'message':str(value.get('operation','')).replace(' → шифрование → Drive','')})
            video=job.alloha_importer.stream(job.url,job.directory,quality=job.quality,referer=job.referer,
                                             mode=job.alloha_mode,progress=report,cancelled=job.cancel.is_set)
            with video.opened(), result.open('wb') as out:
                while block:=video.read(1024*1024):
                    budget.consume(len(block));out.write(block)
                    update({'phase':'downloading'})
                video.validate()
        elif job.staged:
            # Browser-uploaded segments (staged_video): the same ffmpeg remux, no CDN request.
            from media_download import assemble
            from staged_video import write_playlists
            result=assemble(write_playlists(job.directory,job.staged),job.directory,progress=update,run=budget.run)
        else:
            from media_download import download_episode,pick_stream
            page=Resolver(http).resolve(job.url,referer=job.referer) if job.referer else Resolver(http).resolve(job.url);budget.check()
            stream=pick_stream(page.streams,job.quality)
            # Viewer-paced CDNs (source_parser.PACED_HOSTS) need about the film's own
            # length; the 30 min budget would cut them off mid-episode.
            from source_parser import PACED_HOSTS
            from urllib.parse import urlsplit
            if (urlsplit(stream['url']).hostname or '').endswith(PACED_HOSTS):budget.deadline=max(budget.deadline,time.monotonic()+3*3600)
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
            elif job.state in {'cancelled','error','downloaded','taken'} and not job.running and not job.leases:self._remove(job.directory)
    def _snapshot(self,job):
        value={'id':job.id,'kind':job.kind,'state':job.state,'progress':dict(job.progress),'expiresAt':job.expires}
        if job.error:value['error']=job.error
        if job.staged:value['segments']={'received':len(job.staged['sizes']),'total':len(job.staged['files'])}
        if job.state=='done' and (job.file or job.pipe_to_device):
            if job.capability_expires<=self.clock():job.capability=secrets.token_urlsafe(32);job.capability_expires=self.clock()+900
            value.update(downloadUrl='/online/exports/file/'+job.capability,downloadExpiresAt=job.capability_expires,
                         filename=(re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',job.manga['name']).strip(' .') or 'Манга')+'.'+job.manga['format'] if job.manga else (re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',job.name).strip(' .') or 'MediaVault-'+job.id[:8])+('.cbz' if job.kind=='manga' else '.mp4'))
            if job.file:value['bytes']=job.file.stat().st_size
        return value
    def _owned(self,owner,identity):
        job=self.jobs.get(identity)
        if job is None or job.owner!=owner or job.expires<self.clock():raise ExportMissing()
        return job
    def start(self,owner,url,kind,quality='best',referer=None,manga=None,stream=None,name='',alloha_mode=None,alloha_importer=None):
        manga=MangaOptions.model_validate(manga).model_dump() if manga is not None else None
        staged=None
        if stream is not None:
            from staged_video import browser_only,plan
            if kind!='video' or manga or not browser_only(url):raise ValueError('Передать серию из браузера можно только для Collaps.')
            staged=plan(stream)
        elif manga:
            if kind!='manga':raise ValueError('Настройки глав доступны только для манги.')
            if not manga['chapters'] and not (manga['originals'] or manga['mode']=='cached' and manga['cached']):raise ValueError('Выбери главы или готовые страницы из кэша.')
            for chapter in manga['chapters']:validate_request(chapter['url'],'manga',quality)
            for group in ['cached','originals']:
                identities={(p['chapter'],p['page']) for p in manga[group]}
                if len(identities)!=len(manga[group]) or any(c>=max(1,len(manga['chapters'])) for c,p in identities):raise ValueError('Некорректный список сохранённых страниц.')
        else:validate_request(url,kind,quality)
        referer=public_url(referer,resolve_dns=False) if referer else None
        with self.condition:
            self._cleanup()
            same=None if staged else next((j for j in self.jobs.values() if j.owner==owner and j.url==url and j.kind==kind and j.quality==quality and j.referer==referer and j.manga==manga and j.alloha_mode==alloha_mode and j.state in {'staging','queued','running','done'}),None)
            if same:return self._snapshot(same)
            active=[j for j in self.jobs.values() if j.running or j.state in {'queued','staging'}]
            if len(active)>=4 or sum(j.owner==owner for j in active)>=2:raise ExportLimit('Дождись скачивания или останови предыдущее задание.')
            ready=[j for j in self.jobs.values() if j.state=='done']
            if len(ready)>=8 or sum(j.owner==owner for j in ready)>=4:raise ExportLimit('Скачай готовые файлы и убери их из списка перед новым заданием.')
            if shutil.disk_usage(self.root).free<self.reserve+32*1024**2:raise ExportLimit('На сервере недостаточно места для временного скачивания.')
            identity=secrets.token_hex(16);now=self.clock();job=Export(identity,owner,url,kind,quality,now,now+self.ttl,self.root/identity,referer=referer)
            job.manga=manga;job.staged=staged;job.name=str(name or '')[:120]
            job.alloha_mode=alloha_mode;job.alloha_importer=alloha_importer
            if job.pipe_to_device:
                job.state='done';job.progress={'phase':'ready'}
                self.jobs[identity]=job
                return self._snapshot(job)
            if staged:
                job.state='staging';job.progress={'phase':'staging'};job.directory.mkdir(mode=0o700)
                self.jobs[identity]=job;return {**self._snapshot(job),'resources':staged['urls']}
            if manga and (manga['cached'] or manga['originals']):
                job.state='staging';job.progress={'phase':'staging'};job.directory.mkdir(mode=0o700)
            self.jobs[identity]=job;self.condition.notify_all();return self._snapshot(job)
    def put_page(self,owner,identity,chapter,page,data,source=False):
        with self.lock:
            job=self._owned(owner,identity)
            if job.state!='staging':raise ExportLimit('Подготовка страниц уже завершена.')
            expected=next((v for v in job.manga['originals' if source else 'cached'] if v['chapter']==chapter and v['page']==page),None)
            if not expected or hashlib.sha256(data).hexdigest()!=expected['imageHash']:raise ValueError('Сохранённая страница не совпадает с запросом.')
            verify_image(data)
            path=cached_path(job,chapter,page,source);previous=path.stat().st_size if path.is_file() else 0
            size=sum(p.stat().st_size for p in job.directory.glob('*.image'))
            if size-previous+len(data)>GiB:raise ExportLimit('Кэш выбранных глав превышает 1 ГБ.')
            if shutil.disk_usage(self.root).free<self.reserve+len(data):raise ExportLimit('На сервере недостаточно места для страниц.')
            path.write_bytes(data);return self._snapshot(job)
    def put_segment(self,owner,identity,index,data):
        from staged_video import path
        with self.lock:
            job=self._owned(owner,identity)
            if job.state!='staging' or not job.staged:raise ExportLimit('Приём сегментов уже завершён.')
            if not 0<=index<len(job.staged['files']):raise ValueError('Такого сегмента в серии нет.')
            if not data:raise ValueError('Источник вернул пустой сегмент.')
            sizes=job.staged['sizes'];total=sum(sizes.values())-sizes.get(index,0)+len(data)
            if total>2*GiB:raise ExportLimit('Серия превышает 2 ГБ. Выбери качество ниже.')
            if shutil.disk_usage(self.root).free<self.reserve+2*len(data):raise ExportLimit('На сервере недостаточно места для серии.')
            target=path(job.directory,job.staged,index);target.parent.mkdir(mode=0o700,exist_ok=True)
            target.write_bytes(data);sizes[index]=len(data)
            # A slow uplink keeps the job alive while segments keep arriving.
            job.expires=max(job.expires,self.clock()+self.ttl)
            return {'id':job.id,'state':job.state,'segments':{'received':len(sizes),'total':len(job.staged['files'])}}
    def take(self,owner,identity,directory):
        """Hand a finished staged MP4 to the Drive import worker (same volume, a rename)."""
        with self.condition:
            job=self._owned(owner,identity)
            if job.state!='done' or not job.file or not job.file.is_file() or job.leases:raise ExportProblem('Серия из браузера ещё не собрана или уже сохранена.')
            target=Path(directory)/'episode.mp4';shutil.move(str(job.file),target)
            job.state='taken';job.progress={'phase':'taken'};job.file=None;job.capability=''
            self._cleanup();self.condition.notify_all();return target
    def enqueue(self,owner,identity):
        with self.condition:
            job=self._owned(owner,identity)
            if job.state!='staging':return self._snapshot(job)
            if job.staged:
                from staged_video import missing
                if missing(job.directory,job.staged):raise ValueError('Браузер передал не все сегменты серии.')
                job.state='queued';job.progress={'phase':'queued'};self.condition.notify_all();return self._snapshot(job)
            if any(not cached_path(job,v['chapter'],v['page'],source).is_file() for group,source in [('cached',False),('originals',True)] for v in job.manga[group]):raise ValueError('Загружены не все страницы главы.')
            job.state='queued';job.progress={'phase':'queued'};self.condition.notify_all();return self._snapshot(job)
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
            if not job or (not job.pipe_to_device and (not job.file or not job.file.is_file())):raise ExportMissing()
            if job.pipe_to_device:
                if job.leases:raise ExportLimit('Этот файл уже передаётся.')
                job.cancel.clear()
                job.expires=max(job.expires,self.clock()+4*3600)
            job.leases+=1;return job,self._snapshot(job)
    def release(self,job,completed=False,aborted=False):
        with self.lock:
            job.leases=max(0,job.leases-1)
            if completed and not job.leases and job.state=='done':
                job.state='downloaded';job.capability='';job.file=None;self._remove(job.directory)
            elif aborted and job.pipe_to_device and not job.leases:
                job.expires=min(job.expires,self.clock()+self.ttl)
                self._remove(job.directory)
            self._cleanup()
    def _worker(self):
        while True:
            with self.condition:
                self._cleanup()
                if self.stopping:return
                job=next((j for j in self.jobs.values() if j.state=='queued'),None)
                if job is None:self.condition.wait(timeout=10);continue
                job.state='running';job.running=True;job.progress={'phase':'preparing'};job.directory.mkdir(mode=0o700,exist_ok=True)
                if job.alloha and job.alloha_importer:job.expires=max(job.expires,self.clock()+3*3600+600)
            def progress(value):
                if job.cancel.is_set():raise ExportCancelled()
                with self.lock:
                    job.progress={k:v for k,v in value.items() if k in {'phase','message','page','chapter','chaptersTotal','loaded','total','downloadedBytes','pagesLoaded','pagesTotal'} and isinstance(v,(str,int,float))}
            try:
                streaming=job.alloha and job.alloha_importer
                free=max(0,shutil.disk_usage(self.root).free-self.reserve-128*1024**2)
                maximum=min(12*GiB if streaming else GiB if job.kind=='manga' else 2*GiB,free if streaming else free//2)
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
                    job.error=str(error) if isinstance(error,(ExportProblem,SourceError)) else 'Источник не предоставил проверенный файл. Проверь главу или серию и повтори.'
            finally:
                with self.condition:
                    job.running=False;self._cleanup();self.condition.notify_all()
    def close(self):
        with self.condition:
            self.stopping=True
            for job in self.jobs.values():
                if job.running or job.state in {'queued','staging'} or job.pipe_to_device and job.leases:job.cancel.set()
            self.condition.notify_all()
        if self.thread.is_alive():self.thread.join(timeout=6)

_manager=None;_manager_lock=threading.Lock()
def manager():
    global _manager
    with _manager_lock:
        if _manager is None:_manager=Exports(os.getenv('DATA_DIR','/data'))
        return _manager

class StagedTrack(BaseModel):
    model_config=ConfigDict(extra='forbid')
    url:str=Field(max_length=8192)
    text:str=Field(max_length=4*1024*1024)

class StagedStream(BaseModel):
    model_config=ConfigDict(extra='forbid')
    video:StagedTrack
    audio:StagedTrack|None=None

class ExportRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    url:str=Field(default='',max_length=8192)
    referer:str|None=Field(default=None,max_length=8192)
    kind:str=Field(pattern='^(video|manga)$')
    quality:str=Field(default='best',pattern='^(best|[1-9][0-9]{1,3})$')
    manga:MangaOptions|None=None
    stream:StagedStream|None=None
    name:str=Field(default='',max_length=120)
    alloha_mode:Literal['bnsi','browser']|None=Field(default=None,alias='allohaMode')

def install(app,owner):
    @app.post('/online/exports',status_code=202)
    def create_export(body:ExportRequest,subject=Depends(owner)):
        try:return manager().start(subject,body.url,body.kind,body.quality,referer=body.referer,manga=body.manga.model_dump() if body.manga else None,
                                   stream=body.stream.model_dump() if body.stream else None,name=body.name,
                                   alloha_mode=body.alloha_mode,alloha_importer=getattr(app.state,'alloha_importer',None))
        except (ValueError,SourceError) as error:raise HTTPException(422,str(error)) from None
        except ExportLimit as error:raise HTTPException(429,str(error)) from None
    @app.put('/online/exports/{identity}/pages/{chapter}/{page}')
    async def upload_cached_page(identity:str,chapter:int,page:int,request:Request,subject=Depends(owner)):
        data=await request.body()
        if len(data)>30*1024**2:raise HTTPException(413,'Страница превышает 30 МБ.')
        try:return await run_in_threadpool(manager().put_page,subject,identity,chapter,page,data,request.query_params.get('source')=='1')
        except (ValueError,SourceError) as error:raise HTTPException(422,str(error)) from None
        except ExportMissing:raise HTTPException(404,'Задание скачивания не найдено.') from None
        except ExportLimit as error:raise HTTPException(429,str(error)) from None
    @app.put('/online/exports/{identity}/segments/{index}')
    async def upload_segment(identity:str,index:int,request:Request,subject=Depends(owner)):
        data=await request.body()
        if len(data)>30*1024**2:raise HTTPException(413,'Сегмент превышает 30 МБ.')
        try:return await run_in_threadpool(manager().put_segment,subject,identity,index,data)
        except (ValueError,SourceError) as error:raise HTTPException(422,str(error)) from None
        except ExportMissing:raise HTTPException(404,'Задание скачивания не найдено.') from None
        except ExportLimit as error:raise HTTPException(429,str(error)) from None
    @app.post('/online/exports/{identity}/start')
    def start_staged_export(identity:str,subject=Depends(owner)):
        try:return manager().enqueue(subject,identity)
        except ValueError as error:raise HTTPException(422,str(error)) from None
        except ExportMissing:raise HTTPException(404,'Задание скачивания не найдено.') from None
    @app.get('/online/exports/file/{capability}')
    def export_file(capability:str):
        try:job,value=manager().acquire(capability)
        except ExportMissing:raise HTTPException(410,'Ссылка скачивания истекла. Открой готовое задание снова.') from None
        except ExportLimit as error:raise HTTPException(429,str(error)) from None
        if job.pipe_to_device:
            try:
                video=job.alloha_importer.stream(job.url,job.directory,quality=job.quality,referer=job.referer,
                                                 mode=job.alloha_mode,cancelled=job.cancel.is_set)
                opened=video.opened()
                opened.__enter__()
            except Exception as error:
                manager().release(job,aborted=True)
                raise HTTPException(502,str(error) if isinstance(error,SourceError) else 'Alloha не подготовил видео.') from None
            return AllohaDownloadResponse(job,manager(),value['filename'],video,opened)
        try:
            mime={'pdf':'application/pdf','zip':'application/zip','cbz':'application/vnd.comicbook+zip'}[job.manga['format']] if job.manga else 'application/vnd.comicbook+zip' if job.kind=='manga' else 'video/mp4'
            return LeaseFileResponse(job.file,filename=value['filename'],media_type=mime,
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
