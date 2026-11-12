// Browser contract fixtures only: no real accounts, manga images or ML requests.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),dir=path.join(root,'.codex-local/test-output/title-details'),base='/.codex-local/test-output/title-details/';let vite,browser;
(async()=>{
 await fs.mkdir(dir,{recursive:true});
 await fs.writeFile(path.join(dir,'index.html'),'<meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="'+base+'harness.jsx"></script>');
 await fs.writeFile(path.join(dir,'harness.jsx'),`
 import React from 'react';import{createRoot}from'react-dom/client';import WorldTitlePage from'/src/WorldTitlePage.jsx';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';import MangaImport from'/src/MangaImport.jsx';import'/src/styles.css';import'/src/title-page.css';import'/src/import-layout.css';import'/src/discovery-polish.css';import'/src/site-layout.css';import'/src/site-mobile.css';
 const late=location.search.includes('late'),source={title:'Ёцуба и!',aliases:['Ёцуба и!'],kind:'manga',provider:'mangalib',providerName:'MangaLib',language:'ru',url:'https://mangalib.me/ru/fixture'};
 const known=b=>b?.title?.aliases?.includes('Ёцуба и!');window.requests=[];window.inspections=[];
 const service={server:location.origin,status:'connected',session:{serverVersion:69},request:async(p,o={})=>{
 if(p==='/manga/search'){window.requests.push(o.body);return{results:known(o.body)?[source]:[],providers:[]};}
 if(p==='/discovery/manga/search')return{id:'fixture',state:'done',results:known(o.body)?[source]:[],progress:{completed:1,total:1}};
 if(p.startsWith('/discovery/manga/sources'))return{sources:[{id:'1',name:'MangaLib',language:'ru'}]};
 if(p==='/manga/inspect'){window.inspections.push(o.body);if(!known(o.body))throw Error('Источник относится к другому произведению.');return{...source,readable:undefined,chapterCount:2,volumeCount:1,episodes:[1,2.5].map(n=>({number:n,season:1,language:'ru',url:source.url+'/chapter/'+n,title:'Глава '+n})),seasons:[{number:1,name:'Том 1'}]};}
 if(p==='/manga/summary')return{chapterCount:2,volumeCount:1,readable:true};return{};}};
 const state={user:{sub:'fixture'},catalog:{items:[],titleProfiles:{}}},item={id:'manga:fixture',kind:'manga',title:'Yotsuba&!',titles:{en:'Yotsuba&!',native:'よつばと!'},aliases:late?['Yotsuba&!']:['Yotsuba&!','Ёцуба и!','よつばと!'],chapters:120,volumes:16,status:'RELEASING',sources:late?[{...source,title:'Yotsuba&!',aliases:['Yotsuba&!']}]:[],sourceOnly:true,genres:[],tags:[],ids:{}};
 function Demo(){const[value,setValue]=React.useState(item);return late?<main><button onClick={()=>setValue({...value,aliases:[...value.aliases,'Ёцуба и!']})}>Обновить названия</button><MangaImport compact destination="online" item={value} state={state} service={service}/></main>:<WorldTitlePage value={value} state={state} service={service} onBack={()=>{}}/>;}
 createRoot(document.getElementById('root')).render(<ThemeProvider><Demo/></ThemeProvider>);`);
 const{createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/vite-title-details',logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 for(const width of[390,1440]){
  const p=await browser.newPage({viewport:{width,height:900},reducedMotion:'reduce'}),errors=[];p.setDefaultTimeout(12000);p.on('pageerror',e=>errors.push(e.message));
  await p.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
  const url='http://127.0.0.1:'+vite.httpServer.address().port+base+'index.html';await p.goto(url);
  await p.getByLabel('Альтернативные названия',{exact:true}).filter({hasText:'Ёцуба и!'}).waitFor();
  const facts=p.locator('.title-hero-facts');await facts.locator('div').filter({hasText:'Последняя глава в источнике'}).filter({hasText:'2.5'}).waitFor();assert.equal(await facts.locator('div').filter({hasText:'Главы в каталоге'}).locator('dd').innerText(),'120');
  assert.equal(await facts.locator('div').filter({hasText:'Главы в источнике'}).locator('dd').innerText(),'2 · Русский');
  assert.ok(await p.evaluate(()=>window.requests.some(b=>b.title.aliases.includes('Ёцуба и!'))));
  assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await p.evaluate(()=>document.fonts.ready);await p.screenshot({path:path.join(dir,'title-'+width+'.png'),fullPage:true});
  await p.goto(url+'?late');await p.waitForFunction(()=>window.requests.length>0&&window.inspections.length>0);await p.waitForFunction(()=>document.querySelector('.title-source-picker')?.textContent.includes('Источник относится к другому произведению.'));assert.equal(await p.locator('.title-source-option').count(),0);
  await p.getByRole('button',{name:'Обновить названия'}).click();await p.locator('.title-source-option').filter({hasText:'MangaLib'}).waitFor();await p.getByRole('button',{name:'Читать сейчас',exact:true}).waitFor();assert.equal(await p.getByRole('button',{name:'Читать сейчас',exact:true}).isEnabled(),true);
  assert.ok(await p.evaluate(()=>window.inspections.at(-1).title.aliases.includes('Ёцуба и!')));assert.deepEqual(errors,[]);await p.close();console.log('PASS catalogue aliases/counts, verified chapter feedback, late Russian source discovery '+width+'px');
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
