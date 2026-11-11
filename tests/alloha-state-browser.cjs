// Real local HLS decoding, mocked API expiration/refusal; no external ML/CDN.
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
let browser,vite,debug=async()=>({});
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/alloha-state');await fs.mkdir(dir,{recursive:true});
 const manifest=path.join(dir,'master.m3u8');
 execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=8','-t','180','-c:v','libx264','-preset','ultrafast','-g','16','-pix_fmt','yuv420p','-hls_time','2','-hls_list_size','0','-hls_segment_type','fmp4','-y',manifest],{cwd:dir});
 await fs.writeFile(path.join(dir,'index.html'),'<div id="root"></div><script type="module" src="/.codex-local/test-output/alloha-state/app.jsx"></script>');
 await fs.writeFile(path.join(dir,'app.jsx'),`
 import React,{useState}from'react';import{createRoot}from'react-dom/client';import OnlineViewer from'/src/OnlineViewer.jsx';import'/src/styles.css';
 window.MEDIA_VAULT_CONFIG={};localStorage.setItem('mediavault_player_preferences_v1',JSON.stringify({gpu:false,ambient:false,depthShadow:false}));
 const service={server:'https://fixture.example',session:{serverVersion:50},request:async(p,o={})=>{const r=await fetch('https://fixture.example'+p,{method:o.method||'GET',headers:{'Content-Type':'application/json'},body:o.body?JSON.stringify(o.body):undefined,signal:o.signal});const d=await r.json();if(!r.ok)throw Object.assign(Error(d.detail||'closed'),{status:r.status});return d;}};
 const entry={number:1,season:1,title:'Серия 1',url:'https://alloha.yani.tv/?fixture=1'};
 function Demo(){const[open,setOpen]=useState(true);window.unmountPlayer=()=>setOpen(false);return <main style={{maxWidth:960,margin:'auto'}}>{open&&<OnlineViewer entries={[entry]} initial={entry} kind="video" title="Проверка восстановления" service={service} userId="state-test" identity="state-test" metadata={{}} inline onClose={()=>setOpen(false)}/>}</main>;}createRoot(document.getElementById('root')).render(<Demo/>);
 `);
 const {createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/alloha-state',logLevel:'error',server:{watch:null,port:0,strictPort:false,host:'127.0.0.1'}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});const page=await browser.newPage({viewport:{width:1280,height:900}});
 const errors=[],reports=[],requests=[],expired=new Map();let prepared=0;
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>document.addEventListener('playing',event=>{const v=event.target;if(v instanceof HTMLVideoElement&&window.initialBuffer===undefined){window.initialBuffer=v.buffered.length?v.buffered.end(0)-v.currentTime:0;}},true));
 await page.route('https://fixture.example/**',async route=>{
  const req=route.request(),u=new URL(req.url()),parts=u.pathname.split('/'),sid=parts[2],mode=expired.get(sid),cors={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*'};
  const json=(data,status=200)=>route.fulfill({status,contentType:'application/json',headers:cors,body:JSON.stringify(data)});
  requests.push({path:u.pathname,method:req.method()});
  if(req.method()==='OPTIONS')return json({});
  if(u.pathname==='/online/prepare')return json({id:'lease'+(++prepared),url:'/stream/lease'+prepared+'/master.m3u8',type:'hls',qualities:[180],expiresIn:900,allohaMode:'browser',playbackTelemetry:true});
  if(parts[1]==='online'){
   if(req.method()==='DELETE')return json({closed:true});
   if(parts[3]==='heartbeat')return mode==='lease'?json({detail:'expired'},410):json({expiresIn:900});
   if(parts[3]==='playback'){reports.push({sid,...req.postDataJSON()});return mode==='lease'?json({detail:'expired'},404):json({received:true,expiresIn:900});}
  }
  if(parts[1]==='stream'){
   if(mode==='media')return json({detail:'session refused'},409);
   const file=path.basename(u.pathname),data=await fs.readFile(path.join(dir,file));
   return route.fulfill({contentType:file.endsWith('.m3u8')?'application/vnd.apple.mpegurl':'video/mp4',headers:cors,body:data});
  }
  return json({});
 });
 debug=async()=>({prepared,errors,reports:reports.slice(-8),requests:requests.slice(-8),video:await page.locator('video').evaluateAll(vs=>vs.map(v=>({time:v.currentTime,paused:v.paused,seeking:v.seeking,ready:v.readyState,src:v.currentSrc.slice(0,80),error:v.error?.code}))),text:(await page.locator('body').innerText()).slice(-500)});
 await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/alloha-state/index.html');
 const video=page.locator('.mv-player-media');
 await page.waitForFunction(()=>{const v=document.querySelector('.mv-player-media');return v?.currentTime>1&&!v.paused;});
 await video.evaluate(v=>{window.originalVideo=v;v.currentTime=12;v.playbackRate=1.25;});
 await page.waitForFunction(()=>{const v=document.querySelector('.mv-player-media');return v?.currentTime>=12&&!v.seeking;});
 assert.ok(await page.evaluate(()=>window.initialBuffer>=7.9),'Alloha autostarts with at least two four-second segments reserved');console.log('Initial playback ready with eight-second reserve');
 let previousSource=await video.evaluate(v=>v.currentSrc);expired.set('lease1','lease');await page.evaluate(()=>dispatchEvent(new Event('focus')));
 await page.waitForFunction(old=>{const v=document.querySelector('.mv-player-media');return v?.currentSrc&&v.currentSrc!==old&&v.currentTime>=12&&!v.paused&&v.readyState>=2;},previousSource);
 console.log('Playing recovery ready');
 assert.equal(await video.evaluate(v=>v===window.originalVideo),true,'Reconnect preserves the React/native player');
 await video.evaluate(v=>{v.pause();v.currentTime=18;});
 await page.waitForFunction(()=>{const v=document.querySelector('.mv-player-media');return v.paused&&!v.seeking&&Math.abs(v.currentTime-18)<.1;});
 previousSource=await video.evaluate(v=>v.currentSrc);expired.set('lease2','lease');await page.evaluate(()=>dispatchEvent(new Event('focus')));
 await page.waitForFunction(old=>{const v=document.querySelector('.mv-player-media');return v?.currentSrc&&v.currentSrc!==old&&v.readyState>=2&&!v.seeking&&Math.abs(v.currentTime-18)<.3&&v.paused;},previousSource);
 console.log('Paused recovery ready');
 await video.evaluate(v=>v.play());previousSource=await video.evaluate(v=>v.currentSrc);expired.set('lease3','media');await video.evaluate(v=>{v.currentTime=150;});
 await page.waitForFunction(old=>{const v=document.querySelector('.mv-player-media');return v?.currentSrc&&v.currentSrc!==old&&v.readyState>=2&&v.currentTime>=149&&!v.paused&&!v.seeking;},previousSource,{timeout:30000});
 assert.equal(prepared,4,'Each failure creates one replacement session');
 assert.ok(reports.some(r=>r.time>=12&&r.rate===1.25));assert.ok(reports.some(r=>r.paused&&Math.abs(r.time-18)<.3));
 assert.deepEqual(errors,[]);
 await page.evaluate(()=>unmountPlayer());await page.waitForTimeout(100);const count=reports.length;await page.waitForTimeout(100);assert.equal(reports.length,count);
 console.log(JSON.stringify({passed:true,playingResume:true,pausedResume:true,segment409Resume:true,sameVideoElement:true,preparations:prepared,telemetryReports:reports.length}));
})().catch(async e=>{console.error(e.message.slice(0,700));console.error(JSON.stringify(await debug()));process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
