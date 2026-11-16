// CSS refactor guard: screenshots plus a dump of every element's computed style
// for the key screens at 320/390/768/1280/1440. Two captures are compared with
// scripts/css-snapshots-diff.cjs; a pure CSS cleanup must leave both unchanged.
//
//   node scripts/css-snapshots.cjs --out .codex-local/css-snapshots/before [--scenes home,player] [--widths 390,1280] [--no-build]
//
// The site scenes use the production build (vite build + preview) because the
// bundle's CSS order is what users get; player and readers use test harnesses.
// MOCKED: every https request answers from fixtures; no account, no server.
const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..');
const arg=(name,fallback)=>{const i=process.argv.indexOf('--'+name);return i>0?process.argv[i+1]:fallback;};
const OUT=path.resolve(ROOT,arg('out','.codex-local/css-snapshots/latest'));
const WIDTHS=arg('widths','320,390,768,1280,1440').split(',').map(Number);
const HEIGHT=900;
const PNG=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a+kkAAAAASUVORK5CYII=','base64');
const ART='<svg xmlns="http://www.w3.org/2000/svg" width="640" height="960"><path fill="#544d42" d="M0 0h640v960H0z"/><circle cx="320" cy="380" r="170" fill="#a89168"/><path d="M0 700L320 520L640 700V960H0Z" fill="#5b7266"/></svg>';

// Catalogue fixtures shared by the site scenes.
const anime=(id,title,russian)=>({mal_id:id,title,russian,synopsis:'Описание для проверки интерфейса.',type:'TV',episodes:12,year:2021,score:8.4,images:{jpg:{image_url:'https://art.fixture/'+id+'.svg',large_image_url:'https://art.fixture/'+id+'.svg'},webp:{image_url:'https://art.fixture/'+id+'.svg',large_image_url:'https://art.fixture/'+id+'.svg'}},genres:[{mal_id:1,name:'Drama'}],aired:{from:'2021-01-10'}});
const SHELF=[anime(16498,'Mushoku Tensei','Реинкарнация безработного'),anime(20,'Naruto','Наруто'),anime(5114,'Fullmetal Alchemist','Стальной алхимик: Братство'),anime(9253,'Steins;Gate','Врата Штейна'),anime(1535,'Death Note','Тетрадь смерти'),anime(11061,'Hunter x Hunter','Охотник х Охотник')];
const PROFILE={id:16498,russian:'Реинкарнация безработного: История о приключениях в другом мире',name:'Mushoku Tensei',kind:'tv',score:8.5,description:'Описание произведения. Длинный текст должен занимать нормальную колонку, а не превращаться в вертикальный столбец отдельных букв.',aired_on:'2021-01-10',episodes:12,status:'released',rating:'r',image:{original:'https://art.fixture/p.svg'},genres:[{name:'Drama',russian:'Драма'}],studios:[{id:1,name:'Studio Bind'}]};
async function siteRoutes(context){
 await context.route(/^https:\/\//,route=>{
  const req=route.request(),u=new URL(req.url()),cors={'access-control-allow-origin':'*'};
  if(req.resourceType()==='script')return route.fulfill({contentType:'application/javascript',body:''});
  if(req.resourceType()==='font'||req.resourceType()==='stylesheet'&&!u.hostname.includes('fonts.googleapis'))return route.abort();
  if(u.pathname==='/artwork'||u.hostname==='art.fixture'||u.hostname==='art.test')return route.fulfill({headers:cors,contentType:'image/svg+xml',body:ART});
  if(req.resourceType()==='image')return route.fulfill({headers:cors,contentType:'image/png',body:PNG});
  let data={data:[],results:[],sources:[],voices:[],providers:[],items:[],pending:false};
  if(u.pathname.endsWith('/anime-home'))data={current:SHELF,popular:SHELF.slice().reverse(),season:{label:'Тестовый сезон'}};
  else if(u.pathname.includes('/shikimori')||u.hostname.startsWith('shikimori'))data=u.searchParams.has('identity')?PROFILE:[];
  else if(u.pathname.includes('/jikan')||u.hostname==='api.jikan.moe'){const p=u.searchParams.get('path')||u.pathname;data=/\/full$|\/anime\/\d+$/.test(p)?{data:SHELF[0]}:{data:SHELF,pagination:{has_next_page:false}};}
  else if(u.hostname==='graphql.anilist.co')data={data:{Page:{media:[]}}};
  return route.fulfill({headers:cors,contentType:'application/json',body:JSON.stringify(data)});
 });
}

// Scenes: where, how to reach the state, what must be on screen.
const SCENES={
 home:{site:'#home',ready:'.blossom-navbar'},
 library:{site:'#library',ready:'.blossom-navbar'},
 'title-anime':{site:'#watch=anime:shikimori:16498',ready:'.title-showcase'},
 'title-manga':{site:'#watch=manga:shikimori:16498',ready:'.title-showcase'},
 'title-ranobe':{site:'#watch=ranobe:shikimori:16498',ready:'.title-showcase'},
 history:{site:'#history',ready:'.blossom-navbar'},
 player:{harness:'player',async open(page){
  await page.locator('.title-episode-card').first().click();
  await page.waitForFunction(()=>document.querySelector('.mv-player video')?.readyState>=2,null,{timeout:90000});
  await page.locator('.mv-player video').evaluate(v=>new Promise(r=>{v.pause();v.addEventListener('seeked',()=>setTimeout(r,400),{once:true});v.currentTime=1;}));
  await page.locator('.mv-player').evaluate(n=>{n.scrollIntoView({block:'start'});scrollBy(0,-110);});
 }},
 'player-episodes':{harness:'player',async open(page){
  await SCENES.player.open(page);
  await page.getByRole('button',{name:'Выбрать серию'}).click();await page.locator('.mvx-episodes').waitFor();
 }},
 'player-settings':{harness:'player',async open(page){
  await SCENES.player.open(page);
  await page.getByRole('button',{name:'Настройки плеера',exact:true}).click();await page.getByRole('dialog',{name:'Настройки просмотра'}).waitFor();
 }},
 'player-music':{harness:'player',async open(page){
  await SCENES.player.open(page);
  await page.getByRole('button',{name:'Музыка из аниме',exact:true}).click();await page.locator('.player-popover.mvx-menu').waitFor();
 }},
 'ranobe-reader':{harness:'ranobe',async open(page){
  await page.getByRole('button',{name:/Начать читать/}).click({timeout:120000});
  await page.locator('.ranobe-prose p').first().waitFor();
 }},
};

function writeHarnesses(){
 const dir=path.join(ROOT,'test-output');fs.mkdirSync(dir,{recursive:true});
 const clip=path.join(dir,'css-snapshot-video.mp4');
 if(!fs.existsSync(clip))execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','color=c=0x294c60:s=320x180:r=10','-t','20','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart','-y',clip]);
 // The player: the design contract's title page with one playable episode.
 fs.writeFileSync(path.join(dir,'css-snapshot-player.html'),'<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="scene-root"></div><div id="root"></div><script type="module" src="/test-output/css-snapshot-player.jsx"></script></html>');
 fs.writeFileSync(path.join(dir,'css-snapshot-player.jsx'),`import React,{useState} from 'react';import{createRoot}from'react-dom/client';
 import {ThemeProvider} from '/src/blossom/ThemeProvider.tsx';import TitlePage from '/src/TitlePage.jsx';import '/src/styles.css';import '/src/title-page.css';import '/src/import-layout.css';import '/src/discovery-polish.css';import '/src/site-layout.css';import '/src/site-mobile.css';
 window.MEDIA_VAULT_CONFIG={importServerUrl:'https://fixture.example'};
 const art=id=>({id,fileId:id,iv:'fixture',mime:'image/png'}),cover='https://art.test/cover',person='https://art.test/person';
 const profile={version:4,sourceId:'57334',sourceURL:'https://shikimori.io/animes/57334',title:'Дандадан',year:2024,format:'Аниме',description:'Двое школьников сталкиваются с необъяснимым. История о дружбе и сверхъестественном.',genres:['Комедия','Сверхъестественное'],characters:[],related:[],screenshots:[],staff:[{id:'41',name:'Фуга Ямасиро',role:'Режиссёр',image:person}],trailers:[{id:'X_SnV_SdO4k',title:'Тизер',image:cover}],cover,artwork:{[cover]:art('cover'),[person]:art('person')}};
 const items=[1,2,3].map(n=>({id:'episode-'+n,name:'Дандадан — серия '+n+'.mp4',episode:n,season:1,section:'anime',category:'video',collectionId:'g',previewArtwork:art('preview-'+n),size:1000}));
 const title={id:'anime:g',name:'Дандадан',section:'anime',category:'video',items,parts:[],collectionId:'g'};
 const catalog={items,storage:{collections:[{id:'g',name:'Дандадан',section:'anime',parts:[]}]},titleProfiles:{'anime:g':profile}};
 const png=Uint8Array.from(atob('${PNG.toString('base64')}'),c=>c.charCodeAt(0));
 const actions={readArtwork:async()=>new Blob([png],{type:'image/png'}),prepareStream:async()=>'/test-output/css-snapshot-video.mp4',readWhole:async()=>new Blob(),error:()=>{},saveTitleProfile:async()=>profile};
 function Demo(){const[selected,setSelected]=useState(null);return <><header className="app-header"><div className="header-inner"><b>MediaVault</b></div></header><main className="app-main"><TitlePage title={title} state={{catalog,user:{sub:'user-a'},libraryId:'library',admin:false}} actions={actions} onBack={()=>{}} onPlay={setSelected} selected={selected} onRelated={()=>{}} onClosePlayer={()=>setSelected(null)}/></main></>;}
 createRoot(document.getElementById('root')).render(<ThemeProvider><Demo/></ThemeProvider>);`);
 fs.writeFileSync(path.join(dir,'css-snapshot-ranobe.html'),'<!doctype html><html lang="ru" data-blossom><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/tests/ranobe-harness.jsx"></script></html>');
}

// In-page: every rendered element (and drawn ::before/::after) with its box and
// full computed style; identical style strings are stored once.
function dumpStyles(){
 const table=[],index=new Map(),out=[];
 const intern=s=>{let i=index.get(s);if(i===undefined){i=table.length;table.push(s);index.set(s,i);}return i;};
 const styleOf=(el,pseudo)=>{const cs=getComputedStyle(el,pseudo);if(pseudo&&(cs.content==='none'||cs.content==='normal'))return null;const parts=[];for(let i=0;i<cs.length;i++){const p=cs[i];parts.push(p+':'+cs.getPropertyValue(p));}return parts.join(';');};
 const keyOf=el=>{const parts=[];for(let n=el;n&&n.nodeType===1;n=n.parentElement){let i=0;for(let s=n.previousElementSibling;s;s=s.previousElementSibling)if(s.tagName===n.tagName)i++;parts.unshift(n.tagName.toLowerCase()+(i?'['+i+']':'')+(n.classList.length?'.'+[...n.classList].join('.'):''));}return parts.join('>');};
 for(const el of document.querySelectorAll('body, body *')){
  if(el.closest('script,style,svg defs'))continue;
  const r=el.getBoundingClientRect(),key=keyOf(el);
  out.push([key,[Math.round(r.x),Math.round(r.y+scrollY),Math.round(r.width),Math.round(r.height)].join(','),intern(styleOf(el))]);
  for(const p of ['::before','::after']){const s=styleOf(el,p);if(s)out.push([key+p,'',intern(s)]);}
 }
 return {url:location.href,scrollHeight:document.documentElement.scrollHeight,table,elements:out};
}

async function settle(page){
 await page.evaluate(async()=>{await document.fonts.ready;for(const img of document.images)if(!img.complete)await new Promise(r=>{img.onload=img.onerror=r;setTimeout(r,3000);});});
 await page.waitForTimeout(900);
 await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
}

(async()=>{
 const only=arg('scenes','');const names=only?only.split(','):Object.keys(SCENES);
 for(const n of names)if(!SCENES[n])throw Error('unknown scene '+n);
 fs.mkdirSync(OUT,{recursive:true});
 const needSite=names.some(n=>SCENES[n].site),needHarness=names.some(n=>SCENES[n].harness);
 if(needSite&&!process.argv.includes('--no-build'))execFileSync(process.execPath,[path.join(ROOT,'node_modules/vite/bin/vite.js'),'build','--logLevel','error'],{cwd:ROOT,stdio:'inherit'});
 const vite=await import('vite');let preview,dev;
 if(needSite)preview=await vite.preview({root:ROOT,logLevel:'error',preview:{host:'127.0.0.1',port:0}});
 if(needHarness){writeHarnesses();dev=await vite.createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0,hmr:false}});await dev.listen();}
 const siteURL=preview&&('http://127.0.0.1:'+preview.httpServer.address().port+'/');
 const devURL=dev&&('http://127.0.0.1:'+dev.httpServer.address().port);
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox','--enable-unsafe-swiftshader','--font-render-hinting=none','--disable-lcd-text']});
 const report=[];
 // Vite optimizes dependencies on the first harness load and may reload the page; warm it up.
 for(const h of new Set(names.map(n=>SCENES[n].harness).filter(Boolean))){const p=await browser.newPage();await p.goto(devURL+'/test-output/css-snapshot-'+h+'.html',{timeout:180000}).catch(()=>{});await p.waitForTimeout(8000);await p.close();}
 try{
  for(const name of names){
   const scene=SCENES[name];
   for(const width of WIDTHS){
    const context=await browser.newContext({viewport:{width,height:HEIGHT},reducedMotion:'reduce',serviceWorkers:'block',deviceScaleFactor:1,timezoneId:'Europe/Ljubljana',locale:'ru-RU'});
    context.setDefaultTimeout(30000);
    await context.addInitScript(()=>{localStorage.setItem('mediavault_privacy_v1',JSON.stringify({version:1,chosen:true,remember:false}));Math.random=(()=>{let s=42;return()=>(s=(s*16807)%2147483647)/2147483647;})();});
    await siteRoutes(context);
    const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
    try{
     if(scene.site){await page.goto(siteURL+scene.site);await page.locator(scene.ready).first().waitFor({state:'attached'});}
     else{await page.goto(devURL+'/test-output/css-snapshot-'+scene.harness+'.html'+(scene.harness==='ranobe'?'?tray=1':''),{timeout:180000});}
     if(scene.open)await scene.open(page);
     await settle(page);
     const dump=await page.evaluate(dumpStyles);dump.errors=errors;
     fs.writeFileSync(path.join(OUT,name+'-'+width+'.json'),JSON.stringify(dump));
     await page.screenshot({path:path.join(OUT,name+'-'+width+'.png'),fullPage:!!scene.site,animations:'disabled',caret:'hide'});
     report.push(name+' '+width+': '+dump.elements.length+' elements, '+dump.table.length+' styles'+(errors.length?' ERRORS '+errors.join(' | '):''));
     console.log(report.at(-1));
    }catch(e){report.push(name+' '+width+': FAILED '+e.message.split('\n')[0]);console.error(report.at(-1));}
    await context.close();
   }
  }
 }finally{await browser.close();await preview?.close();await dev?.close();}
 fs.writeFileSync(path.join(OUT,'report.txt'),report.join('\n')+'\n');
 if(report.some(l=>l.includes('FAILED')))process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});
