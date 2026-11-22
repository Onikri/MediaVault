// Real dock geometry, section tracking and search motion. No provider requests.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');let browser,vite,last;
(async()=>{const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/title-navigation');await fs.mkdir(dir,{recursive:true});await fs.writeFile(path.join(dir,'title-capsule.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="/.codex-local/test-output/title-navigation/title-capsule.jsx"></script>');await fs.writeFile(path.join(dir,'title-capsule.jsx'),`
import React,{useState} from 'react';import{createRoot}from'react-dom/client';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';import{AnimatedNavbar}from'/src/blossom/components/AnimatedNavbar.tsx';import TitleNavigation from'/src/TitleNavigation.jsx';import{SearchDialog}from'/src/blossom/components/SearchDialog.tsx';import'/src/styles.css';
const short=location.search==='?manga',single=location.search==='?single';const ids=['titlePlayback','titleCharacters','titleStills','titleSchedule','titleMusic','titleRelated','titleWatchOrder'];function Fixture(){const[search,setSearch]=useState(false);return <ThemeProvider><AnimatedNavbar links={[{id:'home',label:'Главная'},{id:'library',label:'Библиотека'},{id:'collection',label:'Коллекция'},{id:'history',label:'История'}]} active="library" onNavigate={()=>{}} onSearch={()=>setSearch(true)} brand={<button className="brand logo">MediaVault</button>}><button id="profileBtn" className="avatar-button">Г</button></AnimatedNavbar><main className="app-main"><div style={{height:850}}>Тайтл</div><TitleNavigation title={{id:'fixture',section:short||single?'manga':'anime',category:short||single?'manga':'video',online:true,items:[]}} profile={single?{}:short?{characters:[{}]}:{sourceId:'20',characters:[{}],screenshots:['one'],related:[{}]}}/>{ids.map(id=><section key={id} id={id} style={{height:400,padding:20}}><h2>{id}</h2></section>)}</main>{search&&<SearchDialog service={{server:""}} onClose={()=>setSearch(false)} onChoose={()=>{}} onBrowse={()=>{}}/>}</ThemeProvider>;}createRoot(document.getElementById('root')).render(<Fixture/>);
`);const{createServer}=await import('vite');vite=await createServer({root,cacheDir:path.join(root,'.codex-local/cache/vite-title-dock'),optimizeDeps:{entries:[path.join(dir,'title-capsule.jsx')]},logLevel:'error',server:{watch:null,host:'127.0.0.1',port:5197,strictPort:false}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
const base='http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/title-navigation/title-capsule.html';
for(const width of[320,390,1025,1280,1440,1669]){
 const page=await browser.newPage({viewport:{width,height:900},hasTouch:width<640}),errors=[];
 last=page;
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base);
 const dock=page.getByRole('navigation',{name:'Разделы тайтла'});
 const brand=page.locator('.header-brand-area .brand.logo');
 const current=dock.locator('[aria-current="location"]');
 await dock.waitFor();
 await page.evaluate(()=>document.fonts.ready);
 const main=await page.locator('.header-inner').boundingBox();
 const rail=await dock.boundingBox();
 assert.ok(rail.y>=main.y+main.height&&rail.y-main.y-main.height<=5,'Section dock hugs the header '+JSON.stringify({main,rail}));
 assert.ok(main.x+main.width-rail.x-rail.width>=0&&main.x+main.width-rail.x-rail.width<12,'Section dock follows the right edge');
 const cells=await dock.locator('button').evaluateAll(nodes=>nodes.map(node=>({x:node.offsetLeft,y:node.offsetTop})));
 assert.ok(cells.every((cell,index)=>index===0||cell.x===cells[index-1].x&&cell.y>cells[index-1].y),'All title items form one column');
 assert.ok(rail.width<=46,'The vertical rail occupies one narrow column');
 assert.equal(await dock.getByRole('button').count(),7);
 assert.equal(await current.getAttribute('aria-label'),'Смотреть');
 assert.equal(await dock.getByRole('button',{name:/Комментарии|Обсуждение/}).count(),0);
 assert.equal(await page.locator('.title-navigation-anchor').isVisible(),false,'The page has no duplicate section rail');
 assert.equal(await brand.evaluate(n=>getComputedStyle(n).backgroundColor),'rgba(0, 0, 0, 0)','The wordmark sits on the bar without a plate, as in the design');
 assert.ok(await dock.evaluate(n=>[n,...n.querySelectorAll('button,.title-dock-label')].every(element=>{
  const style=getComputedStyle(element);
  return style.backgroundColor==='rgba(0, 0, 0, 0)'&&style.borderInlineStartWidth==='0px'&&style.boxShadow==='none';
 })),'The section controls and names have no panels or borders');
 await page.waitForFunction(()=>getComputedStyle(document.querySelector('.title-dock-section[aria-current] .title-dock-label')).opacity==='0');
 if(width<640)assert.equal((await current.boundingBox()).height,44,'Touch controls keep a 44 px target');
 if(width>1024){
  const lastLink=await page.locator('.desktop-nav .nav-link').last().boundingBox(),search=await page.locator('.header-search').boundingBox();
  assert.ok(lastLink.x+lastLink.width<=search.x-2,'The primary navigation leaves a clear search lane');
  assert.ok(await page.locator('.desktop-nav .nav-glide').evaluate(n=>parseFloat(getComputedStyle(n).borderTopLeftRadius)>=n.offsetHeight/2));
 }

 const marker=dock.locator('.title-dock-marker');
 const first=await marker.boundingBox();
 assert.equal(first.width,2);
 assert.equal(first.height,10);
 await dock.getByRole('button',{name:'Музыка',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.title-dock-section[aria-current]')?.getAttribute('aria-label')==='Музыка');
 await page.waitForFunction(()=>{
  const marker=document.querySelector('.title-dock-marker');
  if(!marker)return false;
  const indicator=marker.getBoundingClientRect(),button=marker.parentElement.getBoundingClientRect();
  return Math.abs(indicator.y+indicator.height/2-button.y-button.height/2)<1;
 });
 const music=await marker.boundingBox();
 assert.ok(music.y>first.y+40,'The selection marker follows the change of section vertically');
 assert.equal(await brand.textContent(),'MediaVault');
 const selectedTitle=dock.getByRole('button',{name:'Порядок просмотра',exact:true});
 await selectedTitle.focus();
 await page.keyboard.press('Enter');
 await page.waitForFunction(()=>document.querySelector('.title-dock-section[aria-current]')?.getAttribute('aria-label')==='Порядок просмотра');
 await page.waitForFunction(()=>{
  const label=document.querySelector('.title-dock-section:focus-visible .title-dock-label');
  return label&&label.scrollWidth<=label.clientWidth+1&&Number(getComputedStyle(label).opacity)>.9;
 });
 assert.equal(await brand.textContent(),'MediaVault');
 assert.equal((await dock.boundingBox()).width,rail.width,'The icon column keeps its width with a longer label');
 await selectedTitle.blur();
 if(width===390||width===1440)await page.screenshot({path:path.join(dir,'title-dock-'+width+'.png'),clip:{x:0,y:0,width,height:360}});
 await page.evaluate(()=>scrollTo(0,0));
 await page.waitForFunction(()=>document.querySelector('.title-dock-section[aria-current]')?.getAttribute('aria-label')==='Смотреть');
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 // Sample actual search animation frames with the title dock temporarily hidden.
for(const scrolled of [false,true]){
 await page.evaluate(value=>scrollTo(0,value?480:0),scrolled);await page.waitForTimeout(550);
 for(let cycle=0;cycle<2;cycle++){
  await page.locator('.header-search').click();await page.locator('.morph-search-bar').waitFor();assert.equal(await dock.isVisible(),false);
  if(width===1669&&!scrolled){
   await page.waitForFunction(()=>document.querySelector('.blossom-navbar')?.classList.contains('is-search-expanded'));
   assert.ok(await page.locator('.desktop-nav .nav-link-label').first().isVisible(),'Full-width expanded search retains desktop labels');
   const last=await page.locator('.desktop-nav .nav-link').last().boundingBox();
   const search=await page.locator('.morph-search-bar').boundingBox();
   assert.ok(last.x+last.width<search.x,'Labels have a dedicated lane beside expanded search');
  }
  const sample=()=>page.evaluate(()=>new Promise(resolve=>{const rows=[],start=performance.now();function frame(now){const b=document.querySelector('.morph-search-bar')?.getBoundingClientRect(),h=document.querySelector('.header-inner').getBoundingClientRect(),button=document.querySelector('.header-search');if(b)rows.push({dy:Math.abs(b.y+b.height/2-h.y-h.height/2),w:b.width,h:b.height,r:parseFloat(getComputedStyle(document.querySelector('.morph-search-bar')).borderRadius)});else rows.push({closed:true,visible:getComputedStyle(button).visibility==='visible',opacity:getComputedStyle(button.parentElement).opacity});if(now-start<420)requestAnimationFrame(frame);else resolve(rows);}requestAnimationFrame(frame);}));
  const opening=await sample();assert.ok(opening.every(r=>r.dy<1&&r.w>=37&&Math.abs(r.h-38)<1&&r.r===19),'Opening never jumps vertically or distorts into an ellipse '+JSON.stringify(opening));
  await page.locator('.morph-search-close').click();const closing=await sample();assert.ok(closing.every(r=>r.closed?r.visible&&r.opacity==='1':r.dy<1&&r.w>=37&&Math.abs(r.h-38)<1),'Closing hands directly back to the circle '+JSON.stringify(closing));
  await page.locator('.morph-search-dialog').waitFor({state:'detached'});await dock.waitFor();const circle=await page.locator('.header-search').boundingBox();assert.ok(Math.abs(circle.width-circle.height)<.1&&Math.abs(circle.width-38)<.1,'Repeated close restores exactly the same circle');
 }
}
 if(width===390||width===1440){
  await page.goto(base+'?manga');
  await dock.getByRole('button',{name:'Читать',exact:true}).waitFor();
  assert.equal(await dock.getByRole('button').count(),2);
  await dock.getByRole('button',{name:'Персонажи',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.title-dock-section[aria-current]')?.getAttribute('aria-label')==='Персонажи');
  await page.locator('#titleCharacters').evaluate(node=>node.style.marginTop='-400px');
  await dock.getByRole('button',{name:'Читать',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.title-dock-section[aria-current]')?.getAttribute('aria-label')==='Читать');
  await dock.getByRole('button',{name:'Персонажи',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.title-dock-section[aria-current]')?.getAttribute('aria-label')==='Персонажи');
  await page.goto(base+'?single');
  await page.locator('.title-navigation-anchor').waitFor({state:'attached'});
  assert.equal(await dock.count(),0,'A lone destination needs no section dock');
 }
 assert.deepEqual(errors,[]);
 await page.close();
 console.log('PASS borderless title dock, section scroll, keyboard and search '+width);
}
})().catch(async e=>{console.error(e);await last?.screenshot({path:'.codex-local/test-output/title-navigation/title-capsule-failure.png'}).catch(()=>{});process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const f of['title-capsule.html','title-capsule.jsx'])await fs.rm('.codex-local/test-output/title-navigation/'+f,{force:true});});
