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
from pathlib import Path
from urllib.parse import urlsplit
from source_parser import SourceError, public_url, playback_headers, BLOCKED

_slots=threading.BoundedSemaphore(1)


def browser_paths():
    # /data is the VM checkout's mounted data directory. Chromium/Playwright
    # scratch profiles stay below its .codex-local, never in a user profile.
    root=Path(os.environ.get('DATA_DIR') or Path(__file__).resolve().parents[1])/'.codex-local'
    # Chromium's Unix SingletonSocket has a 108-byte pathname limit. Keep the
    # scratch component short even in the longer hosted-CI checkout path.
    for name,folder in [('TMPDIR','t'),('XDG_CACHE_HOME','browser-cache')]:
        os.environ.setdefault(name,str(root/folder))
        Path(os.environ[name]).mkdir(parents=True,exist_ok=True)


def observed_streams(value):
    if not isinstance(value,str) or len(value)>2*1024*1024:return []
    text=html.unescape(value).replace('\\/','/')
    urls=re.findall(r'https://[^\s<>"\'\\]+\.(?:m3u8|mp4)(?:\?[^\s<>"\'\\]*)?',text)
    result=[]
    for url in urls:
        try:result.append(public_url(url,resolve_dns=False))
        except SourceError:pass
    return list(dict.fromkeys(result))


def browser_destination(url,*,resolve_dns=True):
    # Only this isolated browser may follow public playback APIs. IP/DNS checks stay on.
    return public_url(re.sub(r'^wss:', 'https:',url),resolve_dns=resolve_dns,allow_api=True)


def published_quality_streams(values,headers,*,validate=browser_destination):
    """Read only the active Alloha audio source's explicit quality/URL map."""
    if not isinstance(values,dict) or len(values)>64:return []
    streams=[]
    for quality,value in values.items():
        if not re.fullmatch(r'\d{2,4}',str(quality)) or not 1<=int(quality)<=8640 or not isinstance(value,str):continue
        try:target=validate(value)
        except SourceError:continue
        path=urlsplit(target).path.lower()
        if not path.endswith(('.m3u8','.mp4')):continue
        streams.append({'url':target,'type':'hls' if path.endswith('.m3u8') else 'mp4',
                        'quality':int(quality),'headers':playback_headers(headers)})
    return sorted(streams,key=lambda s:s['quality'],reverse=True)


async def _check_player_access(page):
    if BLOCKED.search((await page.content())[:2*1024*1024]):raise SourceError('Источник требует проверку браузера или вход. Выбери другой источник.')
    plus=page.locator('.tab_need_plus')
    if await plus.count() and await plus.first.is_visible():raise SourceError('Эта серия закрыта ограничением JutPlus. Нужна общедоступная серия или другой источник.')


async def _extract(url,referer=None,*,validate=browser_destination,fixture=None,timeout=12,metadata=None):
    try:from playwright.async_api import async_playwright,TimeoutError as PlaywrightTimeout
    except ImportError:raise SourceError('Для динамического плеера обнови серверный образ с Chromium.') from None
    executable=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium') or shutil.which('google-chrome')
    if not executable:raise SourceError('На сервере не установлен Chromium для динамического плеера.')
    browser_paths()
    validate(url)
    captured={};done=asyncio.Event();requests=0;selected_quality=None;requested_qualities={}
    current=object()
    headers=playback_headers({'Referer':referer or url})
    def record(value,extra=None,quality_hint=current):
        try:target=validate(value)
        except SourceError:return
        path=urlsplit(target).path.lower()
        if urlsplit(target).hostname=='cdn.plyr.io' and path=='/static/blank.mp4':return
        if not path.endswith(('.mp4','.m3u8')):return
        # A late response for the preceding selection must not relabel its URL.
        if target not in captured:
            quality=selected_quality if quality_hint is current else quality_hint
            captured[target]={'url':target,'type':'hls' if path.endswith('.m3u8') else 'mp4','quality':quality,'headers':playback_headers(extra or headers)}
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
                requested_qualities[route.request.url]=selected_quality
                if fixture is not None:
                    body,mime=fixture.get(route.request.url,('', 'text/plain'))
                    return await route.fulfill(body=body,content_type=mime)
                if route.request.resource_type=='media':
                    # Avoid downloading a complete media file merely to discover its address.
                    record(route.request.url,route.request.headers)
                    return await route.abort()
                # HLS.js loads segments as fetch/XHR rather than "media".
                # Manifests suffice to discover quality; do not fetch segments
                # (or misidentify an init.mp4 as a complete standalone movie).
                if re.search(r'\.(?:ts|m4s|aac|cmfv|cmfa|mp4)(?:\?|$)',route.request.url,re.I):return await route.abort()
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
                if 200<=value.status<300 and (urlsplit(value.url).path.lower().endswith('.m3u8') or value.request.resource_type=='media'):
                    record(value.url,value.request.headers,requested_qualities.get(value.url))
            page.on('response',response)
            try:
                # Alloha publishes an iframe player and deliberately has no
                # top-level UI. Load it as an ordinary public embed, preserving
                # the selected episode URL and the publisher's Referer.
                framed=(urlsplit(url).hostname or '').endswith(('.stravers.live','.thealloha.club','.alloha.tv'))
                if framed:
                    if referer:
                        validate(referer)
                        await page.goto(referer,wait_until='domcontentloaded',timeout=timeout*1000)
                        await _check_player_access(page)
                        captured.clear();done.clear()
                    await page.set_content('<iframe allow="autoplay" src="'+html.escape(url,quote=True)+'"></iframe>',wait_until='domcontentloaded',timeout=timeout*1000)
                    element=await page.wait_for_selector('iframe');target=await element.content_frame()
                    await target.wait_for_load_state('domcontentloaded',timeout=timeout*1000)
                else:
                    await page.goto(url,wait_until='domcontentloaded',timeout=timeout*1000);target=page
                await _check_player_access(target)
                await target.evaluate('document.querySelectorAll("video").forEach(v=>{v.muted=true;v.play().catch(()=>{});})')
                if framed:
                    control=target.locator('button[data-plyr="play"],button[data-allplay="play"]').first
                    try:
                        await control.wait_for(state='visible',timeout=3000)
                        await control.click(timeout=2000)
                    except PlaywrightTimeout:pass
                if not captured:
                    try:await asyncio.wait_for(done.wait(),timeout=timeout)
                    except asyncio.TimeoutError:pass
                await _check_player_access(target)
                if metadata is not None:
                    tracks=await target.locator('video track[src]').evaluate_all('(nodes)=>nodes.map(n=>({url:n.src,name:n.label,language:n.srclang}))')
                    metadata['subtitles']=[]
                    for track in tracks[:30]:
                        try:track['url']=validate(track['url'])
                        except SourceError:continue
                        if urlsplit(track['url']).path.lower().endswith('.vtt'):metadata['subtitles'].append(track)
                if framed:
                    # The initialized active audio source publishes the complete
                    # signed ladder. Its own quality keys are authoritative:
                    # delayed WS responses during menu clicks cannot relabel it.
                    values=await target.evaluate("() => typeof player==='undefined' ? null : player.currentSource?.quality || null")
                    initial_headers=next(iter(captured.values()))['headers'] if captured else headers
                    published=published_quality_streams(values,initial_headers,validate=validate)
                    if published:return published
                    # Modern Alloha serves a different signed one-quality HLS
                    # master for each menu choice. The initial 480p request is
                    # not a master containing every resolution. Activate only
                    # the quality buttons actually published by this episode;
                    # never derive URLs or switch its translation/audio track.
                    selector='button[data-allplay="quality"][value],button[data-plyr="quality"][value]'
                    values=await target.locator(selector).evaluate_all('(nodes)=>nodes.map(n=>n.value)')
                    qualities=sorted({int(v) for v in values if re.fullmatch(r'\d{2,4}',v) and 1<=int(v)<=8640},reverse=True)
                    active=await target.locator('button[data-allplay="quality"][value][aria-checked="true"],button[data-plyr="quality"][value][aria-checked="true"]').evaluate_all('(nodes)=>nodes.map(n=>n.value)')
                    unlabelled=[s for s in captured.values() if not s.get('quality')]
                    if len(active)==1 and active[0].isdigit() and int(active[0]) in qualities and len(unlabelled)==1:
                        unlabelled[0]['quality']=int(active[0])
                    quality_deadline=time.monotonic()+min(timeout,12)
                    for height in qualities[:12]:
                        if any(s.get('quality')==height for s in captured.values()):continue
                        remaining=quality_deadline-time.monotonic()
                        if remaining<=0:break
                        selected_quality=height;done.clear()
                        control=target.locator(
                            'button[data-allplay="quality"][value="'+str(height)+'"],button[data-plyr="quality"][value="'+str(height)+'"]').first
                        await control.evaluate('node=>node.click()')
                        try:await asyncio.wait_for(done.wait(),timeout=min(2,remaining))
                        except asyncio.TimeoutError:pass
                    selected_quality=None
                # A browser request usually exposes only the selected quality.
                # Preserve every public source currently published in the DOM.
                for source in await target.locator('video[src],video source[src]').evaluate_all('(nodes)=>nodes.map(n=>({url:n.src,quality:n.getAttribute("res")||n.getAttribute("data-quality")||n.getAttribute("label")}))'):
                    record(source['url'])
                    quality=re.fullmatch(r'(\d{1,4})p?',str(source.get('quality') or ''),re.I)
                    if source['url'] in captured and quality and 1<=int(quality[1])<=8640:captured[source['url']]['quality']=int(quality[1])
                if not captured:raise SourceError('Динамический плеер не опубликовал поддерживаемый MP4/HLS-поток.')
                streams=list(captured.values())
                # Do not let the unlabelled boot stream override a discovered
                # 4K choice in online playback's adaptive-master selection.
                labelled=[s for s in streams if s.get('quality')]
                return labelled if framed and labelled else streams
            finally:await context.close()
        except PlaywrightTimeout:raise SourceError('Плеер не ответил за отведённое время.') from None
        finally:await browser.close()


def extract(url,referer=None,*,details=False):
    if os.environ.get('MEDIA_VAULT_BROWSER_PLAYERS','1')!='1':
        raise SourceError('Динамические плееры отключены на этом сервере.')
    if not _slots.acquire(timeout=10):raise SourceError('Серверный браузер занят другим плеером. Повтори позднее.')
    try:
        try:
            metadata={} if details else None
            streams=asyncio.run(_extract(url,referer,metadata=metadata))
            return {'streams':streams,**metadata} if details else streams
        except SourceError:raise
        except Exception:raise SourceError('Не удалось открыть динамический плеер на сервере.') from None
    finally:_slots.release()


async def _render(url,*,validate=browser_destination,fixture=None,timeout=8):
    """Read dynamically inserted iframe markup, without downloading video."""
    from playwright.async_api import async_playwright,TimeoutError as PlaywrightTimeout
    browser_paths()
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
        except PlaywrightTimeout:raise SourceError('Источник не успел опубликовать разметку плеера.') from None
        finally:await browser.close()


def render(url,*,timeout=8):
    if os.environ.get('MEDIA_VAULT_BROWSER_PLAYERS','1')!='1':raise SourceError('Динамические плееры отключены на сервере.')
    if not _slots.acquire(timeout=5):raise SourceError('Серверный браузер занят другим плеером.')
    try:
        try:return asyncio.run(_render(url,timeout=timeout))
        except SourceError:raise
        except Exception:raise SourceError('Источник не опубликовал доступную разметку плеера.') from None
    finally:_slots.release()
