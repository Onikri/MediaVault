// Real React effects and fetch cancellation; providers and grant refresh are fixtures.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'.codex-local/test-output/remaining-player');let browser,vite;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});
 await fs.writeFile(path.join(DIR,'index.html'),'<meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/.codex-local/test-output/remaining-player/app.jsx"></script>');
 await fs.writeFile(path.join(DIR,'app.jsx'),`
 import React,{useRef}from'react';import{createRoot}from'react-dom/client';import useLyrics from'/src/use-lyrics.js';import warmup from'/src/use-playback-warmup.js';import Drive from'/src/DriveServerStatus.jsx';import{knownMusicDuration}from'/src/music-duration.js';
 const track={id:'fixture',title:'the WORLD',artists:['NIGHTMARE']};
 const service={server:location.origin,status:'connected',session:{serverVersion:49},refresh:async()=>{},connect:async()=>{window.reconnects=(window.reconnects||0)+1;},request:async(p,o={})=>{let r=await fetch(p,{method:o.method||'GET',body:o.body?JSON.stringify(o.body):undefined,headers:{'Content-Type':'application/json'},signal:o.signal});if(!r.ok)throw Object.assign(Error('fixture failure'),{status:r.status});return r.json();}};
 function App(){const ref=useRef(null),warm=warmup({entry:{url:'https://media.example/episode'},sourceUrl:'https://media.example/title',quality:'best',service,enabled:true,anchor:ref});const lyrics=useLyrics(track,knownMusicDuration(track,0,{durationMs:227000}),true,service);return <><Drive enabled service={service}/><button ref={ref} onClick={warm}>Warm</button><output>{lyrics.phase} {lyrics.plainText}</output></>;}
 createRoot(document.getElementById('root')).render(<App/>);
 `);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 for(const width of[390,1440]){
  const page=await browser.newPage({viewport:{width,height:850}}),errors=[],warm=[],closed=[],lyrics=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/google/connection**',r=>r.fulfill({json:{configured:true,connected:false,needsConsent:true,state:'needs_consent',checkedAt:1}}));
  await page.route('**/online/prepare',r=>{warm.push(r.request().postDataJSON());return r.fulfill({json:{id:'preview-capability'}});});
  await page.route('**/online/preview-capability',r=>{assert.equal(r.request().method(),'DELETE');closed.push(1);return r.fulfill({json:{closed:true}});});
  await page.route('**/music/lyrics',r=>{lyrics.push(r.request().postDataJSON());return r.fulfill({json:{phase:'empty'}});});
  await page.route('https://raw.githubusercontent.com/amll-dev/**',r=>r.abort());
  await page.route('https://lrclib.net/**',r=>r.fulfill({json:{id:1,trackName:'the WORLD',artistName:'NIGHTMARE',duration:227,plainLyrics:'Fixture matched lyric'}}));
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/remaining-player/index.html');
  await page.getByText('Google отклонил фоновое разрешение',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Проверить разрешение',exact:true}).click();
  await page.getByRole('button',{name:'Обновить фоновый доступ Drive на ВМ',exact:true}).click();assert.equal(await page.evaluate(()=>window.reconnects),1);
  await page.getByRole('button',{name:'Warm',exact:true}).click();await page.waitForFunction(()=>document.querySelector('output')?.textContent.includes('Fixture matched lyric'));
  await page.waitForTimeout(1700);assert.equal(warm.length,1);assert.equal(warm[0].purpose,'preview');assert.equal(warm[0].quality,'best');assert.equal(closed.length,1);assert.equal(lyrics[0].duration,227);
  await page.getByRole('button',{name:'Warm',exact:true}).click();await page.waitForTimeout(100);assert.equal(warm.length,1);assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS React lyric fallback without audio duration, Drive reconnect status, deduplicated selected-video warmup at 390/1440px');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
