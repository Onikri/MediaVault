import {useSyncExternalStore} from 'react';

// What the title page's materials (player, manga or ranobe reader) know and the
// showcase above them needs: the share payload for the hero's share button and
// the published volume of the chosen source (chapters, volumes, episodes).
const listeners=new Set();
let state={share:null,stats:null};
function emit(){for(const listener of listeners)listener();}
function subscribe(listener){listeners.add(listener);return()=>listeners.delete(listener);}
function patch(change){state={...state,...change};emit();}

// Every mounted player or reader publishes under its own owner key: a player
// kept alive in the background (retained media) or one that unmounts later
// must never replace or erase the share payload of the title on screen.
const shares=new Map();
export function publishTitleShare(value,owner='page'){
 if(shares.get(owner)===(value||undefined))return;
 shares.delete(owner);
 if(value)shares.set(owner,value);
 patch({share:[...shares.values()].pop()||null});
}
// The newest payload of this title (by title id), or the newest of all.
function titleShare(id){
 if(id===undefined)return state.share;
 const values=[...shares.values()];
 for(let index=values.length-1;index>=0;index--)if(values[index]?.title?.id===id)return values[index];
 return null;
}
export function publishTitleStats(value){
 const same=state.stats&&value&&Object.keys({...state.stats,...value}).every(key=>state.stats[key]===value[key]);
 if(!same&&state.stats!==value)patch({stats:value});
}
export function useTitleShare(id){return useSyncExternalStore(subscribe,()=>titleShare(id),()=>null);}
export const readTitleShare=titleShare;
export function useTitleStats(){return useSyncExternalStore(subscribe,()=>state.stats,()=>null);}

// Russian plural forms: plural(5,['глава','главы','глав']) → 'глав'.
export function plural(count,forms){
 const n=Math.abs(Math.trunc(Number(count)||0)),tens=n%100,ones=n%10;
 return forms[tens>=11&&tens<=14?2:ones===1?0:ones>=2&&ones<=4?1:2];
}
export const counted=(count,forms)=>count+' '+plural(count,forms);
