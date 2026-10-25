// UI/API fixtures verify reader lifecycle; these are not neural quality tests.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),directory=path.join(root,'test-output');let browser,vite,debugPage;
(async()=>{
 await fs.mkdir(directory,{recursive:true});
 await fs.writeFile(path.join(directory,'processing-harness.html'),'<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/test-output/processing-harness.jsx"></script></html>');
 await fs.writeFile(path.join(directory,'processing-harness.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import MangaReader from'/src/MangaReader.jsx';import'/src/styles.css';
 const canvas=document.createElement('canvas');canvas.width=128;canvas.height=180;const ctx=canvas.getContext('2d');ctx.fillStyle='#faf8f1';ctx.fillRect(0,0,128,180);ctx.fillStyle='#242629';ctx.fillText('HELLO',25,70);const blob=await new Promise(r=>canvas.toBlob(r));
 const url=URL.createObjectURL(blob);window.fixturePixels=canvas.toDataURL().split(',')[1];
 const bigger=document.createElement('canvas');bigger.width=256;bigger.height=360;bigger.getContext('2d').drawImage(canvas,0,0,256,360);window.fixtureUpscaledPixels=bigger.toDataURL().split(',')[1];
 const service={server:'https://processing.example',status:'connected',request:async(path,options={})=>{const response=await fetch('https://processing.example'+path,{method:options.method||'GET',body:options.body?JSON.stringify(options.body):undefined,signal:options.signal});if(!response.ok)throw Error('Backend fixture failed');return response.json();}};
 window.MEDIA_VAULT_CONFIG={importServerUrl:service.server};
 createRoot(document.getElementById('root')).render(<MangaReader item={{id:'chapter',category:'manga',name:'Манга · проверка обработки',onlinePages:[url]}} catalog={{items:[]}} userId="processing-test" libraryId="fixture" onClose={()=>{}} readerService={service}/>);
 `);
 const {createServer}=await import('vite');vite=await createServer({root,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 for(const width of [360,1280]){
  const context=await browser.newContext({viewport:{width,height:850}}),page=await context.newPage();debugPage=page;let submitted=[],cancelled=0,hold=false;const requests=new Map();page.on('pageerror',e=>console.error('BROWSER',e.message));
  await page.route('https://processing.example/**',async route=>{
   const request=route.request(),url=new URL(request.url());
   let payload={};
   if(url.pathname==='/reader/processing')payload={lmt:{ready:true},upscale:{ready:true,models:[{id:'fixture.pth',name:'MangaJaNai fixture'}]}};
   else if(url.pathname==='/reader/jobs'){submitted.push(request.postDataJSON());payload={id:'task'+submitted.length};requests.set(payload.id,submitted.at(-1).options);}
   else if(url.pathname.endsWith('/cancel')){cancelled++;payload={state:'cancelling'};}
   else if(requests.get(url.pathname.split('/').at(-1))?.operation==='detect')payload={state:'done',result:{boxes:[{x1:20,y1:40,x2:110,y2:110,confidence:1}],regions:[]}};
   else if(requests.get(url.pathname.split('/').at(-1))?.operation==='translate')payload={state:'done',result:{translations:['Привет'],sourceTexts:['HELLO'],gateSkip:[null],regions:[]}};
   else if(requests.get(url.pathname.split('/').at(-1))?.operation==='inpaint')payload={state:'done',result:{cleanedImage:await page.evaluate(()=>window.fixturePixels),regions:[]}};
   else payload=hold?{state:'running',status:'Проверяем отмену'}:{state:'done',result:{renderedImage:await page.evaluate(upscale=>upscale?window.fixtureUpscaledPixels:window.fixturePixels,requests.get(url.pathname.split('/').at(-1))?.upscale),renderedMime:'image/png',regions:[],upscale:{model:'MangaJaNai fixture',width:256,height:360,scale:2}}};
   await route.fulfill({contentType:'application/json',body:JSON.stringify(payload)});
  });
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/processing-harness.html');
  await page.getByRole('button',{name:'Настройки читалки',exact:true}).click();
  await page.getByText('MangaJaNai · качество страниц',{exact:true}).click();
  await page.getByLabel('Включить MangaJaNai',{exact:true}).check();
  await page.getByText('MangaJaNai fixture · 256 × 360',{exact:true}).waitFor();
  assert.equal(submitted.length,1);assert.equal(submitted[0].options.upscale,true);assert.equal(submitted[0].options.translate,false);
  assert.ok(!('host' in submitted[0].options));
  hold=true;await page.getByLabel('Размер тайла MangaJaNai').selectOption('128');
  await page.getByText('Проверяем отмену',{exact:true}).waitFor();
  await page.getByLabel('Включить MangaJaNai',{exact:true}).uncheck();
  await page.waitForFunction(()=>document.querySelector('.reader-page img')?.src.startsWith('blob:'));
  await page.getByText('Libre Manga Translator · модели и режим',{exact:true}).click();
  await page.getByLabel('Движок перевода манги').selectOption('backend');
  await page.getByLabel('Разрешить загрузку моделей на backend',{exact:true}).check();
  hold=false;await page.getByRole('button',{name:'Перевести · LMT',exact:true}).click();
  await page.getByText('LMT · обработка на твоём backend',{exact:true}).waitFor();
  await page.getByText('MangaJaNai fixture · 256 × 360',{exact:true}).waitFor();
  assert.equal(submitted.at(-1).options.translate,true);assert.equal(submitted.at(-1).options.upscale,false);assert.ok(cancelled>=1);
  if(!await page.getByLabel('Включить MangaJaNai',{exact:true}).isVisible())await page.getByText('MangaJaNai · качество страниц',{exact:true}).click();
  await page.getByLabel('Включить MangaJaNai',{exact:true}).check();
  await page.getByText('LMT · обработка на твоём backend',{exact:true}).waitFor();
  assert.equal(submitted.at(-1).options.upscale,true);
  await page.getByRole('button',{name:'Закрыть настройки читалки',exact:true}).click();
  await page.getByRole('button',{name:'Редактор LMT · области и текст',exact:true}).click();
  const editor=page.frameLocator('iframe[title="Редактор Libre Manga Translator"]');
  await editor.getByRole('button',{name:'Confirm',exact:true}).click();
  await editor.getByTitle('Edit text translations').click();
  await editor.locator('textarea').first().fill('Исправленная реплика');
  await editor.getByTitle('Apply changes & update translation',{exact:true}).click();
  await editor.getByRole('button',{name:'Применить в читалке',exact:true}).click();
  await page.locator('iframe[title="Редактор Libre Manga Translator"]').waitFor({state:'detached'});
  await page.getByRole('button',{name:/Перевод · 1 реплик/}).waitFor();
  assert.ok(submitted.some(r=>r.options.operation==='inpaint'));
  const editorUpscales=submitted.filter(r=>r.options.upscale&&!r.options.translate);
  assert.ok(editorUpscales.length>=2,'the editor upscales the cleaned page before typesetting');
  assert.equal(editorUpscales.at(-1).options.tile,128);
  await page.getByText('MangaJaNai fixture · 256 × 360',{exact:true}).waitFor();
  await page.waitForFunction(()=>document.querySelector('.reader-page img')?.naturalWidth===256);
  await page.screenshot({path:path.join(directory,'reader-processing-'+width+'.png'),fullPage:true});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await context.close();console.log('PASS backend reader processing, model controls and cancellation at '+width+'px');
 }
})().catch(async error=>{console.error(error);if(debugPage&&!debugPage.isClosed()){console.error('FRAMES',await Promise.all(debugPage.frames().map(f=>f.locator('body').innerText().then(t=>t.slice(0,1800)).catch(()=>''))));await debugPage.screenshot({path:path.join(directory,'reader-editor-failure.png'),fullPage:true});}process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const file of ['processing-harness.html','processing-harness.jsx'])await fs.rm(path.join(directory,file),{force:true});});
