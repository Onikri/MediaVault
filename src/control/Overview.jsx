import {motion,useReducedMotion} from 'motion/react';
import {BookOpen,Clapperboard,Headphones,Play} from 'lucide-react';
import {bytes,ago,duration} from '../guest-activity-format.js';
import {useNow,jobCounts,plural} from './use-control-data.js';
import {JOB_NAMES,JOB_TONES,Poster,Timeline,usePosters} from './parts.jsx';

const VERB={manga:'читает',music:'слушает'};
const ICON={manga:BookOpen,music:Headphones};

function OnAir({data,service,onOpen,onOpenRoom}){
 const now=useNow(1000),reduce=useReducedMotion();
 const rooms=data.rooms||[],guests=data.guests||[],activity=data.activity||{};
 const posters=usePosters(service,rooms.map(r=>r.malId));
 const nameOf=id=>guests.find(g=>g.id===id)?.name||'Гость';
 const watching=Object.entries(activity).filter(([,s])=>s.watching).map(([id,s])=>({id,name:nameOf(id),...s.watching}));
 const last=Object.entries(activity).filter(([,s])=>s.lastActive).sort((a,b)=>b[1].lastActive-a[1].lastActive)[0];
 const empty=!rooms.length&&!watching.length;
 return <section className="cc-onair" aria-labelledby="cc-onair-title">
  <div className="cc-section-head"><h2 id="cc-onair-title">В эфире</h2>{!empty&&<span className="cc-hint">{[rooms.length&&rooms.length+' '+plural(rooms.length,'комната','комнаты','комнат'),watching.length&&watching.length+' '+plural(watching.length,'гость','гостя','гостей')+' онлайн'].filter(Boolean).join(', ')}</span>}</div>
  {empty?<div className="cc-quiet"><p>Сейчас никто ничего не смотрит.</p>{last&&<p className="cc-hint">Последним заходил {nameOf(last[0])}, {ago(last[1].lastActive)}.</p>}</div>:
  <ul className="cc-air-list">
   {rooms.map((room,i)=><motion.li key={'room:'+room.id} className="cc-air is-room" initial={reduce?false:{opacity:0,y:10}} animate={{opacity:1,y:0}} transition={{delay:i*.04,duration:.3,ease:[.22,1,.36,1]}}>
    <Poster src={posters[room.malId]?.cover} title={room.title}/>
    <div className="cc-air-body">
     <button type="button" className="cc-air-title" onClick={()=>onOpen('rooms')}><Clapperboard size={15}/><strong>{room.title}</strong></button>
     <Timeline room={room} fetchedAt={data.updatedAt} now={now}/>
     <p className="cc-air-people">{room.members.filter(m=>m.online).map(m=>m.name).join(', ')||'В комнате пока никого'}</p>
    </div>
   </motion.li>)}
   {watching.map((w,i)=>{const Icon=ICON[w.category]||Play;return <motion.li key={'guest:'+w.id} className="cc-air is-guest" initial={reduce?false:{opacity:0,y:10}} animate={{opacity:1,y:0}} transition={{delay:(rooms.length+i)*.04,duration:.3,ease:[.22,1,.36,1]}}>
    <div className="cc-air-body">
     <button type="button" className="cc-air-title" onClick={()=>onOpen('guests')}><Icon size={15}/><strong>{w.name}</strong><span>{VERB[w.category]||'смотрит'}</span></button>
     <p className="cc-air-what">{w.title?'«'+w.title+'»':'тайтл без названия'}</p>
    </div>
    <span className="cc-air-time cc-num">{duration(now/1000-w.since)}</span>
   </motion.li>;})}
  </ul>}
 </section>;
}

function Health({data,service,onOpen}){
 const jobs=jobCounts(service?.jobs),guests=data.guests||[],activity=data.activity||{},rooms=data.rooms||[];
 const online=Object.values(activity).filter(s=>s.watching).length,today=Object.values(activity).reduce((t,s)=>t+(s.bytesToday||0),0);
 const viewers=rooms.reduce((t,r)=>t+r.members.filter(m=>m.online).length,0),limit=data.roomRules?.limit;
 const drive=data.drive,driveTone=drive?.needsConsent?'is-warn':drive?.state==='ready'?'is-ok':'';
 const items=[
  {id:'storage',label:'Сервер',value:data.errors.health?'Не отвечает':data.health?'Работает':'…',tone:data.errors.health?'is-bad':data.health?'is-ok':'',
   detail:data.health?'Версия '+data.health.version+(data.latency!=null?', ответ за '+data.latency+' мс':''):data.errors.health||''},
  {id:'storage',label:'Google Диск на ВМ',value:drive?.needsConsent?'Нужно разрешение':drive?.state==='ready'?'Доступ проверен':drive?.configured?'Не проверен':drive?'Не подключён':'…',tone:driveTone,
   detail:drive?.checkedAt?'Проверен '+ago(drive.checkedAt):'Нужен для фонового импорта'},
  {id:'tasks',label:'Задачи',value:jobs.running?jobs.running+' в работе':jobs.waiting?jobs.waiting+' ждут Google':jobs.queued?jobs.queued+' в очереди':'Очередь пуста',tone:!jobs.running&&jobs.waiting?'is-warn':'',
   detail:[jobs.queued&&jobs.running?'ещё '+jobs.queued+' в очереди':'',jobs.waiting?jobs.waiting+' ждут вход Google':'',jobs.failed?jobs.failed+' прервано':''].filter(Boolean).join(', ')||'Готово: '+jobs.done},
  {id:'guests',label:'Гости',value:guests.length?online+' из '+guests.length+' онлайн':'Нет гостей',tone:online?'is-live':'',detail:'Трафик сегодня '+bytes(today)},
  {id:'rooms',label:'Комнаты',value:rooms.length?rooms.length+(limit?' из '+limit:'')+' '+plural(rooms.length,'открыта','открыты','открыто'):'Закрыты',tone:rooms.some(r=>r.playing)?'is-live':'',
   detail:rooms.length?viewers+' '+plural(viewers,'человек','человека','человек')+' внутри':data.errors.rooms||'Открываются из плеера'},
 ];
 return <section aria-labelledby="cc-health-title">
  <div className="cc-section-head"><h2 id="cc-health-title">Состояние</h2></div>
  <div className="cc-health">{items.map(item=><button type="button" key={item.label} className="cc-health-item" onClick={()=>onOpen(item.id)}>
   <span className="cc-health-label">{item.label}</span>
   <strong className={'cc-health-value '+item.tone}>{item.value}</strong>
   <span className="cc-health-detail">{item.detail}</span>
  </button>)}</div>
 </section>;
}

function Traffic({data,onOpen}){
 const rows=(data.guests||[]).map(g=>({...g,stats:data.activity?.[g.id]||{}})).filter(g=>g.stats.bytesMonth>0).sort((a,b)=>b.stats.bytesMonth-a.stats.bytesMonth).slice(0,6);
 const top=Math.max(1,...rows.map(r=>r.stats.bytesMonth));
 return <section aria-labelledby="cc-traffic-title">
  <div className="cc-section-head"><h2 id="cc-traffic-title">Трафик гостей за 30 дней</h2></div>
  {rows.length?<ul className="cc-bars">{rows.map(r=><li key={r.id}><button type="button" onClick={()=>onOpen('guests')}><span>{r.name}</span><strong className="cc-num">{bytes(r.stats.bytesMonth)}</strong><i style={{'--share':r.stats.bytesMonth/top}}/></button></li>)}</ul>:<p className="cc-hint">Гости ещё ничего не смотрели через сервер.</p>}
 </section>;
}

function RecentJobs({service,onOpen}){
 const jobs=[...(service?.jobs||[])].filter(j=>j.status!=='merged').sort((a,b)=>b.updated-a.updated).slice(0,5);
 return <section aria-labelledby="cc-jobs-title">
  <div className="cc-section-head"><h2 id="cc-jobs-title">Последние задачи</h2>{jobs.length>0&&<button type="button" className="cc-text-button" onClick={()=>onOpen('tasks')}>Все задачи</button>}</div>
  {jobs.length?<ul className="cc-jobs">{jobs.map(j=>{const p=j.progress||{},percent=p.total?Math.min(100,Math.round(((p.saved||0)+(p.skipped||0)+(p.failed||0))/p.total*100)):null;return <li key={j.id}>
   <span className="cc-job-name"><strong>{p.title||'Библиотека'}</strong><small>{p.taskType==='enrich'?'Оформление':'Импорт'}, {ago(j.updated)}</small></span>
   <span className={'cc-job-state '+(JOB_TONES[j.status]||'')}>{JOB_NAMES[j.status]||j.status}{j.status==='running'&&percent!=null?' '+percent+'%':''}</span>
  </li>;})}</ul>:<p className="cc-hint">Задач пока не было. Импорт запускается из каталога.</p>}
 </section>;
}

export default function Overview(props){
 return <div className="cc-overview">
  <OnAir {...props}/>
  <Health {...props}/>
  <div className="cc-split"><Traffic {...props}/><RecentJobs {...props}/></div>
 </div>;
}
