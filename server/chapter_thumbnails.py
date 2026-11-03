"""Owner-scoped small chapter previews. Original pages exist only in memory."""
import base64
import hashlib
from io import BytesIO
import os
from pathlib import Path
import threading
import time
import warnings
from fastapi import Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from PIL import Image,ImageOps
from manga_inspection import inspect
from source_parser import PublicHttp,SourceError

MAX_IMAGE=30*1024*1024


def thumbnail(raw):
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(BytesIO(raw)) as original:
            if original.width*original.height>40_000_000:raise SourceError('Слишком большая страница для превью.')
            image=ImageOps.exif_transpose(original).convert('RGB')
            try:
                # A tall webtoon is represented by its top panel, not a one-pixel strip.
                height=min(image.height,round(image.width*9/16))
                crop=image.crop((0,0,image.width,height))
                try:
                    crop.thumbnail((320,180),Image.Resampling.LANCZOS)
                    output=BytesIO();crop.save(output,'JPEG',quality=76,optimize=True)
                    return output.getvalue()
                finally:crop.close()
            finally:image.close()


def first_image(url):
    info=inspect(url)
    pages=info.get('pages') or []
    if not pages:raise SourceError('Источник пока не предоставил страницы этой главы.')
    from suwayomi_bridge import parse_reference,page_image
    target=info.get('thumbnail') or pages[0]
    if parse_reference(target):return page_image(target)[0]
    http=PublicHttp(timeout=(3,10),deadline=time.monotonic()+18)
    response=None
    try:
        response,_=http._open(target,headers={'Referer':info.get('url') or url})
        data=bytearray();deadline=time.monotonic()+18
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data)>MAX_IMAGE or time.monotonic()>deadline:raise SourceError('Страница слишком велика для превью.')
        return bytes(data)
    finally:
        if response is not None:response.close()
        http.close()


class ChapterThumbnails:
    def __init__(self,directory):
        self.directory=Path(directory);self.lock=threading.RLock();self.pending={};self.slots=threading.BoundedSemaphore(2)

    def get(self,subject,url):
        key=hashlib.sha256(('v1\0'+subject+'\0'+url).encode()).hexdigest()
        path=self.directory/(key+'.jpg')
        with self.lock:
            if path.is_file() and path.stat().st_mtime>time.time()-30*86400:return self.result(path.read_bytes(),True)
            pending=self.pending.get(key)
            if pending is None:
                if len(self.pending)>=32:raise HTTPException(429,'Дождись загрузки видимых превью.')
                pending=self.pending[key]={'event':threading.Event()};leader=True
            else:leader=False
        if not leader:
            if not pending['event'].wait(45):raise HTTPException(503,'Превью пока не готово.')
            if 'image' not in pending:raise HTTPException(503,'Источник не вернул превью.')
            return self.result(pending['image'],True)
        acquired=False
        try:
            acquired=self.slots.acquire(blocking=False)
            if not acquired:raise HTTPException(429,'Дождись загрузки видимых превью.')
            image=thumbnail(first_image(url))
            if len(image)>100000:raise SourceError('Миниатюра превысила размер кэша.')
            self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
            temporary=path.with_suffix('.tmp');temporary.write_bytes(image);os.chmod(temporary,0o600);temporary.replace(path)
            with self.lock:
                pending['image']=image
                for old in sorted(self.directory.glob('*.jpg'),key=lambda p:p.stat().st_mtime)[:-512]:old.unlink(missing_ok=True)
            return self.result(image,False)
        except (SourceError,ValueError,OSError,Image.DecompressionBombWarning,Image.DecompressionBombError):
            raise HTTPException(502,'Миниатюра пока недоступна. Главу можно открыть отдельно.') from None
        finally:
            if acquired:self.slots.release()
            with self.lock:self.pending.pop(key,None);pending['event'].set()

    @staticmethod
    def result(image,cached):
        return {'image':'data:image/jpeg;base64,'+base64.b64encode(image).decode(),'cached':cached}


def install(app,owner):
    service=ChapterThumbnails(os.getenv('CHAPTER_THUMBNAIL_CACHE_DIR',str(Path(__file__).resolve().parent/'.codex-local'/'chapter-thumbnails')))
    class Request(BaseModel):
        model_config=ConfigDict(extra='forbid')
        url:str=Field(min_length=1,max_length=8192)
    @app.post('/manga/thumbnail')
    def get(body:Request,subject=Depends(owner)):return service.get(str(subject),body.url)
