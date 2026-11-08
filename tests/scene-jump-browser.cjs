// Frame search hand-off: the title page must pick a voice that has the episode,
// start it by itself at the found second. When the browser refuses autoplay,
// the player is scrolled into view, paused at that second, and Play resumes there. Sources and leases are fixtures; the
// video is real and decoded by Chromium.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
let browser,vite,last;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/scene-jump'),base='/.codex-local/test-output/scene-jump/';await fs.mkdir(dir,{recursive:true});
 execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=8','-f','lavfi','-i','sine=frequency=440:duration=20','-t','20','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-shortest','-movflags','+faststart','-y',path.join(dir,'fixture.mp4')]);
 await fs.writeFile(path.join(dir,'index.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="'+base+'fixture.jsx"></script>');
 await fs.writeFile(path.join(dir,'fixture.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import OnlineWatch from'/src/OnlineWatch.jsx';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';import'/src/styles.css';import'/src/title-page.css';
 window.MEDIA_VAULT_CONFIG={};window.prepared=[];
 const item={id:'shikimori:29787',title:'Сценический тест',kind:'anime',ids:{mal:'29787'}},profile={cover:'',episodeImages:{}};
 const episodes=n=>Array.from({length:n},(_,i)=>({number:i+1,season:1}));
 const short={id:'short',name:'Короткая озвучка',kind:'voice',language:'ru',variants:[{id:'short',player:'Kodik',url:'https://source.example/short',sourceUrl:'https://source.example/title',episodes:episodes(3)}]};
 const full={id:'full',name:'Полная озвучка',kind:'voice',language:'ru',variants:[{id:'full',player:'Kodik',url:'https://source.example/full',sourceUrl:'https://source.example/title',episodes:episodes(6)}]};
 const discovery={data:{voices:[short,full]},loading:false};
 const service={server:location.origin,request:async(p,{body={}}={})=>{
  if(p==='/sources/inspect'){const n=body.dub_url?.endsWith('/full')?6:3;return{seasons:[{number:1,name:'Сезон 1'}],episodes:Array.from({length:n},(_,i)=>({number:i+1,season:1,title:'Серия '+(i+1),url:body.dub_url+'/'+(i+1)}))};}
  if(p==='/online/prepare'){window.prepared.push(body.url);return{id:'lease-'+window.prepared.length,type:'mp4',url:'${base}fixture.mp4?lease='+window.prepared.length,qualities:[720]};}
  if(p.startsWith('/metadata/watch-order'))return{items:[],seasons:[]};
  return{};
 }};
 createRoot(document.getElementById('root')).render(<ThemeProvider><main className="app-main" style={{width:'100%',maxWidth:1000,margin:'0 auto'}}><OnlineWatch item={item} profile={profile} discovery={discovery} service={service} userId="test"/></main></ThemeProvider>);
 `);
 const {createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/vite-scene-jump',logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 // Both browser policies: autoplay allowed (plays by itself) and a click
 // required (waits paused at the moment). No user gesture precedes the jump.
 for(const [policy,width] of [['no-user-gesture-required',1440],['document-user-activation-required',390],['document-user-activation-required',1440]]){
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});const allowed=policy==='no-user-gesture-required';
  const page=await browser.newPage({viewport:{width,height:1000},reducedMotion:'reduce'}),errors=[];last=page;page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(15000);
  // Headless Chrome ignores --autoplay-policy; reproduce the real refusal: unmuted
  // play() rejects with NotAllowedError until the viewer clicks.
  if(!allowed)await page.addInitScript(()=>{let activated=false;addEventListener('pointerdown',()=>{activated=true;},true);const play=HTMLMediaElement.prototype.play;HTMLMediaElement.prototype.play=function(){return activated||this.muted?play.call(this):Promise.reject(new DOMException('play() requires a user gesture','NotAllowedError'));};});
  // WTAS.moe background music for episode 5: a track that covers the found second.
  await page.route('**/music/ost/29787/5',route=>route.fulfill({json:{available:true,pending:false,episodeDuration:20,tracks:[{title:'Scene Theme',album:'Fixture OST',start:3,end:15,confidence:.05,uncertain:false,spotify:'1234567890abcdefABCDEF'},{title:'Noise',album:'Fixture OST',start:4,end:9,confidence:.002,uncertain:true,spotify:null}]}}));
  await page.addInitScript(()=>{try{if(!sessionStorage.getItem('jump-seeded')){sessionStorage.setItem('jump-seeded','1');sessionStorage.setItem('mv_scene_jump_v1',JSON.stringify({mal:'29787',episode:5,time:6,at:Date.now()}));}}catch{}});
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+base+'index.html');
  await page.waitForFunction(()=>{const v=document.querySelector('video.mv-player-media');return v&&v.readyState>=2&&v.currentTime>=5.5;});
  await page.waitForTimeout(1600);
  const state=await page.evaluate(()=>{const v=document.querySelector('video.mv-player-media'),r=document.querySelector('.mv-player').getBoundingClientRect();return {time:v.currentTime,paused:v.paused,muted:v.muted,inView:r.top<innerHeight&&r.bottom>0,prepared:window.prepared,jump:sessionStorage.getItem('mv_scene_jump_v1')};});
  if(allowed){assert.equal(state.paused,false,'Allowed autoplay starts by itself');
   const cue=page.locator('.mvx-song');await cue.waitFor();const cueText=await cue.innerText();
   assert.ok(cueText.includes('Scene Theme')&&cueText.includes('Сейчас звучит')&&!cueText.includes('Noise'),'Background track at this second is shown, uncertain ones are not: '+cueText);
   assert.equal(await cue.locator('a[href="https://open.spotify.com/track/1234567890abcdefABCDEF"]').count(),1,'Official Spotify track link');assert.ok(state.time>=6&&state.time<9,'Plays from the found second: '+state.time);}
  else{assert.ok(state.time>=5.5&&state.time<6.5,'Timeline is set to the found second: '+JSON.stringify(state));assert.equal(state.paused,true,'Refused autoplay waits for Play');}
  assert.equal(state.muted,false,'No silent fallback');
  assert.ok(state.inView,'The player is scrolled into view');
  assert.deepEqual(state.prepared,['https://source.example/full/5'],'Skips the voice without episode 5 and prepares exactly episode 5: '+JSON.stringify(state.prepared));
  assert.equal(state.jump,null,'The hand-off is consumed once');
  if(!allowed){const hit=await page.evaluate(()=>{const b=[...document.querySelectorAll('.mvx-primary')].find(x=>/Продолжить/.test(x.textContent));const r=b.getBoundingClientRect();const top=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);const c=document.querySelector('.mvx-console').getBoundingClientRect();return {btn:[r.y,r.bottom],console:[c.y,c.bottom],top:top.className||top.tagName,inside:b.contains(top)};});assert.ok(hit.inside,'Continue button is tappable, not covered by the controls '+JSON.stringify(hit));assert.ok(await page.getByRole('button',{name:/^Продолжить с 00:0[56]$/}).isVisible(),'The player offers to continue from the found moment');
   await page.getByRole('button',{name:/^Продолжить с 00:0[56]$/}).click();
   await page.waitForFunction(()=>!document.querySelector('video.mv-player-media').paused);
   const resumed=await page.evaluate(()=>document.querySelector('video.mv-player-media').currentTime);
   assert.ok(resumed>=5.5&&resumed<8,'Play starts from the found moment: '+resumed);}
  assert.deepEqual(errors,[]);
  console.log('PASS scene jump ('+(allowed?'autoplay allowed':'click required')+') picks the voice with the episode, sets the timeline, shows the player and plays from that second at '+width);
  await page.close();await browser.close();browser=null;
 }
})().catch(async e=>{console.error(e);process.exitCode=1;try{await last?.screenshot({path:path.join(process.cwd(),'.codex-local/test-output/scene-jump/failure.png'),fullPage:true});}catch{}}).finally(async()=>{await browser?.close();await vite?.close();});
