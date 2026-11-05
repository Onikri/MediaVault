// Delayed provider fixtures exercise the real React source/reader controls.
// These timings are not real upstream latency measurements.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const ROOT=process.cwd(),DIR=path.join(ROOT,'.codex-local/test-output/manga-progressive');let browser,vite;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});await fs.writeFile(path.join(DIR,'index.html'),'<meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/.codex-local/test-output/manga-progressive/app.jsx"></script>');
 await fs.writeFile(path.join(DIR,'app.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import MangaImport from'/src/MangaImport.jsx';import'/src/styles.css';
 window.calls=[];const source={url:'https://manga.example/title',title:'Fixture Manga',providerName:'Fixture',language:'en'},title={id:'fixture',kind:'manga',title:'Fixture Manga',sources:[source]},service={server:location.origin,status:'connected',session:{serverVersion:49},request:async(p,o={})=>{
 window.calls.push(p);if(p==='/manga/inspect')return{title:title.title,url:source.url,language:'en',episodes:[1,2].map(n=>({url:source.url+'/chapter/'+n,number:n,season:1,title:'Chapter '+n,language:'en'})),seasons:[{number:1}],translations:[]};
 if(p==='/manga/summary'){await new Promise((resolve,reject)=>{window.release=resolve;o.signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true});});return{chapterCount:2,volumeCount:1,readable:window.verified};}
 if(p==='/manga/search')return{results:[],providers:[]};if(p==='/discovery/manga/search')return{id:'done',state:'done',results:[]};return{};
 }};createRoot(document.getElementById('root')).render(<MangaImport compact destination="online" item={title} state={{user:{sub:'fixture'}}} service={service}/>);
 `);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 for(const width of[390,1440])for(const verified of[true,false]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/manga-progressive/index.html');
  await page.getByText('Chapter 1',{exact:true}).waitFor();await page.getByText('Главы получены · проверяем загрузку страницы…',{exact:true}).waitFor();const read=page.getByRole('button',{name:'Читать сейчас',exact:true});assert.equal(await read.isEnabled(),false);assert.equal(await page.evaluate(()=>calls.filter(p=>p==='/manga/inspect').length),1,'Auto selection reuses the already loaded chapter metadata');
  await page.evaluate(v=>{window.verified=v;window.release();},verified);
  await page.waitForFunction(v=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent==='Читать сейчас');return b&&!b.disabled===v;},verified);
  if(!verified)await page.getByText('Источник не отдал страницу.',{exact:true}).first().waitFor();
  assert.equal(await page.getByText('Chapter 1',{exact:true}).count(),1);assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS chapters render before delayed image verification; reader remains gated, failure retains chapter navigation, one metadata call at 390/1440px');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
