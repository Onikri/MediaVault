// UI/API fixtures only. Real Suwayomi source checks are recorded separately.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'test-output');let vite,browser;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});await fs.writeFile(path.join(DIR,'suwayomi-harness.html'),'<div id="root"></div><script type="module" src="/test-output/suwayomi-harness.jsx"></script>');
 await fs.writeFile(path.join(DIR,'suwayomi-harness.jsx'),`
import React,{useState} from 'react';import{createRoot}from'react-dom/client';import MangaSourceManager from '/src/MangaSourceManager.jsx';import MangaImport from '/src/MangaImport.jsx';import '/src/styles.css';
let installed=false,pack=null;window.installs=0;window.moreRequests=[];
const rows=[{package:'fixture.ru',name:'Manga Source',language:'ru',installed:false},{package:'fixture.ja',name:'Raw Source',language:'ja',installed:false}];
const service={status:'connected',session:{serverVersion:15,driveConnected:true},request:async(url,options)=>{
 if(url==='/manga/search')return{results:[],providers:[],bridgeSearch:{nextOffset:8,totalSources:40,hasMore:true}};
 if(url==='/manga/bridge/search'){window.moreRequests.push(options.body.bridgeOffset);return{results:[{url:'https://media.example/__manga/suwayomi/m/42',provider:'late',providerName:'Source after the first 32',title:'Demo Manga',language:'en'}],providers:[],window:{checked:8,nextOffset:16,totalSources:40,hasMore:true}};}
 if(url.endsWith('/install-pack')){if(options?.method==='POST'){window.packLanguages=options.body.languages;pack={id:'fixture-pack',state:'done',completed:100,total:100,installed:99,failed:[]};}return pack||{state:'idle'};}
 if(url.endsWith('/install')){window.installs++;installed=true;return{installed:true};}
 if(url.endsWith('/status'))return{ready:true,availableExtensions:1435,sources:installed?[{}]:[]};
 const query=new URL(url,'http://localhost').searchParams;return{extensions:rows.filter(r=>r.language===query.get('language')&&r.name.toLowerCase().includes((query.get('q')||'').toLowerCase())).map(r=>({...r,installed:r.language==='ru'&&installed}))};
}};
function App(){const[view,setView]=useState(false);return <main style={{maxWidth:700,margin:'30px auto',padding:12}}><button onClick={()=>setView(true)}>Проверить поиск</button>{view?<MangaImport state={{admin:true,catalog:{},libraryId:'fixture',user:{sub:'fixture'}}} service={service} item={{id:'42',kind:'manga',title:'Demo Manga'}}/>:<MangaSourceManager service={service} onInstalled={()=>window.refreshed=true}/>}</main>;}
createRoot(document.getElementById('root')).render(<App/>);`);
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:5194}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 for(const width of[360,1440]){
  const page=await browser.newPage({viewport:{width,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:5194/test-output/suwayomi-harness.html');
  assert.equal(await page.getByLabel('Язык дополнительных источников').count(),0);await page.locator('summary').click();await page.getByRole('button',{name:'Подключить: Manga Source',exact:true}).click();await page.getByRole('button',{name:'Подключён: Manga Source',exact:true}).waitFor();assert.equal(await page.evaluate(()=>window.installs),1);
  await page.getByLabel('Язык дополнительных источников').selectOption('ja');await page.getByRole('button',{name:'Подключить: Raw Source',exact:true}).waitFor();await page.getByLabel('Поиск дополнительных источников').fill('missing');await page.getByText('По этому запросу источников нет.').waitFor();await page.getByLabel('Поиск дополнительных источников').fill('Raw');await page.getByRole('button',{name:'Подключить: Raw Source',exact:true}).waitFor();
  await page.getByRole('button',{name:'Подключить все RU · EN · JA · KO',exact:true}).click();await page.getByText(/Пакет готов: 100/).waitFor();assert.deepEqual(await page.evaluate(()=>window.packLanguages),['ru','en','ja','ko']);assert.equal(await page.evaluate(()=>window.refreshed),true);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(DIR,'suwayomi-'+width+'.png')});
  await page.getByRole('button',{name:'Проверить поиск',exact:true}).click();await page.getByText('Дополнительные источники: проверено 8 из 40.').waitFor();await page.getByRole('button',{name:'Проверить следующие источники',exact:true}).click();await page.getByText('Source after the first 32',{exact:true}).waitFor();assert.deepEqual(await page.evaluate(()=>window.moreRequests),[8]);await page.getByText('Дополнительные источники: проверено 16 из 40.').waitFor();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);await page.close();console.log('PASS source catalog, individual/bulk install, progress and paged title search at '+width+'px');
 }
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{await browser?.close();await vite?.close();for(const name of['suwayomi-harness.html','suwayomi-harness.jsx'])await fs.rm(path.join(DIR,name),{force:true});});
