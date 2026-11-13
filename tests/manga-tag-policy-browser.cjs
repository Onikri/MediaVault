// Real React UI with neutral metadata and a simulated runtime policy update.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'.codex-local/test-output/tag-policy');let vite,browser;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});await fs.writeFile(path.join(DIR,'index.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="./harness.jsx"></script>');
 await fs.writeFile(path.join(DIR,'harness.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import CatalogBrowser from'/src/CatalogBrowser.jsx';import policy from'/server/manga-tag-policy.json';import'/src/styles.css';
 window.rules=policy;window.generation=0;
 const row={id:'fixture:1',catalogId:'a'.repeat(32),provider:'fixture',sourceId:'1',kind:'manga',title:'Garden World',url:'https://fixture.example/title/garden',sourceUrl:'https://fixture.example/title/garden',aliases:['Garden World'],genres:['Drama'],tags:['Fantasy'],language:'en',metadataChecked:true};
 const service={server:location.origin,status:'connected',session:{serverVersion:73},request:async(p,o={})=>{
  if(p.startsWith('/manga/tag-policy'))return{revision:String(window.generation),policy:window.rules};
  if(p.startsWith('/manga/catalog/tags'))return{tags:[{key:'драма',original:'Drama',type:'genres',works:1},{key:'фэнтези',original:'Fantasy',type:'tags',works:1}]};
  if(p.startsWith('/manga/catalog?'))return{items:[row],total:1,offset:0};
  if(p.startsWith('/discovery/manga/sources'))return{sources:[{id:'1',name:'Fixture',language:'en'}]};
  if(p==='/discovery/manga/search')return{id:'fixture',state:'done',results:[row]};
  if(p.startsWith('/discovery/manga/search/'))return{state:'done',results:[row]};
  if(p==='/manga/search')return{results:[row],providers:[]};
  if(p==='/manga/inspect')return{...row,episodes:[],seasons:[],translations:[]};
  return{};
 }};
 createRoot(document.getElementById('root')).render(<CatalogBrowser service={service} state={{admin:true,user:{sub:'fixture'}}} initialKind="manga" initialQuery="Garden"/>);`);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0,hmr:false}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1280,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://**',r=>r.fulfill({json:{data:[],results:[]}}));
 await page.route(url=>url.pathname==='/manga/tag-policy',async r=>r.fulfill({json:await page.evaluate(()=>({revision:String(window.generation),policy:window.rules}))}));
 await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/tag-policy/index.html');
 await page.getByRole('button',{name:'Выбрать Garden World',exact:true}).waitFor();
 assert.equal(await page.getByLabel('Жанр',{exact:true}).locator('option').filter({hasText:/^Драма$/}).count(),1);
 await page.getByRole('button',{name:'Выбрать Garden World',exact:true}).click();
 await page.getByRole('heading',{name:'Garden World',exact:true}).waitFor();
 await page.locator('.title-genre-list').getByText('Драма',{exact:true}).waitFor();
 await page.evaluate(()=>{window.rules={...window.rules,tags:window.rules.tags.filter(t=>!['драма','фэнтези'].includes(t.key))};window.generation++;window.dispatchEvent(new Event('focus'));});
 await page.locator('.title-genre-list').getByText('Драма',{exact:true}).waitFor({state:'detached'});
 await page.getByRole('button',{name:'К результатам поиска',exact:true}).click();
 await page.getByRole('button',{name:'Выбрать Garden World',exact:true}).waitFor();
 assert.equal(await page.getByLabel('Жанр',{exact:true}).locator('option').filter({hasText:/^Драма$/}).count(),0);
 assert.equal(await page.locator('#catalogTags option[value="Фэнтези"]').count(),0);
 assert.deepEqual(errors,[]);
 console.log('PASS runtime deletion reaches open title, catalogue cards and filter options despite stale metadata responses');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
