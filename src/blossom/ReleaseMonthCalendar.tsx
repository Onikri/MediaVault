import {useMemo,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ChevronLeft,ChevronRight} from 'lucide-react';
import './release-month-calendar.css';
import {uiLocale} from '../i18n/index.js';

// One readable month at a time: a release day shows its episode number and
// name in the cell itself, so nothing hides behind a hover.
const pad=(n:number)=>String(n).padStart(2,'0');
const dayKey=(date:Date)=>`${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}`;
const monthKey=(date:Date)=>`${date.getFullYear()}-${pad(date.getMonth()+1)}`;
const local=(value:string)=>{const d=new Date(value);return Number.isNaN(d.getTime())?null:d;};
const WEEK=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
const episodesLabel=(list:any[])=>{const nums=list.map(x=>Number(x.episode)).filter(Number.isFinite).sort((a,b)=>a-b);if(!nums.length)return 'Серия';return nums.length===1?'Серия '+nums[0]:'Серии '+nums[0]+'–'+nums.at(-1);};
function until(date:Date,now:number){
 const days=Math.round((new Date(date).setHours(0,0,0,0)-new Date(now).setHours(0,0,0,0))/864e5);
 if(days<0)return 'Вышла';if(days===0)return 'Сегодня';if(days===1)return 'Завтра';
 return 'Через '+days+' '+(days%10===1&&days%100!==11?'день':days%10>=2&&days%10<=4&&(days%100<12||days%100>14)?'дня':'дней');
}

export default function ReleaseMonthCalendar({entries,renderEntry}:{entries:any[];renderEntry:(entry:any)=>any}){
 const reduce=useReducedMotion(),now=Date.now();
 const byDay=useMemo(()=>{const map=new Map<string,any[]>();for(const entry of entries){const date=local(entry.date);if(!date)continue;const key=dayKey(date);map.set(key,[...(map.get(key)||[]),{...entry,day:date}]);}return map;},[entries]);
 const months=useMemo(()=>{const map=new Map<string,number>();for(const [key,list] of byDay)map.set(key.slice(0,7),(map.get(key.slice(0,7))||0)+list.length);return map;},[byDay]);
 const dates=[...byDay.values()].map(list=>list[0].day as Date).sort((a,b)=>a.getTime()-b.getTime());
 const upcoming=dates.find(d=>new Date(d).setHours(23,59,59)>=now);
 const start=upcoming||dates[0];
 const [month,setMonth]=useState(()=>start?new Date(start.getFullYear(),start.getMonth(),1):new Date());
 const [picked,setPicked]=useState<string>(()=>start?dayKey(start):'');
 const [direction,setDirection]=useState(1);
 if(!dates.length)return null;
 const first=dates[0],last=dates.at(-1)!;
 const years=[...new Set(dates.map(d=>d.getFullYear()))];
 const min=new Date(first.getFullYear(),first.getMonth(),1),max=new Date(last.getFullYear(),last.getMonth(),1);
 function go(next:Date,step=Math.sign(next.getTime()-month.getTime())||1){
  const value=new Date(Math.min(max.getTime(),Math.max(min.getTime(),new Date(next.getFullYear(),next.getMonth(),1).getTime())));
  setDirection(step);setMonth(value);
  const inMonth=dates.find(d=>monthKey(d)===monthKey(value)&&new Date(d).setHours(23,59,59)>=now)||dates.find(d=>monthKey(d)===monthKey(value));
  if(inMonth)setPicked(dayKey(inMonth));
 }
 const offset=(new Date(month.getFullYear(),month.getMonth(),1).getDay()+6)%7,length=new Date(month.getFullYear(),month.getMonth()+1,0).getDate();
 const cells=[...Array(offset).fill(null),...Array.from({length},(_,i)=>new Date(month.getFullYear(),month.getMonth(),i+1))];
 while(cells.length%7)cells.push(null);
 const today=dayKey(new Date()),count=months.get(monthKey(month))||0;
 const pickedList=byDay.get(picked)||[],pickedDate=pickedList[0]?.day as Date|undefined;
 const title=month.toLocaleDateString(uiLocale(),{month:'long',year:'numeric'}).replace(/\s*г\.?$/,'');
 const slide=reduce?{}:{initial:{opacity:0,x:direction*28},animate:{opacity:1,x:0},exit:{opacity:0,x:-direction*28}};
 return <div className="release-board">
  <header className="release-board-head">
   <div className="release-board-title"><h3 aria-live="polite">{title[0].toLocaleUpperCase()+title.slice(1)}</h3><span>{count?count+' '+(count%10===1&&count%100!==11?'серия':count%10>=2&&count%10<=4&&(count%100<12||count%100>14)?'серии':'серий'):'Без серий'}</span></div>
   <div className="release-board-nav">
    <button type="button" aria-label="Предыдущий месяц" disabled={month<=min} onClick={()=>go(new Date(month.getFullYear(),month.getMonth()-1,1),-1)}><ChevronLeft size={18}/></button>
    <button type="button" aria-label="Следующий месяц" disabled={month>=max} onClick={()=>go(new Date(month.getFullYear(),month.getMonth()+1,1),1)}><ChevronRight size={18}/></button>
   </div>
  </header>
  {years.length>1&&<div className="release-board-years" role="group" aria-label="Год календаря">{years.map(year=><button key={year} type="button" aria-pressed={month.getFullYear()===year} onClick={()=>go(new Date(year,month.getFullYear()===year?month.getMonth():(dates.find(d=>d.getFullYear()===year)||first).getMonth(),1))}>{year}</button>)}</div>}
  <div className="release-board-months" role="group" aria-label="Месяц календаря">{Array.from({length:12},(_,i)=>{const date=new Date(month.getFullYear(),i,1),n=months.get(monthKey(date))||0;return <button key={i} type="button" disabled={!n} aria-pressed={i===month.getMonth()} aria-label={date.toLocaleDateString(uiLocale(),{month:'long'})+(n?', серий: '+n:', без серий')} onClick={()=>go(date)}>{date.toLocaleDateString(uiLocale(),{month:'short'}).replace('.','')}{n>0&&<small>{n}</small>}</button>;})}</div>
  <div className="release-board-week" aria-hidden="true">{WEEK.map(d=><span key={d}>{d}</span>)}</div>
  <div className="release-board-stage">
   <AnimatePresence mode="popLayout" initial={false} custom={direction}>
    <motion.div key={monthKey(month)} className="release-board-grid" role="grid" aria-label={'Серии, '+title} {...slide} transition={{type:'spring',stiffness:420,damping:38}}>
     {cells.map((date,i)=>{
      if(!date)return <span key={'gap-'+i} className="release-cell is-empty" aria-hidden="true"/>;
      const key=dayKey(date),list=byDay.get(key)||[],future=new Date(date).setHours(23,59,59)>=now;
      if(!list.length)return <span key={key} role="gridcell" className={'release-cell'+(key===today?' is-today':'')}><b>{date.getDate()}</b></span>;
      const name=list.length===1?list[0].title||list[0].titleRomanji||'':'';
      return <button key={key} type="button" role="gridcell" aria-selected={picked===key} className={'release-cell has-release'+(future?' is-upcoming':'')+(key===today?' is-today':'')} aria-label={date.toLocaleDateString(uiLocale(),{day:'numeric',month:'long'})+': '+episodesLabel(list)+(name?', '+name:'')} onClick={()=>setPicked(key)}>
       <b>{date.getDate()}</b><strong>{episodesLabel(list)}</strong><i className="release-cell-short" aria-hidden="true">{list.length===1?'№'+list[0].episode:list.length+' сер.'}</i>{name&&<em>{name}</em>}<small>{until(date,now)}</small>
      </button>;
     })}
    </motion.div>
   </AnimatePresence>
  </div>
  <AnimatePresence mode="wait" initial={false}>
   {pickedDate&&<motion.section key={picked} className="release-board-day" aria-label="Серии выбранного дня" initial={reduce?false:{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0}} transition={{duration:.2}}>
    <h4>{pickedDate.toLocaleDateString(uiLocale(),{weekday:'long',day:'numeric',month:'long',year:'numeric'})}</h4>
    <ol className="release-calendar-entries">{pickedList.map((entry:any)=><li key={entry.episode}>{renderEntry(entry)}</li>)}</ol>
   </motion.section>}
  </AnimatePresence>
 </div>;
}
