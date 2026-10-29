// UI/provider contracts. No production account, sources, or ML inference.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'test-output');let vite,browser;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});await fs.writeFile(path.join(DIR,'world-harness.html'),'<meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/test-output/world-harness.jsx"></script>');
 await fs.writeFile(path.join(DIR,'world-harness.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import CatalogBrowser from'/src/CatalogBrowser.jsx';import MangaImport from'/src/MangaImport.jsx';import TitlePage from'/src/TitlePage.jsx';import'/src/styles.css';import'/src/title-page.css';import'/src/import-workspace.css';import'/src/import-layout.css';import'/src/discovery-polish.css';
 window.searchBodies=[];window.cancelled=[];window.inspected=[];let counter=0;
 const result={id:'suwayomi:1:42',provider:'suwayomi:1',providerName:'Source A',sourceId:'1',kind:'manga',title:'Новый тайтл только в источнике',aliases:['Новый тайтл только в источнике'],url:'https://media.example/__manga/suwayomi/m/42',language:'ru',format:'manga',genres:['Комедия'],sourceOnly:true};
 const service={server:location.origin,status:'connected',session:{serverVersion:16},jobs:[],request:async(p,o={})=>{
 if(p.startsWith('/discovery/manga/sources'))return{sources:[{id:'1',name:'Source A',language:'ru'},{id:'2',name:'Source B',language:'ja'}]};
 if(p==='/discovery/manga/search'){window.searchBodies.push(o.body);return{id:String(++counter),state:'running',progress:{completed:0,total:770},results:[]};}
 if(p.startsWith('/discovery/manga/search/')&&location.search.includes('fallback')&&o.method!=='DELETE'){window.fallbackPoll=(window.fallbackPoll||0)+1;const recovered=window.fallbackPoll>1;return{id:'fallback',state:recovered?'done':'running',progress:{completed:recovered?2:1,total:2},results:recovered?[result,{...result,provider:'mangalib',providerName:'MangaLib',url:'https://mangalib.me/ru/195--naruto'}]:[result]};}
 if(p.startsWith('/discovery/manga/search/')){if(o.method==='DELETE'){window.cancelled.push(p);return{state:'cancelled'};}return{id:p.split('/').at(-1),state:'done',progress:{completed:770,total:770,failed:2,cached:700},results:location.search?[{...result,title:'Игрок максимального уровня',aliases:['Игрок максимального уровня'],url:'https://media.example/wrong'},result]:[result]};}
 if(p==='/manga/search')return{results:[],providers:[]};
 if(p==='/manga/inspect'){window.inspected.push(o.body.url);if(location.search.includes('fallback')&&o.body.url===result.url)throw Error('HTTP 404 source unavailable');return{provider:'suwayomi:1',providerName:'Source A',title:result.title,url:result.url,language:'ru',episodes:[1,2].map(n=>({url:result.url+'/c/'+n,number:n,season:1,title:'Глава '+n,language:'ru'})),seasons:[{number:1,name:'Том 1'}],translations:[]};}
 if(p==='/online/prepare')return{id:'preview',pages:['/online/preview/p.png'],kind:'manga'};
 if(p.startsWith('/online/preview'))return{closed:true};
 if(p.endsWith('/status'))return{ready:true,availableExtensions:1435,sources:[]};
 return{state:'idle',extensions:[]};}};
 const referenceProfile={version:4,sourceId:'fixture',title:result.title,format:'Манга',genres:['Комедия'],characters:[],related:[],themes:[]};
 function Demo(){const[reference,setReference]=React.useState(false);return <><button onClick={()=>setReference(true)}>Показать эталон коллекции</button><main style={{maxWidth:1350,margin:'auto',padding:18}}>{reference?<TitlePage title={{id:'reference',name:result.title,section:'manga',category:'manga',items:[],parts:[],profile:referenceProfile}} state={{admin:false,user:{sub:'fixture'},catalog:{titleProfiles:{reference:referenceProfile}}}} actions={{}} onBack={()=>{}}/>:<CatalogBrowser service={service} state={{admin:true,user:{sub:'fixture'},catalog:null}} initialKind="manga" destination="online" onSubmitted={()=>{}}/>}</main></>;}
 createRoot(document.getElementById('root')).render(location.search?<MangaImport compact destination="online" item={{id:'metadata:1',kind:'manga',title:result.title,aliases:[result.title]}} state={{user:{sub:'fixture'}}} service={service}/>:<Demo/>);`);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:7905,hmr:false}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 for(const width of[360,1440]){
  const page=await browser.newPage({viewport:{width,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/online/preview/p.png',r=>r.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a+kkAAAAASUVORK5CYII=','base64')}));
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
  await page.getByRole('button',{name:'Читать сейчас',exact:true}).waitFor();assert.equal(await page.locator('.title-save-menu').getAttribute('open'),null,'Saving is a secondary disclosure');
  assert.equal(await page.getByRole('button',{name:'Проверить следующие источники',exact:true}).count(),0);
  await page.getByText('Сохранить в коллекцию или на устройство',{exact:true}).click();await page.getByRole('button',{name:'На устройство',exact:true}).click();await page.getByRole('button',{name:'Сохранить на устройство',exact:true}).waitFor();
  await page.getByRole('button',{name:'В Google Диск',exact:true}).click();await page.getByRole('button',{name:'Добавить 2 главы в коллекцию',exact:true}).waitFor();
  await page.getByRole('button',{name:'Онлайн',exact:true}).click();await page.getByText('Сохранить в коллекцию или на устройство',{exact:true}).click();
  await page.getByRole('button',{name:'Читать сейчас',exact:true}).click();await page.locator('.reader-embedded .reader-page-image img').first().waitFor();
  await page.waitForFunction(()=>document.querySelector('.reader-embedded .reader-page-image img')?.naturalWidth>0);
  assert.equal(await page.getByRole('dialog',{name:'Онлайн без сохранения',exact:true}).count(),0);assert.equal(await page.locator('.online-title-materials .online-viewer-inline').count(),1,'Reader stays inside title materials');
  assert.equal(await page.locator('.reader-embedded').evaluate(n=>getComputedStyle(n).position),'relative');assert.notEqual(await page.evaluate(()=>document.body.style.overflow),'hidden');
  await page.getByRole('button',{name:'Развернуть просмотр на весь экран',exact:true}).click();await page.waitForFunction(()=>document.fullscreenElement?.classList.contains('online-viewer-inline'));await page.getByRole('button',{name:'Вернуть на страницу',exact:true}).click();await page.waitForFunction(()=>!document.fullscreenElement);
  await page.getByRole('button',{name:'Закрыть встроенный просмотр',exact:true}).click();assert.equal(await page.locator('.online-viewer-inline').count(),0);
  await page.locator('.online-title-materials .title-episode-card').filter({hasText:'Глава 2'}).click();await page.waitForFunction(()=>document.querySelector('.online-viewer-inline>header small')?.textContent.includes('Глава 2'));await page.getByRole('button',{name:'Закрыть встроенный просмотр',exact:true}).click();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'No horizontal overflow');assert.deepEqual(errors,[]);
  assert.equal(await page.locator('.online-title-page .title-hero').count(),1);assert.equal(await page.locator('.world-title-grid').count(),0,'No second title template');assert.equal(await page.locator('.online-title-materials .title-episode-card').count(),2,'Online chapters use the collection episode cards');
  const layout=()=>{const read=selector=>{const n=document.querySelector(selector),s=getComputedStyle(n);return{display:s.display,columns:s.gridTemplateColumns,gap:s.gap,padding:s.padding,radius:s.borderRadius,font:s.fontSize,lineHeight:s.lineHeight,width:Math.round(n.getBoundingClientRect().width)};};return{hero:read('.title-hero'),poster:read('.title-poster'),heading:read('.title-hero h1'),columns:read('.title-page-columns')};};
  const onlineLayout=await page.evaluate(layout);await page.screenshot({path:path.join(DIR,'world-library-'+width+'.png'),fullPage:true});await page.getByRole('button',{name:'Показать эталон коллекции',exact:true}).click();assert.deepEqual(await page.evaluate(layout),onlineLayout,'Online and collection share title geometry and typography');await page.screenshot({path:path.join(DIR,'collection-reference-'+width+'.png'),fullPage:true});await page.close();console.log('PASS source-only catalog entry, automatic all-source search, subset chips and online/save targets at '+width+'px');
 }
 const identity=await browser.newPage({viewport:{width:1280,height:900}});
 await identity.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/world-harness.html?identity=1');
 await identity.getByRole('button',{name:'Читать сейчас',exact:true}).waitFor();
 assert.deepEqual(await identity.getByLabel('Источник чтения').locator('option').allTextContents(),['Выбери источник','Source A · Русский']);
 assert.deepEqual(await identity.evaluate(()=>window.inspected),['https://media.example/__manga/suwayomi/m/42']);
 await identity.getByText('Другой источник или своя ссылка',{exact:true}).click();
 await identity.getByRole('button',{name:'Обновить источники',exact:true}).click();
 await identity.waitForFunction(()=>window.searchBodies.some(b=>b.refresh===true));
 await identity.close();console.log('PASS metadata title excludes unrelated provider hits and source refresh bypasses cache');

 const fallback=await browser.newPage({viewport:{width:1280,height:900}});
 await fallback.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/world-harness.html?fallback=1');
 await fallback.getByRole('button',{name:'Читать сейчас',exact:true}).waitFor();
 assert.deepEqual(await fallback.evaluate(()=>window.inspected),['https://media.example/__manga/suwayomi/m/42','https://mangalib.me/ru/195--naruto']);
 assert.equal(await fallback.getByLabel('Источник чтения').locator('option').count(),3,'Failed source remains selectable');
 await fallback.getByLabel('Источник чтения').selectOption('https://media.example/__manga/suwayomi/m/42');
 await fallback.getByRole('alert').filter({hasText:'HTTP 404'}).waitFor();
 assert.equal(await fallback.getByLabel('Источник чтения').inputValue(),'https://media.example/__manga/suwayomi/m/42','Explicit source selection is never replaced');
 await fallback.close();console.log('PASS automatic source failure recovers to native MangaLib while manual selection is preserved');

})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const name of['world-harness.html','world-harness.jsx'])await fs.rm(path.join(DIR,name),{force:true});});
