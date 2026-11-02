// Provider API/SDK responses are fixtures; DOM, lifecycle, sizes and controls are real.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');const{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'test-output');let browser,vite;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});
 await fs.writeFile(path.join(DIR,'music-nav-harness.html'),'<html lang="ru"><meta name="viewport" content="width=device-width, initial-scale=1"><div id="root"></div><script type="module" src="/test-output/music-nav-harness.jsx"></script></html>');
 await fs.writeFile(path.join(DIR,'music-nav-harness.jsx'),`
 import React from 'react';import{createRoot}from'react-dom/client';import MiniMusicPlayer from'/src/MiniMusicPlayer.jsx';import{TrackList}from'/src/Soundtrack.jsx';import'/src/styles.css';
 window.MEDIA_VAULT_CONFIG={importServerUrl:location.origin};
 createRoot(document.getElementById('root')).render(<><header style={{display:'flex',justifyContent:'flex-end',gap:12,padding:18,position:'relative',zIndex:30}}><MiniMusicPlayer placement="nav" userId="music-user"/><button>Профиль</button></header><main style={{padding:20}}><TrackList values={[{id:'nav:otonoke',title:'Otonoke',artists:['Creepy Nuts'],type:'OP'}]} userId="music-user"/></main></>);
 `);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 for(const width of[360,1440]){
  const context=await browser.newContext({viewport:{width,height:900}}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/music/search?**',r=>r.fulfill({json:{results:[{id:'01234567890',title:'Otonoke Official',author:'Creepy Nuts',match:true}]}}));
  await page.route('**/music/metadata?**',r=>r.fulfill({json:{found:true,title:'Otonoke',artists:['Creepy Nuts'],album:'Otonoke',date:'2024-10-04',cover:'',url:'https://musicbrainz.org/recording/11111111-1111-1111-1111-111111111111'}}));
  await page.route('https://i.ytimg.com/**',r=>r.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a+kkAAAAASUVORK5CYII=','base64')}));
  let providerRequests=0;await page.route(/https:\/\/(?:www\.)?youtube(?:-nocookie)?\.com\//,r=>{providerRequests++;return r.abort();});
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/music-nav-harness.html');
  await page.getByRole('button',{name:'Слушать Otonoke',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.music-dock-error')?.textContent);assert.equal(await page.locator('.music-panel').getAttribute('aria-hidden'),'true');assert.equal(await page.locator('iframe').count(),0);assert.equal(providerRequests,0);
  if(width>=900){
   const nav=page.locator('.music-nav.has-track'),before=await nav.boundingBox();
   const backgroundBefore=await page.locator('.music-nav .music-bar').evaluate(el=>getComputedStyle(el).backgroundColor);
   await page.locator('.music-nav .music-bar').hover();
   await page.waitForTimeout(430);
   const after=await nav.boundingBox(),island=await page.locator('.music-nav .music-bar').boundingBox();
   assert.equal(Math.round(before.width),Math.round(after.width),'hover must not reflow navbar');
   assert.equal(Math.round(island.height),Math.round(before.height),'music island stays in one row');
   assert.ok(island.width>before.width+70,'music island expands only horizontally');
   assert.equal(await page.locator('.music-nav .music-bar').evaluate(el=>getComputedStyle(el).backgroundColor),backgroundBefore,'hover must not change player color');
   assert.equal(await page.locator('.music-nav .music-dock-title small').textContent(),'Creepy Nuts');
   assert.ok(await page.locator('.music-bar-transport .music-dock-timeline').isVisible(),'timeline replaces song metadata on hover');
   assert.equal(await page.locator('.music-nav .music-expand').count(),0,'mini player no longer wastes a slot on an expand button');
   const knob=page.getByRole('slider',{name:'Громкость музыки в шапке'});
   assert.ok(await knob.isVisible(),'volume knob takes the permanent mini-player action slot');
   const volumeBefore=Number(await knob.getAttribute('aria-valuenow'));
   await knob.hover();await page.mouse.wheel(0,-120);
   await page.waitForFunction(v=>Number(document.querySelector('.music-volume-knob')?.getAttribute('aria-valuenow'))>v,volumeBefore);
   await knob.click(); // Clicking an interactive control must not pin hover after mouseleave.
   await page.mouse.move(4,400);
   await page.waitForFunction(()=>!document.querySelector('.music-nav .music-bar')?.classList.contains('is-hovered'),null,{timeout:2500});
   await page.waitForTimeout(420);
   const closed=await page.locator('.music-nav .music-bar').boundingBox();
   const diagnostic=await page.locator('.music-nav .music-bar').evaluate(el=>({className:el.className,width:getComputedStyle(el).width,focus:document.activeElement?.getAttribute('aria-label'),hover:el.matches(':hover')}));
   assert.equal(Math.round(closed.width),Math.round(before.width),'island collapses after pointer leaves: '+JSON.stringify(diagnostic));
   assert.equal(Math.round(closed.height),Math.round(before.height),'island never grows vertically');
   await page.locator('.music-nav .music-disc').first().click();
   await page.locator('.music-nav .music-bar.is-nav-expanded').waitFor();
   await page.waitForTimeout(540);
   const full=await page.locator('.music-nav .music-bar').boundingBox(),header=await page.locator('header').boundingBox();
   assert.ok(full.width>=296,'expanded island becomes approximately the right quarter of navbar');
   assert.equal(Math.round(full.height),38,'expanded island matches logo/search capsule height');
   assert.ok(Math.abs(full.x+full.width-header.x-header.width)<2,'expanded island touches right edge of navbar');
   assert.equal(await page.locator('.music-bar-full').getAttribute('aria-hidden'),'false');
   const expandedMaterial=await page.locator('.music-nav .music-bar').evaluate(el=>({border:getComputedStyle(el).borderTopWidth,blur:getComputedStyle(el).backdropFilter,background:getComputedStyle(el).backgroundColor}));
   assert.equal(expandedMaterial.border,'0px','large player has no visible outline');
   assert.ok(expandedMaterial.blur.includes('blur(24px)'),'expanded navbar music is dark glass rather than solid black');
   await page.locator('.music-bar-full .music-full-copy').click({force:true});
   await page.locator('.music-nav .music-bar.is-nav-expanded').waitFor({state:'detached'});
  }else assert.equal(await page.locator('.music-nav>.music-bar').isVisible(),false,'mobile navbar uses the icon');
  if(width<900){
   await page.getByRole('button',{name:'Музыкальный плеер',exact:true}).click();
   await page.getByText('Подключи сервер Oracle в профиле для воспроизведения музыки.',{exact:true}).waitFor();
   await page.getByRole('button',{name:'Музыкальные аккаунты и плейлисты',exact:true}).click();
   await page.getByRole('combobox',{name:'Музыкальная платформа',exact:true}).selectOption('spotify');
   await page.getByText('Приложение Spotify',{exact:true}).click();
   await page.getByRole('textbox',{name:'Spotify Client ID',exact:true}).waitFor();
   assert.equal(await page.locator('input[type=password]').count(),0);
  }
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);
  await page.screenshot({path:path.join(DIR,'music-nav-'+width+'.png')});await context.close();console.log('PASS minimized navbar music, no provider widget, server requirement and configured-account UI at '+width+'px');
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const f of['music-nav-harness.html','music-nav-harness.jsx'])await fs.rm(path.join(DIR,f),{force:true});});
