import {useEffect,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Check,LoaderCircle,Plus,Search,X} from 'lucide-react';
import UiSwitch from './UiSwitch.jsx';
import {fetchCatalog} from './catalog.js';

// What one guest may open: the whole library or titles the owner picks,
// and separately whether they may watch and/or read.
const READ=new Set(['manga','ranobe','book','manhwa','manhua','novel','one_shot']);
const keyOf=item=>(READ.has(item.kind)?'manga':'anime')+':'+(item.ids?.mal||'');
export function accessSummary(access){
 const a=access||{scope:'all',watch:true,read:true,titles:[]};
 const what=[a.watch&&'смотреть',a.read&&'читать'].filter(Boolean).join(' и ')||'ничего';
 return (a.scope==='all'?'Вся библиотека':'Тайтлов: '+(a.titles?.length||0))+' · '+what;
}
export default function GuestAccessEditor({guest,busy,onSave}){
 const reduce=useReducedMotion(),initial=guest.access||{scope:'all',watch:true,read:true,titles:[]};
 const [access,setAccess]=useState(initial),[query,setQuery]=useState(''),[kind,setKind]=useState('anime'),[results,setResults]=useState([]),[searching,setSearching]=useState(false);
 useEffect(()=>setAccess(guest.access||{scope:'all',watch:true,read:true,titles:[]}),[guest.id,JSON.stringify(guest.access||{})]);
 useEffect(()=>{
  if(access.scope!=='titles'||query.trim().length<2){setResults([]);return;}
  const abort=new AbortController(),timer=setTimeout(()=>{setSearching(true);
   fetchCatalog('shikimori',{query:query.trim(),kind,server:window.MEDIA_VAULT_CONFIG?.importServerUrl,signal:abort.signal,page:1})
    .then(items=>{if(!abort.signal.aborted)setResults(items.filter(i=>i.ids?.mal).slice(0,8));}).catch(()=>{if(!abort.signal.aborted)setResults([]);}).finally(()=>{if(!abort.signal.aborted)setSearching(false);});},350);
  return()=>{clearTimeout(timer);abort.abort();};
 },[query,kind,access.scope]);
 const chosen=new Set((access.titles||[]).map(t=>t.key));
 const add=item=>{const key=keyOf(item);if(chosen.has(key))return;setAccess(a=>({...a,titles:[...(a.titles||[]),{key,title:item.title||'',cover:/^https:\/\//.test(item.cover||'')?item.cover:''}]}));};
 const remove=key=>setAccess(a=>({...a,titles:(a.titles||[]).filter(t=>t.key!==key)}));
 const changed=JSON.stringify(access)!==JSON.stringify(initial);
 return <div className="guest-access-editor">
  <div className="guest-access-scope" role="group" aria-label={'Доступ гостя '+guest.name}>{[['all','Вся библиотека'],['titles','Только выбранные тайтлы']].map(([id,label])=><button key={id} type="button" aria-pressed={access.scope===id} onClick={()=>setAccess(a=>({...a,scope:id}))}>{access.scope===id&&<motion.span className="guest-access-scope-active" layoutId={'guest-scope-'+guest.id} transition={reduce?{duration:0}:{type:'spring',stiffness:420,damping:36}}/>}<span>{label}</span></button>)}</div>
  <div className="guest-access-kinds">
   <label><UiSwitch checked={!!access.watch} onCheckedChange={v=>setAccess(a=>({...a,watch:v}))} aria-label="Разрешить смотреть"/>Смотреть аниме и фильмы</label>
   <label><UiSwitch checked={!!access.read} onCheckedChange={v=>setAccess(a=>({...a,read:v}))} aria-label="Разрешить читать"/>Читать мангу и ранобэ</label>
  </div>
  {access.scope==='titles'&&<>
   <ul className="guest-access-titles"><AnimatePresence initial={false}>{(access.titles||[]).map(t=><motion.li key={t.key} layout={!reduce} initial={reduce?false:{opacity:0,scale:.9}} animate={{opacity:1,scale:1}} exit={{opacity:0,scale:.9}}>{t.cover&&<img src={t.cover} alt="" referrerPolicy="no-referrer"/>}<span>{t.title||t.key}</span><small>{t.key.startsWith('manga')?'чтение':'просмотр'}</small><button type="button" aria-label={'Убрать '+(t.title||t.key)} onClick={()=>remove(t.key)}><X size={13}/></button></motion.li>)}</AnimatePresence></ul>
   {!access.titles?.length&&<p className="fine">Пока ничего не открыто. Найди тайтл и добавь его.</p>}
   <div className="guest-access-search">
    <div className="guest-access-search-field"><Search size={15}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Найти тайтл, чтобы открыть его гостю" aria-label="Поиск тайтла для гостя"/>{searching&&<LoaderCircle className="guest-access-spin" size={15}/>}</div>
    <div className="guest-access-kind" role="group" aria-label="Тип">{[['anime','Аниме'],['manga','Манга']].map(([id,label])=><button key={id} type="button" aria-pressed={kind===id} onClick={()=>setKind(id)}>{label}</button>)}</div>
   </div>
   {results.length>0&&<ul className="guest-access-results">{results.map(item=>{const on=chosen.has(keyOf(item));return <li key={item.id}><button type="button" disabled={on} onClick={()=>add(item)}>{item.cover&&<img src={item.cover} alt="" referrerPolicy="no-referrer"/>}<span><strong>{item.title}</strong><small>{[item.year,item.format].filter(Boolean).join(' · ')}</small></span>{on?<Check size={15}/>:<Plus size={15}/>}</button></li>;})}</ul>}
  </>}
  <div className="guest-access-actions"><button type="button" className="btn btn-primary btn-small" disabled={busy||!changed} onClick={()=>onSave(access)}>Сохранить доступ</button>{changed&&<button type="button" className="text-link" onClick={()=>setAccess(initial)}>Отменить</button>}</div>
 </div>;
}
