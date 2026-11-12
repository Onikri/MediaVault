// Real MangaImport/retained portal; API replies are fixtures, not live provider tests.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
let browser,vite;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/source-queue'),base='/.codex-local/test-output/source-queue/';await fs.mkdir(dir,{recursive:true});
 await fs.writeFile(path.join(dir,'index.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="'+base+'fixture.jsx"></script>');
 await fs.writeFile(path.join(dir,'fixture.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import MangaImport from'/src/MangaImport.jsx';import{RetainedMediaProvider,RetainedMediaSlot}from'/src/RetainedMedia.jsx';import'/src/styles.css';import'/src/title-page.css';
 const title={id:'vagabond',kind:'manga',title:'Бродяга',titles:{en:'Vagabond',ja:'バガボンド'}},byProvider=location.search.includes('provider'),sources=['ru','ru','ja','ja','ja'].map((language,n)=>({sourceId:String(n),provider:'suwayomi:'+n,providerName:'Reader '+n,url:'https://source.example/'+n,title:'Vagabond',language:byProvider?'ja':language}));
 window.calls=[];window.aborted=[];window.active=0;window.peak=0;window.releaseRussian=false;let serial=0;
 const wait=(ms,signal)=>new Promise((resolve,reject)=>{const timer=setTimeout(done,ms);function done(){signal?.removeEventListener('abort',cancel);resolve();}function cancel(){clearTimeout(timer);signal?.removeEventListener('abort',cancel);reject(signal.reason);}if(signal?.aborted)cancel();else signal?.addEventListener('abort',cancel,{once:true});});
 const service={server:'https://api.fixture',status:'connected',session:{serverVersion:68},request:async(p,o={})=>{
  if(p==='/manga/search')return{results:[],providers:[]};
  if(p==='/discovery/manga/search')return{id:String(++serial),state:'done',results:[],progress:{completed:179,total:179}};
  if(p.startsWith('/discovery/manga/search/'))return{state:'cancelled'};
  if(p.startsWith('/discovery/manga/sources'))return{sources:sources.map(s=>({id:s.sourceId,name:s.providerName,language:s.language}))};
  if(p==='/manga/inspect'||p==='/manga/summary'){
   const n=Number(o.body.url.split('/').at(-1));window.calls.push({path:p,n});window.active++;window.peak=Math.max(window.peak,window.active);
   try{await wait(n<2&&!window.releaseRussian?60000:50,o.signal);return{title:title.title,url:o.body.url,language:sources[n].language,chapterCount:322,volumeCount:1,episodes:[{url:o.body.url+'/chapter/1',number:1,season:1,title:'Глава Reader '+n,language:sources[n].language}],seasons:[{number:1,name:'Том 1'}],translations:[],...(p==='/manga/summary'?{readable:true,verifiedPages:1}:{})};}
   catch(e){if(o.signal?.aborted)window.aborted.push(n);throw e;}finally{window.active--;}
  }return{};
 }};
 function Demo(){const[shown,setShown]=React.useState(true);return <RetainedMediaProvider><main style={{maxWidth:900,margin:'auto',padding:16}}><button onClick={()=>setShown(v=>!v)}>Toggle title</button>{shown&&<RetainedMediaSlot id="manga-test" kind="reader" label="Бродяга"><MangaImport compact destination="online" item={{...title,sources}} state={{user:{sub:'fixture'}}} service={service}/></RetainedMediaSlot>}</main></RetainedMediaProvider>;}createRoot(document.getElementById('root')).render(<Demo/>);`);
 const{createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/vite-source-queue',logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0,strictPort:false}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 for(const width of [360,1440])for(const filter of ['language','provider']){
  const page=await browser.newPage({viewport:{width,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+base+'index.html?'+filter);
  await page.waitForFunction(()=>window.calls.filter(c=>c.path==='/manga/inspect').length===2);
  if(filter==='language')await page.getByLabel('Язык источника манги',{exact:true}).selectOption('ja');
  else{
   await page.locator('#worldSourceQuery').fill('Reader 4');
   await page.getByRole('checkbox',{name:/Reader 4/}).check();
   await page.getByRole('button',{name:'Готово',exact:true}).click();
  }
  await page.waitForFunction(()=>window.calls.some(c=>c.path==='/manga/summary'&&c.n>=2),{},{timeout:2500});
  assert.deepEqual((await page.evaluate(()=>window.aborted)).sort(),[0,1],'Hidden-language requests release both verification slots');
  await page.waitForFunction(()=>window.active===0,{},{timeout:5000});
  assert.equal(await page.locator('.title-source-option').count(),filter==='language'?3:1,'Selected candidates appear without waiting for hidden sources');
  await page.getByRole('button',{name:'Читать сейчас',exact:true}).waitFor();
  assert.equal(await page.locator('.title-source-option[aria-pressed="true"]').count(),1);
  if(filter==='provider'){
   assert.ok((await page.locator('.title-source-option[aria-pressed="true"]').innerText()).includes('Reader 4'));
   await page.getByRole('button',{name:'Toggle title',exact:true}).click();
   assert.equal(await page.locator('.retained-media-host').count(),0);assert.deepEqual(errors,[]);await page.close();console.log('PASS provider filter cancels hidden checks and prioritizes selected reader '+width);continue;
  }
  const calls=await page.evaluate(()=>window.calls.length);
  await page.evaluate(()=>{window.releaseRussian=true;});
  await page.getByLabel('Язык источника манги',{exact:true}).selectOption('all');
  await page.waitForFunction(()=>window.calls.length>0&&window.active===0&&document.querySelectorAll('.title-source-option').length===5,{},{timeout:5000});
  await page.getByLabel('Язык источника манги',{exact:true}).selectOption('ja');
  assert.equal(await page.locator('.title-source-option').count(),3);
  assert.equal(await page.evaluate(()=>window.calls.filter(c=>c.n>=2).length),await page.evaluate(end=>window.calls.slice(0,end).filter(c=>c.n>=2).length,calls),'Completed Japanese results survive filter changes');
  await page.getByLabel('Язык источника манги',{exact:true}).selectOption('ru');
  await page.waitForFunction(()=>document.querySelector('.title-source-option[aria-pressed="true"]')?.textContent.includes('Reader 0'));
  await page.getByLabel('Язык источника манги',{exact:true}).selectOption('ja');
  await page.waitForFunction(()=>document.querySelector('.title-source-option[aria-pressed="true"]')?.textContent.includes('Reader 2'));
  await page.getByRole('button',{name:'Toggle title',exact:true}).click();
  assert.equal(await page.locator('.retained-media-host').count(),0,'Inactive title checks unmount with their retained host');
  assert.deepEqual(errors,[]);await page.close();console.log('PASS language switches cancel hidden checks, retain verified results and unblock real retained title '+width);
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
