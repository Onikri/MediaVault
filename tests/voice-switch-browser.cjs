// Picking another voice in the player switches the video source itself.
// Real React + hls.js + decoded fixture video. Server and balancer replies are
// fixtures (no live Alloha/Kodik/Collaps): this is the browser contract, not a
// live playback check.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {execFileSync}=require('node:child_process');const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'.codex-local/test-output/voice-switch'),harness=path.join(DIR,'voice-switch-harness.html');
let vite,browser,lastPage;
const ffmpeg=args=>execFileSync('ffmpeg',['-v','error',...args]);
const hls=(name)=>['-f','hls','-hls_time','4','-hls_playlist_type','vod','-hls_segment_filename',path.join(DIR,name+'-%02d.ts'),'-y',path.join(DIR,name+'.m3u8')];
(async()=>{
 await fs.mkdir(DIR,{recursive:true});
 // Server-relayed players (Alloha, Kodik): muxed renditions. Collaps: one video
 // rendition and two dubs as separate audio renditions, as its CDN publishes them.
 for(const height of [360,720])ffmpeg(['-f','lavfi','-i',`testsrc2=size=${height*16/9}x${height}:rate=12`,'-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','60','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-g','48','-c:a','aac',...hls(String(height))]);
 ffmpeg(['-f','lavfi','-i','testsrc2=size=640x360:rate=12','-t','60','-an','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-g','48',...hls('v360')]);
 for(const [name,frequency] of [['a0',330],['a1',660]])ffmpeg(['-f','lavfi','-i',`sine=frequency=${frequency}:sample_rate=44100`,'-t','60','-vn','-c:a','aac',...hls(name)]);
 const jsx=`import React from 'react';import {createRoot} from 'react-dom/client';import TitlePage from '/src/TitlePage.jsx';import OnlineWatch from '/src/OnlineWatch.jsx';import '/src/styles.css';import '/src/title-page.css';import '/src/discovery-polish.css';import '/src/world-library.css';
 window.MEDIA_VAULT_CONFIG={importServerUrl:'https://fixture.example'};
 const item={id:'mal:57334',title:'Дандадан',kind:'anime',ids:{mal:'57334'},year:2024};
 const profile={title:'Дандадан',sourceId:'57334',cover:'https://fixture.example/poster.svg',year:2024,format:'ТВ-сериал',episodes:2,duration:24,description:'Фикстура.'};
 const episodes=make=>[1,2].map(number=>({number,season:1,url:make(number)}));
 const voice=(id,name,player,make)=>({id,name,language:'ru',kind:'voice',variants:[{id:'v-'+id,name,url:make(1),sourceUrl:'https://'+player.toLowerCase()+'.example/title',player,provider:'kinobox',episodes:episodes(make)}]});
 const collaps=audio=>n=>'https://api.nextembed.ws/embed/serial/77?mv_audio='+audio+'&mv_season=1&mv_episode='+n;
 const voices=[voice('dub','Дубляж','Alloha',n=>'https://alloha.example/?season=1&episode='+n),voice('anilibria','AniLibria','Kodik',n=>'https://kodik.example/serial/1/'+n),voice('dreamcast','Dream Cast','Collaps',collaps(0)),voice('anidub','AniDub','Collaps',collaps(1))];
 const service={server:'https://fixture.example',session:{serverVersion:35},request:async(p,o={})=>{const r=await fetch('https://fixture.example'+p,{method:o.method||'GET',body:o.body?JSON.stringify(o.body):undefined,signal:o.signal});if(!r.ok)throw Error('Fixture HTTP '+r.status);return r.json();}};
 const discovery={data:{voices,providers:[],complete:true},loading:false,retry:()=>{}};
 createRoot(document.getElementById('root')).render(<main className="app-main"><TitlePage title={{id:item.id,name:item.title,section:'anime',category:'video',items:[],parts:[],online:true}} state={{user:{sub:'viewer'},catalog:{items:[]}}} actions={{}} online onlineProfile={profile} onlineFacts={[]} onBack={()=>{}} onRelated={()=>{}} server={service.server} materials={<OnlineWatch item={item} profile={profile} discovery={discovery} service={service} userId="viewer"/>}/></main>);`;
 await fs.writeFile(harness,'<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="scene-root"></div><div id="root"></div><script type="module" src="/.codex-local/test-output/voice-switch/voice-switch-harness.jsx"></script></html>');
 await fs.writeFile(harness.replace('.html','.jsx'),jsx);
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,cacheDir:path.join(ROOT,'.codex-local/cache/vite-voice-switch'),logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 const context=await browser.newContext({viewport:{width:1280,height:900},reducedMotion:'reduce'}),page=await context.newPage(),errors=[],prepares=[],network=[];
 lastPage=page;page.on('pageerror',e=>{errors.push(e.message);console.error('UI_ERROR',e.stack);});
 await page.addInitScript(()=>{if(!sessionStorage.getItem('seeded')){sessionStorage.setItem('seeded','1');localStorage.setItem('mv_watch_v1:viewer:57334',JSON.stringify({voiceId:'dub',episode:1,season:1}));}});
 const cors={'access-control-allow-origin':'*','access-control-allow-headers':'*','access-control-allow-methods':'*'};
 let leases=0,holdKodik=false,releaseKodik,failKodik=false;
 const masters={alloha:'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1400000,RESOLUTION=1280x720,NAME="1080p"\n720.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=640x360,NAME="480p"\n360.m3u8\n',
  kodik:'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1400000,RESOLUTION=1280x720,NAME="720p"\n720.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=640x360,NAME="360p"\n360.m3u8\n'};
 const file=async(route,name)=>route.fulfill({contentType:name.endsWith('.ts')?'video/mp2t':'application/vnd.apple.mpegurl',headers:cors,body:await fs.readFile(path.join(DIR,name))});
 await page.route('https://fixture.example/**',async route=>{
  const req=route.request(),url=new URL(req.url()),json=(data,status=200)=>route.fulfill({status,contentType:'application/json',headers:cors,body:JSON.stringify(data)});
  if(req.method()==='OPTIONS')return route.fulfill({status:204,headers:cors});
  if(url.pathname==='/online/prepare'){
   const body=req.postDataJSON(),viewer=String(body.clientId||'').endsWith(':viewer'),provider=body.url.includes('kodik')?'kodik':'alloha';
   if(viewer)prepares.push(body);
   if(viewer&&provider==='kodik'&&holdKodik)await new Promise(resolve=>releaseKodik=resolve);
   if(viewer&&provider==='kodik'&&failKodik)return json({detail:'fixture failure'},502);
   const id=provider+'-'+(++leases);
   return json({id,type:'hls',url:'/online/'+id+'/master.m3u8',qualities:provider==='kodik'?[720,360]:[1080,480],expiresIn:120,subtitles:[]});
  }
  if(url.pathname.endsWith('/heartbeat')||req.method()==='DELETE')return json({closed:true,expiresIn:120});
  const lease=/^\/online\/((alloha|kodik)-\d+)\/(.+)$/.exec(url.pathname);
  if(lease){network.push(lease[1]+'/'+lease[3]);return lease[3]==='master.m3u8'?route.fulfill({contentType:'application/vnd.apple.mpegurl',headers:cors,body:masters[lease[2]]}):file(route,lease[3]);}
  return json({tracks:[],intervals:[],ratings:[],items:[]});
 });
 // Collaps: the viewer's browser opens the embed and the CDN itself (CORS).
 await page.route('https://api.nextembed.ws/**',route=>{network.push('collaps-embed');return route.fulfill({contentType:'text/html',headers:cors,body:'makePlayer({seasons:[{"season":1,"episodes":[{"episode":1,"hls":"https://cdn.collaps.example/master.m3u8"},{"episode":2,"hls":"https://cdn.collaps.example/master.m3u8"}]}]})'});});
 await page.route('https://cdn.collaps.example/**',route=>{const name=new URL(route.request().url()).pathname.slice(1);network.push('collaps/'+name);
  if(name==='master.m3u8')return route.fulfill({contentType:'application/vnd.apple.mpegurl',headers:cors,body:'#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="Dream Cast",DEFAULT=NO,AUTOSELECT=NO,URI="a0.m3u8"\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="AniDub",DEFAULT=NO,AUTOSELECT=NO,URI="a1.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=500000,RESOLUTION=640x360,AUDIO="a"\nv360.m3u8\n'});
  return file(route,name);});

 const video=page.locator('.mv-player-stage>video').first();
 const state=()=>video.evaluate(v=>({src:v.currentSrc,time:v.currentTime,paused:v.paused,ready:v.readyState}));
 const sheet=()=>page.getByRole('dialog',{name:'Настройки просмотра'});
 async function qualities(){
  await page.getByRole('button',{name:'Настройки плеера',exact:true}).click();await sheet().waitFor();
  await sheet().getByRole('button',{name:/^Качество/}).click();
  const labels=await sheet().getByRole('radiogroup',{name:'Качество',exact:true}).getByRole('radio').evaluateAll(ns=>ns.map(n=>n.textContent.trim()));
  await sheet().focus();await page.keyboard.press('Escape');await page.keyboard.press('Escape');await sheet().waitFor({state:'detached'});
  // hls.js orders levels by bitrate; compare the offered heights, highest first.
  return labels.map(label=>/^\d+p/.exec(label)?.[0]).filter(Boolean).sort((a,b)=>parseInt(b)-parseInt(a));
 }
 async function pick(name){
  await page.getByRole('button',{name:/^Озвучка: /}).click();
  await page.getByRole('radiogroup',{name:'Озвучка',exact:true}).getByRole('radio',{name:new RegExp('^'+name)}).click();
 }
 const newSource=old=>page.waitForFunction(old=>{const v=document.querySelector('.mv-player-stage>video');return v&&v.currentSrc!==old&&v.readyState>=2&&!v.paused;},old,{timeout:30000});
 const viewerPrepares=provider=>prepares.filter(b=>b.url.includes(provider)).length;

 await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/voice-switch/voice-switch-harness.html');
 await page.getByRole('button',{name:'Смотреть серию 1'}).click();
 await page.waitForFunction(()=>{const v=document.querySelector('.mv-player-stage>video');return v?.readyState>=2&&!v.paused&&v.currentTime>.5;},{},{timeout:30000});
 assert.equal(await page.getByRole('button',{name:/^Озвучка: /}).getAttribute('aria-label'),'Озвучка: Дубляж');
 assert.equal(viewerPrepares('alloha'),1);
 {const q=await qualities();assert.deepEqual(q,['1080p','480p'],'Alloha qualities '+JSON.stringify(q));}

 // Alloha → Kodik: a new stream from the second the old one reached, with a visible loader.
 await video.evaluate(v=>{v.currentTime=20;});await page.waitForFunction(()=>document.querySelector('.mv-player-stage>video').currentTime>=20.3);
 let before=await state();holdKodik=true;
 await pick('AniLibria');
 await page.locator('.mvx-status.is-switching').getByText('Загружаем озвучку «AniLibria»').waitFor();
 await page.locator('.mv-player').screenshot({path:path.join(DIR,'voice-switch-loading.png')});
 for(let i=0;i<40&&!releaseKodik;i++)await page.waitForTimeout(100);
 assert.ok(releaseKodik,'Kodik stream requested by the viewer');assert.equal((await state()).src,before.src,'until Kodik answers, the loaded stream stays');
 holdKodik=false;releaseKodik();
 await newSource(before.src);
 let after=await state();
 assert.ok(after.time>=before.time-.5,'Kodik continues from '+before.time+', got '+after.time);
 assert.equal(await page.locator('.mvx-status.is-switching').count(),0,'the loader leaves once the new voice plays');
 assert.ok(network.some(n=>/^kodik-\d+\/(?:720|360)-\d+\.ts$/.test(n)),'Kodik segments are played');
 assert.equal(await page.getByRole('button',{name:/^Озвучка: /}).getAttribute('aria-label'),'Озвучка: AniLibria');
 assert.deepEqual(await qualities(),['720p','360p'],'qualities follow the Kodik stream');

 // Kodik → Collaps: opened in the browser, no server lease.
 before=await state();const serverPrepares=prepares.length;
 await pick('Dream Cast');await newSource(before.src);after=await state();
 assert.equal(prepares.length,serverPrepares,'Collaps plays without a server lease');
 assert.ok(network.includes('collaps-embed')&&network.includes('collaps/a0.m3u8'),'Collaps embed and the chosen dub track load');
 assert.ok(after.time>=before.time-.5,'Collaps continues from '+before.time+', got '+after.time);
 assert.deepEqual(await qualities(),['360p'],'qualities follow the Collaps stream');

 // Collaps → Collaps: the other dub is an audio track of the same stream.
 before=await state();const embeds=network.filter(n=>n==='collaps-embed').length;
 await pick('AniDub');
 await page.waitForFunction(()=>performance.getEntriesByType('resource').some(e=>e.name.includes('cdn.collaps.example/a1.m3u8')),{},{timeout:15000}).catch(()=>{});
 for(let i=0;i<50&&!network.includes('collaps/a1.m3u8');i++)await page.waitForTimeout(100);
 assert.ok(network.includes('collaps/a1.m3u8'),'the AniDub track is loaded');
 after=await state();
 assert.equal(after.src,before.src,'same stream: no reload');assert.ok(after.time>=before.time,'playback keeps going');
 assert.equal(network.filter(n=>n==='collaps-embed').length,embeds,'the embed is not opened again');
 assert.equal(await page.getByRole('button',{name:/^Озвучка: /}).getAttribute('aria-label'),'Озвучка: AniDub');

 // A failing voice says so and offers the playing one back instead of reverting silently.
 failKodik=true;before=await state();const kodikTries=viewerPrepares('kodik');
 await pick('AniLibria');
 const failure=page.locator('.mvx-status.is-switch-failed');
 await failure.getByText(/Не удалось включить «AniLibria»/).waitFor({timeout:20000});
 assert.equal(viewerPrepares('kodik'),kodikTries+1);assert.equal((await state()).src,before.src);
 await page.locator('.mv-player').screenshot({path:path.join(DIR,'voice-switch-failed.png')});
 await failure.getByRole('button',{name:'Вернуть «AniDub»'}).click();
 await failure.waitFor({state:'detached'});
 assert.equal(await page.getByRole('button',{name:/^Озвучка: /}).getAttribute('aria-label'),'Озвучка: AniDub');
 assert.equal((await state()).src,before.src,'giving the voice back keeps the playing stream');
 failKodik=false;

 // Back to Alloha: a fresh Alloha stream, same second, Alloha's qualities again.
 before=await state();
 await pick('Дубляж');await newSource(before.src);after=await state();
 assert.equal(viewerPrepares('alloha'),2);assert.ok(after.time>=before.time-.5,'Alloha continues from '+before.time+', got '+after.time);
 assert.deepEqual(await qualities(),['1080p','480p'],'qualities follow the Alloha stream again');
 assert.equal(await page.locator('.mv-external-audio').count(),0,'a voice switch never falls back to separate audio over the old video');
 await page.screenshot({path:path.join(DIR,'voice-switch.png')});
 assert.deepEqual(errors,[]);
 await context.close();
 console.log('PASS voice switch Alloha → Kodik → Collaps → Collaps track → failure + revert → Alloha: new streams, kept position, rebuilt qualities');
})().catch(async e=>{console.error(e);if(lastPage){await lastPage.screenshot({path:path.join(DIR,'failure.png'),fullPage:true}).catch(()=>{});console.error((await lastPage.locator('body').innerText().catch(()=>'')).slice(0,2500));}process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const file of [harness,harness.replace('.html','.jsx')])await fs.rm(file,{force:true});});
