const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
let browser,vite,last;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'test-output');await fs.mkdir(dir,{recursive:true});
 execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=8','-t','30','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart','-y',path.join(dir,'player-session.mp4')]);
 await fs.writeFile(path.join(dir,'player-session.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="/test-output/player-session.jsx"></script>');
 await fs.writeFile(path.join(dir,'player-session.jsx'),`
 import React,{useState}from'react';import{createRoot}from'react-dom/client';import Player from'/src/MediaVaultPlayer.jsx';import{useMediaVaultPlayer}from'/src/player-session.js';import'/src/styles.css';
 window.counts={setup:0,stop:0,abort:0,play:0};window.MEDIA_VAULT_CONFIG={};
 const item={id:'core',name:'Проверка React-плеера',category:'video'};
 const extension={id:'fixture',slot:'overlay',setup({on,signal}){window.counts.setup++;on('play',()=>window.counts.play++);signal.addEventListener('abort',()=>window.counts.abort++);return()=>window.counts.stop++;},Component:()=>{const api=useMediaVaultPlayer();return <button id="extension-seek" onClick={()=>api.seek(9)}>Модуль перемотки</button>;}};
 function Demo(){const[revision,setRevision]=useState(0),[enabled,setEnabled]=useState(true),[mounted,setMounted]=useState(true);return <><header id="outside" style={{height:220}}>Страница тайтла</header><main style={{maxWidth:900,margin:'0 auto'}}>{mounted&&<Player item={{...item,revision}} source="/test-output/player-session.mp4" catalog={{items:[item]}} userId="test" libraryId="core" extensions={enabled?[extension]:[]} apiRef={api=>window.player=api}/>}<button id="rerender" onClick={()=>setRevision(n=>n+1)}>Сведения</button><button id="module" onClick={()=>setEnabled(v=>!v)}>Модуль</button><button id="unmount" onClick={()=>setMounted(false)}>Закрыть</button><div style={{height:1400}}/></main></>;}createRoot(document.getElementById('root')).render(<Demo/>);
 document.addEventListener('contextmenu',e=>window.contextTarget=e.target.tagName);
 `);
 const {createServer}=await import('vite');vite=await createServer({root,logLevel:'error',cacheDir:'.codex-local/player-session-vite',server:{host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--enable-unsafe-swiftshader']});
 for(const width of [390,1440]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];last=page;page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/player-session.html');
  const video=page.locator('.mv-player-media');await page.waitForFunction(()=>window.player?.media?.readyState>=2);
  await page.evaluate(()=>{window.originalVideo=window.player.media;window.originalRoot=window.player.root;});
  await video.click({position:{x:50,y:50}});await page.waitForFunction(()=>window.player.getSnapshot().playing);
  await page.waitForFunction(()=>window.player.media.currentTime>.2);
  await page.locator('#rerender').click();assert.equal(await page.evaluate(()=>window.originalVideo===window.player.media&&window.originalRoot===window.player.root),true);
  assert.equal(await page.evaluate(()=>window.counts.setup),1,'Re-rendering does not restart modules');
  await page.evaluate(()=>window.player.pause());await video.click({button:'right',position:{x:50,y:50}});assert.equal(await page.evaluate(()=>window.contextTarget),'VIDEO','The actual video receives the context menu');await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Настройки плеера',exact:true}).click();const menu=page.getByRole('dialog',{name:'Настройки просмотра'});await menu.waitFor();await page.waitForTimeout(350);
  const offset=()=>menu.evaluate(n=>{const p=n.closest('.mv-player').getBoundingClientRect(),r=n.getBoundingClientRect();return {x:r.x-p.x,y:r.y-p.y,width:r.width,height:r.height,inside:r.x>=p.x&&r.right<=p.right+1&&r.y>=p.y&&r.bottom<=p.bottom+1};});
  const before=await offset();await page.evaluate(()=>scrollBy(0,80));await page.waitForTimeout(100);const after=await offset();assert.ok(before.inside&&after.inside);assert.ok(Math.abs(before.y-after.y)<1,'Menu scrolls with its player, not with the viewport');
  await page.keyboard.press('Escape');await menu.waitFor({state:'hidden'});
  await page.evaluate(()=>window.player.theater(true));await page.waitForFunction(()=>document.querySelector('.player-theater-dimmed'));
  assert.equal(await video.evaluate(n=>{for(let p=n;p;p=p.parentElement)if(+getComputedStyle(p).opacity<.99)return false;return true;}),true,'Theater never dims an ancestor of its video');
  await page.waitForFunction(()=>+getComputedStyle(document.querySelector('#outside')).opacity<=.161);
  await page.locator('.mv-player').focus();await page.keyboard.press('Escape');await page.waitForFunction(()=>!document.querySelector('.player-theater-dimmed'));
  await page.locator('#extension-seek').click();assert.ok(Math.abs(await video.evaluate(v=>v.currentTime)-9)<.1);
  await page.evaluate(()=>window.player.preferences({speed:1.5,volume:.4}));await page.waitForFunction(()=>window.player.media.playbackRate===1.5&&window.player.media.volume===.4);
  await page.evaluate(()=>window.player.play());await page.waitForFunction(()=>window.player.media.currentTime>9.1);
  await page.locator('#module').click();assert.deepEqual(await page.evaluate(()=>[window.counts.stop,window.counts.abort]),[1,1]);assert.equal(await page.locator('#extension-seek').count(),0);
  const events=await page.evaluate(()=>window.counts.play);await page.evaluate(async()=>{window.player.pause();await window.player.play();});assert.equal(await page.evaluate(()=>window.counts.play),events,'Removed modules have no media listeners');
  assert.equal(await page.evaluate(()=>window.originalVideo===window.player.media),true);
  await page.evaluate(()=>window.player.pause());await page.locator('.mv-player').focus();await page.keyboard.press('k');await page.waitForFunction(()=>window.player.getSnapshot().playing);
  await page.evaluate(()=>window.player.theater(true));await page.locator('#unmount').evaluate(n=>n.click());await page.waitForFunction(()=>!document.querySelector('.mv-player'));assert.equal(await page.locator('.player-theater-dimmed').count(),0);
  assert.deepEqual(errors,[]);console.log('PASS React player identity, native hit target, local menus, theater, commands and extension lifecycle '+width);await page.close();
 }
})().catch(async error=>{console.error(error);if(last)await last.screenshot({path:'test-output/player-session-failure.png'}).catch(()=>{});process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const f of ['player-session.html','player-session.jsx'])await fs.rm('test-output/'+f,{force:true});});
