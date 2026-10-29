// Real HTMLAudioElement decoding/seek/lifecycle; resolver and YouTube are fixtures.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'test-output');let browser,vite;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});const audioPath=path.join(DIR,'music-server-fixture.m4a');execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','sine=frequency=440:duration=16','-c:a','aac','-movflags','+faststart','-threads','1','-y',audioPath]);const audio=await fs.readFile(audioPath);
 await fs.writeFile(path.join(DIR,'music-audio-harness.html'),'<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/test-output/music-audio-harness.jsx"></script></html>');
 await fs.writeFile(path.join(DIR,'music-audio-harness.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import MiniMusicPlayer from'/src/MiniMusicPlayer.jsx';import{OnlineMusic}from'/src/OnlineLibrary.jsx';import'/src/styles.css';
 window.MEDIA_VAULT_CONFIG={importServerUrl:location.origin};
 const service={server:location.origin,request:async(path,options={})=>{const response=await fetch(path,{method:options.method||'GET',body:options.body?JSON.stringify(options.body):undefined,headers:{'Content-Type':'application/json'},signal:options.signal});const result=await response.json();if(!response.ok)throw Error(result.detail);return result;}};
 createRoot(document.getElementById('root')).render(<><header style={{display:'flex',justifyContent:'flex-end',padding:20}}><MiniMusicPlayer service={service} placement="nav" userId="audio-owner"/></header><OnlineMusic userId="audio-owner"/></>);
 `);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 for(const width of[390,1440]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));const prepared=[],closed=[];let failing=false;
  const token='a'.repeat(43),resource='b'.repeat(16);
  await page.route('**/music/play',async route=>{prepared.push(route.request().postDataJSON());await route.fulfill(failing?{status:502,json:{detail:'YouTube requires server verification'}}:{json:{id:token,streamUrl:'/online/'+token+'/'+resource,mime:'audio/mp4',duration:16,title:'Server audio fixture'}});});
  await page.route('**/music/metadata?**',r=>r.fulfill({json:{found:false}}));
  await page.route('https://i.ytimg.com/**',r=>r.abort());
  await page.route('**/online/**',async route=>{if(route.request().method()==='DELETE'){closed.push(route.request().url());return route.fulfill({json:{closed:true}});}const range=route.request().headers().range,match=range?.match(/bytes=(\d+)-(\d*)/),start=match?Number(match[1]):0,end=match&&match[2]?Math.min(Number(match[2]),audio.length-1):audio.length-1;return route.fulfill({status:match?206:200,contentType:'audio/mp4',headers:{'Accept-Ranges':'bytes','Content-Length':String(end-start+1),...(match?{'Content-Range':'bytes '+start+'-'+end+'/'+audio.length}:{})},body:audio.subarray(start,end+1)});});
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/music-audio-harness.html');
  await page.getByLabel('Ссылка на аудио',{exact:true}).fill('https://youtu.be/dQw4w9WgXcQ');await page.getByRole('button',{name:'Открыть',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('audio.music-audio')?.currentTime>.15);
  assert.equal(prepared[0].url,'https://www.youtube.com/watch?v=dQw4w9WgXcQ');assert.equal(await page.locator('iframe').count(),0);
  if(width<900)await page.getByRole('button',{name:'Музыкальный плеер',exact:true}).click();else await page.getByRole('button',{name:'Подробности музыки',exact:true}).click();
  await page.getByRole('button',{name:'Свернуть музыкальный плеер',exact:true}).click();const before=await page.locator('audio').evaluate(a=>a.currentTime);await page.waitForTimeout(300);assert.ok(await page.locator('audio').evaluate((a,n)=>!a.paused&&a.currentTime>n,before),'Collapsed server audio keeps playing');
  if(width<900)await page.getByRole('button',{name:'Музыкальный плеер',exact:true}).click();else await page.getByRole('button',{name:'Подробности музыки',exact:true}).click();
  const slider=page.getByLabel('Позиция музыки в подробностях',{exact:true});await slider.fill('8');await page.waitForFunction(()=>document.querySelector('audio')?.currentTime>=7.9);
  await page.getByRole('button',{name:'Пауза в подробностях',exact:true}).click();assert.equal(await page.locator('audio').evaluate(a=>a.paused),true);
  await page.getByRole('button',{name:'Продолжить в подробностях',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('audio').paused);
  await page.getByRole('button',{name:'Закрыть музыкальный плеер',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('audio'));assert.equal(closed.length,1,'Close releases backend capability');
  failing=true;await page.getByRole('button',{name:'Открыть',exact:true}).click();await page.getByText('YouTube requires server verification',{exact:true}).waitFor();assert.equal(await page.locator('iframe').count(),0,'A failed resolver never creates an iframe silently');await page.getByRole('button',{name:'Открыть официальный плеер YouTube',exact:true}).waitFor();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);await page.screenshot({path:path.join(DIR,'music-audio-'+width+'.png')});await page.close();console.log('PASS pasted YouTube URL, real audio decode/seek, collapsed playback, cleanup and explicit fallback at '+width+'px');
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const name of['music-audio-harness.html','music-audio-harness.jsx'])await fs.rm(path.join(DIR,name),{force:true});});
