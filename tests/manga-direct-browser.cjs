// Real English contour detector (or DIRECT_DETECTOR=rtdetr), Canvas/FontFace and encrypted IndexedDB.
// Google responses are explicit fixtures: this is not a Google latency benchmark.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');let browser,vite;
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(root,'test-output');await fs.mkdir(out,{recursive:true});
 await fs.writeFile(path.join(out,'manga-direct.html'),'<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/test-output/manga-direct.jsx"></script></html>');
 await fs.writeFile(path.join(out,'manga-direct.jsx'),`
import React from'react';import{createRoot}from'react-dom/client';import JSZip from'jszip';import MangaReader from'/src/MangaReader.jsx';import'/src/styles.css';
window.calls=[];window.actualTimings=[];
const c=document.createElement('canvas');c.width=900;c.height=1100;const x=c.getContext('2d');x.fillStyle='#eee6d8';x.fillRect(0,0,900,1100);x.font='bold 25px sans-serif';x.textAlign='center';
for(const [n,b]of[[70,80,360,250],[490,115,790,300],[85,440,390,620],[480,730,800,940]].entries()){x.fillStyle='white';x.beginPath();x.ellipse((b[0]+b[2])/2,(b[1]+b[3])/2,(b[2]-b[0])/2,(b[3]-b[1])/2,0,0,Math.PI*2);x.fill();x.strokeStyle='#111';x.lineWidth=2;x.stroke();x.fillStyle='#111';const lines=[['I DO NOT','BELIEVE IN','ALIENS.'],['WAIT! DO NOT','OPEN THAT','DOOR.'],['MOMO, ARE YOU','ALL RIGHT?'],['WE WILL MEET','AGAIN','TOMORROW.']][n];for(const [i,line]of lines.entries())x.fillText(line,(b[0]+b[2])/2,(b[1]+b[3])/2+(i-(lines.length-1)/2)*34);}
const blob=await new Promise(resolve=>c.toBlob(resolve,'image/png'));
const zip=new JSZip();zip.file('1.png',blob);zip.file('2.png',blob);const chapter=await zip.generateAsync({type:'blob'});
const item={id:'direct-chapter',name:'Быстрый перевод · проверка',category:'manga',collectionId:'title',translationInfo:{language:'en'}};
createRoot(document.getElementById('root')).render(<MangaReader item={item} catalog={{items:[item]}} userId="direct-test" libraryId="library" readWhole={async()=>chapter} onClose={()=>{}}/>);
`);
 const{createServer}=await import('vite');vite=await createServer({root,logLevel:'error',plugins:[{name:'built-lmt-for-test',configureServer(server){server.middlewares.use(async(req,res,next)=>{
  const pathname=new URL(req.url,'http://fixture').pathname,at=pathname.indexOf('/lmt/');if(at<0)return next();
  const file=path.resolve(root,'dist/lmt',pathname.slice(at+5));if(!file.startsWith(path.join(root,'dist/lmt/')))return next();
  try{const data=await fs.readFile(file);res.setHeader('Content-Type',file.endsWith('.wasm')?'application/wasm':file.endsWith('.js')||file.endsWith('.mjs')?'text/javascript':file.endsWith('.html')?'text/html':'application/octet-stream');res.end(data);}catch{next();}
 });}}],server:{host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const metrics=[];
 for(const width of[390,1366]){
  const context=await browser.newContext({viewport:{width,height:1000}}),page=await context.newPage(),errors=[],requests=[],modelDownloads=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(90000);
  await page.addInitScript(detector=>{
   if(!localStorage.getItem('mv_lmt_settings:direct-test'))localStorage.setItem('mv_lmt_settings:direct-test',JSON.stringify({version:7,engine:'direct',directModel:'gemma-4-26b-a4b-it',directDetector:detector,inpaint:'fast',font:'auto',allowDownloads:true}));
   localStorage.setItem('mediavault_reader_v2:direct-test',JSON.stringify({translate:true,mode:'pages',direction:'rtl',preload:2}));
   const NativeWorker=window.Worker;window.actualTimings=[];window.Worker=class extends NativeWorker{constructor(...args){super(...args);this.addEventListener('message',e=>{if(e.data.result?.timings)window.actualTimings.push(e.data.result.timings);});}};
  },process.env.DIRECT_DETECTOR||'en-fast');
  await page.route('**/*detector-v4-s_int8.onnx*',async route=>{modelDownloads.push('rtdetr');let bytes;try{bytes=await fs.readFile(path.join(out,'quality-models/rtdetr.onnx'));}catch{const response=await fetch(route.request().url(),{signal:AbortSignal.timeout(45000)});assert.ok(response.ok);bytes=Buffer.from(await response.arrayBuffer());}return route.fulfill({contentType:'application/octet-stream',headers:{'access-control-allow-origin':'*'},body:bytes});});
  await page.route('https://generativelanguage.googleapis.com/**',async route=>{
   const request=route.request();if(request.method()==='OPTIONS')return route.fulfill({status:204,headers:{'access-control-allow-origin':'*','access-control-allow-headers':'*'}});
   const body=request.postDataJSON();requests.push({url:request.url(),key:request.headers()['x-goog-api-key'],body});
   const ids=body.contents[0].parts.filter(p=>p.text?.startsWith('P')).flatMap(p=>p.text.split(': ')[1].split(','));
   const rows=ids.map((id,i)=>({id,ru:['Я не верю в инопланетян.','Стой! Не открывай эту дверь.','Момо, ты в порядке?','Мы снова встретимся завтра.'][i%4],f:i%3,k:0}));
   // Hold the HTTP response until the live status has been checked.
   await new Promise(resolve=>{page.releaseGoogle=resolve;});
   await route.fulfill({headers:{'access-control-allow-origin':'*'},json:{candidates:[{finishReason:'STOP',content:{parts:[{text:JSON.stringify(rows)}]}}],usageMetadata:{promptTokenCount:1000,candidatesTokenCount:150}}});
  });
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/manga-direct.html');
  await page.getByLabel('Настройки читалки',{exact:true}).click();assert.equal(await page.getByLabel('Где обрабатывать перевод').inputValue(),'direct');
  assert.equal(await page.getByLabel('Ключ Google AI Studio',{exact:true}).count(),0);assert.equal(await page.getByLabel('OCR LMT').count(),0);assert.equal(await page.getByLabel('Восстановление фона LMT').count(),0);
  await page.getByLabel('Личный ключ быстрого перевода').fill('fixture-personal-do-not-save');await page.getByRole('button',{name:'Применить личный ключ',exact:true}).click();await page.getByLabel('Закрыть настройки читалки',{exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.reader-live-progress')?.textContent.includes('Напрямую в Google')).catch(async error=>{console.log('Direct diagnostic',JSON.stringify({status:await page.locator('.reader-live-progress').innerText(),models:modelDownloads,requests:requests.length,errors}));throw error;});
  await new Promise((resolve,reject)=>{const until=Date.now()+10000;const poll=()=>requests.length?resolve():Date.now()>until?reject(Error('Google request did not arrive')):setTimeout(poll,25);poll();});
  assert.equal(modelDownloads.length,process.env.DIRECT_DETECTOR==='rtdetr'?1:0);assert.equal(requests.length,1);assert.equal(requests[0].key,'fixture-personal-do-not-save');assert.ok(!JSON.stringify(requests[0].body).includes('fixture-personal-do-not-save'));assert.match(requests[0].body.contents[0].parts[0].text,/RIGHT TO LEFT/);assert.equal(requests[0].body.generationConfig.thinkingConfig.thinkingLevel,'MINIMAL');assert.equal(requests[0].body.contents[0].parts.filter(p=>p.inlineData).length,2);
  await page.screenshot({path:path.join(out,'manga-direct-wait-'+width+'.png')});page.releaseGoogle();
  await page.waitForFunction(()=>document.querySelector('canvas.reader-translated-overlay')?.dataset.ready==='true');assert.equal(await page.locator('.translation-marker').count(),0);
  assert.match(await page.locator('.reader-live-progress').innerText(),/Google [0-9]/);assert.equal(await page.evaluate(()=>Object.values(localStorage).some(v=>v.includes('fixture-personal-do-not-save'))),false);assert.equal(await page.evaluate(()=>Object.values(sessionStorage).some(v=>v.includes('fixture-personal-do-not-save'))),false);
  const difference=await page.evaluate(()=>{const box=document.querySelector('.reader-page-image'),img=box.querySelector('img'),translated=box.querySelector('canvas'),canvas=document.createElement('canvas');canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;const ctx=canvas.getContext('2d');ctx.drawImage(img,0,0);const a=ctx.getImageData(0,0,canvas.width,canvas.height).data;ctx.drawImage(translated,0,0);const b=ctx.getImageData(0,0,canvas.width,canvas.height).data;let changed=0;for(let n=0;n<a.length;n+=4)if(Math.abs(a[n]-b[n])>40)changed++;return changed;});assert.ok(difference>1500,'Actual glyphs must be erased/replaced');
  metrics.push({width,provenance:'Actual '+(process.env.DIRECT_DETECTOR==='rtdetr'?'RT-DETR WASM':'English contour detector')+' and Canvas worker. Google response is a fixture, not an API speed/quality measurement.',modelDownloads:modelDownloads.length,googleRequests:requests.length,workerTimings:await page.evaluate(()=>window.actualTimings),changedPixels:difference});
  await page.screenshot({path:path.join(out,'manga-direct-ready-'+width+'.png')});
  await page.keyboard.down('Alt');assert.equal(await page.locator('canvas.reader-translated-overlay').evaluate(e=>e.style.opacity),'0');await page.keyboard.up('Alt');
  await page.getByRole('button',{name:'Вперёд →',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[data-page="1"] canvas.reader-translated-overlay')?.dataset.ready==='true');assert.equal(requests.length,1,'Prefetched second page must not call Google again');
  await page.reload();await page.waitForFunction(()=>document.querySelector('canvas.reader-translated-overlay')?.dataset.ready==='true');assert.equal(requests.length,1,'Reload must work from encrypted JSON without a saved key');
  assert.deepEqual(errors,[]);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await context.close();console.log('PASS direct Google contract, actual detection, cleanup/Cyrillic worker, encrypted cache and mobile UI '+width);
 }
 await fs.writeFile(path.join(out,'manga-direct-browser-metrics.json'),JSON.stringify(metrics,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const name of['manga-direct.html','manga-direct.jsx'])await fs.rm(path.resolve(__dirname,'../test-output/'+name),{force:true});});
