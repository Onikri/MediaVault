// Real React + two browser pages + actual room WebSockets/Range relay.
// Video and catalogue data are fixtures. SPAN inference uses real pinned weights.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),https=require('node:https'),{spawn,execFileSync}=require('node:child_process'),{chromium}=require('playwright');
let browser,vite,backend,last,log;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/interface-rooms'),base='/.codex-local/test-output/interface-rooms/';await fs.mkdir(dir,{recursive:true});
 execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=12','-t','25','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart','-y',path.join(dir,'fixture.mp4')]);
 await fs.writeFile(path.join(dir,'cert.py'),`from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pathlib import Path
import datetime,ipaddress
p=Path(__file__).resolve().parent;k=rsa.generate_private_key(public_exponent=65537,key_size=2048);n=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')]);c=x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=1)).not_valid_after(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=2)).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),False).sign(k,hashes.SHA256());(p/'key.pem').write_bytes(k.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));(p/'cert.pem').write_bytes(c.public_bytes(serialization.Encoding.PEM))
`);execFileSync('python',[path.join(dir,'cert.py')]);
 await fs.writeFile(path.join(dir,'fixture_api.py'),`from fastapi import FastAPI,Header,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import os
import watch_rooms
app=FastAPI();app.add_middleware(CORSMiddleware,allow_origins=[os.environ['ALLOWED_ORIGIN']],allow_methods=['*'],allow_headers=['*'],expose_headers=['Content-Range','Accept-Ranges','Content-Length'])
def owner(authorization:str=Header(default='')):
 if authorization!='Bearer fixture':raise HTTPException(401)
 return 'fixture'
watch_rooms.install(app,owner)
@app.get('/health')
def health():return {'ok':True}
@app.get('/models/{name}')
def model(name:str):return FileResponse(Path(os.environ['MODEL_FILE']),media_type='application/octet-stream')
app.mount('/lmt',StaticFiles(directory=os.environ['ORT_ROOT']),name='runtime')
`);
 const {createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/vite-interface-rooms',logLevel:'error',optimizeDeps:{include:['onnxruntime-web/wasm']},server:{host:'127.0.0.1',port:0}});await vite.listen();const origin='http://127.0.0.1:'+vite.httpServer.address().port;
 const net=require('node:net'),port=await new Promise(r=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>r(n));});}),server='https://127.0.0.1:'+port;
 log=await fs.open(path.join(dir,'api.log'),'w');backend=spawn('python',['-m','uvicorn','fixture_api:app','--host','127.0.0.1','--port',String(port),'--ssl-keyfile',path.join(dir,'key.pem'),'--ssl-certfile',path.join(dir,'cert.pem'),'--no-access-log'],{cwd:root,windowsHide:true,env:{...process.env,PYTHONPATH:[path.join(root,'.codex-local/tools/python'),path.join(root,'server'),dir].join(path.delimiter),ALLOWED_ORIGIN:origin,MODEL_FILE:path.join(root,'.codex-local/models/illustration-span-fp32.onnx'),ORT_ROOT:path.join(root,'dist/lmt')},stdio:['ignore',log.fd,log.fd]});
 for(let i=0;i<80;i++){try{await new Promise((resolve,reject)=>https.get(server+'/health',{rejectUnauthorized:false},res=>{res.resume();res.statusCode===200?resolve():reject();}).on('error',reject));break;}catch{await new Promise(r=>setTimeout(r,100));if(i===79)throw Error('Fixture API did not start');}}
 await fs.writeFile(path.join(dir,'index.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="'+base+'fixture.jsx"></script>');
 const size=(await fs.stat(path.join(dir,'fixture.mp4'))).size;
 await fs.writeFile(path.join(dir,'fixture.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import{ThemeProvider}from'/src/blossom/ThemeProvider.tsx';import Player from'/src/MediaVaultPlayer.jsx';import Room from'/src/WatchRoomPage.jsx';import{AnimeCard}from'/src/blossom/components/AnimeCard.tsx';import'/src/styles.css';import'/src/title-page.css';import'/src/interface-refinement.css';
 window.MEDIA_VAULT_CONFIG={importServerUrl:${JSON.stringify(server)}};const identity=new URLSearchParams(location.hash.slice(1)).get('room');
 const item={id:'room-fixture-v1',name:'Совместный просмотр',category:'video',size:${size}};
 const service={server:${JSON.stringify(server)},request:async(path,options={})=>{const r=await fetch(${JSON.stringify(server)}+path,{method:options.method||'GET',headers:{'Authorization':'Bearer fixture','Content-Type':'application/json'},body:options.body?JSON.stringify(options.body):undefined}),d=await r.json();if(!r.ok)throw Error(d.detail);return d;}};
 const App=()=>identity?<Room identity={identity}/>:<main style={{width:'100%',maxWidth:1100,margin:'auto',padding:16}}><div style={{width:180,marginBottom:20}}><AnimeCard category="manga" anime={{mal_id:'1',title:'Манга',synopsis:'Описание',score:9,genres:[],trailer:{youtube_id:'abcdefghijk'}}} onOpen={()=>{}} onFavorite={()=>window.bookmarked=true}/></div><Player apiRef={api=>window.player=api} autoPlay characterService={service} item={item} source=${JSON.stringify(base+'fixture.mp4')} catalog={{items:[item]}} userId="fixture" libraryId="fixture"/></main>;
 createRoot(document.getElementById('root')).render(<ThemeProvider><App/></ThemeProvider>);
 window.runModel=async()=>{const blob=await(await fetch('/src/blossom/placeholders/print.webp')).blob(),image=await createImageBitmap(blob),canvas=new OffscreenCanvas(192,288);canvas.getContext('2d').drawImage(image,0,0,192,288);image.close();const worker=new Worker(new URL('/src/title-upscale.worker.js',location.origin),{type:'module'});const result=await new Promise((resolve,reject)=>{const t=setTimeout(()=>reject(Error('CPU model timeout')),90000);worker.onmessage=e=>{clearTimeout(t);resolve(e.data);};worker.onerror=e=>{clearTimeout(t);reject(Error(e.message));};const bitmap=canvas.transferToImageBitmap();worker.postMessage({id:1,bitmap,modelUrl:${JSON.stringify(server+'/models/illustration-span-3f5245ed1abe.onnx')},runtimePaths:${JSON.stringify(server+'/lmt/')}},[bitmap]);});worker.terminate();if(result.type!=='result')throw Error(result.message||result.type);window.modelResult=result;return {width:result.width,height:result.height,inferenceMs:result.inferenceMs,provider:result.provider,bytes:result.blob.size};};
 `);
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--ignore-certificate-errors','--autoplay-policy=no-user-gesture-required','--enable-unsafe-swiftshader']});
 const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1440,height:1000}}),host=await context.newPage(),errors=[];last=host;host.on('pageerror',e=>errors.push(e.message));
 await host.route('https://**/*',r=>r.request().url().startsWith(server)?r.continue():r.fulfill({json:{data:[]}}));await host.goto(origin+base+'index.html');await host.waitForFunction(()=>window.player?.media.readyState>=2);
 assert.equal(await host.locator('.media-kind-badge').innerText(),'Манга');await host.getByRole('button',{name:'В избранное',exact:true}).click();assert.ok(await host.evaluate(()=>window.bookmarked));
 await host.evaluate(()=>window.player.openPanel('settings'));await host.getByRole('tab',{name:'Просмотр',exact:true}).waitFor();const heights=[];
 for(const tab of ['Просмотр','Изображение','Атмосфера','Субтитры','Пропуск','Действия','Комната']){await host.getByRole('tab',{name:tab,exact:true}).click();await host.waitForTimeout(80);heights.push((await host.locator('.player-settings-glass').boundingBox()).height);}
 assert.ok(Math.max(...heights)-Math.min(...heights)<2,'Settings height must stay fixed: '+heights);assert.equal(await host.locator('.player-settings-glass header,.player-settings-shortcuts').count(),0);
 await host.getByLabel('Пароль новой комнаты',{exact:true}).fill('room-pass');await host.getByRole('button',{name:'Создать комнату',exact:true}).click();await host.getByLabel('Ссылка комнаты',{exact:true}).waitFor();const link=await host.getByLabel('Ссылка комнаты',{exact:true}).inputValue(),id=new URLSearchParams(new URL(link).hash.slice(1)).get('room');assert.ok(id);
 await host.evaluate(()=>window.player.openPanel('watch'));await host.evaluate(()=>window.player.play());await host.waitForFunction(()=>window.player.media.currentTime>1);
 const guest=await context.newPage();last=guest;guest.on('pageerror',e=>errors.push(e.message));await guest.goto(origin+base+'index.html#room='+id);await guest.getByLabel('Имя в комнате',{exact:true}).fill('Друг');await guest.getByLabel('Пароль комнаты',{exact:true}).fill('room-pass');await guest.getByRole('button',{name:'Войти в комнату',exact:true}).click();await guest.locator('video.mv-player-media').waitFor();await guest.waitForFunction(()=>document.querySelector('video.mv-player-media')?.currentTime>.3,{timeout:30000});
 assert.equal(await guest.locator('.mv-player-media').count(),1);assert.equal(await guest.locator('.blossom-navbar,.library-sidebar').count(),0,'Guest cannot navigate the collection');assert.ok(await guest.getByLabel('Перемотка видео',{exact:true}).isDisabled(),'Guest defaults to host-only control');
 await host.evaluate(()=>window.player.seek(12));await guest.waitForFunction(()=>Math.abs(document.querySelector('video.mv-player-media').currentTime-12)<2,{timeout:15000});await host.evaluate(()=>window.player.pause());await guest.waitForFunction(()=>document.querySelector('video.mv-player-media').paused,{timeout:12000});
 const hostTime=await host.evaluate(()=>window.player.media.currentTime),guestTime=await guest.locator('video.mv-player-media').evaluate(v=>v.currentTime);assert.ok(Math.abs(hostTime-guestTime)<1.5,'Room timeline synchronizes');
 console.log('PASS real password room, same React player, scoped host Range relay, guest permissions, pause and seek');
 await guest.close();last=host;await host.evaluate(()=>window.player.openPanel('settings'));await host.getByRole('tab',{name:'Атмосфера',exact:true}).click();await host.waitForTimeout(250);await host.screenshot({path:path.join(dir,'settings.png')});await host.evaluate(()=>window.player.openPanel('watch'));
 const ml=await host.evaluate(()=>window.runModel());assert.equal(ml.provider,'wasm');assert.deepEqual([ml.width,ml.height],[384,576]);assert.ok(ml.bytes>1000);console.log('REAL_CPU_SPAN',JSON.stringify(ml));
 const output=await host.evaluate(async()=>Array.from(new Uint8Array(await window.modelResult.blob.arrayBuffer())));await fs.writeFile(path.join(dir,'span-enhanced.webp'),Buffer.from(output));
 assert.deepEqual(errors,[]);await host.screenshot({path:path.join(dir,'player.png'),fullPage:true});await context.close();
})().catch(async e=>{console.error(e);await last?.screenshot({path:path.join(process.cwd(),'.codex-local/test-output/interface-rooms/failure.png')}).catch(()=>{});process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();backend?.kill();await log?.close();});
