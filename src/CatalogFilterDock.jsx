import {filterValues} from './catalog-taxonomy.js';
import {RollingNumber} from './LibraryRail.jsx';
import {releaseStatusOptions} from './release-status.js';
import {useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence,LayoutGroup,animate,motion,useReducedMotion} from 'motion/react';
import {ArrowDownUp,Check,ChevronDown,Plus,RotateCcw,Search,SlidersHorizontal,X} from 'lucide-react';
import './catalog-filter-dock.css';
import './catalog-design.css';

// One sticky row of filters above the catalogue. Each filter opens its own
// panel (a sheet on phones); several tags narrow results together.
export const TAG_LIMIT=12;
export const splitTags=filterValues;
const AGES=[['','Любой возраст'],['under18','До 18 лет'],['adult','18+']];
const SPRING={type:'spring',stiffness:520,damping:38,mass:.8};
const same=(a,b)=>a.toLocaleLowerCase()===b.toLocaleLowerCase();
const plural=(n,[one,few,many])=>{const t=n%10,h=n%100;return t===1&&h!==11?one:t>=2&&t<=4&&(h<12||h>14)?few:many;};

function useNarrow(){
 const query='(max-width: 640px)',[narrow,setNarrow]=useState(()=>matchMedia(query).matches);
 useEffect(()=>{const media=matchMedia(query),update=()=>setNarrow(media.matches);media.addEventListener('change',update);return()=>media.removeEventListener('change',update);},[]);
 return narrow;
}

function Panel({anchor,label,onClose,children,footer,compact=false}){
 const ref=useRef(null),phone=useNarrow(),narrow=phone||!!(matchMedia('(max-width:1024px)').matches&&document.documentElement.dataset.catalogMerged),reduced=useReducedMotion(),[place,setPlace]=useState(null);
 useLayoutEffect(()=>{
  if(narrow||!anchor)return;
  let frame=0;
  const measure=()=>{frame=0;const rect=anchor.getBoundingClientRect(),width=ref.current?.offsetWidth||360,start=rect.left+width>innerWidth-12?rect.right-width:rect.left;setPlace({top:rect.bottom+10,left:Math.round(Math.min(Math.max(12,start),innerWidth-width-12)),room:Math.round(innerHeight-rect.bottom-26)});};
  const queue=()=>{if(!frame)frame=requestAnimationFrame(measure);};
  // Too little room under the filter: bring the dock up to its sticky place first.
  let lift=null;const dock=anchor.closest('.catalog-toolbar'),rect=anchor.getBoundingClientRect();
  if(dock&&innerHeight-rect.bottom<360){const top=parseFloat(getComputedStyle(dock).top)||0,gap=dock.getBoundingClientRect().top-top;if(gap>4){const from=scrollY;if(reduced)scrollTo(0,from+gap);else lift=animate(from,from+gap,{duration:.5,ease:[.22,1,.36,1],onUpdate:value=>scrollTo(0,value)});}}
  measure();addEventListener('resize',queue);addEventListener('scroll',queue,true);
  return()=>{lift?.stop();cancelAnimationFrame(frame);removeEventListener('resize',queue);removeEventListener('scroll',queue,true);};
 },[anchor,narrow]);
 useEffect(()=>{
  const key=event=>{if(event.key==='Escape'){event.preventDefault();onClose(true);}};
  const outside=event=>{if(!ref.current?.contains(event.target)&&!anchor?.contains(event.target))onClose(false);};
  document.addEventListener('keydown',key);document.addEventListener('pointerdown',outside);
  return()=>{document.removeEventListener('keydown',key);document.removeEventListener('pointerdown',outside);};
 },[anchor,onClose]);
 useEffect(()=>{const first=ref.current?.querySelector('.fdock-panel-body input:not([disabled]),.fdock-panel-body [aria-selected=true],.fdock-panel-body button:not([disabled])');first?.focus({preventScroll:true});},[]);
 const motionProps=reduced?{initial:{opacity:0},animate:{opacity:1},exit:{opacity:0}}:narrow?{initial:{y:'100%'},animate:{y:0},exit:{y:'100%'}}:{initial:{opacity:0,y:-8,scale:.97},animate:{opacity:1,y:0,scale:1},exit:{opacity:0,y:-6,scale:.98}};
 return createPortal(<>
  {narrow&&<motion.div className="fdock-scrim" aria-hidden="true" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} onClick={()=>onClose(false)}/>}
  <motion.div ref={ref} role="dialog" aria-label={label} className={'fdock-panel'+(narrow?' is-sheet':'')+(compact?' is-compact':'')} style={narrow?undefined:{top:place?.top??-9999,left:place?.left??0,maxHeight:place?Math.max(240,Math.min(500,place.room)):undefined}} {...motionProps} transition={reduced?{duration:.12}:SPRING}
   drag={narrow&&!reduced?'y':false} dragConstraints={{top:0,bottom:0}} dragElastic={{top:0,bottom:.6}} onDragEnd={(_,info)=>{if(info.offset.y>90||info.velocity.y>600)onClose(false);}}>
   {narrow&&<span className="fdock-grip" aria-hidden="true"/>}
   <div className="fdock-panel-head"><h3>{label}</h3><button type="button" className="fdock-close" aria-label={'Закрыть: '+label} onClick={()=>onClose(true)}><X size={16}/></button></div>
   <div className="fdock-panel-body">{children}</div>
   {footer&&<div className="fdock-panel-foot">{footer}</div>}
  </motion.div>
 </>,document.body);
}

function Finder({value,onChange,placeholder,onEnter}){
 return <label className="fdock-find"><Search size={15}/><input value={value} onChange={e=>onChange(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&onEnter){e.preventDefault();onEnter();}}} placeholder={placeholder} aria-label={placeholder} autoComplete="off" spellCheck={false}/></label>;
}

function Options({label,options,selected,onPick,multiple=false,columns}){
 return <div role="listbox" aria-label={label} aria-multiselectable={multiple||undefined} className={'fdock-options'+(columns?' is-grid':'')} style={columns?{'--fdock-columns':columns}:undefined}>
  {options.map(([value,text])=>{const on=selected(value);return <button type="button" role="option" key={value||'none'} aria-selected={on} className={on?'is-on':undefined} onClick={()=>onPick(value)}>
   <span>{text}</span>{on&&<Check size={14}/>}
  </button>;})}
 </div>;
}

function ChoicePanel({options,value,onPick,label,findLabel}){
 const [find,setFind]=useState(''),needle=find.trim().toLocaleLowerCase();
 const shown=options.filter(option=>option.toLocaleLowerCase().includes(needle));
 return <>{options.length>12&&<Finder value={find} onChange={setFind} placeholder={findLabel}/>}
  {shown.length?<Options label={label} options={shown.map(option=>[option,option])} selected={option=>!!value&&same(option,value)} onPick={onPick}/>:<p className="fdock-empty">{options.length?'Ничего не нашлось. Попробуй другое слово.':'Варианты появятся, когда загрузятся карточки.'}</p>}
 </>;
}

function TagPanel({value,options,onChange}){
 const tags=splitTags(value),[find,setFind]=useState(''),needle=find.trim().toLocaleLowerCase();
 const has=tag=>tags.some(old=>same(old,tag)),full=tags.length>=TAG_LIMIT;
 const add=raw=>{const known=options.find(option=>same(option,raw.trim())),tag=(known||raw.trim()).replace(/,/g,' ').trim();if(!tag||has(tag)||full)return;onChange([...tags,tag].join(','));setFind('');};
 const remove=tag=>onChange(tags.filter(old=>old!==tag).join(','));
 const toggle=tag=>has(tag)?remove(tags.find(old=>same(old,tag))):add(tag);
 const matches=options.filter(option=>!has(option)&&option.toLocaleLowerCase().includes(needle)),shown=matches.slice(0,80);
 const custom=find.trim()&&!options.some(option=>same(option,find.trim()))&&!has(find.trim());
 return <>
  <Finder value={find} onChange={setFind} placeholder={full?'Не больше 12 тегов':'Найти или добавить тег'} onEnter={()=>find.trim()&&add(matches.find(option=>same(option,find.trim()))||find)}/>
  {tags.length>0&&<ul className="fdock-chosen" aria-label="Выбранные теги">
   <AnimatePresence initial={false} mode="popLayout">{tags.map(tag=><motion.li key={tag} layout initial={{opacity:0,scale:.7}} animate={{opacity:1,scale:1}} exit={{opacity:0,scale:.7}} transition={SPRING}>
    <span>{tag}</span><button type="button" aria-label={'Убрать тег '+tag} onClick={()=>remove(tag)}><X size={12}/></button>
   </motion.li>)}</AnimatePresence>
  </ul>}
  {custom&&!full&&<button type="button" className="fdock-add" onClick={()=>add(find)}><Plus size={14}/>Добавить «{find.trim()}»</button>}
  {shown.length>0&&<Options multiple label="Теги" options={shown.map(option=>[option,option])} selected={has} onPick={toggle}/>}
  {matches.length>shown.length&&<p className="fdock-empty">Ещё {matches.length-shown.length}. Уточни поиск, чтобы увидеть остальные.</p>}
  {!shown.length&&!custom&&<p className="fdock-empty">{options.length?'Такого тега нет в каталогах.':'Теги появятся, когда загрузятся карточки.'}</p>}
 </>;
}

function SignedPanel({label,positive,negative,options,onChange}){
 const [find,setFind]=useState('');
 const included=splitTags(positive),excluded=splitTags(negative);
 const choose=(value,sign)=>{
  const own=sign==='include'?included:excluded,other=sign==='include'?excluded:included;
  if(!own.includes(value)&&own.length>=64)return;
  const next=own.includes(value)?own.filter(v=>v!==value):[...own,value];
  onChange(sign==='include'?next:other.filter(v=>v!==value),sign==='exclude'?next:other.filter(v=>v!==value));
 };
 const visible=[...new Set([...included,...excluded,...options])].filter(v=>v.toLocaleLowerCase().includes(find.trim().toLocaleLowerCase())).slice(0,120);
 return <><Finder value={find} onChange={setFind} placeholder={'Найти: '+label.toLocaleLowerCase()}/>
  <p className="fdock-signed-note">«+» — оставить тайтлы хотя бы с одним выбранным значением. «−» — скрыть тайтлы с выбранным значением.</p>
  <div className="fdock-signed-list">{visible.map(value=><div key={value} className="fdock-signed-option"><span>{value}</span>
   <button type="button" aria-label={'Включить '+value} aria-pressed={included.includes(value)} onClick={()=>choose(value,'include')}><Plus size={15}/></button>
   <button type="button" aria-label={'Исключить '+value} aria-pressed={excluded.includes(value)} onClick={()=>choose(value,'exclude')}><span aria-hidden="true">−</span></button>
  </div>)}</div>{!visible.length&&<p className="fdock-empty">Подходящих значений нет.</p>}</>;
}

function YearPanel({value,onChange,years}){
 const now=new Date().getFullYear(),list=years?years.map(String):Array.from({length:12},(_,i)=>String(now-i));
 return <>
  {!years&&<label className="fdock-find fdock-year"><span>Год выпуска</span><input type="number" inputMode="numeric" min="1880" max="2100" value={value} onChange={e=>onChange(e.target.value)} placeholder="Например, 2009"/></label>}
  {list.length>0&&<Options label={years?'Годы в коллекции':'Недавние годы'} columns={4} options={list.map(year=>[year,year])} selected={year=>year===value} onPick={year=>onChange(year===value?'':year)}/>}
  {years&&!years.length&&<p className="fdock-empty">У тайтлов коллекции пока нет года выпуска.</p>}
 </>;
}

function SourcePanel({options,value,onChange,error,disabled}){
 const [find,setFind]=useState(''),[adult,setAdult]=useState(false),needle=find.trim().toLocaleLowerCase();
 const shown=options.filter(s=>(!adult||s.adult)&&String(s.name||'').toLocaleLowerCase().includes(needle));
 const meta=s=>[s.language==='all'?'мультиязычный':String(s.language||'').toUpperCase(),s.adult?'18+':''].filter(Boolean).join(' · ');
 if(disabled)return <p className="fdock-empty">Подключи сервер, чтобы выбрать источники.</p>;
 return <>
  <div className="fdock-source-tools"><Finder value={find} onChange={setFind} placeholder="Найти источник"/><button type="button" className="fdock-chip-toggle" aria-pressed={adult} onClick={()=>setAdult(v=>!v)}>18+</button></div>
  {shown.length?<Options multiple label="Источники" options={shown.map(s=>[s.id,<>{s.name} <small className="fdock-option-meta">{meta(s)}</small></>])} selected={id=>value.includes(id)} onPick={id=>onChange(value.includes(id)?value.filter(v=>v!==id):[...value,id])}/>:<p className="fdock-empty">{error||(options.length?'Таких источников нет.':'Список источников загружается.')}</p>}
 </>;
}

function VoicePanel({value,onChange,options,disabled}){
 const needle=value.trim().toLocaleLowerCase(),shown=options.filter(option=>option.toLocaleLowerCase().includes(needle)&&!same(option,value)).slice(0,40);
 return <>
  <label className="fdock-find"><Search size={15}/><input value={value} onChange={e=>onChange(e.target.value)} disabled={disabled} placeholder={disabled?'Подключи сервер, чтобы искать озвучку':'Студия, например AniDub'} aria-label="Студия озвучки" autoComplete="off"/></label>
  {!disabled&&shown.length>0&&<Options label="Студии озвучки" options={shown.map(option=>[option,option])} selected={()=>false} onPick={onChange}/>}
 </>;
}

const OPEN_KEY='mediavault_filters_open_v1';
const MORPH={type:'spring',stiffness:420,damping:36,mass:.9};
// Whether the filter row is unfolded; wide screens start unfolded, the choice is remembered.
function useFiltersOpen(){
 const [open,setOpen]=useState(()=>{try{const saved=localStorage.getItem(OPEN_KEY);if(saved==='1'||saved==='0')return saved==='1';}catch{}return matchMedia('(min-width:1025px)').matches;});
 const change=value=>{setOpen(value);try{localStorage.setItem(OPEN_KEY,value?'1':'0');}catch{}};
 return [open,change];
}

/** Sort control: a pill with the current order; the choices open in the same panel as the filters. */
export function SortMenu({value,options,onChange,label='Сортировка'}){
 const [open,setOpen]=useState(false),anchor=useRef(null),reduced=useReducedMotion();
 const current=options.find(([id])=>id===value)?.[1]||options[0]?.[1];
 const close=useCallback(refocus=>{setOpen(false);if(refocus)anchor.current?.focus({preventScroll:true});},[]);
 return <>
  <button ref={anchor} type="button" className={'sort-pill'+(open?' is-open':'')} aria-haspopup="dialog" aria-expanded={open} aria-label={label+': '+current} onClick={()=>setOpen(old=>!old)}>
   <ArrowDownUp size={15} aria-hidden="true"/>
   <AnimatePresence mode="popLayout" initial={false}><motion.span key={current} className="sort-pill-value" initial={reduced?false:{opacity:0,y:6}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-6}} transition={{duration:.2}}>{current}</motion.span></AnimatePresence>
   <ChevronDown className="fdock-chevron" size={14} aria-hidden="true"/>
  </button>
  <AnimatePresence>{open&&<Panel key="sort" compact anchor={anchor.current} label={label} onClose={close}>
   <Options label={label} options={options} selected={id=>id===value} onPick={id=>{onChange(id);close(true);}}/>
  </Panel>}</AnimatePresence>
 </>;
}

// «Рельс»: one «Фильтры» button next to the search; applied filters stay under
// it as chips; every facet lives in one drawer (a bottom sheet on phones).
function FilterDrawer({sentinel,stuck,search,items,active,bodyFor,noteOf,onReset,count,title,morphId}){
 const [open,setOpen]=useState(false),[focus,setFocus]=useState(null),button=useRef(null),phone=useNarrow(),reduced=useReducedMotion();
 const set=items.filter(item=>item.clear&&item.value);
 const show=key=>{setFocus(key||null);setOpen(true);};
 const close=useCallback(()=>{setOpen(false);requestAnimationFrame(()=>button.current?.focus({preventScroll:true}));},[]);
 useEffect(()=>{
  if(!open)return;
  const key=event=>{if(event.key==='Escape'){event.preventDefault();close();}};
  document.addEventListener('keydown',key);
  const frame=requestAnimationFrame(()=>{const target=focus&&document.getElementById(morphId+'-facet-'+focus);if(target)target.scrollIntoView({block:'start',behavior:reduced?'instant':'smooth'});});
  return()=>{document.removeEventListener('keydown',key);cancelAnimationFrame(frame);};
 },[open,focus,close,morphId,reduced]);
 const motionProps=reduced?{initial:{opacity:0},animate:{opacity:1},exit:{opacity:0}}:phone?{initial:{y:'100%'},animate:{y:0},exit:{y:'100%'}}:{initial:{x:'104%'},animate:{x:0},exit:{x:'104%'}};
 return <>
  <span ref={sentinel} className="fdock-sentinel" aria-hidden="true"/>
  <div className={'catalog-toolbar is-rail'+(stuck?' is-stuck':'')}>
   <div className="fdock-search"><div className="fdock-search-inner">{search}</div></div>
   <motion.button ref={button} type="button" className={'rail-filters-button'+(active?' is-set':'')} aria-haspopup="dialog" aria-expanded={open} aria-label={'Фильтры'+(active?', выбрано '+active:'')} onClick={()=>show(null)} whileTap={reduced?undefined:{scale:.96}}>
    <SlidersHorizontal size={17} aria-hidden="true"/><span>Фильтры</span>
    <AnimatePresence initial={false}>{active>0&&<motion.span key="count" className="fdock-count" initial={{scale:0}} animate={{scale:1}} exit={{scale:0}} transition={SPRING}>{active}</motion.span>}</AnimatePresence>
   </motion.button>
  </div>
  <motion.div layout={!reduced} className="rail-chips" aria-label="Выбранные фильтры">
   <AnimatePresence initial={false} mode="popLayout">
    {set.map(item=><motion.span layout={!reduced} key={item.key} className="rail-chip" initial={{opacity:0,scale:.8}} animate={{opacity:1,scale:1}} exit={{opacity:0,scale:.8}} transition={SPRING}>
     <button type="button" className="rail-chip-edit" onClick={()=>show(item.key)}><small>{item.label}</small><span>{item.value}</span></button>
     <button type="button" className="rail-chip-clear" aria-label={'Убрать фильтр '+item.label} onClick={item.clear}><X size={12}/></button>
    </motion.span>)}
    {set.length>1&&<motion.button layout={!reduced} key="reset" type="button" className="rail-chips-reset" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} onClick={onReset}>Сбросить всё</motion.button>}
   </AnimatePresence>
  </motion.div>
  {createPortal(<AnimatePresence>{open&&<>
   <motion.div key="scrim" className="rail-drawer-scrim" aria-hidden="true" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} onClick={close}/>
   <motion.aside key="drawer" role="dialog" aria-modal="true" aria-label="Фильтры" className={'rail-drawer'+(phone?' is-sheet':'')} {...motionProps}
    transition={reduced?{duration:.15}:{type:'spring',stiffness:380,damping:40}}
    drag={phone&&!reduced?'y':false} dragConstraints={{top:0,bottom:0}} dragElastic={{top:0,bottom:.5}} onDragEnd={(_,info)=>{if(info.offset.y>100||info.velocity.y>600)close();}}>
    {phone&&<span className="fdock-grip" aria-hidden="true"/>}
    <div className="rail-drawer-head"><div><span className="rail-drawer-kicker">{title}</span><h2>Фильтры</h2></div><button type="button" className="fdock-close" aria-label="Закрыть фильтры" onClick={close}><X size={18}/></button></div>
    <div className="rail-drawer-body">{items.map((item,index)=><motion.section key={item.key} id={morphId+'-facet-'+item.key} role="group" aria-label={item.label} className={'rail-facet'+(focus===item.key?' is-focus':'')}
     initial={reduced?false:{opacity:0,x:24}} animate={{opacity:1,x:0,transition:{...SPRING,delay:.08+index*.035}}}>
     <h3>{item.label}<AnimatePresence initial={false}>{item.clear&&item.value&&!item.quiet&&<motion.button key="clear" type="button" className="rail-facet-clear" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} onClick={item.clear}>Очистить</motion.button>}</AnimatePresence></h3>
     <div className="rail-facet-body">{bodyFor(item.key,()=>{})}</div>
     {noteOf(item.key)&&<p className="rail-facet-note">{noteOf(item.key)}</p>}
    </motion.section>)}</div>
    <div className="rail-drawer-foot">
     <button type="button" className="rail-drawer-reset" disabled={!active} onClick={onReset}><RotateCcw size={14}/>Сбросить</button>
     <motion.button type="button" className="rail-drawer-done" onClick={close} whileTap={reduced?undefined:{scale:.97}}>Показать{count!=null?<> <RollingNumber value={count}/></>:''}</motion.button>
    </div>
   </motion.aside>
  </>}</AnimatePresence>,document.body)}
 </>;
}

const InlineToolbar=({children})=>children;
const libraryStatusOptions=[['available','Уже доступны'],...releaseStatusOptions];
export default function CatalogFilterDock({mergeNavigation=false,search,kind,filters,defaultStatus='',onFilter,onReset,fields=['genre','year','status','tag','format','age','voice','language'],years,genres=[],tags=[],formats=[],voice='',onVoice,voiceOptions=[],voiceDisabled=false,voiceExact=false,voiceTitle='Озвучка',voiceNote,language,sources,morphId='filters',variant='dock',resultCount,title='Каталог'}){
 const [panel,setPanel]=useState(null),anchors=useRef({}),sentinel=useRef(null),[stuck,setStuck]=useState(false),reduced=useReducedMotion(),[open,setOpen]=useFiltersOpen(),toggle=useRef(null),fold=useRef(null);
 // The bar stays in the page as a sticky glass strip under the navbar capsule;
 // the navbar keeps its sections and labels.
 const ToolbarHost=InlineToolbar;
 const chosenTags=splitTags(filters.tag);
 const statusOptions=mergeNavigation?libraryStatusOptions:releaseStatusOptions;
 useEffect(()=>{const merged=event=>{if(event.detail.mobile){setPanel(null);setOpen(false);}};addEventListener('mediavault:catalog-merged',merged);return()=>removeEventListener('mediavault:catalog-merged',merged);},[]);
 useEffect(()=>{const node=sentinel.current;if(!node)return;const observer=new IntersectionObserver(([entry])=>setStuck(!entry.isIntersecting&&entry.boundingClientRect.top<=(entry.rootBounds?.top??96)),{rootMargin:'-96px 0px 0px 0px'});observer.observe(node);return()=>observer.disconnect();},[]);
 useEffect(()=>setPanel(null),[kind]);
 const close=useRef(null);close.current=refocus=>{const key=panel;setPanel(null);if(refocus&&key)anchors.current[key]?.focus({preventScroll:true});};
 const shut=useCallback(refocus=>close.current(refocus),[]);
 const switchOpen=value=>{setPanel(null);setOpen(value);requestAnimationFrame(()=>(value?fold:toggle).current?.focus({preventScroll:true}));};
 const age=AGES.find(([id])=>id===filters.age)?.[1],use=key=>fields.includes(key);
 const items=[
  use('genre')&&{key:'genre',label:mergeNavigation?'Жанры':'Жанр',value:[splitTags(filters.genre).join(', '),splitTags(filters.excludeGenre).length?'− '+splitTags(filters.excludeGenre).join(', '):''].filter(Boolean).join(' · '),clear:()=>{onFilter('genre','');onFilter('excludeGenre','');}},
  use('year')&&{key:'year',label:'Год',value:filters.year,clear:()=>onFilter('year','')},
  use('status')&&['anime','manga','ranobe','movie','tv'].includes(kind)&&{key:'status',label:'Статус',
   value:filters.status===defaultStatus?'':statusOptions.find(([id])=>id===(filters.status||''))?.[1],
   clear:()=>onFilter('status',undefined)},
  use('tag')&&kind!=='book'&&{key:'tag',label:'Теги',value:[splitTags(filters.tag).join(', '),splitTags(filters.excludeTag).length?'− '+splitTags(filters.excludeTag).join(', '):''].filter(Boolean).join(' · '),clear:()=>{onFilter('tag','');onFilter('excludeTag','');}},
  use('format')&&formats.length>0&&{key:'format',label:'Формат',value:filters.format,clear:()=>onFilter('format','')},
  kind==='manga'&&{key:'readingMode',label:'Подача',value:filters.readingMode==='webtoon'?'Вебтун':filters.readingMode==='paged'?'Страницы':'',clear:()=>onFilter('readingMode','')},
  use('age')&&{key:'age',label:'Возраст',value:filters.age?age:'',clear:()=>onFilter('age','')},
  use('voice')&&(kind==='anime'||voiceExact)&&{key:'voice',label:voiceTitle,value:voice,clear:()=>onVoice('')},
  sources&&{key:'sources',label:'Источники',value:sources.value.length?(sources.options.find(s=>s.id===sources.value[0])?.name||sources.value[0])+(sources.value.length>1?' +'+(sources.value.length-1):''):'',clear:()=>sources.onChange([])},
  use('language')&&language&&{key:'language',label:language.label,value:language.options.find(([id])=>id===language.value)?.[1],quiet:language.value===language.options[0][0]},
 ].filter(Boolean);
 const active=items.filter(item=>item.clear&&item.value).length+Math.max(0,chosenTags.length-1);
 const current=items.find(item=>item.key===panel);
 const noteOf=key=>key==='tag'?'Теги объединяются через ИЛИ; с жанрами — через И. Исключения имеют приоритет.':key==='voice'?voiceNote:key==='genre'&&kind==='manga'?'Жанры ищутся прямо в каталогах источников.':key==='language'?language?.note:key==='sources'?(sources?.value.length?'Ищем только в выбранных источниках.':'Ничего не выбрано: ищем во всех подключённых.'):'';
 const note=noteOf(panel);
 // One facet's controls: in a floating panel or a section of the filter drawer.
 const bodyFor=(key,done)=><>
  {key==='genre'&&mergeNavigation&&<SignedPanel label="Жанры" options={genres} positive={filters.genre} negative={filters.excludeGenre} onChange={(yes,no)=>{onFilter('genre',yes);onFilter('excludeGenre',no);}}/>}
  {key==='genre'&&!mergeNavigation&&<ChoicePanel label="Жанры" findLabel="Найти жанр" options={genres} value={filters.genre} onPick={value=>{onFilter('genre',value);done(true);}}/>}
  {key==='tag'&&!mergeNavigation&&<TagPanel value={filters.tag} options={tags} onChange={value=>onFilter('tag',value)}/>}
  {key==='year'&&<YearPanel years={years} value={filters.year} onChange={value=>{onFilter('year',value);if(years)done(true);}}/>}
  {key==='status'&&<Options label="Статус выпуска" options={statusOptions} selected={id=>id===(filters.status||'')} onPick={id=>{onFilter('status',id);done(true);}}/>}
  {key==='tag'&&mergeNavigation&&<SignedPanel label="Теги" options={tags} positive={filters.tag} negative={filters.excludeTag} onChange={(yes,no)=>{onFilter('tag',yes);onFilter('excludeTag',no);}}/>}
  {key==='readingMode'&&<Options label="Подача" options={[["","Любая"],["webtoon","Вебтун"],["paged","Страницы"]]} selected={value=>value===(filters.readingMode||'')} onPick={value=>{onFilter('readingMode',value);done(true);}}/>}
  {key==='format'&&<ChoicePanel label="Форматы" findLabel="Найти формат" options={formats} value={filters.format} onPick={value=>{onFilter('format',same(value,filters.format||'')?'':value);done(true);}}/>}
  {key==='age'&&<Options label="Возраст" options={AGES} selected={id=>id===(filters.age||'')} onPick={id=>{onFilter('age',id);done(true);}}/>}
  {key==='voice'&&(voiceExact?<ChoicePanel label={voiceTitle} findLabel={voiceTitle==='Перевод'?'Найти перевод':'Найти озвучку'} options={voiceOptions} value={voice} onPick={value=>{onVoice(same(value,voice||'')?'':value);done(true);}}/>:<VoicePanel value={voice} onChange={onVoice} options={voiceOptions} disabled={voiceDisabled}/>)}
  {key==='sources'&&<SourcePanel {...sources}/>}
  {key==='language'&&<Options label={language.label} options={language.options} selected={id=>id===language.value} onPick={id=>{language.onChange(id);done(true);}}/>}
 </>;
 if(variant==='drawer')return <FilterDrawer sentinel={sentinel} stuck={stuck} search={search} items={items} active={active} bodyFor={bodyFor} noteOf={noteOf} onReset={()=>{setPanel(null);onReset();}} count={resultCount} title={title} morphId={morphId}/>;
 const morph=reduced?{duration:0}:MORPH,fade=reduced?{}:{initial:{opacity:0},animate:{opacity:1,transition:{delay:.12,duration:.2}}};
 return <>
  <span ref={sentinel} className="fdock-sentinel" aria-hidden="true"/>
  <ToolbarHost stuck={stuck}><div className={'catalog-toolbar'+(stuck?' is-stuck':'')+(open?' is-open':' is-folded')}>
  <LayoutGroup id={morphId}>
  <motion.div layout={!reduced} transition={morph} className="fdock-search" style={{borderRadius:14}}><motion.div layout={!reduced} transition={morph} className="fdock-search-inner">{search}</motion.div></motion.div>
  {open?<motion.div key="dock" layoutId={morphId+'-shell'} transition={morph} style={{borderRadius:16}} className="fdock" role="toolbar" aria-label="Фильтры каталога">
   <motion.div layout="position" className="fdock-row" {...fade}>
    {items.map(item=><motion.div layout={!reduced} transition={SPRING} key={item.key} className={'fdock-item'+(item.value&&!item.quiet?' is-set':'')+(panel===item.key?' is-open':'')}>
     <button type="button" ref={node=>{anchors.current[item.key]=node;}} className="fdock-pill" aria-haspopup="dialog" aria-expanded={panel===item.key} onClick={()=>setPanel(old=>old===item.key?null:item.key)}>
      <span className="fdock-label">{item.label}</span>
      {item.value&&<span className="fdock-value">{item.value}</span>}
      <ChevronDown className="fdock-chevron" size={14} aria-hidden="true"/>
     </button>
     <AnimatePresence initial={false}>{item.clear&&item.value&&<motion.button type="button" key="clear" className="fdock-clear" aria-label={'Убрать фильтр '+item.label} onClick={item.clear}
      initial={{opacity:0,width:0}} animate={{opacity:1,width:30}} exit={{opacity:0,width:0}} transition={SPRING}><X size={13}/></motion.button>}</AnimatePresence>
    </motion.div>)}
   </motion.div>
   <AnimatePresence initial={false}>{active>0&&<motion.button type="button" key="reset" className="fdock-reset" onClick={()=>{setPanel(null);onReset();}} aria-label={'Сбросить фильтры каталога: '+active}
    initial={{opacity:0,scale:.85}} animate={{opacity:1,scale:1}} exit={{opacity:0,scale:.85}} transition={SPRING}>
    <span className="fdock-count">{active}</span><RotateCcw size={14}/><span className="fdock-reset-text">Сбросить</span>
   </motion.button>}</AnimatePresence>
   <motion.button ref={fold} type="button" className="fdock-fold" aria-label="Свернуть фильтры" aria-expanded="true" title="Свернуть фильтры" onClick={()=>switchOpen(false)}
    {...(reduced?{}:{initial:{rotate:-90,opacity:0},animate:{rotate:0,opacity:1,transition:{...SPRING,delay:.1}}})}><X size={16}/></motion.button>
  </motion.div>
  :<motion.button key="toggle" ref={toggle} type="button" layoutId={morphId+'-shell'} transition={morph} style={{borderRadius:14}} className={'fdock-toggle'+(active?' is-set':'')} aria-expanded="false" aria-label={'Фильтры'+(active?', выбрано '+active:'')} onClick={()=>switchOpen(true)}>
   <motion.span layout="position" className="fdock-toggle-face" {...fade}><SlidersHorizontal size={16} aria-hidden="true"/><span className="fdock-toggle-text">Фильтры</span>{active>0&&<span className="fdock-count">{active}</span>}</motion.span>
  </motion.button>}
  </LayoutGroup>
  </div></ToolbarHost>
  <AnimatePresence>{current&&<Panel key={current.key} anchor={anchors.current[current.key]} label={current.label} onClose={shut}
   footer={note||current.key==='tag'?<>{note&&<p>{note}</p>}{current.key==='tag'&&<button type="button" className="fdock-done" onClick={()=>shut(true)}>Готово{chosenTags.length?' · '+chosenTags.length+' '+plural(chosenTags.length,['тег','тега','тегов']):''}</button>}{current.key==='sources'&&<button type="button" className="fdock-done" onClick={()=>shut(true)}>Готово{sources.value.length?' · '+sources.value.length:''}</button>}</>:null}>
   {bodyFor(current.key,shut)}
  </Panel>}</AnimatePresence>
 </>;
}
