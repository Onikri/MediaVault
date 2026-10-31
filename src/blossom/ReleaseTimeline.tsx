import {useEffect,useRef,useState} from 'react';
import {CalendarDays} from 'lucide-react';
import {jikan} from '../media-metadata.js';
export default function ReleaseTimeline({identity,releases=[],server}:{identity?:string;releases?:any[];server?:string}){
 const root=useRef<HTMLElement>(null),[enabled,setEnabled]=useState(false),[episodes,setEpisodes]=useState<any[]>([]),[busy,setBusy]=useState(false);
 useEffect(()=>{const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setEnabled(true);observer.disconnect();}},{rootMargin:'200px'});if(root.current)observer.observe(root.current);return()=>observer.disconnect();},[]);
 useEffect(()=>{setEpisodes([]);if(!enabled||!/^\d+$/.test(identity||''))return;const abort=new AbortController();setBusy(true);jikan('anime/'+identity+'/episodes',{server,signal:abort.signal}).then(data=>{if(!abort.signal.aborted)setEpisodes((data.data||[]).filter((x:any)=>x.aired).map((x:any)=>({episode:x.mal_id,date:x.aired})));}).catch(()=>{}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});return()=>abort.abort();},[enabled,identity,server]);
 const values=[...new Map([...episodes,...releases].filter(x=>x.date&&Number.isFinite(Date.parse(x.date))).map(x=>[x.episode+':'+x.date,x])).values()].sort((a,b)=>Date.parse(a.date)-Date.parse(b.date));
 const future=values.filter(x=>Date.parse(x.date)>=Date.now()),visible=future.length?future.slice(0,6):values.slice(-6);
 return <section ref={root} id="titleSchedule" className="release-timeline"><div className="section-heading"><h2><CalendarDays size={19}/>Календарь выпуска</h2></div>{visible.length?<div className="release-dates">{visible.map(x=><div key={x.episode+':'+x.date}><time dateTime={x.date}><strong>{new Date(x.date).toLocaleDateString('ru-RU',{day:'numeric',month:'short'})}</strong><small>{new Date(x.date).getFullYear()}</small></time><span>Серия {x.episode}</span><small>{Date.parse(x.date)<Date.now()?'Вышла':'Ожидается'}</small></div>)}</div>:<p className="fine" role="status">{busy?'Загружаем даты серий…':'Каталоги пока не предоставили даты серий.'}</p>}<p className="fine">Даты оригинального выхода. График озвучки может отличаться.</p></section>;
}
