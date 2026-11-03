import {useEffect,useState} from 'react';
const cached=new Map(),pending=new Map();
export async function loadWatchOrder(identity,server,{signal}={}){
 if(!/^[1-9]\d{0,11}$/.test(String(identity||''))||!server)return null;
 const key=server+':'+identity,hit=cached.get(key);signal?.throwIfAborted();if(hit&&hit.until>Date.now())return hit.value;
 if(!pending.has(key)){
  const work=fetch(server+'/metadata/watch-order?identity='+encodeURIComponent(identity),{signal:AbortSignal.timeout(25000)}).then(async r=>{if(!r.ok)throw Error('Связи сезонов временно недоступны.');const value=await r.json();if(!Array.isArray(value.items))throw Error('Каталог не предоставил связи сезонов.');cached.set(key,{value,until:Date.now()+300000});while(cached.size>80)cached.delete(cached.keys().next().value);return value;});pending.set(key,work);work.finally(()=>pending.delete(key)).catch(()=>{});
 }
 const value=await pending.get(key);signal?.throwIfAborted();return value;
}
export function useFranchiseSeasons(identity,server){
 const[value,setValue]=useState(null);useEffect(()=>{const abort=new AbortController();setValue(null);loadWatchOrder(identity,server,{signal:abort.signal}).then(data=>{if(!abort.signal.aborted)setValue(data);}).catch(()=>{});return()=>abort.abort();},[identity,server]);return value?.seasons||[];
}
export function episodeDetail(title,number){
 const value=String(title||'').trim(),n=String(Number(number));
 const match=value.match(/^(?:(?:серия|эпизод|episode|ep\.?|series)\s*0*(\d+)|0*(\d+)\s*(?:серия|эпизод|episode|ep\.?|series))\s*(?:[:.\-–—]\s*)?(.*)$/i);
 if(!match||String(Number(match[1]||match[2]))!==n)return value||undefined;
 return match[3].trim()||undefined;
}

export function catalogueSeasonHint(item){
 const names=[item?.title,item?.titles?.ru,item?.titles?.en,...(item?.aliases||[])].filter(Boolean);
 for(const name of names){const match=name.match(/(\d{1,2})(?:st|nd|rd|th)\s+season|(?:сезон|season)\s*(\d{1,2})/i);if(match)return Number(match[1]||match[2]);}
 for(const name of names){const match=name.match(/\s(\d{1,2})(?:\.\s*(?:часть|part)\s*\d+)?$/i);if(match)return Number(match[1]);}
 return null;
}
