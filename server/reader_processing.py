# SPDX-License-Identifier: AGPL-3.0-or-later
"""Owner-scoped volatile processing queue with progress and real cancellation."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import os
import secrets
import time
from pathlib import Path
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from lmt_runtime import LmtRuntime
from manga_upscale import ProcessingCancelled, Upscaler, model_catalog, read_image

MAX_IMAGE = 10 * 1024 * 1024
TTL = 600
MAX_RESULTS = 128 * 1024 * 1024


class Box(BaseModel):
    model_config = ConfigDict(extra='ignore')
    x1: float = Field(ge=0,le=100000,allow_inf_nan=False)
    y1: float = Field(ge=0,le=100000,allow_inf_nan=False)
    x2: float = Field(ge=0,le=100000,allow_inf_nan=False)
    y2: float = Field(ge=0,le=100000,allow_inf_nan=False)
    confidence: float = Field(default=1,ge=0,le=1)


class ProcessOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    translate: bool = False
    upscale: bool = False
    operation: Literal['process','detect','translate','inpaint'] = 'process'
    boxes: list[Box] | None = Field(default=None,max_length=100)
    gateForce: bool = False
    language: str = Field(default='English', max_length=40)
    targetLanguage: str = Field(default='Russian', max_length=40)
    ocr: str = Field(default='paddle', pattern=r'^(paddle|ppocrv6-manga|manga-ocr|pororo)$')
    detector: str = Field(default='comic-bubble', pattern=r'^(comic-bubble|comic-text-detector)$')
    inpaint: str = Field(default='fast', pattern=r'^(fast|quality)$')
    allowDownloads: bool = False
    contextKey: str = Field(default='default', max_length=200)
    scale: int = Field(default=2, ge=1, le=4)
    model: str = Field(default='auto', max_length=200)
    content: str = Field(default='auto', pattern=r'^(auto|mono|color)$')
    tile: int = Field(default=256, ge=64, le=512)


class ProcessBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    image: str = Field(min_length=20, max_length=14 * 1024 * 1024)
    options: ProcessOptions


class Processor:
    def __init__(self, directory):
        directory = Path(directory)
        assets = os.getenv('LMT_ASSETS_DIR', str(Path(__file__).resolve().parents[1] / 'dist' / 'lmt'))
        self.lmt = LmtRuntime(assets, directory / 'lmt-browser')
        self.upscaler = Upscaler(os.getenv('MANGAJANAI_MODEL_DIR', str(directory / 'mangajanai')), os.getenv('MANGAJANAI_DEVICE', 'auto'))
        self.jobs = {}
        self.queue = asyncio.Queue(maxsize=4)
        self.worker = self.active = self.janitor = None

    def cleanup(self):
        for key, job in list(self.jobs.items()):
            if job['state'] in {'done', 'error', 'cancelled'} and job['updated'] < time.monotonic() - TTL:
                del self.jobs[key]
        completed = sorted(((key, job) for key, job in self.jobs.items() if job['state'] in {'done', 'error', 'cancelled'}), key=lambda row:row[1]['updated'])
        retained = sum(sum(len(job.get('result', {}).get(field, '')) for field in ('renderedImage','cleanedImage')) for _, job in completed)
        while completed and (retained > MAX_RESULTS or len(self.jobs) >= 16):
            key, job = completed.pop(0)
            retained -= sum(len(job.get('result', {}).get(field, '')) for field in ('renderedImage','cleanedImage'))
            self.jobs.pop(key, None)

    async def _expire(self):
        while True:
            await asyncio.sleep(30)
            self.cleanup()

    def get(self, job_id, subject):
        self.cleanup()
        job = self.jobs.get(job_id)
        if not job or job['subject'] != subject:
            raise HTTPException(404, 'Задание не найдено или срок результата истёк.')
        return job

    def submit(self, data, options, subject):
        self.cleanup()
        if sum(j['state'] in {'queued', 'running'} for j in self.jobs.values()) >= 5 or len(self.jobs) >= 16:
            raise HTTPException(429, 'Очередь обработки заполнена. Подожди завершения страниц.')
        if self.queue.full():
            raise HTTPException(429, 'Очередь обработки заполнена.')
        job_id = secrets.token_urlsafe(24)
        self.jobs[job_id] = {'subject': subject, 'state': 'queued', 'status': 'Ожидаем обработку',
                             'data': data, 'options': options, 'updated': time.monotonic(), 'cancel': False}
        self.queue.put_nowait(job_id)
        if not self.worker or self.worker.done():
            self.worker = asyncio.create_task(self._worker())
        if not self.janitor or self.janitor.done():
            self.janitor = asyncio.create_task(self._expire())
        return job_id

    def cancel(self, job):
        job['cancel'] = True
        job.pop('result', None)
        job['data'] = b''
        if job['state'] != 'running':
            job.update(state='cancelled', updated=time.monotonic(), status='Отменено')

    async def _worker(self):
        while not self.queue.empty():
            job_id = await self.queue.get()
            job = self.jobs[job_id]
            try:
                if job['cancel']:
                    continue
                job.update(state='running', updated=time.monotonic())
                self.active = asyncio.create_task(self._process(job))
                started = time.monotonic()
                while not self.active.done():
                    if job['cancel'] or time.monotonic() - started > 900:
                        job['cancel'] = True
                        # Torch finishes its current tile before memory is released.
                        if job['options']['translate'] and not job.get('upscaling'):
                            self.active.cancel()
                        break
                    await asyncio.sleep(.1)
                result = await self.active
                if job['cancel']:
                    raise ProcessingCancelled()
                job.update(state='done', result=result, status='Готово')
            except (ProcessingCancelled, asyncio.CancelledError):
                job.update(state='cancelled', status='Отменено')
            except Exception as error:
                # Never return prompts, provider replies, keys or image payloads.
                message = str(error) if isinstance(error, ValueError) else 'Обработка не завершена. Проверь модели и локальный LLM на backend.'
                job.update(state='error', status=message[:300])
            finally:
                job['data'] = b''
                job['updated'] = time.monotonic()
                self.cleanup()
                self.active = None
                self.queue.task_done()

    async def _process(self, job):
        options = job['options']
        data = job['data']
        image = await asyncio.to_thread(read_image, data)
        result = {'regions': []}
        def progress(status):
            job['status'] = status
        if options['translate']:
            progress('Запускаем Libre Manga Translator на backend')
            config = {**options, 'contextKey': hashlib.sha256((job['subject'] + ':' + options['contextKey']).encode()).hexdigest()}
            result = await self.lmt.run(data, config, progress)
        if options['upscale']:
            job['upscaling'] = True
            # OCR uses the original. Upscale cleaned artwork, then typeset at
            # output resolution, keeping neural reconstruction away from glyphs.
            if result.get('cleanedImage'):
                image = await asyncio.to_thread(read_image, base64.b64decode(result['cleanedImage']))
            image, info = await asyncio.to_thread(self.upscaler.run, image, options, progress, lambda: job['cancel'])
            result['upscale'] = info
            output = io.BytesIO()
            image.save(output, format='WEBP', quality=95)
            rendered = await self.lmt.typeset(output.getvalue(), result['regions'], info['scale']) if result.get('regions') else base64.b64encode(output.getvalue()).decode()
            result.update(renderedImage=rendered, renderedMime='image/webp')
        if options['operation'] != 'inpaint':
            result.pop('cleanedImage', None)
        return result

    async def close(self):
        for job in self.jobs.values():
            self.cancel(job)
        if self.worker:
            await self.worker
        if self.janitor:
            self.janitor.cancel()
            try:
                await self.janitor
            except asyncio.CancelledError:
                pass
        self.jobs.clear()
        await self.lmt.close()


def install(app, data_dir, owner):
    processor = Processor(data_dir)
    app.state.reader_processor = processor

    @app.get('/reader/processing')
    def status():
        models = model_catalog(processor.upscaler.directory)
        return {'lmt': processor.lmt.status(), 'upscale': {'ready': bool(models), 'models': models},
                'source': 'https://github.com/Onikri/MediaVault', 'resultLifetimeSeconds': TTL}

    @app.post('/reader/jobs', status_code=202)
    async def submit(body: ProcessBody, subject=Depends(owner)):
        options = body.options.model_dump()
        if not (options['translate'] or options['upscale']):
            raise HTTPException(422, 'Выбери перевод или апскейл.')
        if options['scale'] not in (1, 2, 4):
            raise HTTPException(422, 'Масштаб должен быть 1, 2 или 4.')
        if options['translate'] and not options['allowDownloads']:
            raise HTTPException(422, 'Разреши подготовку моделей LMT.')
        needs_llm = options['operation'] in {'process','translate'}
        if options['translate'] and not processor.lmt.status()['ready' if needs_llm else 'assetsReady']:
            raise HTTPException(503, 'LMT ещё не настроен на backend.')
        if options['upscale'] and not model_catalog(processor.upscaler.directory):
            raise HTTPException(503, 'Модели MangaJaNai ещё не установлены на backend.')
        try:
            data = base64.b64decode(body.image, validate=True)
        except ValueError:
            raise HTTPException(422, 'Некорректная страница.') from None
        if len(data) > MAX_IMAGE:
            raise HTTPException(413, 'Страница превышает 10 МБ.')
        return {'id': processor.submit(data, options, subject)}

    @app.get('/reader/jobs/{job_id}')
    async def poll(job_id: str, subject=Depends(owner)):
        job = processor.get(job_id, subject)
        return {'state': job['state'], 'status': job['status'],
                **({'result': job['result']} if job['state'] == 'done' else {})}

    @app.post('/reader/jobs/{job_id}/cancel')
    async def cancel(job_id: str, subject=Depends(owner)):
        processor.cancel(processor.get(job_id, subject))
        return {'state': 'cancelling'}

    return processor
