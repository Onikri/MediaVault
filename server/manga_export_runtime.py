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


STAGES = {'queued': 'в очереди', 'detecting': 'поиск текста', 'detected': 'текст размечен', 'translating': 'перевод Google',
          'cleaning': 'очистка фона и набор', 'error': 'ошибка, повторим'}


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
    slots = []
    def google(path, body):
        budget.check()
        if path not in {'/reader/google/keys', '/reader/google/generate', '/reader/lmt/fallback'}:
            raise SourceError('Неподдерживаемый запрос переводчика.')
        # Bubbles Google refused go to the private LMT worker (OCR + Hy-MT2) on
        # the same Docker network, with the export owner's session.
        base = os.environ.get('LMT_INTERNAL_URL', 'http://lmt:7861') if path == '/reader/lmt/fallback' else 'http://127.0.0.1:7860'
        response = requests.request('GET' if path.endswith('/keys') else 'POST',
                                   base.rstrip('/') + path, headers=headers,
                                   json=body if not path.endswith('/keys') else None,
                                   timeout=(4, 250 if path == '/reader/lmt/fallback' else 150))
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
        # The v4 pool-aware renderer delegates project cooldown/failover to the
        # gateway. Do not add a second sleep/slot-rotation loop around that call.
        if path.endswith('/generate') and body.get('pool'):
            return await asyncio.to_thread(google, path, body)
        for attempt in range(3):
            try:
                return await asyncio.to_thread(google, path, body)
            except GatewayRetry as error:
                if attempt==2:
                    raise
                if path.endswith('/generate') and len(slots)>1:
                    previous=body.get('slot')
                    position=slots.index(previous) if previous in slots else -1
                    body={**body,'slot':slots[(position+1)%len(slots)]}
                progress({'phase':'translating','message':f'Google временно занят · повтор через {error.seconds:g} с'})
                until=time.monotonic()+error.seconds
                while time.monotonic()<until:
                    budget.check()
                    await asyncio.sleep(min(.2,max(0,until-time.monotonic())))
    lmt = os.environ.get('LMT_INTERNAL_URL', 'http://lmt:7861').rstrip('/')
    def private_font_list():
        # The owner's licensed lettering faces live with the LMT worker, as for the reader.
        try:
            response = requests.get(lmt + '/reader/lmt/fonts', headers=headers, timeout=(4, 30))
            return response.json() if response.status_code == 200 else {'fonts': []}
        except (requests.RequestException, ValueError):
            return {'fonts': []}
    def private_font(index):
        if type(index) is not int or not 0 <= index < 40:
            return ''
        response = requests.get(f'{lmt}/reader/lmt/fonts/{index}', headers=headers, timeout=(4, 60))
        if response.status_code != 200 or len(response.content) > 4_000_000:
            raise SourceError('Шрифт владельца не получен с LMT.')
        return base64.b64encode(response.content).decode()
    # The stage of every page, as the reader shows it, for the job queue and the save dialog.
    total = len(pages)
    finished = set(skip)
    def stage_text(index, value):
        label = STAGES.get(str(value.get('phase') or ''), 'обработка')
        detail = str(value.get('message') or '').strip()
        line = f'Перевод на ВМ · готово {len(finished)} из {total} · стр. {index + 1}: {label}'
        return line, (f'Стр. {index + 1}: {label}' + (f' · {detail}' if detail else ''))[:250]
    def page_progress(index, value):
        if type(index) is not int or not isinstance(value, dict):
            return
        operation, message = stage_text(index, value)
        progress({'phase': 'translating', 'page': index + 1, 'pagesTotal': total, 'pagesLoaded': len(finished),
                  'stage': str(value.get('phase') or '')[:20], 'operation': operation, 'message': message})
    def rendered(index, image):
        save(index, base64.b64decode(image, validate=True))
        if type(index) is int:
            finished.add(index)
            progress({'phase': 'translating', 'page': index + 1, 'pagesTotal': total, 'pagesLoaded': len(finished), 'stage': 'saved',
                      'operation': f'Перевод на ВМ · готово {len(finished)} из {total}', 'message': f'Стр. {index + 1}: готова'})
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
            await page.expose_function('exportFontList', lambda: asyncio.to_thread(private_font_list))
            await page.expose_function('exportFont', lambda index: asyncio.to_thread(private_font, index))
            await page.expose_function('exportSourcePage', lambda index: base64.b64encode(pages[index]).decode() if type(index) is int and 0 <= index < len(pages) else '')
            await page.expose_function('exportRenderedPage', rendered)
            await page.expose_function('exportPageProgress', page_progress)
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
