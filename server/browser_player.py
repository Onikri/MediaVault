"""Ephemeral source-only Chromium for public JS/WebSocket players.

No user profile, Google session or persistent cookies. Every destination is
validated, including WebSockets; media URLs are read from actual browser events.
"""
import asyncio
import html
import os
import re
import shutil
import threading
import time
from urllib.parse import urlsplit
from source_parser import SourceError, public_url, playback_headers, BLOCKED

_slots=threading.BoundedSemaphore(1)


def observed_streams(value):
    if not isinstance(value,str) or len(value)>2*1024*1024:return []
    text=html.unescape(value).replace('\\/','/')
    urls=re.findall(r'https://[^\s<>"\'\\]+\.(?:m3u8|mp4)(?:\?[^\s<>"\'\\]*)?',text)
    result=[]
    for url in urls:
        try:result.append(public_url(url,resolve_dns=False))
        except SourceError:pass
    return list(dict.fromkeys(result))[:30]


def browser_destination(url,*,resolve_dns=True):
    # Only this isolated browser may follow public playback APIs. IP/DNS checks stay on.
    return public_url(re.sub(r'^wss:', 'https:',url),resolve_dns=resolve_dns,allow_api=True)


async def _check_player_access(page):
    if BLOCKED.search((await page.content())[:2*1024*1024]):raise SourceError('Источник требует проверку браузера или вход. Выбери другой источник.')
    plus=page.locator('.tab_need_plus')
    if await plus.count() and await plus.first.is_visible():raise SourceError('Эта серия закрыта ограничением JutPlus. Нужна общедоступная серия или другой источник.')


async def _extract(url,referer=None,*,validate=browser_destination,fixture=None,timeout=12):
    try:from playwright.async_api import async_playwright
    except ImportError:raise SourceError('Для динамического плеера обнови серверный образ с Chromium.') from None
    executable=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium') or shutil.which('google-chrome')
    if not executable:raise SourceError('На сервере не установлен Chromium для динамического плеера.')
    validate(url)
    captured={};done=asyncio.Event();requests=0
    headers=playback_headers({'Referer':referer or url})
    def record(value,extra=None):
        try:target=validate(value)
        except SourceError:return
        path=urlsplit(target).path.lower()
        if not path.endswith(('.mp4','.m3u8')):return
        captured[target]={'url':target,'type':'hls' if path.endswith('.m3u8') else 'mp4','quality':None,'headers':playback_headers(extra or headers)}
        done.set()
    async with async_playwright() as driver:
        launch={'headless':True,'executable_path':executable,'args':['--no-sandbox','--disable-background-networking','--disable-dev-shm-usage']}
        # Preserve the managed proxy for source requests; production may have none.
        proxy=os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')
        if proxy and fixture is None:launch['proxy']={'server':proxy}
        browser=await driver.chromium.launch(**launch)
        try:
            context=await browser.new_context(service_workers='block',accept_downloads=False)
            async def guard(route):
                nonlocal requests
                requests+=1
                try:validate(route.request.url)
                except SourceError:return await route.abort()
                if requests>160 or route.request.resource_type in {'image','font'}:return await route.abort()
                if fixture is not None:
                    body,mime=fixture.get(route.request.url,('', 'text/plain'))
                    return await route.fulfill(body=body,content_type=mime)
                if route.request.resource_type=='media':
                    # Avoid downloading a complete media file merely to discover its address.
                    record(route.request.url,route.request.headers)
                    return await route.abort()
                await route.continue_()
            await context.route('**/*',guard)
            async def websocket(route):
                try:validate(route.url)
                except SourceError:return await route.close()
                remote=route.connect_to_server()
                def receive(message):
                    for value in observed_streams(message):record(value)
                    route.send(message)
                remote.on_message(receive)
            await context.route_web_socket('**/*',websocket)
            page=await context.new_page()
            page.on('popup',lambda popup:asyncio.create_task(popup.close()))
            def response(value):
                if 200<=value.status<300:record(value.url,value.request.headers)
            page.on('response',response)
            try:
                await page.goto(url,wait_until='domcontentloaded',timeout=timeout*1000)
                await _check_player_access(page)
                await page.evaluate('document.querySelectorAll("video").forEach(v=>{v.muted=true;v.play().catch(()=>{});})')
                if not captured:
                    try:await asyncio.wait_for(done.wait(),timeout=timeout)
                    except asyncio.TimeoutError:pass
                await _check_player_access(page)
                if not captured:raise SourceError('Динамический плеер не опубликовал поддерживаемый MP4/HLS-поток.')
                return list(captured.values())
            finally:await context.close()
        finally:await browser.close()


def extract(url,referer=None):
    if os.environ.get('MEDIA_VAULT_BROWSER_PLAYERS','1')!='1':
        raise SourceError('Динамические плееры отключены на этом сервере.')
    if not _slots.acquire(timeout=10):raise SourceError('Серверный браузер занят другим плеером. Повтори позднее.')
    try:
        try:return asyncio.run(_extract(url,referer))
        except SourceError:raise
        except Exception:raise SourceError('Не удалось открыть динамический плеер на сервере.') from None
    finally:_slots.release()


async def _render(url,*,validate=browser_destination,fixture=None,timeout=8):
    """Read dynamically inserted iframe markup, without downloading video."""
    from playwright.async_api import async_playwright,TimeoutError as PlaywrightTimeout
    validate(url);deadline=time.monotonic()+timeout
    async with async_playwright() as driver:
        launch={'headless':True,'executable_path':os.environ.get('CHROMIUM_PATH') or shutil.which('chromium') or shutil.which('google-chrome'),
                'args':['--no-sandbox','--disable-background-networking','--disable-dev-shm-usage']}
        proxy=os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')
        if proxy and fixture is None:launch['proxy']={'server':proxy}
        browser=await driver.chromium.launch(**launch)
        try:
            context=await browser.new_context(service_workers='block',accept_downloads=False);requests=0
            async def guard(route):
                nonlocal requests
                requests+=1
                try:validate(route.request.url)
                except SourceError:return await route.abort()
                if requests>160 or route.request.resource_type in {'image','font','media'} or re.search(r'\.(?:mp4|m3u8|ts|m4s)(?:\?|$)',route.request.url):return await route.abort()
                if fixture is not None:
                    body,mime=fixture.get(route.request.url,('', 'text/plain'))
                    return await route.fulfill(body=body,content_type=mime)
                await route.continue_()
            await context.route('**/*',guard)
            async def websocket(route):await route.close()
            await context.route_web_socket('**/*',websocket)
            page=await context.new_page();page.on('popup',lambda popup:asyncio.create_task(popup.close()))
            await page.goto(url,wait_until='domcontentloaded',timeout=max(1,int((deadline-time.monotonic())*1000)))
            if BLOCKED.search((await page.content())[:2*1024*1024]):raise SourceError('Источник требует проверку браузера или вход.')
            try:await page.wait_for_function('!!document.querySelector("iframe[src],iframe[data-src]")',timeout=max(1,int((deadline-time.monotonic())*1000)))
            except PlaywrightTimeout:pass
            text=await page.content()
            if BLOCKED.search(text[:2*1024*1024]):raise SourceError('Источник требует проверку браузера или вход.')
            return text,validate(page.url)
        finally:await browser.close()


def render(url,*,timeout=8):
    if os.environ.get('MEDIA_VAULT_BROWSER_PLAYERS','1')!='1':raise SourceError('Динамические плееры отключены на сервере.')
    if not _slots.acquire(timeout=5):raise SourceError('Серверный браузер занят другим плеером.')
    try:
        try:return asyncio.run(_render(url,timeout=timeout))
        except SourceError:raise
        except Exception:raise SourceError('Источник не опубликовал доступную разметку плеера.') from None
    finally:_slots.release()
