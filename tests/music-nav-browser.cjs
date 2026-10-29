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
  if(width<900)await page.getByRole('button',{name:'Музыкальный плеер',exact:true}).click();else await page.getByRole('button',{name:'Подробности музыки',exact:true}).click();await page.getByText('Подключи сервер Oracle в профиле для воспроизведения музыки.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Музыкальные аккаунты и плейлисты',exact:true}).click();await page.getByRole('combobox',{name:'Музыкальная платформа',exact:true}).selectOption('spotify');await page.getByText('Приложение Spotify',{exact:true}).click();await page.getByRole('textbox',{name:'Spotify Client ID',exact:true}).waitFor();
  assert.equal(await page.locator('input[type=password]').count(),0);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);
  await page.screenshot({path:path.join(DIR,'music-nav-'+width+'.png')});await context.close();console.log('PASS minimized navbar music, no provider widget, server requirement and configured-account UI at '+width+'px');
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const f of['music-nav-harness.html','music-nav-harness.jsx'])await fs.rm(path.join(DIR,f),{force:true});});
