import {useState} from 'react';
import {mangaLanguageName} from './manga-import.js';

export default function MangaSearchDiagnostics({providers=[]}){
 const [limit,setLimit]=useState(20);
 const issues=providers.filter(provider=>['unavailable','skipped'].includes(provider.state));
 if(!issues.length)return null;
 return <details className="provider-diagnostics">
  <summary>Причины по источникам · {issues.length}</summary>
  {issues.slice(0,limit).map(provider=><p key={provider.id}>
   <b>{provider.name}</b>
   <span>{mangaLanguageName(provider.language)} · {provider.message||'Источник недоступен'}{Number.isFinite(provider.elapsedMs)?' · '+(provider.elapsedMs/1000).toLocaleString('ru-RU',{maximumFractionDigits:1})+' с':''}</span>
  </p>)}
  {limit<issues.length&&<button type="button" className="text-link" onClick={()=>setLimit(n=>n+20)}>Ещё источники</button>}
 </details>;
}
