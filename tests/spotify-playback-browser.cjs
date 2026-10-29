// Actual PKCE/playlist UI, with fixture Spotify API and Oracle media preparation.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');const{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'test-output');let browser,vite;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});await fs.writeFile(path.join(DIR,'spotify-player-harness.html'),'<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/test-output/spotify-player-harness.jsx"></script></html>');
 await fs.writeFile(path.join(DIR,'spotify-player-harness.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import MiniMusicPlayer from'/src/MiniMusicPlayer.jsx';import MusicConnections from'/src/MusicConnections.jsx';import'/src/styles.css';
 window.MEDIA_VAULT_CONFIG={spotifyClientId:'123456789012345678901234567890ab'};window.MEDIA_VAULT_CONFIG.importServerUrl=location.origin;window.spotifySDKLoaded=0;window.Spotify={Player:class{constructor(){window.spotifySDKLoaded++;throw Error('Browser SDK playback is forbidden');}}};
 const service={server:location.origin,request:async(path,options={})=>{const r=await fetch(path,{method:options.method||'GET',body:options.body?JSON.stringify(options.body):undefined,headers:{'Content-Type':'application/json'}});const d=await r.json();if(!r.ok)throw Object.assign(Error(d.detail),{status:r.status});return d;}};

 createRoot(document.getElementById('root')).render(<><header style={{display:'flex',justifyContent:'flex-end',padding:20}}><MiniMusicPlayer service={service} placement="nav" userId="spotify-test"/></header><main style={{padding:20,maxWidth:700}}><MusicConnections/></main></>);
 `);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1280,height:950}}),page=await context.newPage(),errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));
 const headers={'access-control-allow-origin':'*','access-control-allow-headers':'*','access-control-allow-methods':'*'};
 await context.route('**/spotify-callback.html?**',async r=>r.fulfill({contentType:'text/html',body:await fs.readFile(path.join(ROOT,'spotify-callback.html'),'utf8')}));
 await context.route('https://accounts.spotify.com/authorize?**',r=>{const u=new URL(r.request().url());assert.equal(u.searchParams.get('code_challenge_method'),'S256');assert.ok(!u.searchParams.get('scope').split(' ').includes('streaming'));assert.ok(!u.searchParams.get('scope').split(' ').includes('user-modify-playback-state'));const url=u.searchParams.get('redirect_uri')+'?'+new URLSearchParams({state:u.searchParams.get('state'),code:'fixture-code'});return r.fulfill({contentType:'text/html',body:'<script>location.replace('+JSON.stringify(url)+');<\/script>'});});
 await context.route('https://accounts.spotify.com/api/token',r=>r.request().method()==='OPTIONS'?r.fulfill({status:204,headers}):r.fulfill({headers,json:{access_token:'fixture-sdk-token',expires_in:3600}}));
 await context.route('https://api.spotify.com/v1/**',r=>{
  if(r.request().method()==='OPTIONS')return r.fulfill({status:204,headers});const u=new URL(r.request().url()),method=r.request().method(),body=r.request().postDataJSON();requests.push({path:u.pathname,method,body});assert.equal(r.request().headers().authorization,'Bearer fixture-sdk-token');
  assert.ok(!u.pathname.startsWith('/v1/me/player'),'Spotify must not receive playback requests');
  if(u.pathname==='/v1/me/playlists'&&method==='POST'){assert.deepEqual(body,{name:'Мои опенинги',public:false});return r.fulfill({headers,json:{id:'new-private',name:body.name}});}
  if(u.pathname.endsWith('/items'))return r.fulfill({headers,json:{items:[{item:{uri:'spotify:track:FixtureTrack123',name:'Fixture Song',artists:[{name:'Fixture Artist'}],album:{images:[]}}}]}});
  return r.fulfill({headers,json:{items:[{id:'my-list',name:'Сохранённая музыка'}]}});
 });
 let oraclePreparations=0;await page.route('**/music/search?**',r=>{const u=new URL(r.request().url());assert.equal(u.searchParams.get('title'),'Fixture Song');return r.fulfill({json:{results:[{id:'01234567890',title:'Fixture Song',author:'Fixture Artist',match:true}]}});});await page.route('**/music/metadata?**',r=>r.fulfill({json:{found:false}}));await page.route('**/music/play',r=>{oraclePreparations++;assert.equal(r.request().postDataJSON().url,'https://www.youtube.com/watch?v=01234567890');return r.fulfill({status:502,json:{detail:'Oracle fixture unavailable'}});});await page.route('https://i.ytimg.com/**',r=>r.abort());
 await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/spotify-player-harness.html');
 const profile=page.locator('main .music-connections');await profile.getByRole('combobox',{name:'Музыкальная платформа',exact:true}).selectOption('spotify');await profile.getByRole('button',{name:'Подключить Spotify',exact:true}).click();await profile.getByRole('combobox',{name:'Плейлист музыкальной платформы',exact:true}).waitFor();
 await profile.getByRole('textbox',{name:'Название нового музыкального плейлиста',exact:true}).fill('Мои опенинги');await profile.getByRole('button',{name:'Создать плейлист',exact:true}).click();await profile.getByText('Плейлист создан на платформе.',{exact:true}).waitFor();
 await profile.getByRole('button',{name:'Открыть песни плейлиста',exact:true}).click();await profile.getByRole('button',{name:'Fixture Song',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.music-dock-error')?.textContent==='Oracle fixture unavailable');
 assert.equal(oraclePreparations,1);assert.equal(await page.locator('iframe').count(),0);assert.equal(await page.evaluate(()=>window.spotifySDKLoaded),0);assert.equal(await page.locator('.music-panel').getAttribute('aria-hidden'),'true');
 await profile.getByRole('button',{name:'Отключить',exact:true}).click();assert.ok((await page.evaluate(()=>Object.values(localStorage))).every(v=>!String(v).includes('fixture-sdk-token')),'OAuth token never persists');assert.deepEqual(errors,[]);
 await context.close();console.log('PASS Spotify PKCE playlist scopes and private playlists; selected songs use Oracle with no browser SDK or iframe');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const f of['spotify-player-harness.html','spotify-player-harness.jsx'])await fs.rm(path.join(DIR,f),{force:true});});
