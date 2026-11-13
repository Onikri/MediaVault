import {useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence,LayoutGroup,animate,motion,useReducedMotion} from 'motion/react';
import {ArrowDownUp,Check,ChevronDown,Plus,RotateCcw,Search,SlidersHorizontal,X} from 'lucide-react';
import './catalog-filter-dock.css';

// One sticky row of filters above the catalogue. Each filter opens its own
// panel (a sheet on phones); several tags narrow results together.
export const TAG_LIMIT=12;
export const splitTags=value=>String(value||'').split(',').map(tag=>tag.trim()).filter(Boolean);
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
 const ref=useRef(null),narrow=useNarrow(),reduced=useReducedMotion(),[place,setPlace]=useState(null);
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

function YearPanel({value,onChange,years}){
 const now=new Date().getFullYear(),list=years?years.map(String):Array.from({length:12},(_,i)=>String(now-i));
 return <>
  {!years&&<label className="fdock-find fdock-year"><span>Год выпуска</span><input type="number" inputMode="numeric" min="1880" max="2100" value={value} onChange={e=>onChange(e.target.value)} placeholder="Например, 2009"/></label>}
  {list.length>0&&<Options label={years?'Годы в коллекции':'Недавние годы'} columns={4} options={list.map(year=>[year,year])} selected={year=>year===value} onPick={year=>onChange(year===value?'':year)}/>}
  {years&&!years.length&&<p className="fdock-empty">У тайтлов коллекции пока нет года выпуска.</p>}
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
 const [open,setOpen]=useState(()=>{try{const saved=localStorage.getItem(OPEN_KEY);if(saved==='1'||saved==='0')return saved==='1';}catch{}return matchMedia('(min-width: 1181px)').matches;});
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

export default function CatalogFilterDock({search,kind,filters,onFilter,onReset,fields=['genre','year','tag','format','age','voice','language'],years,genres=[],tags=[],formats=[],voice='',onVoice,voiceOptions=[],voiceDisabled=false,voiceExact=false,voiceNote,language,morphId='filters'}){
 const [panel,setPanel]=useState(null),anchors=useRef({}),sentinel=useRef(null),[stuck,setStuck]=useState(false),reduced=useReducedMotion(),[open,setOpen]=useFiltersOpen(),toggle=useRef(null),fold=useRef(null);
 const chosenTags=splitTags(filters.tag);
 useEffect(()=>{const node=sentinel.current;if(!node)return;const observer=new IntersectionObserver(([entry])=>setStuck(!entry.isIntersecting&&entry.boundingClientRect.top<0),{rootMargin:'-96px 0px 0px 0px'});observer.observe(node);return()=>observer.disconnect();},[]);
 useEffect(()=>setPanel(null),[kind]);
 const close=useRef(null);close.current=refocus=>{const key=panel;setPanel(null);if(refocus&&key)anchors.current[key]?.focus({preventScroll:true});};
 const shut=useCallback(refocus=>close.current(refocus),[]);
 const switchOpen=value=>{setPanel(null);setOpen(value);requestAnimationFrame(()=>(value?fold:toggle).current?.focus({preventScroll:true}));};
 const age=AGES.find(([id])=>id===filters.age)?.[1],use=key=>fields.includes(key);
 const items=[
  use('genre')&&{key:'genre',label:'Жанр',value:filters.genre,clear:()=>onFilter('genre','')},
  use('year')&&{key:'year',label:'Год',value:filters.year,clear:()=>onFilter('year','')},
  use('tag')&&{key:'tag',label:'Теги',value:chosenTags.length?chosenTags[0]+(chosenTags.length>1?' +'+(chosenTags.length-1):''):'',clear:()=>onFilter('tag','')},
  use('format')&&{key:'format',label:'Формат',value:filters.format,clear:()=>onFilter('format','')},
  use('age')&&{key:'age',label:'Возраст',value:filters.age?age:'',clear:()=>onFilter('age','')},
  use('voice')&&(kind==='anime'||voiceExact)&&{key:'voice',label:'Озвучка',value:voice,clear:()=>onVoice('')},
  use('language')&&language&&{key:'language',label:language.label,value:language.options.find(([id])=>id===language.value)?.[1],quiet:language.value===language.options[0][0]},
 ].filter(Boolean);
 const active=items.filter(item=>item.clear&&item.value).length+Math.max(0,chosenTags.length-1);
 const current=items.find(item=>item.key===panel);
 const note=panel==='tag'?(chosenTags.length>1?'Показываем тайтлы, у которых есть все выбранные теги.':'Можно выбрать до 12 тегов. Подойдут тайтлы, где есть все сразу.'):panel==='voice'?voiceNote:panel==='genre'&&kind==='manga'?'Жанры ищутся прямо в каталогах источников.':panel==='language'?language?.note:'';
 const morph=reduced?{duration:0}:MORPH,fade=reduced?{}:{initial:{opacity:0},animate:{opacity:1,transition:{delay:.12,duration:.2}}};
 return <>
  <span ref={sentinel} className="fdock-sentinel" aria-hidden="true"/>
  <div className={'catalog-toolbar'+(stuck?' is-stuck':'')+(open?' is-open':' is-folded')}>
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
  </div>
  <AnimatePresence>{current&&<Panel key={current.key} anchor={anchors.current[current.key]} label={current.label} onClose={shut}
   footer={note||current.key==='tag'?<>{note&&<p>{note}</p>}{current.key==='tag'&&<button type="button" className="fdock-done" onClick={()=>shut(true)}>Готово{chosenTags.length?' · '+chosenTags.length+' '+plural(chosenTags.length,['тег','тега','тегов']):''}</button>}</>:null}>
   {current.key==='genre'&&<ChoicePanel label="Жанры" findLabel="Найти жанр" options={genres} value={filters.genre} onPick={value=>{onFilter('genre',same(value,filters.genre||'')?'':value);shut(true);}}/>}
   {current.key==='year'&&<YearPanel years={years} value={filters.year} onChange={value=>{onFilter('year',value);if(years)shut(true);}}/>}
   {current.key==='tag'&&<TagPanel value={filters.tag} options={tags} onChange={value=>onFilter('tag',value)}/>}
   {current.key==='format'&&<ChoicePanel label="Форматы" findLabel="Найти формат" options={formats} value={filters.format} onPick={value=>{onFilter('format',same(value,filters.format||'')?'':value);shut(true);}}/>}
   {current.key==='age'&&<Options label="Возраст" options={AGES} selected={id=>id===(filters.age||'')} onPick={id=>{onFilter('age',id);shut(true);}}/>}
   {current.key==='voice'&&(voiceExact?<ChoicePanel label="Студии озвучки" findLabel="Найти озвучку" options={voiceOptions} value={voice} onPick={value=>{onVoice(same(value,voice||'')?'':value);shut(true);}}/>:<VoicePanel value={voice} onChange={onVoice} options={voiceOptions} disabled={voiceDisabled}/>)}
   {current.key==='language'&&<Options label={language.label} options={language.options} selected={id=>id===language.value} onPick={id=>{language.onChange(id);shut(true);}}/>}
  </Panel>}</AnimatePresence>
 </>;
}
