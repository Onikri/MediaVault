const KEY='mediavault_privacy_v1',COOKIE='mv_preferences',DEVICE='mv_device';
// Signing in through Google remembers this device unless the visitor chose
// «Только необходимые». The banner stays until an explicit choice.
const fallback={version:1,chosen:false,remember:true};
function cookiePath(){return new URL(import.meta.env?.BASE_URL||'./',location.href).pathname;}
function cookie(name){
  try{const row=document.cookie.split('; ').find(r=>r.startsWith(name+'='));return row?decodeURIComponent(row.slice(name.length+1)):'';}catch{return '';}
}
function writeCookie(name,value){
  try{document.cookie=name+'='+encodeURIComponent(value)+'; Max-Age='+(value?31536000:0)+'; Path='+cookiePath()+'; SameSite=Strict'+(location.protocol==='https:'?'; Secure':'');}catch{}
}
// Browsers short of disk space clear site storage (localStorage, IndexedDB)
// but keep cookies, so the choice is mirrored in a preferences-only cookie.
export function privacyPreferences(){
  try{
    const stored=localStorage.getItem(KEY);
    if(stored)return {...fallback,...JSON.parse(stored)};
    const mirrored=JSON.parse(cookie(COOKIE)||'null');
    if(mirrored&&typeof mirrored.remember==='boolean'){
      const value={...fallback,chosen:mirrored.chosen!==false,remember:mirrored.remember,restoredFromCookie:true};
      localStorage.setItem(KEY,JSON.stringify(value));return value;
    }
  }catch{}
  return {...fallback};
}
export function savePrivacyPreferences(remember,{chosen=true}={}){
  const value={version:1,chosen,remember:!!remember,updatedAt:Date.now()};
  try{localStorage.setItem(KEY,JSON.stringify(value));}catch{}
  // Preferences only. No identity, Google token, phrase or vault key in cookies.
  writeCookie(COOKIE,JSON.stringify({v:1,remember:!!remember,chosen}));
  if(!remember)writeCookie(DEVICE,'');
  window.dispatchEvent(new CustomEvent('mediavault-privacy',{detail:value}));return value;
}
// The id of this device's remembered sign-in. Not a credential: restoring
// needs a signature from the private key kept in IndexedDB. It lets a device
// whose storage was cleared replace its old server record instead of piling
// up new ones.
export function rememberedDeviceId(){const id=cookie(DEVICE);return /^[A-Za-z0-9_-]{32,100}$/.test(id)?id:'';}
export function saveRememberedDeviceId(id){writeCookie(DEVICE,id||'');}
// Ask the browser not to clear this site's storage under disk pressure.
// Chrome decides silently (engagement, bookmark, installed app); Firefox asks.
export async function keepStorage(){
  try{
    if(!navigator.storage?.persist)return null;
    if(await navigator.storage.persisted())return true;
    return await navigator.storage.persist();
  }catch{return null;}
}
