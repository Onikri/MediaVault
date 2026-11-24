// Real React/Radix keyboard/pointer/geometry; no model execution or Google calls.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const ROOT=process.cwd(),DIR=path.join(ROOT,'.codex-local/test-output/reader-track-settings');let browser,vite,last;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});await fs.writeFile(path.join(DIR,'index.html'),'<meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/.codex-local/test-output/reader-track-settings/app.jsx"></script>');
 await fs.writeFile(path.join(DIR,'app.jsx'),`
 import React,{useState}from'react';import{createRoot}from'react-dom/client';import Shell from'/src/ReaderShell.jsx';import LmtSettings from'/src/LmtSettings.jsx';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';import'/src/styles.css';import '/src/title-page.css';import '/src/reader-save.css';import '/src/import-queue.css';import '/src/profile-menu.css';
 window.MEDIA_VAULT_CONFIG={};const service={server:location.origin,status:'connected',session:{serverVersion:49},request:async()=>({slots:[],keyCount:0})};
 function App(){const[page,setPage]=useState(1),[vertical,setVertical]=useState(false),[settings,setSettings]=useState(false),[config,setConfig]=useState({engine:'direct',language:'Japanese',directDetector:'rtdetr',directInput:'annotated'});window.configure=()=>setVertical(v=>!v);window.config=config;window.current=page;return <Shell title="Название манги" onClose={()=>{}} progress={{current:page,total:256,start:page,end:Math.min(256,page+1),label:page+'–'+Math.min(256,page+1)+' / 256'}} onPage={p=>setPage(p+1)} onPrevious={()=>setPage(p=>Math.max(1,p-1))} onNext={()=>setPage(p=>Math.min(256,p+1))} canPrevious={page>1} canNext={page<256} progressOrientation={vertical?'vertical':'horizontal'} previews={<p>Превью</p>} settingsOpen={settings} onSettingsOpenChange={setSettings} settings={<div className="reader-settings"><div className="reader-translation-settings"><LmtSettings directKeyScope="fixture" value={config} onChange={setConfig} service={service} onClearCache={()=>{}}/></div></div>}><div style={{height:'100%',background:'#25252b'}}/></Shell>;}
 createRoot(document.getElementById('root')).render(<ThemeProvider><App/></ThemeProvider>);
 `);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 for(const width of[390,1440]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];last=page;page.setDefaultTimeout(6000);page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/reader-track-settings/index.html');const root=page.locator('.immersive-reader'),show=()=>root.dispatchEvent('reader-show-chrome');await page.waitForTimeout(80);await show();await page.waitForFunction(()=>document.querySelector('.immersive-reader')?.dataset.chrome==='true');
  assert.equal(await page.locator('.reader-dock').getByRole('button',{name:'Превью страниц',exact:true,includeHidden:true}).count(),1);assert.equal(await page.locator('.reader-dock').getByRole('button',{name:'Превью страниц',exact:true}).count(),0);
  // The dock's empty glass is the page slider: find a free spot, peek, seek, drag to the end, Home.
  {
   await show();await page.waitForTimeout(480);
   const vertical=await page.locator('.reader-dock').evaluate(n=>n.classList.contains('is-vertical'));
   const findSpot=()=>page.evaluate(vertical=>{const s=document.querySelector('.reader-dock .rd-scrub'),r=s.getBoundingClientRect();
    for(let f=.5,i=0;i<90;i++,f=i%2?.5+i*.005:.5-i*.005){const x=vertical?r.left+r.width/2:r.left+r.width*f,y=vertical?r.top+r.height*f:r.top+r.height/2;if(document.elementFromPoint(x,y)?.classList.contains('rd-scrub-input'))return {f,x,y};}return null;},vertical);
   let spot=await findSpot();assert.ok(spot,'The dock leaves empty glass to scrub');
   const expected=Math.round(spot.f*255)+1;
   await page.mouse.move(spot.x,spot.y);await page.locator('.rd-peek b').waitFor();assert.ok(Math.abs(Number(await page.locator('.rd-peek b').textContent())-expected)<=1,'The peek names the page under the pointer');
   await page.mouse.click(spot.x,spot.y);await page.waitForFunction(n=>Math.abs(current-n)<=1,expected);
   const edge=await page.evaluate(vertical=>{const r=document.querySelector('.reader-dock .rd-scrub').getBoundingClientRect();return vertical?{x:r.left+r.width/2,y:r.bottom-1}:{x:r.right-1,y:r.top+r.height/2};},vertical);
   // Right-to-left manga runs the glass from the right: try one edge, then the other.
   await show();await page.waitForTimeout(300);spot=await findSpot();await page.mouse.move(spot.x,spot.y);await page.mouse.down();await page.mouse.move(edge.x,edge.y,{steps:5});await page.mouse.up();await page.waitForFunction(()=>current===256||current===1);
   if(await page.evaluate(()=>current)===1){const start=await page.evaluate(vertical=>{const r=document.querySelector('.reader-dock .rd-scrub').getBoundingClientRect();return vertical?{x:r.left+r.width/2,y:r.top+1}:{x:r.left+1,y:r.top+r.height/2};},vertical);await show();spot=await findSpot();await page.mouse.move(spot.x,spot.y);await page.mouse.down();await page.mouse.move(start.x,start.y,{steps:5});await page.mouse.up();await page.waitForFunction(()=>current===256);}
   await show();await page.getByLabel('Перейти к странице',{exact:true}).press('Home');await page.waitForFunction(()=>current===1);
   const box=await page.locator('.reader-dock .rd-bar').boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width+1,'The dock stays on screen');
  }
  await show();await page.getByRole('button',{name:'Настройки читалки',exact:true}).click();const panel=page.locator('.reader-panel');const help=page.getByRole('button',{name:'Пояснения к настройкам перевода',exact:true});assert.equal(await help.getAttribute('aria-expanded'),'false');await help.click();assert.equal(await help.getAttribute('aria-expanded'),'true');await help.click();
  await page.getByRole('button',{name:'Блоки на листе',exact:true}).click();await page.waitForFunction(()=>config.directInput==='blocks');await page.getByText('Вырезки текста с номерами на читаемых листах. Исходные координаты и вёрстка сохраняются.',{exact:true}).waitFor();await page.getByRole('button',{name:'Страницы с рамками',exact:true}).click();await page.waitForFunction(()=>config.directInput==='annotated');
  await page.getByText('Дополнительная разметка',{exact:true}).click();await page.getByRole('combobox',{name:'Разметка для Google',exact:true}).click();assert.equal(await page.getByRole('option').count(),4);await page.getByRole('option',{name:'Google сам находит текст и координаты',exact:true}).click();await page.waitForFunction(()=>config.directInput==='vision');await page.getByRole('combobox',{name:'Исходный язык LMT',exact:true}).click();await page.getByRole('option',{name:'Корейский',exact:true}).click();await page.waitForFunction(()=>config.language==='Korean');
  assert.ok(await panel.evaluate(n=>n.scrollWidth<=n.clientWidth+1));await page.screenshot({path:path.join(DIR,'settings-'+width+'.png')});assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS dock glass slider: peek, exact seek, drag to the end, keyboard range; folded previews; compact translation help and all payload modes at 390/1440px');
})().catch(async e=>{console.error(e);await last?.screenshot({path:path.join(DIR,'failure.png')}).catch(()=>{});process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
