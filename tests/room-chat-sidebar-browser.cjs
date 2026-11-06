// Real React player inside a retained-media slot on a title layout, a real
// watch_rooms backend: the host's room chat must move into the right column
// (ratings slide below it) and the player must keep the full main width.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),https=require('node:https'),{spawn,execFileSync}=require('node:child_process'),{chromium}=require('playwright');
let browser,vite,backend,last,log;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/room-chat-sidebar'),base='/.codex-local/test-output/room-chat-sidebar/',python=process.env.PYTHON||'python';await fs.mkdir(dir,{recursive:true});
 execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=12','-t','20','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart','-y',path.join(dir,'fixture.mp4')]);
 await fs.writeFile(path.join(dir,'cert.py'),`from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pathlib import Path
import datetime,ipaddress
p=Path(__file__).resolve().parent;k=rsa.generate_private_key(public_exponent=65537,key_size=2048);n=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
now=datetime.datetime.now(datetime.timezone.utc)
c=x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=2)).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(k,hashes.SHA256())
(p/'key.pem').write_bytes(k.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.TraditionalOpenSSL,serialization.NoEncryption()));(p/'cert.pem').write_bytes(c.public_bytes(serialization.Encoding.PEM))
`);execFileSync(python,[path.join(dir,'cert.py')]);
 await fs.writeFile(path.join(dir,'fixture_api.py'),`from fastapi import FastAPI,Header,HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import watch_rooms
app=FastAPI();app.add_middleware(CORSMiddleware,allow_origins=[os.environ['ALLOWED_ORIGIN']],allow_methods=['*'],allow_headers=['*'],expose_headers=['Content-Range','Accept-Ranges','Content-Length'])
def owner(authorization:str=Header(default='')):
 if authorization!='Bearer fixture':raise HTTPException(401)
 return 'fixture'
watch_rooms.install(app,owner)
@app.get('/health')
def health():return {'ok':True}
`);
 const {createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/vite-room-chat-sidebar',logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();const origin='http://127.0.0.1:'+vite.httpServer.address().port;
 const net=require('node:net'),port=await new Promise(r=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>r(n));});}),server='https://127.0.0.1:'+port;
 log=await fs.open(path.join(dir,'api.log'),'w');backend=spawn(python,['-m','uvicorn','fixture_api:app','--host','127.0.0.1','--port',String(port),'--ssl-keyfile',path.join(dir,'key.pem'),'--ssl-certfile',path.join(dir,'cert.pem'),'--no-access-log'],{cwd:root,windowsHide:true,env:{...process.env,PYTHONPATH:[path.join(root,'server'),dir].join(path.delimiter),ALLOWED_ORIGIN:origin},stdio:['ignore',log.fd,log.fd]});
 for(let i=0;i<100;i++){try{await new Promise((resolve,reject)=>https.get(server+'/health',{rejectUnauthorized:false},res=>{res.resume();res.statusCode===200?resolve():reject();}).on('error',reject));break;}catch{await new Promise(r=>setTimeout(r,100));if(i===99)throw Error('Fixture API did not start');}}
 await fs.writeFile(path.join(dir,'index.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="'+base+'fixture.jsx"></script>');
 const size=(await fs.stat(path.join(dir,'fixture.mp4'))).size;
 await fs.writeFile(path.join(dir,'fixture.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';import Player from'/src/MediaVaultPlayer.jsx';import{RetainedMediaProvider,RetainedMediaSlot}from'/src/RetainedMedia.jsx';import'/src/styles.css';import'/src/title-page.css';import'/src/watch-page.css';import'/src/interface-refinement.css';
 window.MEDIA_VAULT_CONFIG={importServerUrl:${JSON.stringify(server)}};
 const item={id:'room-chat-fixture',name:'Совместный просмотр',category:'video',size:${size}};
 const service={server:${JSON.stringify(server)},request:async(path,options={})=>{const r=await fetch(${JSON.stringify(server)}+path,{method:options.method||'GET',headers:{'Authorization':'Bearer fixture','Content-Type':'application/json'},body:options.body?JSON.stringify(options.body):undefined}),d=await r.json();if(!r.ok)throw Error(d.detail);return d;}};
 const App=()=><RetainedMediaProvider><article className="title-page watch-title-page" style={{maxWidth:1320,margin:'0 auto',padding:16}}><div className="title-page-columns mv-title-layout"><div className="title-page-main"><section id="titlePlayback" className="title-playback"><RetainedMediaSlot id="fixture-player" label="Фикстура"><Player apiRef={api=>window.player=api} autoPlay characterService={service} item={item} source=${JSON.stringify(base+'fixture.mp4')} catalog={{items:[item]}} userId="fixture" libraryId="fixture"/></RetainedMediaSlot></section></div>
  <aside className="title-sidebar"><section className="title-rating-section"><div className="title-rating"><h3>Твоя оценка</h3><p>Как тебе эта история?</p></div></section><section className="platform-ratings" id="fixtureRatings"><h2>Оценки зрителей</h2><p>Шикимори 6,15</p></section></aside></div></article></RetainedMediaProvider>;
 createRoot(document.getElementById('root')).render(<ThemeProvider><App/></ThemeProvider>);
 `);
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--ignore-certificate-errors','--autoplay-policy=no-user-gesture-required','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']});
 const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[];last=page;page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://**/*',r=>r.request().url().startsWith(server)?r.continue():r.fulfill({json:{data:[]}}));await page.goto(origin+base+'index.html');await page.waitForFunction(()=>window.player?.media.readyState>=2);
 const main=await page.locator('.title-page-main').boundingBox(),before=await page.locator('.mv-player').first().boundingBox(),ratingsBefore=await page.locator('#fixtureRatings').boundingBox();
 assert.ok(await page.locator('.mv-player').first().evaluate(n=>!!n.closest('.retained-media-host')),'The fixture uses the retained (body-portalled) player like the real title page');
 await page.locator('.mv-player').first().hover();await page.getByRole('button',{name:'Настройки плеера',exact:true}).click({force:true});
 const together=page.locator('button.mvx-row').filter({hasText:'Смотреть вместе'}).first();await together.scrollIntoViewIfNeeded();
 if(await together.getAttribute('aria-expanded')!=='true')await together.click();
 await page.getByLabel('Пароль новой комнаты',{exact:true}).waitFor({state:'visible'});
 await page.getByLabel('Пароль новой комнаты',{exact:true}).fill('room-pass');await page.getByRole('button',{name:'Создать комнату',exact:true}).click();await page.getByLabel('Ссылка комнаты',{exact:true}).waitFor();
 await page.evaluate(()=>window.player.openPanel('watch'));
 const chat=page.locator('.title-sidebar > .room-chat-slot .player-room-conversation');await chat.waitFor({state:'visible',timeout:5000});await page.waitForTimeout(700);
 assert.equal(await page.locator('.player-room-layout.has-live-room').count(),0,'The player no longer shares its row with the chat');
 const after=await page.locator('.mv-player').first().boundingBox(),slot=await page.locator('.room-chat-slot').boundingBox(),side=await page.locator('.title-sidebar').boundingBox(),ratings=await page.locator('#fixtureRatings').boundingBox();
 assert.ok(after.width>=main.width-4,'Player keeps the main column width: '+after.width+' / '+main.width);
 assert.ok(Math.abs(after.width-before.width)<4,'Player width is unchanged by the room');
 assert.ok(Math.abs(slot.x-side.x)<2&&Math.abs(slot.width-side.width)<2,'Chat fills the right column');
 assert.ok(slot.y<=ratingsBefore.y+2&&ratings.y>slot.y+slot.height-2,'Ratings slid below the chat');
 assert.ok(slot.height>300,'Chat is fully expanded after the animation: '+slot.height);
 await chat.getByLabel('Сообщение в комнате').fill('Привет из колонки');await chat.getByRole('button',{name:'Отправить сообщение',exact:true}).click();await chat.getByText('Привет из колонки').waitFor();
 await page.screenshot({path:path.join(dir,'room-chat-sidebar.png')});
 // Narrow screens hide the column: the chat must fall back next to the player.
 await page.setViewportSize({width:820,height:1000});await page.waitForTimeout(600);
 const hidden=await page.locator('.title-sidebar').evaluate(n=>getComputedStyle(n).display==='none');
 if(hidden){assert.equal(await page.locator('.room-chat-slot .player-room-conversation').count(),0);assert.equal(await page.locator('.player-room-conversation').count(),1);}
 await page.setViewportSize({width:1440,height:1000});await page.waitForTimeout(600);await chat.waitFor({state:'visible'});
 assert.deepEqual(errors,[]);console.log('PASS room chat takes the title column, ratings slide below, player keeps its width');
 await context.close();
})().catch(async e=>{console.error(e);await last?.screenshot({path:path.join(process.cwd(),'.codex-local/test-output/room-chat-sidebar/failure.png')}).catch(()=>{});process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();backend?.kill();await log?.close();});
