import {useCallback,useEffect,useId,useMemo,useRef,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ArrowUpRight,Clock,LoaderCircle,Search,X} from 'lucide-react';
import {useGlobalSearch,SEARCH_KINDS} from '../../use-global-search.js';
import {Poster} from '../../ImportParts.jsx';
import './morph-search.css';

/* MorphingSearchChips port: the original 56px glass bar, centered panel,
   spring-grown glass surface, animated chips, recents and list cursor.
   Live MediaVault catalog results remain available below the suggestions. */
const ENTER={type:'spring',stiffness:380,damping:28,mass:.8} as const;
const EXIT={type:'spring',stiffness:520,damping:40,mass:.6} as const;
const SWAP={type:'spring',stiffness:420,damping:34,mass:.7} as const;
const KEY='mediavault_search_recents_v1';
const typeLabel=(kind:string)=>Object.fromEntries(SEARCH_KINDS)[kind]||'Сериал';
const same=(a:string,b:string)=>a.trim().toLocaleLowerCase()===b.trim().toLocaleLowerCase();
function coordinates(){
 const width=Math.min(560,Math.max(280,window.innerWidth-24)),target=document.querySelector('.blossom-navbar .header-center-search .header-search')?.getBoundingClientRect();
 return {width,left:(window.innerWidth-width)/2,top:target?.top??18,seedWidth:target?.width??112,seedHeight:target?.height??38};
}
function Highlight({text,query}:{text:string,query:string}){const at=query?text.toLocaleLowerCase().indexOf(query.toLocaleLowerCase()):-1;return at<0?<>{text}</>:<>{text.slice(0,at)}<strong>{text.slice(at,at+query.length)}</strong>{text.slice(at+query.length)}</>;}
export function SearchDialog({service,onClose,onChoose,onBrowse}:{service:any,onClose:()=>void,onChoose:(item:any)=>void,onBrowse:(query:string,kind:string)=>void}){
 const reduce=useReducedMotion(),[geometry]=useState(coordinates),id=useId();
 const [query,setQuery]=useState(''),[kind,setKind]=useState('all'),[composing,setComposing]=useState(false),[closing,setClosing]=useState(false);
 const [chips,setChips]=useState<string[]>([]),[marked,setMarked]=useState<string|null>(null),[activeId,setActiveId]=useState<string|null>(null),[rowCursor,setRowCursor]=useState(0),[panelFloor,setPanelFloor]=useState(0);
 const [recents,setRecents]=useState<string[]>(()=>{try{const saved=JSON.parse(localStorage.getItem(KEY)||'[]');return Array.isArray(saved)?saved.filter((v):v is string=>typeof v==='string').slice(0,5):[];}catch{return[];}});
 const input=useRef<HTMLInputElement>(null),finished=useRef(false),panelRows=useRef<HTMLDivElement>(null);
 const searchText=query.trim()||chips.at(-1)||'';
 const state=useGlobalSearch(searchText,kind,service,composing),items=state.items.slice(0,24),index=Math.max(0,items.findIndex((x:any)=>x.id===activeId));
 const suggestions=useMemo(()=>!query.trim()?recents.map(label=>({id:'recent:'+label,label,kind:'recent'})): [
  {id:'query:'+query.trim(),label:query.trim(),kind:'query'},
  ...recents.filter(v=>v.toLowerCase().includes(query.trim().toLowerCase())&&!same(v,query)).slice(0,5).map(label=>({id:'recent:'+label,label,kind:'recent'}))
 ],[recents,query]);
 const persist=useCallback((next:string[])=>{setRecents(next);try{localStorage.setItem(KEY,JSON.stringify(next));}catch{}},[]);
 const remember=useCallback((term:string)=>{const value=term.trim();if(value)persist([value,...recents.filter(v=>!same(value,v))].slice(0,5));},[recents,persist]);
 const close=useCallback(()=>{if(finished.current||closing)return;if(reduce){finished.current=true;onClose();}else setClosing(true);},[closing,onClose,reduce]);
 const choose=(item:any)=>{remember(searchText||item.title);onChoose(item);};
 const browse=()=>{if(searchText)remember(searchText);onBrowse(searchText,kind);};
 const addChip=(text:string)=>{const v=text.trim();if(!v)return;setChips(old=>old.some(c=>same(c,v))?old:[...old,v]);setQuery('');setMarked(null);remember(v);setRowCursor(0);input.current?.focus();};
 const removeChip=(text:string)=>{setChips(old=>old.filter(c=>c!==text));setMarked(null);input.current?.focus();};
 const forget=(text?:string)=>persist(text?recents.filter(v=>v!==text):[]);
 useEffect(()=>{const header=document.querySelector('.blossom-navbar');header?.classList.add('is-search-open');input.current?.focus({preventScroll:true});return()=>header?.classList.remove('is-search-open');},[]);
 useEffect(()=>{if(!closing)return;const t=setTimeout(()=>{if(!finished.current){finished.current=true;onClose();}},450);return()=>clearTimeout(t);},[closing,onClose]);
 useEffect(()=>{const escape=(event:KeyboardEvent)=>{if(event.key!=='Escape'||event.isComposing)return;event.preventDefault();event.stopPropagation();event.stopImmediatePropagation();if(marked){setMarked(null);return;}if(query){setQuery('');setActiveId(null);return;}close();};document.addEventListener('keydown',escape,true);return()=>document.removeEventListener('keydown',escape,true);},[marked,query,close]);
 useEffect(()=>{if(closing)return;const handler=(event:PointerEvent)=>{const root=document.querySelector('.morph-search-dialog');const trigger=document.querySelector('.header-center-search');if(root?.contains(event.target as Node)||trigger?.contains(event.target as Node))return;close();};document.addEventListener('pointerdown',handler,true);return()=>document.removeEventListener('pointerdown',handler,true);},[closing,close]);
 useEffect(()=>{if(!panelRows.current||closing)return;const update=()=>setPanelFloor(old=>Math.max(old,panelRows.current?.offsetHeight||0));update();const ro=new ResizeObserver(update);ro.observe(panelRows.current);return()=>ro.disconnect();},[query,kind,closing,items.length]);
 const focusField=(event:React.PointerEvent)=>{if((event.target as Element).closest('button,input,a'))return;event.preventDefault();input.current?.focus();};
 const onInputKey=(event:React.KeyboardEvent<HTMLInputElement>)=>{
  if(composing||event.nativeEvent.isComposing||event.keyCode===229)return;
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(marked){setMarked(null);return;}if(query){setQuery('');return;}close();return;}
  if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();if(items.length){const next=activeId==null?0:Math.max(0,Math.min(items.length-1,index+(event.key==='ArrowDown'?1:-1)));setActiveId(items[next]?.id||null);document.getElementById(id+'-hit-'+next)?.scrollIntoView({block:'nearest'});}else setRowCursor(x=>(x+(event.key==='ArrowDown'?1:-1)+suggestions.length)%Math.max(1,suggestions.length));return;}
  if(event.key==='Enter'){event.preventDefault();if(items[index])choose(items[index]);else if(query.trim())addChip(query);else if(suggestions[rowCursor])addChip(suggestions[rowCursor].label);return;}
  if(event.key==='Backspace'&&event.currentTarget.selectionStart===0&&event.currentTarget.selectionEnd===0&&!query&&chips.length){event.preventDefault();const last=chips.at(-1)!;if(marked===last)removeChip(last);else setMarked(last);return;}
  if(event.key==='ArrowLeft'&&event.currentTarget.selectionStart===0&&!query&&chips.length){event.preventDefault();setMarked(chips.at(-1)!);}
 };
 return <Dialog.Root open modal={false} onOpenChange={value=>{if(!value)close();}}>
 <Dialog.Portal forceMount>
 <Dialog.Content asChild forceMount onEscapeKeyDown={event=>{event.preventDefault();if(marked){setMarked(null);return;}if(query){setQuery('');setActiveId(null);return;}close();}} aria-describedby={id+'-help'}>
 <motion.div className={'search-dialog blossom-search-dialog morph-search-dialog'+(closing?' is-closing':'')} style={{top:geometry.top,left:geometry.left,width:geometry.width,transformOrigin:'top center'}} initial={reduce?false:{opacity:0,y:-2}} animate={{opacity:closing?0:1,y:closing?-4:0}} transition={{duration:reduce?0:.16}}>
  <Dialog.Title className="sr-only">Поиск в библиотеке</Dialog.Title>
  <motion.div className="morph-search-bar" onPointerDown={focusField}
   initial={reduce?false:{width:geometry.seedWidth,height:geometry.seedHeight}}
   animate={{width:closing?geometry.seedWidth:'100%',height:closing?geometry.seedHeight:56}}
   transition={reduce?{duration:0}:(closing?EXIT:ENTER)}>
   <Search size={20} aria-hidden="true"/>
   <div className="morph-search-chips">
    <AnimatePresence initial={false} mode="popLayout">
     {chips.map(chip=><motion.span key={chip} layout="position" className={'morph-search-token'+(marked===chip?' is-marked':'')}
      initial={reduce?false:{opacity:0,scale:.6,filter:'blur(4px)'}} animate={{opacity:1,scale:1,filter:'blur(0px)'}} exit={{opacity:0,scale:.6,filter:'blur(4px)'}} transition={reduce?{duration:0}:SWAP}><span title={chip}>{chip}</span><button type="button" aria-label={'Удалить фильтр '+chip} onClick={()=>removeChip(chip)}><X size={13}/></button></motion.span>)}
    </AnimatePresence>
   </div>
   <motion.input ref={input} layout="position" transition={reduce?{duration:0}:SWAP} role="combobox" type="text" autoComplete="off" spellCheck={false} enterKeyHint="search" maxLength={160}
     aria-label="Поиск произведения" aria-expanded={!closing} aria-controls={id+'-suggestions'} aria-autocomplete="list"
     value={query} placeholder="Поиск" onChange={e=>{setQuery(e.target.value);setActiveId(null);setRowCursor(0);}} onCompositionStart={()=>setComposing(true)} onCompositionEnd={()=>setComposing(false)}
     onKeyDown={onInputKey}/>
   {state.loading?<LoaderCircle className="morph-search-spinner" size={18} aria-label="Поиск выполняется"/>:null}
   {(query||chips.length)>0?<button className="morph-search-clear" type="button" aria-label="Очистить запрос" onClick={()=>{setQuery('');setChips([]);input.current?.focus();}}><X size={17}/></button>:<kbd>Ctrl K</kbd>}
   <button className="morph-search-close" type="button" aria-label="Закрыть поиск" onClick={close}><X size={18}/></button>
  </motion.div>
  <AnimatePresence>
   {!closing&&<motion.div key="panel" className="morph-search-panel" initial={reduce?false:{width:112,height:40,y:-28,opacity:0}} animate={{width:'100%',height:'auto',y:0,opacity:1}} exit={reduce?{opacity:0}:{width:112,height:40,y:-28,opacity:0,transition:EXIT}} transition={reduce?{duration:0}:ENTER}>
    <motion.div className="morph-search-panel-content" initial={reduce?false:{opacity:0,y:-6}} animate={{opacity:1,y:0}} exit={{opacity:0}} transition={{duration:reduce?0:.18,delay:reduce?0:.12}}>
     <div className="morph-search-panel-heading"><span>{query.trim()?'Suggestions':'Recent'}</span>{!query.trim()&&recents.length>0&&<button type="button" onClick={()=>forget()}>Clear</button>}</div>
     <div className="morph-search-panel-rows" ref={panelRows} style={{minHeight:panelFloor||undefined}}>
      <div id={id+'-suggestions'} role="group" aria-label={query.trim()?'Подсказки':'Недавние запросы'} className="morph-search-suggestion-list">
       {suggestions.map((row,i)=><motion.button key={row.id} type="button" aria-current={rowCursor===i?'true':undefined}
        className={'morph-search-suggestion'+(rowCursor===i?' is-selected':'')}
        onMouseEnter={()=>setRowCursor(i)} onClick={()=>row.kind==='recent'?(setQuery(row.label),input.current?.focus()):addChip(row.label)}>
        {rowCursor===i&&<motion.span layoutId="morph-search-cursor" className="morph-search-suggestion-highlight" transition={SWAP}/>}
        {row.kind==='recent'?<Clock size={16}/>:<Search size={16}/>}<span><Highlight text={row.label} query={query.trim()}/></span>
        {row.kind==='recent'&&<span className="morph-search-remove-recent" role="button" tabIndex={-1} aria-label={'Удалить запрос '+row.label} onClick={e=>{e.stopPropagation();forget(row.label);}}><X size={14}/></span>}
       </motion.button>)}
       {!suggestions.length&&!query.trim()&&<p className="morph-search-empty">Начни вводить название — поиск по каталогам MediaVault.</p>}
      </div>
      <div className="morph-search-filters" role="group" aria-label="Где искать">{SEARCH_KINDS.map(([k,label])=><button key={k} className="morph-search-chip" type="button" aria-pressed={kind===k} onClick={()=>{setKind(k);setActiveId(null);}}>{kind===k&&<motion.span className="morph-search-chip-active" layoutId="morph-search-active-category" transition={SWAP}/>}<span>{label}</span></button>)}</div>
      {searchText.length>=2&&<div className="morph-search-results">
       <div className="morph-search-panel-heading"><span>Результаты поиска</span>{items.length>0&&<span>{items.length}{state.loading?' +':''}</span>}</div>
       <div id="blossomSearchHits" className="morph-search-results-list" role="listbox" aria-label="Результаты поиска" aria-busy={state.loading}>
        <AnimatePresence initial={false}>{items.map((item:any,i:number)=><motion.button key={item.id} id={id+'-hit-'+i} role="option" aria-selected={index===i} type="button" className={'morph-search-result'+(index===i?' is-active':'')} onMouseEnter={()=>setActiveId(item.id)} onClick={()=>choose(item)} initial={reduce?false:{opacity:0,y:6}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-4}} transition={{duration:reduce?0:.18,delay:reduce?0:Math.min(i,5)*.025}}>
         <span className="morph-search-poster"><Poster item={item}/></span><span className="morph-search-result-meta"><strong><Highlight text={item.title} query={searchText}/></strong><small>{typeLabel(item.kind)}{[item.year,item.authors?.join(', ')||item.artists?.join(', '),item.format].filter(Boolean).map(v=>' · '+v)}</small></span><ArrowUpRight size={17}/>
        </motion.button>)}</AnimatePresence>
        {!state.loading&&!items.length&&<p className="morph-search-empty" role="status">Совпадений нет. Попробуй другое название.</p>}
        {state.loading&&<p className="morph-search-progress" role="status">Каталоги дополняют результаты…</p>}
       </div>
      </div>}
     </div>
     <footer className="morph-search-footer" id={id+'-help'}><span><kbd>↑ ↓</kbd> Выбрать · <kbd>↵</kbd> Открыть · <kbd>Esc</kbd> Закрыть</span>{searchText.length>=2&&<button type="button" onClick={browse}>Полный поиск <ArrowUpRight size={13}/></button>}</footer>
    </motion.div>
   </motion.div>}
  </AnimatePresence>
 </motion.div>
 </Dialog.Content>
 </Dialog.Portal>
 </Dialog.Root>;
}
