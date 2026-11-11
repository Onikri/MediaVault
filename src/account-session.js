// Short-lived Google access is encrypted on the device, never put in cookies
// or localStorage. A session-only login survives reload in its own tab.
import {deviceStore} from './device-storage.js';

const encoder=new TextEncoder(),decoder=new TextDecoder();
const TAB='mediavault_login_tab',LOGOUT='mediavault_login_epoch';
const marker=()=>{try{return localStorage.getItem(LOGOUT)||'';}catch{return '';}};
export const accountEpoch=marker;
const encode=value=>btoa(String.fromCharCode(...new Uint8Array(value)));
const decode=value=>Uint8Array.from(atob(value),c=>c.charCodeAt(0));
function tabId(){
 try{let id=sessionStorage.getItem(TAB);if(!id){id=crypto.randomUUID();sessionStorage.setItem(TAB,id);}return id;}catch{return null;}
}
function slot(remember){const id=remember?'remembered':tabId();return id?'account-access:'+id:null;}

export async function saveAccountSession(result,user,{remember,current=()=>true}={}){
 if(!result?.access_token||!user?.sub)return;
 const name=slot(remember);if(!name)throw Error('Хранилище сессии вкладки недоступно.');
 const epoch=marker();
 let key=await deviceStore('get','account-access-key');
 if(!key){key=await crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);key=await deviceStore('getOrPut','account-access-key',key);}
 const expiresAt=Date.now()+Math.max(0,Math.min(3600,Number(result.expires_in)||0))*1000;
 const iv=crypto.getRandomValues(new Uint8Array(12));
 const profile=Object.fromEntries(['sub','email','email_verified','name','given_name','picture'].map(k=>[k,user[k]]).filter(([,v])=>v!==undefined));
 const data=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:encoder.encode(name+'\n'+epoch)},key,
  encoder.encode(JSON.stringify({access_token:result.access_token,scope:result.scope,expiresAt,user:profile})));
 if(!current()||marker()!==epoch)return;
 await deviceStore('put',name,{epoch,iv:encode(iv),data:encode(data)});
}

export async function readAccountSession(remember){
 const name=slot(remember);if(!name)return null;
 const epoch=marker(),record=await deviceStore('get',name);
 if(!record||record.epoch!==epoch)return null;
 const key=await deviceStore('get','account-access-key');if(!key)return null;
 try{
  const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:decode(record.iv),additionalData:encoder.encode(name+'\n'+epoch)},key,decode(record.data));
  const result=JSON.parse(decoder.decode(plain));
  if(marker()!==epoch||!result.user?.sub||!result.user?.email_verified)return null;
  return {...result,valid:!!result.access_token&&result.expiresAt>Date.now()+30000,
   expires_in:Math.max(0,(result.expiresAt-Date.now())/1000)};
 }catch{return null;}
}

export async function clearAccountSession(){
 // The synchronous marker invalidates old writes even if logout races with
 // an IndexedDB transaction from a pending sign-in/refresh.
 const epoch=marker();
 try{localStorage.setItem(LOGOUT,crypto.randomUUID());}catch{}
 const names=[slot(true),slot(false)].filter(Boolean);
 await Promise.all(names.map(name=>deviceStore('deleteIf',name,{epoch})));
}
