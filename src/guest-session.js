import {useEffect,useState} from 'react';
// Guest profile session issued by the owner's server. Holds a signed session
// token and the public profile only — never the password.
const KEY='mediavault_guest_session_v1',EVENT='mediavault:guest-session';
export function readGuestSession(storage=localStorage){
 try{const value=JSON.parse(storage.getItem(KEY)||'null');if(!value||typeof value.token!=='string'||!value.guest?.id)return null;if(value.expiresAt&&value.expiresAt*1000<Date.now()){storage.removeItem(KEY);return null;}return value;}catch{return null;}
}
export function saveGuestSession(value){try{localStorage.setItem(KEY,JSON.stringify({token:value.token,expiresAt:value.expiresAt,guest:value.guest}));}catch{}dispatchEvent(new Event(EVENT));}
export function clearGuestSession(){try{localStorage.removeItem(KEY);}catch{}dispatchEvent(new Event(EVENT));}
export function useGuestSession(){
 const [value,setValue]=useState(()=>readGuestSession());
 useEffect(()=>{const update=()=>setValue(readGuestSession());addEventListener(EVENT,update);addEventListener('storage',update);return()=>{removeEventListener(EVENT,update);removeEventListener('storage',update);};},[]);
 return value;
}
function server(){return String(window.MEDIA_VAULT_CONFIG?.importServerUrl||'').replace(/\/$/,'');}
async function call(path,{method='GET',body}={}){
 const base=server();if(!base)throw Error('Сервер MediaVault не настроен.');
 const response=await fetch(base+path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(20000)});
 const data=await response.json().catch(()=>({}));
 if(!response.ok)throw Object.assign(Error(typeof data.detail==='string'?data.detail:'Сервер не ответил. Повтори немного позже.'),{status:response.status});
 return data;
}
export const invitePreview=token=>call('/guests/invite/'+encodeURIComponent(token));
export async function enrollGuest(body){const session=await call('/guests/enroll',{method:'POST',body});saveGuestSession(session);return session;}
export async function loginGuest(body){const session=await call('/guests/login',{method:'POST',body});saveGuestSession(session);return session;}
export function inviteLink(token){const url=new URL(location.href);url.hash='invite='+token;url.search='';return url.href;}
export function readInviteToken(hash=location.hash){const value=new URLSearchParams(hash.slice(1)).get('invite')||'';return /^[\w-]{20,80}$/.test(value)?value:'';}
