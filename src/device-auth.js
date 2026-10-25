import {deviceStore} from './device-storage.js';
const encode=bytes=>btoa(String.fromCharCode(...new Uint8Array(bytes))).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');
const text=new TextEncoder();
async function request(server,path,body,token){
  const r=await fetch(server+path,{method:'POST',signal:AbortSignal.timeout(15000),headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:JSON.stringify(body)});
  const data=await r.json().catch(()=>({}));if(!r.ok)throw Object.assign(Error(data.detail||'Не удалось восстановить вход на этом устройстве.'),{status:r.status});return data;
}
async function proof(record){
  const challenge=await request(record.server,'/devices/challenge',{id:record.id});
  const message='MediaVault device session\n'+record.id+'\n'+challenge.nonce;
  return {id:record.id,nonce:challenge.nonce,signature:encode(await crypto.subtle.sign({name:'ECDSA',hash:'SHA-256'},record.privateKey,text.encode(message)))};
}
export async function rememberGoogleSession(server,token,user){
  let record=await deviceStore('get','auth');
  if(record?.sub===user.sub&&record.server===server){
    if(record.pendingURL&&record.pendingUntil>Date.now())return finishConsent(record);
    try{await request(server,'/devices/restore',await proof(record));return record;}catch(error){if(error.status!==401&&error.status!==404)throw error;}
  }
  const keys=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},false,['sign','verify']);
  const registered=await request(server,'/devices/register',{public_key:await crypto.subtle.exportKey('jwk',keys.publicKey)},token);
  record={id:registered.id,privateKey:keys.privateKey,server,sub:user.sub,...(registered.url?{pendingURL:registered.url,pendingUntil:Date.now()+540000}:{})};
  await deviceStore('put','auth',record);
  return record.pendingURL?finishConsent(record):record;
}
async function finishConsent(record){
    const server=record.server;
    if(new URL(record.pendingURL).origin!=='https://accounts.google.com')throw Error('Сервер вернул неизвестный адрес Google.');
    const popup=window.open(record.pendingURL,'mediavault-remember-device','popup,width=560,height=720');
    if(!popup)throw Error('Нажми «Запомнить это устройство» в профиле ещё раз и разреши окно Google.');
    await new Promise((resolve,reject)=>{let finished=false;const finish=error=>{if(finished)return;finished=true;clearInterval(timer);clearTimeout(timeout);window.removeEventListener('message',message);error?reject(error):resolve();};const message=event=>{if(event.origin===server&&event.source===popup&&event.data?.type==='mediavault-server-connected')finish();};window.addEventListener('message',message);const timer=setInterval(()=>{if(popup.closed)finish();},1000),timeout=setTimeout(()=>{popup.close();finish(Error('Запоминание устройства не завершено. Повтори из профиля.'));},150000);});
    await request(server,'/devices/restore',await proof(record));
    delete record.pendingURL;delete record.pendingUntil;await deviceStore('put','auth',record);return record;
}
export async function restoreGoogleSession(){const record=await deviceStore('get','auth');if(!record)return null;return request(record.server,'/devices/restore',await proof(record));}
export async function forgetGoogleSession(){
  const record=await deviceStore('get','auth');
  try{if(record)await request(record.server,'/devices/remove',await proof(record));}finally{await deviceStore('delete','auth');}
}
