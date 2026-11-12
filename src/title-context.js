import {useSyncExternalStore} from 'react';

// What the title page's materials (player, manga or ranobe reader) know and the
// showcase above them needs: the share payload for the hero's share button and
// the published volume of the chosen source (chapters, volumes, episodes).
const listeners=new Set();
let state={share:null,stats:null};
function emit(){for(const listener of listeners)listener();}
function subscribe(listener){listeners.add(listener);return()=>listeners.delete(listener);}
function patch(change){state={...state,...change};emit();}

export function publishTitleShare(value){if(state.share!==value)patch({share:value});}
export function publishTitleStats(value){
 const same=state.stats&&value&&Object.keys({...state.stats,...value}).every(key=>state.stats[key]===value[key]);
 if(!same&&state.stats!==value)patch({stats:value});
}
export function useTitleShare(){return useSyncExternalStore(subscribe,()=>state.share,()=>null);}
export function useTitleStats(){return useSyncExternalStore(subscribe,()=>state.stats,()=>null);}

// Russian plural forms: plural(5,['глава','главы','глав']) → 'глав'.
export function plural(count,forms){
 const n=Math.abs(Math.trunc(Number(count)||0)),tens=n%100,ones=n%10;
 return forms[tens>=11&&tens<=14?2:ones===1?0:ones>=2&&ones<=4?1:2];
}
export const counted=(count,forms)=>count+' '+plural(count,forms);
