import {useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Bookmark,BookmarkCheck,ChevronLeft,ChevronRight,LoaderCircle} from 'lucide-react';
import {useCatalogFavorites} from './catalog-favorites.js';
import {onlineTitleLocation} from './title-route.js';
import './library-calendar.css';
import {uiLocale} from './i18n/index.js';

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
const monthName=d=>d.toLocaleDateString(uiLocale(),{month:'long'});
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
const plural=(n,[one,few,many])=>{const t=n%10,h=n%100;return t===1&&h!==11?one:t>=2&&t<=4&&(h<12||h>14)?few:many;};
// Time left until an episode, in words a person reads at a glance.
function until(at,now){
 const minutes=Math.round((at-now)/60000);
 if(minutes<=0)return 'уже вышла';
 if(minutes<60)return 'через '+minutes+' мин';
 const hours=Math.floor(minutes/60);
 if(hours<24)return 'через '+hours+' ч'+(hours<3&&minutes%60?' '+minutes%60+' мин':'');
 const days=Math.round(hours/24);return 'через '+days+' '+plural(days,['день','дня','дней']);
}

function Soon({items,now,when,time,onPick}){
 const track=useRef(null),[edges,setEdges]=useState({left:false,right:false});
 useLayoutEffect(()=>{const node=track.current;if(!node)return;const update=()=>setEdges({left:node.scrollLeft>4,right:node.scrollLeft+node.clientWidth<node.scrollWidth-4});update();node.addEventListener('scroll',update,{passive:true});const observer=new ResizeObserver(update);observer.observe(node);return()=>{node.removeEventListener('scroll',update);observer.disconnect();};},[items.length]);
 const move=direction=>track.current?.scrollBy({left:direction*Math.max(280,track.current.clientWidth*.8),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
 return <section className="lc-soon" aria-label="Ближайшие серии">
  <header><h3>Ближайшие серии</h3><div className="lc-soon-arrows"><button type="button" aria-label="Прокрутить назад" disabled={!edges.left} onClick={()=>move(-1)}><ChevronLeft size={18}/></button><button type="button" aria-label="Прокрутить вперёд" disabled={!edges.right} onClick={()=>move(1)}><ChevronRight size={18}/></button></div></header>
  <div className={'lc-soon-frame'+(edges.left?' fade-left':'')+(edges.right?' fade-right':'')}>
   <ol ref={track} className="lc-soon-track">{items.map(e=>{const soon=e.at-now<86400000;return <li key={e.t.mal}>
    <button type="button" className="lc-soon-card" aria-label={e.t.title+', серия '+e.episode+', '+when(e.at)+' в '+time(e.at)} onClick={()=>onPick(e)}>
     <span className="lc-soon-poster"><Poster src={e.t.cover}/></span>
     <span className="lc-soon-text"><strong>{e.t.title}</strong><span className="lc-soon-episode">Серия {e.episode}{e.t.total?' из '+e.t.total:''}</span><span className="lc-soon-when">{cap(when(e.at))}, {time(e.at)}</span></span>
     <span className={'lc-countdown'+(soon?' is-soon':'')}>{until(e.at,now)}</span>
    </button>
   </li>;})}</ol>
  </div>
 </section>;
}

export default function LibraryCalendar({userId}){
 const reduce=useReducedMotion(),favorites=useCatalogFavorites(userId);
 const trackedIds=useMemo(()=>{try{return JSON.parse(localStorage.getItem('mv_catalog_favorites_v1:'+(userId||'guest'))||'[]').filter(v=>/^anime:mal:\d+$/.test(v)).map(v=>v.split(':')[2]);}catch{return [];}},[userId,favorites]);
 const {data,error}=useSchedule(trackedIds);
 const tracked=new Set(trackedIds);
 const [mode,setMode]=useState(null),[month,setMonth]=useState(()=>{const d=new Date();return new Date(d.getFullYear(),d.getMonth(),1);}),[selected,setSelected]=useState(()=>dayKey(new Date())),[direction,setDirection]=useState(0);
 const [now,setNow]=useState(()=>Date.now());
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),60000);return()=>clearInterval(timer);},[]);
 const view=mode||(trackedIds.length?'tracked':'all');
 const titles=(data||[]).filter(t=>view==='all'?t.status==='RELEASING'||tracked.has(t.mal):tracked.has(t.mal));
 const byDay=useMemo(()=>{const map=new Map();for(const t of titles)for(const e of t.episodes){const k=dayKey(new Date(e.at));if(!map.has(k))map.set(k,[]);map.get(k).push({...e,t});}for(const list of map.values())list.sort((a,b)=>a.at-b.at);return map;},[titles]);
 const today=dayKey(new Date(now));
 const upcoming=titles.flatMap(t=>t.episodes.filter(e=>e.at>now).slice(0,1).map(e=>({...e,t}))).sort((a,b)=>a.at-b.at).slice(0,16);
 const shift=step=>{setDirection(step);setMonth(d=>new Date(d.getFullYear(),d.getMonth()+step,1));};
 const pick=date=>{const d=new Date(date);setSelected(dayKey(d));const first=new Date(d.getFullYear(),d.getMonth(),1);if(first.getTime()!==month.getTime()){setDirection(first>month?1:-1);setMonth(first);}};
 const toggle=t=>favorites.toggle({kind:'anime',ids:{mal:t.mal}});
 const open=t=>onlineTitleLocation({kind:'anime',provider:'shikimori',providerId:t.mal,id:'shikimori:'+t.mal,ids:{mal:t.mal},title:t.title,cover:t.cover});
 const when=at=>{const days=Math.round((new Date(at).setHours(0,0,0,0)-new Date(now).setHours(0,0,0,0))/86400000);return days===0?'сегодня':days===1?'завтра':days===-1?'вчера':new Date(at).toLocaleDateString(uiLocale(),{weekday:'short',day:'numeric',month:'short'});};
 const time=at=>new Date(at).toLocaleTimeString(uiLocale(),{hour:'2-digit',minute:'2-digit'});
 const first=(month.getDay()+6)%7,days=new Date(month.getFullYear(),month.getMonth()+1,0).getDate();
 const monthCount=[...byDay.entries()].filter(([k])=>k.startsWith(dayKey(month).slice(0,7))).reduce((sum,[,list])=>sum+list.length,0);
 const dayItems=byDay.get(selected)||[],selectedDate=new Date(selected+'T12:00:00');
 const slide=reduce?{initial:false,animate:{opacity:1},exit:{opacity:0}}:{initial:{opacity:0,x:direction*36},animate:{opacity:1,x:0},exit:{opacity:0,x:direction*-36}};
 return <section className="library-calendar" aria-label="Календарь выхода серий">
  <header className="lc-toolbar">
   <div className="lc-modes" role="group" aria-label="Что показывать">{[['tracked','Отслеживаемые',trackedIds.length],['all','Все онгоинги',null]].map(([id,label,count])=><button key={id} type="button" aria-pressed={view===id} onClick={()=>setMode(id)}>{view===id&&<motion.span className="lc-mode-active" layoutId="lc-mode" transition={reduce?{duration:0}:{type:'spring',stiffness:420,damping:36}}/>}<span>{label}</span>{count!=null&&<small>{count}</small>}</button>)}</div>
   <div className="lc-nav">
    <button type="button" aria-label="Предыдущий месяц" onClick={()=>shift(-1)}><ChevronLeft size={18}/></button>
    <AnimatePresence mode="popLayout" initial={false}><motion.strong key={dayKey(month)} {...slide} transition={{duration:.22,ease:[.22,1,.36,1]}}>{cap(monthName(month))} {month.getFullYear()}</motion.strong></AnimatePresence>
    <button type="button" aria-label="Следующий месяц" onClick={()=>shift(1)}><ChevronRight size={18}/></button>
    <button type="button" className="lc-today" onClick={()=>pick(Date.now())}>Сегодня</button>
   </div>
  </header>
  {view==='tracked'&&!trackedIds.length&&<p className="lc-note">Добавь онгоинг в закладки, и его серии появятся здесь. Пока показываем всё, что выходит сейчас.</p>}
  {error&&<p className="lc-note is-error" role="alert">{error}</p>}
  {!data&&!error&&<p className="lc-note" role="status"><LoaderCircle className="lc-spin" size={15}/>Получаем расписание серий…</p>}
  {upcoming.length>0&&<Soon items={upcoming} now={now} when={when} time={time} onPick={e=>pick(e.at)}/>}
  <div className="lc-board">
   <section className="lc-month" aria-label={cap(monthName(month))+' '+month.getFullYear()+(monthCount?', серий: '+monthCount:'')}>
    <div className="lc-weekdays" aria-hidden="true">{WEEK.map(d=><span key={d}>{d}</span>)}</div>
    <AnimatePresence mode="popLayout" initial={false}><motion.div key={dayKey(month)} className="lc-grid" role="grid" {...slide} transition={{duration:.28,ease:[.22,1,.36,1]}}>
     {Array.from({length:first},(_,i)=><span key={'e'+i} className="lc-blank"/>)}
     {Array.from({length:days},(_,i)=>{const date=new Date(month.getFullYear(),month.getMonth(),i+1),key=dayKey(date),items=byDay.get(key)||[],past=key<today;return <button key={key} type="button" role="gridcell" className={'lc-day'+(items.length?' has-items':'')+(key===today?' is-today':'')+(key===selected?' is-selected':'')+(past?' is-past':'')} aria-selected={key===selected} aria-label={date.toLocaleDateString(uiLocale(),{weekday:'long',day:'numeric',month:'long'})+(items.length?', '+items.length+' '+plural(items.length,['серия','серии','серий']):', серий нет')} onClick={()=>setSelected(key)}>
      <span className="lc-num">{i+1}</span>
      {items.length>0&&<span className="lc-cell-list">{items.slice(0,3).map(e=><span key={e.t.mal+':'+e.episode} className="lc-cell-entry"><span className="lc-cell-poster"><Poster src={e.t.cover}/></span><span className="lc-cell-text"><b>{e.t.title}</b><small>{time(e.at)} · {e.episode} сер.</small></span></span>)}</span>}
      {items.length>3&&<span className="lc-more">ещё {items.length-3}</span>}
      {items.length>0&&<span className="lc-cell-count">{items.length}</span>}
     </button>;})}
    </motion.div></AnimatePresence>
   </section>
   <AnimatePresence mode="wait" initial={false}><motion.section key={selected} className="lc-agenda" aria-label="Серии выбранного дня" initial={reduce?false:{opacity:0,y:10}} animate={{opacity:1,y:0}} exit={{opacity:0}} transition={{duration:.2}}>
    <header><h3>{cap(selectedDate.toLocaleDateString(uiLocale(),{weekday:'long',day:'numeric',month:'long'}))}</h3>{dayItems.length>0&&<span>{dayItems.length} {plural(dayItems.length,['серия','серии','серий'])}</span>}</header>
    {dayItems.length?<ol className="lc-agenda-list">{dayItems.map(e=>{const out=e.at<=now;return <li key={e.t.mal+':'+e.episode} className={out?'is-out':undefined}>
     <time className="lc-agenda-time" dateTime={new Date(e.at).toISOString()}>{time(e.at)}</time>
     <button type="button" className="lc-entry" onClick={()=>open(e.t)}>
      <span className="lc-entry-poster"><Poster src={e.t.cover}/></span>
      <span className="lc-entry-text"><strong>{e.t.title}</strong><small>Серия {e.episode}{e.t.total?' из '+e.t.total:''}</small><span className={'lc-entry-state'+(out?' is-out':e.at-now<86400000?' is-soon':'')}>{out?'Уже вышла':until(e.at,now)}</span></span>
     </button>
     <button type="button" className={'lc-track'+(tracked.has(e.t.mal)?' is-on':'')} aria-pressed={tracked.has(e.t.mal)} aria-label={(tracked.has(e.t.mal)?'Не отслеживать ':'Отслеживать ')+e.t.title} title={tracked.has(e.t.mal)?'Убрать из закладок':'Добавить в закладки и отслеживать'} onClick={()=>toggle(e.t)}>{tracked.has(e.t.mal)?<BookmarkCheck size={18}/>:<Bookmark size={18}/>}</button>
    </li>;})}</ol>:<p className="lc-agenda-empty">{data?'В этот день новых серий нет. Выбери день с обложками в календаре.':'Расписание ещё загружается.'}</p>}
   </motion.section></AnimatePresence>
  </div>
 </section>;
}
