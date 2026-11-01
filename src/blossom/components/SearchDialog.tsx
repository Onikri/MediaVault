import {useCallback,useEffect,useRef,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ArrowUpRight,Clock,LoaderCircle,Search,X} from 'lucide-react';
import {useGlobalSearch,SEARCH_KINDS} from '../../use-global-search.js';
import {Poster} from '../../ImportParts.jsx';
import './morph-search.css';

const SPRING={type:'spring',stiffness:380,damping:28,mass:.8} as const;
const RECENT_KEY='mediavault_search_recents_v1';
const typeLabel=(kind:string)=>Object.fromEntries(SEARCH_KINDS)[kind]||'Сериал';
const sameTerm=(a:string,b:string)=>a.trim().toLocaleLowerCase()===b.trim().toLocaleLowerCase();
function searchGeometry(){
 if(typeof window==='undefined')return {width:600,seedWidth:112,seedHeight:40,x:0,y:-24};
 const width=Math.max(280,Math.min(620,window.innerWidth-24)),right=window.innerWidth<=640?12:24,top=window.innerWidth<=640?70:82;
 const trigger=document.querySelector('.blossom-navbar .header-search')?.getBoundingClientRect();
 return {width,seedWidth:trigger?.width||112,seedHeight:trigger?.height||40,
  x:trigger?trigger.right-(window.innerWidth-right):0,y:trigger?trigger.top-top:-24};
}
function Highlight({text,query}:{text:string;query:string}){
 const at=query?text.toLocaleLowerCase().indexOf(query.toLocaleLowerCase()):-1;
 return at<0?<>{text}</>:<>{text.slice(0,at)}<mark>{text.slice(at,at+query.length)}</mark>{text.slice(at+query.length)}</>;
}
export function SearchDialog({service,onClose,onChoose,onBrowse}:{service:any;onClose:()=>void;onChoose:(item:any)=>void;onBrowse:(query:string,kind:string)=>void}){
 const reduced=useReducedMotion(),[geometry]=useState(searchGeometry);
 const [query,setQuery]=useState(''),[kind,setKind]=useState('all'),[activeId,setActiveId]=useState<string|null>(null),[composing,setComposing]=useState(false),[closing,setClosing]=useState(false);
 const [recents,setRecents]=useState<string[]>(()=>{try{const stored=JSON.parse(localStorage.getItem(RECENT_KEY)||'[]');return Array.isArray(stored)?stored.filter((term):term is string=>typeof term==='string').slice(0,5):[];}catch{return [];}});
 const input=useRef<HTMLInputElement>(null),closeHandled=useRef(false);
 const state=useGlobalSearch(query,kind,service,composing),items=state.items.slice(0,24),index=Math.max(0,items.findIndex((x:any)=>x.id===activeId));
 const remember=useCallback((term:string)=>{const value=term.trim();if(!value)return;setRecents(old=>{const next=[value,...old.filter(x=>!sameTerm(x,value))].slice(0,5);try{localStorage.setItem(RECENT_KEY,JSON.stringify(next));}catch{}return next;});},[]);
 const forget=useCallback((term?:string)=>setRecents(old=>{const next=term?old.filter(x=>x!==term):[];try{localStorage.setItem(RECENT_KEY,JSON.stringify(next));}catch{}return next;}),[]);
 const close=useCallback(()=>{if(closeHandled.current)return;if(reduced){closeHandled.current=true;onClose();}else setClosing(true);},[onClose,reduced]);
 const choose=(item:any)=>{remember(query||item.title);onChoose(item);};
 const browse=()=>{remember(query);onBrowse(query,kind);};
 useEffect(()=>{if(closing)return;input.current?.focus({preventScroll:true});},[closing]);
 const start={opacity:0,width:geometry.seedWidth,height:geometry.seedHeight,x:geometry.x,y:geometry.y,borderRadius:28};
 const expanded={opacity:1,width:geometry.width,height:'auto',x:0,y:0,borderRadius:26};
 const transition=reduced?{duration:0}:SPRING;
 return <Dialog.Root open onOpenChange={next=>{if(!next)close();}}>
  <Dialog.Portal forceMount>
   <Dialog.Overlay className={'dialog-backdrop blossom-search-backdrop morph-search-backdrop'+(closing?' is-closing':'')}/>
   <Dialog.Content asChild forceMount aria-describedby="blossomSearchHelp">
    <motion.div className="search-dialog blossom-search-dialog morph-search-dialog" initial={reduced?expanded:start} animate={closing?{...start,transition:{type:'spring',stiffness:520,damping:40,mass:.6}}:expanded} transition={transition} style={{transformOrigin:'right top'}} onAnimationComplete={()=>{if(closing&&!closeHandled.current){closeHandled.current=true;onClose();}}}>
     <Dialog.Title className="sr-only">Поиск в библиотеке</Dialog.Title>
     <div className="morph-search-bar">
      <Search size={20} aria-hidden="true"/>
      <input ref={input} autoFocus autoComplete="off" maxLength={160} role="combobox" aria-expanded={items.length>0} aria-controls="blossomSearchHits" aria-activedescendant={items.length?'blossom-hit-'+index:undefined} value={query} aria-label="Поиск произведения" placeholder="Аниме, манга, книги, музыка…" onCompositionStart={()=>setComposing(true)} onCompositionEnd={()=>setComposing(false)} onChange={event=>{setQuery(event.target.value);setActiveId(null);}} onKeyDown={event=>{if(event.nativeEvent.isComposing||composing)return;if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();const next=activeId==null?0:Math.max(0,Math.min(items.length-1,index+(event.key==='ArrowDown'?1:-1)));setActiveId(items[next]?.id||null);document.getElementById('blossom-hit-'+next)?.scrollIntoView({block:'nearest'});}else if(event.key==='Enter'){event.preventDefault();if(items[index])choose(items[index]);else if(query.trim().length>=2)browse();}}}/>
      {state.loading?<LoaderCircle className="morph-search-spinner" size={17} aria-label="Поиск выполняется"/>:query?<button type="button" aria-label="Очистить запрос" className="morph-search-clear" onClick={()=>{setQuery('');setActiveId(null);input.current?.focus();}}><X size={16}/></button>:<kbd>Ctrl K</kbd>}
      <Dialog.Close asChild><button className="morph-search-close" type="button" aria-label="Закрыть поиск" onClick={event=>{event.preventDefault();close();}}><X size={18}/></button></Dialog.Close>
     </div>
     <div className="morph-search-filters" role="group" aria-label="Где искать">{SEARCH_KINDS.map(([id,label])=><button key={id} type="button" className="morph-search-chip" aria-pressed={kind===id} onClick={()=>{setKind(id);setActiveId(null);}}>{kind===id&&<motion.span layoutId="morph-search-active-category" className="morph-search-chip-active" transition={transition}/>}<span>{label}</span></button>)}</div>
     <div className="morph-search-list" id="blossomSearchHits" role="listbox" aria-label="Результаты поиска" aria-busy={state.loading}>
      {!query.trim()&&<><div className="morph-search-section"><span>Недавние запросы</span>{recents.length>0&&<button type="button" onClick={()=>forget()}>Очистить</button>}</div>{recents.length>0?recents.map(term=><div className="morph-search-recent" key={term}><button type="button" onClick={()=>{setQuery(term);setActiveId(null);input.current?.focus();}}><Clock size={15}/><span>{term}</span></button><button type="button" aria-label={'Удалить запрос '+term} onClick={()=>forget(term)}><X size={14}/></button></div>):<p className="morph-search-empty">Введи минимум два символа — поиск работает по онлайн-каталогам MediaVault.</p>}</>}
      {query.trim()&&query.trim().length<2&&<p className="morph-search-empty">Введи хотя бы два символа.</p>}
      {query.trim().length>=2&&<><div className="morph-search-section"><span>{state.loading?'Ищем материалы…':'Результаты поиска'}</span>{items.length>0&&<span>{items.length}{state.loading?' +':''}</span>}</div><AnimatePresence initial={false}>{items.map((item:any,i:number)=><motion.button key={item.id} type="button" role="option" aria-selected={index===i} id={'blossom-hit-'+i} onMouseEnter={()=>setActiveId(item.id)} onClick={()=>choose(item)} className={'morph-search-result'+(index===i?' is-active':'')} initial={reduced?false:{opacity:0,y:6}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-4}} transition={{duration:reduced?0:.2,delay:reduced?0:Math.min(i,5)*.025}}><span className="morph-search-poster"><Poster item={item}/></span><span className="morph-search-result-meta"><strong><Highlight text={item.title} query={query.trim()}/></strong><small><b>{typeLabel(item.kind)}</b>{[item.year,item.authors?.join(', ')||item.artists?.join(', '),item.format].filter(Boolean).map(v=>' · '+v)}</small></span><ArrowUpRight size={17}/></motion.button>)}</AnimatePresence>{!state.loading&&!items.length&&<p className="morph-search-empty" role="status">Совпадений нет. Попробуй другое название.</p>}{state.loading&&<p className="morph-search-progress" role="status">Каталоги дополняют результаты…</p>}</>}
     </div>
     <footer className="morph-search-footer" id="blossomSearchHelp"><span><kbd>↑ ↓</kbd> Выбрать · <kbd>↵</kbd> Открыть · <kbd>Esc</kbd> Закрыть</span>{query.trim().length>=2&&<button type="button" onClick={browse}>Полный поиск <ArrowUpRight size={13}/></button>}</footer>
    </motion.div>
   </Dialog.Content>
  </Dialog.Portal>
 </Dialog.Root>;
}
