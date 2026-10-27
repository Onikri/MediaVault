"""Bounded chapter → CBZ pipeline on the import server, with an encrypted preview."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import threading
import zipfile
from manga_sources import parse_pages,site_for
from source_parser import SourceError

def image_extension(header):
    if header.startswith(b'\xff\xd8\xff'):return 'jpg'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):return 'png'
    if header.startswith((b'GIF87a',b'GIF89a')):return 'gif'
    if header[:4]==b'RIFF' and header[8:12]==b'WEBP':return 'webp'
    if header[4:8]==b'ftyp' and header[8:12] in {b'avif',b'avis'}:return 'avif'
    return None

def download_chapter(url,temporary,http,progress=lambda _:None,quality='best'):
    if not site_for(url):raise SourceError('Эта читалка пока не поддерживается.')
    if site_for(url).family in {'lib','dex','naver','mangaraw','sen','toonkor'}:
        from manga_sources import inspect
        data=inspect(url,http);final=data['url'];pages=data['pages']
    else:
        text,final,_=http.document(url)
        if not site_for(final):raise SourceError('Глава перенаправила на другую читалку.')
        pages=parse_pages(text,final)
    if not pages or len(pages)>500:raise SourceError('В открытой главе не найдены изображения или превышен лимит 500 страниц.')
    output=Path(temporary)/'chapter.cbz';local=threading.local();clients=[];lock=threading.Lock()
    def download(entry):
        index,url=entry
        if not hasattr(local,'http'):
            local.http=http.fork() if hasattr(http,'fork') else http
            if local.http is not http:
                with lock:clients.append(local.http)
        target=Path(temporary)/f'page-{index:04d}'
        local.http.download(url,target,headers={'Referer':final},maximum=30*1024*1024)
        with target.open('rb') as source:extension=image_extension(source.read(32))
        if not extension:raise SourceError('Читалка вернула заглушку вместо изображения страницы.')
        if quality in {'1280','1920'}:
            packed=target.with_suffix('.jpg')
            result=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(target),'-frames:v','1','-vf',"scale='min("+quality+",iw)':-2",'-q:v','4','-threads','1',str(packed)],capture_output=True,timeout=20,check=False)
            if result.returncode:raise SourceError('Не удалось сжать страницу. Выбери оригинальное качество.')
            target.unlink();target=packed;extension='jpg'
        return index,target,extension
    workers=3 if hasattr(http,'fork') else 1
    try:
        progress({'phase':'downloading','pagesLoaded':0,'pagesTotal':len(pages)})
        with ThreadPoolExecutor(max_workers=workers) as pool,zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
            # Only one small batch is in flight, including on cancel or a slow page.
            for start in range(0,len(pages),workers):
                batch=list(enumerate(pages[start:start+workers],start+1))
                for index,target,extension in pool.map(download,batch):
                    archive.write(target,f'{index:04d}.{extension}');target.unlink()
                    if output.stat().st_size>1024**3:raise SourceError('Глава превышает лимит 1 ГБ.')
                    progress({'phase':'downloading','pagesLoaded':index,'pagesTotal':len(pages)})
        return output
    finally:
        for client in clients:client.close()

def chapter_preview(path):
    try:
        with zipfile.ZipFile(path) as archive:
            entry=next(v for v in archive.infolist() if not v.is_dir() and v.file_size<=30*1024*1024)
            data=archive.read(entry)
        result=subprocess.run(['ffmpeg','-nostdin','-v','error','-i','pipe:0','-frames:v','1','-vf',"scale='min(640,iw)':-2",'-q:v','4','-threads','1','-f','image2pipe','-vcodec','mjpeg','-'],input=data,capture_output=True,timeout=12,check=False)
        return result.stdout if result.returncode==0 and result.stdout.startswith(b'\xff\xd8\xff') and len(result.stdout)<=500000 else None
    except (OSError,ValueError,StopIteration,zipfile.BadZipFile,subprocess.SubprocessError):return None
