// Contract regression: provider replies are fixtures, not real source availability.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'test-output');let browser,vite;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});
 await fs.writeFile(path.join(DIR,'title-sources.html'),'<meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/test-output/title-sources.jsx"></script>');
 await fs.writeFile(path.join(DIR,'title-sources.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import MangaImport from'/src/MangaImport.jsx';import'/src/styles.css';import'/src/world-library.css';import'/src/title-page.css';
 window.started=[];window.summaryActive=0;window.summaryPeak=0;
 const title={id:'selected:1',title:'Exact manga',titles:{ru:'Точная манга',ja:'正確な漫画',ko:'정확한 만화'},kind:'manga'};
 const sources=Array.from({length:82},(_,i)=>({id:'source:'+i,sourceId:String(i+1),provider:'suwayomi:'+String(i+1),providerName:i===81?'Rare source':'Source '+String(i).padStart(2,'0'),url:'https://media.example/m/'+i,title:title.title,kind:'manga',language:i%2?'en':'ru'}));
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));let serial=0;
 function Demo(){const[status,setStatus]=React.useState('connected');const service={server:location.origin,status,session:{serverVersion:29},request:async(p,o={})=>{
 if(p==='/manga/search')return{results:[],providers:[]};
 if(p==='/discovery/manga/search'){window.started.push(o.body);return{id:String(++serial),state:'running',results:[],progress:{completed:0,total:770}};}
 if(p.startsWith('/discovery/manga/search/')){if(o.method==='DELETE')return{state:'cancelled'};window.polls=(window.polls||0)+1;if(window.polls===1)throw Error('Temporary network failure');return{id:'job',state:'done',results:[],progress:{completed:770,total:770,failed:3}};}
 if(p.startsWith('/discovery/manga/sources')){const q=new URLSearchParams(p.split('?')[1]).get('q')||'';return{sources:sources.map((s,i)=>({id:String(i+1),name:s.providerName,language:s.language})).filter(s=>s.name.toLowerCase().includes(q.toLowerCase()))};}
 if(p==='/manga/summary'){window.summaryActive++;window.summaryPeak=Math.max(window.summaryPeak,window.summaryActive);await sleep(5);window.summaryActive--;if(o.body.url.endsWith('/0'))throw Error('HTTP 500 source failed');return{chapterCount:25,volumeCount:3};}
 if(p==='/manga/inspect'){const n=Number(o.body.url.split('/').at(-1));await sleep(n===2?100:10);if(n===0||n===2)throw Error('HTTP 500 source failed');return{title:title.title,url:o.body.url,language:n%2?'en':'ru',episodes:[{url:o.body.url+'/chapter/1',number:1,season:1,title:'Chapter for '+n,language:n%2?'en':'ru'}],seasons:[{number:1,name:'Том 1'}],translations:[]};}
 return{};}};return <main style={{maxWidth:1000,margin:'auto',padding:16}}><button onClick={()=>setStatus(status==='connected'?'error':'connected')}>Toggle connection</button><MangaImport compact destination="online" item={{...title,sources}} state={{user:{sub:'fixture'}}} service={service}/></main>;}
 createRoot(document.getElementById('root')).render(<Demo/>);`);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 for(const width of[360,1440]){
  const p=await browser.newPage({viewport:{width,height:1000}}),errors=[];p.on('pageerror',e=>errors.push(e.message));await p.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/title-sources.html');
  await p.getByRole('button',{name:'Читать сейчас',exact:true}).waitFor();assert.equal(await p.locator('.title-source-option').count(),82);
  await p.getByText(/Поиск завершён: 770/).waitFor();assert.equal(await p.locator('.title-source-option').count(),82,'Empty final poll preserves attached and previously found sources');
  await p.getByRole('button',{name:'Toggle connection',exact:true}).click();assert.equal(await p.locator('.title-source-option').count(),82);assert.equal(await p.getByRole('button',{name:'Читать сейчас',exact:true}).count(),1,'Temporary service status does not discard inspected chapters');await p.getByRole('button',{name:'Toggle connection',exact:true}).click();
  await p.getByLabel('Поиск по источникам',{exact:true}).fill('Rare');await p.getByText('25 глав · 3 тома',{exact:true}).waitFor();assert.equal(await p.locator('.title-source-option').count(),1,'Sources beyond first 70 are searchable');await p.getByLabel('Поиск по источникам',{exact:true}).fill('');
  assert.ok(await p.evaluate(()=>window.summaryPeak<=2));assert.ok(await p.evaluate(()=>window.started.some(b=>b.title.titles.ja==='正確な漫画')),'Title aliases go to the server');
  await p.getByLabel('Язык источника манги',{exact:true}).selectOption('en');assert.equal(await p.locator('.title-source-option').count(),41);
  await p.getByLabel('Язык источника манги',{exact:true}).selectOption('all');
  await p.locator('.title-source-option').filter({hasText:'Source 02'}).click();await p.locator('.title-source-option').filter({hasText:'Source 03'}).click();await p.getByText('Chapter for 3',{exact:true}).waitFor();await p.waitForTimeout(150);assert.equal(await p.locator('.title-source-option').filter({hasText:'Source 03'}).getAttribute('aria-pressed'),'true');assert.equal(await p.locator('.inline-error').filter({hasText:'HTTP 500 source failed'}).count(),0,'Late error from previous selection cannot overwrite the new chapter list');
  await p.locator('.title-source-option').filter({hasText:'Source 00'}).click();await p.getByRole('alert').filter({hasText:'HTTP 500 source failed'}).waitFor();assert.equal(await p.locator('.title-source-option').count(),82,'Failed sources remain available for retry');
  assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);await p.screenshot({path:path.join(DIR,'title-sources-'+width+'.png'),fullPage:true});await p.close();console.log('PASS retained source results, transient recovery, alias search, languages, complete source list, counts, bounded metadata and stale request protection at '+width+'px');
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const n of['title-sources.html','title-sources.jsx'])await fs.rm(path.join(DIR,n),{force:true});});
