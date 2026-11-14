// CI contract with neutral controls; no source/account requests or ML inference.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/catalog-morph');let browser,vite,lastPage;
(async()=>{
 await fs.mkdir(dir,{recursive:true});
 await fs.writeFile(path.join(dir,'index.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="./fixture.jsx"></script>');
 await fs.writeFile(path.join(dir,'fixture.jsx'),`
 import React,{useState} from 'react';import{createRoot}from'react-dom/client';
 import{AnimatedNavbar}from'/src/blossom/components/AnimatedNavbar.tsx';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';
 import CatalogFilterDock from'/src/CatalogFilterDock.jsx';import{useSectionBrandFor}from'/src/section-brand-store.js';import Icon from'/src/Icons.jsx';
 import'/src/styles.css';import'/src/blossom/integration.css';import'/src/blossom/composition.css';import'/src/site-layout.css';import'/src/site-mobile.css';
 const links=[['home','Главная','home'],['library','Библиотека','library'],['collection','Коллекция','cloud'],['history','История','history']].map(([id,label,icon])=>({id,label,icon:<Icon name={icon}/>}));
 function Demo(){const[filters,setFilters]=useState({}),[query,setQuery]=useState(''),[rail,setRail]=useState(null);window.filters=filters;
 useSectionBrandFor(rail,{sections:[['manga','Манга'],['anime','Аниме']],active:'manga',onPick:()=>{}});
 return <ThemeProvider><AnimatedNavbar links={links} active="library" onNavigate={()=>{}} onSearch={()=>{window.globalSearchOpened=true;}} brand={<button className="brand logo">MediaVault</button>}/>
 <main style={{padding:'160px 14px 20px',maxWidth:1400,margin:'auto'}}><div ref={setRail} style={{height:40}}>Манга</div>
 <CatalogFilterDock mergeNavigation kind="manga" filters={filters} onFilter={(key,value)=>setFilters(old=>({...old,[key]:value}))} onReset={()=>setFilters({})} genres={['Фэнтези','Комедия','Драма']} tags={['Dragons','Robots']} formats={['Манга','Манхва']} search={<div className="catalog-search-wrap"><div className="search-bar catalog-search"><input aria-label="Поиск в каталоге" className="search-input" value={query} onChange={e=>setQuery(e.target.value)}/></div></div>}/>
 <div style={{height:2600}}>Нейтральная проверка каталога</div></main></ThemeProvider>}
 createRoot(document.getElementById('root')).render(<Demo/>);`);
 const {createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/vite-catalog-morph',logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 for(const width of [320,390,768,1440]){
  const page=lastPage=await browser.newPage({viewport:{width,height:960},reducedMotion:'reduce'}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('https://**/*',route=>route.fulfill({status:204}));
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/catalog-morph/index.html');
  const query=page.getByRole('textbox',{name:'Поиск в каталоге'});await query.fill('Garden');
  await page.evaluate(()=>scrollTo(0,500));await page.waitForTimeout(100);
  assert.equal(await query.evaluate(e=>document.activeElement===e),true,'Scrolling preserves focused input');
  await query.evaluate(e=>e.blur());
  await page.waitForFunction(()=>document.documentElement.dataset.catalogMerged==='true');
  assert.equal(await page.locator('.catalog-toolbar').count(),1,'Only one toolbar is mounted');
  if(width<=1000)await page.getByRole('navigation',{name:'Навигация',exact:true}).getByRole('button',{name:'Библиотека',exact:true}).waitFor();
  assert.equal(await page.locator('.catalog-nav-slot .catalog-toolbar').count(),1);
  assert.equal(await query.inputValue(),'Garden');
  await page.getByRole('button',{name:'Раздел: Манга. Сменить раздел'}).waitFor({timeout:8000}).catch(async error=>{console.error(await page.evaluate(()=>({scroll:scrollY,brand:document.querySelector('.header-brand-area')?.textContent,display:document.querySelector('.header-brand-area')&&getComputedStyle(document.querySelector('.header-brand-area')).display,width:document.querySelector('.navbar-brand-morph')?.getBoundingClientRect().width})));throw error;});
  await page.keyboard.press('Control+k');assert.equal(await query.evaluate(e=>document.activeElement===e),true);assert.equal(await page.evaluate(()=>!!window.globalSearchOpened),false);
  await query.evaluate(e=>e.blur());
  if(!(await page.getByRole('toolbar',{name:'Фильтры каталога'}).isVisible()))await page.getByRole('button',{name:/^Фильтры/}).click();
  await page.getByRole('toolbar',{name:'Фильтры каталога'}).getByRole('button',{name:/^Жанры/}).click();
  await page.getByRole('button',{name:'Включить Фэнтези',exact:true}).click();await page.getByRole('button',{name:'Включить Комедия',exact:true}).click();await page.getByRole('button',{name:'Исключить Драма',exact:true}).click();
  assert.deepEqual(await page.evaluate(()=>window.filters.genre),['Фэнтези','Комедия']);assert.deepEqual(await page.evaluate(()=>window.filters.excludeGenre),['Драма']);
  await page.keyboard.press('Escape');
  await page.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth+1);
  await page.screenshot({path:path.join(dir,'merged-'+width+'.png')});
  await page.evaluate(()=>{document.activeElement?.blur();scrollTo(0,0);});await page.waitForFunction(()=>!document.documentElement.dataset.catalogMerged);
  assert.equal(await query.inputValue(),'Garden');assert.equal(await page.locator('.catalog-toolbar').count(),1);assert.deepEqual(errors,[]);
  await page.close();console.log('PASS signed filters, one dock, section brand, focus and reverse scroll '+width);
 }
})().catch(async e=>{console.error(e);await lastPage?.screenshot({path:path.join(dir,'failure.png')}).catch(()=>{});process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
