import {deviceStore} from './device-storage.js';

const utf8=new TextEncoder(),encode=value=>btoa(String.fromCharCode(...new Uint8Array(value))),decode=value=>Uint8Array.from(atob(value),c=>c.charCodeAt(0));
const names=(scope,provider)=>({record:'secret:'+provider+':'+scope,key:'secret-wrap:'+provider+':'+scope});
const aad=(scope,provider)=>utf8.encode('MediaVault device secret v1\n'+scope+'\n'+provider);
function identity(scope,provider){if(!scope||scope==='anonymous'||String(scope).length>256||!['google-translation'].includes(provider))throw Error('Войди в профиль, чтобы запомнить ключ на этом устройстве.');}

export async function saveDeviceSecret(scope,provider,value,{store=deviceStore,now=Date.now}={}){
 identity(scope,provider);const id=names(scope,provider);
 if(!value||value.length>512)throw Error('Проверь API-ключ.');
 let key=await store('get',id.key);
 if(!key){const fresh=await crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);key=await store('getOrPut',id.key,fresh);}
 const iv=crypto.getRandomValues(new Uint8Array(12)),data=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:aad(scope,provider)},key,utf8.encode(value));
 await store('put',id.record,{version:1,scope,provider,iv:encode(iv),data:encode(data),expiresAt:now()+90*86400000});
}
export async function readDeviceSecret(scope,provider,{store=deviceStore,now=Date.now}={}){
 identity(scope,provider);const id=names(scope,provider),record=await store('get',id.record);
 if(!record)return '';
 if(record.version!==1||record.scope!==scope||record.provider!==provider)throw Error('Сохранённый ключ не относится к этому профилю.');
 if(!Number.isFinite(record.expiresAt)||record.expiresAt<=now()){await store('delete',id.record);return '';}
 const key=await store('get',id.key);if(!key)throw Error('Ключ устройства недоступен. Введи API-ключ заново.');
 return new TextDecoder().decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:decode(record.iv),additionalData:aad(scope,provider)},key,decode(record.data)));
}
export async function forgetDeviceSecret(scope,provider,{store=deviceStore}={}){
 if(!scope||scope==='anonymous')return;const id=names(scope,provider);await store('delete',id.record);await store('delete',id.key);
}
