"""The reader's narration director on Oracle, in a source-isolated browser.

narration-export.html runs src/tts/chapter-script.js unchanged: the title
bible, the role pass (Gemini Lite / Gemma through the owner's server key pool)
and the cast. The answer is the chapter's multi-voice script; ranobe_audiobook
voices it. One persistent profile per owner keeps the book's bible and the
chapters' roles between chapters, as the reader's own browser does.
"""
import asyncio
import hashlib
import mimetypes
import os
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests
from source_parser import SourceError

_locks = {}
_guard = threading.Lock()


def _lock(owner):
    with _guard:
        return _locks.setdefault(owner, threading.Lock())


def chapter_script(owner, paragraphs, *, book_key, chapter_key, meta, direction, cancelled=None, timeout=1500):
    """{rows: [{text, voice, style, pause, kind}], analysis, stats} for one chapter."""
    with _lock(owner):
        return asyncio.run(_script(owner, paragraphs, book_key, chapter_key, meta, direction, cancelled, timeout))


async def _script(owner, paragraphs, book_key, chapter_key, meta, direction, cancelled, timeout):
    from playwright.async_api import async_playwright
    from api import session_token
    from browser_player import browser_paths

    assets = Path(os.environ.get('MANGA_EXPORT_ASSETS', '/app/export-assets')).resolve()
    if not (assets / 'narration-export.html').is_file():
        raise SourceError('Режиссёр озвучки ещё не установлен на ВМ.')
    browser_paths()
    profile = Path(os.environ.get('DATA_DIR', '/data')) / '.codex-local' / 'narration-browser' / hashlib.sha256(owner.encode()).hexdigest()
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    origin = 'http://127.0.0.1:17863'
    headers = {'Authorization': 'Bearer ' + session_token(owner)}
    deadline = time.monotonic() + timeout

    def check():
        if cancelled and cancelled():
            raise SourceError('Импорт отменён владельцем.')
        if time.monotonic() > deadline:
            raise SourceError('Разметка ролей главы заняла слишком много времени.')

    def google(path, body):
        check()
        if path != '/reader/google/generate':
            raise SourceError('Неподдерживаемый запрос режиссёра озвучки.')
        response = requests.post('http://127.0.0.1:7860' + path, headers=headers, json=body, timeout=(4, 150))
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code != 200:
            # The page's generate() reads «повтор через N» to wait out minute limits.
            retry = response.headers.get('Retry-After')
            detail = str(data.get('detail') or 'Google не ответил режиссёру озвучки.')[:350]
            raise RuntimeError(detail + (f' · повтор через {retry}' if retry and retry.isdigit() else ''))
        return data

    async def google_request(path, body):
        return await asyncio.to_thread(google, path, body)

    async with async_playwright() as driver:
        context = await driver.chromium.launch_persistent_context(
            str(profile), executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'),
            headless=True, accept_downloads=False, service_workers='block',
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking'])
        try:
            async def route(request):
                url = urlsplit(request.request.url)
                if request.request.url.startswith(origin + '/'):
                    target = (assets / unquote(url.path).lstrip('/')).resolve()
                    if target.is_relative_to(assets) and target.is_file():
                        return await request.fulfill(body=target.read_bytes(), content_type=mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
                    return await request.fulfill(status=404, body='')
                # Nothing else: model calls use the fixed binding below.
                return await request.abort()
            await context.route('**/*', route)
            page = await context.new_page()
            await page.expose_function('exportGoogleRequest', google_request)
            await page.goto(origin + '/narration-export.html')
            await page.wait_for_function('typeof window.narrationScript==="function"')
            task = await page.evaluate_handle('args => { const state={done:false}; window.narrationScript(args).then(value=>{state.value=value;state.done=true;},error=>{state.error=String(error&&error.message||error);state.done=true;}); return state; }',
                                              {'paragraphs': paragraphs, 'bookKey': book_key, 'chapterKey': chapter_key, 'meta': meta, 'direction': direction})
            while not await task.evaluate('state=>state.done'):
                check()
                await page.wait_for_timeout(250)
            error = await task.evaluate('state=>state.error||""')
            if error:
                raise SourceError(error[:350])
            return await task.evaluate('state=>state.value')
        finally:
            await context.close()
