// Real HTMLAudioElement decoding/seek/lifecycle; resolver and YouTube are fixtures.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'.codex-local/test-output/music-audio');let browser,vite;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});const audioPath=path.join(DIR,'music-server-fixture.m4a');execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','sine=frequency=440:duration=45','-c:a','aac','-movflags','+faststart','-threads','1','-y',audioPath]);const audio=await fs.readFile(audioPath);
 await fs.writeFile(path.join(DIR,'music-audio-harness.html'),'<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/.codex-local/test-output/music-audio/music-audio-harness.jsx"></script></html>');
 await fs.writeFile(path.join(DIR,'music-audio-harness.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import {ThemeProvider} from '/src/blossom/ThemeProvider.tsx';import {AnimatedNavbar} from '/src/blossom/components/AnimatedNavbar.tsx';import MiniMusicPlayer from'/src/MiniMusicPlayer.jsx';import{closeMusic}from'/src/music-player.js';import{OnlineMusic}from'/src/OnlineLibrary.jsx';import'/src/styles.css';
 window.MEDIA_VAULT_CONFIG={importServerUrl:location.origin};
 const service={server:location.origin,request:async(path,options={})=>{const response=await fetch(path,{method:options.method||'GET',body:options.body?JSON.stringify(options.body):undefined,headers:{'Content-Type':'application/json'},signal:options.signal});const result=await response.json();if(!response.ok)throw Object.assign(Error(result.detail),{status:response.status});return result;}};
 createRoot(document.getElementById('root')).render(<ThemeProvider><div className="app-shell"><AnimatedNavbar links={[{id:'home',label:'Главная'},{id:'library',label:'Библиотека'},{id:'collection',label:'Коллекция'},{id:'history',label:'История'}]} active="home" onNavigate={()=>{}} onSearch={()=>{}} brand={<button className="brand logo">MediaVault</button>}><MiniMusicPlayer service={service} placement="nav" userId="audio-owner"/><button className="avatar-button" aria-label="Профиль">Г</button></AnimatedNavbar><main className="app-main"><OnlineMusic userId="audio-owner"/><button aria-label="Закрыть тестовую музыкальную очередь" onClick={closeMusic}>Завершить</button></main></div></ThemeProvider>);
 `);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 for(const width of[390,1440]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));const prepared=[],closed=[];let failing=false,failureStatus=502;
  const token='a'.repeat(43),resource='b'.repeat(16);
  await page.route('**/music/play',async route=>{prepared.push(route.request().postDataJSON());await route.fulfill(failing?{status:failureStatus,json:{detail:'YouTube requires server verification'}}:{json:{id:token,streamUrl:'/online/'+token+'/'+resource,mime:'audio/mp4',duration:16,title:'Server audio fixture'}});});
  let remotePrepared=0;await page.route('**/music/remote',async route=>{remotePrepared++;assert.equal(route.request().postDataJSON().url,'https://music.example/song.mp3');await route.fulfill({json:{id:token,streamUrl:'/online/'+token+'/'+resource,mime:'audio/mp4',duration:16}});});
  await page.route('**/music/metadata?**',r=>r.fulfill({json:{found:false}}));
  await page.route('https://i.ytimg.com/**',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="360"><path fill="black" d="M0 0h480v360H0z"/><path fill="#809e6a" d="M0 45h480v270H0z"/><path fill="#cfb785" d="M200 75h80v210h-80z"/></svg>'}));let youtubeRequests=0;await page.route(/https:\/\/(?:www\.)?youtube(?:-nocookie)?\.com\//,r=>{youtubeRequests++;return r.abort();});
  await page.route('**/online/**',async route=>{if(route.request().method()==='DELETE'){closed.push(route.request().url());return route.fulfill({json:{closed:true}});}const range=route.request().headers().range,match=range?.match(/bytes=(\d+)-(\d*)/),start=match?Number(match[1]):0,end=match&&match[2]?Math.min(Number(match[2]),audio.length-1):audio.length-1;return route.fulfill({status:match?206:200,contentType:'audio/mp4',headers:{'Accept-Ranges':'bytes','Content-Length':String(end-start+1),...(match?{'Content-Range':'bytes '+start+'-'+end+'/'+audio.length}:{})},body:audio.subarray(start,end+1)});});
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/music-audio/music-audio-harness.html');
  await page.getByLabel('Ссылка на аудио',{exact:true}).fill('https://youtu.be/dQw4w9WgXcQ');await page.getByRole('button',{name:'Открыть',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('audio.music-audio')?.currentTime>.15);
  assert.equal(prepared[0].url,'https://www.youtube.com/watch?v=dQw4w9WgXcQ');assert.equal(await page.locator('iframe').count(),0);
  if(width<900){
    if(width<900)await page.getByRole('button',{name:'Музыкальный плеер',exact:true}).click();else await page.getByRole('button',{name:'Подробности музыки',exact:true}).click();
    await page.waitForFunction(()=>{const e=document.querySelector('.music-island');return e&&Math.abs(e.getBoundingClientRect().height-parseFloat(e.style.height))<1&&Math.abs(e.getBoundingClientRect().x-parseFloat(e.style.left))<1&&Math.abs(e.getBoundingClientRect().y-parseFloat(e.style.top))<1;});const panel=await page.locator('.music-island').boundingBox(),trigger=await page.locator('.music-nav').boundingBox();assert.ok(panel.height<320&&Math.abs(panel.y-trigger.y-trigger.height-10)<1,'Playing island follows the navbar trigger');assert.ok(panel.x>=12&&panel.x+panel.width<=width-12,'Island fits viewport');const offset=await page.locator('.music-nav').evaluate(e=>{const a=e.getBoundingClientRect(),b=e.closest('.header-inner').getBoundingClientRect();return Math.abs(a.y+a.height/2-b.y-b.height/2);});assert.ok(offset<.6,'Playing transport keeps navbar vertically centered');await page.screenshot({path:path.join(DIR,'music-island-playing-'+width+'.png')});
    await page.getByRole('button',{name:'Свернуть музыкальный плеер',exact:true}).click();const before=await page.locator('audio').evaluate(a=>a.currentTime);await page.waitForTimeout(300);assert.ok(await page.locator('audio').evaluate((a,n)=>!a.paused&&a.currentTime>n,before),'Collapsed server audio keeps playing');
    if(width<900)await page.getByRole('button',{name:'Музыкальный плеер',exact:true}).click();else await page.getByRole('button',{name:'Подробности музыки',exact:true}).click();
    const slider=page.getByLabel('Позиция музыки в подробностях',{exact:true});await slider.fill('8');await page.waitForFunction(()=>document.querySelector('audio')?.currentTime>=7.9);
    await page.getByRole('button',{name:'Пауза в подробностях',exact:true}).click();assert.equal(await page.locator('audio').evaluate(a=>a.paused),true);
    await page.getByRole('button',{name:'Продолжить в подробностях',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('audio').paused);
    await page.getByRole('button',{name:'Закрыть музыкальный плеер',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('audio'));assert.equal(closed.length,1,'Close releases backend capability');
  }else{
   // Real audio stays mounted while the same cover grows about its existing center.
   await page.locator('.music-bar').hover();await page.waitForTimeout(450);
   await page.locator('.music-shared-cover img').waitFor();
   await page.waitForFunction(()=>document.querySelector('.music-shared-cover img')?.naturalWidth===480);
   await page.evaluate(()=>{window.__audio=document.querySelector('audio');window.__cover=document.querySelector('.music-shared-cover');window.__image=window.__cover.querySelector('img');});
   const sampleMorph=async action=>{
    const audioBefore=await page.locator('audio').evaluate(a=>a.currentTime);
    await page.evaluate(()=>{window.__coverFrames=[];const end=performance.now()+650;function frame(now){const node=document.querySelector('.music-shared-cover'),disc=node?.querySelector('.music-cover-scale'),r=disc?.getBoundingClientRect();if(r)window.__coverFrames.push({x:r.x+r.width/2,y:r.y+r.height/2,size:r.width,same:node===window.__cover&&node.querySelector('img')===window.__image,visible:getComputedStyle(node).opacity==='1'&&getComputedStyle(node).visibility==='visible'});if(now<end)requestAnimationFrame(frame);}requestAnimationFrame(frame);});
    await action();await page.waitForTimeout(700);
    const rows=await page.evaluate(()=>window.__coverFrames),start=rows[0];
    assert.ok(rows.length>8&&rows.every(r=>r.same&&r.visible&&Math.abs(r.x-start.x)<.6&&Math.abs(r.y-start.y)<.6&&r.size>29.5&&r.size<39),'One visible cover keeps its screen center throughout the spring '+JSON.stringify(rows));
    assert.ok(await page.locator('audio').evaluate((a,t)=>a===window.__audio&&!a.paused&&a.currentTime>t+.3,audioBefore),'Mode changes never replace or interrupt audio');
   };
   await sampleMorph(()=>page.locator('.music-shared-cover').click());
   assert.ok(await page.locator('.music-cover-scale').evaluate(n=>Math.abs(n.getBoundingClientRect().width-38)<.1));
   const vinyl=page.locator('.music-shared-cover .music-artwork-vinyl');
   await page.locator('audio').evaluate(a=>a.pause());
   await page.waitForFunction(()=>getComputedStyle(document.querySelector('.music-shared-cover .music-artwork-vinyl')).animationPlayState==='paused');
   await page.waitForTimeout(40);const angleTime=await vinyl.evaluate(n=>n.getAnimations()[0].currentTime);
   await page.waitForTimeout(160);assert.ok(Math.abs((await vinyl.evaluate(n=>n.getAnimations()[0].currentTime))-angleTime)<1,'Pause preserves the vinyl angle');
   await page.locator('audio').evaluate(a=>a.play());await page.waitForTimeout(100);
   assert.ok(await vinyl.evaluate((n,t)=>n.getAnimations()[0].currentTime>t+30,angleTime),'Playback resumes rotation without resetting it');
   assert.equal(await page.locator('.music-shared-cover img').evaluate(n=>getComputedStyle(n).transform),'matrix(1.34, 0, 0, 1.34, 0, 0)','Baked-in letterbox bands are cropped');
   await page.screenshot({path:path.join(DIR,'music-cover-expanded.png')});
   await sampleMorph(()=>page.locator('.music-bar-full').click({position:{x:130,y:8}}));
   assert.ok(await page.locator('.music-cover-scale').evaluate(n=>Math.abs(n.getBoundingClientRect().width-30)<.1));
   await page.emulateMedia({reducedMotion:'reduce'});await page.locator('.music-shared-cover').click();
   assert.equal(await vinyl.evaluate(n=>getComputedStyle(n).animationName),'none','Reduced motion disables rotation');
   await page.locator('.music-bar-full').click({position:{x:130,y:8}});await page.emulateMedia({reducedMotion:'no-preference'});
   // Desktop: expanded music is the navbar itself; no separate floating island.
   await page.getByRole('button',{name:'Открыть музыкальный плеер',exact:true}).click();
   await page.locator('.music-nav .music-bar.is-nav-expanded').waitFor();
   await page.waitForTimeout(540);
   const full=await page.locator('.music-nav .music-bar').boundingBox(),header=await page.locator('.blossom-navbar .header-inner').boundingBox();
   assert.equal(Math.round(full.height),38,'Expanded transport matches the logo capsule height');
   assert.ok(Math.abs(full.width-344)<2,'Expanded transport matches the reference mini-player width');
   assert.ok(Math.abs(full.x+full.width-(await page.locator('.music-nav').boundingBox()).x-(await page.locator('.music-nav').boundingBox()).width)<2,'Expanded transport keeps its own right edge');
   await page.locator('.music-nav .music-bar.is-nav-expanded').click({position:{x:130,y:8}});
   await page.locator('.music-nav .music-bar.is-nav-expanded').waitFor({state:'detached'});
   const before=await page.locator('audio').evaluate(a=>a.currentTime);
   await page.waitForTimeout(300);
   assert.ok(await page.locator('audio').evaluate((a,n)=>!a.paused&&a.currentTime>n,before),'Collapsed navbar audio keeps playing');
   await page.getByRole('button',{name:'Открыть музыкальный плеер',exact:true}).click();
   const play=page.locator('.music-nav .music-full-play');await play.waitFor({state:'visible'});
   const volumeBefore=await page.locator('audio').evaluate(a=>a.volume);
   await play.hover();await page.mouse.wheel(0,-120);
   await page.waitForFunction(v=>document.querySelector('audio')?.volume>v,volumeBefore);
   const knob=await play.boundingBox();
   await page.mouse.move(knob.x+knob.width/2,knob.y+knob.height/2);
   await page.mouse.down();
   await page.mouse.move(knob.x+knob.width/2+85,knob.y+knob.height/2,{steps:12});
   await page.locator('.music-seek-surface').waitFor({state:'visible'});
   const playBox=await play.boundingBox(),clockBox=await page.locator('.music-seek-time').boundingBox();
   assert.ok(await play.evaluate(el=>parseFloat(getComputedStyle(el).width)===38),'expanded Play matches the search circle even during gesture scale');
   assert.ok(clockBox.width<=60,'dot-matrix timestamp stays small');
   assert.ok(Math.abs((playBox.x+playBox.width/2)-(clockBox.x+clockBox.width/2))<5,'dot-matrix time replaces Play at the same horizontal position');
   assert.equal(await page.locator('.music-seek-time').evaluate(n=>getComputedStyle(n).fontSize),'11px','seek time uses compact navbar typography');
   assert.equal(await page.locator('.music-seek-marker').count(),1,'precise white seek divider is visible');
   const seekBar=await page.locator('.music-bar').boundingBox(),audioDuration=await page.locator('audio').evaluate(a=>a.duration),expected=Math.max(0,Math.min(1,(knob.x+knob.width/2+85-seekBar.x)/seekBar.width))*audioDuration;
   await page.mouse.up();
   await page.waitForFunction(v=>Math.abs(document.querySelector('audio')?.currentTime-v)<.75,expected);
   await page.locator('.music-seek-surface').waitFor({state:'detached'});
   await play.click();assert.equal(await page.locator('audio').evaluate(a=>a.paused),true,'Expanded play control pauses audio');
   await play.click();await page.waitForFunction(()=>!document.querySelector('audio').paused);
   await page.getByRole('button',{name:'Закрыть тестовую музыкальную очередь',exact:true}).click();
   await page.waitForFunction(()=>!document.querySelector('audio'));
   assert.equal(closed.length,1,'Closing the track releases backend capability');
  }
  await page.getByLabel('Ссылка на аудио',{exact:true}).fill('https://music.example/song.mp3');await page.getByRole('button',{name:'Открыть',exact:true}).click();await page.waitForFunction(()=>document.querySelector('audio.music-audio')?.currentTime>.15);assert.equal(remotePrepared,1);assert.ok(await page.locator('audio').evaluate(a=>new URL(a.currentSrc).origin===location.origin),'Remote file bytes come from Oracle');if(width<900){await page.getByRole('button',{name:'Музыкальный плеер',exact:true}).click();await page.getByRole('button',{name:'Закрыть музыкальный плеер',exact:true}).click();}else await page.getByRole('button',{name:'Закрыть тестовую музыкальную очередь',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('audio'));await page.getByLabel('Ссылка на аудио',{exact:true}).fill('https://youtu.be/dQw4w9WgXcQ');
  failing=true;await page.getByRole('button',{name:'Открыть',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.music-dock-error')?.textContent);assert.equal(await page.locator('.music-panel').getAttribute('aria-hidden'),'true','Failure keeps the player minimized');assert.equal(await page.locator('iframe').count(),0);assert.equal(youtubeRequests,0,'No YouTube API, video or embed is loaded');
  if(width<900){
   if(width<900)await page.getByRole('button',{name:'Музыкальный плеер',exact:true}).click();else await page.getByRole('button',{name:'Подробности музыки',exact:true}).click();await page.getByText('YouTube requires server verification',{exact:true}).waitFor();await page.getByText('Аудио через Oracle недоступно',{exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Продолжить в подробностях',exact:true}).isEnabled(),true,'Play remains an actionable server retry');const attempts=prepared.length;failureStatus=401;await page.getByRole('button',{name:'Продолжить в подробностях',exact:true}).click();await page.waitForFunction(n=>document.querySelector('.music-dock-error')?.textContent&&document.querySelector('.music-play')?.disabled===false,attempts);assert.equal(prepared.length,attempts+1,'Play retries Oracle');assert.equal(await page.locator('iframe').count(),0);
  }else{
   await page.getByRole('button',{name:'Открыть музыкальный плеер',exact:true}).click();
   await page.locator('.music-nav .music-bar.is-nav-expanded').waitFor();
   await page.locator('.music-nav .music-full-lyric').getByText(/Ошибка аудио/).waitFor();
   const play=page.locator('.music-nav .music-full-play');
   assert.equal(await play.isEnabled(),true,'Expanded Play remains available for provider retry');
   const attempts=prepared.length;failureStatus=401;await play.click();
   await page.waitForFunction(n=>document.querySelector('.music-dock-error')?.textContent&&document.querySelector('.music-full-play')?.disabled===false,attempts);
   assert.equal(prepared.length,attempts+1,'Expanded Play retries Oracle');
   assert.equal(await page.locator('iframe').count(),0);
  }
  if(width<900){
   const attempts=prepared.length;
   await page.getByRole('button',{name:'Воспроизвести через YouTube',exact:true}).click();
   const embed=page.locator('.music-island iframe');
   assert.match(await embed.getAttribute('src'),/^https:\/\/www\.youtube-nocookie\.com\/embed\/dQw4w9WgXcQ\?/);
   await page.getByRole('button',{name:'Закрыть видео YouTube',exact:true}).click();
   await embed.waitFor({state:'detached'});
   assert.equal(prepared.length,attempts,'Opening and closing the explicit embed does not retry the failed server');
  }
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);await page.screenshot({path:path.join(DIR,'music-audio-'+width+'.png')});await page.close();console.log('PASS pasted YouTube URL, real audio decode/seek, collapsed playback, cleanup, compact errors and server retry at '+width+'px');
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const name of['music-audio-harness.html','music-audio-harness.jsx'])await fs.rm(path.join(DIR,name),{force:true});});
