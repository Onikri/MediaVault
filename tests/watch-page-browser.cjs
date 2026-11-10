// Real React + HLS.js + decoded video/audio. Public-source/Oracle replies are fixtures.
const {showEpisodes}=require('./player-episodes.cjs');
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {execFileSync}=require('node:child_process');const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'.codex-local/test-output/watch'),harness=path.join(DIR,'watch-page-harness.html');
let vite,browser,lastPage;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});
 for(const height of [360,720])execFileSync('ffmpeg',['-v','error','-f','lavfi','-i',`testsrc2=size=${height*16/9}x${height}:rate=12`,'-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','100','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-g','48','-c:a','aac','-f','hls','-hls_time','4','-hls_playlist_type','vod','-hls_segment_filename',path.join(DIR,height+'-%02d.ts'),'-y',path.join(DIR,height+'.m3u8')]);
 const jsx=`import React,{useState} from 'react';import {createRoot} from 'react-dom/client';import TitlePage from '/src/TitlePage.jsx';import OnlineWatch from '/src/OnlineWatch.jsx';import '/src/styles.css';import '/src/title-page.css';import '/src/discovery-polish.css';import '/src/world-library.css';
 window.MEDIA_VAULT_CONFIG={importServerUrl:'https://fixture.example'};
 const item={id:'mal:57334',title:'Дандадан',kind:'anime',ids:{mal:'57334'},year:2024};
 const profile={title:'Дандадан',sourceId:'57334',cover:'https://fixture.example/poster.svg',year:2024,format:'ТВ-сериал',status:'Вышел',episodes:12,duration:24,score:8.46,description:'Момо верит в призраков, Окарун — в пришельцев. Один спор приводит их к встрече с обоими. История о дружбе, первой любви и странных приключениях.',genres:['Комедия','Экшен','Сверхъестественное'],characters:[{id:'momo',name:'Момо Аясэ',role:'Главная героиня',image:'https://fixture.example/poster.svg'},{id:'okarun',name:'Кэн Такакура',role:'Главный герой',image:'https://fixture.example/poster.svg'}]};
 const voices=['a','b'].map((id,i)=>({id,name:i?'Команда Б':'Команда А',language:'ru',kind:'voice',variants:[{id:'v'+id,name:i?'Команда Б':'Команда А',url:'https://source.example/'+id,sourceUrl:'https://source.example/title',player:'Kodik',episodes:[1,2,3,4,5,6,7,8,9,10,11,12].map(number=>({number,url:'https://source.example/'+id+'/'+number}))}]}));
 voices[0].variants.push({...voices[0].variants[0],id:'a-hd',url:'https://source.example/a-hd'});
// Subtitle versions: Kodik's carries the text in the picture (no track); the other publishes a VTT.
for(const [id,name] of [['c','Crunchyroll.Subtitles'],['d','Студия субтитров']])voices.push({id,name,language:'ru',kind:'subtitles',variants:[{id:'v'+id,name,url:'https://source.example/'+id,sourceUrl:'https://source.example/title',player:'Kodik',episodes:[1,2,3,4,5,6,7,8,9,10,11,12].map(number=>({number,url:'https://source.example/'+id+'/'+number}))}]});
 const service={server:'https://fixture.example',session:{serverVersion:35},request:async(p,o={})=>{const r=await fetch('https://fixture.example'+p,{method:o.method||'GET',body:o.body?JSON.stringify(o.body):undefined,signal:o.signal});if(!r.ok)throw Error('Fixture HTTP '+r.status);return r.json();}};
 const discovery={data:{voices,providers:[],complete:true},loading:false,retry:()=>{}};
 function Demo(){const [revision,setRevision]=useState(0);return <main className="app-main"><button id="remount" onClick={()=>setRevision(n=>n+1)}>Открыть страницу заново</button><TitlePage key={revision} title={{id:item.id,name:item.title,section:'anime',category:'video',items:[],parts:[],online:true}} state={{user:{sub:'viewer'},catalog:{items:[]}}} actions={{}} online onlineProfile={profile} onlineFacts={[["Язык","Русский"],["Формат","ТВ-сериал"]]} onBack={()=>{}} onRelated={()=>{}} server={service.server} materials={<OnlineWatch item={item} profile={profile} discovery={discovery} service={service} userId="viewer"/>}/></main>};createRoot(document.getElementById('root')).render(<Demo/>);`;
 await fs.writeFile(harness,'<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="scene-root"></div><div id="root"></div><script type="module" src="/.codex-local/test-output/watch/watch-page-harness.jsx"></script></html>');
 await fs.writeFile(harness.replace('.html','.jsx'),jsx);
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,cacheDir:path.join(ROOT,'.codex-local/cache/vite-watch'),logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 for(const width of [390,1440]){
  const context=await browser.newContext({viewport:{width,height:1000},reducedMotion:'reduce'}),page=await context.newPage(),errors=[],requests=[],previewLeases=new Set(),previewHighLevels=[];let leases=0,networkDown=false,holdQuality=true,releaseQuality;let qualityRequests=0;
  lastPage=page;page.on('pageerror',e=>{errors.push(e.message);console.error('UI_ERROR',e.stack);});
  const cors={'access-control-allow-origin':'*','access-control-allow-headers':'*','access-control-allow-methods':'*'};
  await page.route('https://fixture.example/**',async route=>{
   const req=route.request(),url=new URL(req.url()),json=data=>route.fulfill({contentType:'application/json',headers:cors,body:JSON.stringify(data)});
   if(req.method()==='OPTIONS')return route.fulfill({status:204,headers:cors});
   if(url.pathname==='/poster.svg')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="560"><rect width="400" height="560" fill="#375963"/><circle cx="230" cy="160" r="90" fill="#d4b89f"/><path d="M30 560L180 240 340 560" fill="#748277"/></svg>'});
   if(url.pathname==='/sources/inspect'){
    const b=req.postDataJSON(),studio=b.dub_url.split('/').at(-1);return json({episodes:Array.from({length:12},(_,i)=>({number:i+1,season:1,url:'https://source.example/'+studio+'/'+(i+1)}))});
   }
   if(url.pathname==='/sources/qualities'){qualityRequests++;if(holdQuality)await new Promise(resolve=>releaseQuality=resolve);const b=req.postDataJSON(),qualities=b.url.includes('/b/')?[2160,720,360]:b.url.includes('/a-hd/')?[1080,720,360]:[720,360];return json({qualities,best:qualities[0],original:false});}
   if(url.pathname==='/online/prepare'){const b=req.postDataJSON();requests.push(b);const id='lease'+(++leases);if(b.clientId?.startsWith('previews-'))previewLeases.add(id);const tracks=b.url.includes('/c/')?[]:b.url.includes('/d/')?[{id:'ru',name:'Студия субтитров',language:'ru',url:'/online/'+id+'/studio.vtt'}]:[{id:'ru',name:'Русские',language:'ru',url:'/online/'+id+'/sub.vtt'}];return json({id,type:'hls',url:'/online/'+id+'/master.m3u8',qualities:[720,360],expiresIn:120,subtitles:tracks});}
   if(url.pathname.endsWith('/heartbeat')||req.method()==='DELETE')return json({closed:true,expiresIn:120});
   if(url.pathname.endsWith('/master.m3u8'))return route.fulfill({contentType:'application/vnd.apple.mpegurl',headers:cors,body:'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=640x360,NAME="360p"\n360.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=1400000,RESOLUTION=1280x720,NAME="720p"\n720.m3u8\n'});
   if(url.pathname.endsWith('/studio.vtt'))return route.fulfill({contentType:'text/vtt',headers:cors,body:'WEBVTT\n\n00:00:00.000 --> 00:10:00.000\nСубтитры студии\n'});
   if(url.pathname.endsWith('/sub.vtt'))return route.fulfill({contentType:'text/vtt',headers:cors,body:'WEBVTT\n\n00:00:01.000 --> 00:00:30.000\nНезависимые субтитры\n'});
   if(/\/(?:360|720)(?:\.m3u8|-\d+\.ts)$/.test(url.pathname)){if(networkDown)return route.abort('internetdisconnected');const file=path.basename(url.pathname),body=await fs.readFile(path.join(DIR,file));if(previewLeases.has(url.pathname.split('/')[2])&&file.startsWith('720'))previewHighLevels.push(file);return route.fulfill({contentType:file.endsWith('.ts')?'video/mp2t':'application/vnd.apple.mpegurl',headers:cors,body});}
   if(url.pathname.startsWith('/music/timings/'))return json({intervals:[{type:'op',start:2,end:6,source:'AniSkip'}]});
   if(url.pathname.startsWith('/music/anime/'))return json({tracks:Array.from({length:9},(_,i)=>({id:'fixture-theme-'+i,title:'Тестовая тема '+(i+1),artists:['Тестовый исполнитель'],type:i%2?'ED':'OP'}))});
   return json({ratings:[],items:[]});
  });
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/watch/watch-page-harness.html');
  await page.getByRole('button',{name:'Серия 2',exact:false}).first().waitFor();
  assert.equal(await page.locator('.watch-episode-grid .title-episode-card').count(),12);
  assert.equal(await page.locator('#voiceSource').count(),0);assert.equal(await page.locator('[aria-label="Качество просмотра"]').count(),0,'No external voice/quality block');
  // Sources and player options live in one sheet ("Настройки просмотра"): rows that
  // unfold into radio groups and switches. The page shows no separate source block.
  const sheet=()=>page.getByRole('dialog',{name:'Настройки просмотра'});
  const row=label=>sheet().getByRole('button',{name:new RegExp('^'+label)});
  const rowValue=label=>row(label).locator('.mvx-row-value').innerText();
  const choices=label=>sheet().getByRole('radiogroup',{name:label,exact:true});
  const choose=async(label,option)=>{if(!await choices(label).isVisible())await row(label).click();await choices(label).getByRole('radio',{name:new RegExp('^'+option)}).click();};
  const bestVideo=()=>sheet().getByRole('switch',{name:/^Лучшее видео из всех озвучек/});
  const openSources=async()=>{await page.getByRole('button',{name:'Настройки просмотра',exact:true}).click();await sheet().waitFor();};
  const closeSheet=async()=>{await sheet().focus();await page.keyboard.press('Escape');await sheet().waitFor({state:'detached'});};
  const openPlayerSettings=async()=>{await page.getByRole('button',{name:'Настройки плеера',exact:true}).click();await sheet().waitFor();};
  const closePlayer=async()=>{await openPlayerSettings();await sheet().getByRole('button',{name:'Закрыть встроенный просмотр',exact:true}).click();await page.locator('.mv-player-stage>video').waitFor({state:'detached'});};
  await openSources();await row('Озвучка').click();
  assert.deepEqual(await choices('Озвучка').getByRole('radio').evaluateAll(ns=>ns.map(n=>n.querySelector('strong').childNodes[0].textContent)),['Команда А','Команда Б','Студия субтитров','Crunchyroll.Subtitles'],'Subtitle versions come after the dubs');
  const colors=await choices('Озвучка').getByRole('radio').first().evaluate(n=>({color:getComputedStyle(n).color,background:getComputedStyle(n.closest('.player-popover')).backgroundColor}));
  assert.notEqual(colors.background,colors.color,'Voice choices stay legible on the sheet');
  await closeSheet();
  await page.locator('.watch-episode-grid .title-episode-card').first().scrollIntoViewIfNeeded();
  await page.waitForFunction(()=>[...document.querySelectorAll('.watch-episode-grid img')].slice(0,3).length===3&&[...document.querySelectorAll('.watch-episode-grid img')].slice(0,3).every(n=>n.src.startsWith('data:image/')),{},{timeout:30000});
  assert.deepEqual(previewHighLevels,[],'Background previews must not fetch higher-quality video');
  await page.screenshot({path:path.join(DIR,'title-idle-'+width+'.png'),fullPage:true});
  await page.emulateMedia({reducedMotion:'no-preference'});await page.locator('.watch-episode-grid .title-episode-card').first().hover();await page.locator('.episode-motion-frame').first().waitFor();const motionFrame=await page.locator('.episode-motion-frame').first().getAttribute('src');await page.waitForFunction(src=>document.querySelector('.episode-motion-frame')?.src!==src,motionFrame);await page.mouse.move(0,0);await page.emulateMedia({reducedMotion:'reduce'});
  await openSources();await row('Найти другие качества').click();await page.waitForFunction(()=>document.querySelector('.player-popover')?.textContent.includes('Проверяем качества'));
  await closeSheet();await page.locator('.watch-episode-grid .title-episode-card').first().click();await page.waitForFunction(()=>{const v=document.querySelector('.mv-player-stage>video');return v?.readyState>=2&&!v.paused&&v.currentTime>.2;},{},{timeout:6000});
  assert.equal(qualityRequests,1,'Playback starts while the quality probe is still unresolved');holdQuality=false;releaseQuality?.();
  await closePlayer();
  await openSources();await row('Найти другие качества').click();
  await row('Качество').click();await choices('Качество').getByRole('radio',{name:/^2160p/}).waitFor();
  await choose('Качество','2160p');assert.equal(await rowValue('Озвучка'),'Команда Б','A quality only one studio offers switches to that studio');
  await bestVideo().click();await choose('Озвучка','Команда А');
  await bestVideo().click();assert.equal(await rowValue('Качество'),'Лучшее, авто','Returning to a lower-quality studio clears an incompatible filter');
  await bestVideo().click();assert.equal(await bestVideo().getAttribute('aria-checked'),'true');await page.waitForFunction(()=>document.querySelector('.player-popover')?.textContent.includes('Доступно до 2160p'));
  await closeSheet();await page.locator('.watch-episode-grid .title-episode-card').nth(1).click();
  const video=page.locator('.mv-player-stage>video').first();await page.waitForFunction(()=>document.querySelector('.mv-player-stage>video')?.readyState>=2);
  await page.waitForFunction(()=>{const v=document.querySelector('.mv-player-stage>video');return v?.buffered.length&&v.buffered.end(0)>85;},{},{timeout:30000});
  networkDown=true;await video.evaluate(v=>{v.currentTime=6;v.play();});await page.waitForFunction(()=>document.querySelector('.mv-player-stage>video')?.currentTime>=8);await video.evaluate(v=>v.pause());networkDown=false;
  assert.ok(requests.some(b=>b.url==='https://source.example/b/2'),'Best video is selected across voices');
  assert.ok(requests.some(b=>b.url==='https://source.example/a/2'),'Selected studio remains an independent audio lease');
  assert.equal(await page.evaluate(()=>document.fullscreenElement),null);assert.notEqual(await page.evaluate(()=>document.body.style.overflow),'hidden');
  await page.locator('.mv-player').focus();await page.keyboard.press('k');await page.waitForFunction(()=>!document.querySelector('.mv-player-stage>video').paused);
  await video.evaluate(v=>{v.currentTime=3;});await page.getByRole('button',{name:'Пропустить опенинг',exact:false}).waitFor();
  await page.getByRole('button',{name:'Пропустить опенинг',exact:false}).click();assert.ok(await video.evaluate(v=>v.currentTime)>=6);
  assert.equal(await page.locator('.online-video-frameless>header').isVisible(),false);assert.equal(await page.locator('.mv-player-panorama img,.mv-relief-near').count(),0,'Pause keeps one image instead of duplicating the frame');
  // Theater mode is a switch under "Эффекты паузы" (the bar button is gone).
  await openPlayerSettings();await row('Эффекты паузы').click();const theater=sheet().getByRole('switch',{name:/^Кинотеатр/});
  await theater.click();await page.waitForFunction(()=>document.querySelector('.mv-player').classList.contains('is-theater'));await theater.click();await page.waitForFunction(()=>!document.querySelector('.mv-player').classList.contains('is-theater'));
  await row('Эффекты паузы').click();await theater.waitFor({state:'hidden'});
  assert.ok(await page.locator('.player-popover').evaluate(n=>n.scrollHeight<=n.clientHeight+1));
  await page.waitForFunction(()=>+getComputedStyle(document.querySelector('.player-popover')).opacity>=.99);await page.locator('.player-popover').screenshot({path:path.join(DIR,'settings-'+width+'.png')});
  assert.equal(await row('Источник').count(),1,'Source settings are flattened into one row of the player sheet');
  await closeSheet();
  const before=await video.evaluate(v=>({source:v.currentSrc,time:v.currentTime}));
  // The dub switch sits in the control bar; another studio arrives as separate audio.
  await page.getByRole('button',{name:/^Озвучка: /}).click();await page.getByRole('radiogroup',{name:'Озвучка',exact:true}).getByRole('radio',{name:/^Команда Б/}).click();await page.waitForFunction(()=>document.querySelector('.mv-external-audio')?.readyState>=2);
  assert.equal(await video.evaluate(v=>v.currentSrc),before.source,'Audio switch must preserve video source');
  assert.ok(await video.evaluate(v=>v.currentTime)>=before.time);
  await video.evaluate(v=>{v.currentTime=12;});await page.waitForFunction(()=>{const v=document.querySelector('.mv-player-stage>video'),a=document.querySelector('.mv-external-audio');return Math.abs(v.currentTime-a.currentTime)<.6;});
  assert.ok(requests.some(b=>b.url==='https://source.example/b/2'),'Alternate audio belongs to the same episode');
  await openPlayerSettings();await row('Эффекты паузы').click();const depth=sheet().getByRole('switch',{name:/^Эффект на паузе/});
  await depth.click();assert.equal(await page.getByRole('region',{name:'Видеоплеер MediaVault'}).evaluate(n=>n.classList.contains('depth-shadow-off')),true);await depth.click();assert.equal(await page.getByRole('region',{name:'Видеоплеер MediaVault'}).evaluate(n=>n.classList.contains('depth-shadow-off')),false);
  await row('Эффекты паузы').click();await depth.waitFor({state:'hidden'});
  await choose('Субтитры','Русские');
  // Escape folds the open row first, then closes the sheet.
  await page.keyboard.press('Escape');await choices('Субтитры').waitFor({state:'hidden'});await page.keyboard.press('Escape');await sheet().waitFor({state:'detached'});
  await page.locator('.mvx-captions').getByText('Независимые субтитры').waitFor();
  // Episode songs are one list in the "Музыка серии" popover (up to eight, no pages).
  await page.getByRole('button',{name:'Музыка из аниме',exact:true}).click();const music=page.getByRole('dialog',{name:'Музыка серии'});await music.locator('.mvx-song-row').first().waitFor();
  const songs=await music.locator('.mvx-songs').first().locator('.mvx-song-row').count();assert.ok(songs>=1&&songs<=8,'Songs '+songs);assert.ok(await music.evaluate(n=>n.scrollHeight<=n.clientHeight+1));
  await page.waitForFunction(()=>+getComputedStyle(document.querySelector('.player-popover')).opacity>=.99);await music.screenshot({path:path.join(DIR,'music-'+width+'.png')});
  await music.focus();await page.keyboard.press('Escape');await music.waitFor({state:'detached'});
  await video.evaluate(v=>{v.pause();v.currentTime=14;v.dispatchEvent(new Event('timeupdate'));});
  await page.screenshot({path:path.join(DIR,'title-playing-'+width+'.png'),fullPage:true});
  await closePlayer();await page.getByRole('button',{name:'Открыть страницу заново'}).click();
  await page.getByRole('button',{name:'Смотреть серию 2'}).waitFor();await openSources();assert.equal(await rowValue('Озвучка'),'Команда А');
  await closeSheet();await page.getByRole('button',{name:'Смотреть серию 2'}).click();await page.waitForFunction(()=>{const v=document.querySelector('.mv-player-stage>video');return v?.readyState>=2&&v.currentTime>=13;});
  await page.waitForFunction(()=>!!document.querySelector('.mv-external-audio'));
  // While a video plays, the episode grid lives in the player's episode panel.
  await showEpisodes(page);assert.equal(await page.locator('.watch-episode-grid .title-episode-card').nth(1).locator('img').evaluate(n=>n.src.startsWith('data:image/')),true,'Preview survives page remount');
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);
  // Captions from another version: a published track is switched on by itself;
  // burned-in subtitles switch the video to that version and say so.
  const closeEpisodes=page.getByRole('button',{name:'Закрыть серии',exact:true});if(await closeEpisodes.isVisible().catch(()=>false))await closeEpisodes.click();
  await openPlayerSettings();await row('Субтитры').click();
  await choices('Источник субтитров').getByRole('radio',{name:/^Студия субтитров/}).click();
  await page.locator('.mvx-captions').getByText('Субтитры студии').waitFor({timeout:20000});
  assert.match(await rowValue('Субтитры'),/Студия субтитров/);
  await choices('Источник субтитров').getByRole('radio',{name:/^Crunchyroll\.Subtitles/}).click();
  await sheet().getByText('Субтитры «Crunchyroll.Subtitles» вшиты в видео этой версии: включили её.').waitFor({timeout:20000});
  for(let i=0;i<40&&!requests.some(b=>/source\.example\/c\/\d+$/.test(b.url)&&!String(b.clientId||'').includes(':captions'));i++)await page.waitForTimeout(250);
  assert.ok(requests.some(b=>/source\.example\/c\/\d+$/.test(b.url)&&!String(b.clientId||'').includes(':captions')),'the Crunchyroll version becomes the video');
  await page.keyboard.press('Escape');await page.keyboard.press('Escape');await sheet().waitFor({state:'detached'});
  await context.close();console.log('PASS embedded title, legible voice choices, adaptive HLS, independent synchronized audio/captions, AniSkip, durable resume/preview at '+width+'px');
 }
})().catch(async e=>{console.error(e);if(lastPage){await lastPage.screenshot({path:path.join(DIR,'failure.png'),fullPage:true});console.error((await lastPage.locator('body').innerText()).slice(0,2500));}process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const file of [harness,harness.replace('.html','.jsx')])await fs.rm(file,{force:true});});
