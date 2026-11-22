// Actual application and nested catalogue layout; public providers are fixtures.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
let vite,browser,last;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/library-layout'),base='/.codex-local/test-output/library-layout/';await fs.mkdir(dir,{recursive:true});
 await fs.writeFile(path.join(dir,'index.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="'+base+'fixture.jsx"></script>');
 await fs.writeFile(path.join(dir,'fixture.jsx'),`import React from'react';import{createRoot}from'react-dom/client';import App from'/src/App.jsx';import'/src/styles.css';import'/src/title-page.css';import'/src/import-layout.css';window.MEDIA_VAULT_CONFIG={importServerUrl:'https://fixture.example'};createRoot(document.getElementById('root')).render(<App/>);`);
 const {createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/vite-library-layout',logLevel:'error',server:{watch:null,host:'127.0.0.1',port:5203,strictPort:false}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 for(const width of [390,1024,1669]){
  const page=await browser.newPage({viewport:{width,height:960},reducedMotion:'reduce'});last=page;const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>localStorage.setItem('mediavault_privacy_v1',JSON.stringify({version:1,chosen:true,remember:false})));
  const requestedSorts=[];
  await page.route('https://**/*',r=>{
   const u=new URL(r.request().url());if(u.hostname==='art.fixture'||u.pathname==='/artwork')return r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="240" height="340"><path fill="#3f3546" d="M0 0h240v340H0z"/></svg>'});
   const anime=Array.from({length:8},(_,i)=>({mal_id:20+i,id:20+i,title:'Test '+i,name:'Test '+i,russian:'Тайтл '+i,kind:'tv',type:'TV',episodes:12,year:2024,score:8,status:'released',genres:[],images:{jpg:{large_image_url:'https://art.fixture/p.svg'}},image:{original:'https://art.fixture/p.svg'}}));
   let data={data:[]};
   if(u.pathname.includes('/shikimori')||u.hostname.startsWith('shikimori'))data=anime;
   else if(u.pathname.includes('/jikan')||u.hostname==='api.jikan.moe'||u.hostname==='api.tenrai.org')data={data:anime};
   else if(u.hostname==='graphql.anilist.co'){
    const {variables}=r.request().postDataJSON()||{};
    requestedSorts.push(variables);
    const later=Math.floor(Date.now()/1000)+3600;
    const media=[
     {id:100,format:'TV',title:{romaji:'Upcoming 2050'},seasonYear:2050,status:'NOT_YET_RELEASED',averageScore:99},
     {id:101,format:'TV',title:{romaji:'Episode not out'},status:'RELEASING',episodes:12,nextAiringEpisode:{episode:1,airingAt:later}},
     ...anime.map((a,i)=>({id:a.id,idMal:a.id,format:'TV',title:{romaji:a.name},averageScore:89-i,seasonYear:2024,
      status:i===0?'RELEASING':'FINISHED',nextAiringEpisode:i===0?{episode:2,airingAt:later}:null,coverImage:{large:a.image.original}})),
    ];
    data={data:{Page:{media:variables?.states?media.filter(a=>variables.states.includes(a.status)):media,pageInfo:{lastPage:1}}}};
   }
   return r.fulfill({json:data});
  });
  const app='http://127.0.0.1:'+vite.httpServer.address().port+base+'index.html';
  await page.goto(app+'#library');await page.locator('.online-library .catalog-grid .anime-card-shell').first().waitFor();await page.evaluate(()=>document.fonts.ready);
  const main=await page.locator('.library-workspace-main').boundingBox(),content=await page.locator('.blossom-catalog-content').boundingBox(),cards=page.locator('.catalog-grid .anime-card-shell');
  assert.equal(requestedSorts[0].sort,'TRENDING_DESC');
  assert.ok(requestedSorts[0].states.includes('RELEASING'));
  assert.equal(await cards.count(),8);
  assert.equal(await cards.first().getAttribute('data-title-name'),'Тайтл 0');
  assert.equal(await page.getByText('Upcoming 2050',{exact:true}).count(),0);
  assert.equal(await page.getByText('Episode not out',{exact:true}).count(),0);
  await cards.first().hover();
  await page.waitForFunction(()=>[...document.querySelectorAll('.catalog-grid .title-rating-badge')].some(n=>Number(getComputedStyle(n).opacity)>.95&&n.textContent.includes('8.9')));
  const glass=await page.locator('.kt-nav-inner').evaluate(n=>{const c=getComputedStyle(n.querySelector('.kt-nav-capsule'));return {height:n.getBoundingClientRect().height,filter:c.backdropFilter};});
  assert.match(glass.filter,/blur\(40px\)/,'The bar carries the design glass');
  assert.ok(glass.height<=64,'The bar keeps the design height');
  assert.ok(content.width>=main.width-4,'Catalogue uses its whole main column: '+JSON.stringify({main,content}));
  if(width>=1000){const a=await cards.nth(0).boundingBox(),b=await cards.nth(1).boundingBox();assert.ok(Math.abs(a.y-b.y)<2&&b.x>a.x+a.width,'Cards form a row, rather than a narrow nested sidebar');}
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(dir,'library-'+width+'.png')});
  if(width===1669){
   await page.goto(app+'#profile');
   await page.locator('.cc-nav').getByRole('button',{name:'Оформление'}).click();
   const setting=page.getByRole('switch',{name:'Показывать анонсы'});
   assert.equal(await setting.getAttribute('aria-checked'),'false');
   await setting.click();
   await page.goto(app+'#library');
   await page.getByText('Upcoming 2050',{exact:true}).waitFor();
   assert.equal(requestedSorts.at(-1).sort,'TRENDING_DESC');
   assert.equal(requestedSorts.at(-1).states,undefined);
   await page.reload();
   await page.getByText('Upcoming 2050',{exact:true}).waitFor();
  }
  assert.deepEqual(errors,[]);await page.close();console.log('PASS library grid, trending, release filtering, ratings and matte header '+width);
 }
})().catch(async e=>{console.error(e);await last?.screenshot({path:'.codex-local/test-output/library-layout/failure.png'}).catch(()=>{});process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
