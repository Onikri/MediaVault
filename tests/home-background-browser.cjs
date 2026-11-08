// Actual home background video decode/crop. Catalogue and YouTube failure are fixtures.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
let browser,vite;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/home-background'),base='/.codex-local/test-output/home-background/';await fs.mkdir(dir,{recursive:true});
 execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x140:rate=10','-vf','pad=320:180:0:20:black','-t','3','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-y',path.join(dir,'fixture.mp4')]);
 await fs.writeFile(path.join(dir,'index.html'),'<meta name="referrer" content="no-referrer"><div id="root"></div><script type="module" src="'+base+'fixture.jsx"></script>');
 await fs.writeFile(path.join(dir,'fixture.jsx'),`import React from'react';import{createRoot}from'react-dom/client';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';import{HeroBanner}from'/src/blossom/components/HeroBanner.tsx';import'/src/styles.css';import'/src/title-page.css';window.YT={Player:function(node,options){setTimeout(()=>options.events.onError({data:153}),50);return{destroy(){}};}};createRoot(document.getElementById('root')).render(<ThemeProvider><HeroBanner identity="16498" server="https://api.fixture" title="Атака титанов" artwork="/src/blossom/placeholders/anime.svg" trailer="https://www.youtube.com/watch?v=abcdefghijk"/></ThemeProvider>);`);
 const {createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/vite-home-background',logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});const page=await browser.newPage({viewport:{width:1366,height:768}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let referer='';await page.route('https://www.youtube.com/**',r=>{referer=r.request().headers().referer;return r.fulfill({contentType:'text/html',body:'ERROR 153'});});
 await page.route('https://api.fixture/**',async r=>r.request().url().endsWith('/video')?r.fulfill({contentType:'video/mp4',body:await fs.readFile(path.join(dir,'fixture.mp4'))}):r.fulfill({json:{status:'ready',url:'/backgrounds/16498/video'}}));
 await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+base+'index.html');
 await page.waitForFunction(()=>document.querySelector('.home-feature video')?.currentTime>.5);await page.waitForFunction(()=>Number(document.querySelector('.home-feature video').style.getPropertyValue('--background-crop'))>1.2);
 assert.equal(await page.locator('.title-background-youtube').count(),0,'Error iframe is removed; the same title uses the native video');assert.ok(referer?.startsWith('http://127.0.0.1:'),'YouTube gets an explicit origin referrer despite the document privacy policy');
 await page.getByRole('button',{name:'Остановить фоновый трейлер',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.home-feature video').paused);
 assert.deepEqual(errors,[]);await page.screenshot({path:path.join(dir,'home.png')});console.log('PASS home native video, YouTube error153 handling/referrer, actual letterbox crop and pause');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
