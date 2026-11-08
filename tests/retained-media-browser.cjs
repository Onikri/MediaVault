// Real media element and MP4 buffer across actual React page unmounts.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
const ROOT=process.cwd(),DIR=path.join(ROOT,'.codex-local/test-output/retained-media');let browser,vite;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','color=c=0x25252c:size=320x180:rate=8','-t','25','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart','-threads','1','-y',path.join(DIR,'video.mp4')]);
 await fs.writeFile(path.join(DIR,'index.html'),'<meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/.codex-local/test-output/retained-media/app.jsx"></script>');
 await fs.writeFile(path.join(DIR,'app.jsx'),`
 import React,{useState}from'react';import{createRoot}from'react-dom/client';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';import{RetainedMediaProvider,RetainedMediaSlot,VideoDock,useRetainedMedia}from'/src/RetainedMedia.jsx';import Player from'/src/MediaVaultPlayer.jsx';import'/src/styles.css';import'/src/interface-refinement.css';
 window.MEDIA_VAULT_CONFIG={};const item={id:'fixture',category:'video',name:'Сохранённое видео'};
 function Owner(){const[active,setActive]=useState(true);useRetainedMedia(active,{label:'Сохранённое видео',kind:'video'},()=>setActive(false));return active?<Player item={item} source="/.codex-local/test-output/retained-media/video.mp4" catalog={{items:[item]}} libraryId="fixture" userId="fixture" apiRef={v=>window.player=v}/>:<button onClick={()=>setActive(true)}>Начать снова</button>;}
 function Demo(){const[page,setPage]=useState('watch');return <><header className="site-header" style={{display:'flex',alignItems:'center',justifyContent:'space-between',height:60,padding:12}}><button id="away" onClick={()=>setPage('browse')}>Другая страница</button><VideoDock/></header><main className="app-main" style={{width:'100%',maxWidth:900,margin:'40px auto'}}>{page==='watch'?<RetainedMediaSlot id="fixture" label="Сохранённое видео" restore={()=>setPage('watch')}><Owner/></RetainedMediaSlot>:<h1>Библиотека</h1>}<div style={{height:800}}/></main></>;}
 createRoot(document.getElementById('root')).render(<ThemeProvider><RetainedMediaProvider><Demo/></RetainedMediaProvider></ThemeProvider>);
 `);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 for(const width of[390,1440]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/retained-media/index.html');await page.waitForFunction(()=>window.player?.media?.readyState>=2);
  await page.evaluate(()=>{window.original=player.media;window.metadataCount=0;original.addEventListener('loadedmetadata',()=>metadataCount++);original.currentTime=5;original.play();});await page.waitForFunction(()=>player.media.currentTime>5.1);
  const before=await page.evaluate(()=>({time:original.currentTime,end:original.buffered.end(original.buffered.length-1)}));await page.click('#away');await page.getByRole('heading',{name:'Библиотека',exact:true}).waitFor();await page.locator('[data-mode=hidden]').waitFor({state:'attached'});
  assert.equal(await page.evaluate(()=>player.media===original&&original.paused),true,'Leaving the page pauses the same retained element');
  await page.getByRole('button',{name:'Плеер в фоне',exact:true}).click();await page.getByRole('button',{name:'Картинка в картинке',exact:true}).click();await page.locator('[data-mode=popup]').waitFor();assert.equal(await page.evaluate(()=>player.media===original),true);
  await page.evaluate(()=>player.media.play());await page.waitForFunction(v=>player.media.currentTime>v+.1,before.time);
  await page.getByRole('button',{name:'Вернуться к просмотру на странице',exact:true}).click();await page.locator('[data-mode=attached]').waitFor();await page.waitForTimeout(600);
  assert.equal(await page.evaluate(()=>player.media===original),true);assert.equal(await page.evaluate(()=>metadataCount),0,'Navigation and mini view do not reload media metadata');assert.ok(await page.evaluate(v=>original.buffered.end(original.buffered.length-1)>=v-.1,before.end),'Existing native buffered range stays intact');
  const bounds=await page.locator('.mv-player').boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=width+1);await page.screenshot({path:path.join(DIR,'retained-'+width+'.png'),fullPage:true});
  await page.getByRole('button',{name:'Плеер в фоне',exact:true}).click();await page.getByRole('button',{name:'Закрыть просмотр',exact:true}).click();await page.getByRole('button',{name:'Начать снова',exact:true}).waitFor();assert.equal(await page.locator('video.mv-player-media').count(),0);assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS same video DOM node, buffered range, time and metadata across page unmount, mini view, return and explicit close at 390/1440px');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
