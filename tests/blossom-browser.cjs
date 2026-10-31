// Actual React integration with fixture catalog responses. No external account or ML inference.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {chromium}=require('playwright'),navigateApp=require('./app-navigation.cjs');
const ROOT=path.resolve(__dirname,'..'),dir=path.join(ROOT,'.codex-local/test-output/blossom');let browser,vite;
(async()=>{
 await fs.mkdir(dir,{recursive:true});const html=path.join(ROOT,'test-output/blossom-harness.html'),jsx=html.replace('.html','.jsx');
 await fs.writeFile(html,'<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="scene-root"></div><div id="root"></div><script type="module" src="/test-output/blossom-harness.jsx"></script></html>');
 await fs.writeFile(jsx,`import React from 'react';import {createRoot} from 'react-dom/client';import '/src/styles.css';import '/src/title-page.css';import '/src/import-layout.css';import '/src/discovery-polish.css';import App from '/src/App.jsx';window.MEDIA_VAULT_CONFIG={};createRoot(document.getElementById('root')).render(<App/>);`);
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 for(const width of [360,768,1280]){
  const context=await browser.newContext({viewport:{width,height:960},reducedMotion:'reduce',serviceWorkers:'block'});context.setDefaultTimeout(15000);
  await context.addInitScript(()=>localStorage.setItem('mediavault_privacy_v1',JSON.stringify({version:1,chosen:true,remember:false})));
  await context.route('https://**',route=>{
   const kitsu=route.request().url().startsWith('https://kitsu.io/');
   return route.fulfill({headers:{'access-control-allow-origin':'*'},contentType:'application/json',body:JSON.stringify(kitsu?{data:[{id:'20',type:'anime',attributes:{canonicalTitle:'Naruto',titles:{en:'Naruto'},synopsis:'Описание из каталога для проверки интерфейса.',subtype:'TV',episodeCount:220,startDate:'2002-10-03',ageRating:'PG'}}]}:{data:{Page:{media:[]}}})});
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const palette=()=>page.evaluate(()=>Object.fromEntries(['canvas','surface','surface-raised','blossom','petal'].map(k=>[k,document.documentElement.style.getPropertyValue('--color-'+k)])));
  const fits=async name=>{await page.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth+1,{},{timeout:2000}).catch(async()=>{console.error(await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,15).map(e=>({c:e.className,w:e.getBoundingClientRect().width,r:e.getBoundingClientRect().right}))));await page.screenshot({path:path.join(dir,'overflow-'+width+'.png'),fullPage:true});});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' fits '+width);};
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/blossom-harness.html');
  await page.locator('.hero-stage h1').waitFor();await page.evaluate(()=>document.fonts.ready);await fits('Home');
  assert.equal((await palette()).blossom,'#ee3c35');assert.equal(await page.locator('.category-grid .producer-card').count(),5);
  await page.screenshot({path:path.join(dir,'home-'+width+'.png'),fullPage:true});
  await page.locator('#profileBtn').click();await page.locator('#appearanceSettings').waitFor();
  await page.getByRole('button',{name:'Бордо',exact:true}).click();await page.waitForFunction(()=>document.documentElement.style.getPropertyValue('--color-blossom')!=='#ee3c35');
  const burgundy=await palette();assert.notEqual(burgundy.surface,'#251b20');
  await page.reload();await page.locator('#appearanceSettings').waitFor();assert.deepEqual(await palette(),burgundy);
  await page.getByRole('checkbox',{name:/Палитра из фона/}).check();
  const image=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=c.height=32;const ctx=c.getContext('2d');ctx.fillStyle='#205de0';ctx.fillRect(0,0,32,32);return c.toDataURL('image/png').split(',')[1];});
  await page.getByLabel('Изображение фона',{exact:true}).setInputFiles({name:'blue.png',mimeType:'image/png',buffer:Buffer.from(image,'base64')});
  await page.getByRole('button',{name:'Вернуть Blossom',exact:true}).waitFor();
  await page.waitForFunction(()=>{const hex=document.documentElement.style.getPropertyValue('--color-blossom');return parseInt(hex.slice(5,7),16)>parseInt(hex.slice(1,3),16);});
  const blue=await palette();assert.notEqual(blue.canvas,burgundy.canvas);
  await page.reload();await page.getByRole('button',{name:'Вернуть Blossom',exact:true}).waitFor();await page.waitForFunction(seed=>document.documentElement.style.getPropertyValue('--color-blossom')===seed,blue.blossom);
  await page.evaluate(()=>dispatchEvent(new CustomEvent('mediavault:backdrop-palette',{detail:'#d82a3c'})));
  await page.waitForFunction(seed=>document.documentElement.style.getPropertyValue('--color-surface')!==seed,blue.surface);
  await page.getByRole('button',{name:'Сбросить оформление',exact:true}).click();assert.equal((await palette()).canvas,'#11191c');
  await page.evaluate(()=>dispatchEvent(new CustomEvent('mediavault:backdrop-palette',{detail:'#0000ff'})));assert.equal((await palette()).blossom,'#ee3c35','Manual theme ignores changing title backgrounds');
  await page.getByRole('button',{name:'Вернуть Blossom',exact:true}).click();await fits('Profile');await page.screenshot({path:path.join(dir,'profile-'+width+'.png'),fullPage:true});
  await page.keyboard.press('Control+k');const dialog=page.getByRole('dialog',{name:'Поиск в библиотеке'});await dialog.waitFor();
  assert.equal(await page.getByRole('combobox',{name:'Поиск произведения'}).evaluate(e=>document.activeElement===e),true);
  await page.getByRole('combobox',{name:'Поиск произведения'}).fill('Naruto');await dialog.getByRole('option').first().waitFor();await fits('Search');
  await page.screenshot({path:path.join(dir,'search-'+width+'.png')});await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
  await navigateApp(page,'Библиотека');await page.locator('.catalog-grid .anime-card').first().waitFor();await fits('Catalog');
  await page.screenshot({path:path.join(dir,'catalog-'+width+'.png'),fullPage:true});
  const poster=await page.locator('.catalog-grid .anime-card').first().boundingBox();assert.ok(Math.abs(poster.width/poster.height-.75)<.01,'Supplied poster ratio');
  await page.keyboard.press('Control+k');await page.getByRole('combobox',{name:'Поиск произведения'}).fill('Naruto');await page.getByRole('dialog').getByRole('option').first().waitFor();await page.keyboard.press('Enter');await page.locator('.title-hero h1').waitFor();
  await fits('Title');await page.screenshot({path:path.join(dir,'title-'+width+'.png'),fullPage:true});
  assert.deepEqual(errors,[]);await context.close();console.log('PASS Blossom '+width+'px: theme persistence, wallpaper, background colors, keyboard search and real catalog navigation');
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const name of ['blossom-harness.html','blossom-harness.jsx'])await fs.rm(path.join(ROOT,'test-output',name),{force:true});});
