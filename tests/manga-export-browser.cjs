// Real IndexedDB encryption, React controls and binary upload; API is a fixture.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'test-output');let browser,vite;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});
 await fs.writeFile(path.join(DIR,'manga-export-harness.html'),'<meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/test-output/manga-export-harness.jsx"></script>');
 await fs.writeFile(path.join(DIR,'manga-export-harness.jsx'),`
 import React from 'react';import{createRoot}from'react-dom/client';
 import ReaderChapterExport from '/src/ReaderChapterExport.jsx';import{translationCacheKey,putTranslation,cachedChapterPages,clearTranslations}from'/src/translation-cache.js';import{bytesBase64}from'/src/manga-translation.js';import{createImportClient}from'/src/import-service.js';import'/src/styles.css';
 window.requests=[];window.downloads=[];HTMLAnchorElement.prototype.click=function(){window.downloads.push(this.download)};
 const scope='export-browser:online',chapter='online:https://mangapill.com/chapters/fixture';
 const canvas=document.createElement('canvas');canvas.width=100;canvas.height=150;canvas.getContext('2d').fillRect(0,0,100,150);const blob=await new Promise(r=>canvas.toBlob(r));
 await clearTranslations(scope);
 for(let i=0;i<2;i++){const key=await translationCacheKey(blob,{engine:'direct',directModel:'gemini-3.5-flash-lite'},scope);await putTranslation(key+':chapter='+encodeURIComponent(chapter)+':page='+i+':render-v12:fast:auto',scope,{renderedImage:await blob.arrayBuffer(),renderedMime:'image/png'},{chapter,index:i,total:2,url:'https://mangapill.com/chapters/fixture'});}
 window.checkCache=()=>cachedChapterPages({scope,chapter,total:2});
 const service={session:{serverVersion:50},server:'https://vm.example',request:async(path,o={})=>{window.requests.push({path,method:o.method,body:o.body instanceof Blob?'BINARY':o.body});if(path==='/online/exports')return{id:'job',state:'staging'};if(path.endsWith('/start'))return{id:'job',state:'done',downloadUrl:'/online/exports/file/token',filename:'Test.cbz'};return{id:'job',state:'staging'}}};
 window.checkBinary=async()=>{let outgoing;const client=createImportClient('https://vm.example',()=>null,async(url,options)=>{outgoing=options;return{ok:true,json:async()=>({ok:true})}});await client.request('/upload',{method:'PUT',body:blob,auth:false});return{binary:outgoing.body instanceof Blob,type:outgoing.headers['Content-Type'],size:outgoing.body.size}};
 createRoot(document.getElementById('root')).render(<main style={{padding:12}}><ReaderChapterExport scope={scope} total={2} item={{id:chapter,name:'Тестовая глава',episode:1,sourceURL:'https://mangapill.com/chapters/fixture'}} settings={{directInput:'vision',directModel:'gemini-3.5-flash-lite',directBatchPages:2,inpaint:'fast',font:'auto',language:'Japanese',direction:'rtl',directDetector:'rtdetr'}} service={service}/></main>);
 `);
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium'});
 for(const width of [360,1280]){
  const context=await browser.newContext({viewport:{width,height:900}}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/manga-export-harness.html');
  await page.getByRole('button',{name:'Скачать главу с переводом'}).click();await page.getByText('Готово в кэше: 2 / 2 страниц.').waitFor();
  const cached=await page.evaluate(async()=>{const value=await checkCache();return{complete:value.complete,count:value.pages.length,hash:value.pages[0].sourceHash}});assert.equal(cached.complete,true);assert.equal(cached.count,2);assert.match(cached.hash,/^[a-f0-9]{64}$/);
  const binary=await page.evaluate(()=>checkBinary());assert.equal(binary.binary,true);assert.equal(binary.type,'application/octet-stream');
  await page.getByRole('button',{name:'Сохранить на устройство',exact:true}).click();await page.getByText('Файл передан браузеру для сохранения.').waitFor();
  const calls=await page.evaluate(()=>requests);assert.equal(calls[0].body.manga.cached.length,2);assert.equal(calls[0].body.manga.chapters[0].pageCount,2);assert.equal(calls.filter(c=>c.method==='PUT'&&c.body==='BINARY').length,2);assert.equal(calls[0].body.manga.mode,'cached');assert.deepEqual(await page.evaluate(()=>downloads),['Test.cbz']);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);
  await page.screenshot({path:path.join(DIR,'manga-export-'+width+'.png')});await context.close();
 }
 console.log('PASS encrypted cached chapter → binary staged export, format controls and mobile layout');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{await browser?.close();await vite?.close();for(const f of ['manga-export-harness.html','manga-export-harness.jsx'])await fs.rm(path.join(DIR,f),{force:true})});
