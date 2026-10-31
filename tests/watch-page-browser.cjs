// Real React + HLS.js + decoded video/audio. Public-source/Oracle replies are fixtures.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {execFileSync}=require('node:child_process');const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'.codex-local/test-output/watch'),harness=path.join(ROOT,'test-output/watch-page-harness.html');
let vite,browser,lastPage;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});
 for(const height of [360,720])execFileSync('ffmpeg',['-v','error','-f','lavfi','-i',`color=c=0x31545d:s=${height*16/9}x${height}:r=12`,'-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','40','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-g','48','-c:a','aac','-f','hls','-hls_time','4','-hls_playlist_type','vod','-hls_segment_filename',path.join(DIR,height+'-%02d.ts'),'-y',path.join(DIR,height+'.m3u8')]);
 const jsx=`import React,{useState} from 'react';import {createRoot} from 'react-dom/client';import TitlePage from '/src/TitlePage.jsx';import OnlineWatch from '/src/OnlineWatch.jsx';import '/src/styles.css';import '/src/title-page.css';import '/src/discovery-polish.css';import '/src/world-library.css';
 window.MEDIA_VAULT_CONFIG={importServerUrl:'https://fixture.example'};
 const item={id:'mal:57334',title:'Дандадан',kind:'anime',ids:{mal:'57334'},year:2024};
 const profile={title:'Дандадан',sourceId:'57334',cover:'https://fixture.example/poster.svg',year:2024,format:'ТВ-сериал',status:'Вышел',episodes:12,duration:24,score:8.46,description:'Момо верит в призраков, Окарун — в пришельцев. Один спор приводит их к встрече с обоими. История о дружбе, первой любви и странных приключениях.',genres:['Комедия','Экшен','Сверхъестественное'],characters:[{id:'momo',name:'Момо Аясэ',role:'Главная героиня',image:'https://fixture.example/poster.svg'},{id:'okarun',name:'Кэн Такакура',role:'Главный герой',image:'https://fixture.example/poster.svg'}]};
 const voices=['a','b'].map((id,i)=>({id,name:i?'Команда Б':'Команда А',language:'ru',kind:'voice',variants:[{id:'v'+id,name:i?'Команда Б':'Команда А',url:'https://source.example/'+id,sourceUrl:'https://source.example/title',player:'Kodik',episodes:[1,2,3,4,5,6,7,8,9,10,11,12].map(number=>({number,url:'https://source.example/'+id+'/'+number}))}]}));
 const service={server:'https://fixture.example',session:{serverVersion:35},request:async(p,o={})=>{const r=await fetch('https://fixture.example'+p,{method:o.method||'GET',body:o.body?JSON.stringify(o.body):undefined,signal:o.signal});if(!r.ok)throw Error('Fixture HTTP '+r.status);return r.json();}};
 const discovery={data:{voices,providers:[],complete:true},loading:false,retry:()=>{}};
 function Demo(){const [revision,setRevision]=useState(0);return <main className="app-main"><button id="remount" onClick={()=>setRevision(n=>n+1)}>Открыть страницу заново</button><TitlePage key={revision} title={{id:item.id,name:item.title,section:'anime',category:'video',items:[],parts:[],online:true}} state={{user:{sub:'viewer'},catalog:{items:[]}}} actions={{}} online onlineProfile={profile} onlineFacts={[["Язык","Русский"],["Формат","ТВ-сериал"]]} onBack={()=>{}} onRelated={()=>{}} server={service.server} materials={<OnlineWatch item={item} profile={profile} discovery={discovery} service={service} userId="viewer"/>}/></main>};createRoot(document.getElementById('root')).render(<Demo/>);`;
 await fs.writeFile(harness,'<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="scene-root"></div><div id="root"></div><script type="module" src="/test-output/watch-page-harness.jsx"></script></html>');
 await fs.writeFile(harness.replace('.html','.jsx'),jsx);
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,cacheDir:path.join(ROOT,'.codex-local/cache/vite-watch'),logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 for(const width of [390,1440]){
  const context=await browser.newContext({viewport:{width,height:1000},reducedMotion:'reduce'}),page=await context.newPage(),errors=[],requests=[],previewLeases=new Set(),previewHighLevels=[];let leases=0;
  lastPage=page;page.on('pageerror',e=>{errors.push(e.message);console.error('UI_ERROR',e.stack);});
  const cors={'access-control-allow-origin':'*','access-control-allow-headers':'*','access-control-allow-methods':'*'};
  await page.route('https://fixture.example/**',async route=>{
   const req=route.request(),url=new URL(req.url()),json=data=>route.fulfill({contentType:'application/json',headers:cors,body:JSON.stringify(data)});
   if(req.method()==='OPTIONS')return route.fulfill({status:204,headers:cors});
   if(url.pathname==='/poster.svg')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="560"><rect width="400" height="560" fill="#375963"/><circle cx="230" cy="160" r="90" fill="#d4b89f"/><path d="M30 560L180 240 340 560" fill="#748277"/></svg>'});
   if(url.pathname==='/sources/inspect'){
    const b=req.postDataJSON(),studio=b.dub_url.endsWith('/b')?'b':'a';return json({episodes:Array.from({length:12},(_,i)=>({number:i+1,season:1,url:'https://source.example/'+studio+'/'+(i+1)}))});
   }
   if(url.pathname==='/online/prepare'){const b=req.postDataJSON();requests.push(b);const id='lease'+(++leases);if(b.clientId?.startsWith('previews-'))previewLeases.add(id);return json({id,type:'hls',url:'/online/'+id+'/master.m3u8',qualities:[720,360],expiresIn:120,subtitles:[{id:'ru',name:'Русские',language:'ru',url:'/online/'+id+'/sub.vtt'}]});}
   if(url.pathname.endsWith('/heartbeat')||req.method()==='DELETE')return json({closed:true,expiresIn:120});
   if(url.pathname.endsWith('/master.m3u8'))return route.fulfill({contentType:'application/vnd.apple.mpegurl',headers:cors,body:'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=640x360,NAME="360p"\n360.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=1400000,RESOLUTION=1280x720,NAME="720p"\n720.m3u8\n'});
   if(url.pathname.endsWith('/sub.vtt'))return route.fulfill({contentType:'text/vtt',headers:cors,body:'WEBVTT\n\n00:00:01.000 --> 00:00:30.000\nНезависимые субтитры\n'});
   if(/\/(?:360|720)(?:\.m3u8|-\d+\.ts)$/.test(url.pathname)){const file=path.basename(url.pathname),body=await fs.readFile(path.join(DIR,file));if(previewLeases.has(url.pathname.split('/')[2])&&file.startsWith('720'))previewHighLevels.push(file);return route.fulfill({contentType:file.endsWith('.ts')?'video/mp2t':'application/vnd.apple.mpegurl',headers:cors,body});}
   if(url.pathname.startsWith('/music/timings/'))return json({intervals:[{type:'op',start:2,end:6,source:'AniSkip'}]});
   if(url.pathname.startsWith('/music/anime/'))return json({tracks:[]});
   return json({ratings:[],items:[]});
  });
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/watch-page-harness.html');
  await page.getByRole('button',{name:'Серия 2',exact:false}).first().waitFor();
  assert.equal(await page.locator('.watch-episode-grid .title-episode-card').count(),12);
  assert.equal(await page.locator('#voiceSource').count(),0);assert.equal(await page.locator('[aria-label="Качество просмотра"]').count(),0);
  const colors=await page.getByLabel('Озвучка для просмотра').evaluate(n=>({background:getComputedStyle(n).backgroundColor,color:getComputedStyle(n).color,scheme:getComputedStyle(n).colorScheme}));
  assert.equal(colors.scheme,'dark');assert.notEqual(colors.background,colors.color);
  await page.waitForFunction(()=>[...document.querySelectorAll('.watch-episode-grid img')].length===12&&[...document.querySelectorAll('.watch-episode-grid img')].every(n=>n.src.startsWith('data:image/')),{},{timeout:30000});
  assert.deepEqual(previewHighLevels,[],'Background previews must not fetch higher-quality video');
  await page.screenshot({path:path.join(DIR,'title-idle-'+width+'.png'),fullPage:true});
  await page.locator('.watch-episode-grid .title-episode-card').nth(1).click();
  const video=page.locator('.mv-player-stage>video').first();await page.waitForFunction(()=>document.querySelector('.mv-player-stage>video')?.readyState>=2);
  assert.equal(await page.evaluate(()=>document.fullscreenElement),null);assert.notEqual(await page.evaluate(()=>document.body.style.overflow),'hidden');
  await page.locator('.mv-player').focus();await page.keyboard.press('k');await page.waitForFunction(()=>!document.querySelector('.mv-player-stage>video').paused);
  await video.evaluate(v=>{v.currentTime=3;});await page.getByRole('button',{name:'Пропустить опенинг',exact:false}).waitFor();
  await page.getByRole('button',{name:'Пропустить опенинг',exact:false}).click();assert.ok(await video.evaluate(v=>v.currentTime)>=6);
  await page.getByRole('button',{name:'Настройки плеера',exact:true}).click();
  await page.getByLabel('Качество',{exact:true}).selectOption('0');await page.getByLabel('Качество',{exact:true}).selectOption('-1');
  const before=await video.evaluate(v=>({source:v.currentSrc,time:v.currentTime}));
  await page.getByLabel('Озвучка в плеере').selectOption('b');await page.waitForFunction(()=>document.querySelector('.mv-external-audio')?.readyState>=2);
  assert.equal(await video.evaluate(v=>v.currentSrc),before.source,'Audio switch must preserve video source');
  assert.ok(await video.evaluate(v=>v.currentTime)>=before.time);
  await video.evaluate(v=>{v.currentTime=12;});await page.waitForFunction(()=>{const v=document.querySelector('.mv-player-stage>video'),a=document.querySelector('.mv-external-audio');return Math.abs(v.currentTime-a.currentTime)<.6;});
  assert.ok(requests.some(b=>b.url==='https://source.example/b/2'),'Alternate audio belongs to the same episode');
  await page.getByRole('tab',{name:'Субтитры',exact:true}).click();await page.locator('#settings-page-captions .mv-player-settings').getByLabel('Субтитры',{exact:true}).selectOption('native:0');
  await page.getByRole('button',{name:'Закрыть настройки',exact:true}).click();await page.locator('.mv-player-captions').getByText('Независимые субтитры').waitFor();
  await video.evaluate(v=>{v.pause();v.currentTime=14;v.dispatchEvent(new Event('timeupdate'));});
  await page.screenshot({path:path.join(DIR,'title-playing-'+width+'.png'),fullPage:true});
  await page.getByRole('button',{name:'Закрыть встроенный просмотр'}).click();await page.getByRole('button',{name:'Открыть страницу заново'}).click();
  await page.getByRole('button',{name:'Смотреть · серия 2'}).waitFor();assert.equal(await page.getByLabel('Озвучка для просмотра').inputValue(),'a');
  await page.getByRole('button',{name:'Смотреть · серия 2'}).click();await page.waitForFunction(()=>{const v=document.querySelector('.mv-player-stage>video');return v?.readyState>=2&&v.currentTime>=13;});
  await page.waitForFunction(()=>!!document.querySelector('.mv-external-audio'));
  assert.equal(await page.locator('.watch-episode-grid .title-episode-card').nth(1).locator('img').evaluate(n=>n.src.startsWith('data:image/')),true,'Preview survives page remount');
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);
  await context.close();console.log('PASS embedded title, dark voice select, adaptive HLS, independent synchronized audio/captions, AniSkip, durable resume/preview at '+width+'px');
 }
})().catch(async e=>{console.error(e);if(lastPage){await lastPage.screenshot({path:path.join(DIR,'failure.png'),fullPage:true});console.error((await lastPage.locator('body').innerText()).slice(0,2500));}process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const file of [harness,harness.replace('.html','.jsx')])await fs.rm(file,{force:true});});
