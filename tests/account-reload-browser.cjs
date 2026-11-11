// Full sign-in -> reload contract: real React, WebCrypto, IndexedDB and ECDSA.
// Google and device HTTP are fixtures; no real user credentials are read.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require('playwright');
let browser,vite;
(async()=>{
 const root=path.resolve(__dirname,'..'),dir=path.join(root,'.codex-local/test-output/account-reload');await fs.mkdir(dir,{recursive:true});
 const user={sub:'fixture-owner',email:'owner@example.test',email_verified:true,name:'Owner'};
 const hash=crypto.createHash('sha256').update(user.email).digest('hex');
 await fs.writeFile(path.join(dir,'index.html'),'<div id="root"></div><script type="module" src="/.codex-local/test-output/account-reload/app.jsx"></script>');
 await fs.writeFile(path.join(dir,'app.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import{useVault}from'/src/vault.js';import ProfileMenu from'/src/ProfileMenu.jsx';import{deviceStore}from'/src/device-storage.js';import{saveAccountSession,readAccountSession,clearAccountSession}from'/src/account-session.js';
 window.deviceStore=deviceStore;window.saveAccountSession=saveAccountSession;window.readAccountSession=readAccountSession;window.clearAccountSession=clearAccountSession;
 window.MEDIA_VAULT_CONFIG={googleClientId:'fixture-client',adminEmailSha256:'${hash}',importServerUrl:'https://account.example'};
 window.gisLogins=0;window.google={accounts:{oauth2:{initTokenClient:options=>({requestAccessToken:()=>{window.gisLogins++;options.callback({access_token:'fixture-google-access',expires_in:3600,scope:'openid email profile https://www.googleapis.com/auth/drive.readonly'});}})}}};
 function Demo(){const{state,actions}=useVault();window.state=state;window.actions=actions;return <><ProfileMenu state={state} onLogin={actions.login} onLogout={actions.logout}/><button id="login" disabled={state.restoring} onClick={actions.login}>Login</button><button id="logout" onClick={actions.logout}>Logout</button></>;}createRoot(document.getElementById('root')).render(<Demo/>);
 `);
 const {createServer}=await import('vite');vite=await createServer({root,logLevel:'error',server:{host:'127.0.0.1',port:0,strictPort:false,watch:null}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
 const context=await browser.newContext({serviceWorkers:'block'}),page=await context.newPage();
 const records=new Map(),nonces=new Map(),errors=[];let registerDown=false,restoreDown=false,registrations=0,restores=0;
 page.on('pageerror',e=>errors.push(e.message));
 const cors={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'*'};
 await context.route('https://account.example/**',async route=>{
  const req=route.request(),p=new URL(req.url()).pathname;
  const json=(body,status=200)=>route.fulfill({headers:cors,json:body,status});
  if(req.method()==='OPTIONS')return json({});
  const body=req.postDataJSON();
  if(p==='/devices/register'){
   if(registerDown)return json({detail:'temporary outage'},503);
   const id=crypto.randomBytes(32).toString('base64url');records.set(id,body.public_key);registrations++;
   return json({id,ready:true});
  }
  if(p==='/devices/challenge'){
   if(!records.has(body.id))return json({detail:'missing device'},401);
   const nonce=crypto.randomBytes(24).toString('base64url');nonces.set(body.id+':'+nonce,true);return json({nonce});
  }
  if(['/devices/restore','/devices/remove'].includes(p)){
   if(restoreDown)return json({detail:'temporary outage'},503);
   const key=records.get(body.id),nonce=body.nonce,pending=nonces.get(body.id+':'+nonce);nonces.delete(body.id+':'+nonce);
   if(!key||!pending)return json({detail:'invalid proof'},401);
   assert.ok(crypto.verify('sha256',Buffer.from('MediaVault device session\n'+body.id+'\n'+nonce),{key:crypto.createPublicKey({key,format:'jwk'}),dsaEncoding:'ieee-p1363'},Buffer.from(body.signature,'base64url')));
   if(p.endsWith('/remove')){records.delete(body.id);return json({removed:true});}
   restores++;return json({access_token:'fixture-restored-access',expires_in:3500,scope:'openid email profile https://www.googleapis.com/auth/drive.readonly',user});
  }
  return json({});
 });
 await context.route('https://www.googleapis.com/**',route=>{
  const p=new URL(route.request().url()).pathname;
  if(p.includes('userinfo'))return route.fulfill({headers:cors,json:user});
  assert.match(route.request().headers().authorization||'',/^Bearer fixture-(google|restored)-access$/,'Drive uses restored credentials');
  return route.fulfill({headers:cors,json:{files:[]}});
 });
 const url='http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/account-reload/index.html';
 await page.goto(url);await page.waitForFunction(()=>window.state&&!state.restoring);
 // Necessary-only cookies used to lose the entire login on any reload.
 await page.evaluate(()=>localStorage.setItem('mediavault_privacy_v1',JSON.stringify({version:1,chosen:true,remember:false})));
 await page.click('#login');await page.waitForFunction(()=>state.user&&state.driveConnected&&!state.busy);
 assert.equal(registrations,0);
 const sealed=await page.evaluate(async()=>({records:await new Promise((resolve,reject)=>{const req=indexedDB.open('mediavault-trusted-device-v1',1);req.onerror=()=>reject(req.error);req.onsuccess=()=>{const db=req.result,tx=db.transaction('records');const all=tx.objectStore('records').getAll();all.onsuccess=()=>{resolve(all.result.map(v=>v instanceof CryptoKey?{key:v.type,extractable:v.extractable}:v));db.close();};};}),cookies:document.cookie,local:Object.fromEntries(Object.entries(localStorage)),tab:Object.fromEntries(Object.entries(sessionStorage))}));
 assert.doesNotMatch(JSON.stringify(sealed),/fixture-google-access/,'access token is absent from plaintext browser storage');
 assert.ok(sealed.records.some(r=>r.key==='secret'&&r.extractable===false),'wrapping key is non-exportable');
 await page.reload();await page.waitForFunction(()=>state.user&&state.driveConnected&&!state.restoring);
 assert.equal(await page.evaluate(()=>gisLogins),0,'reload must not reopen Google');
 console.log('PASS session-only sign-in survives reload with protected Drive access');
 const fresh=await context.newPage();await fresh.goto(url);await fresh.waitForFunction(()=>window.state&&!state.restoring);
 assert.equal(await fresh.evaluate(()=>state.user),null,'session-only access must not leak to another tab');await fresh.close();
 // A server registration failure must not discard a successful Google login.
 await page.click('#logout');await page.waitForFunction(()=>!state.user);
 await page.evaluate(()=>localStorage.setItem('mediavault_privacy_v1',JSON.stringify({version:1,chosen:true,remember:true})));
 registerDown=true;await page.click('#login');await page.waitForFunction(()=>state.user&&!state.busy&&state.deviceError);
 registerDown=false;await page.reload();await page.waitForFunction(()=>state.user&&state.driveConnected&&state.remembered&&!state.restoring);
 assert.equal(await page.evaluate(()=>gisLogins),0);
 const identity=await page.evaluate(async()=> (await deviceStore('get','auth')).id);
 console.log('PASS failed initial registration repairs after reload without Google popup');
 // Long AFK: expired cached access falls back to the real signed device flow.
 await page.evaluate(async user=>saveAccountSession({access_token:'expired-fixture',expires_in:0,scope:'https://www.googleapis.com/auth/drive.readonly'},user,{remember:true}),user);
 await page.reload();await page.waitForFunction(()=>state.user&&state.driveConnected&&!state.restoring);
 assert.ok(restores>0);assert.equal(await page.evaluate(()=>gisLogins),0);
 assert.equal(await page.evaluate(async()=> (await deviceStore('get','auth')).id),identity);
 console.log('PASS expired local access renews through the same signed device');
 await page.evaluate(async user=>saveAccountSession({access_token:'expired-fixture',expires_in:0,scope:'https://www.googleapis.com/auth/drive.readonly'},user,{remember:true}),user);
 restoreDown=true;await page.reload();await page.waitForFunction(()=>state.user&&state.deviceError&&!state.restoring);
 await page.getByRole('button',{name:'Профиль',exact:true}).click();
 assert.equal(await page.getByText('Ты не вошёл',{exact:true}).count(),0);
 restoreDown=false;await page.evaluate(()=>dispatchEvent(new Event('focus')));await page.waitForFunction(()=>state.driveConnected&&!state.busy);
 console.log('PASS temporary restore outage keeps account identity and recovers');
 const other=await context.newPage();await other.goto(url);await other.waitForFunction(()=>window.state?.user&&state.driveConnected&&!state.restoring);
 // A late asynchronous cache write may not resurrect an explicit logout.
 await page.evaluate(async()=>{const record=await deviceStore('get','account-access:remembered');await clearAccountSession();await deviceStore('put','account-access:remembered',record);if(await readAccountSession(true))throw Error('stale cache revived');});
 // Explicit logout still revokes both the cache and the device proof.
 await page.click('#logout');await page.waitForFunction(()=>!state.user);
 await other.waitForFunction(()=>!state.user);await other.close();
 await page.reload();await page.waitForFunction(()=>window.state&&!state.restoring);
 assert.equal(await page.evaluate(()=>state.user),null);
 assert.deepEqual(errors,[]);
 console.log('PASS explicit logout remains signed out after reload');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
