// UI/provider contracts. No production account, sources, or ML inference.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'test-output');let vite,browser;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});await fs.writeFile(path.join(DIR,'world-harness.html'),'<meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/test-output/world-harness.jsx"></script>');
 await fs.writeFile(path.join(DIR,'world-harness.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import CatalogBrowser from'/src/CatalogBrowser.jsx';import'/src/styles.css';import'/src/title-page.css';import'/src/import-workspace.css';import'/src/import-layout.css';import'/src/discovery-polish.css';
 window.searchBodies=[];window.cancelled=[];let counter=0;
 const result={id:'suwayomi:1:42',provider:'suwayomi:1',providerName:'Source A',sourceId:'1',kind:'manga',title:'Новый тайтл только в источнике',aliases:['Новый тайтл только в источнике'],url:'https://media.example/__manga/suwayomi/m/42',language:'ru',format:'manga',sourceOnly:true};
 const service={server:location.origin,status:'connected',session:{serverVersion:16},jobs:[],request:async(p,o={})=>{
 if(p.startsWith('/discovery/manga/sources'))return{sources:[{id:'1',name:'Source A',language:'ru'},{id:'2',name:'Source B',language:'ja'}]};
 if(p==='/discovery/manga/search'){window.searchBodies.push(o.body);return{id:String(++counter),state:'running',progress:{completed:0,total:770},results:[]};}
 if(p.startsWith('/discovery/manga/search/')){if(o.method==='DELETE'){window.cancelled.push(p);return{state:'cancelled'};}return{id:p.split('/').at(-1),state:'done',progress:{completed:770,total:770,failed:2,cached:700},results:[result]};}
 if(p==='/manga/search')return{results:[],providers:[]};
 if(p==='/manga/inspect')return{provider:'suwayomi:1',providerName:'Source A',title:result.title,url:result.url,language:'ru',episodes:[1,2].map(n=>({url:result.url+'/c/'+n,number:n,season:1,title:'Глава '+n,language:'ru'})),seasons:[{number:1,name:'Том 1'}],translations:[]};
 if(p==='/online/prepare')return{id:'preview',pages:['/online/preview/p.png'],kind:'manga'};
 if(p.startsWith('/online/preview'))return{closed:true};
 if(p.endsWith('/status'))return{ready:true,availableExtensions:1435,sources:[]};
 return{state:'idle',extensions:[]};}};
 createRoot(document.getElementById('root')).render(<main style={{maxWidth:1350,margin:'auto',padding:18}}><CatalogBrowser service={service} state={{admin:true,user:{sub:'fixture'},catalog:null}} initialKind="manga" destination="online" onSubmitted={()=>{}}/></main>);`);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:0,hmr:false}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 for(const width of[360,1440]){
  const page=await browser.newPage({viewport:{width,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/metadata/**',r=>r.fulfill({json:{data:[],results:[]}}));await page.route('https://**',r=>r.fulfill({json:{data:[],results:[]}}));
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/world-harness.html');
  await page.getByLabel('Глобальный поиск по каталогам').fill('Новый');
  await page.getByRole('button',{name:'Выбрать Новый тайтл только в источнике',exact:true}).waitFor();
  assert.ok((await page.evaluate(()=>window.searchBodies)).every(b=>!Object.hasOwn(b,'sourceIds')),'All-source request omits optional subset');
  await page.getByLabel('Источники Все подключённые').fill('Source');
  await page.getByRole('checkbox',{name:'Source A RU'}).check();await page.getByRole('checkbox',{name:'Source B JA'}).check();await page.getByRole('button',{name:'Готово',exact:true}).click();
  await page.waitForFunction(()=>window.searchBodies.some(b=>b.sourceIds?.length===2));
  await page.getByRole('button',{name:'Выбрать Новый тайтл только в источнике',exact:true}).waitFor();
  await page.getByRole('button',{name:'Убрать источник Source B',exact:true}).click();
  await page.getByRole('button',{name:'Выбрать Новый тайтл только в источнике',exact:true}).click();
  await page.getByRole('heading',{name:'Новый тайтл только в источнике',exact:true}).waitFor();
  await page.getByRole('button',{name:'Читать сейчас',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Онлайн',exact:true}).getAttribute('aria-pressed'),'true');
  assert.equal(await page.getByRole('button',{name:'Проверить следующие источники',exact:true}).count(),0);
  await page.getByRole('button',{name:'На устройство',exact:true}).click();await page.getByRole('button',{name:'Сохранить на устройство',exact:true}).waitFor();
  await page.getByRole('button',{name:'В Google Диск',exact:true}).click();await page.getByRole('button',{name:'Добавить 2 главы в коллекцию',exact:true}).waitFor();
  await page.getByRole('button',{name:'Онлайн',exact:true}).click();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'No horizontal overflow');assert.deepEqual(errors,[]);
  await page.screenshot({path:path.join(DIR,'world-library-'+width+'.png'),fullPage:true});await page.close();console.log('PASS source-only catalog entry, automatic all-source search, subset chips and online/save targets at '+width+'px');
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const name of['world-harness.html','world-harness.jsx'])await fs.rm(path.join(DIR,name),{force:true});});
