import {deviceStore} from './device-storage.js';
const encoder=new TextEncoder();
const bytes=value=>Uint8Array.from(atob(value),c=>c.charCodeAt(0));
const b64=value=>btoa(String.fromCharCode(...new Uint8Array(value)));
const aad=(sub,id)=>encoder.encode('MediaVault trusted library\n'+sub+'\n'+id);
const recordId=(sub,id)=>'vault:'+sub+':'+id;
async function wrapKey(){let key=await deviceStore('get','wrap-key');if(!key){key=await crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);await deviceStore('put','wrap-key',key);}return key;}
async function prfKey(record){
  const credential=await navigator.credentials.get({publicKey:{challenge:crypto.getRandomValues(new Uint8Array(32)),allowCredentials:[{type:'public-key',id:bytes(record.credential)}],userVerification:'required',timeout:60000,extensions:{prf:{eval:{first:bytes(record.prfSalt)}}}}});
  const output=credential?.getClientExtensionResults()?.prf?.results?.first;
  if(!output)throw Error('Этот способ входа не поддерживает защищённую разблокировку библиотеки. Используй секретную фразу.');
  const base=await crypto.subtle.importKey('raw',output,'HKDF',false,['deriveKey']);
  return crypto.subtle.deriveKey({name:'HKDF',hash:'SHA-256',salt:bytes(record.prfSalt),info:encoder.encode('MediaVault biometric vault v1')},base,{name:'AES-GCM',length:256},false,['encrypt','decrypt']);
}
export async function biometricAvailable(){return !!globalThis.PublicKeyCredential&&!!navigator.credentials&&await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable().catch(()=>false);}
export async function saveTrustedVault(sub,libraryId,rawKey,salt,{biometric=false}={}){
  const record={sub,libraryId,salt:b64(salt),biometric};let key;
  if(biometric){
    if(!await biometricAvailable())throw Error('Биометрия и защищённый PIN недоступны в этом браузере.');
    const prfSalt=crypto.getRandomValues(new Uint8Array(32));
    const credential=await navigator.credentials.create({publicKey:{challenge:crypto.getRandomValues(new Uint8Array(32)),rp:{name:'MediaVault'},user:{id:await crypto.subtle.digest('SHA-256',encoder.encode(sub)),name:'MediaVault',displayName:'Библиотека MediaVault'},pubKeyCredParams:[{type:'public-key',alg:-7}],authenticatorSelection:{authenticatorAttachment:'platform',userVerification:'required',residentKey:'preferred'},timeout:60000,attestation:'none',extensions:{prf:{eval:{first:prfSalt}}}}});
    if(!credential?.getClientExtensionResults()?.prf?.enabled)throw Error('Браузер не поддерживает WebAuthn PRF. Секретная фраза по-прежнему доступна; автоматическое открытие можно включить отдельно.');
    record.credential=b64(credential.rawId);record.prfSalt=b64(prfSalt);key=await prfKey(record);
  }else key=await wrapKey();
  const iv=crypto.getRandomValues(new Uint8Array(12));record.iv=b64(iv);record.data=b64(await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:aad(sub,libraryId)},key,rawKey));
  await deviceStore('put',recordId(sub,libraryId),record);return record;
}
export async function trustedVault(sub,libraryId){return deviceStore('get',recordId(sub,libraryId));}
export async function openTrustedVault(sub,libraryId){
  const record=await trustedVault(sub,libraryId);if(!record||record.sub!==sub||record.libraryId!==libraryId)return null;
  const key=record.biometric?await prfKey(record):await wrapKey();
  const raw=new Uint8Array(await crypto.subtle.decrypt({name:'AES-GCM',iv:bytes(record.iv),additionalData:aad(sub,libraryId)},key,bytes(record.data)));
  return {serverKey:raw,salt:bytes(record.salt),key:await crypto.subtle.importKey('raw',raw,{name:'AES-GCM'},false,['encrypt','decrypt'])};
}
export async function forgetTrustedVault(sub,libraryId){await deviceStore('delete',recordId(sub,libraryId));}
