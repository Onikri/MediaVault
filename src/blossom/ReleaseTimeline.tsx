import {useEffect,useRef,useState} from 'react';
import {CalendarDays,List,ChevronLeft,ChevronRight} from 'lucide-react';
import {jikan} from '../media-metadata.js';
export default function ReleaseTimeline({identity,releases=[],server}:{identity?:string;releases?:any[];server?:string}){
 const root=useRef<HTMLElement>(null),generation=useRef(0);
 const [enabled,setEnabled]=useState(false),[episodes,setEpisodes]=useState<any[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[retry,setRetry]=useState(0),[view,setView]=useState('list'),[month,setMonth]=useState('');
 useEffect(()=>{const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setEnabled(true);observer.disconnect();}},{rootMargin:'200px'});if(root.current)observer.observe(root.current);return()=>observer.disconnect();},[]);
 useEffect(()=>{
  const version=++generation.current,controller=new AbortController();setEpisodes([]);setMonth('');setError('');
  if(!enabled||!/^\d+$/.test(identity||''))return()=>controller.abort();setBusy(true);
  (async()=>{let page=1;do{
   const data=await jikan('anime/'+identity+'/episodes',{server,signal:controller.signal,params:{page}});
   if(controller.signal.aborted||version!==generation.current)return;if(!Array.isArray(data.data))throw Error();
   setEpisodes(old=>[...new Map([...old,...data.data.filter((x:any)=>x.aired).map((x:any)=>({episode:x.mal_id,date:x.aired,title:x.title,titleRomanji:x.title_romanji,titleJapanese:x.title_japanese,filler:x.filler,recap:x.recap,characters:x.characters}))].map(x=>[String(x.episode),x])).values()]);
   if(!data.pagination?.has_next_page)break;page++;
   // Fetch progressively within the public API request budget.
   await new Promise<void>((resolve,reject)=>{const done=()=>{controller.signal.removeEventListener('abort',cancel);resolve();},timer=setTimeout(done,1100),cancel=()=>{clearTimeout(timer);reject(controller.signal.reason);};controller.signal.addEventListener('abort',cancel,{once:true});});
  }while(page<=20);})().catch(()=>{if(!controller.signal.aborted)setError('Не удалось получить все даты.');}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});return()=>controller.abort();
 },[enabled,identity,server,retry]);
 const merged=new Map();for(const item of [...episodes,...releases])if(item.date&&Number.isFinite(Date.parse(item.date)))merged.set(String(item.episode),{...merged.get(String(item.episode)),...item});
 const values=[...merged.values()].sort((a,b)=>Date.parse(a.date)-Date.parse(b.date));
 const months=[...new Set(values.map(x=>x.date.slice(0,7)))],selected=months.includes(month)?month:months[0],monthIndex=months.indexOf(selected),date=selected?new Date(selected+'-01T12:00:00'):null;
 const description=(x:any)=>[x.filler?'Филлер':'',x.recap?'Рекап':'',...(x.characters||[]).map((c:any)=>typeof c==='string'?c:c.name).filter(Boolean)].filter(Boolean).join(' · ');
 function entry(x:any){return <><span className="release-episode-number">{String(x.episode).padStart(2,'0')}</span><div><strong>{x.title||x.titleRomanji||x.titleJapanese||'Серия '+x.episode}</strong><time dateTime={x.date}>{new Date(x.date).toLocaleDateString('ru-RU',{day:'numeric',month:'short',year:'numeric'})}</time>{description(x)&&<small>{description(x)}</small>}</div><small>{Date.parse(x.date)<Date.now()?'Вышла':'Ожидается'}</small></>;}
 const days=date?new Date(date.getFullYear(),date.getMonth()+1,0).getDate():0,offset=date?(date.getDay()+6)%7:0;
 return <section ref={root} id="titleSchedule" className="release-timeline release-calendar"><div className="section-heading"><h2><CalendarDays size={19}/>Календарь выпуска</h2><div className="section-view-switch" role="group" aria-label="Вид календаря"><button aria-label="Список дат" aria-pressed={view==='list'} onClick={()=>setView('list')}><List size={17}/></button><button aria-label="Календарь по месяцам" aria-pressed={view==='month'} onClick={()=>setView('month')}><CalendarDays size={17}/></button></div></div>
 {view==='list'?<ol className="release-calendar-entries release-compact-list">{values.map(x=><li key={x.episode+':'+x.date}>{entry(x)}</li>)}</ol>:date&&<div className="release-month-view"><nav aria-label="Месяц календаря"><button aria-label="Предыдущий месяц" disabled={monthIndex<=0} onClick={()=>setMonth(months[monthIndex-1])}><ChevronLeft size={18}/></button><strong>{date.toLocaleDateString('ru-RU',{month:'long',year:'numeric'})}</strong><button aria-label="Следующий месяц" disabled={monthIndex>=months.length-1} onClick={()=>setMonth(months[monthIndex+1])}><ChevronRight size={18}/></button></nav><div className="release-day-grid">{['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map(d=><small key={d}>{d}</small>)}{Array.from({length:offset},(_,i)=><span key={'blank'+i}/>)}{Array.from({length:days},(_,i)=>{const entries=values.filter(x=>x.date.slice(0,10)===selected+'-'+String(i+1).padStart(2,'0'));return <div key={i} className={entries.length?'has-release':''}>{entries.length?<details><summary aria-label={(i+1)+': '+entries.map(x=>x.title||'Серия '+x.episode).join(', ')}>{i+1}<i/></summary><ul>{entries.map(x=><li key={x.episode}>{entry(x)}</li>)}</ul></details>:<span>{i+1}</span>}</div>;})}</div></div>}
 {!values.length&&!busy&&!error&&<p className="fine">Каталоги пока не предоставили даты серий.</p>}{busy&&<p role="status" className="fine">Получаем даты… {values.length||''}</p>}{error&&<button className="text-link" onClick={()=>setRetry(v=>v+1)}>{error} Повторить</button>}
 <p className="fine">Оригинальные даты выпуска. График выбранной озвучки может отличаться.</p></section>;
}
