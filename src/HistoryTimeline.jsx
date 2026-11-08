import {useMemo,useState,useSyncExternalStore} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {BookOpen,Clapperboard,Cloud,History,Music2,Play,Trash2,X} from 'lucide-react';
import {readProgress,progressClock} from './playback-progress.js';
import {readReading} from './reading-progress.js';
import {useRetainedWorkspace} from './RetainedMedia.jsx';
import {Poster} from './ImportParts.jsx';
import './history-page.css';
import {uiLocale} from './i18n/index.js';

// One history for everything opened on this device: library titles (online),
// player sessions (online and collection) and collection files.
const TITLES='mv_public_titles_v1',HIDDEN='mv_history_hidden_v1';
const listeners=new Set(),emit=()=>listeners.forEach(fn=>fn());
function readJSON(key,fallback){try{return JSON.parse(localStorage.getItem(key)||'null')??fallback;}catch{return fallback;}}
function hidden(){return readJSON(HIDDEN,{});}
function hide(keys){const value=hidden(),now=Date.now();for(const key of keys)value[key]=now;try{localStorage.setItem(HIDDEN,JSON.stringify(Object.fromEntries(Object.entries(value).slice(-400))));}catch{}emit();}
function useHistoryRevision(){return useSyncExternalStore(fn=>{listeners.add(fn);addEventListener('storage',fn);return()=>{listeners.delete(fn);removeEventListener('storage',fn);};},()=>localStorage.getItem(HIDDEN)||'',()=>'');}
const kindLabel={anime:'Аниме',manga:'Манга',ranobe:'Ранобэ',book:'Книга',movie:'Фильм',tv:'Сериал',music:'Музыка'};
const dayLabel=at=>{const d=new Date(at),today=new Date();today.setHours(0,0,0,0);const diff=Math.round((today-new Date(d.getFullYear(),d.getMonth(),d.getDate()))/86400000);return diff===0?'Сегодня':diff===1?'Вчера':d.toLocaleDateString(uiLocale(),{day:'numeric',month:'long',...(d.getFullYear()!==today.getFullYear()?{year:'numeric'}:{})});};
const timeLabel=at=>new Date(at).toLocaleTimeString(uiLocale(),{hour:'2-digit',minute:'2-digit'});
const watchKey=route=>{try{return new URLSearchParams(String(route||'').replace(/^#/,'')).get('watch')||'';}catch{return '';}};

export default function HistoryTimeline({recent,onOpen,renderCover,userId,libraryId,onForgetCollection,onClearCollection,actions,empty=null}){
 const store=useRetainedWorkspace(),reduce=useReducedMotion(),revision=useHistoryRevision(),[filter,setFilter]=useState('all');
 const viewing=useSyncExternalStore(store?store.subscribe:()=>()=>{},()=>store?store.getSnapshot().history:[],()=>[]);
 const entries=useMemo(()=>{
  const muted=hidden(),titles=readJSON(TITLES,{}),rows=new Map();
  const put=row=>{if((muted[row.key]||0)>=row.at)return;const old=rows.get(row.key);if(!old||old.at<row.at)rows.set(row.key,{...old,...row,cover:row.cover||old?.cover});};
  for(const [key,value] of Object.entries(titles))if(value?.openedAt)put({key:'title:'+key,source:'library',kind:value.kind,title:value.title||'Без названия',cover:value.cover,mal:value.ids?.mal||(value.provider==='shikimori'?value.providerId:''),meta:[kindLabel[value.kind],value.year].filter(Boolean).join(' · '),at:value.openedAt,open:()=>{location.hash='watch='+key;}});
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
 const shown=entries.filter(row=>filter==='all'||row.source===filter);
 const groups=[];for(const row of shown){const label=dayLabel(row.at);const last=groups.at(-1);if(last?.label===label)last.rows.push(row);else groups.push({label,rows:[row]});}
 function forget(row){hide([row.key]);if(row.viewId)store?.forget?.(row.viewId);if(row.itemId)onForgetCollection?.(row.itemId);}
 function clearAll(){if(!confirm('Очистить всю историю на этом устройстве? Прогресс серий и страниц сохранится.'))return;hide(entries.map(row=>row.key));store?.forgetAll?.();onClearCollection?.();}
 const counts={all:entries.length,library:entries.filter(r=>r.source==='library').length,collection:entries.filter(r=>r.source==='collection').length};
 if(!entries.length)return empty;
 return <div className="history-page">
  <div className="history-toolbar">
   <div className="history-filter" role="group" aria-label="Что показать">{[['all','Всё'],['library','Библиотека'],['collection','Коллекция']].map(([id,label])=><button key={id} type="button" aria-pressed={filter===id} onClick={()=>setFilter(id)}>{filter===id&&<motion.span layoutId="history-filter" className="history-filter-active" transition={reduce?{duration:0}:{type:'spring',stiffness:420,damping:36}}/>}<span>{label}</span><small>{counts[id]}</small></button>)}</div>
   <button type="button" className="history-clear" onClick={clearAll}><Trash2 size={15}/>Очистить историю</button>
  </div>
  {groups.map(group=><section key={group.label} className="history-day"><h2>{group.label}</h2><ul><AnimatePresence initial={false}>{group.rows.map(row=><motion.li key={row.key} layout={!reduce} initial={reduce?false:{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={reduce?{opacity:0}:{opacity:0,scale:.96}} transition={{duration:.22}}>
   <button type="button" className="history-card" onClick={row.open}>
    <span className="history-poster">{row.item?renderCover(row.item):row.cover||row.mal?<Poster item={{id:row.key,title:row.title,cover:row.cover,kind:row.kind,ids:row.mal?{mal:row.mal}:{}}}/>:<span className="history-poster-empty">{row.kind==='manga'||row.kind==='ranobe'||row.kind==='book'?<BookOpen size={22}/>:row.kind==='music'?<Music2 size={22}/>:<Clapperboard size={22}/>}</span>}{row.progress>0&&<i className="history-bar"><b style={{transform:`scaleX(${row.progress})`}}/></i>}</span>
    <span className="history-text">
     <strong>{row.title}</strong>
     <small>{row.meta}</small>
     <span className="history-tags"><span className={'history-source is-'+row.source}>{row.source==='library'?<History size={12}/>:<Cloud size={12}/>}{row.source==='library'?'Библиотека':'Коллекция'}</span><span>{timeLabel(row.at)}</span></span>
    </span>
    <span className="history-go">{row.kind==='manga'||row.kind==='ranobe'||row.kind==='book'?<BookOpen size={17}/>:<Play size={17}/>}</span>
   </button>
   <button type="button" className="history-forget" aria-label={'Убрать из истории: '+row.title} title="Убрать из истории" onClick={()=>forget(row)}><X size={15}/></button>
  </motion.li>)}</AnimatePresence></ul></section>)}
  {!shown.length&&<p className="fine">В этом разделе истории пока пусто.</p>}
 </div>;
}
