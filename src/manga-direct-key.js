// Personal Google keys stay in this tab. Never put them in shared settings,
// translation cache identities, URL query strings or the VM configuration.
const keys=new Map(),prefix='mv_direct_google_key:';
export function directKey(scope){
 if(keys.has(scope))return keys.get(scope);
 try{const key=sessionStorage.getItem(prefix+scope)||'';if(key)keys.set(scope,key);return key;}catch{return '';}
}
export function setDirectKey(scope,value,remember=false){
 const key=String(value||'').trim();
 if(key&&(!/^[\x21-\x7e]+$/.test(key)||key.length>512))throw Error('Проверь ключ: убери пробелы и переносы строк.');
 if(key)keys.set(scope,key);else keys.delete(scope);
 try{if(key&&remember)sessionStorage.setItem(prefix+scope,key);else sessionStorage.removeItem(prefix+scope);}catch{}
}
export function remembersDirectKey(scope){try{return !!sessionStorage.getItem(prefix+scope);}catch{return false;}}
globalThis.addEventListener?.('mediavault-locked',()=>{
 keys.clear();try{for(const key of Object.keys(sessionStorage))if(key.startsWith(prefix))sessionStorage.removeItem(key);}catch{}
});
