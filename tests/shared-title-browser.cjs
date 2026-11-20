// A title opened by share link shows only that title and its reader: no links,
// no way back into the site, no owner tools; closing the reader stays on the page.
// The owner's reader offers the share button. The server is a mocked route set.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'.codex-local','shared-title-fixture');
const HARNESS='/.codex-local/shared-title-fixture/shared-title-harness';
const reveal=async page=>{const reader=page.locator('.immersive-reader').last();await reader.waitFor();if(await reader.getAttribute('data-chrome')!=='true'){const box=await reader.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+2);await page.mouse.move(box.x+box.width/2,box.y+20);await page.waitForFunction(()=>document.querySelector('.immersive-reader')?.dataset.chrome==='true');}};
(async()=>{
 await fs.mkdir(DIR,{recursive:true});
 await fs.writeFile(path.join(DIR,'shared-title-harness.html'),'<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="'+HARNESS+'.jsx"></script></html>');
 await fs.writeFile(path.join(DIR,'shared-title-harness.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import JSZip from'jszip';import'/src/styles.css';
 import MangaReader from'/src/MangaReader.jsx';import{publishTitleShare}from'/src/title-context.js';import TitlePage from'/src/TitlePage.jsx';import TitleSourcePicker from'/src/TitleSourcePicker.jsx';import'/src/manga-desk.css';import'/src/title-dossier.css';import'/src/world-library.css';
 window.MEDIA_VAULT_CONFIG={importServerUrl:location.origin};
 const mode=new URLSearchParams(location.search).get('mode');
 const service={server:location.origin,status:'connected',session:{role:'owner',serverVersion:76},request:async(p,o={})=>{if(p.startsWith('/shares/title/')&&o.method==='DELETE'){window.revoked=p;return{revoked:true};}if(p!=='/shares/title')return{};await new Promise(r=>setTimeout(r,80));(window.shares||=[]).push(o.body);const mark=o.body.translate?'T':'O';return{id:'b'.repeat(64),token:mark.repeat(43)};}};
 if(mode==='owner'||mode?.startsWith('auto-')){
  const view=mode.slice(5);
  if(mode!=='owner')localStorage.setItem('mediavault_reader_v3:u:manga',JSON.stringify({mode:view==='drift'?'scroll':view,fit:'width',autoNext:true,autoScroll:view==='drift',autoScrollSpeed:'fast',transition:'simple'}));
  const c=document.createElement('canvas');c.width=400;c.height=600;c.getContext('2d').fillRect(0,0,400,600);const png=await new Promise(r=>c.toBlob(r,'image/png'));
  const zip=new JSZip();for(let i=1;i<=3;i++)zip.file(i+'.png',png);const archive=await zip.generateAsync({type:'blob'});
  publishTitleShare({service,title:{title:'Тестовая манга'},kind:'manga',entries:[{url:'https://manga.example/c1',number:1,season:1,title:'Глава 1'}],initial:{url:'https://manga.example/c1'},referer:'https://manga.example/t',dub:'Нова',language:'ru',userId:'u'});
  const item={id:'c1-'+mode,category:'manga',collectionId:'test',sourceURL:'https://manga.example/c1',name:'Тестовая манга · глава 1.cbz',episode:1,translationInfo:{language:'ru'}};
  const following={...item,id:'c2',episode:2,sourceURL:'https://manga.example/c2'};
  createRoot(document.getElementById('root')).render(<MangaReader item={item} catalog={{items:[item,following]}} userId="u" libraryId="fixture" readerService={service} onClose={()=>{}} onSelectItem={entry=>{window.next=entry.episode;}} readWhole={async()=>archive}/>);
 }else if(mode==='hero'){
  const id='test-manhwa',title={id,name:'Тестовая манхва',category:'manga',section:'manga',items:[],parts:[]};
  createRoot(document.getElementById('root')).render(<TitlePage title={title} actions={{}} state={{user:{sub:'u'}}} online onlineProfile={{title:title.name,format:'Манхва'}} shareService={service}/>);
 }else if(mode==='sources'){
  const sources=[{url:'one',providerName:'Nude-Moon',language:'ru'},{url:'two',providerName:'HentaiChan.cc',language:'ru'}];
  const favorites={has:source=>source.url==='two',toggle:()=>{}};
  const info=Object.fromEntries(sources.map(s=>[s.url,{state:'ready',readable:true,chapterCount:1,volumeCount:1}]));
  createRoot(document.getElementById('root')).render(<div className="desk-source-menu" style={{width:'min(100%, 282px)'}}><TitleSourcePicker sources={sources} value="two" onChoose={()=>{}} favorites={favorites} info={info}/></div>);
 }else{
  location.hash='share='+'S'.repeat(43);const {default:App}=await import('/src/App.jsx');createRoot(document.getElementById('root')).render(<App/>);
 }`);
 const{createServer}=await import('vite');const vite=await createServer({root:ROOT,cacheDir:'.codex-local/shared-title-e2e-cache',logLevel:'error',server:{watch:null,host:'127.0.0.1',port:5196,strictPort:false}});await vite.listen();
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const base='http://127.0.0.1:'+vite.httpServer.address().port+HARNESS+'.html';
  const page=await browser.newPage({viewport:{width:1280,height:860}}),errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.message);});
  await page.addInitScript(()=>{
   Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
    async write([item]){window.copied=await (await item.getType('text/plain')).text();},
    async writeText(link){window.copied=link;}
   }});
  });
  const grant={id:'a'.repeat(64),token:'grant-token',expiresAt:Math.floor(Date.now()/1000)+86400,kind:'manga',title:{name:'Тестовое произведение',cover:'/cover-test.png',description:'Описание тайтла. '.repeat(30),year:2018,format:'manhwa',ids:{}},
   entries:[1,2].map(n=>({url:'https://manga.example/c'+n,number:n,season:1,title:'Глава '+n})),initial:0,referer:null,dub:'Нова',language:'ru',quality:'best',translate:false,translation:{}};
  const image=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=','base64');
  await page.route('**/shares/title/*',r=>r.fulfill({json:grant}));
  await page.route('**/cover-test.png',r=>r.fulfill({contentType:'image/png',body:image}));
  await page.route('**/manga/thumbnail',r=>r.fulfill({json:{image:'data:image/jpeg;base64,'+image.toString('base64')}}));
  const opened=[];
  await page.route('**/online/**',r=>{const m=r.request().method();if(m==='POST'){
   if(r.request().url().endsWith('/online/prepare'))opened.push(r.request().postDataJSON().url);
   return r.fulfill({json:{id:'manga-token-0123456789abcdef',pages:[1,2].map(n=>'/online/manga-token-0123456789abcdef/'+n),type:'manga'}});
  }if(m==='DELETE')return r.fulfill({json:{closed:true}});return r.fulfill({contentType:'image/png',body:image});});
  await page.goto(base);
  await page.getByRole('heading',{name:grant.title.name,level:1}).waitFor();
  await page.locator('.shared-title-lane img[src^="data:"]').first().waitFor();
  assert.equal(await page.locator('.immersive-reader').count(),0);
  assert.equal(opened.length,0);
  assert.equal(await page.locator('a[href]').count(),0,'The shared page links nowhere');
  assert.equal(await page.getByRole('button',{name:/На главную|Библиотека|Назад/}).count(),0,'No way back into the site');
  assert.equal(await page.evaluate(()=>scrollY),0,'The page opens at the title, not scrolled to the reader');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.getByRole('combobox',{name:'Выбрать главу'}).selectOption('1');
  await page.getByRole('button',{name:'Читать',exact:true}).click();
  await page.locator('.immersive-reader').waitFor();
  assert.equal(opened[0],grant.entries[1].url);
  await reveal(page);
  assert.equal(await page.getByRole('button',{name:'Отладка страницы'}).count(),0,'Server diagnostics stay hidden from a visitor');
  assert.equal(await page.getByRole('button',{name:'Поделиться тайтлом'}).count(),0,'A visitor cannot reshare');
  await page.getByRole('button',{name:'Закрыть просмотр',exact:true}).click();
  await page.getByRole('button',{name:'Читать',exact:true}).waitFor();
  assert.match(await page.evaluate(()=>location.hash),/^#share=/,'Closing the reader keeps the visitor on the shared title');
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(150);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'No sideways scroll on a phone');
  assert.equal(await page.getByRole('combobox',{name:'Выбрать главу'}).inputValue(),'1');
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.locator('.shared-title-lane').first().evaluate(node=>getComputedStyle(node).animationName),'none');
  // The owner shares from the existing toolbar in both viewports.
  await page.setViewportSize({width:1280,height:860});await page.goto(base+'?mode=owner');
  await page.locator('.reader-page img').first().waitFor();await reveal(page);
  const toolbar=page.locator('.reader-top');
  const before=await toolbar.boundingBox();
  await page.getByRole('button',{name:'Поделиться тайтлом'}).click();
  assert.equal(await page.locator('.title-share-capsule button').count(),2);
  assert.deepEqual(await toolbar.boundingBox(),before,'Share choices leave the toolbar in place');
  assert.equal(await page.locator('.server-dialog').count(),0,'The reader uses its toolbar');
  await page.getByRole('button',{name:'С переводом',exact:true}).click();
  await page.waitForFunction(()=>/#share=T{43}$/.test(window.copied||''));
  assert.equal(await page.evaluate(()=>window.shares[0].translate),true);
  assert.equal(await page.evaluate(()=>window.shares[0].kind),'manga');
  await page.getByRole('button',{name:'Закрыть доступ по ссылке'}).click();
  await page.waitForFunction(()=>window.revoked==='/shares/title/'+'b'.repeat(64));
  await page.keyboard.press('Escape');
  await page.setViewportSize({width:360,height:800});
  await reveal(page);
  await page.getByRole('button',{name:'Поделиться тайтлом'}).click();
  const choice=page.getByRole('button',{name:'Без перевода',exact:true});
  await choice.waitFor();
  const box=await choice.boundingBox();
  assert.ok(box.x>=0&&box.x+box.width<=360,'Phone action fits in the toolbar');
  await choice.click();
  await page.waitForFunction(()=>/#share=O{43}$/.test(window.copied||''));
  assert.deepEqual(await page.evaluate(()=>[window.shares[1].translate,window.shares[1].translation]),[false,{}]);
  await page.goto(base+'?mode=hero');
  await page.getByRole('button',{name:'Поделиться тайтлом'}).click();
  await page.waitForFunction(()=>window.shares?.[0]?.kind==='title');
  assert.deepEqual(await page.evaluate(()=>window.shares[0].entries),[]);

  await page.setViewportSize({width:1280,height:860});
  for(const view of ['scroll','pages','spread','focus']){
   await page.goto(base+'?mode=auto-'+view);
   await page.locator('.reader-page img').first().waitFor();
   if(view==='scroll')await page.locator('.reader-content').evaluate(node=>node.scrollTop=node.scrollHeight);
   else await page.keyboard.press('End');
   await page.waitForFunction(()=>document.querySelector('[data-page="2"] .reader-image-stack img')?.naturalWidth>0);
   if(view==='spread')assert.equal(await page.locator('.reader-content .reader-page').count(),2);
   await page.locator('.reader-content').evaluate(node=>node.scrollTop=node.scrollHeight);
   const sendWheel=delta=>page.locator('.reader-content').evaluate((node,delta)=>{
    node.dispatchEvent(new WheelEvent('wheel',{deltaY:delta,bubbles:true}));
   },delta);
   await sendWheel(25);
   assert.equal(await page.evaluate(()=>window.next),undefined,view+' tolerates small wheel movement');
   await sendWheel(230);
   await page.waitForFunction(()=>window.next===2,null,{timeout:3000}).catch(async error=>{
    const state=await page.locator('.reader-content').evaluate(node=>({top:node.scrollTop,height:node.scrollHeight,viewport:node.clientHeight,mode:node.className,panel:node.closest('.immersive-reader').dataset.panel}));
    throw Error(view+': '+JSON.stringify(state),{cause:error});
   });
  }
  await page.goto(base+'?mode=auto-drift');
  await page.waitForFunction(()=>document.querySelector('.reader-content')?.scrollTop>24);
  await page.setViewportSize({width:360,height:800});
  await page.goto(base+'?mode=auto-scroll');
  const surface=page.locator('.reader-content');
  await page.locator('.reader-page img').first().waitFor();
  await surface.evaluate(node=>node.scrollTop=node.scrollHeight);
  await page.waitForFunction(()=>document.querySelector('[data-page="2"] .reader-image-stack img')?.naturalWidth>0);
  await surface.evaluate(node=>{
   node.scrollTop=node.scrollHeight;
   const touch=y=>new Touch({identifier:1,target:node,clientX:130,clientY:y});
   node.dispatchEvent(new TouchEvent('touchstart',{touches:[touch(610)],bubbles:true}));
   node.dispatchEvent(new TouchEvent('touchend',{changedTouches:[touch(465)],bubbles:true}));
  });
  await page.waitForFunction(()=>window.next===2);
  await page.goto(base+'?mode=sources');
  const picked=page.locator('.title-source-option').filter({hasText:'HentaiChan.cc'});
  await picked.waitFor();
  assert.equal(await picked.getAttribute('aria-pressed'),'true');
  assert.equal(await picked.evaluate(node=>getComputedStyle(node).boxShadow),'none');
  assert.equal(await picked.locator('strong').evaluate(node=>node.scrollWidth<=node.clientWidth),true,'Source name fits on one line');
  assert.equal(await picked.locator('small').first().evaluate(node=>getComputedStyle(node).whiteSpace),'nowrap');
  assert.deepEqual(errors,[]);
  console.log('shared title browser contract: ok');
 }finally{await browser.close();await vite.close();}
})().catch(error=>{console.error(error);process.exit(1);});
