// Which language of dubs, chapters and books to prefer on this device.
// 'all' keeps every language; the interface language decides what comes first.
import {useEffect,useState} from 'react';
import {uiLanguage} from './i18n/index.js';
export const CONTENT_LANGUAGES=[['all','Все языки'],['ru','Русский'],['uk','Українська']];
const KEY='mediavault_content_language_v1',listeners=new Set();
export function contentLanguage(storage=globalThis.localStorage){try{const value=storage?.getItem(KEY);return CONTENT_LANGUAGES.some(([id])=>id===value)?value:'all';}catch{return 'all';}}
export function setContentLanguage(value,storage=globalThis.localStorage){
 if(!CONTENT_LANGUAGES.some(([id])=>id===value))return;
 try{storage?.setItem(KEY,value);}catch{}
 for(const listener of listeners)listener(value);
}
export function useContentLanguage(){
 const [value,setValue]=useState(contentLanguage);
 useEffect(()=>{listeners.add(setValue);return()=>listeners.delete(setValue);},[]);
 return value;
}
// Ukrainian first when chosen or when the interface itself is Ukrainian.
export function preferredVoiceLanguage(filter=contentLanguage()){return filter==='all'?(uiLanguage()==='uk'?'uk':'ru'):filter;}
export function voiceMatches(voice,filter){
 const language=voice?.language||'und';
 return filter==='all'||(filter==='uk'?language==='uk':language!=='uk');
}

// A shelf like "LostFilm" can ask the next opened title to start with its dub.
const VOICE_HINT='mediavault_voice_hint_v1';
const comparable=value=>String(value||'').toLocaleLowerCase('ru').replace(/[^\p{L}\p{N}]+/gu,'');
export function rememberVoiceHint(voice,titles,storage=globalThis.sessionStorage){
 try{storage?.setItem(VOICE_HINT,JSON.stringify({voice,titles:titles.map(comparable).filter(Boolean),expires:Date.now()+30*60e3}));}catch{}
}
export function voiceHintFor(item,storage=globalThis.sessionStorage){
 try{
  const hint=JSON.parse(storage?.getItem(VOICE_HINT)||'null');
  if(!hint||hint.expires<Date.now())return '';
  const names=[item?.title,...Object.values(item?.titles||{}),...(item?.aliases||[])].map(comparable);
  return names.some(name=>hint.titles.includes(name))?hint.voice:'';
 }catch{return '';}
}
