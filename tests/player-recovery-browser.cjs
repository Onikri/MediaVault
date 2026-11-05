// React health/queue contracts use controlled events; timeline decoding uses real MP4.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'.codex-local/test-output/player-recovery');let browser,vite;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=8','-t','12','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart','-threads','1','-y',path.join(DIR,'video.mp4')]);
 await fs.writeFile(path.join(DIR,'index.html'),'<meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/.codex-local/test-output/player-recovery/app.jsx"></script>');
 await fs.writeFile(path.join(DIR,'app.jsx'),`
 import React,{useRef,useState}from'react';import{createRoot}from'react-dom/client';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';import Player from'/src/MediaVaultPlayer.jsx';import Timeline from'/src/TimelinePreview.jsx';import Queue from'/src/ImportQueue.jsx';import useHealth from'/src/use-playback-health.js';import'/src/styles.css';
 window.MEDIA_VAULT_CONFIG={};window.errors=0;window.fake=new EventTarget();Object.assign(window.fake,{readyState:0,paused:false,seeking:false,currentTime:0});const item={id:'recovery',name:'Проверка воспроизведения',category:'video'},source='/.codex-local/test-output/player-recovery/video.mp4';
 function Health(){const h=useHealth(useRef(window.fake),'fixture',()=>window.errors++);return <div id="health">{h.phase}:{String(h.visible)}<button id="dismiss" onClick={h.dismiss}>Скрыть</button></div>;}
 const now=Date.now()/1000;const jobs=[{id:'run',status:'running',created:now,updated:now,progress:{taskType:'enrich',title:'Оформляемый тайтл',file:'Серия 2.mp4',operation:'Извлекаем кадр для превью',cursor:1,current:2,total:5}},{id:'old',status:'completed',created:now-30,updated:now-10,progress:{title:'Готовая манга',saved:3,total:3,phase:'done'}},{id:'merged',status:'merged',created:now-10,updated:now,progress:{title:'Дубликат',taskType:'enrich',phase:'merged',mergedInto:'run'}}];
 function App(){const[error,setError]=useState('Старая ошибка');return <main style={{maxWidth:900,margin:'20px auto'}}><Health/><div id="old-error">{error}</div><Player item={item} catalog={{items:[item]}} source={source} userId="test" libraryId="fixture" onPlaybackRecovered={()=>setError('')} apiRef={api=>window.player=api}/><div style={{position:'relative',height:130,marginTop:50}}><Timeline source={source} type="video" point={2} left={50}/></div><Queue service={{jobs}}/></main>;}createRoot(document.getElementById('root')).render(<ThemeProvider><App/></ThemeProvider>);
 `);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 for(const width of[390,1440]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.clock.install();
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/player-recovery/index.html');await page.waitForFunction(()=>window.player?.media);
  await page.clock.fastForward(27000);await page.waitForFunction(()=>document.querySelector('#health').textContent.startsWith('failed:true'));assert.equal(await page.evaluate(()=>window.errors),0,'Temporary stall does not trigger source fallback');
  await page.click('#dismiss');await page.waitForFunction(()=>document.querySelector('#health').textContent.startsWith('failed:false'));
  await page.evaluate(()=>{fake.readyState=2;fake.dispatchEvent(new Event('playing'));});await page.waitForFunction(()=>document.querySelector('#health').textContent.startsWith('playing:false'));
  await page.evaluate(()=>player.media.play());await page.waitForFunction(()=>player.media.currentTime>.05);assert.equal(await page.locator('#old-error').innerText(),'');
  await page.locator('.mv-timeline-frame img').waitFor();assert.equal(await page.locator('.mv-timeline-frame video').evaluate(v=>getComputedStyle(v).display),'none');
  const main=await page.locator('.mv-player').boundingBox(),picture=await page.locator('video.mv-player-media').boundingBox();assert.ok(picture.width<=main.width+1&&picture.height<=main.height+1,'Real video stays inside player');
  await page.getByText('Извлекаем кадр для превью',{exact:true}).waitFor();assert.equal(await page.locator('.queue-task').count(),2,'Merged duplicates are history, not active queue entries');
  await page.getByRole('button',{name:'Таблица',exact:true}).click();await page.getByRole('combobox',{name:'Состояние заданий',exact:true}).click();await page.getByRole('option',{name:'Активные',exact:true}).click();assert.equal(await page.locator('.queue-task').count(),1);
  await page.getByRole('combobox',{name:'Группировка заданий',exact:true}).click();await page.getByRole('option',{name:'По операции',exact:true}).click();await page.getByRole('heading',{name:/^Оформление/}).waitFor();
  await page.screenshot({path:path.join(DIR,'queue-player-'+width+'.png'),fullPage:true});assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS recoverable stall, parent notice recovery, actual preview decoding, contained video and queue filters at 390/1440px');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
