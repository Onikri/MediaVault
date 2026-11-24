// Real catalogue layout under delayed neutral responses, no account/source traffic.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/catalog-load');let browser,vite,page;
(async()=>{
 await fs.mkdir(dir,{recursive:true});await fs.writeFile(path.join(dir,'index.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="./fixture.jsx"></script>');
 await fs.writeFile(path.join(dir,'fixture.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import CatalogBrowser from'/src/CatalogBrowser.jsx';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';import policy from'/tests/fixtures/manga-tag-policy.json';import{setMangaPolicy}from'/src/manga-tag-policy.js';
 import'/src/styles.css';import'/src/blossom/integration.css';import'/src/site-layout.css';
 setMangaPolicy(policy,'fixture-grid');window.cardReads=[];
 const invalidPolicy={...policy,tags:[...policy.tags,{key:'legacy',label:'Legacy',aliases:['x'.repeat(121)]}]};
 const service={server:location.origin,status:'connected',session:{serverVersion:75},request:async(p,o={})=>{
 if(p.startsWith('/manga/tag-policy')){await new Promise(r=>setTimeout(r,5000));window.vocabularyReturned=true;return{policy:invalidPolicy,revision:'broken-vocabulary'};}
 if(p.startsWith('/manga/catalog/tags'))return{tags:[]};
 if(p.startsWith('/discovery/manga/sources'))return{sources:[]};
 if(p.startsWith('/manga/catalog?')){if(window.outage)throw Object.assign(Error('Fixture network outage'),{status:503});const params=new URL(p,location.origin).searchParams;if(!/^[0-9]+$/.test(params.get('offset')||'')||!/^[0-9]+$/.test(params.get('limit')||''))throw Object.assign(Error('Invalid integer query parameter'),{status:422});if(params.get('includeTagPolicy')!=='false')throw Error('Cards must request the page alone');const limit=Number(params.get('limit'));window.firstRequest??=performance.now();window.cardReads.push(limit);await new Promise(r=>setTimeout(r,200));return{items:Array.from({length:limit},(_,i)=>({id:'fixture:'+i,catalogId:String(i).padStart(32,'0'),provider:'fixture',kind:'manga',sourceId:'1',title:'Garden '+i,sourceUrl:'https://fixture.example/'+i,url:'https://fixture.example/'+i,genres:['Drama'],tags:[],metadataChecked:true})),works:limit,workTotal:1000,total:1000,offset:0,tagPolicy:{policy:invalidPolicy,revision:'old-server'}};}
 return{items:[],total:0};}};
 function Demo(){const[outage,setOutage]=React.useState(false);window.setOutage=value=>{window.outage=value;setOutage(value);};return <ThemeProvider><main style={{width:1700,maxWidth:'100%',margin:'auto'}}><CatalogBrowser initialKind="manga" service={{...service,status:outage?'error':'connected'}} state={{admin:true,user:{sub:'fixture'}}}/></main></ThemeProvider>;}createRoot(document.getElementById('root')).render(<Demo/>);`);
 const{createServer}=await import('vite');vite=await createServer({root,logLevel:'error',cacheDir:'.codex-local/cache/vite-catalog-load',server:{host:'127.0.0.1',port:0,watch:null}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});page=await browser.newPage({viewport:{width:1798,height:1000},reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://**/*',r=>r.fulfill({json:{data:[],results:[]}}));
 await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/catalog-load/index.html');
 await page.waitForFunction(()=>document.querySelectorAll('.catalog-card').length===28,null,{timeout:15000});
 const first=await page.evaluate(()=>({elapsed:performance.now()-window.firstRequest,vocabularyReturned:!!window.vocabularyReturned}));
 assert.ok(first.elapsed<3000,JSON.stringify(first));assert.equal(first.vocabularyReturned,false);
 await page.waitForTimeout(1200);const reads=await page.evaluate(()=>window.cardReads);assert.equal(reads.at(-1),28);assert.ok(reads.length<=3,'Grid loading must not oscillate page limits: '+JSON.stringify(reads));assert.equal(await page.locator('.catalog-card').count(),28);assert.deepEqual(errors,[]);
 await page.evaluate(()=>window.setOutage(true));await page.waitForTimeout(400);assert.equal(await page.locator('.catalog-card').count(),28,'A temporary server error retains the indexed page');await page.evaluate(()=>window.setOutage(false));await page.waitForTimeout(500);assert.equal(await page.locator('.catalog-card').count(),28);
 await page.screenshot({path:path.join(dir,'stable-wide-catalog.png')});console.log('PASS 1798px catalogue loads and settles on 28 cards without page-size/request oscillation');
})().catch(async e=>{console.error(e);await page?.screenshot({path:path.join(dir,'failure.png')}).catch(()=>{});process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
