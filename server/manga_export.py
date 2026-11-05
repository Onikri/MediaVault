"""Chapter/volume packaging and translation with a private encrypted page cache."""
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import time
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from source_parser import SourceError


class Chapter(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(min_length=1, max_length=8192)
    number: float = Field(default=1, ge=0, le=100000)
    volume: int = Field(default=1, ge=0, le=10000)
    title: str = Field(default='', max_length=200)
    pageCount: int = Field(default=0, ge=0, le=1500)


class Translation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    directModel: Literal['gemini-3.5-flash-lite','gemini-3.1-flash-lite','gemini-2.5-flash-lite','gemma-4-26b-a4b-it','gemma-4-31b-it'] = 'gemini-3.5-flash-lite'
    language: Literal['English','Japanese','Korean','Chinese (Simplified)'] = 'Japanese'
    direction: Literal['ltr','rtl'] = 'rtl'
    directInput: Literal['vision','annotated','blocks','coordinates'] = 'vision'
    directDetector: Literal['en-fast','rtdetr','ctd','yolo26n-manga','ppocrv6-det'] = 'rtdetr'
    directBatchPages: Literal[2,3] = 2
    inpaint: Literal['fast','quality','moebius','migan'] = 'fast'
    font: Literal['auto','comic-relief','balsamiq-sans','caveat','pangolin','neucha','ruslan-display','marck-script','press-start','pt-serif','system'] = 'auto'


class CachedPage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    chapter: int = Field(ge=0, le=99)
    page: int = Field(ge=0, le=1499)
    sourceHash: str = Field(default='', pattern=r'^(?:[a-f0-9]{64})?$')
    imageHash: str = Field(pattern=r'^[a-f0-9]{64}$')


class Options(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['original','translate','cached'] = 'original'
    format: Literal['cbz','zip','pdf'] = 'cbz'
    name: str = Field(default='Манга', min_length=1, max_length=180)
    chapters: list[Chapter] = Field(default_factory=list, max_length=100)
    cached: list[CachedPage] = Field(default_factory=list, max_length=1500)
    translation: Translation = Field(default_factory=Translation)


def verify_image(data):
    if not data or len(data) > 30 * 1024**2:
        raise SourceError('Готовая страница пуста или превышает 30 МБ.')
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 24_000_000:
                raise ValueError()
            image.verify()
    except Exception:
        raise SourceError('Готовая страница не является проверенным изображением до 24 Мп.') from None


def cached_path(job, chapter, page):
    return job.directory / f'cached-{chapter:03d}-{page:04d}.image'


class PageCache:
    def __init__(self, directory):
        self.root = Path(directory) / '.codex-local' / 'export-translations'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cipher = AESGCM((Path(directory) / 'service.key').read_bytes())
    def key(self, owner, source, config):
        return hashlib.sha256(owner.encode() + b'\0' + source + json.dumps({'version':1,**config},sort_keys=True).encode()).hexdigest()
    def read(self, identity):
        path = self.root / (identity + '.cache')
        try:
            if time.time() - path.stat().st_mtime > 7 * 86400:
                return None
            raw = path.read_bytes()
            return self.cipher.decrypt(raw[:12], raw[12:], identity.encode())
        except Exception:
            return None
    def write(self, identity, data):
        iv = secrets.token_bytes(12)
        path = self.root / (identity + '.cache')
        temporary = path.with_suffix('.part')
        temporary.write_bytes(iv + self.cipher.encrypt(iv, data, identity.encode()))
        temporary.chmod(0o600)
        temporary.replace(path)
        files = sorted(self.root.glob('*.cache'), key=lambda f:f.stat().st_mtime)
        total = sum(f.stat().st_size for f in files)
        for value in files:
            if total <= 512 * 1024**2 and time.time() - value.stat().st_mtime <= 7 * 86400:
                break
            total -= value.stat().st_size
            value.unlink(missing_ok=True)


def produce(job, http, budget, progress):
    from manga_download import download_chapter, image_extension
    from manga_export_runtime import translate_pages
    from pdf_export import write_pdf

    options = job.manga
    result = job.directory / ('manga.' + options['format'])
    cached = {(v['chapter'],v['page']):v for v in options['cached']}
    cache = PageCache(os.getenv('DATA_DIR','/data')) if options['mode']=='translate' else None
    output_pages = []
    total = 0
    page_count = 0
    chapters = options['chapters'] or [None]
    archive = zipfile.ZipFile(result,'w',compression=zipfile.ZIP_STORED) if options['format']!='pdf' else None
    try:
        for chapter_index, chapter in enumerate(chapters):
            budget.check()
            directory = job.directory / f'chapter-{chapter_index:03d}'
            directory.mkdir(exist_ok=True)
            available = sorted(p for c,p in cached if c==chapter_index)
            complete = chapter and chapter['pageCount']>0 and available==list(range(chapter['pageCount']))
            if chapter is None or complete or options['mode']=='cached':
                pages = sorted(p for c,p in cached if c==chapter_index)
                if pages != list(range(len(pages))) or not pages or chapter and not complete:
                    raise SourceError('Для сохранения из кэша нужны все страницы главы.')
                originals = None
            else:
                source = download_chapter(chapter['url'], directory, http, progress=lambda p:progress({**p,'chapter':chapter_index+1,'chaptersTotal':len(chapters)}), quality=job.quality)
                originals = zipfile.ZipFile(source)
                pages = [v for v in originals.infolist() if not v.is_dir() and v.file_size<=30*1024**2 and v.filename.lower().endswith(('.jpg','.jpeg','.png','.webp','.gif','.avif'))]
                pages.sort(key=lambda v:v.filename)
            class Pages:
                def __len__(self):return len(pages)
                def __getitem__(self,index):return originals.read(pages[index])
            identity = {}
            skip = []
            def save(index, data):
                budget.check()
                if type(index) is not int or not 0<=index<len(pages):
                    raise SourceError('Переводчик вернул неизвестную страницу.')
                verify_image(data)
                (directory / f'{index:04d}.image').write_bytes(data)
                if cache and index in identity:
                    cache.write(identity[index], data)
                progress({'phase':'translating','chapter':chapter_index+1,'chaptersTotal':len(chapters),'pagesTotal':len(pages),'pagesLoaded':len(list(directory.glob('*.image')))})
            try:
                for index in range(len(pages)):
                    budget.check()
                    raw = originals.read(pages[index]) if originals else None
                    if cache and raw is not None:
                        identity[index] = cache.key(job.owner,raw,options['translation'])
                    hit = cached.get((chapter_index,index))
                    data = cached_path(job,chapter_index,index).read_bytes() if hit and (raw is None or hit['sourceHash']==hashlib.sha256(raw).hexdigest()) else None
                    data = data or (cache.read(identity[index]) if index in identity else None)
                    if data:
                        verify_image(data)
                        (directory / f'{index:04d}.image').write_bytes(data)
                        skip.append(index)
                    elif options['mode']=='original':
                        (directory / f'{index:04d}.image').write_bytes(raw)
                        skip.append(index)
                    elif options['mode']=='cached':
                        raise SourceError('Глава переведена не полностью. Выбери перевод недостающих страниц.')
                if options['mode']=='translate' and len(skip)<len(pages):
                    progress({'phase':'translating','chapter':chapter_index+1,'chaptersTotal':len(chapters),'pagesLoaded':len(skip),'pagesTotal':len(pages)})
                    translate_pages(job, Pages(), options['translation'], skip, save, progress, budget)
                for index in range(len(pages)):
                    budget.check()
                    path = directory / f'{index:04d}.image'
                    data = path.read_bytes()
                    extension = image_extension(data[:32])
                    if not extension:
                        raise SourceError('Готовая глава содержит неподдерживаемую страницу.')
                    total += len(data)
                    page_count += 1
                    if total>budget.maximum or page_count>1500:
                        raise SourceError('Выбранные главы превышают лимит 1500 страниц или размер скачивания.')
                    if archive:
                        prefix = f'{chapter_index+1:03d}-chapter-{chapter["number"]:g}/' if len(chapters)>1 else ''
                        archive.write(path, prefix + f'{index+1:04d}.{extension}')
                    else:
                        output_pages.append(path)
                progress({'phase':'assembling','chapter':chapter_index+1,'chaptersTotal':len(chapters)})
            finally:
                if originals:
                    originals.close()
        if archive:
            archive.close()
        else:
            write_pdf(output_pages,result,budget)
        return result
    finally:
        if archive:
            archive.close()
