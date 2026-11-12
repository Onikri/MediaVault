// Real React/Radix/motion save sheet, real page encoding and ZIP/PDF writers.
// The translator is a fixture (cached page, fresh page, page with a refused bubble).
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'test-output');let browser,vite;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});
 await fs.writeFile(path.join(DIR,'manga-export-harness.html'),'<meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/test-output/manga-export-harness.jsx"></script>');
 await fs.writeFile(path.join(DIR,'manga-export-harness.jsx'),`
 import React from 'react';import{createRoot}from'react-dom/client';import ReaderChapterExport from '/src/ReaderChapterExport.jsx';import'/src/styles.css';import'/src/blossom/tokens.css';
 window.downloads=[];window.opened=[];HTMLAnchorElement.prototype.click=function(){window.downloads.push({name:this.download,href:this.href});};
 const page=async(n,type='image/png')=>{const c=new OffscreenCanvas(60,90),x=c.getContext('2d');x.fillStyle='#fff';x.fillRect(0,0,60,90);x.fillStyle='#000';x.fillText(String(n),20,40);return c.convertToBlob({type});};
 const total=5;
 const source={live:true,blob:i=>page(i+1),render:async(i,blob,signal,status)=>{status({phase:'translating'});await new Promise(r=>setTimeout(r,40));
  if(i===0)return {renderedImage:await (await page(1,'image/webp')).arrayBuffer(),cacheHit:true};
  const bitmap=await createImageBitmap(await page(i+1));return {renderedBitmap:bitmap,unresolvedRegions:i===3?['P4_B1']:[]};},state:()=>({translated:4,partial:1})};
 const readiness=async()=>({total,translated:4,partial:1,pages:Uint8Array.from([1,1,1,3,1]),canTranslate:true});
 createRoot(document.getElementById('root')).render(<main style={{padding:12}}><ReaderChapterExport title="fixture" chapterLabel="Глава 3 · 5 страниц" fileName="Тестовая манга · Глава 3" total={total} createSource={async()=>source} readiness={readiness} onOpenPage={i=>window.opened.push(i)} storageKey="export-browser"/></main>);
 `);
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined});
 for(const width of [360,1280]){
  const context=await browser.newContext({viewport:{width,height:800}}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/manga-export-harness.html');
  await page.getByRole('button',{name:'Скачать главу с переводом'}).click();
  await page.getByText('5 из 5 переведены · 1 с пропусками',{exact:true}).waitFor();
  for(const format of ['PDF','CBZ']){
   await page.getByRole('radio',{name:format,exact:true}).click();
   await page.getByRole('button',{name:'Сохранить главу',exact:true}).click();
   await page.getByRole('heading',{name:'Глава сохранена'}).waitFor();
   const file=await page.evaluate(async()=>{const d=downloads.at(-1),bytes=new Uint8Array(await (await fetch(d.href)).arrayBuffer()),text=new TextDecoder('latin1').decode(bytes);return {name:d.name,head:text.slice(0,8),entries:text.startsWith('PK')?new DataView(bytes.buffer).getUint16(text.lastIndexOf('PK\x05\x06')+10,true):(text.match(/\/Type \/Page /g)||[]).length};});
   assert.equal(file.name,'Тестовая манга · Глава 3 · RU.'+format.toLowerCase());assert.equal(file.entries,5);assert.equal(file.head.slice(0,format==='PDF'?5:2),format==='PDF'?'%PDF-':'PK');
   if(format==='PDF'){await page.getByRole('button',{name:'Готово',exact:true}).click();await page.getByRole('button',{name:'Скачать главу с переводом'}).click();}
  }
  await page.getByText('1 страница сохранена с пропусками перевода').waitFor();
  assert.match(await page.locator('.reader-save-problems li').innerText(),/Стр\. 4[\s\S]*1 реплика без перевода/);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(DIR,'manga-export-'+width+'.png')});
  await page.getByRole('button',{name:'Открыть',exact:true}).click();assert.deepEqual(await page.evaluate(()=>opened),[3]);
  assert.deepEqual(errors,[]);await context.close();
 }
 console.log('PASS device-side chapter save: cached/rendered/partial pages → CBZ and PDF, problem list and mobile layout');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{await browser?.close();await vite?.close();for(const f of ['manga-export-harness.html','manga-export-harness.jsx'])await fs.rm(path.join(DIR,f),{force:true})});
