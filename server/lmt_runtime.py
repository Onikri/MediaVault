# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the actual upstream web pipeline in a private backend Chromium profile."""
from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit


class LmtRuntime:
    ORIGIN = 'http://127.0.0.1:17861'

    def __init__(self, assets, directory):
        self.assets = Path(assets).resolve()
        self.directory = Path(directory)
        self.browser = self.playwright = self.page = None
        self.progress = lambda _: None
        self.allow_downloads = False

    def status(self):
        return {'ready': (self.assets / 'index.html').is_file() and
                         bool(os.getenv('LMT_LLM_URL') and os.getenv('LMT_LLM_MODEL')),
                'assetsReady': (self.assets / 'index.html').is_file(),
                'llmConfigured': bool(os.getenv('LMT_LLM_URL') and os.getenv('LMT_LLM_MODEL')),
                'engine': 'Libre Manga Translator', 'mode': 'backend',
                'source': 'https://github.com/Onikri/MediaVault/tree/main/lmt'}

    async def _route(self, route):
        request = route.request
        url = urlsplit(request.url)
        if request.url.startswith(self.ORIGIN + '/llm/'):
            # The client never chooses a network destination or supplies API keys.
            import httpx
            target = os.environ['LMT_LLM_URL'].rstrip('/') + '/' + url.path.removeprefix('/llm/')
            headers = {'Content-Type': 'application/json'}
            if os.getenv('LMT_LLM_API_KEY'):
                headers['Authorization'] = 'Bearer ' + os.environ['LMT_LLM_API_KEY']
            try:
                async with httpx.AsyncClient(timeout=180, follow_redirects=False, trust_env=False) as client:
                    response = await client.post(target, content=request.post_data_buffer, headers=headers)
                await route.fulfill(status=response.status_code, content_type='application/json', body=response.content)
            except Exception:
                await route.fulfill(status=502, content_type='application/json', body='{"error":"Local LLM unavailable"}')
            return
        if request.url.startswith(self.ORIGIN + '/'):
            path = (self.assets / unquote(url.path).lstrip('/')).resolve()
            if not path.is_relative_to(self.assets) or not path.is_file():
                await route.fulfill(status=404, body='')
                return
            mime = 'application/wasm' if path.suffix == '.wasm' else mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
            await route.fulfill(content_type=mime, body=path.read_bytes())
            return
        # Weights only; no page uploads, telemetry or arbitrary client URLs.
        if self.allow_downloads and url.scheme == 'https' and (
            url.hostname in {'huggingface.co', 'hf.co', 'cdn-lfs.huggingface.co', 'cdn-lfs-us-1.huggingface.co',
                             'github.com', 'release-assets.githubusercontent.com', 'raw.githubusercontent.com'} or
            (url.hostname or '').endswith('.hf.co') or (url.hostname or '').endswith('.huggingface.co')
        ) and request.method in {'GET', 'HEAD'}:
            await route.continue_()
        else:
            await route.abort('blockedbyclient')

    async def _start(self, needs_llm=True):
        if self.page and not self.page.is_closed():
            return
        if not self.status()['ready' if needs_llm else 'assetsReady']:
            raise ValueError('Собери LMT и настрой LMT_LLM_URL/LMT_LLM_MODEL на backend.')
        from playwright.async_api import async_playwright
        if not self.browser:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.playwright = await async_playwright().start()
            options = {'headless': True, 'service_workers': 'block',
                       'args': ['--disable-dev-shm-usage'], 'accept_downloads': False}
            if os.getenv('CHROMIUM_PATH'):
                options['executable_path'] = os.environ['CHROMIUM_PATH']
            if os.getenv('LMT_CHROMIUM_NO_SANDBOX') == '1':
                options['args'].append('--no-sandbox')
            self.browser = await self.playwright.chromium.launch_persistent_context(str(self.directory), **options)
            await self.browser.route('**/*', self._route)
        self.page = await self.browser.new_page()
        await self.page.expose_function('mvProgress', lambda status: self.progress(status))
        await self.page.goto(self.ORIGIN + '/index.html')
        await self.page.wait_for_function('typeof window.mangaTranslate === "function"')

    async def run(self, data, config, progress):
        self.progress = progress
        self.allow_downloads = config.get('allowDownloads', False)
        try:
            await self._start(config.get('operation','process') in {'process','translate'})
        except BaseException:
            self.progress = lambda _: None
            self.allow_downloads = False
            await self.close()
            raise
        # Only operator-controlled LLM endpoint/schema/model reach the browser.
        config = {**config, 'mode': 'api', 'host': self.ORIGIN + '/llm/',
                  'serverModel': os.getenv('LMT_LLM_MODEL','unused'),
                  'serverSchema': os.getenv('LMT_LLM_SCHEMA', 'openai')}
        try:
            return await self.page.evaluate('''async ({image,config}) => {
                const bytes=Uint8Array.from(atob(image),c=>c.charCodeAt(0));
                const result=await window.mangaTranslate(bytes.buffer,config,s=>window.mvProgress(s));
                for(const key of ['renderedImage','cleanedImage'])if(result[key]){
                    const data=new Uint8Array(result[key]);let text='';
                    for(let i=0;i<data.length;i+=8192)text+=String.fromCharCode(...data.subarray(i,i+8192));
                    result[key]=btoa(text);
                }
                return result;
            }''', {'image': base64.b64encode(data).decode(), 'config': config})
        except BaseException:
            await self.reset_page()
            raise
        finally:
            self.progress = lambda _: None
            self.allow_downloads = False

    async def reset_page(self):
        page, self.page = self.page, None
        if page:
            await page.close()

    async def typeset(self, data, regions, scale):
        await self._start()
        return await self.page.evaluate('''async ({image,regions,scale}) => {
            const input=Uint8Array.from(atob(image),c=>c.charCodeAt(0));
            const result=new Uint8Array(await window.mangaTypeset(input,regions,scale));
            let text='';for(let i=0;i<result.length;i+=8192)text+=String.fromCharCode(...result.subarray(i,i+8192));
            return btoa(text);
        }''', {'image':base64.b64encode(data).decode(), 'regions':regions, 'scale':scale})

    async def close(self):
        await self.reset_page()
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
