import {useCallback,useSyncExternalStore} from 'react';

// Favourite reading sites, per profile and kind (manga, ranobe, book). A
// favourite site is checked first, opened first and listed first.
const KEY='mv_source_favorites_v1';
const listeners=new Set();
function read(){try{return JSON.parse(localStorage.getItem(KEY)||'{}')||{};}catch{return {};}}
let cache=read();
function write(next){cache=next;try{localStorage.setItem(KEY,JSON.stringify(next));}catch{}for(const l of listeners)l();}
globalThis.addEventListener?.('storage',event=>{if(event.key===KEY){cache=read();for(const l of listeners)l();}});
export const siteOf=source=>String(source?.sourceId||source?.provider||source?.providerName||'').toLowerCase();
export function useSourceFavorites(userId,kind){
 const scope=(userId||'guest')+':'+kind;
 const list=useSyncExternalStore(cb=>{listeners.add(cb);return()=>listeners.delete(cb);},()=>cache[scope]||EMPTY,()=>EMPTY);
 const toggle=useCallback(source=>{const site=siteOf(source);if(!site)return;const now=cache[scope]||[];write({...cache,[scope]:now.includes(site)?now.filter(s=>s!==site):[...now,site]});},[scope]);
 return {list,has:source=>list.includes(siteOf(source)),toggle};
}
const EMPTY=[];

// Order: favourite sites; then sources whose published chapters come closest
// to the work's total (the most complete translation); unknown counts last.
// Without a known total the source with more chapters goes first.
export function rankSources(sources,{favorites=[],expected=0,count=()=>null}={}){
 const total=Number(expected)||0;
 const score=source=>{
  const n=Number(count(source));
  const known=Number.isFinite(n)&&n>0;
  const distance=!known?Infinity:total?Math.abs(total-n)/total:1/(1+n);
  return [favorites.includes(siteOf(source))?0:1,known?0:1,distance];
 };
 return sources.map((source,index)=>({source,index,key:score(source)}))
  .sort((a,b)=>a.key[0]-b.key[0]||a.key[1]-b.key[1]||a.key[2]-b.key[2]||a.index-b.index)
  .map(row=>row.source);
}
