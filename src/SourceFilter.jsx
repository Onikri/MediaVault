import {useEffect,useRef,useState} from 'react';
import Icon from './Icons.jsx';
export default function SourceFilter({service,language='all',value,onChange,label='Источники'}){
 const [query,setQuery]=useState(''),[options,setOptions]=useState([]),[error,setError]=useState(''),[open,setOpen]=useState(false),[labels,setLabels]=useState({}),root=useRef(null);
 useEffect(()=>{const abort=new AbortController();if(service.status!=='connected'||Number(service.session?.serverVersion)<16)return;
  const timer=setTimeout(()=>service.request('/discovery/manga/sources?'+new URLSearchParams({language,q:query}),{signal:abort.signal}).then(data=>{if(!abort.signal.aborted){setOptions(data.sources||[]);setLabels(old=>({...old,...Object.fromEntries((data.sources||[]).map(s=>[s.id,s.name]))}));setError('');}}).catch(e=>{if(!abort.signal.aborted)setError(e.message);}),query?180:0);
  return()=>{clearTimeout(timer);abort.abort();};
 },[query,language,service.server,service.status,service.session?.serverVersion]);
 useEffect(()=>{const close=e=>{if(!root.current?.contains(e.target))setOpen(false);};document.addEventListener('pointerdown',close);return()=>document.removeEventListener('pointerdown',close);},[]);
 return <div className="world-source-filter" ref={root}><label htmlFor="worldSourceQuery">{label} <small>{value.length?value.length+' выбрано':'Все подключённые'}</small></label><div className="source-filter-input"><Icon name="search" size={16}/><input id="worldSourceQuery" value={query} onChange={e=>{setQuery(e.target.value);setOpen(true);}} onFocus={()=>setOpen(true)} onKeyDown={e=>{if(e.key==='Escape')setOpen(false);}} placeholder="Название сайта…" autoComplete="off" aria-expanded={open} aria-controls="worldSourceOptions" disabled={service.status!=='connected'||Number(service.session?.serverVersion)<16}/></div>
  {open&&<div id="worldSourceOptions" className="source-filter-options" role="group" aria-label="Выбрать источники">{options.map(s=><label key={s.id}><input type="checkbox" checked={value.includes(s.id)} onChange={()=>onChange(value.includes(s.id)?value.filter(id=>id!==s.id):[...value,s.id])}/><span>{s.name}<small>{s.language.toUpperCase()}{s.adult?' · 18+':''}</small></span></label>)}{!options.length&&<p>{error||'Совпадений нет'}</p>}<button type="button" className="text-link" onClick={()=>setOpen(false)}>Готово</button></div>}
  {!!value.length&&<div className="source-filter-chips">{value.map(id=><button type="button" key={id} onClick={()=>onChange(value.filter(v=>v!==id))} aria-label={'Убрать источник '+(labels[id]||id)}>{labels[id]||id}<Icon name="close" size={12}/></button>)}<button type="button" className="text-link" onClick={()=>onChange([])}>Все источники</button></div>}
 </div>;
}
