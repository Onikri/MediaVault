import {useCallback,useEffect,useId,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ArrowUpRight,Clock,ImageUp,LoaderCircle,Search,X} from 'lucide-react';
import {useGlobalSearch,SEARCH_KINDS} from '../../use-global-search.js';
import {genreLabels,matchesFilters} from '../../catalog.js';
import UiSelect from '../../UiSelect.jsx';
import {Poster} from '../../ImportParts.jsx';
import './morph-search.css';
import '../../glass-popover.css';
import {GLASS_ENTER,GLASS_HIDDEN,GLASS_VISIBLE} from '../../glass-motion.js';

/* MorphingSearchChips port: the original 56px glass bar, centered panel,
   spring-grown glass surface, animated chips, recents and list cursor.
   Live MediaVault catalog results remain available below the suggestions. */
const SWAP={type:'spring',stiffness:420,damping:34,mass:.7} as const;
const KEY='mediavault_search_recents_v1';
const typeLabel=(kind:string)=>Object.fromEntries(SEARCH_KINDS)[kind]||'Сериал';
const same=(a:string,b:string)=>a.trim().toLocaleLowerCase()===b.trim().toLocaleLowerCase();
const GENRES=[...new Set(Object.values(genreLabels))].sort((a,b)=>a.localeCompare(b,'ru'));
const YEARS=Array.from({length:new Date().getFullYear()+2-1960},(_,i)=>String(new Date().getFullYear()+1-i));
const MAX_WIDTH=680,MIN_WIDTH=300;
// Coordinates are local to the navbar. Scrolling moves the same surface with
// its button; a viewport portal would chase the animated header one frame late.
function coordinates(){
 const target=document.querySelector('.blossom-navbar .header-center-search .header-search')?.getBoundingClientRect();
 const innerElement=document.querySelector<HTMLElement>('.blossom-navbar .header-inner'),inner=innerElement?.getBoundingClientRect();
 const total=inner?.width??window.innerWidth;
 let width:number;
 if(window.innerWidth<=640)width=total-20;
 else{
  // The field grows into whatever the brand/nav and the action icons leave free,
  // so the search (and its filters) use the wide header instead of a fixed 340px.
  const brand=innerElement?.querySelector<HTMLElement>('.header-brand-area')?.scrollWidth??0,actions=innerElement?.querySelector<HTMLElement>('.header-actions')?.scrollWidth??0;
  width=Math.max(MIN_WIDTH,Math.min(MAX_WIDTH,total-2*Math.max(brand,actions)-48));
 }
 const height=38,left=(total-width)/2;
 const top=inner?(inner.height-height)/2:(target?.top??18);
 return {width,left,top,height,anchorX:target?target.left+target.width/2-(inner?.left??0)-left-width/2:0,seedWidth:target?.width??38};
}
function Highlight({text,query}:{text:string,query:string}){const at=query?text.toLocaleLowerCase().indexOf(query.toLocaleLowerCase()):-1;return at<0?<>{text}</>:<>{text.slice(0,at)}<strong>{text.slice(at,at+query.length)}</strong>{text.slice(at+query.length)}</>;}
export function SearchDialog({service,onClose,onChoose,onBrowse}:{service:any,onClose:()=>void,onChoose:(item:any)=>void,onBrowse:(query:string,kind:string,filters?:{year:string,genre:string})=>void}){
 const reduce=useReducedMotion(),[geometry,setGeometry]=useState(coordinates),id=useId();
 // Phones and tablets search from the dock: the sheet grows out of the round
 // search button at the bottom and folds back into it.
 const [sheet]=useState(()=>{const dock=document.documentElement.dataset.searchFrom==='dock';delete document.documentElement.dataset.searchFrom;return dock&&typeof matchMedia==='function'&&matchMedia('(max-width:1000px)').matches;}),[shown,setShown]=useState(false);
 useEffect(()=>{if(!sheet)return;const frame=requestAnimationFrame(()=>requestAnimationFrame(()=>setShown(true)));return()=>cancelAnimationFrame(frame);},[sheet]);
 const [query,setQuery]=useState(''),[kind,setKind]=useState('all'),[year,setYear]=useState(''),[genre,setGenre]=useState(''),[composing,setComposing]=useState(false),[closing,setClosing]=useState(false);
 const [chips,setChips]=useState<string[]>([]),[marked,setMarked]=useState<string|null>(null),[activeId,setActiveId]=useState<string|null>(null),[rowCursor,setRowCursor]=useState(0),[panelFloor,setPanelFloor]=useState(0);
 const [recents,setRecents]=useState<string[]>(()=>{try{const saved=JSON.parse(localStorage.getItem(KEY)||'[]');return Array.isArray(saved)?saved.filter((v):v is string=>typeof v==='string').slice(0,5):[];}catch{return[];}});
 const input=useRef<HTMLInputElement>(null),finished=useRef(false),panelRows=useRef<HTMLDivElement>(null);
 const searchText=query.trim()||chips.at(-1)||'';
 const state=useGlobalSearch(searchText,kind,service,composing),filtered=useMemo(()=>year||genre?state.items.filter((item:any)=>matchesFilters({genres:[],...item},{year,genre})):state.items,[state.items,year,genre]),items=filtered.slice(0,24),index=Math.max(0,items.findIndex((x:any)=>x.id===activeId));
 const suggestions=useMemo(()=>!query.trim()?recents.map(label=>({id:'recent:'+label,label,kind:'recent'})): [
  {id:'query:'+query.trim(),label:query.trim(),kind:'query'},
  ...recents.filter(v=>v.toLowerCase().includes(query.trim().toLowerCase())&&!same(v,query)).slice(0,5).map(label=>({id:'recent:'+label,label,kind:'recent'}))
 ],[recents,query]);
 const persist=useCallback((next:string[])=>{setRecents(next);try{localStorage.setItem(KEY,JSON.stringify(next));}catch{}},[]);
 const remember=useCallback((term:string)=>{const value=term.trim();if(value)persist([value,...recents.filter(v=>!same(value,v))].slice(0,5));},[recents,persist]);
 const close=useCallback(()=>{if(finished.current||closing)return;if(reduce){finished.current=true;onClose();}else setClosing(true);},[closing,onClose,reduce]);
 const choose=(item:any)=>{remember(searchText||item.title);onChoose(item);};
 const browse=()=>{if(searchText)remember(searchText);onBrowse(searchText,kind==='all'&&!searchText?'anime':kind,{year,genre});};
 const addChip=(text:string)=>{const v=text.trim();if(!v)return;setChips(old=>old.some(c=>same(c,v))?old:[...old,v]);setQuery('');setMarked(null);remember(v);setRowCursor(0);input.current?.focus();};
 const removeChip=(text:string)=>{setChips(old=>old.filter(c=>c!==text));setMarked(null);input.current?.focus();};
 const forget=(text?:string)=>persist(text?recents.filter(v=>v!==text):[]);
 useLayoutEffect(()=>{
  const header=document.querySelector('.blossom-navbar');
  header?.classList.add('is-search-open');
  dispatchEvent(new Event('mediavault:search-open'));
  const update=()=>setGeometry(previous=>{const next=coordinates();return Object.keys(next).every(key=>previous[key as keyof typeof previous]===next[key as keyof typeof next])?previous:next;});
  update();
  const observer=new ResizeObserver(update);
  const inner=header?.querySelector('.header-inner');if(inner)observer.observe(inner);
  const slot=header?.querySelector('.header-center-search');if(slot)observer.observe(slot);
  window.addEventListener('resize',update);
  input.current?.focus({preventScroll:true});
  return()=>{observer.disconnect();window.removeEventListener('resize',update);(header?.querySelector('.header-inner') as HTMLElement|null)?.style.removeProperty('--search-slot');header?.classList.remove('is-search-open');dispatchEvent(new Event('mediavault:search-close'));};
 },[]);
 useLayoutEffect(()=>{const inner=document.querySelector<HTMLElement>('.blossom-navbar .header-inner');if(!inner||window.innerWidth<=640)return;inner.style.setProperty('--search-slot',(closing?38:geometry.width)+'px');},[geometry.width,closing]);
 useEffect(()=>{if(!closing)return;const t=setTimeout(()=>{if(!finished.current){finished.current=true;onClose();}},400);return()=>clearTimeout(t);},[closing,onClose]);
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
 return createPortal(<motion.div role="dialog" aria-label="Поиск в библиотеке" aria-modal="false" aria-describedby={id+'-help'} className={'blossom-search-dialog morph-search-dialog'+(closing?' is-closing':'')+(sheet?' is-sheet':'')+(sheet&&shown&&!closing?' is-shown':'')} style={sheet?undefined:{position:document.querySelector('.blossom-navbar .header-inner')?'absolute':'fixed',top:geometry.top,left:geometry.left,width:geometry.width}} initial={false}>
  <motion.div className="morph-search-bar" onPointerDown={focusField}
   initial={reduce||sheet?false:{width:geometry.seedWidth,height:38,x:geometry.anchorX}}
   animate={sheet?{width:'100%',height:46,borderRadius:23,x:0}:{width:closing?geometry.seedWidth:geometry.width,height:38,borderRadius:19,x:closing?geometry.anchorX:0}}
   transition={{duration:reduce?0:.32,ease:[.22,1,.36,1]}} onAnimationComplete={()=>{if(closing&&!finished.current){finished.current=true;onClose();}}}>
   <motion.span className="morph-search-icon" aria-hidden="true" initial={reduce?false:{left:10}} animate={{left:closing?10:16}} transition={{duration:reduce?0:.32,ease:[.22,1,.36,1]}}><Search size={18}/></motion.span>
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
   {(query||chips.length)>0&&<button className="morph-search-clear" type="button" aria-label="Очистить запрос" onClick={()=>{setQuery('');setChips([]);input.current?.focus();}}><X size={17}/></button>}
   <button className="morph-search-close" type="button" aria-label="Закрыть поиск" onClick={close}><X size={18}/></button>
  </motion.div>
  <AnimatePresence>
   {!closing&&<motion.div key="panel" className="morph-search-panel" initial={reduce?false:GLASS_HIDDEN} animate={GLASS_VISIBLE} exit={GLASS_HIDDEN} transition={reduce?{duration:0}:GLASS_ENTER}>
    <motion.div className="morph-search-panel-content" initial={reduce?false:{opacity:0,y:-6}} animate={{opacity:1,y:0}} exit={{opacity:0}} transition={{duration:reduce?0:.18,delay:reduce?0:.12}}>
     <div className="morph-search-panel-heading"><span>{query.trim()?'Подсказки':'Недавние'}</span>{!query.trim()&&recents.length>0&&<button type="button" onClick={()=>forget()}>Очистить</button>}</div>
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
      <div className="morph-search-refine">
       <div className="morph-search-filters" role="group" aria-label="Где искать">{SEARCH_KINDS.map(([k,label])=><button key={k} className="morph-search-chip" type="button" aria-pressed={kind===k} onClick={()=>{setKind(k);setActiveId(null);}}>{kind===k&&<motion.span className="morph-search-chip-active" layoutId="morph-search-active-category" transition={SWAP}/>}<span>{label}</span></button>)}</div>
       <div className="morph-search-facets" role="group" aria-label="Фильтры поиска">
        <label><span>Год</span><UiSelect aria-label="Год выхода" value={year} onChange={(e:any)=>{setYear(e.target.value);setActiveId(null);}}><option value="">Любой</option>{YEARS.map(v=><option key={v} value={v}>{v}</option>)}</UiSelect></label>
        <label><span>Жанр</span><UiSelect aria-label="Жанр" value={genre} onChange={(e:any)=>{setGenre(e.target.value);setActiveId(null);}}><option value="">Любой</option>{GENRES.map(v=><option key={v} value={v}>{v}</option>)}</UiSelect></label>
        {(year||genre)&&<button type="button" className="morph-search-reset" onClick={()=>{setYear('');setGenre('');}}>Сбросить</button>}
       </div>
      </div>
      {searchText.length>=2&&<div className="morph-search-results">
       <div className="morph-search-panel-heading"><span>Результаты поиска</span>{items.length>0&&<span>{items.length}{state.loading?' +':''}</span>}</div>
       <div id="blossomSearchHits" className="morph-search-results-list" role="listbox" aria-label="Результаты поиска" aria-busy={state.loading}>
        <AnimatePresence initial={false}>{items.map((item:any,i:number)=><motion.button key={item.id} id={id+'-hit-'+i} role="option" aria-selected={index===i} type="button" className={'morph-search-result'+(index===i?' is-active':'')} onMouseEnter={()=>setActiveId(item.id)} onClick={()=>choose(item)} initial={reduce?false:{opacity:0,y:6}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-4}} transition={{duration:reduce?0:.18,delay:reduce?0:Math.min(i,5)*.025}}>
         <span className="morph-search-poster"><Poster item={item}/></span><span className="morph-search-result-meta"><strong translate="no"><Highlight text={item.title} query={searchText}/></strong><small>{typeLabel(item.kind)}{[item.year,item.authors?.join(', ')||item.artists?.join(', '),item.format].filter(Boolean).map(v=>' · '+v)}</small></span><ArrowUpRight size={17}/>
        </motion.button>)}</AnimatePresence>
        {!state.loading&&!items.length&&<p className="morph-search-empty" role="status">{state.items.length&&(year||genre)?'С такими фильтрами ничего нет. Сбрось год или жанр.':'Совпадений нет. Попробуй другое название.'}</p>}
        {state.loading&&<p className="morph-search-progress" role="status">Каталоги дополняют результаты…</p>}
       </div>
      </div>}
     </div>
     <footer className="morph-search-footer" id={id+'-help'}><button type="button" className="morph-search-frame" title="Найти аниме, серию и момент по скриншоту. Можно и перетащить картинку на страницу или вставить Ctrl+V." onClick={()=>{dispatchEvent(new Event('mediavault:scene-pick'));close();}}><ImageUp size={14}/>Найти по кадру</button>{(searchText.length>=2||year||genre)&&<button type="button" onClick={browse}>{searchText.length>=2?'Полный поиск':'Открыть в библиотеке'} <ArrowUpRight size={13}/></button>}</footer>
    </motion.div>
   </motion.div>}
  </AnimatePresence>
 </motion.div>,(!sheet&&document.querySelector('.blossom-navbar .header-inner'))||document.body);
}
