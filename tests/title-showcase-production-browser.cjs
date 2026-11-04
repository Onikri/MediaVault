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
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);await page.screenshot({path:path.join(dir,'title-'+width+'.png')});await page.close();console.log('PASS built title route, content columns and first screen '+width);
 }
})().catch(async e=>{console.error(e);await last?.screenshot({path:'.codex-local/test-output/showcase-production/failure.png'}).catch(()=>{});process.exitCode=1;}).finally(async()=>{await browser?.close();await server?.httpServer.close();});
