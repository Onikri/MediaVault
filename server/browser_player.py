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
import copy
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlsplit
from source_parser import SourceError, public_url, playback_headers, BLOCKED, USER_AGENT, is_alloha_player

def browser_workers():
    try:return max(1,min(2,int(os.environ.get('MEDIA_VAULT_BROWSER_WORKERS',min(2,os.cpu_count() or 1)))))
    except (TypeError,ValueError):return 1

# YummyAnime's Alloha CDN (*.vkvideo.cloud) answers 403 unless a request
# carries the player Origin and an ordinary browser User-Agent. Verified on
# Oracle 2026-11-05: it refuses "node", "python-requests/*" and exactly the
# shared scraper default (Windows Chrome/126 = source_parser.USER_AGENT), while
# any other current browser UA, on any OS, is accepted. Signed URLs are not
# bound to the extracting browser's UA, so stream fetches reuse this profile.
YANI_ORIGIN='https://alloha.yani.tv'
YANI_USER_AGENT='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'

_slots=threading.BoundedSemaphore(browser_workers())
_playback_cache=OrderedDict()
_cache_lock=threading.Lock()
_pending={}


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


async def _extract(url,referer=None,*,validate=browser_destination,fixture=None,timeout=12,metadata=None,mode=None):
    try:from playwright.async_api import async_playwright,Error as PlaywrightError,TimeoutError as PlaywrightTimeout
    except ImportError:raise SourceError('Для динамического плеера обнови серверный образ с Chromium.') from None
    executable=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium') or shutil.which('google-chrome')
    if not executable:raise SourceError('На сервере не установлен Chromium для динамического плеера.')
    browser_paths()
    validate(url)
    framed = is_alloha_player(url)
    yani = urlsplit(url).hostname=='alloha.yani.tv'
    if mode and referer:
        validate(referer)
    captured={};done=asyncio.Event();requests=0;selected_quality=None;requested_qualities={}
    current=object()
    headers=playback_headers({'Referer':referer or url})
    def record(value,extra=None,quality_hint=current):
        if mode and captured:
            return
        try:target=validate(value)
        except SourceError:return
        path=urlsplit(target).path.lower()
        if urlsplit(target).hostname=='cdn.plyr.io' and path=='/static/blank.mp4':return
        if not path.endswith(('.mp4', '.m3u8')) or (mode == 'mp4' and not path.endswith('.mp4')):
            return
        if mode and path.rsplit('/', 1)[-1] in {'blank.mp4', 'init.mp4', 'ad.mp4', 'preroll.mp4'}:
            return
        # A late response for the preceding selection must not relabel its URL.
        if target not in captured:
            quality=selected_quality if quality_hint is current else quality_hint
            captured[target]={'url':target,'type':'hls' if path.endswith('.m3u8') else 'mp4','quality':quality,'headers':playback_headers({**headers, **{k.title(): v for k, v in (extra or {}).items()}})}
            done.set()
    async with async_playwright() as driver:
        launch={'headless':True,'executable_path':executable,'args':['--no-sandbox','--disable-background-networking','--disable-dev-shm-usage']}
        # Preserve the managed proxy for source requests; production may have none.
        proxy=os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')
        if proxy and fixture is None:launch['proxy']={'server':proxy}
        browser=await driver.chromium.launch(**launch)
        try:
            # Alloha selects its signed CDN URLs during iframe initialization.
            # Use the same public browser profile as subsequent media requests.
            context_options = {'user_agent': USER_AGENT} if framed or mode else {}
            if yani:
                context_options.update(user_agent=YANI_USER_AGENT,locale='ru-RU',viewport={'width':1280,'height':720})
            context=await browser.new_context(service_workers='block',accept_downloads=False, **context_options)
            async def guard(route):
                nonlocal requests
                requests+=1
                try:validate(route.request.url)
                except SourceError:return await route.abort()
                if requests>160 or route.request.resource_type in {'image','font'}:return await route.abort()
                requested_qualities[route.request.url]=selected_quality
                if mode and route.request.method == 'GET':
                    path = urlsplit(route.request.url).path.lower()
                    if (path.endswith('.mp4') or (mode != 'mp4' and path.endswith('.m3u8'))) and route.request.resource_type in {'media', 'xhr', 'fetch'}:
                        record(route.request.url, route.request.headers)
                        return await route.abort()
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
                    if not mode:
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
                    navigation = await page.goto(url, wait_until='domcontentloaded', timeout=timeout*1000,
                                                 **({'referer': referer} if mode and referer else {}))
                    if mode and navigation and navigation.status in {401, 403}:
                        raise SourceError('Источник ограничил доступ к странице на Oracle.')
                    target=page
                await _check_player_access(target)
                await target.evaluate('document.querySelectorAll("video").forEach(v=>{v.muted=true;v.play().catch(()=>{});})')
                if mode and not captured:
                    selectors = ('text=ВИДЕО ПЛЕЕР', '.play', '#player')
                    if mode in {'mp4', 'hentasis-mirror'}:
                        selectors += ('.rl-fake-player', '.rl-button-play')
                    for selector in selectors:
                        for player_frame in page.frames[:8]:
                            if captured:
                                break
                            try:
                                await player_frame.locator(selector).first.click(timeout=650)
                                await asyncio.wait_for(done.wait(), timeout=.8)
                            except (PlaywrightError, asyncio.TimeoutError):
                                continue
                        if captured:
                            break
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
                if framed:
                    # The publisher's boot request can finish before this
                    # iframe initializes its selected audio source. Never
                    # mistake that response for the active quality ladder.
                    try:
                        await target.wait_for_function("() => typeof player!=='undefined' && player.currentSource?.quality && Object.keys(player.currentSource.quality).length>0",timeout=min(5000,timeout*1000))
                    except PlaywrightTimeout:
                        modern=await target.evaluate("() => typeof player!=='undefined' && 'currentSource' in player")
                        if modern:raise SourceError('Плеер ещё не загрузил выбранную озвучку. Повтори подключение.') from None
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
                    if yani:
                        # Same browser profile as this extraction; see YANI_USER_AGENT.
                        initial_headers={'Origin':YANI_ORIGIN,'User-Agent':await target.evaluate('navigator.userAgent')}
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


# The same CDN also starts refusing a (server IP, User-Agent) pair after a
# burst of extractions: every extraction issues new signed URLs. One viewer
# needs one extraction per episode, so keep its URLs instead of re-issuing.
def _seconds(name,default):
    try:return max(0,int(os.environ.get(name,default)))
    except (TypeError,ValueError):return default
ALLOHA_CACHE_SECONDS=_seconds('MEDIA_VAULT_ALLOHA_CACHE_SECONDS',1200)
ALLOHA_MIN_REFRESH_SECONDS=_seconds('MEDIA_VAULT_ALLOHA_MIN_REFRESH_SECONDS',90)
ALLOHA_COOLDOWN_SECONDS=_seconds('MEDIA_VAULT_ALLOHA_COOLDOWN_SECONDS',300)
_cooldown={}


def _throttled(url):
    return urlsplit(url).hostname=='alloha.yani.tv'


def _cooling(url):
    with _cache_lock:
        remaining=_cooldown.get(urlsplit(url).hostname,0)-time.monotonic()
    if remaining>0:
        raise SourceError('CDN Alloha временно ограничил сервер. Повтори через '+str(max(1,round(remaining/60)))+' мин. или выбери другой плеер.')


def rejected(url,referer=None,mode=None):
    """The CDN answered 403 for streams from this extraction.

    Returns True when the cached URLs were old enough that a single new
    extraction is reasonable. Freshly issued URLs being refused means the
    server is throttled: back off instead of issuing more signed URLs.
    """
    if not _throttled(url):return False
    with _cache_lock:
        old=_playback_cache.pop((url,referer,mode),None)
        if old and time.monotonic()-old[2]>=ALLOHA_MIN_REFRESH_SECONDS:return True
        _cooldown[urlsplit(url).hostname]=time.monotonic()+ALLOHA_COOLDOWN_SECONDS
        return False


def extract(url,referer=None,*,details=False,mode=None,refresh=False,cached_only=False):
    if os.environ.get('MEDIA_VAULT_BROWSER_PLAYERS','1')!='1':
        raise SourceError('Динамические плееры отключены на этом сервере.')
    key=(url,referer,mode)
    throttled=_throttled(url)
    if refresh:
        with _cache_lock:
            old=_playback_cache.get(key)
            # Client retries must not re-issue signed URLs in a tight loop.
            if not throttled or not old or time.monotonic()-old[2]>=ALLOHA_MIN_REFRESH_SECONDS:
                _playback_cache.pop(key,None)
    def cached():
        with _cache_lock:
            old=_playback_cache.get(key)
            if old and old[0]>time.monotonic():
                _playback_cache.move_to_end(key)
                return copy.deepcopy(old[1])
    value=cached()
    if value is not None:return value if details else value['streams']
    if throttled:
        _cooling(url)
        # Hover/episode previews and warm-ups would each issue new signed
        # URLs; for this CDN they may only reuse an existing extraction.
        if cached_only:raise SourceError('Превью этого плеера не готовится, чтобы не перегружать источник.')
    # Different public players can use two CPU-bounded slots. Identical work
    # still shares one extraction, rather than launching duplicate Chromiums.
    with _cache_lock:
        pending=_pending.get(key);leader=pending is None
        if leader:
            if len(_pending)>=64:raise SourceError('Сервер готовит другие плееры. Повтори позднее.')
            pending=_pending[key]={'event':threading.Event()}
    if not leader:
        if not pending['event'].wait(45):raise SourceError('Плеер не завершил подготовку. Повтори подключение.')
        if 'result' not in pending:raise SourceError(pending.get('error','Не удалось открыть динамический плеер на сервере.'))
        result=copy.deepcopy(pending['result']);return result if details else result['streams']
    acquired=False
    try:
        acquired=_slots.acquire(timeout=15)
        if not acquired:raise SourceError('Серверный браузер занят другим плеером. Повтори позднее.')
        value=cached()
        if value is not None:
            pending['result']=copy.deepcopy(value);return value if details else value['streams']
        try:
            metadata={}
            options = {'mode': mode, 'timeout': 25} if mode else {}
            async def run():
                work = _extract(url, referer, metadata=metadata, **options)
                return await asyncio.wait_for(work, timeout=25) if mode else await work
            streams = asyncio.run(run())
            value={'streams':streams,**metadata}
            if streams:
                with _cache_lock:
                    # Short signed-source lifetime, VM memory only. Quality
                    # inspection and immediate playback share one browser run.
                    now=time.monotonic()
                    _playback_cache[key]=(now+(ALLOHA_CACHE_SECONDS if throttled else 45),copy.deepcopy(value),now)
                    while len(_playback_cache)>64:_playback_cache.popitem(last=False)
            pending['result']=copy.deepcopy(value)
            return value if details else streams
        except SourceError:raise
        except asyncio.TimeoutError:raise SourceError('Динамический плеер не выдал поток за 25 секунд.') from None
        except Exception:raise SourceError('Не удалось открыть динамический плеер на сервере.') from None
    except SourceError as error:
        pending['error']=str(error);raise
    finally:
        if acquired:_slots.release()
        with _cache_lock:_pending.pop(key,None);pending['event'].set()


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
