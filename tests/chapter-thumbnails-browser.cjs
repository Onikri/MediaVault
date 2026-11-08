// Real React, viewport observation, JPEG decoding and IndexedDB; Oracle is a fixture.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
let browser,vite,last;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/chapter-thumbnails'),base='/.codex-local/test-output/chapter-thumbnails/';await fs.mkdir(dir,{recursive:true});
 await fs.writeFile(path.join(dir,'index.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="'+base+'fixture.jsx"></script>');
 await fs.writeFile(path.join(dir,'fixture.jsx'),`
 import React,{useState}from'react';import{createRoot}from'react-dom/client';import ChapterChooser from'/src/ChapterChooser.jsx';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';import'/src/styles.css';import'/src/title-page.css';import'/src/world-library.css';
 window.calls=[];window.inflight=0;window.maxInflight=0;
 const canvas=document.createElement('canvas');canvas.width=320;canvas.height=180;const ctx=canvas.getContext('2d');ctx.fillStyle='#557080';ctx.fillRect(0,0,320,180);const image=canvas.toDataURL('image/jpeg');
 const entries=Array.from({length:12},(_,i)=>({number:166+i,title:'Глава '+(166+i),url:'https://mangapill.com/chapters/'+(166+i)}));
 const service={status:'connected',server:location.origin,session:{serverVersion:43},request:async(p,{body={},signal}={})=>{
  if(p!=='/manga/thumbnail')return{id:'hover',pages:[]};window.calls.push(body.url);window.inflight++;window.maxInflight=Math.max(window.maxInflight,window.inflight);
  try{await new Promise((resolve,reject)=>{const id=setTimeout(resolve,40);signal?.addEventListener('abort',()=>{clearTimeout(id);reject(new DOMException('Aborted','AbortError'));},{once:true});});if(body.url.endsWith('/168'))throw Error('Fixture unavailable');return{image};}finally{window.inflight--;}
 }};
 function Demo(){const[chosen,setChosen]=useState(null);return <ThemeProvider><main className="app-main" style={{paddingTop:1200}}><output id="chosen">{chosen?.number}</output><ChapterChooser active={!chosen} userId="fixture" entries={entries} service={service} cards onChoose={setChosen}/></main></ThemeProvider>};createRoot(document.getElementById('root')).render(<Demo/>);
 `);
 const {createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/vite-chapter-thumbs',logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0,strictPort:false}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 for(const width of [390,1440]){
  const page=await browser.newPage({viewport:{width,height:1000}}),errors=[];last=page;page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000);
  const url='http://127.0.0.1:'+vite.httpServer.address().port+base+'index.html';await page.goto(url);await page.waitForTimeout(200);assert.equal(await page.evaluate(()=>window.calls.length),0,'Offscreen chapters do not trigger background requests');
  await page.locator('.world-chapters').scrollIntoViewIfNeeded();await page.waitForFunction(()=>document.querySelectorAll('.online-chapter-art img').length>=3);await page.locator('.online-chapter-entry').last().scrollIntoViewIfNeeded();await page.waitForFunction(()=>document.querySelectorAll('.online-chapter-art img').length===11);
  assert.ok(await page.evaluate(()=>window.maxInflight<=2),'Thumbnail queue is bounded to two lanes');
  assert.ok(await page.locator('.online-chapter-art img').first().evaluate(n=>n.complete&&n.naturalWidth===320));
  assert.equal(await page.locator('.title-episode-card').count(),12,'Failed thumbnail does not remove its chapter');
  await page.screenshot({path:path.join(dir,'chapters-'+width+'.png'),fullPage:false});
  await page.reload();await page.locator('.world-chapters').scrollIntoViewIfNeeded();await page.waitForFunction(()=>document.querySelectorAll('.online-chapter-art img').length>=3);await page.locator('.online-chapter-entry').last().scrollIntoViewIfNeeded();await page.waitForFunction(()=>document.querySelectorAll('.online-chapter-art img').length===11);
  assert.ok(await page.evaluate(()=>window.calls.length<=1),'Successful thumbnails are restored from IndexedDB without Oracle requests');
  await page.locator('.title-episode-card').first().click();await page.locator('#chosen').getByText('166',{exact:true}).waitFor();
  assert.deepEqual(errors,[]);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.close();console.log('PASS visible unread chapters 166–177, bounded fetching, error isolation and durable thumbnails '+width);
 }
})().catch(async e=>{console.error(e);await last?.screenshot({path:'.codex-local/test-output/chapter-thumbnails/failure.png'}).catch(()=>{});process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
