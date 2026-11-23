import {useEffect,useMemo,useRef,useState,useSyncExternalStore} from 'react';
import {AnimatePresence,LayoutGroup,motion,useReducedMotion,useScroll} from 'motion/react';
import {BookOpen,Clapperboard,Music2,Play,RotateCcw,Trash2,X} from 'lucide-react';
import {KineticText,RollingNumber} from './LibraryRail.jsx';
import {readProgress,progressClock} from './playback-progress.js';
import {readReading} from './reading-progress.js';
import {useRetainedWorkspace} from './RetainedMedia.jsx';
import {Poster} from './ImportParts.jsx';
import './history-page.css';
import {uiLocale} from './i18n/index.js';
import {titleOpens,scopedKey} from './history-scope.js';

// One history per profile for everything opened on this device: library titles (online),
// player sessions (online and collection) and collection files.
const TITLES='mv_public_titles_v1',HIDDEN='mv_history_hidden_v1';
const listeners=new Set(),emit=()=>listeners.forEach(fn=>fn());
function readJSON(key,fallback){try{return JSON.parse(localStorage.getItem(key)||'null')??fallback;}catch{return fallback;}}
function hidden(user){return readJSON(scopedKey(HIDDEN,user),{});}
function unhide(keys,user){const value=hidden(user);for(const key of keys)delete value[key];try{localStorage.setItem(scopedKey(HIDDEN,user),JSON.stringify(value));}catch{}emit();}
function hide(keys,user){const value=hidden(user),now=Date.now();for(const key of keys)value[key]=now;try{localStorage.setItem(scopedKey(HIDDEN,user),JSON.stringify(Object.fromEntries(Object.entries(value).slice(-400))));}catch{}emit();}
function useHistoryRevision(){return useSyncExternalStore(fn=>{listeners.add(fn);addEventListener('storage',fn);return()=>{listeners.delete(fn);removeEventListener('storage',fn);};},()=>localStorage.getItem(scopedKey(HIDDEN))||'',()=>'');}
const kindLabel={anime:'Аниме',manga:'Манга',ranobe:'Ранобэ',book:'Книга',movie:'Фильм',tv:'Сериал',music:'Музыка'};
const dayLabel=at=>{const d=new Date(at),today=new Date();today.setHours(0,0,0,0);const diff=Math.round((today-new Date(d.getFullYear(),d.getMonth(),d.getDate()))/86400000);return diff===0?'Сегодня':diff===1?'Вчера':d.toLocaleDateString(uiLocale(),{day:'numeric',month:'long',...(d.getFullYear()!==today.getFullYear()?{year:'numeric'}:{})});};
const timeLabel=at=>new Date(at).toLocaleTimeString(uiLocale(),{hour:'2-digit',minute:'2-digit'});
const watchKey=route=>{try{return new URLSearchParams(String(route||'').replace(/^#/,'')).get('watch')||'';}catch{return '';}};

export default function HistoryTimeline({recent,onOpen,renderCover,userId,libraryId,onForgetCollection,onClearCollection,actions,empty=null}){
 const store=useRetainedWorkspace(),reduce=useReducedMotion(),revision=useHistoryRevision(),[filter,setFilter]=useState('all'),[kind,setKind]=useState('all');
 const viewing=useSyncExternalStore(store?store.subscribe:()=>()=>{},()=>store?store.getSnapshot().history:[],()=>[]);
 const entries=useMemo(()=>{
  const muted=hidden(userId),titles=readJSON(TITLES,{}),opens=titleOpens(userId),rows=new Map();
  const put=row=>{if((muted[row.key]||0)>=row.at)return;const old=rows.get(row.key);if(!old||old.at<row.at)rows.set(row.key,{...old,...row,cover:row.cover||old?.cover});};
  for(const [key,openedAt] of Object.entries(opens)){const value=titles[key];if(value)put({key:'title:'+key,source:'library',kind:value.kind,title:value.title||'Без названия',cover:value.cover,mal:value.ids?.mal||(value.provider==='shikimori'?value.providerId:''),meta:[kindLabel[value.kind],value.year].filter(Boolean).join(' · '),at:openedAt,open:()=>{location.hash='watch='+key;}});}
  for(const value of viewing||[]){
   if(value.resumeItemId&&recent.some(r=>r.item.id===value.resumeItemId))continue;
   const key=watchKey(value.route),title=key?titles[key]:null;
   put({key:key?'title:'+key:'view:'+value.id,viewId:value.id,source:key?'library':'collection',kind:title?.kind||(value.kind==='reader'?'manga':'anime'),title:title?.title||value.label,cover:title?.cover,mal:title?.ids?.mal||'',meta:value.label!==title?.title?value.label:[kindLabel[title?.kind],title?.year].filter(Boolean).join(' · '),at:value.at,playing:true,open:()=>store?.revisit(value)});
  }
  for(const {entry,item} of recent){
   const manga=item.category==='manga',progress=manga?readReading(userId,libraryId,item.id):readProgress(userId,libraryId,item.id);
   put({key:'item:'+item.id,itemId:item.id,source:'collection',kind:manga?'manga':item.category==='audio'?'music':'anime',title:item.name,item,meta:progress?(manga?'Страница '+(progress.page+1):'Остановился на '+progressClock(progress.time)):'Открыть снова',progress:progress?.duration>0?Math.min(1,progress.time/progress.duration):0,at:entry.at,open:()=>onOpen(item)});
  }
  return [...rows.values()].sort((a,b)=>b.at-a.at);
 },[viewing,recent,revision,userId,libraryId]);
 // «Лента»: where it came from and what it was are two rail filters; rows can be
 // swiped away and come back with «Вернуть» until the notice fades.
 const shown=entries.filter(row=>(filter==='all'||row.source===filter)&&(kind==='all'||row.kind===kind));
 const groups=[];for(const row of shown){const label=dayLabel(row.at);const last=groups.at(-1);if(last?.label===label)last.rows.push(row);else groups.push({label,rows:[row]});}
 const [undo,setUndo]=useState(null),[ask,setAsk]=useState(false),[day,setDay]=useState(''),[stuck,setStuck]=useState(false),dayRefs=useRef({}),dragged=useRef(false),pending=useRef(null);
 pending.current=undo;
 // Losing a player session or a collection record cannot be undone, so it waits for the notice to go.
 useEffect(()=>{if(!undo)return;const t=setTimeout(()=>{undo.commit();setUndo(null);},6000);return()=>clearTimeout(t);},[undo]);
 useEffect(()=>()=>pending.current?.commit(),[]);
 function settle(next){if(undo)undo.commit();setUndo(next);}
 function forget(row){hide([row.key],userId);settle({label:'«'+row.title+'» убрано из истории',restore:()=>unhide([row.key],userId),commit:()=>{if(row.viewId)store?.forget?.(row.viewId);if(row.itemId)onForgetCollection?.(row.itemId);}});}
 function clearAll(){const keys=entries.map(row=>row.key);hide(keys,userId);setAsk(false);settle({label:'История очищена · прогресс серий и страниц сохранён',restore:()=>unhide(keys,userId),commit:()=>{store?.forgetAll?.();onClearCollection?.();}});}
 const kinds=[...new Set(entries.map(row=>row.kind).filter(Boolean))];
 const count=(s,k)=>entries.filter(row=>(s==='all'||row.source===s)&&(k==='all'||row.kind===k)).length;
 const {scrollY}=useScroll();
 useEffect(()=>scrollY.on('change',v=>setStuck(v>320)),[scrollY]);
 useEffect(()=>{
  const observer=new IntersectionObserver(list=>{const top=list.filter(e=>e.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top)[0];if(top)setDay(top.target.dataset.day);},{rootMargin:'-30% 0px -60% 0px'});
  Object.values(dayRefs.current).forEach(node=>node&&observer.observe(node));return()=>observer.disconnect();
 },[groups.length,filter,kind]);
 if(!entries.length&&!undo)return empty;
 const headline=day&&groups.some(g=>g.label===day)?day:groups[0]?.label||'История';
 const hero=entries[0],reading=k=>['manga','ranobe','book'].includes(k);
 const glyph=row=>reading(row.kind)?<BookOpen size={16}/>:row.kind==='music'?<Music2 size={16}/>:<Play size={16}/>;
 const cover=row=>row.item?renderCover(row.item):row.cover||row.mal?<Poster item={{id:row.key,title:row.title,cover:row.cover,kind:row.kind,ids:row.mal?{mal:row.mal}:{}}}/>:<span className="history-poster-empty">{reading(row.kind)?<BookOpen size={22}/>:row.kind==='music'?<Music2 size={22}/>:<Clapperboard size={22}/>}</span>;
 const ink=on=>on&&<motion.span layoutId="ink" className="mv-rail-ink" transition={reduce?{duration:0}:{type:'spring',stiffness:520,damping:40,mass:.8}}/>;
 return <div className="mv-railed history-page">
  <nav className="mv-rail history-rail" aria-label="Фильтры истории">
   <span className="mv-rail-kicker">История</span>
   <LayoutGroup id="history-source"><ul className="mv-rail-list" role="group" aria-label="Что показать">{[['all','Всё'],['library','Библиотека'],['collection','Коллекция']].map(([id,label])=><li key={id}>
    <button type="button" aria-pressed={filter===id} className={filter===id?'is-on':undefined} onClick={()=>setFilter(id)}>{ink(filter===id)}<span className="mv-rail-label">{label}</span><span className="mv-rail-count"><RollingNumber value={count(id,kind)}/></span></button></li>)}</ul></LayoutGroup>
   {kinds.length>1&&<><span className="mv-rail-kicker history-rail-kicker">Что смотрел</span>
   <LayoutGroup id="history-kind"><ul className="mv-rail-list" role="group" aria-label="Вид">{[['all','Всё подряд'],...kinds.map(k=>[k,kindLabel[k]||k])].map(([id,label])=><li key={id}>
    <button type="button" aria-pressed={kind===id} className={kind===id?'is-on':undefined} onClick={()=>setKind(id)}>{ink(kind===id)}<span className="mv-rail-label">{label}</span><span className="mv-rail-count"><RollingNumber value={count(filter,id)}/></span></button></li>)}</ul></LayoutGroup></>}
   <div className="mv-rail-actions history-clear-row"><AnimatePresence mode="popLayout" initial={false}>{ask
    ?<motion.span key="ask" className="history-ask" initial={{opacity:0,scale:.92}} animate={{opacity:1,scale:1}} exit={{opacity:0,scale:.92}}><small>Очистить всё?</small><button type="button" className="is-yes" onClick={clearAll}>Да</button><button type="button" onClick={()=>setAsk(false)}>Нет</button></motion.span>
    :<motion.button key="clear" type="button" className="history-clear" disabled={!entries.length} initial={{opacity:0,scale:.92}} animate={{opacity:1,scale:1}} exit={{opacity:0,scale:.92}} onClick={()=>setAsk(true)}><Trash2 size={15}/><span className="mv-rail-label">Очистить историю</span></motion.button>}</AnimatePresence></div>
  </nav>
  <div className="mv-railed-main">
   <header className="mv-rail-head"><span className="mv-rail-kicker">История</span><div className="mv-rail-title" aria-hidden="true"><KineticText text={headline}/></div></header>
   <AnimatePresence>{stuck&&groups.length>0&&<motion.div className="history-daybar" aria-hidden="true" initial={{y:-70,opacity:0}} animate={{y:0,opacity:1}} exit={{y:-70,opacity:0}} transition={{type:'spring',stiffness:420,damping:36}}><KineticText text={headline}/><small>{shown.length} в истории</small></motion.div>}</AnimatePresence>
   {hero&&filter==='all'&&kind==='all'&&<motion.button type="button" className="history-hero" onClick={hero.open} initial={reduce?false:{opacity:0,y:18}} animate={{opacity:1,y:0}} transition={{type:'spring',stiffness:260,damping:32}}>
    {hero.cover&&<img className="history-hero-bg" src={hero.cover} alt=""/>}<span className="history-hero-shade"/>
    <span className="history-hero-poster">{cover(hero)}</span>
    <span className="history-hero-text"><span className="mv-rail-kicker">Продолжить{kindLabel[hero.kind]?' · '+kindLabel[hero.kind]:''}</span><b>{hero.title}</b><small>{hero.meta}</small>
     {hero.progress>0&&<span className="history-bar"><motion.i initial={{width:0}} animate={{width:hero.progress*100+'%'}} transition={{duration:1.2,ease:[.22,1,.36,1]}}/></span>}</span>
    <span className="history-hero-go">{glyph(hero)}<span>{reading(hero.kind)?'Читать':'Смотреть'}</span></span>
   </motion.button>}
   {groups.map(group=><section key={group.label} className="history-day" data-day={group.label} ref={node=>{dayRefs.current[group.label]=node;}}>
    <h2>{group.label}<small>{group.rows.length}</small></h2>
    <ul><AnimatePresence initial={false}>{group.rows.map((row,i)=><motion.li key={row.key} layout={!reduce} initial={reduce?false:{opacity:0,y:12}} animate={{opacity:1,y:0,transition:{type:'spring',stiffness:260,damping:32,delay:Math.min(i,8)*.04}}} exit={reduce?{opacity:0}:{opacity:0,x:-90,height:0,marginBottom:0,transition:{duration:.3}}}>
     <motion.div className="history-row" drag={reduce?false:'x'} dragConstraints={{left:0,right:0}} dragElastic={{left:.6,right:.08}} dragSnapToOrigin
      onDragStart={()=>{dragged.current=true;}} onDragEnd={(_,info)=>{setTimeout(()=>{dragged.current=false;},0);if(info.offset.x<-110)forget(row);}}>
      {row.cover&&<img className="history-row-bg" src={row.cover} alt=""/>}
      <button type="button" className="history-card" onClick={event=>{if(dragged.current){event.preventDefault();return;}row.open();}}>
       <span className="history-poster">{cover(row)}</span>
       <span className="history-text"><strong>{row.title}</strong><small>{row.meta}</small>{row.progress>0&&<span className="history-bar"><motion.i initial={{width:0}} animate={{width:row.progress*100+'%'}} transition={{duration:1,ease:[.22,1,.36,1]}}/></span>}</span>
       <span className="history-meta"><span className={'history-source is-'+row.source}>{row.source==='library'?'Библиотека':'Коллекция'}</span><time>{timeLabel(row.at)}</time></span>
       <span className="history-go">{glyph(row)}</span>
      </button>
      <button type="button" className="history-forget" aria-label={'Убрать из истории: '+row.title} title="Убрать из истории" onClick={()=>forget(row)}><X size={15}/></button>
     </motion.div>
    </motion.li>)}</AnimatePresence></ul>
   </section>)}
   {!shown.length&&<p className="history-empty">В этом разделе истории пока пусто.</p>}
  </div>
  <AnimatePresence>{undo&&<motion.div className="history-undo" role="status" initial={{y:80,opacity:0}} animate={{y:0,opacity:1}} exit={{y:80,opacity:0}} transition={{type:'spring',stiffness:420,damping:36}}>
   <span>{undo.label}</span><button type="button" onClick={()=>{undo.restore();setUndo(null);}}><RotateCcw size={14}/>Вернуть</button>
  </motion.div>}</AnimatePresence>
 </div>;
}
