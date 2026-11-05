// Test the built application: production CSS order differs from isolated JSX harnesses.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');let server,browser,last;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/showcase-production');await fs.mkdir(dir,{recursive:true});
 const {preview}=await import('vite');server=await preview({root,preview:{host:'127.0.0.1',port:7924}});
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 for(const [width,height] of [[390,900],[1440,900],[1920,1080],[3440,1232]]){
  const page=await browser.newPage({viewport:{width,height},reducedMotion:'reduce'});last=page;const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>localStorage.setItem('mediavault_privacy_v1',JSON.stringify({version:1,chosen:true,remember:false})));
  await page.route('https://**/*',r=>{
   if(r.request().resourceType()==='script')return r.fulfill({contentType:'application/javascript',body:''});const u=new URL(r.request().url());if(u.pathname==='/artwork'||u.hostname==='art.fixture')return r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="960"><path fill="#544d42" d="M0 0h640v960H0z"/></svg>'});
   const profile={id:16498,russian:'Реинкарнация безработного: История о приключениях в другом мире',name:'Mushoku Tensei',kind:'tv',score:8.5,description:'Описание произведения. Длинный текст должен занимать нормальную колонку, а не превращаться в вертикальный столбец отдельных букв.',aired_on:'2021-01-10',episodes:12,status:'released',rating:'r',image:{original:'https://art.fixture/p.svg'},genres:[{name:'Drama',russian:'Драма'}],studios:[{id:1,name:'Studio Bind'}]};
   if(u.pathname.includes('/shikimori'))return r.fulfill({json:u.searchParams.has('identity')?profile:[]});
   if(u.pathname.includes('/jikan'))return r.fulfill({json:{data:{mal_id:16498,title:profile.name,title_english:profile.name,images:{jpg:{large_image_url:'https://art.fixture/p.svg'}},synopsis:profile.description}}});
   return r.fulfill({json:{data:[],results:[],sources:[],voices:[],providers:[],items:[],pending:false}});
  });
  await page.goto('http://127.0.0.1:7924/#watch=anime:shikimori:16498');await page.getByRole('heading',{name:'Реинкарнация безработного: История о приключениях в другом мире',exact:true}).waitFor({state:'attached'});await page.evaluate(()=>document.fonts.ready);
  const hero=await page.locator('.title-showcase').boundingBox(),content=await page.locator('.title-showcase-content').boundingBox(),copy=await page.locator('.title-hero-copy').boundingBox();
  if(width>=1000){assert.ok(copy.width>=350,'Description column stays readable in built CSS: '+JSON.stringify({width,hero,content,copy}));assert.ok(content.width>hero.width-160,'Scene content uses the viewport width');assert.ok(content.y+content.height<=height+1,'Content fits the first-screen scene');}
  const layers=await page.evaluate(async()=>{
   scrollTo(0,300);await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
   const shell=document.querySelector('.app-shell'),main=shell.querySelector('.app-main'),nav=shell.querySelector('.blossom-navbar'),search=nav.querySelector('.header-search');
   const r=search.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2;
   const top=()=>document.elementFromPoint(x,y),overlay=(className,parent,style)=>{const node=document.createElement('div');node.className=className;Object.assign(node.style,style);parent.append(node);return node;};
   const player=overlay('retained-media-host',document.body,{position:'absolute',left:'0',top:scrollY+'px',width:'100vw',height:'160px'});
   player.dataset.mode='attached';
   const section=overlay('title-chapter-layer-probe',main,{position:'fixed',inset:'0',zIndex:'150'});
   const preview=overlay('anime-preview is-portal',document.body,{inset:'0',transform:'none',pointerEvents:'auto'});
   const headerOnTop=nav.contains(top());
   const reader=overlay('immersive-reader',shell,{});
   const readerOnTop=reader===top();
   reader.remove();
   const modal=overlay('dialog-overlay',document.body,{});
   const dialogOnTop=modal===top();
   [player,section,preview,modal].forEach(node=>node.remove());
   return {headerOnTop,readerOnTop,dialogOnTop};
  });
  assert.deepEqual(layers,{headerOnTop:true,readerOnTop:true,dialogOnTop:true},'Navbar stays above page content and below immersive overlays at '+width);
  await page.evaluate(()=>scrollTo(0,0));
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(dir,'title-'+width+'.png')});
  await page.goto('http://127.0.0.1:7924/?manga-fixture#watch=manga:shikimori:16498');
  await page.locator('.retained-media-host[data-mode=attached] .manga-playback-controls .title-playback-selectors').first().waitFor({timeout:7000});
  const searchAboveManga=await page.evaluate(async()=>{
   const search=document.querySelector('.header-search'),filters=document.querySelector('.retained-media-host[data-mode=attached] .manga-playback-controls .title-playback-selectors');
   const f=filters.getBoundingClientRect(),r=search.getBoundingClientRect();
   scrollBy(0,f.top+f.height/2-(r.top+r.height/2));
   await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   const p=search.getBoundingClientRect();return search.contains(document.elementFromPoint(p.left+p.width/2,p.top+p.height/2));
  });
  assert.ok(searchAboveManga,'Search stays clickable while manga source filters scroll beneath it at '+width);
  assert.deepEqual(errors,[]);await page.close();console.log('PASS built title layout and navbar layers over anime and manga '+width);
 }
})().catch(async e=>{console.error(e);await last?.screenshot({path:'.codex-local/test-output/showcase-production/failure.png'}).catch(()=>{});process.exitCode=1;}).finally(async()=>{await browser?.close();await server?.httpServer.close();});
