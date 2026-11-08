// Ukrainian title and synopsis (Hikka, via the MediaVault server) when the
// interface is Ukrainian. Russian interface: nothing is requested.
import {useEffect,useState} from 'react';
import {useUiLanguage} from './i18n/LanguageSettings.jsx';

const cache=new Map();
const KINDS=new Set(['anime','tv','movie','manga','ranobe']);

export function useUkrainianTitle(server,kind,mal){
 const language=useUiLanguage(),key=kind+':'+mal;
 const [value,setValue]=useState(()=>cache.get(key)||null);
 useEffect(()=>{
  if(language!=='uk'||!server||!KINDS.has(kind)||!/^\d{1,9}$/.test(String(mal||''))){setValue(null);return;}
  if(cache.has(key)){setValue(cache.get(key));return;}
  const abort=new AbortController();
  fetch(server+'/metadata/hikka?'+new URLSearchParams({kind,identity:String(mal)}),{signal:abort.signal})
   .then(r=>r.ok?r.json():null).then(data=>{const found=data?.value||null;cache.set(key,found);if(!abort.signal.aborted)setValue(found);}).catch(()=>{});
  return()=>abort.abort();
 },[language,server,key]);
 return language==='uk'?value:null;
}
