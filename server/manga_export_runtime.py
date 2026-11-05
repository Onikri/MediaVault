"""Run the unchanged reader renderer on Oracle using a source-isolated browser."""
import asyncio
import base64
import hashlib
import mimetypes
import os
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests
from source_parser import SourceError


class GatewayRetry(SourceError):
    def __init__(self, message, seconds):
        super().__init__(message)
        self.seconds = seconds


def translate_pages(job, pages, options, skip, save, progress, budget):
    return asyncio.run(_translate_pages(job, pages, options, skip, save, progress, budget))


async def _translate_pages(job, pages, options, skip, save, progress, budget):
    from playwright.async_api import async_playwright
    from api import session_token
    from browser_player import browser_paths

    assets = Path(os.environ.get('MANGA_EXPORT_ASSETS', '/app/export-assets')).resolve()
    if not (assets / 'manga-export.html').is_file():
        raise SourceError('Модуль перевода перед скачиванием ещё не установлен на ВМ.')
    browser_paths()
    profile = Path(os.environ.get('DATA_DIR', '/data')) / '.codex-local' / 'export-browser' / hashlib.sha256(job.owner.encode()).hexdigest()
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    origin = 'http://127.0.0.1:17862'
    headers = {'Authorization': 'Bearer ' + session_token(job.owner)}
    def google(path, body):
        budget.check()
        if path not in {'/reader/google/keys', '/reader/google/generate'}:
            raise SourceError('Неподдерживаемый запрос переводчика.')
        response = requests.request('GET' if path.endswith('/keys') else 'POST',
                                   'http://127.0.0.1:7860' + path, headers=headers,
                                   json=body if not path.endswith('/keys') else None, timeout=(4, 150))
        data = response.json()
        if response.status_code != 200:
            if response.status_code in {429, 502, 503, 504}:
                try:
                    delay = max(1, min(300, float(response.headers.get('Retry-After', '6'))))
                except (TypeError, ValueError):
                    delay = 6
                raise GatewayRetry(str(data.get('detail') or 'Google временно занят.')[:350], delay)
            raise SourceError(str(data.get('detail') or 'Google не завершил перевод.')[:350])
        return data
    async def google_request(path, body):
        for attempt in range(3):
            try:
                return await asyncio.to_thread(google, path, body)
            except GatewayRetry as error:
                if attempt==2:
                    raise
                progress({'phase':'translating','message':f'Google временно занят · повтор через {error.seconds:g} с'})
                until=time.monotonic()+error.seconds
                while time.monotonic()<until:
                    budget.check()
                    await asyncio.sleep(min(.2,max(0,until-time.monotonic())))
    keys = await google_request('/reader/google/keys', {})
    slots = [s['slot'] for s in keys.get('slots', []) if s.get('configured') and options['directModel'] in s.get('availableModels', [])]
    if not slots:
        raise SourceError('Добавь в профиле серверный ключ Google для выбранной модели.')
    async with async_playwright() as driver:
        context = await driver.chromium.launch_persistent_context(
            str(profile), executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'),
            headless=True, accept_downloads=False, service_workers='block',
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking'])
        try:
            async def route(request):
                budget.check()
                url = urlsplit(request.request.url)
                if request.request.url.startswith(origin + '/'):
                    target = (assets / unquote(url.path).lstrip('/')).resolve()
                    if target.is_relative_to(assets) and target.is_file():
                        return await request.fulfill(body=target.read_bytes(), content_type=mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
                    return await request.fulfill(status=404, body='')
                # Public model weights only. API calls use the fixed binding.
                host = url.hostname or ''
                if request.request.method in {'GET', 'HEAD'} and url.scheme == 'https' and not url.username and (
                    host in {'huggingface.co', 'hf.co'} or host.endswith(('.hf.co', '.huggingface.co'))
                ):
                    return await request.continue_()
                return await request.abort()
            await context.route('**/*', route)
            page = await context.new_page()
            await page.expose_function('exportGoogleRequest', google_request)
            await page.expose_function('exportSourcePage', lambda index: base64.b64encode(pages[index]).decode() if type(index) is int and 0 <= index < len(pages) else '')
            await page.expose_function('exportRenderedPage', lambda index, image: save(index, base64.b64decode(image, validate=True)))
            await page.expose_function('exportPageProgress', lambda index, value: progress({'phase': 'translating', 'page': index + 1, 'message': str(value.get('message') or 'Перевод и оформление')[:250]}))
            await page.goto(origin + '/manga-export.html')
            await page.wait_for_function('typeof window.translateExportChapter==="function"')
            task = await page.evaluate_handle('args => { const state={done:false}; window.translateExportChapter(args).then(()=>state.done=true,error=>{state.error=error.message;state.done=true}); return state; }',
                                        {'count': len(pages), 'options': options, 'slots': slots, 'skip': skip})
            while not await task.evaluate('state=>state.done'):
                budget.check()
                await page.wait_for_timeout(200)
            error = await task.evaluate('state=>state.error')
            if error:
                raise SourceError(str(error)[:350])
        finally:
            await context.close()
