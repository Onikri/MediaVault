// The title page of the approved design on real React with fixture artwork and
// catalogue: full-screen showcase, content card, chapter rail and typography,
// episode capsules, the navbar morph and the Нуар theme. No external services.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
let browser,vite,last;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/title-showcase'),base='/.codex-local/test-output/title-showcase/';await fs.mkdir(dir,{recursive:true});
 execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=8','-t','12','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart','-y',path.join(dir,'fixture.mp4')]);
 await fs.writeFile(path.join(dir,'index.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="'+base+'fixture.jsx"></script>');
 await fs.writeFile(path.join(dir,'fixture.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';import{AnimatedNavbar}from'/src/blossom/components/AnimatedNavbar.tsx';import TitlePage from'/src/TitlePage.jsx';import PlaybackReveal from'/src/PlaybackReveal.jsx';import Player from'/src/MediaVaultPlayer.jsx';import'/src/styles.css';import'/src/title-page.css';import'/src/import-layout.css';import'/src/site-layout.css';
 window.MEDIA_VAULT_CONFIG={importServerUrl:'https://api.fixture'};window.commands=[];window.addEventListener('message',e=>{try{const d=JSON.parse(e.data);if(d.fixtureCommand)window.commands.push(d.fixtureCommand);}catch{}});
 const profile={sourceId:'16498',source:'shikimori',origin:'Манга',rating:'R-17',age:17,studio:'Wit Studio',title:'Атака титанов',year:2013,score:8.58,status:'Завершён',format:'ТВ-сериал',episodes:25,duration:24,genres:['Экшен','Драма'],description:'С давних времён человечество ведёт борьбу с титанами. Это огромные существа, которые не обладают особым интеллектом. Остатки человечества укрылись за высокими стенами. Однажды привычный мир меняется, и Эрен решает узнать, что находится за его пределами.',cover:'https://art.fixture/poster.svg',backgrounds:['https://art.fixture/scene.svg'],directors:['Акинори Фудэсака'],themes:['Исторический','Медицина'],characters:[],trailers:[{url:'https://www.youtube.com/watch?v=abcdefghijk',image:'https://art.fixture/scene.svg'}]};
 const isManga=location.search.includes('manga'),item={id:'fixture',name:'Серия 1',category:'video'};
 createRoot(document.getElementById('root')).render(<ThemeProvider><div className="app-shell" data-view="library"><AnimatedNavbar links={[{id:'home',label:'Главная'},{id:'library',label:'Библиотека'},{id:'collection',label:'Коллекция'}]} active="library" onSearch={()=>{}} onNavigate={()=>{}} brand={<button className="brand logo">MediaVault</button>}><button className="avatar-button">Г</button></AnimatedNavbar><main className="app-main"><TitlePage title={{id:'fixture',name:profile.title,section:isManga?'manga':'anime',category:isManga?'manga':'video',items:[],parts:[],online:true}} state={{user:{sub:'fixture'},catalog:{items:[]}}} actions={{}} online onlineFacts={[["Доступ","Онлайн"],["Сезон просмотра","Сезон 1 · 25 сер."],["Статус оригинала","Завершён"],["Рейтинг","PG-13"],["Студия","OLM"]]} onlineProfile={profile} onBack={()=>{}} onRelated={()=>{}} materials={<><h2>Смотреть</h2><PlaybackReveal><Player item={item} source="${base}fixture.mp4" catalog={{items:[item]}} userId="fixture" apiRef={api=>window.player=api}/></PlaybackReveal></>}/></main></div></ThemeProvider>);
 `);
  const {createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/vite-showcase',logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required','--enable-unsafe-swiftshader']});
 const url='http://127.0.0.1:'+vite.httpServer.address().port+base+'index.html';
 {const warm=await browser.newPage();await warm.goto(url);await warm.waitForTimeout(4000);await warm.close();}
 for(const [width,height] of [[390,900],[1024,768],[1440,900]]){
  const page=await browser.newPage({viewport:{width,height}}),errors=[];last=page;page.setDefaultTimeout(9000);page.on('pageerror',e=>{errors.push(e.message);console.error(e.stack);});
  await page.route('https://art.fixture/**',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect width="1600" height="900" fill="#2b3a40"/><circle fill="#d9cfb2" cx="1100" cy="240" r="120"/></svg>'}));
  await page.route('https://www.youtube.com/**',r=>r.fulfill({body:'',contentType:'text/html'}));
  await page.route('https://api.fixture/**',r=>r.fulfill({json:{data:[],tracks:[],ratings:[]}}));
  await page.goto(url);
  // Showcase: the title in the design's monumental type, the call to action and the actions.
  const hero=page.locator('.kt-hero');await hero.waitFor();
  assert.equal((await hero.locator('h1').textContent()).replace(/\s+/g,' ').trim(),'Атака титанов');
  await hero.getByRole('button',{name:'Смотреть онлайн',exact:true}).waitFor();
  await hero.getByRole('button',{name:'Трейлеры',exact:true}).waitFor();
  assert.equal(await hero.locator('[aria-label="В избранное"]').count(),1);
  const box=await hero.boundingBox(),inner=await page.evaluate(()=>document.documentElement.clientWidth);assert.ok(Math.abs(box.height-height)<2&&Math.abs(box.y)<1&&box.width>=inner-1,'Showcase fills the screen '+JSON.stringify(box));
  if(width>=1024){
   assert.equal(await page.locator('.kt-hero [aria-label^="Серия "]').count(),25,'Episode ruler marks every episode');
   assert.ok(await page.locator('.kt-hero').getByText('Акинори Фудэсака').count()>=1,'Telemetry lists the director');
  }
  // The content card slides over the showcase; chapters, rail and navbar follow the scroll.
  assert.equal(await page.evaluate(()=>getComputedStyle(document.querySelector('.kt-navbar')).getPropertyValue('--nav-t').trim()),'0.0000');
  await page.evaluate(()=>document.getElementById('chapter-watch').scrollIntoView({block:'start'}));
  await page.waitForFunction(()=>Number(getComputedStyle(document.querySelector('.kt-navbar')).getPropertyValue('--nav-t'))>.95);
  if(width>=768){await page.getByLabel('Навигация по главам').waitFor({state:'visible'});await page.locator('[aria-label="Открыть список разделов"]').click();await page.getByRole('button',{name:'Трейлеры',exact:true}).last().waitFor();}
  else await page.getByRole('button',{name:/^0\d/}).last().waitFor();
  // Нуар: the page turns black, the accents white.
  await page.evaluate(async()=>{const m=await import('/src/title-exact/theme-mode.js');m.setThemeMode('noir');});
  await page.waitForFunction(()=>document.querySelector('.kt-page')?.dataset.theme==='noir');
  await page.evaluate(async()=>{const m=await import('/src/title-exact/theme-mode.js');m.setThemeMode('classic');});
  assert.deepEqual(errors,[]);await page.screenshot({path:path.join(dir,'title-'+width+'.png')});await page.close();
  console.log('PASS kinetic title page: showcase, telemetry, chapter rail, navbar morph and theme '+width);
 }
})().catch(async e=>{console.error(e);await last?.screenshot({path:'.codex-local/test-output/title-showcase/failure.png'}).catch(()=>{});process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
