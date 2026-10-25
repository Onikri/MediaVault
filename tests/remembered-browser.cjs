const assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
module.exports=async function({browser,base,installProvider,OWNER,PHRASE,catalogId}){
 base=base.replace('127.0.0.1','localhost'); // WebAuthn forbids IP addresses as relying-party domains.
 const context=await browser.newContext({viewport:{width:768,height:1024},serviceWorkers:'allow'});context.setDefaultTimeout(20000);
 await installProvider(context,OWNER,{showConsent:true,server:'https://import.example.com'});
 const devices=new Map();let restores=0;
 await context.route('https://import.example.com/**',async route=>{
  const r=route.request(),url=new URL(r.url()),data=r.postDataJSON?.()||{};
  const json=(body,status=200)=>route.fulfill({status,headers:{'access-control-allow-origin':'*','access-control-allow-headers':'*','access-control-allow-methods':'*'},contentType:'application/json',body:JSON.stringify(body)});
  if(r.method()==='OPTIONS')return json({});
  if(url.pathname==='/health')return json({application:'MediaVault',version:5,origin:new URL(base).origin,rememberedDevices:true});
  if(url.pathname==='/auth/session')return json({token:'private-fixture-session',driveConnected:true,oauthConfigured:true});
  if(url.pathname==='/jobs')return json({jobs:[]});
  if(url.pathname==='/library/enrich')return json({id:'enrich-fixture',status:'queued',created:Date.now()/1000,progress:{taskType:'enrich',saved:0,total:0}},202);
  if(url.pathname==='/devices/register'){
   const id='fixture-device-'+String(devices.size+1).padStart(32,'0');
   devices.set(id,{key:await webcrypto.subtle.importKey('jwk',data.public_key,{name:'ECDSA',namedCurve:'P-256'},false,['verify'])});return json({id,ready:true});
  }
  if(url.pathname==='/devices/challenge'){
   const value=devices.get(data.id);if(!value)return json({detail:'Unknown device'},401);
   value.nonce=Buffer.from(webcrypto.getRandomValues(new Uint8Array(32))).toString('base64url');return json({nonce:value.nonce});
  }
  if(['/devices/restore','/devices/remove'].includes(url.pathname)){
   const value=devices.get(data.id);if(!value||value.nonce!==data.nonce)return json({detail:'Expired proof'},401);
   value.nonce=null;const message='MediaVault device session\n'+data.id+'\n'+data.nonce;
   const ok=await webcrypto.subtle.verify({name:'ECDSA',hash:'SHA-256'},value.key,Buffer.from(data.signature,'base64url'),Buffer.from(message));
   if(!ok)return json({detail:'Invalid proof'},401);
   if(url.pathname.endsWith('/remove')){devices.delete(data.id);return json({removed:true});}
   restores++;return json({access_token:OWNER,expires_in:3500,scope:'openid email profile https://www.googleapis.com/auth/drive.readonly'});
  }
  return json({data:[]});
 });
 try{
  const page=await context.newPage(),cdp=await context.newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator',{options:{protocol:'ctap2',ctap2Version:'ctap2_1',transport:'internal',hasResidentKey:true,hasUserVerification:true,isUserVerified:true,automaticPresenceSimulation:true,hasPrf:true}});
  await page.goto(base+'?library='+catalogId);
  await page.getByRole('region',{name:'Cookies и запоминание устройства'}).waitFor();
  await page.getByRole('button',{name:'Принять и запомнить',exact:true}).click();
  await page.locator('#profileBtn').click();await page.locator('#loginBtn').click();
  await page.locator('#passphrase').fill(PHRASE);await page.locator('#unlockBtn').click();
  await page.waitForFunction(()=>document.querySelector('#count')?.textContent.includes('10'));
  await page.waitForFunction(async()=>{const db=await new Promise(r=>{const q=indexedDB.open('mediavault-trusted-device-v1',1);q.onsuccess=()=>r(q.result);});try{return await new Promise(r=>{const q=db.transaction('records').objectStore('records').getAll();q.onsuccess=()=>r(q.result.some(v=>v?.libraryId&&v?.data));});}finally{db.close();}});
  const cookie=await page.evaluate(()=>document.cookie);assert.ok(cookie.includes('mv_preferences='));assert.ok(!cookie.includes(OWNER)&&!cookie.includes(PHRASE)&&!cookie.includes('access_token'));
  await page.reload();await page.waitForFunction(()=>document.querySelector('#count')?.textContent.includes('10'));
  assert.equal(await page.evaluate(()=>window.__grants?.length||0),0,'Reload restores Google and the encrypted library without another Google popup or phrase');
  assert.ok(restores>=1,'Restoring uses a real ECDSA-signed challenge');
  const protectedKey=await page.evaluate(async()=>{const db=await new Promise(r=>{const q=indexedDB.open('mediavault-trusted-device-v1',1);q.onsuccess=()=>r(q.result);});const record=await new Promise(r=>{const q=db.transaction('records').objectStore('records').get('auth');q.onsuccess=()=>r(q.result);});db.close();try{await crypto.subtle.exportKey('jwk',record.privateKey);return false;}catch{return record.privateKey.extractable===false;}});
  assert.ok(protectedKey,'The remembered signing key cannot be exported');
  await page.locator('#profileBtn').click();
  await page.getByRole('button',{name:'Настроить защищённое открытие',exact:true}).click();
  await page.getByText('Разблокировка устройством включена',{exact:true}).waitFor();
  await page.reload();await page.locator('#profileBtn').click();
  await page.locator('.device-settings').getByRole('button',{name:'Открыть библиотеку',exact:true}).waitFor();
  assert.equal(await page.locator('#libraryPanel').count(),0,'A biometric vault stays locked after Google restores');
  await page.locator('.device-settings').getByRole('button',{name:'Открыть библиотеку',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#count')?.textContent.includes('10'));
  await page.locator('#profileBtn').click();await page.locator('#logoutBtn').click();await page.reload();
  await page.locator('#profileBtn').click();assert.equal(await page.locator('#loginBtn').isEnabled(),true,'Logout does not silently log the account back in');
  console.log('PASS: cookie consent; opt-in device persistence; non-exportable key; real signatures; automatic Google + vault restore; WebAuthn PRF wrapping and unlock with a virtual platform authenticator; logout.');
 }finally{await context.close();}
};
