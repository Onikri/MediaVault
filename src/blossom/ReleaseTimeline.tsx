import {useEffect,useRef,useState} from 'react';
import {CalendarDays,ArrowRight} from 'lucide-react';
import {jikan} from '../media-metadata.js';
export default function ReleaseTimeline({identity,releases=[],server}:{identity?:string;releases?:any[];server?:string}){
 const root=useRef<HTMLElement>(null),abort=useRef<AbortController|null>(null),generation=useRef(0);
 const [enabled,setEnabled]=useState(false),[episodes,setEpisodes]=useState<any[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[next,setNext]=useState<number|null>(1),[month,setMonth]=useState('all'),[count,setCount]=useState(12);
 useEffect(()=>{const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setEnabled(true);observer.disconnect();}},{rootMargin:'200px'});if(root.current)observer.observe(root.current);return()=>observer.disconnect();},[]);
 async function load(page:number,version=generation.current){
  abort.current?.abort();const controller=new AbortController();abort.current=controller;setBusy(true);setError('');
  try{const data=await jikan('anime/'+identity+'/episodes',{server,signal:controller.signal,params:{page}});if(controller.signal.aborted||version!==generation.current)return;
   if(!Array.isArray(data.data))throw Error('Некорректный ответ календаря');
   setEpisodes(old=>[...new Map([...old,...data.data.filter((x:any)=>x.aired).map((x:any)=>({episode:x.mal_id,date:x.aired}))].map(x=>[x.episode,x])).values()]);setNext(data.pagination?.has_next_page?page+1:null);
  }catch{if(!controller.signal.aborted)setError('Не удалось загрузить даты серий.');}finally{if(!controller.signal.aborted)setBusy(false);}
 }
 useEffect(()=>{generation.current++;setEpisodes([]);setMonth('all');setCount(12);setNext(1);if(enabled&&/^\d+$/.test(identity||''))load(1,generation.current);return()=>abort.current?.abort();},[enabled,identity,server]);
 const values=[...new Map([...episodes,...releases].filter(x=>x.date&&Number.isFinite(Date.parse(x.date))).map(x=>[String(x.episode),x])).values()].sort((a,b)=>Date.parse(a.date)-Date.parse(b.date));
 const monthOf=(x:any)=>x.date.slice(0,7),months=[...new Set(values.map(monthOf))],filtered=month==='all'?values:values.filter(x=>monthOf(x)===month),visible=filtered.slice(0,count),upcoming=values.find(x=>Date.parse(x.date)>=Date.now());
 return <section ref={root} id="titleSchedule" className="release-timeline release-calendar"><div className="section-heading"><h2><CalendarDays size={19}/>Календарь выпуска</h2><span className="fine">{values.length?values.length+' дат':''}</span></div>
 {upcoming&&<div className="release-next"><span>Ближайшая серия</span><strong>Серия {upcoming.episode}</strong><time dateTime={upcoming.date}>{new Date(upcoming.date).toLocaleDateString('ru-RU',{day:'numeric',month:'long'})}</time><ArrowRight size={16}/></div>}
 {months.length>1&&<nav className="release-months" aria-label="Месяц выпуска"><button aria-pressed={month==='all'} onClick={()=>{setMonth('all');setCount(12);}}>Весь сезон</button>{months.map(m=><button key={m} aria-pressed={month===m} onClick={()=>{setMonth(m);setCount(12);}}>{new Date(m+'-01T12:00:00Z').toLocaleDateString('ru-RU',{month:'long',year:'numeric'})}</button>)}</nav>}
 {visible.length?<ol className="release-calendar-entries">{visible.map(x=><li key={x.episode+':'+x.date} aria-current={x===upcoming?'date':undefined}><span className="release-episode-number">{String(x.episode).padStart(2,'0')}</span><div><strong>Серия {x.episode}</strong><time dateTime={x.date}>{new Date(x.date).toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'})}</time></div><small>{Date.parse(x.date)<Date.now()?'Вышла':'Ожидается'}</small></li>)}</ol>:!busy&&!error&&<p className="fine">Каталоги пока не предоставили даты серий.</p>}
 {filtered.length>visible.length&&<button className="text-link" onClick={()=>setCount(n=>n+12)}>Ещё даты · показано {visible.length} из {filtered.length}</button>}
 {next!==null&&enabled&&<button className="text-link" disabled={busy} onClick={()=>{load(next);setCount(n=>n+12);}}>{busy?'Загружаем даты…':error?'Повторить загрузку':'Загрузить следующие серии'}</button>}{error&&<p className="fine" role="alert">{error}</p>}
 <p className="fine">Оригинальные даты выпуска. График выбранной озвучки может отличаться.</p></section>;
}
