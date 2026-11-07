import {useEffect,useMemo,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Bookmark,BookmarkCheck,CalendarDays,ChevronLeft,ChevronRight,LoaderCircle} from 'lucide-react';
import {useCatalogFavorites} from './catalog-favorites.js';
import {onlineTitleLocation} from './title-route.js';
import './library-calendar.css';

// Episode air dates come from AniList's published airing schedule (not computed);
// Russian names from Shikimori. Bookmarked anime are the tracked ones.
const ANILIST='https://graphql.anilist.co';
const MEDIA='id idMal status episodes format title{romaji english} coverImage{large medium} airingSchedule(perPage:100){nodes{episode airingAt}}';
const QUERY=`query($ids:[Int],$tracked:Boolean!){
 tracked:Page(perPage:50){media(idMal_in:$ids,type:ANIME)@include(if:$tracked){${MEDIA}}}
 airing:Page(perPage:40){media(status:RELEASING,type:ANIME,isAdult:false,sort:POPULARITY_DESC,format_in:[TV,TV_SHORT,ONA]){${MEDIA}}}
}`;
const WEEK=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
const dayKey=d=>d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
const monthName=d=>d.toLocaleDateString('ru-RU',{month:'long'});
const cap=v=>v.charAt(0).toUpperCase()+v.slice(1);
const cache={value:null,key:''};

async function russianNames(ids,signal){
 const names={};
 for(let i=0;i<ids.length;i+=50){
  const chunk=ids.slice(i,i+50);
  try{const r=await fetch('https://shikimori.io/api/animes?'+new URLSearchParams({ids:chunk.join(','),limit:'50'}),{signal});if(r.ok)for(const row of await r.json())if(row?.id)names[row.id]=row.russian||row.name;}catch(e){if(signal.aborted)throw e;}
 }
 return names;
}
function useSchedule(trackedIds){
 const key=trackedIds.slice().sort().join(','),[state,setState]=useState(()=>cache.key===key&&cache.value?{data:cache.value,error:''}:{data:null,error:''});
 useEffect(()=>{
  if(cache.key===key&&cache.value){setState({data:cache.value,error:''});return;}
  const abort=new AbortController(),signal=AbortSignal.any([abort.signal,AbortSignal.timeout(25000)]);
  setState(old=>({data:old.data,error:''}));
  (async()=>{
   const ids=trackedIds.map(Number).filter(Boolean).slice(0,50);
   const response=await fetch(ANILIST,{method:'POST',signal,headers:{'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify({query:QUERY,variables:{ids,tracked:ids.length>0}})});
   const body=await response.json().catch(()=>({}));
   if(!response.ok||!body.data)throw Error(response.status===429?'AniList попросил подождать минуту. Повтори чуть позже.':'Не удалось получить расписание серий.');
   const media=new Map();
   for(const row of [...(body.data.tracked?.media||[]),...(body.data.airing?.media||[])])if(row?.idMal&&!media.has(row.idMal))media.set(row.idMal,row);
   const names=await russianNames([...media.keys()],signal);
   const titles=[...media.values()].map(row=>({mal:String(row.idMal),title:names[row.idMal]||row.title.english||row.title.romaji,status:row.status,total:row.episodes,cover:row.coverImage?.large||row.coverImage?.medium||'',episodes:(row.airingSchedule?.nodes||[]).filter(n=>n?.airingAt).map(n=>({episode:n.episode,at:n.airingAt*1000}))}));
   cache.key=key;cache.value=titles;
   if(!abort.signal.aborted)setState({data:titles,error:''});
  })().catch(e=>{if(!abort.signal.aborted)setState(old=>({data:old.data,error:e.message||'Не удалось получить расписание серий.'}));});
  return()=>abort.abort();
 },[key]);
 return state;
}
function Poster({src}){const [failed,setFailed]=useState(false);return src&&!failed?<img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" onError={()=>setFailed(true)}/>:<span className="lc-poster-empty"/>;}

export default function LibraryCalendar({userId}){
 const reduce=useReducedMotion(),favorites=useCatalogFavorites(userId);
 const trackedIds=useMemo(()=>{try{return JSON.parse(localStorage.getItem('mv_catalog_favorites_v1:'+(userId||'guest'))||'[]').filter(v=>/^anime:mal:\d+$/.test(v)).map(v=>v.split(':')[2]);}catch{return [];}},[userId,favorites]);
 const {data,error}=useSchedule(trackedIds);
 const tracked=new Set(trackedIds);
 const [mode,setMode]=useState(null),[start,setStart]=useState(()=>{const d=new Date();return new Date(d.getFullYear(),d.getMonth(),1);}),[selected,setSelected]=useState(()=>dayKey(new Date()));
 const view=mode||(trackedIds.length?'tracked':'all');
 const titles=(data||[]).filter(t=>view==='all'?t.status==='RELEASING'||tracked.has(t.mal):tracked.has(t.mal));
 const byDay=useMemo(()=>{const map=new Map();for(const t of titles)for(const e of t.episodes){const k=dayKey(new Date(e.at));if(!map.has(k))map.set(k,[]);map.get(k).push({...e,t});}for(const list of map.values())list.sort((a,b)=>a.at-b.at);return map;},[titles]);
 const now=Date.now(),today=dayKey(new Date());
 const upcoming=titles.flatMap(t=>t.episodes.filter(e=>e.at>now).slice(0,1).map(e=>({...e,t}))).sort((a,b)=>a.at-b.at).slice(0,10);
 const months=[0,1,2].map(i=>new Date(start.getFullYear(),start.getMonth()+i,1));
 const range=cap(monthName(months[0]))+' — '+monthName(months[2])+' '+months[2].getFullYear();
 const toggle=t=>favorites.toggle({kind:'anime',ids:{mal:t.mal}});
 const open=t=>onlineTitleLocation({kind:'anime',provider:'shikimori',providerId:t.mal,id:'shikimori:'+t.mal,ids:{mal:t.mal},title:t.title,cover:t.cover});
 const when=at=>{const days=Math.round((new Date(at).setHours(0,0,0,0)-new Date().setHours(0,0,0,0))/86400000);return days===0?'сегодня':days===1?'завтра':days===-1?'вчера':days>1?'через '+days+' дн.':new Date(at).toLocaleDateString('ru-RU',{day:'numeric',month:'short'});};
 const time=at=>new Date(at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
 const dayItems=byDay.get(selected)||[];
 return <section className="library-calendar" aria-label="Календарь выхода серий">
  <header className="lc-toolbar">
   <div className="lc-modes" role="group" aria-label="Что показывать">{[['tracked','Отслеживаемые',trackedIds.length],['all','Все онгоинги',null]].map(([id,label,count])=><button key={id} type="button" aria-pressed={view===id} onClick={()=>setMode(id)}>{view===id&&<motion.span className="lc-mode-active" layoutId="lc-mode" transition={reduce?{duration:0}:{type:'spring',stiffness:420,damping:36}}/>}<span>{label}</span>{count!=null&&<small>{count}</small>}</button>)}</div>
   <div className="lc-nav"><button type="button" aria-label="Предыдущие три месяца" onClick={()=>setStart(d=>new Date(d.getFullYear(),d.getMonth()-3,1))}><ChevronLeft size={18}/></button><strong>{range}</strong><button type="button" aria-label="Следующие три месяца" onClick={()=>setStart(d=>new Date(d.getFullYear(),d.getMonth()+3,1))}><ChevronRight size={18}/></button><button type="button" className="lc-today" onClick={()=>{const d=new Date();setStart(new Date(d.getFullYear(),d.getMonth(),1));setSelected(dayKey(d));}}>Сегодня</button></div>
  </header>
  {view==='tracked'&&!trackedIds.length&&<p className="lc-note">Добавь онгоинг в закладки — его серии появятся здесь. Пока показываем, что выходит сейчас: переключись на «Все онгоинги».</p>}
  {error&&<p className="lc-note is-error" role="alert">{error}</p>}
  {!data&&!error&&<p className="lc-note" role="status"><LoaderCircle className="lc-spin" size={15}/>Получаем расписание серий…</p>}
  {upcoming.length>0&&<div className="lc-soon"><h3>Скоро</h3><ol>{upcoming.map(e=><li key={e.t.mal}><button type="button" onClick={()=>{const d=new Date(e.at);setSelected(dayKey(d));setStart(new Date(d.getFullYear(),d.getMonth(),1));}}><span className="lc-soon-poster"><Poster src={e.t.cover}/></span><span className="lc-soon-text"><strong>{e.t.title}</strong><small>Серия {e.episode} · {when(e.at)}, {time(e.at)}</small></span></button></li>)}</ol></div>}
  <div className="lc-months">{months.map(month=>{const first=(month.getDay()+6)%7,days=new Date(month.getFullYear(),month.getMonth()+1,0).getDate();return <div key={dayKey(month)} className="lc-month">
   <h3>{cap(monthName(month))} <span>{month.getFullYear()}</span></h3>
   <div className="lc-grid" role="grid">{WEEK.map(d=><span key={d} className="lc-weekday">{d}</span>)}{Array.from({length:first},(_,i)=><span key={'e'+i}/>)}
    {Array.from({length:days},(_,i)=>{const date=new Date(month.getFullYear(),month.getMonth(),i+1),key=dayKey(date),items=byDay.get(key)||[],past=key<today;return <button key={key} type="button" role="gridcell" className={'lc-day'+(items.length?' has-items':'')+(key===today?' is-today':'')+(key===selected?' is-selected':'')+(past?' is-past':'')} aria-label={date.toLocaleDateString('ru-RU',{day:'numeric',month:'long'})+(items.length?', серий: '+items.length:'')} onClick={()=>setSelected(key)}>
     <span className="lc-num">{i+1}</span>
     {items.length>0&&<span className="lc-stack">{items.slice(0,3).map(e=><span key={e.t.mal+':'+e.episode}><Poster src={e.t.cover}/></span>)}{items.length>3&&<b>+{items.length-3}</b>}</span>}
    </button>;})}
   </div>
  </div>;})}</div>
  <AnimatePresence mode="wait" initial={false}><motion.div key={selected} className="lc-day-panel" initial={reduce?false:{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0}} transition={{duration:.2}}>
   <h3><CalendarDays size={17}/>{cap(new Date(selected+'T12:00:00').toLocaleDateString('ru-RU',{weekday:'long',day:'numeric',month:'long'}))}</h3>
   {dayItems.length?<ul>{dayItems.map(e=><li key={e.t.mal+':'+e.episode}>
    <button type="button" className="lc-entry" onClick={()=>open(e.t)}><span className="lc-entry-poster"><Poster src={e.t.cover}/></span><span className="lc-entry-text"><strong>{e.t.title}</strong><small>Серия {e.episode}{e.t.total?' из '+e.t.total:''} · {time(e.at)}</small></span><span className={'lc-entry-state'+(e.at<=now?' is-out':'')}>{e.at<=now?'Вышла':'Выйдет '+when(e.at)}</span></button>
    <button type="button" className={'lc-track'+(tracked.has(e.t.mal)?' is-on':'')} aria-pressed={tracked.has(e.t.mal)} aria-label={(tracked.has(e.t.mal)?'Не отслеживать ':'Отслеживать ')+e.t.title} title={tracked.has(e.t.mal)?'Убрать из закладок':'Добавить в закладки и отслеживать'} onClick={()=>toggle(e.t)}>{tracked.has(e.t.mal)?<BookmarkCheck size={17}/>:<Bookmark size={17}/>}</button>
   </li>)}</ul>:<p className="lc-note">{data?'В этот день серий нет.':'…'}</p>}
  </motion.div></AnimatePresence>
 </section>;
}
