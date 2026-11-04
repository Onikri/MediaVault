import {Play,BookOpen,ChevronRight} from 'lucide-react';
import {readProgress,progressClock} from './playback-progress.js';
import {readReading} from './reading-progress.js';
const dateKey=value=>new Date(value).toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'});
export default function HistoryTimeline({recent,onOpen,renderCover,userId,libraryId}){
 const groups=new Map();for(const record of recent){const date=dateKey(record.entry.at);if(!groups.has(date))groups.set(date,[]);groups.get(date).push(record);}
 return <div className="history-timeline">{[...groups].map(([date,records])=><section key={date}><h2>{date}</h2><div>{records.map(({item})=>{const manga=item.category==='manga',progress=manga?readReading(userId,libraryId,item.id):readProgress(userId,libraryId,item.id);return <button key={item.id} onClick={()=>onOpen(item)} className="history-resume-row"><span className="history-cover">{renderCover(item)}</span><span className="history-copy"><strong>{item.name}</strong><small>{manga?<BookOpen size={12}/>:<Play size={12}/>} {progress?(manga?'Продолжить · страница '+(progress.page+1):'Продолжить · '+progressClock(progress.time)):'Открыть снова'}</small>{progress?.duration>0&&<span className="history-progress"><i style={{width:Math.min(100,progress.time/progress.duration*100)+'%'}}/></span>}</span><ChevronRight size={16}/></button>;})}</div></section>)}</div>;
}
