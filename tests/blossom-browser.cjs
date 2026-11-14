// Actual React integration with fixture catalog responses. No external account or ML inference.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {chromium}=require('playwright'),navigateApp=require('./app-navigation.cjs');
const ROOT=path.resolve(__dirname,'..'),dir=path.join(ROOT,'.codex-local/test-output/blossom');let browser,vite;
(async()=>{
 await fs.mkdir(dir,{recursive:true});const html=path.join(ROOT,'test-output/blossom-harness.html'),jsx=html.replace('.html','.jsx');
 await fs.writeFile(html,'<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="scene-root"></div><div id="root"></div><script type="module" src="/test-output/blossom-harness.jsx"></script></html>');
 await fs.writeFile(jsx,`import React from 'react';import {createRoot} from 'react-dom/client';import '/src/styles.css';import '/src/title-page.css';import '/src/import-layout.css';import '/src/discovery-polish.css';import '/src/site-layout.css';import '/src/site-mobile.css';import App from '/src/App.jsx';window.MEDIA_VAULT_CONFIG={importServerUrl:"https://fixture.example"};createRoot(document.getElementById('root')).render(<App/>);`);
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 for(const width of [360,768,1280]){
  const context=await browser.newContext({viewport:{width,height:960},reducedMotion:'reduce',serviceWorkers:'block'});context.setDefaultTimeout(15000);
  await context.addInitScript(()=>localStorage.setItem('mediavault_privacy_v1',JSON.stringify({version:1,chosen:true,remember:false})));
  await context.route(/^https:\/\//,route=>{
   const url=new URL(route.request().url()),cors={'access-control-allow-origin':'*'};
   if(url.pathname==='/artwork'||url.hostname==='art.test')return route.fulfill({headers:cors,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a+kkAAAAASUVORK5CYII=','base64')});
   const anime={mal_id:20,title:'Naruto',russian:'Наруто',synopsis:'',type:'TV',episodes:220,year:2002,score:8,images:{jpg:{large_image_url:'https://art.test/naruto.png'}},aired:{from:'2002-10-03'}};
   const shiki={id:20,russian:'Наруто',name:'Naruto',kind:'tv',episodes:220,aired_on:'2002-10-03',image:{original:'https://art.test/naruto.png'},description:'Описание из каталога для проверки интерфейса.'};
   let data={data:[]};
   if(url.pathname.endsWith('/anime-home'))data={current:[anime],popular:[anime],season:{label:'Тестовый сезон'}};
   else if(url.pathname.includes('kitsu.io')||url.hostname==='kitsu.io')data={data:[]};
   else if(url.hostname==='openlibrary.org')data={docs:[{key:'/works/OL123W',title:'Naruto · книга',cover_i:1}]};
   else if(url.pathname.includes('/shikimori')||url.hostname.startsWith('shikimori'))data=url.searchParams.has('identity')?shiki:[{...shiki,description:''}];
   else if(url.pathname.includes('/jikan')||url.hostname==='api.jikan.moe'||url.hostname==='api.tenrai.org')data={data:url.searchParams.get('path')?.endsWith('/full')?anime:[anime]};
   else if(url.pathname.includes('anilist')||url.hostname==='graphql.anilist.co')data={data:{Page:{media:[]}}};
   return route.fulfill({headers:cors,contentType:'application/json',body:JSON.stringify(data)});
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const palette=()=>page.evaluate(()=>Object.fromEntries(['canvas','surface','surface-raised','blossom','petal'].map(k=>[k,document.documentElement.style.getPropertyValue('--color-'+k)])));
  const fits=async name=>{await page.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth+1,{},{timeout:2000}).catch(async()=>{console.error(await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,15).map(e=>({c:e.className,w:e.getBoundingClientRect().width,r:e.getBoundingClientRect().right}))));await page.screenshot({path:path.join(dir,'overflow-'+width+'.png'),fullPage:true});});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' fits '+width);};
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/blossom-harness.html');
  await page.locator('.hero-stage.is-revealed').waitFor();await page.locator('.home-discover .anime-cover img:not([data-placeholder])').first().waitFor();await page.evaluate(()=>document.fonts.ready);await fits('Home');
  const defaultDecoration=await page.locator('.hero-stage').first().evaluate(e=>getComputedStyle(e).backgroundColor);assert.equal((await palette()).blossom,'#ee3c35');assert.equal(await page.locator('.home-sections>button').count(),7);
  await page.screenshot({path:path.join(dir,'home-'+width+'.png'),fullPage:true});
  const topChrome=await page.locator('.blossom-navbar .header-inner').evaluate(e=>{const s=getComputedStyle(e);return {background:s.backgroundColor,border:s.borderTopWidth,shadow:s.boxShadow,before:getComputedStyle(e,'::before').content};});
  assert.equal(topChrome.background,'rgba(0, 0, 0, 0)');assert.equal(topChrome.border,'0px');assert.equal(topChrome.shadow,'none');assert.equal(topChrome.before,'none');
  if(width===1280){const header=page.locator('.blossom-navbar'),expanded=await header.boundingBox(),active=page.locator('.desktop-nav [aria-current="page"]');await active.hover();assert.equal(await active.evaluate(e=>getComputedStyle(e).backgroundColor),'rgba(0, 0, 0, 0)','Hover cannot paint a second active shape');const a=await active.boundingBox(),pill=await page.locator('.nav-glide').boundingBox();assert.ok(Math.abs(a.width-pill.width)<1&&Math.abs(a.height-pill.height)<1,'One pill follows the full active button');await page.evaluate(()=>scrollTo(0,180));await page.locator('.blossom-navbar.is-scrolled').waitFor();await page.waitForFunction(w=>document.querySelector('.blossom-navbar').getBoundingClientRect().width<w-20,expanded.width);assert.ok((await header.boundingBox()).width<expanded.width,'Navbar contracts on scroll');await page.screenshot({path:path.join(dir,'navbar-scrolled.png')});await page.evaluate(()=>scrollTo(0,0));await page.locator('.blossom-navbar:not(.is-scrolled)').waitFor();}
  assert.equal(await page.locator('.blossom-navbar .import-settings-trigger').count(),0,'connections no longer occupy navbar');
  await page.locator('#profileBtn').click();await page.locator('.profile-menu').getByRole('button',{name:'Настройки'}).click();await page.locator('.cc-nav').getByRole('button',{name:'Хранилище'}).click();await page.locator('.connection-settings-card .import-settings-trigger').waitFor();await page.locator('.cc-nav').getByRole('button',{name:'Оформление'}).click();await page.locator('#appearanceSettings').waitFor();
  await page.getByRole('button',{name:'Бордо',exact:true}).click();await page.waitForFunction(()=>document.documentElement.style.getPropertyValue('--color-blossom')!=='#ee3c35');
  const burgundy=await palette();assert.equal(burgundy.surface,'#19191e');
  await page.reload();await page.locator('.cc-nav').getByRole('button',{name:'Оформление'}).click();await page.locator('#appearanceSettings').waitFor();assert.deepEqual(await palette(),burgundy);
  await page.getByRole('checkbox',{name:/Палитра из фона/}).check();
  const image=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=c.height=32;const ctx=c.getContext('2d');ctx.fillStyle='#205de0';ctx.fillRect(0,0,32,32);return c.toDataURL('image/png').split(',')[1];});
  await page.getByLabel('Изображение фона',{exact:true}).setInputFiles({name:'blue.png',mimeType:'image/png',buffer:Buffer.from(image,'base64')});
  await page.getByRole('button',{name:'Вернуть Blossom',exact:true}).waitFor();
  await page.waitForFunction(()=>{const hex=document.documentElement.style.getPropertyValue('--color-blossom');return parseInt(hex.slice(5,7),16)>parseInt(hex.slice(1,3),16);});
  const blue=await palette();assert.notEqual(blue.canvas,burgundy.canvas);await page.locator('.brand.logo').click();await page.locator('.hero-stage').first().waitFor();await page.locator('.hero-stage.is-revealed').waitFor();assert.notEqual(await page.locator('.hero-stage').first().evaluate(e=>getComputedStyle(e).backgroundColor),defaultDecoration,'Decorative panels follow the whole palette');await page.screenshot({path:path.join(dir,'background-'+width+'.png'),fullPage:true});await page.locator('#profileBtn').click();await page.locator('.profile-menu').getByRole('button',{name:'Настройки'}).click();await page.locator('.cc-nav').getByRole('button',{name:'Оформление'}).click();await page.locator('#appearanceSettings').waitFor();
  await page.reload();await page.locator('.cc-nav').getByRole('button',{name:'Оформление'}).click();await page.getByRole('button',{name:'Вернуть Blossom',exact:true}).waitFor();await page.waitForFunction(seed=>document.documentElement.style.getPropertyValue('--color-blossom')===seed,blue.blossom);
  await page.evaluate(()=>dispatchEvent(new CustomEvent('mediavault:backdrop-palette',{detail:'#d82a3c'})));
  await page.waitForFunction(seed=>document.documentElement.style.getPropertyValue('--color-surface')!==seed,blue.surface);
  await page.getByRole('button',{name:'Сбросить оформление',exact:true}).click();assert.equal((await palette()).canvas,'#0c0c0f');
  await page.evaluate(()=>dispatchEvent(new CustomEvent('mediavault:backdrop-palette',{detail:'#0000ff'})));assert.equal((await palette()).blossom,'#ee3c35','Manual theme ignores changing title backgrounds');
  await page.getByRole('button',{name:'Вернуть Blossom',exact:true}).click();await fits('Profile');await page.screenshot({path:path.join(dir,'profile-'+width+'.png'),fullPage:true});
  const mobile=width<=1000;
  const trigger=page.locator(mobile?'.mobile-dock-search':'.header-center-search .header-search');
  const originalSearch=await trigger.boundingBox();
  assert.ok(Math.abs(originalSearch.width-(mobile?52:38))<1,'Search uses the dock circle on mobile and navbar circle on desktop');
  await trigger.click();const dialog=page.getByRole('dialog',{name:'Поиск в библиотеке'});await dialog.waitFor();
  assert.equal(await page.getByRole('combobox',{name:'Поиск произведения'}).evaluate(e=>document.activeElement===e),true);
  await page.getByRole('combobox',{name:'Поиск произведения'}).fill('Naruto');await dialog.getByRole('option').first().waitFor();await fits('Search');
  const position=await dialog.boundingBox(),field=await page.locator('.morph-search-bar').boundingBox();
  assert.ok(position.x>=0&&position.x+position.width<=width+1,'Search stays within viewport');
  assert.ok(field.width>originalSearch.width+30,'Search expands into a readable field');
  assert.equal(await dialog.locator('kbd').count(),0,'Search displays no hotkey legends');
  assert.equal(await page.locator('.morph-search-backdrop').count(),0,'Search has no blocking backdrop');
  if(mobile){
   assert.equal(await dialog.evaluate(e=>e.classList.contains('is-sheet')),true,'Dock search opens the mobile sheet');
   assert.ok(field.y>480&&field.y+field.height<=960,'Mobile field remains within thumb reach');
   assert.equal(await page.locator('.header-center-search').isVisible(),false,'Mobile has only the dock search entry');
   const panel=await dialog.locator('.morph-search-panel').boundingBox();
   assert.ok(panel.y+panel.height<=field.y+1,'Suggestions stack above the mobile field');
  }else{
   const inner=await page.locator('.blossom-navbar .header-inner').boundingBox();
   assert.ok(field.x>=inner.x-1&&field.x+field.width<=inner.x+inner.width+1,'Desktop search remains inside navbar');
   assert.ok(Math.abs(field.y+field.height/2-inner.y-inner.height/2)<2,'Desktop search stays vertically centered');
   const actions=await page.locator('.blossom-navbar .header-actions').boundingBox();
   assert.ok(field.x+field.width<=actions.x+2,'Desktop search does not overlap profile and music controls');
  }
  await page.screenshot({path:path.join(dir,'search-'+width+'.png')});await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('combobox',{name:'Поиск произведения'}).inputValue(),'','first Escape clears the query like MorphingSearchChips');
  await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
  if(width===1280){
   await page.evaluate(()=>scrollTo(0,480));
   await page.waitForFunction(()=>document.querySelector('.blossom-navbar')?.classList.contains('is-scrolled'));
   const compactSearch=await page.locator('.header-center-search .header-search').boundingBox();
   assert.ok(Math.abs(compactSearch.width-38)<1,'scrolled search restores the same circle');
   await page.keyboard.press('Control+k');const scrolled=page.getByRole('dialog',{name:'Поиск в библиотеке'});await scrolled.waitFor();
   const scrolledBar=await page.locator('.morph-search-bar').boundingBox(),scrolledInner=await page.locator('.blossom-navbar .header-inner').boundingBox();
   assert.ok(scrolledBar.x>=scrolledInner.x-1&&scrolledBar.x+scrolledBar.width<=scrolledInner.x+scrolledInner.width+1,'scrolled search remains inside the narrowed navbar');
   await page.keyboard.press('Escape');await scrolled.waitFor({state:'hidden'});await page.evaluate(()=>scrollTo(0,0));
  }
  await navigateApp(page,'Библиотека');await page.locator('.catalog-grid .anime-card').first().waitFor();await fits('Catalog');
  await page.screenshot({path:path.join(dir,'catalog-'+width+'.png'),fullPage:true});
  if(width===1280){await page.locator('.catalog-grid .anime-card').first().hover();const tip=page.getByRole('tooltip');await tip.waitFor();await tip.getByText('Описание из каталога для проверки интерфейса.',{exact:true}).waitFor();const box=await tip.boundingBox();assert.ok(box.x>=0&&box.y>=0&&box.y+box.height<=960,'Hydrated preview stays inside viewport');await page.screenshot({path:path.join(dir,'catalog-tooltip.png')});await page.mouse.move(0,0);}
  const catalogWidth=(await page.locator('.catalog-grid').boundingBox()).width;
  const poster=await page.locator('.catalog-grid .anime-card').first().boundingBox();assert.ok(Math.abs(poster.width/poster.height-.75)<.01,'Supplied poster ratio');
  for(const [label,selector] of [['Небольшие карточки','.catalog-layout-compact'],['Список','.catalog-layout-list'],['Таблица','.library-table'],['Крупные карточки','.catalog-grid']]){await page.getByRole('button',{name:label,exact:true}).click();await page.locator(selector).waitFor();await fits(label);}
  await navigateApp(page,'Коллекция');await page.locator('.collection-rail').waitFor();assert.equal(await page.getByRole('group',{name:'Вид библиотеки'}).evaluate(e=>getComputedStyle(e).borderRadius),'100px');assert.equal(await page.locator('.title-browser-toolbar .import-tabs').evaluate(e=>getComputedStyle(e).borderTopWidth),'0px');if(width===1280){await page.waitForFunction(expected=>{const e=document.querySelector('#libraryGrid');return e&&Math.abs(e.getBoundingClientRect().width-expected)<1;},catalogWidth,{timeout:5000});assert.ok(Math.abs((await page.locator('#libraryGrid').boundingBox()).width-catalogWidth)<1,'Catalog and collection allocate equal poster space');}
  const centered=await page.locator('.blossom-navbar .brand.logo').evaluate(e=>{const r=e.getBoundingClientRect(),p=e.closest('.header-inner').getBoundingClientRect();return Math.abs(r.y+r.height/2-p.y-p.height/2);});assert.ok(centered<.6,'Navbar has equal top and bottom spacing');
  await page.getByRole('button',{name:'Музыкальный плеер',exact:true}).click();await page.waitForFunction(()=>{const e=document.querySelector('.music-island');return e?.classList.contains('is-expanded')&&Math.abs(e.getBoundingClientRect().height-parseFloat(e.style.height))<1&&Math.abs(e.getBoundingClientRect().x-parseFloat(e.style.left))<1&&Math.abs(e.getBoundingClientRect().y-parseFloat(e.style.top))<1;});assert.equal(await page.locator('.music-island .music-connections').count(),0,'Accounts do not occupy the empty player');const island=await page.locator('.music-island').boundingBox(),music=await page.locator('.music-nav').boundingBox();assert.ok(island.height<230&&island.y>=music.y+music.height,'Empty island is compact and anchored under music');await page.screenshot({path:path.join(dir,'collection-island-'+width+'.png')});await page.keyboard.press('Escape');await page.locator('.music-island[aria-hidden=true]').waitFor({state:'attached'});await page.getByRole('button',{name:'Музыкальный плеер',exact:true}).click();await page.evaluate(()=>{const input=document.createElement('input');input.id='outsideFocusProbe';input.setAttribute('aria-label','Outside focus fixture');input.style.cssText='position:fixed;left:12px;bottom:12px;width:160px;height:36px;z-index:10000';document.body.append(input);});await page.locator('#outsideFocusProbe').click();await page.locator('.music-island[aria-hidden=true]').waitFor({state:'attached'});assert.equal(await page.locator('#outsideFocusProbe').evaluate(e=>document.activeElement===e),true,'Outside click collapses without stealing focus');await page.locator('#outsideFocusProbe').evaluate(e=>e.remove());
  await page.keyboard.press('Control+k');await page.getByRole('dialog').getByRole('button',{name:'Аниме',exact:true}).click();await page.getByRole('combobox',{name:'Поиск произведения'}).fill('Naruto');await page.getByRole('dialog').getByRole('option').first().waitFor();await page.keyboard.press('Enter');await page.locator('.title-hero h1').waitFor();
  await fits('Title');await page.screenshot({path:path.join(dir,'title-'+width+'.png'),fullPage:true});
  await page.waitForFunction(()=>{const i=document.querySelector('.title-feature .title-poster img:not([data-placeholder])');return i?.complete&&i.naturalWidth>0;});assert.deepEqual(errors,[]);await context.close();console.log('PASS Blossom '+width+'px: theme persistence, wallpaper, background colors, keyboard search and real catalog navigation');
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const name of ['blossom-harness.html','blossom-harness.jsx'])await fs.rm(path.join(ROOT,'test-output',name),{force:true});});
