// Real React profile/reader interactions. Catalogue, login and image data are fixtures.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
let browser,vite,last;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/profile-reader'),base='/.codex-local/test-output/profile-reader/';await fs.mkdir(dir,{recursive:true});
 await fs.writeFile(path.join(dir,'index.html'),'<meta name="viewport" content="width=device-width,initial-scale=1"><div id="scene-root"></div><div id="root"></div><script type="module" src="'+base+'fixture.jsx"></script>');
 await fs.writeFile(path.join(dir,'fixture.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import App from'/src/App.jsx';import MangaReader from'/src/MangaReader.jsx';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';import JSZip from'jszip';import'/src/styles.css';import'/src/title-page.css';
 window.MEDIA_VAULT_CONFIG={importServerUrl:'https://fixture.example'};
 if(location.search.includes('reader')){const c=document.createElement('canvas');c.width=640;c.height=960;const ctx=c.getContext('2d');ctx.fillStyle='#eee6d5';ctx.fillRect(0,0,640,960);ctx.fillStyle='#52525c';ctx.fillRect(25,25,590,400);ctx.fillStyle='#8e8e97';ctx.fillRect(25,450,270,480);ctx.fillRect(320,450,295,480);const blob=await new Promise(r=>c.toBlob(r,'image/png')),zip=new JSZip();for(let i=1;i<=3;i++)zip.file(i+'.png',blob);const archive=await zip.generateAsync({type:'blob'}),item={id:'reader-interface',name:'Проверка читалки',category:'manga',size:archive.size};createRoot(document.getElementById('root')).render(<ThemeProvider><MangaReader item={item} catalog={{items:[item]}} libraryId="fixture" userId="fixture" readWhole={async()=>archive} onClose={()=>{}}/></ThemeProvider>);}else createRoot(document.getElementById('root')).render(<App/>);
 `);
 const {createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/vite-profile-reader',logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 for(const width of [390,1440]){
  const page=await browser.newPage({viewport:{width,height:940}}),errors=[];last=page;page.on('pageerror',e=>errors.push(e.message));
  await page.route('https://**/*',r=>r.fulfill({json:{data:[],current:[],popular:[]}}));
  await page.addInitScript(()=>localStorage.setItem('mediavault_privacy_v1',JSON.stringify({version:1,chosen:true,remember:false})));
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+base+'index.html#profile');
  await page.getByRole('tab',{name:'Аккаунт',exact:true}).waitFor();await page.locator('#loginBtn').waitFor();
  assert.equal(await page.locator('.account-layout').count(),1);
  for(const [tab,selector] of [['Оформление','#appearanceSettings'],['Подключения','.kodik-connection'],['Устройство и доступ','.privacy-settings']]){
   await page.getByRole('tab',{name:tab,exact:true}).click();
   if(tab==='Устройство и доступ')await page.getByRole('tabpanel').waitFor();else await page.locator(selector).waitFor();
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Profile fits '+width+' '+tab);
  }
  await page.getByRole('tab',{name:'Оформление',exact:true}).click();await page.waitForTimeout(220);await page.screenshot({path:path.join(dir,'profile-'+width+'.png'),fullPage:true});
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+base+'index.html?reader=1');
  await page.waitForFunction(()=>document.querySelector('.reader-page img')?.naturalWidth===640);
  await page.locator('.immersive-reader').dispatchEvent('reader-show-chrome');await page.getByRole('button',{name:'Настройки читалки',exact:true}).click();
  const panel=page.locator('.reader-panel');await panel.getByRole('button',{name:'Вписать целиком',exact:true}).click();
  await page.locator('.reader-fit-page').waitFor();assert.equal(await panel.getByRole('button',{name:'Вписать целиком',exact:true}).getAttribute('aria-pressed'),'true');
  await panel.getByRole('button',{name:'Вебтун',exact:true}).click();await page.locator('.reader-mode-scroll').waitFor();assert.equal(await page.locator('.reader-page').count(),3);
  await panel.getByRole('button',{name:'Разворот',exact:true}).click();await page.getByRole('button',{name:'Закрыть настройки читалки',exact:true}).click();
  await page.locator('.immersive-reader').dispatchEvent('reader-show-chrome');const chrome=await page.locator('.reader-top').boundingBox();assert.equal(await page.locator('.reader-bottom-float').evaluate(n=>getComputedStyle(n).borderTopWidth),'0px');assert.ok(chrome.width<=1101&&chrome.x>=0&&chrome.x+chrome.width<=width+1);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(dir,'reader-'+width+'.png')});
  assert.deepEqual(errors,[]);await page.close();console.log('PASS profile tabs, retained settings, four reader modes and capsule geometry '+width);
 }
})().catch(async e=>{console.error(e);await last?.screenshot({path:'.codex-local/test-output/profile-reader/failure.png'}).catch(()=>{});process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
