import {saveDeviceSecret,readDeviceSecret,forgetDeviceSecret} from './device-secrets.js';
// Optional device records contain only AES-GCM ciphertext. The wrapping key is
// non-exportable and account-scoped in IndexedDB. No key enters cookies/settings.
const keys=new Map(),remembered=new Set(),opening=new Map(),writes=new Map(),prefix='mv_direct_google_key:';
let generation=0;
export function directKey(scope){
 if(keys.has(scope))return keys.get(scope);
 try{const key=sessionStorage.getItem(prefix+scope)||'';sessionStorage.removeItem(prefix+scope);if(key)keys.set(scope,key);return key;}catch{return '';}
}
export function setDirectKey(scope,value){
 generation++;const key=String(value||'').trim();
 if(key&&(!/^[\x21-\x7e]+$/.test(key)||key.length>512))throw Error('Проверь ключ: убери пробелы и переносы строк.');
 if(key)keys.set(scope,key);else keys.delete(scope);
 try{sessionStorage.removeItem(prefix+scope);}catch{}
}
export function remembersDeviceKey(scope){return remembered.has(scope);}
export async function restoreDirectKey(scope){
 if(directKey(scope))return directKey(scope);if(!scope||scope==='anonymous')return '';
 if(opening.has(scope))return opening.get(scope);
 const epoch=generation,task=(async()=>{try{const value=await readDeviceSecret(scope,'google-translation');if(epoch!==generation)return '';if(value){keys.set(scope,value);remembered.add(scope);}return value;}catch{return '';}})();opening.set(scope,task);
 try{return await task;}finally{if(opening.get(scope)===task)opening.delete(scope);}
}
function serialize(scope,work){const previous=writes.get(scope)||Promise.resolve(),task=previous.catch(()=>{}).then(work);writes.set(scope,task);return task.finally(()=>{if(writes.get(scope)===task)writes.delete(scope);});}
export async function rememberDirectKey(scope,value){
 setDirectKey(scope,value);const epoch=generation;
 return serialize(scope,async()=>{if(epoch!==generation)throw Error('Сохранение ключа отменено после выхода.');await saveDeviceSecret(scope,'google-translation',value);if(epoch!==generation){await forgetDeviceSecret(scope,'google-translation');throw Error('Сохранение ключа отменено после выхода.');}remembered.add(scope);});
}
export function forgetRememberedDirectKey(scope){
 generation++;keys.delete(scope);remembered.delete(scope);try{sessionStorage.removeItem(prefix+scope);}catch{}
 return serialize(scope,()=>forgetDeviceSecret(scope,'google-translation'));
}
function lockKeys(){generation++;opening.clear();
 keys.clear();try{for(const key of Object.keys(sessionStorage))if(key.startsWith(prefix))sessionStorage.removeItem(key);}catch{}
}
globalThis.addEventListener?.('mediavault-locked',lockKeys);
globalThis.addEventListener?.('mediavault-forgot-device',()=>{lockKeys();remembered.clear();});
