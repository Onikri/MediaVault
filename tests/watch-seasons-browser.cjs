// Real React/native media decoding; source inspections and leases are fixtures.
const {showEpisodes,chooseSeason}=require('./player-episodes.cjs');
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
let browser,vite,last;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/watch-seasons'),base='/.codex-local/test-output/watch-seasons/';await fs.mkdir(dir,{recursive:true});
 execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=8','-t','15','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart','-y',path.join(dir,'fixture.mp4')]);
 await fs.writeFile(path.join(dir,'index.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="'+base+'fixture.jsx"></script>');
 await fs.writeFile(path.join(dir,'fixture.jsx'),`
 import React,{useState}from'react';import{createRoot}from'react-dom/client';import OnlineWatch from'/src/OnlineWatch.jsx';import Player from'/src/MediaVaultPlayer.jsx';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';import'/src/styles.css';import'/src/title-page.css';
 window.MEDIA_VAULT_CONFIG={};window.requests=[];window.releasedLeases=[];
 const item={id:'season-fixture',title:'Сезонный тест',kind:'anime'},profile={cover:'',episodeImages:{}};
 const voice={id:'a',name:'Команда А',kind:'voice',language:'ru',variants:[{id:'a',player:'Kodik',url:'https://source.example/a',sourceUrl:'https://source.example/title'}]};
 const discovery={data:{voices:[voice]},loading:false};
 function delay(ms,signal){return new Promise((resolve,reject)=>{const id=setTimeout(resolve,ms);signal?.addEventListener('abort',()=>{clearTimeout(id);reject(new DOMException('Aborted','AbortError'));},{once:true});});}
 let count=0;const service={server:location.origin,request:async(p,{body={},signal}={})=>{
  if(p==='/sources/inspect'){await delay(body.season===1?10:350,signal);if(body.season===3)throw Error('Тест: список сезона временно недоступен');return{seasons:[1,2,3].map(number=>({number,name:'Сезон '+number})),episodes:[1,2,3].map(number=>({number,season:body.season,title:'Серия '+number,url:'https://source.example/s'+body.season+'/'+number}))};}
  if(p==='/online/prepare'){window.requests.push(body);await delay(450,signal);return{id:'lease-'+(++count),type:'mp4',url:'${base}fixture.mp4?lease='+count,qualities:[720]};}
  if(p.endsWith('/heartbeat'))return{};
  if(p.startsWith('/online/')){window.releasedLeases.push(p);return{};}
  return{};
 }};
 function Demo(){const[season,setSeason]=useState(null);return <ThemeProvider><main className="app-main" style={{width:'100%',maxWidth:1000,margin:'0 auto'}}><output id="browsed">{season?.name} · {season?.episodes}</output><OnlineWatch item={item} profile={profile} discovery={discovery} service={service} userId="test" onSeasonBrowse={setSeason}/></main></ThemeProvider>}
 const assets=[1,2].flatMap(season=>[1,2].map(episode=>({id:'s'+season+'e'+episode,name:'Серия '+episode,category:'video',section:'anime',collectionId:'local',season,episode})));
 function Local(){const[current,setCurrent]=useState(assets[0]);return <ThemeProvider><main className="app-main"><Player autoPlay item={current} source={'${base}fixture.mp4?item='+current.id} catalog={{items:assets,storage:{collections:[{id:'local',name:'Коллекция',section:'anime'}]}}} onSelectItem={item=>{window.localChoices=(window.localChoices||0)+1;setCurrent(item);}}/></main></ThemeProvider>}
 createRoot(document.getElementById('root')).render(location.search.includes('local')?<Local/>:<Demo/>);
 `);
 const {createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/vite-watch-seasons',logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 for(const width of [390,1440]){
  const page=await browser.newPage({viewport:{width,height:1000},reducedMotion:'reduce'}),errors=[];last=page;page.on('pageerror',e=>{errors.push(e.message);console.error(e.stack);});page.setDefaultTimeout(8000);
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+base+'index.html');
  await page.getByRole('button',{name:'Смотреть серию 1',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.mv-player-media')?.currentTime>.1);
  await showEpisodes(page);await page.evaluate(()=>{window.video=document.querySelector('.mv-player-media');window.shell=document.querySelector('[data-player]');window.selector=document.querySelector('[aria-label="Сезон просмотра"]');});
  const mainCount=()=>page.evaluate(()=>window.requests.filter(r=>r.clientId?.endsWith(':viewer')).length);
  const countBefore=await mainCount();
  await chooseSeason(page,'2');
  await chooseSeason(page,'3');
  await page.getByText('Тест: список сезона временно недоступен',{exact:false}).waitFor();
  assert.equal(await mainCount(),countBefore,'Browsing/failing a season must not prepare another media stream');
  assert.ok(await page.evaluate(()=>window.video===document.querySelector('.mv-player-media')&&!window.video.paused&&window.shell===document.querySelector('[data-player]')&&window.selector===document.querySelector('[aria-label="Сезон просмотра"]')),'Player and season chooser stay mounted');
  await chooseSeason(page,'2');await page.locator('#browsed').getByText('Сезон 2 · 3',{exact:true}).waitFor();
  assert.equal(await mainCount(),countBefore);
  const previous=await page.evaluate(()=>({time:window.video.currentTime,src:window.video.currentSrc,closed:window.releasedLeases.length}));
  await showEpisodes(page);await page.locator('.watch-episode-grid .title-episode-card').nth(1).click();
  await page.waitForTimeout(150);
  assert.ok(await page.evaluate(p=>window.video.currentSrc===p.src&&!window.video.paused&&window.video.currentTime>p.time&&window.releasedLeases.length===p.closed,previous),'Current stream survives preparation of the next episode');
  await page.waitForFunction(src=>window.video.currentSrc!==src&&window.video.readyState>=2,previous.src);
  assert.equal(await mainCount(),countBefore+1,'Explicit episode choice prepares exactly one stream');
  assert.ok(await page.evaluate(()=>window.requests.filter(r=>r.clientId?.endsWith(':viewer')).at(-1).url.endsWith('/s2/2')));
  assert.ok(await page.evaluate(()=>window.video===document.querySelector('.mv-player-media')&&window.shell===document.querySelector('[data-player]')),'Episode handoff preserves React player/native video identity');
  // The online episode panel stays open after a choice; close it and toggle it from the chip.
  await page.getByRole('button',{name:'Закрыть серии',exact:true}).click();await page.locator('.mvx-episodes').waitFor({state:'detached'});
  await page.getByRole('button',{name:'Выбрать серию',exact:true}).click();await page.locator('.mvx-episodes').waitFor();await page.getByRole('button',{name:'Закрыть серии',exact:true}).click();await page.locator('.mvx-episodes').waitFor({state:'detached'});
  const nextCount=await mainCount();await chooseSeason(page,'1');await page.locator('#browsed').getByText('Сезон 1 · 3',{exact:true}).waitFor();
  assert.equal(await mainCount(),nextCount);
  const saved=await page.evaluate(()=>JSON.parse(localStorage.getItem('mv_watch_v1:test:season-fixture')));assert.equal(saved.season,2);assert.equal(saved.episode,2,'Browsing does not overwrite actual resume position');
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);
  await page.screenshot({path:path.join(dir,'seasons-'+width+'.png')});
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+base+'index.html?local');
  await page.waitForFunction(()=>document.querySelector('.mv-player-media')?.readyState>=2);
  await page.evaluate(()=>{window.video=document.querySelector('.mv-player-media');window.source=window.video.currentSrc;});
  // Local seasons are browsed from the player's episode panel.
  await page.getByRole('button',{name:'Выбрать серию',exact:true}).click();
  await page.getByRole('tablist',{name:'Сезон плеера'}).getByRole('tab',{name:'Сезон 2',exact:true}).click();
  assert.ok(await page.evaluate(()=>window.video===document.querySelector('.mv-player-media')&&window.video.currentSrc===window.source&&!window.localChoices),'Local season browsing also preserves current media');
  await page.locator('.mvx-episodes .mvx-card').nth(1).click();
  await page.waitForFunction(()=>window.video.currentSrc.includes('s2e2'));
  assert.equal(await page.evaluate(()=>window.localChoices),1);assert.ok(await page.evaluate(()=>window.video===document.querySelector('.mv-player-media')));
  assert.deepEqual(errors,[]);await page.close();console.log('PASS season browsing, source errors, exact episode handoff, stable player and resume '+width);
 }
})().catch(async e=>{console.error(e);await last?.screenshot({path:'.codex-local/test-output/watch-seasons/failure.png'}).catch(()=>{});process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
