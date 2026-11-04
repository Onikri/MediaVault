import {useEffect,useState} from 'react';
export const favoriteKey=item=>`${item.kind||item.section||'anime'}:${item.ids?.mal||item.metadataId||item.sourceId?'mal:'+(item.ids?.mal||item.metadataId||item.sourceId):(item.provider||'local')+':'+(item.providerId||item.id)}`;
export function useCatalogFavorites(userId='guest'){
 const key='mv_catalog_favorites_v1:'+userId,read=()=>{try{const value=JSON.parse(localStorage.getItem(key)||'[]');return Array.isArray(value)?value:[];}catch{return [];}};
 const [values,setValues]=useState(read);
 useEffect(()=>{const update=()=>setValues(read());update();addEventListener('mv-favorites',update);addEventListener('storage',update);return()=>{removeEventListener('mv-favorites',update);removeEventListener('storage',update);};},[key]);
 return {has:item=>values.includes(favoriteKey(item)),toggle:item=>{const id=favoriteKey(item),old=read(),next=old.includes(id)?old.filter(v=>v!==id):[...old,id];try{localStorage.setItem(key,JSON.stringify(next.slice(-5000)));}catch{setValues(next.slice(-5000));}dispatchEvent(new Event('mv-favorites'));}};
}
