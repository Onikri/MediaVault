// Catalogue hook/UI contracts with neutral metadata. No external sources or ML.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'.codex-local/test-output/catalog');let vite,browser;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});
 await fs.writeFile(path.join(DIR,'index.html'),'<div id="root"></div><script type="module" src="./harness.jsx"></script>');
 await fs.writeFile(path.join(DIR,'harness.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import useMangaCatalog from'/src/use-manga-catalog.js';
 window.calls=[];let checked=false,active=0;window.peak=0;
 const service={server:'https://fixture.example',session:{serverVersion:72},request:async(p,o={})=>{
  window.calls.push({p,body:o.body});const url=new URL(p,location.origin);
  if(p==='/manga/catalog/enrich'){active++;window.peak=Math.max(active,window.peak);await new Promise(r=>setTimeout(r,30));active--;checked=true;return{items:[{status:'indexed'}]};}
  if(url.pathname.endsWith('/tags'))return{tags:[{original:'Drama',type:'genres',works:2}]};
  const q=url.searchParams.get('q');if(q==='Old')await new Promise(r=>setTimeout(r,600));
  const filtered=!!url.searchParams.get('tag'),offset=Number(url.searchParams.get('offset'));
  const rows=Array.from({length:Math.min(30,35-offset)},(_,i)=>({catalogId:String(offset+i).padStart(32,'0'),title:q+' '+(offset+i),metadataChecked:checked}));
  return{items:filtered&&!checked?[]:rows,total:filtered&&!checked?0:35,offset};
 }};
 function Demo(){const[query,setQuery]=React.useState('Garden'),[page,setPage]=React.useState(1),[tag,setTag]=React.useState(''),[version,setVersion]=React.useState(72);
 const data=useMangaCatalog({query,kind:'manga',filters:{tag,genre:'',year:'',format:'',age:''},language:'en',sourceIds:['990000000000000003'],service:{...service,session:{serverVersion:version}},page});
 return <><input aria-label="Query" value={query} onChange={e=>setQuery(e.target.value)}/><button onClick={()=>setPage(v=>v+1)}>Next</button><button onClick={()=>setTag('Time Travel')}>Filter</button><button onClick={()=>setVersion(71)}>Old server</button><pre id="state">{JSON.stringify(data)}</pre></>;}
 createRoot(document.getElementById('root')).render(<Demo/>);`);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0,hmr:false}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/catalog/index.html');
 const state=()=>JSON.parse(document.querySelector('#state').textContent);
 await page.waitForFunction(()=>JSON.parse(document.querySelector('#state').textContent).ready);
 assert.equal((await page.evaluate(state)).results.length,30);
 await page.getByText('Next',{exact:true}).click();
 await page.waitForFunction(()=>JSON.parse(document.querySelector('#state').textContent).results.length===5);
 assert.equal((await page.evaluate(state)).hasMore,false);
 await page.getByText('Filter',{exact:true}).click();
 await page.waitForFunction(()=>window.calls.some(c=>c.p==='/manga/catalog/enrich'));
 await page.waitForFunction(()=>{const s=JSON.parse(document.querySelector('#state').textContent);return s.ready&&!s.enriching&&s.results.length===5;});
 assert.equal(await page.evaluate(()=>window.peak),2);
 const calls=await page.evaluate(()=>window.calls);
 assert.ok(calls.filter(c=>c.p==='/manga/catalog/enrich').every(c=>c.body.ids.length===1));
 assert.ok(calls.some(c=>c.p.includes('tag=Time+Travel')&&c.p.includes('sourceIds=990000000000000003')&&c.p.includes('language=en')));
 await page.getByLabel('Query').fill('Old');await page.waitForFunction(()=>window.calls.some(c=>c.p.includes('q=Old')));
 await page.getByLabel('Query').fill('New');
 await page.waitForFunction(()=>JSON.parse(document.querySelector('#state').textContent).results[0]?.title.startsWith('New'));
 // The earlier request intentionally ignores AbortSignal, exercising stale-response protection.
 await page.waitForTimeout(700);assert.ok((await page.evaluate(state)).results.every(r=>r.title.startsWith('New')));
 await page.getByText('Old server',{exact:true}).click();
 await page.waitForFunction(()=>!JSON.parse(document.querySelector('#state').textContent).capable);
 const count=await page.evaluate(()=>window.calls.length);await page.getByLabel('Query').fill('Unsupported');await page.waitForTimeout(400);
 assert.equal(await page.evaluate(()=>window.calls.length),count);assert.deepEqual(errors,[]);
 console.log('PASS persistent catalogue pagination, combined filters, bounded metadata enrichment, stale requests and server compatibility');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
